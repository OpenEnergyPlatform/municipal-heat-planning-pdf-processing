"""
app.py – Streamlit RAG chat over a docpipe corpus. The only module that imports
Streamlit.

What the corpus is about comes from the profile: its catalog supplies the
labels, the filters and the detail shown for a selected document.

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
    answer, catalog, chunker, faiss_store, llm_client, query_cache, request_log,
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
        doc_id = st.selectbox(
            cat.document_noun, options=list(by_id),
            format_func=lambda i: by_id[i].label,
        )
        for heading, lines in by_id[doc_id].detail:
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
