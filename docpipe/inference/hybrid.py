"""
hybrid.py: One ranking out of two searches, over one document or all.

The chat used to search one document by meaning. Two things were missing:
a search over the whole corpus, and a search by word for the questions a
vector is weak at (`lexical.py` says why). This module is both.

    by meaning   the query vector against the passages' vectors: the
                 document's own sub-index as before, or the global index
                 when no document is named
    by word      the question's words against the word index, where there
                 is one

and the two rankings merged by reciprocal rank: a passage's score is the
sum of 1 / (60 + its rank) over the searches that found it. Ranks, not
scores, because a cosine and a BM25 number share no scale; 60 is the
constant of the method's paper and nothing here was tuned on it.

Without a word index, or for a question that is an image, the result is
the search by meaning alone, in its order and with its scores: what the
chat did before.

Over the whole corpus only the current version of a document answers. An
older version of the same plan would otherwise put two numbers for one
place into one answer.

Author: Felix Vossel
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Optional

import numpy as np

from . import db, faiss_store, lexical

RRF_K = 60
# The global search returns vectors, several per passage and of every
# kind; this many times top_k are asked for so that top_k passages of the
# wanted kinds are among them.
OVERFETCH = 8
MAX_FETCH = 4096
# Ids looked up in one statement: under the number of values every build
# of SQLite lets a statement carry.
LOOKUP = 500


def kinds_of(embedding_types) -> list:
    """section | table | figure for a list of embedding types."""
    found = []
    for name in embedding_types:
        kind = str(name).split("_", 1)[0]
        if kind in lexical.KINDS and kind not in found:
            found.append(kind)
    return found


def current_documents(conn: sqlite3.Connection) -> Optional[set]:
    """The ids of the documents that are the current version of their
    work, or None for a database that does not record versions."""
    try:
        return {row[0] for row in conn.execute(
            'SELECT "id" FROM "Documents" WHERE "is_current" = 1')}
    except sqlite3.OperationalError:
        return None


def dense_corpus(conn: sqlite3.Connection, global_index, embedding_types,
                 query_vec, top_k: int, *, exclude: Optional[set] = None,
                 content_fetcher: Optional[Callable] = None) -> list:
    """The best passages of the whole corpus by meaning, as content dicts
    with their score, best first, one per passage."""
    fetch = content_fetcher or db.fetch_owner_content
    wanted = set(embedding_types)
    current = current_documents(conn)
    total = int(getattr(global_index, "ntotal", 0))
    if not total or not wanted or top_k <= 0:
        return []
    query = np.asarray(query_vec, dtype="float32").reshape(1, -1)
    asked = min(total, MAX_FETCH, max(top_k * OVERFETCH, top_k))
    hits: list = []
    while True:
        scores, ids = global_index.search(query, asked)
        pairs = [(float(score), int(faiss_id)) for score, faiss_id
                 in zip(scores[0].tolist(), ids[0].tolist()) if faiss_id >= 0]
        owners: dict = {}
        found = [faiss_id for _score, faiss_id in pairs]
        for start in range(0, len(found), LOOKUP):
            part = found[start:start + LOOKUP]
            marks = ",".join("?" * len(part))
            for faiss_id, kind_name, owner_kind, owner_id in conn.execute(
                    'SELECT "faiss_id", "embedding_type", "owner_kind", '
                    f'"owner_id" FROM "Embeddings" WHERE "faiss_id" IN ({marks})',
                    part):
                if kind_name in wanted:
                    owners[int(faiss_id)] = (str(owner_kind), int(owner_id))
        best: dict = {}
        for score, faiss_id in pairs:
            owner = owners.get(faiss_id)
            if owner is None or (exclude and owner in exclude):
                continue
            if owner not in best or score > best[owner]:
                best[owner] = score
        hits = []
        for owner, score in sorted(best.items(), key=lambda item: -item[1]):
            content = fetch(conn, *owner)
            if content is None:
                continue
            if current is not None \
                    and content.get("document_id") not in current:
                continue
            hits.append({"score": score, **content})
            if len(hits) == top_k:
                break
        if len(hits) >= top_k or asked >= min(total, MAX_FETCH):
            return hits
        asked = min(total, MAX_FETCH, asked * 4)


def fuse(rankings: list) -> list:
    """[(key, score)] best first, from several rankings of keys. A key's
    score is the sum of 1 / (RRF_K + rank) over the rankings that hold it;
    equal scores keep the order of the first ranking that held them."""
    scores: dict = {}
    first: dict = {}
    for order, ranking in enumerate(rankings):
        for rank, key in enumerate(ranking, 1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            first.setdefault(key, (order, rank))
    return sorted(scores.items(), key=lambda item: (-item[1], first[item[0]]))


def retrieve(conn: sqlite3.Connection, global_index, id_to_pos: dict,
             document_id: Optional[int], embedding_types: list, query_vec,
             top_k: int, *, text: Optional[str] = None,
             lexical_index: Optional[sqlite3.Connection] = None,
             exclude: Optional[set] = None,
             content_fetcher: Optional[Callable] = None) -> list:
    """The passages to answer from, best first.

    *document_id* None searches the whole corpus. *text* is what the word
    index is asked; without it, or without *lexical_index*, the result is
    the search by meaning alone. Every hit is a content dict with `score`;
    a merged hit also says where each search ranked it (`dense_rank`,
    `lexical_rank`, None where that search did not find it).
    """
    fetch = content_fetcher or db.fetch_owner_content
    if document_id is None:
        dense = dense_corpus(conn, global_index, embedding_types, query_vec,
                             top_k, exclude=exclude, content_fetcher=fetch)
    else:
        more = {"content_fetcher": content_fetcher} if content_fetcher else {}
        dense = faiss_store.retrieve(
            conn, global_index, id_to_pos, document_id, embedding_types,
            query_vec, top_k, exclude=exclude, **more)
    if lexical_index is None or not (text or "").strip():
        return dense
    # More than top_k are asked for, as of the vectors: what was examined
    # before and what an older version of a document says is taken out
    # afterwards, and would otherwise use up the places.
    found = lexical.search(lexical_index, text, document=document_id,
                           kinds=kinds_of(embedding_types),
                           limit=top_k * OVERFETCH + len(exclude or ()))
    current = current_documents(conn) if document_id is None else None
    worded = [(kind, owner) for kind, owner, document in found
              if not (exclude and (kind, owner) in exclude)
              and (current is None or document in current)][:top_k]
    if not worded:
        return dense
    by_owner = {(hit["owner_kind"], hit["owner_id"]): hit for hit in dense}
    dense_order = list(by_owner)
    merged = []
    for owner, score in fuse([dense_order, worded]):
        hit = by_owner.get(owner)
        if hit is None:
            content = fetch(conn, *owner)
            if content is None:
                continue
            hit = dict(content)
        merged.append({
            **hit, "score": score,
            "dense_rank": dense_order.index(owner) + 1
            if owner in by_owner else None,
            "lexical_rank": worded.index(owner) + 1
            if owner in worded else None})
        if len(merged) == top_k:
            break
    return merged
