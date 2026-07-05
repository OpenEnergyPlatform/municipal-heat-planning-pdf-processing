"""
Tests for the inference_app read-side + pure-logic helpers.

Covers db.py (candidate-faiss-id UNION + content/citation lookup), chunker.py
(token-budget packing + citation labels), and query_cache.py (round-trip +
key derivation). Streamlit / FAISS / torch paths are exercised on the server,
not here.
"""
import sqlite3

import pytest

from scripts.inference_app import db, chunker, query_cache
from scripts.inference_app import config as C


# ---------------------------------------------------------------------------
# Fixture: a small populated corpus on top of the shared kwp_db schema fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def corpus(kwp_db):
    db_path, con = kwp_db
    con.executescript(
        """
        INSERT INTO OrganisationUnits (id, name, state) VALUES (1, 'Landkreis X', 'BW');
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (1, 'Musterstadt', 12345, 1);
        UPDATE Documents SET organisation_unit = 1, published = '20240101',
            municipality_ags = 12345, is_current = 1 WHERE id = 1;

        INSERT INTO Sections (id, document, section_number, title, content, page_number)
            VALUES (1, 1, 0, 'Wärmebedarf', 'Der Wärmebedarf betrug 100 GWh.', 12),
                   (2, 1, 1, 'Potenziale',  'Fernwärme und Wärmepumpen.',       20);

        INSERT INTO Tables (id, section, block_id, path, page_number, caption, markdown)
            VALUES (1, 1, 'p12_tbl0', 'images/p12_tbl0.png', 12, 'Energieträger', '| a | b |');

        INSERT INTO Images (id, section, block_id, path, page_number, caption, description)
            VALUES (1, 2, 'p20_img0', 'images/p20_img0.png', 20, 'Wärmekarte', 'Eine Karte.');

        INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, owner_id) VALUES
            (100, 'section_text',  'section', 1),
            (101, 'section_title', 'section', 1),
            (102, 'section_text',  'section', 2),
            (103, 'section_title', 'section', 2),
            (200, 'table_text',    'table',   1),
            (201, 'table_vl',      'table',   1),
            (300, 'figure_text',   'figure',  1),
            (301, 'figure_vl',     'figure',  1);
        """
    )
    con.commit()
    con.close()
    return db_path


# ---------------------------------------------------------------------------
# db.py
# ---------------------------------------------------------------------------
def test_connect_readonly_rejects_writes(corpus):
    conn = db.connect_readonly(corpus)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO Sections (document, section_number) VALUES (1, 99)")


def test_candidate_ids_headings_only(corpus):
    conn = db.connect_readonly(corpus)
    rows = db.get_candidate_faiss_ids(conn, 1, ["section_title"])
    assert {r[0] for r in rows} == {101, 103}
    # returns (faiss_id, embedding_type, owner_kind, owner_id)
    assert all(r[1] == "section_title" and r[2] == "section" for r in rows)


def test_candidate_ids_text_only(corpus):
    conn = db.connect_readonly(corpus)
    rows = db.get_candidate_faiss_ids(conn, 1, ["section_text"])
    assert {r[0] for r in rows} == {100, 102}


def test_candidate_ids_tables_both_types(corpus):
    conn = db.connect_readonly(corpus)
    rows = db.get_candidate_faiss_ids(conn, 1, ["table_text", "table_vl"])
    assert {r[0] for r in rows} == {200, 201}
    assert all(r[2] == "table" and r[3] == 1 for r in rows)


def test_candidate_ids_figures_both_types(corpus):
    conn = db.connect_readonly(corpus)
    rows = db.get_candidate_faiss_ids(conn, 1, ["figure_text", "figure_vl"])
    assert {r[0] for r in rows} == {300, 301}


def test_candidate_ids_all_scopes_union(corpus):
    conn = db.connect_readonly(corpus)
    all_types = [t for s in C.ALL_SCOPES for t in C.SCOPE_TO_EMBEDDING_TYPES[s]]
    rows = db.get_candidate_faiss_ids(conn, 1, all_types)
    assert {r[0] for r in rows} == {100, 101, 102, 103, 200, 201, 300, 301}


def test_candidate_ids_empty_types(corpus):
    conn = db.connect_readonly(corpus)
    assert db.get_candidate_faiss_ids(conn, 1, []) == []


def test_candidate_ids_other_document_isolated(corpus):
    conn = db.connect_readonly(corpus)
    # Document 2 does not exist → no candidates.
    assert db.get_candidate_faiss_ids(conn, 2, ["section_text"]) == []


def test_fetch_section_content(corpus):
    conn = db.connect_readonly(corpus)
    c = db.fetch_owner_content(conn, "section", 1)
    assert c["owner_kind"] == "section"
    assert c["title"] == "Wärmebedarf"
    assert c["page_number"] == 12
    assert c["image_path"] is None
    assert c["document_id"] == 1


def test_fetch_table_content_has_parent_section(corpus):
    conn = db.connect_readonly(corpus)
    c = db.fetch_owner_content(conn, "table", 1)
    assert c["title"] == "Energieträger"
    assert c["text"] == "| a | b |"
    assert c["page_number"] == 12
    assert c["image_path"] == "images/p12_tbl0.png"
    assert c["section_title"] == "Wärmebedarf"     # parent section
    assert c["document_id"] == 1


def test_fetch_figure_content(corpus):
    conn = db.connect_readonly(corpus)
    c = db.fetch_owner_content(conn, "figure", 1)
    assert c["title"] == "Wärmekarte"
    assert c["text"] == "Eine Karte."
    assert c["page_number"] == 20
    assert c["section_title"] == "Potenziale"


def test_list_documents_and_label(corpus):
    conn = db.connect_readonly(corpus)
    docs = db.list_documents(conn)
    assert len(docs) == 1
    label = db.document_label(docs[0])
    assert "Musterstadt" in label
    assert "(aktuell)" in label


# ---------------------------------------------------------------------------
# chunker.py
# ---------------------------------------------------------------------------
def _hit(i, kind="section", chars=400, page=12):
    return {
        "score": 1.0 - i * 0.01,
        "owner_kind": kind,
        "owner_id": i,
        "title": f"Titel {i}",
        "text": "x" * chars,
        "page_number": page,
        "section_title": "Wärmebedarf",
        "image_path": None,
    }


def test_pack_chunks_splits_by_budget():
    # char/4 heuristic: 400 chars ≈ 100 tokens. Budget 150 → 1 hit per chunk.
    hits = [_hit(i) for i in range(3)]
    chunks = chunker.pack_chunks(hits, token_budget=150, tokenizer=None)
    assert len(chunks) == 3
    # every hit preserved, in order
    seen = [it["index"] for ch in chunks for it in ch.items]
    assert seen == [0, 1, 2]


def test_pack_chunks_groups_when_budget_allows():
    hits = [_hit(i, chars=40) for i in range(4)]  # ~10 tokens each
    chunks = chunker.pack_chunks(hits, token_budget=1000, tokenizer=None)
    assert len(chunks) == 1
    assert len(chunks[0].items) == 4


def test_pack_chunks_oversized_hit_gets_own_chunk():
    hits = [_hit(0, chars=40), _hit(1, chars=8000), _hit(2, chars=40)]
    chunks = chunker.pack_chunks(hits, token_budget=150, tokenizer=None)
    # the oversized middle hit is isolated; nothing is dropped
    total = sum(len(ch.items) for ch in chunks)
    assert total == 3


def test_citation_label_table():
    label = chunker.citation_label(_hit(0, kind="table"))
    assert "Tabelle" in label
    assert "Seite 12" in label
    assert "Wärmebedarf" in label  # parent section


def test_citation_label_missing_page():
    hit = _hit(0)
    hit["page_number"] = None
    assert "unbekannt" in chunker.citation_label(hit)


# ---------------------------------------------------------------------------
# query_cache.py
# ---------------------------------------------------------------------------
def test_query_cache_roundtrip(tmp_path):
    import numpy as np
    conn = query_cache.connect(tmp_path / "cache.db")
    key = query_cache.make_key("text", text="wärmebedarf")
    assert query_cache.get(conn, key) is None
    vec = np.arange(C.EMBEDDING_DIM, dtype="float32")
    query_cache.put(conn, key, vec)
    got = query_cache.get(conn, key)
    assert got is not None
    assert np.array_equal(got, vec)


def test_query_cache_key_sensitivity():
    k_text = query_cache.make_key("text", text="abc")
    k_text2 = query_cache.make_key("text", text="abc")
    k_other = query_cache.make_key("text", text="xyz")
    k_mode = query_cache.make_key("image", text="abc")
    k_img = query_cache.make_key("image", image_bytes=b"\x89PNG...")
    assert k_text == k_text2       # deterministic
    assert k_text != k_other       # text matters
    assert k_text != k_mode        # mode matters
    assert k_img != k_mode         # image bytes matter
