"""
faiss_store.py – Global index loading + ephemeral sub-index retrieval.

The corpus is one global FAISS IndexIDMap(IndexFlatIP). A search is scoped to a
document + a set of embedding types by reconstructing just the candidate vectors
into a small in-memory IndexFlatIP and searching that.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Callable, Optional

import faiss
import numpy as np

from docpipe.embedding.config import EMBEDDING_DIM
from . import db

log = logging.getLogger(__name__)


def load_global_index(index_path: Path) -> tuple[faiss.Index, dict[int, int]]:
    """
    Load the global FAISS index into RAM, with a dict mapping each stored
    faiss_id → its internal position.

    The dict is needed because an IndexIDMap does NOT support reconstruct(id);
    a vector is pulled back out by inverting the position→id table (`id_map`)
    and reconstructing by position on the wrapped flat index — see
    reconstruct_vector().
    """
    index = faiss.read_index(str(index_path))
    id_to_pos = _build_id_to_pos(index)
    log.info("Loaded global FAISS index: %s (%d vectors)", index_path, index.ntotal)
    return index, id_to_pos


def _build_id_to_pos(index: faiss.Index) -> dict[int, int]:
    """Map each original faiss_id → its internal position in the index."""
    try:
        id_array = faiss.vector_to_array(index.id_map)  # position -> original id
    except Exception:
        # Not an IndexIDMap (e.g. a plain flat index): identity mapping.
        return {i: i for i in range(index.ntotal)}
    return {int(fid): pos for pos, fid in enumerate(id_array)}


def reconstruct_vector(global_index: faiss.Index, id_to_pos: dict[int, int], faiss_id: int):
    """Reconstruct one stored vector by its original faiss_id."""
    inner = getattr(global_index, "index", global_index)  # wrapped IndexFlatIP
    return inner.reconstruct(int(id_to_pos[int(faiss_id)]))


def build_subindex(
    global_index: faiss.Index,
    id_to_pos: dict[int, int],
    faiss_ids: list[int],
) -> faiss.IndexFlatIP:
    """
    Reconstruct the given vector ids from the global index and pack them into a
    fresh IndexFlatIP.

    Local position p in the sub-index corresponds to faiss_ids[p]; the caller
    maps results back through that list. Every id in `faiss_ids` MUST be present
    in `id_to_pos`.
    """
    sub = faiss.IndexFlatIP(EMBEDDING_DIM)
    if not faiss_ids:
        return sub
    vectors = np.vstack(
        [reconstruct_vector(global_index, id_to_pos, fid) for fid in faiss_ids]
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


def retrieve_many(
    conn: sqlite3.Connection,
    global_index: faiss.Index,
    id_to_pos: dict[int, int],
    document_id: int,
    embedding_types: list[str],
    query_vecs,
    top_k: int,
    content_fetcher: Optional[Callable[[sqlite3.Connection, str, int], Optional[dict]]] = None,
    exclude: Optional[set] = None,
) -> list[list[dict]]:
    """Many probes against ONE sub-index. Same results as retrieve() per probe.

    build_subindex reconstructs every candidate vector of the document, and a
    sweep asks that document some sixty questions per round: rebuilding the
    same sub-index for each of them was the whole cost of planning a document.
    Here the candidate ids are read once, the sub-index is built once, and FAISS
    is handed the probes as one query matrix — which is what its search() has
    always taken.

    The per-probe exclusion is reproduced exactly, not approximated. Callers
    ran the probes in order and grew the excluded set as each one answered, so
    that is what happens here, inside one call: `taken` starts as `exclude` and
    every probe's answers join it. Searching the unfiltered sub-index and
    skipping excluded rows afterwards gives the same rows as filtering first,
    because dropping rows from an exact flat index cannot reorder the rest.
    """
    fetch = content_fetcher or db.fetch_owner_content

    rows = db.get_candidate_faiss_ids(conn, document_id, embedding_types)
    rows = [r for r in rows if r[0] in id_to_pos]
    probes = list(query_vecs)
    if not rows or not probes:
        return [[] for _ in probes]

    faiss_ids = [r[0] for r in rows]
    id_to_owner: dict[int, tuple[str, int]] = {r[0]: (r[2], r[3]) for r in rows}
    sub_index = build_subindex(global_index, id_to_pos, faiss_ids)

    queries = np.asarray(probes, dtype="float32").reshape(len(probes), -1)
    # The full ranking, not top_k: a later probe has to be able to reach past
    # everything the earlier ones took. On a flat index every score is computed
    # anyway, so asking for all of them costs the sort, not the search.
    scores, positions = sub_index.search(queries, sub_index.ntotal)

    taken: set = set(exclude or ())
    out: list[list[dict]] = []
    for row_scores, row_positions in zip(scores.tolist(), positions.tolist()):
        best: dict[tuple[str, int], float] = {}
        kept = 0
        for score, pos in zip(row_scores, row_positions):
            if pos < 0:
                continue
            owner = id_to_owner[faiss_ids[pos]]
            if owner in taken:
                continue
            # Dedup happens POST-search on the owner: table_text and table_vl
            # point at one Table row, and which scores higher is not known
            # until the search is done.
            if owner not in best or score > best[owner]:
                best[owner] = float(score)
            kept += 1
            if kept == top_k:
                break
        hits: list[dict] = []
        for (owner_kind, owner_id), score in sorted(
                best.items(), key=lambda kv: kv[1], reverse=True):
            content = fetch(conn, owner_kind, owner_id)
            if content is None:
                continue
            hits.append({"score": score, **content})
        taken.update(best)
        out.append(hits)
    return out


def retrieve(
    conn: sqlite3.Connection,
    global_index: faiss.Index,
    id_to_pos: dict[int, int],
    document_id: int,
    embedding_types: list[str],
    query_vec: np.ndarray,
    top_k: int,
    content_fetcher: Optional[Callable[[sqlite3.Connection, str, int], Optional[dict]]] = None,
    exclude: Optional[set] = None,
) -> list[dict]:
    """
    Full scoped retrieval: candidate ids → sub-index → top-k → dedup by owner →
    content + citation, ranked by score descending. Empty list if nothing matches.

    `exclude` drops candidates whose (owner_kind, owner_id) is in the set — used
    by re-check turns to search past the sources an earlier attempt already
    examined.

    Dedup must happen POST-search on (owner_kind, owner_id): when e.g. table_text
    and table_vl point at the same Table row, only the higher-scoring hit is
    kept, and which type scores higher is not known until the search is done.
    """
    fetch = content_fetcher or db.fetch_owner_content

    rows = db.get_candidate_faiss_ids(conn, document_id, embedding_types)
    # Only ids actually present in the index: guards against DB/index drift and
    # keeps the local-position ↔ faiss_id mapping below exact.
    rows = [r for r in rows if r[0] in id_to_pos]
    if exclude:
        rows = [r for r in rows if (r[2], r[3]) not in exclude]
    if not rows:
        return []

    faiss_ids = [r[0] for r in rows]
    id_to_owner: dict[int, tuple[str, int]] = {r[0]: (r[2], r[3]) for r in rows}

    sub_index = build_subindex(global_index, id_to_pos, faiss_ids)
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
