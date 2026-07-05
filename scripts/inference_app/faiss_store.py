"""
faiss_store.py – Global index loading + ephemeral sub-index retrieval.

The corpus is one global FAISS IndexIDMap(IndexFlatIP). To scope a search to a
single document and a chosen set of embedding types, we reconstruct just the
candidate vectors into a small in-memory IndexFlatIP and search that. Kept free
of any Streamlit import so it can be unit-tested with a synthetic index.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Callable, Optional

import faiss
import numpy as np

from .config import EMBEDDING_DIM
from . import db

log = logging.getLogger(__name__)


def load_global_index(index_path: Path) -> faiss.Index:
    """
    Load the global FAISS IDMap(IndexFlatIP) into RAM once.

    Eagerly builds the direct map so per-request reconstruct(id) is an O(1)
    lookup (and so the map is not built lazily/racily on first use under
    concurrent Streamlit sessions).
    """
    index = faiss.read_index(str(index_path))
    try:
        index.make_direct_map()
    except Exception as e:  # some index types build it implicitly
        log.debug("make_direct_map() skipped: %s", e)
    log.info("Loaded global FAISS index: %s (%d vectors)", index_path, index.ntotal)
    return index


def build_subindex(global_index: faiss.Index, faiss_ids: list[int]) -> faiss.IndexFlatIP:
    """
    Reconstruct the given vector ids from the global index and pack them into a
    fresh IndexFlatIP. Local position p in the sub-index corresponds to
    faiss_ids[p], so the caller maps results back through that list.
    """
    sub = faiss.IndexFlatIP(EMBEDDING_DIM)
    if not faiss_ids:
        return sub
    vectors = np.vstack(
        [global_index.reconstruct(int(fid)) for fid in faiss_ids]
    ).astype("float32")
    sub.add(vectors)
    return sub


def search_subindex(
    sub_index: faiss.Index,
    query_vec: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Search a single query row; returns (scores, local_positions) 1×k arrays."""
    q = np.asarray(query_vec, dtype="float32").reshape(1, -1)
    k = min(top_k, sub_index.ntotal)
    if k == 0:
        return np.empty((1, 0), dtype="float32"), np.empty((1, 0), dtype="int64")
    return sub_index.search(q, k)


def retrieve(
    conn: sqlite3.Connection,
    global_index: faiss.Index,
    document_id: int,
    embedding_types: list[str],
    query_vec: np.ndarray,
    top_k: int,
    content_fetcher: Optional[Callable[[sqlite3.Connection, str, int], Optional[dict]]] = None,
) -> list[dict]:
    """
    Full scoped retrieval: candidate ids → sub-index → top-k → dedup by owner →
    content + citation, ranked by score descending.

    Dedup is post-search on (owner_kind, owner_id): when both e.g. table_text
    and table_vl point at the same Table row, only the higher-scoring hit's
    content is kept. This must be done after the search (not before), since we
    cannot know which embedding type scores higher until we search.
    """
    fetch = content_fetcher or db.fetch_owner_content

    rows = db.get_candidate_faiss_ids(conn, document_id, embedding_types)
    if not rows:
        return []

    faiss_ids = [r[0] for r in rows]
    id_to_owner: dict[int, tuple[str, int]] = {r[0]: (r[2], r[3]) for r in rows}

    sub_index = build_subindex(global_index, faiss_ids)
    scores, positions = search_subindex(sub_index, query_vec, top_k)

    # Highest score per (owner_kind, owner_id).
    best: dict[tuple[str, int], float] = {}
    for score, pos in zip(scores[0].tolist(), positions[0].tolist()):
        if pos < 0:
            continue
        owner = id_to_owner[faiss_ids[pos]]
        if owner not in best or score > best[owner]:
            best[owner] = float(score)

    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)

    hits: list[dict] = []
    for (owner_kind, owner_id), score in ranked:
        content = fetch(conn, owner_kind, owner_id)
        if content is None:
            continue
        hits.append({"score": score, **content})
    return hits
