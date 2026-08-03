"""
app.py – Streamlit RAG chat over the KWP knowledge base. The only module that
imports Streamlit.

Run:
    streamlit run scripts/inference_app/app.py --server.address 0.0.0.0 --server.port 8501

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import sys
import tempfile
import time
from pathlib import Path

# The bundled pdf.js viewer is served as ES modules; some Python installs don't
# map .mjs → a JS MIME type, and browsers refuse to execute modules served as
# octet-stream.
mimetypes.add_type("text/javascript", ".mjs")

# `streamlit run` executes this file as a top-level script (no package context),
# so relative imports would fail — import the package absolutely off the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from scripts.inference_app import (
    config, db, faiss_store, query_cache, chunker, llm_client, pdf_link, code_exec,
    request_log,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached resources. The embedding model is deliberately NOT cached here — see
# quantized_embedder.load_embedder.
# ---------------------------------------------------------------------------
@st.cache_resource
def get_index():
    """Returns (faiss_index, id_to_pos) — loaded once, held in RAM."""
    return faiss_store.load_global_index(config.INDEX_PATH)


@st.cache_resource
def get_db():
    return db.connect_readonly(config.DB_PATH)


@st.cache_resource
def get_cache():
    return query_cache.connect(config.QUERY_CACHE_PATH)


@st.cache_resource
def get_request_log():
    return request_log.connect(config.REQUEST_LOG_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def resolve_image_path(stored_path: str | None) -> Path | None:
    """Best-effort resolution of a Tables/Images `path` to an on-disk file."""
    if not stored_path:
        return None
    candidates = [Path(stored_path), config.IMAGE_ROOT / stored_path]
    for c in candidates:
        if c.exists():
            return c
    return None


def embed_query(item: dict, cache_conn, cache_key: str):
    """Return the query vector, from cache or a fresh on-demand embed."""
    cached = query_cache.get(cache_conn, cache_key)
    if cached is not None:
        log.info("Query cache hit (%s)", cache_key[:12])
        return cached, True
    # Heavy backend imported lazily so a cache-hit turn never touches torch.
    from scripts.inference_app.quantized_embedder import embed_query as _embed
    vec = _embed(
        item,
        model_name=config.EMBEDDING_MODEL,
        max_length=config.EMBEDDING_MAX_TOKEN_LENGTH,
        timeout_s=config.EMBED_LOCK_TIMEOUT_S,
        idle_unload_seconds=config.EMBED_IDLE_UNLOAD_SECONDS,
    )
    query_cache.put(cache_conn, cache_key, vec)
    return vec, False


def run_turn(task: str, image_bytes: bytes | None, image_only: bool,
             document_id: int, scopes: list[str], as_json: bool = False,
             history: list | None = None):
    """
    Execute one full retrieval + answer turn. Returns a dict with:
    answer (str|None), answer_text (str|None), citations (list[dict]),
    n_findings (int), cache_hit (bool), n_hits (int), phrase (str|None),
    as_json (bool), n_batches (int), compute (list).

    answer is None when nothing was retrieved or nothing could be grounded.
    """
    result = {"answer": None, "answer_text": None, "citations": [], "n_findings": 0,
              "cache_hit": False, "n_hits": 0, "phrase": None, "as_json": as_json,
              "n_batches": 0, "compute": [], "examined": [], "recheck": False,
              "n_excluded": 0}

    start_time = time.time()
    conn = get_db()
    cache_conn = get_cache()
    log_conn = get_request_log()

    with _spinner("Vorbereiten"):
        index, id_to_pos = get_index()

    # --- 1) build the query item + cache key, per mode ---
    tmp_path = None
    recheck = False
    if image_bytes is not None and image_only:
        mode = "image"
        tmp_path = _write_temp_image(image_bytes)
        item = {"image": tmp_path}
        phrase = None
        cache_key = query_cache.make_key(mode, image_bytes=image_bytes)
    elif image_bytes is not None:
        mode = "image+text"
        with _spinner("🔎 Suchanker (Bild+Text)"):
            phrase, recheck = llm_client.make_search_phrase(task, visual=True, history=history)
        tmp_path = _write_temp_image(image_bytes)
        item = {"text": phrase, "image": tmp_path}
        cache_key = query_cache.make_key(mode, text=phrase, image_bytes=image_bytes)
    else:
        mode = "text"
        visual_anchor = _scopes_are_visual(scopes)
        with _spinner("🔎 Suchanker"):
            phrase, recheck = llm_client.make_search_phrase(task, visual=visual_anchor, history=history)
        item = {"text": phrase}
        cache_key = query_cache.make_key(mode, text=phrase)
    result["phrase"] = phrase
    result["recheck"] = recheck

    # A re-check ("schau noch einmal nach") searches PAST the sources earlier
    # attempts already examined — otherwise it re-reads the same top sources and
    # can only repeat itself. Walk back through the whole re-check chain to the
    # original question, or the second re-check resurfaces the first turn's
    # sources.
    exclude = set()
    if recheck:
        for turn in reversed(history or []):
            exclude.update((k, i) for k, i in turn.get("examined", []))
            if not turn.get("recheck"):
                break
    result["n_excluded"] = len(exclude)

    # --- 2) embed (cache or on-demand model load) ---
    with _spinner("🧮 Embedding"):
        query_vec, cache_hit = embed_query(item, cache_conn, cache_key)
    result["cache_hit"] = cache_hit
    if tmp_path:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    # --- 3) scoped retrieval ---
    with _spinner("📚 Suche"):
        embedding_types = [t for s in scopes for t in config.SCOPE_TO_EMBEDDING_TYPES[s]]
        hits = faiss_store.retrieve(
            conn, index, id_to_pos, document_id, embedding_types, query_vec, config.TOP_K,
            exclude=exclude,
        )
    result["n_hits"] = len(hits)
    if not hits:
        latency_ms = (time.time() - start_time) * 1000
        request_log.log_request(
            log_conn, document_id, task or phrase or "", mode, scopes,
            latency_ms=latency_ms, n_hits=0, error_message="No hits", cache_hit=False
        )
        return result

    # --- 4) answer across the top sources in context-safe batches; a further
    #        batch runs only while the answer is still incomplete ---
    top_hits = hits[: config.MAX_CHUNK_ATTEMPTS]
    batches = chunker.pack_chunks(top_hits, config.ANSWER_CONTEXT_TOKENS, tokenizer=None)
    citations, seen = [], set()
    prior_text = None
    off_envelope = False
    examined = set()
    with _spinner("🔍 Antwort aus den Quellen"):
        for bi, chunk in enumerate(batches, start=1):
            items = chunk.items
            # Sources the LLM actually reads this turn; a later re-check of the
            # same question searches past exactly these.
            examined.update((top_hits[it["index"]]["owner_kind"],
                             top_hits[it["index"]]["owner_id"]) for it in items)
            # Attach the table/figure crops so values that exist only in a chart
            # can be read off the image (capped; downscaled in llm_client).
            images = {}
            for it in items:
                if len(images) >= config.ANSWER_MAX_IMAGES:
                    break
                img = resolve_image_path(top_hits[it["index"]].get("image_path"))
                if img is not None:
                    images[it["index"]] = str(img)
            # Text answer during batching; JSON formatting happens once at the end.
            code_ctx = _code_context(items, top_hits) if code_exec.is_enabled() else None
            out = llm_client.answer_from_sources(
                task, items, prior=prior_text, as_json=False,
                code_runner=(code_exec.run_code if code_exec.is_enabled() else None),
                code_context=code_ctx, max_compute=config.CODE_EXEC_MAX_ROUNDS,
                history=history, images=images or None)
            result["compute"].extend(out.get("compute") or [])
            off_envelope = off_envelope or bool(out.get("off_envelope"))
            attached = set(out.get("attached_images") or [])
            item_by_index = {it["index"]: it for it in items}
            for s in out.get("supports", []):
                try:
                    idx = int(s.get("index"))
                except (TypeError, ValueError):
                    continue
                it = item_by_index.get(idx)
                if it is None or not (0 <= idx < len(top_hits)):
                    continue
                if s.get("bild"):
                    # Read off an attached crop: no verbatim quote can exist, the
                    # validated substitute is the reading + the flagged rendering.
                    quote = llm_client.visual_reading(s, attached)
                    visual = True
                else:
                    quote = llm_client.grounded_quote(s.get("quote", ""), it)
                    visual = False
                if quote is None:
                    continue
                hit = top_hits[idx]
                key = (hit["owner_kind"], hit["owner_id"])
                if key in seen:
                    continue
                seen.add(key)
                citations.append({**hit, "quote": quote, "visual": visual})
            if out.get("found"):
                prior_text = out.get("answer")
            result["n_batches"] = bi
            if out.get("complete") and citations:
                break     # fully answered → don't scan the remaining batches
    result["examined"] = sorted(examined)

    # Re-read every image-derived value in a focused single-image call and fold
    # the results into the answer. The big call above only IDENTIFIES which
    # figure carries the answer; with ten sources and several charts in one
    # prompt it misreads (returned a stack's total height as one segment).
    visual_cits = [c for c in citations if c.get("visual")]
    if visual_cits and prior_text:
        readings = []
        with _spinner("🔬 Ablesung präzisieren"):
            for cit in visual_cits[: config.READOFF_MAX_CALLS]:
                img = resolve_image_path(cit.get("image_path"))
                if img is None:
                    continue
                ro = llm_client.read_off_image(task, str(img), cit["quote"])
                if ro:
                    cit["quote"] = ro["ablesung"]
                    readings.append(f"{chunker.citation_label(cit)}: {ro['ablesung']}")
            if readings:
                prior_text = llm_client.revise_with_readings(task, prior_text, readings)

    # Deterministic marking of read-off values: the prompt asks for the phrase,
    # but only this guarantees it. In JSON output the schema may leave no room
    # for it — there the flagged citation below the answer is the channel.
    if prior_text and any(c.get("visual") for c in citations) \
            and "abgelesen" not in prior_text:
        prior_text = (prior_text.rstrip()
                      + "\n\n(Hinweis: Werte teilweise aus Abbildungen abgelesen "
                        "– Schätzwerte, Ablesefehler möglich.)")
    if not citations or not prior_text:      # nothing grounded → refuse (anti-hallucination)
        latency_ms = (time.time() - start_time) * 1000
        # An off-envelope reply is a model failure, not an absent fact — logging
        # both as "no citations" makes the two indistinguishable after the fact.
        request_log.log_request(
            log_conn, document_id, task or phrase or "", mode, scopes,
            latency_ms=latency_ms, n_hits=result["n_hits"],
            error_message=("Answer ignored the response envelope" if off_envelope
                           else "No grounded citations"),
            cache_hit=False
        )
        return result

    # --- 5) final answer (format to JSON once at the end, if requested) ---
    result["answer_text"] = prior_text          # prose answer, for follow-up context
    if as_json:
        with _spinner("🧩 Als JSON"):
            result["answer"] = llm_client.format_as_json(task, prior_text)
    else:
        result["answer"] = prior_text
    result["citations"] = citations
    result["n_findings"] = len(citations)

    # --- 6) log + cache the response (successful case only) ---
    latency_ms = (time.time() - start_time) * 1000
    answer_hash = hashlib.sha256((result["answer"] or "").encode()).hexdigest()[:12]
    request_log.log_request(
        log_conn, document_id, task or phrase or "", mode, scopes,
        latency_ms=latency_ms, n_hits=result["n_hits"], n_citations=result["n_findings"],
        answer_hash=answer_hash, cache_hit=False
    )
    return result


def _scopes_are_visual(scopes: list[str]) -> bool:
    """True if the query targets ONLY figure/table scopes → caption-style anchor."""
    return bool(scopes) and all(s in config.VISUAL_SCOPES for s in scopes)


def _code_context(items: list[dict], top_hits: list[dict]) -> dict:
    """Sandbox context for a batch: its table sources as {caption, markdown}."""
    tables = []
    for it in items:
        idx = it.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(top_hits)):
            continue
        hit = top_hits[idx]
        if hit.get("owner_kind") == "table" and (hit.get("text") or "").strip():
            tables.append({"caption": hit.get("title") or "", "markdown": hit.get("text") or ""})
    return {"tables": tables}


def _spinner(label: str):
    """A labelled spinner with Streamlit's built-in live elapsed timer."""
    return st.spinner(f"{label} …", show_time=True)


def _write_temp_image(image_bytes: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="kwp_query_")
    with os.fdopen(fd, "wb") as f:
        f.write(image_bytes)
    return path


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="KWP RAG Chat", layout="wide")
    # Hide Streamlit's top-right "running man" status widget.
    st.markdown("<style>[data-testid='stStatusWidget']{display:none !important;}</style>",
                unsafe_allow_html=True)
    st.title("Kommunale Wärmeplanung – Recherche")

    conn = get_db()

    # ---- Sidebar: document + scopes ----
    with st.sidebar:
        st.header("Auswahl")
        include_old = st.checkbox("Historische Versionen einbeziehen", value=False)
        docs = db.list_documents(conn, include_superseded=include_old)
        if not docs:
            st.error("Keine Dokumente in der Datenbank gefunden.")
            st.stop()

        coverage = db.municipality_coverage(conn, docs)
        labels = {d["id"]: db.document_label(d, coverage.get(d["id"])) for d in docs}
        doc_id = st.selectbox(
            "Wärmeplan", options=[d["id"] for d in docs],
            format_func=lambda i: labels[i],
        )
        covered = coverage.get(doc_id, [])
        if len(covered) > 1:
            with st.expander(f"🏘 Zugehörige Gemeinden ({len(covered)})"):
                st.markdown("\n".join(f"- {m}" for m in covered))
        scopes = st.multiselect(
            "Suchbereich", options=config.ALL_SCOPES, default=config.ALL_SCOPES,
            help="Tabellen/Bilder liegen doppelt im Index: „Bild + Beschreibung“ "
                 "durchsucht das eingebettete Bild samt Beschreibung, "
                 "„nur Beschreibung“ nur den Caption-/Beschreibungstext ohne das Bild.",
        )
        out_fmt = st.radio("Antwortformat", ["Fließtext", "JSON"], horizontal=True)
        as_json = out_fmt == "JSON"
        if config.LLM_STUB_MODE:
            st.info("LLM_STUB_MODE aktiv – Antworten sind Platzhalter.")

    # ---- Reset chat when the document changes ----
    if st.session_state.get("doc_id") != doc_id:
        st.session_state["doc_id"] = doc_id
        st.session_state["chat_history"] = []
        st.session_state["turns"] = []          # follow-up context resets with the document

    history = st.session_state.setdefault("chat_history", [])

    # ---- Render history ----
    for msg in history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                _render_answer(msg["content"], msg.get("as_json", False))
            else:
                st.markdown(msg["content"])
            if msg.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {msg['phrase']}")
            if msg.get("recheck_note"):
                st.caption(msg["recheck_note"])
            _render_compute(msg.get("compute"))
            for cit in msg.get("citations", []):
                _render_citation(cit)

    # ---- Optional image upload + mode ----
    # The image and this toggle only change how the *query embedding* is formed;
    # the text task always drives the final question answering.
    uploaded = st.file_uploader("Optionales Bild zur Anfrage", type=["png", "jpg", "jpeg"])
    image_only = False
    if uploaded is not None:
        image_only = st.radio(
            "Bild fürs Retrieval verwenden als",
            options=["Bild + Text", "Nur Bild"], horizontal=True,
        ) == "Nur Bild"

    # ---- Chat input (always required: it is the extraction task for the LLM) ----
    task = st.chat_input("Extraktionsauftrag …")
    if not task:
        return

    if not scopes:
        st.warning("Bitte mindestens einen Suchbereich wählen.")
        return

    image_bytes = uploaded.getvalue() if uploaded is not None else None

    # Echo the user turn
    user_text = task if uploaded is None else f"{task}  \n_(mit Bild)_"
    history.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    result = run_turn(task, image_bytes, image_only, doc_id, scopes, as_json=as_json,
                      history=st.session_state.get("turns", []))

    recheck_note = None
    if result.get("recheck"):
        recheck_note = (f"🔁 Wiederholungssuche – {result['n_excluded']} bereits "
                        f"geprüfte Quellen übersprungen")

    # Compose assistant reply
    with st.chat_message("assistant"):
        if result["answer"] is None:
            if result["n_hits"] == 0:
                reply = ("Alle passenden Quellen wurden bereits geprüft."
                         if result.get("recheck") and result.get("n_excluded")
                         else "Keine Treffer im gewählten Suchbereich.")
            else:
                reply = ("In den geprüften Quellen wurde keine belegbare Information "
                         "zum Auftrag gefunden.")
            st.markdown(reply)
            if result.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {result['phrase']}")
            if recheck_note:
                st.caption(recheck_note)
            _render_compute(result.get("compute"))
            history.append({"role": "assistant", "content": reply, "citations": [],
                            "phrase": result.get("phrase"), "as_json": False,
                            "recheck_note": recheck_note,
                            "compute": result.get("compute", [])})
        else:
            _render_answer(result["answer"], result["as_json"])
            if result.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {result['phrase']}")
            if recheck_note:
                st.caption(recheck_note)
            _render_compute(result.get("compute"))
            # Rendered directly (not inside an expander) so each citation can carry
            # its own "Kontext anzeigen" expander without illegal nesting.
            for cit in result["citations"]:
                _render_citation(cit)
            history.append({
                "role": "assistant", "content": result["answer"],
                "citations": result["citations"], "phrase": result.get("phrase"),
                "as_json": result["as_json"], "recheck_note": recheck_note,
                "compute": result.get("compute", []),
            })

    # Remember this turn for follow-ups; no document excerpts are retained.
    # Failed turns too: "schau noch einmal nach" is asked precisely AFTER a
    # failure, and without the failed question in context the anchor is built
    # from the literal follow-up words with no referent at all.
    turns = st.session_state.setdefault("turns", [])
    turns.append({
        "task": task, "phrase": result.get("phrase"),
        "answer": result.get("answer_text") or result.get("answer")
                  or "(keine belegte Antwort gefunden)",
        # (owner_kind, owner_id) of the sources the LLM read this turn — a
        # re-check searches past these instead of re-reading them. The flag
        # marks chain membership, so a second re-check excludes the whole chain.
        "examined": result.get("examined", []),
        "recheck": result.get("recheck", False),
    })
    st.session_state["turns"] = turns[-5:]


def _render_compute(compute: list | None) -> None:
    """Show the code the model ran in the sandbox + its output."""
    if not compute:
        return
    with st.expander(f"🧮 Berechnung anzeigen ({len(compute)}×)"):
        for step in compute:
            st.code(step.get("code", ""), language="python")
            out = step.get("output") or {}
            if out.get("ok"):
                txt = (out.get("stdout") or "").strip() or "(keine Ausgabe)"
            else:
                txt = "Fehler: " + (out.get("error") or (out.get("stderr") or "").strip() or "?")
            st.text(txt[:2000])


def _render_answer(answer: str, as_json: bool) -> None:
    """Render the assistant answer: pretty JSON (interactive, code fallback) or prose."""
    if as_json:
        try:
            st.json(json.loads(answer))
        except (ValueError, TypeError):
            st.code(answer, language="json")
    else:
        st.markdown(answer)


def _pdf_link_for(cit: dict):
    """
    (url, page) deep link into the source PDF for a citation, or None if no PDF
    area is configured, the filename is unknown, or no page could be resolved.
    """
    prefix = config.PDF_URL_PREFIX
    if not prefix:
        return None
    conn = get_db()
    filename = db.document_filename(conn, cit.get("document_id"))
    if not filename:
        return None
    page = cit.get("page_number")
    phrase = None
    rects = None
    quote = cit.get("quote")
    if cit.get("owner_kind") == "section" and quote and cit.get("owner_id"):
        loc = pdf_link.locate_quote(quote, db.section_segments(conn, cit["owner_id"]))
        if loc:
            page, phrase = loc            # exact page (+ a fallback phrase)
        if page:
            # Per-line rects of the quote itself, so ONLY the cited passage is
            # boxed. Drawn by pdfjs_overlay.js.
            rects = pdf_link.best_quote_rects(config.PDF_ROOT / filename, page, quote)
            if not rects:
                pdf_phrase = pdf_link.best_search_phrase(config.PDF_ROOT / filename, page, quote)
                if pdf_phrase:
                    phrase = pdf_phrase
    if not page:
        return None
    if config.PDF_VIEWER_PREFIX:      # bundled pdf.js → highlight in every browser
        url = pdf_link.pdf_viewer_url(config.PDF_VIEWER_PREFIX, prefix, filename,
                                      page, phrase, rects)
    else:                             # native browser viewer (no overlay; phrase only)
        url = pdf_link.pdf_page_url(prefix, filename, page, phrase)
    return url, page


def _render_citation(cit: dict) -> None:
    """Render one citation: source label, quote, expandable context, image.

    Must NOT be called inside another st.expander (Streamlit forbids nesting the
    context expander below).
    """
    label = chunker.citation_label(cit)
    st.caption(f"📄 {label}")
    quote = cit.get("quote")
    if quote:
        st.markdown("> " + str(quote).replace("\n", " "))
    if cit.get("visual"):
        st.caption("📷 Aus der Abbildung abgelesen – Schätzwert, Ablesefehler möglich")
    link = _pdf_link_for(cit)
    if link:
        url, page = link
        st.link_button(f"📄 Seite {page} im PDF öffnen", url)
    context = (cit.get("text") or "").strip()
    if context:
        with st.expander("Kontext anzeigen"):
            body = context
            if quote and str(quote) in body:
                body = body.replace(str(quote), f"**{quote}**", 1)
            st.markdown(body)
    img = resolve_image_path(cit.get("image_path"))
    if img is not None:
        st.image(str(img))


if __name__ == "__main__":
    main()
