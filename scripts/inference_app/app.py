"""
app.py – Streamlit RAG chat over the KWP knowledge base.

The only module that imports Streamlit. Wires together: document picker + scope
selection (sidebar), a chat box with an optional image upload, on-demand
embedding of the query, scoped sub-index retrieval, and the iterative chunk-by-
chunk LLM question answering with citations.

Run:
    streamlit run scripts/inference_app/app.py --server.address 0.0.0.0 --server.port 8501

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# `streamlit run scripts/inference_app/app.py` executes this file as a top-level
# script (no package context), so relative imports would fail. Put the repo root
# (.../ above scripts/) on sys.path and import the package absolutely.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from scripts.inference_app import config, db, faiss_store, query_cache, chunker, llm_client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached resources (RAM is abundant; only the embedding model's VRAM is scarce,
# and that is deliberately NOT cached — see quantized_embedder.load_embedder).
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
             document_id: int, scopes: list[str], as_json: bool = False):
    """
    Execute one full retrieval + answer turn. Returns a dict with:
    answer (str|None), citations (list[dict]), n_findings (int), cache_hit (bool),
    n_hits (int), phrase (str|None), as_json (bool), timings (dict).

    Each sub-step runs under its own timed st.spinner. The top sources are handed
    to the LLM in a SINGLE call, so it sees every source together — fewest calls,
    it picks the right source, and info spread across several is combined in one
    pass. Every statement is validated against a verbatim quote from its cited
    source (grounding); an answer with no grounded support is refused.
    """
    result = {"answer": None, "citations": [], "n_findings": 0, "cache_hit": False,
              "n_hits": 0, "phrase": None, "as_json": as_json, "timings": {},
              "n_batches": 0}
    timings = result["timings"]

    conn = get_db()
    cache_conn = get_cache()
    with _timed_spinner("Vorbereiten", timings):
        index, id_to_pos = get_index()

    # --- 1) build the query item + cache key, per mode ---
    tmp_path = None
    if image_bytes is not None and image_only:
        mode = "image"
        tmp_path = _write_temp_image(image_bytes)
        item = {"image": tmp_path}
        phrase = None
        cache_key = query_cache.make_key(mode, image_bytes=image_bytes)
    elif image_bytes is not None:
        mode = "image+text"
        # visual anchor: a figure/diagram-style caption matches figures better.
        with _timed_spinner("🔎 Suchanker (Bild+Text)", timings):
            phrase = llm_client.make_search_phrase(task, visual=True)
        tmp_path = _write_temp_image(image_bytes)
        item = {"text": phrase, "image": tmp_path}
        cache_key = query_cache.make_key(mode, text=phrase, image_bytes=image_bytes)
    else:
        mode = "text"
        # A figure/table-only search wants a caption-style anchor, not prose.
        visual_anchor = _scopes_are_visual(scopes)
        with _timed_spinner("🔎 Suchanker", timings):
            phrase = llm_client.make_search_phrase(task, visual=visual_anchor)
        item = {"text": phrase}
        cache_key = query_cache.make_key(mode, text=phrase)
    result["phrase"] = phrase

    # --- 2) embed (cache or on-demand model load) ---
    with _timed_spinner("🧮 Embedding", timings):
        query_vec, cache_hit = embed_query(item, cache_conn, cache_key)
    result["cache_hit"] = cache_hit
    if tmp_path:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    # --- 3) scoped retrieval ---
    with _timed_spinner("📚 Suche", timings):
        embedding_types = [t for s in scopes for t in config.SCOPE_TO_EMBEDDING_TYPES[s]]
        hits = faiss_store.retrieve(
            conn, index, id_to_pos, document_id, embedding_types, query_vec, config.TOP_K
        )
    result["n_hits"] = len(hits)
    if not hits:
        return result

    # --- 4) answer across the top sources in context-safe BATCHES. Usually ONE
    #        call; a further batch runs only while the answer is still incomplete,
    #        so no source is dropped (no truncation). Every statement keeps an
    #        exact, verbatim-quote reference to its source. ---
    top_hits = hits[: config.MAX_CHUNK_ATTEMPTS]
    batches = chunker.pack_chunks(top_hits, config.ANSWER_CONTEXT_TOKENS, tokenizer=None)
    citations, seen = [], set()
    prior_text = None
    with _timed_spinner("🔍 Antwort aus den Quellen", timings):
        for bi, chunk in enumerate(batches, start=1):
            items = chunk.items
            # text answer during batching; JSON formatting happens once at the end
            out = llm_client.answer_from_sources(task, items, prior=prior_text, as_json=False)
            item_by_index = {it["index"]: it for it in items}
            for s in out.get("supports", []):
                try:
                    idx = int(s.get("index"))
                except (TypeError, ValueError):
                    continue
                it = item_by_index.get(idx)
                if it is None or not (0 <= idx < len(top_hits)):
                    continue
                gq = llm_client.grounded_quote(s.get("quote", ""), it)
                if gq is None:
                    continue
                hit = top_hits[idx]
                key = (hit["owner_kind"], hit["owner_id"])
                if key in seen:
                    continue
                seen.add(key)
                citations.append({**hit, "quote": gq})
            if out.get("found"):
                prior_text = out.get("answer")
            result["n_batches"] = bi
            if out.get("complete") and citations:
                break     # fully answered → don't scan the remaining batches
    if not citations or not prior_text:      # nothing grounded → refuse (anti-hallucination)
        return result

    # --- 5) final answer (format to JSON once at the end, if requested) ---
    if as_json:
        with _timed_spinner("🧩 Als JSON", timings):
            result["answer"] = llm_client.format_as_json(task, prior_text)
    else:
        result["answer"] = prior_text
    result["citations"] = citations
    result["n_findings"] = len(citations)
    return result


def _scopes_are_visual(scopes: list[str]) -> bool:
    """True if the query targets ONLY figure/table scopes → caption-style anchor."""
    return bool(scopes) and all(s in config.VISUAL_SCOPES for s in scopes)


@contextmanager
def _timed_spinner(label: str, timings: dict):
    """st.spinner (with live elapsed timer) that also records its wall-time."""
    t0 = time.perf_counter()
    with st.spinner(f"{label} …", show_time=True):
        yield
    timings[label] = time.perf_counter() - t0


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
    # Hide Streamlit's top-right "running man" status widget (not wanted).
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
        # Which municipalities this plan covers (convoys cover several) — clickable.
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
            _render_timings(msg.get("timings"))
            for cit in msg.get("citations", []):
                _render_citation(cit)

    # ---- Optional image upload + mode ----
    # The text task always drives the final question answering; the image (if
    # any) and this toggle only change how the *query embedding* is formed.
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

    # Run pipeline
    result = run_turn(task, image_bytes, image_only, doc_id, scopes, as_json=as_json)

    # Compose assistant reply
    with st.chat_message("assistant"):
        if result["answer"] is None:
            if result["n_hits"] == 0:
                reply = "Keine Treffer im gewählten Suchbereich."
            else:
                reply = ("In den geprüften Quellen wurde keine belegbare Information "
                         "zum Auftrag gefunden.")
            st.markdown(reply)
            if result.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {result['phrase']}")
            _render_timings(result.get("timings"))
            history.append({"role": "assistant", "content": reply, "citations": [],
                            "phrase": result.get("phrase"), "as_json": False,
                            "timings": result.get("timings")})
        else:
            _render_answer(result["answer"], result["as_json"])
            if result.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {result['phrase']}")
            _render_timings(result.get("timings"))
            # Rendered directly (not inside an expander) so each citation can carry
            # its own "Kontext anzeigen" expander without illegal nesting.
            for cit in result["citations"]:
                _render_citation(cit)
            history.append({
                "role": "assistant", "content": result["answer"],
                "citations": result["citations"], "phrase": result.get("phrase"),
                "as_json": result["as_json"], "timings": result.get("timings"),
            })


def _render_timings(timings: dict | None) -> None:
    """Small caption with the per-phase durations and total (⏱)."""
    if not timings:
        return
    parts = [f"{k} {v:.0f}s" for k, v in timings.items()]
    st.caption("⏱ " + "  ·  ".join(parts) + f"  ·  gesamt {sum(timings.values()):.0f}s")


def _render_answer(answer: str, as_json: bool) -> None:
    """Render the assistant answer: pretty JSON (interactive, code fallback) or prose."""
    if as_json:
        try:
            st.json(json.loads(answer))
        except (ValueError, TypeError):
            st.code(answer, language="json")
    else:
        st.markdown(answer)


def _render_citation(cit: dict) -> None:
    """Render one citation: source label, verbatim quote, expandable full context, image.

    Must NOT be called inside another st.expander (Streamlit forbids nesting the
    context expander below).
    """
    label = chunker.citation_label(cit)
    st.caption(f"📄 {label}")
    quote = cit.get("quote")
    if quote:
        st.markdown("> " + str(quote).replace("\n", " "))
    context = (cit.get("text") or "").strip()
    if context:
        with st.expander("Kontext anzeigen"):
            body = context
            # Best-effort: emphasise the exact quote within its full context.
            if quote and str(quote) in body:
                body = body.replace(str(quote), f"**{quote}**", 1)
            st.markdown(body)
    img = resolve_image_path(cit.get("image_path"))
    if img is not None:
        st.image(str(img))


if __name__ == "__main__":
    main()
