"""
app.py – Streamlit RAG chat over a docpipe corpus. The only module that imports
Streamlit.

What the corpus is about comes from the profile: its catalog supplies the
labels, the filters and the detail shown for a selected document. With a
graph configured (INFERENCE_KG_TTL_PATH, the file `--serialize` wrote) a
question goes to the graph first and to the documents only when the graph
says why it has no answer.

Run:
    DOCPIPE_PROFILE=kwp streamlit run scripts/inference_app/app.py \\
        --server.address 0.0.0.0 --server.port 8501

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

from docpipe.inference import (
    answer, catalog, chunker, compare, faiss_store, kg_route, llm_client,
    query_cache, request_log,
)
from docpipe.inference import config as core_config
from docpipe.inference import db
from scripts.inference_app import config, pdf_link

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached resources. The embedding model is deliberately NOT among them: whether
# it stays loaded is the backend's business, and on a card that also serves this
# app the answer is no.
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


@st.cache_resource
def get_catalog():
    """The profile's catalog, or the generic one if no profile is configured."""
    return catalog.load_catalog(config.PROFILE)


@st.cache_resource
def get_graph():
    """The graph `--serialize` wrote, and the trust lines above its nodes."""
    return kg_route.load_graph(config.KG_TTL_PATH)


@st.cache_resource
def get_kg_hooks():
    """What the profile contributes to the graph route; None without a graph."""
    return kg_route.hooks(config.PROFILE)


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
    # Heavy backend imported lazily so a cache-hit turn never touches torch;
    # which backend that is (local model or an endpoint) is configuration.
    from docpipe.embedding import get_embedder
    vec = get_embedder().embed_one(item)
    query_cache.put(cache_conn, cache_key, vec)
    return vec, False


def run_turn(task: str, image_bytes: bytes | None, image_only: bool,
             document_id: int, scopes: list[str], as_json: bool = False,
             history: list | None = None):
    """One turn, with this app's resources and its spinners attached."""
    with _spinner("Vorbereiten"):
        index, id_to_pos = get_index()
    cache_conn = get_cache()

    def _embed(item):
        key = query_cache.make_key(
            "image" if item.get("image") and not item.get("text")
            else ("image+text" if item.get("image") else "text"),
            text=item.get("text"),
            image_bytes=image_bytes if item.get("image") else None,
        )
        return embed_query(item, cache_conn, key)

    corpus = answer.Corpus(
        conn=get_db(), index=index, id_to_pos=id_to_pos, embed=_embed,
        resolve_image=resolve_image_path, log_conn=get_request_log(),
    )
    return answer.answer_question(
        task, corpus, document_id, scopes, image_bytes=image_bytes,
        image_only=image_only, as_json=as_json, history=history,
        progress=_spinner,
    )


def run_comparison(task: str, documents: list, scopes: list[str],
                   as_json: bool = False, histories: dict | None = None):
    """The same question to every selected document, then one comparison.

    No image: an uploaded picture is a query anchor for one document's index,
    and the same crop searched across five plans anchors four of them to
    whatever happens to look similar.
    """
    with _spinner("Vorbereiten"):
        index, id_to_pos = get_index()
    cache_conn = get_cache()

    def _embed(item):
        key = query_cache.make_key("text", text=item.get("text"))
        return embed_query(item, cache_conn, key)

    corpus = answer.Corpus(
        conn=get_db(), index=index, id_to_pos=id_to_pos, embed=_embed,
        resolve_image=resolve_image_path, log_conn=get_request_log(),
    )
    return compare.compare_documents(
        task, corpus, documents, scopes, as_json=as_json,
        histories=histories, progress=_spinner,
    )




def run_kg_turn(task: str, document_id: int) -> dict:
    """One question to the graph; `answer_from_graph` decides everything."""
    graph, comments = get_graph()
    return kg_route.answer_from_graph(
        task, get_kg_hooks(), graph, comments, db_path=config.DB_PATH,
        document=db.document_filename(get_db(), document_id),
        ask=_ask_coordinate)


def _ask_coordinate(task: str, slot):
    """One closed question to the model, over the spec's own list."""
    return llm_client.choose(get_kg_hooks().prompt, task, slot.question,
                             slot.answerable() if slot.is_closed else {})


def _spinner(label: str):
    """A labelled spinner with Streamlit's built-in live elapsed timer."""
    return st.spinner(f"{label} …", show_time=True)




# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main() -> None:
    cat = get_catalog()
    title = config.PROFILE.display_title if config.PROFILE else "docpipe – Recherche"
    st.set_page_config(page_title=title, layout="wide")
    # Hide Streamlit's top-right "running man" status widget.
    st.markdown("<style>[data-testid='stStatusWidget']{display:none !important;}</style>",
                unsafe_allow_html=True)
    st.title(title)

    conn = get_db()

    # ---- Sidebar: document + scopes ----
    with st.sidebar:
        st.header("Auswahl")
        include_old = st.checkbox("Historische Versionen einbeziehen", value=False)
        entries = cat.entries(conn, include_superseded=include_old)
        if not entries:
            st.error("Keine Dokumente in der Datenbank gefunden.")
            st.stop()

        # Filters are whatever the profile declared and its catalog filled; a
        # facet no document carries a value for is not offered at all.
        options = catalog.facet_options(entries, cat.facets)
        selections = {
            facet.field: st.multiselect(facet.label, options[facet.field], default=[])
            for facet in cat.facets if facet.field in options
        }
        entries = catalog.apply_filters(entries, selections)
        if not entries:
            st.warning("Kein Dokument passt zu dieser Filterauswahl.")
            st.stop()

        by_id = {e.id: e for e in entries}
        # Several selected = the same question to each, then a comparison over
        # the answers. Not a joint retrieval: the longest chapter would take
        # every slot in the top-k and the other documents would look silent.
        doc_ids = st.multiselect(
            cat.document_noun, options=list(by_id),
            format_func=lambda i: by_id[i].label,
            default=list(by_id)[:1],
            max_selections=config.COMPARE_MAX_DOCUMENTS,
            help="Mehrere Auswahlen: dieselbe Frage geht an jeden Plan einzeln, "
                 "danach werden nur die Antworten verglichen.",
        )
        if not doc_ids:
            st.warning(f"Bitte mindestens ein {cat.document_noun} wählen.")
            st.stop()
        if len(doc_ids) == 1:
            for heading, lines in by_id[doc_ids[0]].detail:
                with st.expander(heading):
                    st.markdown("\n".join(f"- {line}" for line in lines))
        scopes = st.multiselect(
            "Suchbereich", options=config.ALL_SCOPES, default=config.ALL_SCOPES,
            help="Tabellen/Bilder liegen doppelt im Index: „Bild + Beschreibung“ "
                 "durchsucht das eingebettete Bild samt Beschreibung, "
                 "„nur Beschreibung“ nur den Caption-/Beschreibungstext ohne das Bild.",
        )
        out_fmt = st.radio("Antwortformat", ["Fließtext", "JSON"], horizontal=True)
        as_json = out_fmt == "JSON"
        # The graph first, the documents second. A value node has neither a
        # picture nor a search scope, so the two inputs above apply to the
        # document search only, and the help text says so.
        kg_hooks = get_kg_hooks()
        kg_available = kg_hooks is not None and config.KG_TTL_PATH.is_file()
        route_mode = st.radio(
            "Antwortweg", ["Automatik", "Wissensgraph", "Dokumentsuche"],
            horizontal=True, disabled=not kg_available,
            help="Automatik fragt zuerst den Wissensgraphen und fällt auf die "
                 "Dokumentsuche zurück; Wissensgraph antwortet nur aus dem "
                 "Graphen oder gar nicht. Bild und Suchbereich gelten nur für "
                 "die Dokumentsuche.")
        if not kg_available:
            route_mode = "Dokumentsuche"
        if config.LLM_STUB_MODE:
            st.info("LLM_STUB_MODE aktiv – Antworten sind Platzhalter.")

    # ---- Reset chat when the selection changes ----
    comparing = len(doc_ids) > 1
    doc_id = doc_ids[0]
    if st.session_state.get("doc_ids") != doc_ids:
        st.session_state["doc_ids"] = doc_ids
        st.session_state["chat_history"] = []
        # Follow-up context resets with the selection, and it is kept per
        # document: a re-check has to search past what THAT document already
        # showed, not past what another one did.
        st.session_state["turns_by_doc"] = {}

    history = st.session_state.setdefault("chat_history", [])

    # ---- Render history ----
    for msg in history:
        with st.chat_message(msg["role"]):
            if msg.get("kg_values") is not None:
                _render_kg(msg["kg_values"])
                continue
            if msg.get("rows") is not None:
                _render_comparison(msg)
                continue
            if msg["role"] == "assistant":
                _render_answer(msg["content"], msg.get("as_json", False))
            else:
                st.markdown(msg["content"])
            if msg.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {msg['phrase']}")
            if msg.get("recheck_note"):
                st.caption(msg["recheck_note"])
            if msg.get("route_note"):
                st.caption(msg["route_note"])
            _render_compute(msg.get("compute"))
            for cit in msg.get("citations", []):
                _render_citation(cit)

    # ---- Optional image upload + mode ----
    # The image and this toggle only change how the *query embedding* is formed;
    # the text task always drives the final question answering.
    uploaded = (None if comparing else
                st.file_uploader("Optionales Bild zur Anfrage",
                                 type=["png", "jpg", "jpeg"]))
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

    by_doc = st.session_state.setdefault("turns_by_doc", {})

    if comparing:
        outcome = run_comparison(task, [(i, by_id[i].label) for i in doc_ids],
                                 scopes, as_json=as_json, histories=by_doc)
        with st.chat_message("assistant"):
            _render_comparison(outcome)
        history.append({"role": "assistant", "content": "", **outcome})
        for row in outcome["rows"]:
            _remember(by_doc, row["document_id"], task, row)
        return

    # The graph route, when offered: it answers, or it says why not and the
    # document search runs with that sentence as a caption. Each branch
    # returns, because everything below reads `result`.
    route_note = None
    if route_mode != "Dokumentsuche":
        with _spinner("Wissensgraph"):
            outcome = run_kg_turn(task, doc_id)
        if outcome["route"] == "kg":
            with st.chat_message("assistant"):
                _render_kg(outcome["values"])
            history.append({"role": "assistant", "content": "",
                            "kg_values": outcome["values"], "route": "kg"})
            return
        note = kg_hooks.notes[outcome["reason"]]
        if route_mode == "Wissensgraph":
            # Forced: a graph that says nothing is a finding about the
            # graph, and a silent fallback would hide it.
            with st.chat_message("assistant"):
                st.markdown(note)
            history.append({"role": "assistant", "content": note,
                            "route": "kg_empty"})
            return
        route_note = ("📚 Dokumentsuche, der Wissensgraph hat nicht "
                      "geantwortet: " + note)

    result = run_turn(task, image_bytes, image_only, doc_id, scopes, as_json=as_json,
                      history=by_doc.get(doc_id, []))

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
            if route_note:
                st.caption(route_note)
            _render_compute(result.get("compute"))
            history.append({"role": "assistant", "content": reply, "citations": [],
                            "phrase": result.get("phrase"), "as_json": False,
                            "recheck_note": recheck_note,
                            "route_note": route_note,
                            "compute": result.get("compute", [])})
        else:
            _render_answer(result["answer"], result["as_json"])
            if result.get("phrase"):
                st.caption(f"🔎 Suchanker (Embedding-Phrase): {result['phrase']}")
            if recheck_note:
                st.caption(recheck_note)
            if route_note:
                st.caption(route_note)
            _render_compute(result.get("compute"))
            # Rendered directly (not inside an expander) so each citation can carry
            # its own "Kontext anzeigen" expander without illegal nesting.
            for cit in result["citations"]:
                _render_citation(cit)
            history.append({
                "role": "assistant", "content": result["answer"],
                "citations": result["citations"], "phrase": result.get("phrase"),
                "as_json": result["as_json"], "recheck_note": recheck_note,
                "route_note": route_note,
                "compute": result.get("compute", []),
            })

    _remember(by_doc, doc_id, task, result)


def _remember(by_doc: dict, document_id: int, task: str, result: dict) -> None:
    """Keep this turn as follow-up context for ITS document; no excerpts.

    Failed turns too: "schau noch einmal nach" is asked precisely AFTER a
    failure, and without the failed question in context the anchor is built
    from the literal follow-up words with no referent at all.
    """
    turns = by_doc.setdefault(document_id, [])
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
    by_doc[document_id] = turns[-5:]


def _render_comparison(outcome: dict) -> None:
    """The comparison, then every document's own answer and citations.

    The comparison first because it is what was asked for, and each answer in
    full underneath it because the comparison is the only part of this screen
    that no citation backs: it was written from the answers alone.
    """
    rows = outcome.get("rows") or []
    if outcome.get("dropped"):
        st.warning("Nicht abgefragt (Obergrenze %d): %s"
                   % (config.COMPARE_MAX_DOCUMENTS, ", ".join(outcome["dropped"])))
    if outcome.get("comparison"):
        st.markdown(outcome["comparison"])
        st.caption("⚖️ Vergleich der Antworten, ohne eigene Quellen — die Belege "
                   "stehen bei den einzelnen Antworten.")
    elif outcome.get("answered", 0) < 2:
        st.markdown("Zu wenige belegte Antworten für einen Vergleich.")
    else:
        st.markdown("Der Vergleich konnte nicht erzeugt werden; die Antworten "
                    "der einzelnen Pläne stehen unten.")
    st.dataframe(
        [{"Plan": r["label"], "Antwort": compare.summary(r),
          "Belege": r.get("n_findings", 0)} for r in rows],
        hide_index=True, use_container_width=True)
    for row in rows:
        st.subheader(row["label"])
        if row.get("answer") is None:
            st.markdown("Keine belegbare Information in diesem Plan gefunden."
                        if row.get("n_hits") else
                        "Keine Treffer im gewählten Suchbereich.")
        else:
            _render_answer(row["answer"], outcome.get("as_json", False))
        if row.get("phrase"):
            st.caption(f"🔎 Suchanker (Embedding-Phrase): {row['phrase']}")
        _render_compute(row.get("compute"))
        for cit in row.get("citations", []):
            _render_citation(cit)


def _render_kg(values: list) -> None:
    """The graph's values, each under the trust line the serializer wrote.

    The badge is the LAST comment line above the node and the evidence the
    rest, which is the order evidence_comment writes them in. A C is a
    warning because the profile's own word for it is a review request.
    """
    hooks = get_kg_hooks()
    for value in values:
        st.markdown(f"**{value['number']} {hooks.label(value['unit'])}** · "
                    f"{value['year']} · {hooks.label(value['quantity'])} · "
                    f"{hooks.label(value['aggregation'])}")
        about = [hooks.label(iri) for iri in (value.get("abouts") or "").split()]
        st.caption("🏷 " + " · ".join([value["partLabel"]] + about))
        level = kg_route.trust_level(value["trust"], hooks.prose)
        if level == kg_route.LEVEL_C:
            st.warning(value["trust"])
        elif level == kg_route.LEVEL_B:
            st.caption(value["trust"])
        else:
            st.markdown(value["trust"])
        if value.get("evidence"):
            with st.expander("Beleg anzeigen"):
                st.markdown("\n".join(f"- {line}" for line in value["evidence"]))


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
