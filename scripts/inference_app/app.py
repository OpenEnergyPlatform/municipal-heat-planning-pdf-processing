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

import logging
import os
import sys
import tempfile
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
             document_id: int, scopes: list[str]):
    """
    Execute one full retrieval + QA turn. Returns a dict with keys:
    answer (str|None), citations (list[dict]), n_chunks_tried (int),
    cache_hit (bool), n_hits (int), phrase (str|None).

    All sub-steps run inside a single st.status so there is one continuously
    animated progress indicator for the whole turn (search phrase → embedding →
    retrieval → source-by-source QA) with no dead gap where the UI looks frozen.

    Retrieved hits are checked ONE AT A TIME, so the source shown for an answer
    is exactly the one the LLM used — no guessing from multi-hit source_refs.
    """
    result = {"answer": None, "citations": [], "n_chunks_tried": 0,
              "cache_hit": False, "n_hits": 0, "phrase": None}

    with st.status("Anfrage wird bearbeitet …", expanded=False) as status:
        conn = get_db()
        cache_conn = get_cache()
        status.update(label="Index wird geladen …")
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
            status.update(label="Suchphrase wird erzeugt …")
            phrase = llm_client.make_search_phrase(task)
            tmp_path = _write_temp_image(image_bytes)
            item = {"text": phrase, "image": tmp_path}
            cache_key = query_cache.make_key(mode, text=phrase, image_bytes=image_bytes)
        else:
            mode = "text"
            status.update(label="Suchphrase wird erzeugt …")
            phrase = llm_client.make_search_phrase(task)
            item = {"text": phrase}
            cache_key = query_cache.make_key(mode, text=phrase)
        result["phrase"] = phrase

        # --- 2) embed (cache or on-demand model load) ---
        status.update(label="Embedding wird berechnet (Modell lädt ggf.) …")
        query_vec, cache_hit = embed_query(item, cache_conn, cache_key)
        result["cache_hit"] = cache_hit
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

        # --- 3) scoped retrieval ---
        status.update(label="Passende Stellen werden gesucht …")
        embedding_types = [t for s in scopes for t in config.SCOPE_TO_EMBEDDING_TYPES[s]]
        hits = faiss_store.retrieve(
            conn, index, id_to_pos, document_id, embedding_types, query_vec, config.TOP_K
        )
        result["n_hits"] = len(hits)
        if not hits:
            status.update(label="Keine Treffer im gewählten Suchbereich.", state="complete")
            return result

        # --- 4) source-by-source QA: first hit that answers IS the cited source ---
        top_hits = hits[: config.MAX_CHUNK_ATTEMPTS]
        for attempt, hit in enumerate(top_hits, start=1):
            result["n_chunks_tried"] = attempt
            status.update(label=f"Quelle {attempt}/{len(top_hits)} wird geprüft …")
            answer = llm_client.ask_chunk(task, [chunker.format_hit(attempt - 1, hit)])
            if answer.get("found"):
                result["answer"] = answer["answer"]
                result["citations"] = [hit]          # exactly the source that answered
                status.update(label=f"Antwort in Quelle {attempt} gefunden.", state="complete")
                return result

        status.update(label=f"In {len(top_hits)} Quellen keine Antwort gefunden.",
                      state="complete")
    return result


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

        labels = {d["id"]: db.document_label(d) for d in docs}
        doc_id = st.selectbox(
            "Wärmeplan", options=[d["id"] for d in docs],
            format_func=lambda i: labels[i],
        )
        scopes = st.multiselect(
            "Suchbereich", options=config.ALL_SCOPES, default=config.ALL_SCOPES,
        )
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
            st.markdown(msg["content"])
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
    result = run_turn(task, image_bytes, image_only, doc_id, scopes)

    # Compose assistant reply
    with st.chat_message("assistant"):
        if result["answer"] is None:
            if result["n_hits"] == 0:
                reply = "Keine Treffer im gewählten Suchbereich."
            else:
                reply = (f"Antwort im gewählten Bereich nicht gefunden "
                         f"({result['n_chunks_tried']} Auszüge geprüft).")
            st.markdown(reply)
            history.append({"role": "assistant", "content": reply, "citations": []})
        else:
            st.markdown(result["answer"])
            with st.expander("Quellen"):
                for cit in result["citations"]:
                    _render_citation(cit)
            history.append({
                "role": "assistant", "content": result["answer"],
                "citations": result["citations"],
            })


def _render_citation(cit: dict) -> None:
    """Render one citation (source label + optional image)."""
    label = chunker.citation_label(cit)
    st.caption(f"📄 {label}")
    img = resolve_image_path(cit.get("image_path"))
    if img is not None:
        st.image(str(img))


if __name__ == "__main__":
    main()
