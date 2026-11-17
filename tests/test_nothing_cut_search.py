"""The search of the chat and the harvest loses no passage to the pieces of
the index (owner decision 2026-11-17: "Nichts kürzen, einfach ggf. clever
aufteilen und darauf achten, dass die Zuordnung ... nicht verloren gehen").

The promises, each with a case that breaks it by construction:

1. A search for top_k hits gives top_k distinct owners, AND an owner that has
   more pieces than top_k does not use up the places of the others
   (`faiss_store.retrieve`, `rank_prepared`, `fuse_prepared`).
2. A window or frame the reranker could not learn is not kept, AND it is
   asked again after the interval of the chat window, AND a frame of 0 from
   a failed probe is never stored.
3. `pieces_of` tells a database of format 1 by its columns and gives {}
   only then, AND every other database error raises.
"""
from __future__ import annotations

import sqlite3

import faiss
import numpy as np
import pytest

from docpipe import rules
from docpipe import window as windows
from docpipe.inference import db as inference_db
from docpipe.inference import faiss_store, rerank


# -- 1: top_k counts owners ---------------------------------------------------------

# owner -> its vectors; one owner (1) has more pieces than top_k.
VECTORS = {
    1: [[1.0, 0.0], [0.99, 0.1], [0.98, 0.2], [0.97, 0.2]],
    2: [[0.5, 0.5]],
    3: [[0.4, 0.6]],
}


@pytest.fixture
def corpus(monkeypatch):
    monkeypatch.setattr(faiss_store, "EMBEDDING_DIM", 2)
    rows, vectors = [], []
    for owner, vecs in VECTORS.items():
        for vec in vecs:
            rows.append((len(rows), "section_text", "section", owner))
            vectors.append(vec)
    index = faiss.IndexIDMap(faiss.IndexFlatIP(2))
    index.add_with_ids(np.array(vectors, dtype=np.float32),
                       np.arange(len(vectors), dtype=np.int64))
    monkeypatch.setattr(inference_db, "get_candidate_faiss_ids",
                        lambda conn, document_id, types: list(rows))
    conn = sqlite3.connect(":memory:")       # no piece column: format 1
    conn.execute('CREATE TABLE "Embeddings" ("faiss_id" INTEGER)')

    def fetch(_conn, kind, owner):
        return {"owner_kind": kind, "owner_id": owner}
    return conn, index, faiss_store._build_id_to_pos(index), fetch


def test_retrieve_gives_top_k_owners_not_top_k_vectors(corpus):
    conn, index, id_to_pos, fetch = corpus
    hits = faiss_store.retrieve(conn, index, id_to_pos, 0, ["section_text"],
                                np.array([1.0, 0.0]), 3,
                                content_fetcher=fetch)
    assert [h["owner_id"] for h in hits] == [1, 2, 3]


def test_retrieve_with_fewer_owners_than_top_k_returns_them_all(corpus):
    conn, index, id_to_pos, fetch = corpus
    hits = faiss_store.retrieve(conn, index, id_to_pos, 0, ["section_text"],
                                np.array([1.0, 0.0]), 10,
                                content_fetcher=fetch)
    assert sorted(h["owner_id"] for h in hits) == [1, 2, 3]


def test_rank_prepared_counts_owners_against_top_k(corpus):
    conn, index, id_to_pos, fetch = corpus
    prepared = faiss_store.prepare_document(conn, index, id_to_pos, 0,
                                            ["section_text"])
    scores, positions = faiss_store.search_prepared(
        prepared, [np.array([1.0, 0.0])])
    out = faiss_store.rank_prepared(conn, prepared, scores, positions, 3,
                                    content_fetcher=fetch)
    assert [h["owner_id"] for h in out[0]] == [1, 2, 3]
    # The owners taken by the first probe are not given to the second.
    scores, positions = faiss_store.search_prepared(
        prepared, [np.array([1.0, 0.0]), np.array([1.0, 0.0])])
    out = faiss_store.rank_prepared(conn, prepared, scores, positions, 2,
                                    content_fetcher=fetch)
    assert [h["owner_id"] for h in out[0]] == [1, 2]
    assert [h["owner_id"] for h in out[1]] == [3]


def test_fuse_prepared_cuts_by_owners(corpus):
    conn, index, id_to_pos, fetch = corpus
    prepared = faiss_store.prepare_document(conn, index, id_to_pos, 0,
                                            ["section_text"])
    scores, positions = faiss_store.search_prepared(
        prepared, [np.array([1.0, 0.0])])
    with rules.overlaid(sentence_top=2, search_kinds=["section"],
                        search_full_ranking=False, sentence_fusion="max"):
        hits = faiss_store.fuse_prepared(conn, prepared, scores, positions,
                                         0, content_fetcher=fetch)
    assert sorted(h["owner_id"] for h in hits) == [1, 2]


# -- 2: a failed window is not kept ---------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(rerank, "_WINDOWS", {})
    monkeypatch.setattr(rerank, "_ASKED", {})
    monkeypatch.setattr(windows, "server_counter", lambda *a, **k: None)
    state = {"limit": None, "calls": 0}

    def served_limit(*args, **kwargs):
        state["calls"] += 1
        return state["limit"]
    monkeypatch.setattr(windows, "served_limit", served_limit)
    return state


KEY = ("http://r", "m")


def _again():
    """The interval of the chat window has passed."""
    rerank._ASKED[KEY] -= 1000.0


def _post(tokens=7):
    return lambda body: {"usage": {"prompt_tokens": tokens}}


def test_a_failed_limit_is_asked_again_after_the_interval(served):
    assert rerank.window_for("http://r", "m", "", _post()) is None
    assert KEY not in rerank._WINDOWS
    served["limit"] = 4096
    # Within the interval it is not asked at all.
    assert rerank.window_for("http://r", "m", "", _post()) is None
    assert served["calls"] == 1
    _again()
    made = rerank.window_for("http://r", "m", "", _post())
    assert made is not None and made.limit == 4096 and made.frame == 7
    # Learned whole, it is kept and asked no more.
    assert rerank.window_for("http://r", "m", "", _post()) is made
    assert served["calls"] == 2


def test_a_failed_frame_probe_is_never_kept_as_a_frame_of_zero(served):
    served["limit"] = 4096

    def broken(body):
        raise OSError("probe failed")
    assert rerank.window_for("http://r", "m", "", broken) is None
    assert KEY not in rerank._WINDOWS
    _again()
    assert rerank.window_for("http://r", "m", "", _post(0)) is None
    _again()
    made = rerank.window_for("http://r", "m", "", _post(9))
    assert made is not None and made.frame == 9


# -- 3: pieces_of tells format 1 by its columns -----------------------------------------

def test_format_1_database_gives_no_pieces():
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "Embeddings" ("faiss_id" INTEGER PRIMARY KEY, '
                 '"embedding_type" TEXT, "owner_kind" TEXT, "owner_id" INT)')
    assert inference_db.pieces_of(conn, [1, 2]) == {}


def test_format_2_database_gives_its_pieces():
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "Embeddings" ("faiss_id" INTEGER PRIMARY KEY, '
                 '"embedding_type" TEXT, "owner_kind" TEXT, "owner_id" INT, '
                 '"piece" INT, "part" INT, "page" INT, "first_line" INT, '
                 '"last_line" INT)')
    conn.execute("INSERT INTO Embeddings VALUES (1, 'section_text', "
                 "'section', 5, 2, 0, 3, 4, 6)")
    assert inference_db.pieces_of(conn, [1])[1]["piece"] == 2


class Locked:
    """A connection whose statements fail as a locked database does; with
    *columns* its table has the piece column, so only the query fails."""

    def __init__(self, columns=None):
        self.columns = columns

    def execute(self, sql, params=()):
        if self.columns is not None and sql.startswith("PRAGMA"):
            return _Rows([(0, name) for name in self.columns])
        raise sqlite3.OperationalError("database is locked")


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_another_database_error_raises_not_format_1():
    with pytest.raises(sqlite3.OperationalError):
        inference_db.pieces_of(Locked(), [1])
    with pytest.raises(sqlite3.OperationalError):
        inference_db.pieces_of(Locked(["faiss_id", "piece"]), [1])
