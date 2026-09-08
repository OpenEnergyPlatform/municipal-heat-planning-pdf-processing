"""retrieve_many must answer exactly what retrieve answered, probe by probe.

The batched form exists because build_subindex reconstructs every candidate
vector of a document and the sweep used to call it once per probe — sixty-four
times a round, four rounds, per document. Whether that rewrite is safe is one
question only: does it return the same thing? So this compares the two against
a real (small) index rather than asserting the shape of the new one.
"""
import conftest

conftest.needs_real("faiss")

import numpy as np
import pytest

faiss = pytest.importorskip("faiss")

from docpipe.embedding.config import EMBEDDING_DIM
from docpipe.inference import db, faiss_store

N = 40


def _fixture(monkeypatch):
    rng = np.random.default_rng(7)
    vectors = rng.normal(size=(N, EMBEDDING_DIM)).astype("float32")
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    inner = faiss.IndexFlatIP(EMBEDDING_DIM)
    index = faiss.IndexIDMap(inner)
    ids = np.arange(100, 100 + N).astype("int64")
    index.add_with_ids(vectors, ids)

    # Two embedding rows per owner for half of them, which is the case dedup
    # exists for: table_text and table_vl point at one Table row.
    rows = [(int(ids[i]), "section_text", "section", 1000 + i // 2)
            for i in range(N)]
    monkeypatch.setattr(db, "get_candidate_faiss_ids",
                        lambda conn, doc, types: list(rows))
    monkeypatch.setattr(db, "fetch_owner_content",
                        lambda conn, kind, oid: {"owner_kind": kind,
                                                 "owner_id": oid, "text": "t"})
    id_to_pos = {int(fid): pos for pos, fid in enumerate(ids)}
    probes = rng.normal(size=(6, EMBEDDING_DIM)).astype("float32")
    probes /= np.linalg.norm(probes, axis=1, keepdims=True)
    return index, id_to_pos, probes


def _sequential(index, id_to_pos, probes, top_k, exclude):
    """What the sweep did: one call per probe, growing the excluded set."""
    seen = set(exclude)
    out = []
    for probe in probes:
        hits = faiss_store.retrieve(None, index, id_to_pos, 7, [], probe,
                                    top_k, exclude=set(seen))
        seen.update((h["owner_kind"], h["owner_id"]) for h in hits)
        out.append(hits)
    return out


@pytest.mark.parametrize("top_k", [1, 3, 8])
def test_batched_retrieval_matches_probe_by_probe(monkeypatch, top_k):
    index, id_to_pos, probes = _fixture(monkeypatch)
    expected = _sequential(index, id_to_pos, probes, top_k, set())
    got = faiss_store.retrieve_many(None, index, id_to_pos, 7, [],
                                    list(probes), top_k)
    assert [[(h["owner_id"], round(h["score"], 5)) for h in row] for row in got] \
        == [[(h["owner_id"], round(h["score"], 5)) for h in row] for row in expected]


def test_batched_retrieval_honours_a_prior_exclusion(monkeypatch):
    index, id_to_pos, probes = _fixture(monkeypatch)
    exclude = {("section", 1000), ("section", 1001), ("section", 1002)}
    expected = _sequential(index, id_to_pos, probes, 4, exclude)
    got = faiss_store.retrieve_many(None, index, id_to_pos, 7, [],
                                    list(probes), 4, exclude=exclude)
    assert [[h["owner_id"] for h in row] for row in got] \
        == [[h["owner_id"] for h in row] for row in expected]
    assert not any(("section", h["owner_id"]) in exclude
                   for row in got for h in row)


def test_no_probes_and_no_candidates_are_both_empty(monkeypatch):
    index, id_to_pos, probes = _fixture(monkeypatch)
    assert faiss_store.retrieve_many(None, index, id_to_pos, 7, [], [], 5) == []
    monkeypatch.setattr(db, "get_candidate_faiss_ids", lambda *a: [])
    assert faiss_store.retrieve_many(None, index, id_to_pos, 7, [],
                                     list(probes), 5) == [[]] * len(probes)
