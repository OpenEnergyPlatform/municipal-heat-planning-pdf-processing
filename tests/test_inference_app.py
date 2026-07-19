"""
Tests for the inference_app read-side + pure-logic helpers.

Covers db.py (candidate-faiss-id UNION + content/citation lookup), chunker.py
(token-budget packing + citation labels), and query_cache.py (round-trip +
key derivation). Streamlit / FAISS / torch paths are exercised on the server,
not here.
"""
import sqlite3

import pytest

from scripts.inference_app import db, chunker, query_cache, pdf_link
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

        -- Pages/Segments: Segments.page is a FK to Pages.id (10/11), NOT the
        -- human page_number (12/13). section_segments must resolve the number.
        INSERT INTO Pages (id, document, page_number) VALUES (10, 1, 12), (11, 1, 13);
        INSERT INTO Segments (section, ordinal, page, kind, text) VALUES
            (1, 0, 10, 'text', 'Der Waermebedarf betrug 100 GWh im Jahr.'),
            (1, 1, 11, 'text', 'Fortsetzung auf der naechsten Seite.');
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


# ---------------------------------------------------------------------------
# config.py – granular VL / text scope split
# ---------------------------------------------------------------------------
def test_scope_split_maps_each_to_single_type():
    assert C.SCOPE_TO_EMBEDDING_TYPES[C.SCOPE_FIGURES_VL] == ["figure_vl"]
    assert C.SCOPE_TO_EMBEDDING_TYPES[C.SCOPE_FIGURES_TEXT] == ["figure_text"]
    assert C.SCOPE_TO_EMBEDDING_TYPES[C.SCOPE_TABLES_VL] == ["table_vl"]
    assert C.SCOPE_TO_EMBEDDING_TYPES[C.SCOPE_TABLES_TEXT] == ["table_text"]


def test_all_scopes_cover_all_six_types_once():
    flat = [t for s in C.ALL_SCOPES for t in C.SCOPE_TO_EMBEDDING_TYPES[s]]
    assert set(flat) == {"section_title", "section_text",
                         "table_vl", "table_text", "figure_vl", "figure_text"}
    assert len(flat) == 6           # each scope contributes exactly one type


def test_visual_scopes_are_figure_and_table_only():
    assert C.VISUAL_SCOPES == frozenset({
        C.SCOPE_TABLES_VL, C.SCOPE_TABLES_TEXT,
        C.SCOPE_FIGURES_VL, C.SCOPE_FIGURES_TEXT})
    assert C.SCOPE_HEADINGS not in C.VISUAL_SCOPES
    assert C.SCOPE_TEXT not in C.VISUAL_SCOPES


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
    # image_path is IMAGE_ROOT-relative: doc folder = filename ('doc.pdf') minus .pdf
    assert c["image_path"] == "doc/images/p12_tbl0.png"
    assert c["section_title"] == "Wärmebedarf"     # parent section
    assert c["document_id"] == 1


def test_section_segments_resolves_page_number(corpus):
    conn = db.connect_readonly(corpus)
    segs = db.section_segments(conn, 1)
    # page is the human page_number joined from Pages (12/13), NOT the
    # Segments.page FK values (10/11).
    assert segs == [(12, "Der Waermebedarf betrug 100 GWh im Jahr."),
                    (13, "Fortsetzung auf der naechsten Seite.")]


def test_document_filename_lookup(corpus):
    conn = db.connect_readonly(corpus)
    assert db.document_filename(conn, 1) == "doc.pdf"
    assert db.document_filename(conn, 999) is None


def test_fetch_figure_content(corpus):
    conn = db.connect_readonly(corpus)
    c = db.fetch_owner_content(conn, "figure", 1)
    assert c["title"] == "Wärmekarte"
    assert c["text"] == "Eine Karte."
    assert c["page_number"] == 20
    assert c["image_path"] == "doc/images/p20_img0.png"   # IMAGE_ROOT-relative
    assert c["section_title"] == "Potenziale"


def test_list_documents_and_label(corpus):
    conn = db.connect_readonly(corpus)
    docs = db.list_documents(conn)
    assert len(docs) == 1
    cov = db.municipality_coverage(conn, docs)
    assert cov[docs[0]["id"]] == ["Musterstadt"]      # single-doc OU → its member
    label = db.document_label(docs[0], cov[docs[0]["id"]])
    assert "Musterstadt" in label
    assert "(aktuell)" in label


def _doc_row(**kw):
    base = {"municipality_name": "Gemmrigheim", "organisation_unit_name": None,
            "published": "20260401", "is_current": 1,
            "filename": "waermeplan_konvoi_hessigheim_20260401.pdf"}
    base.update(kw)
    return base


def test_konvoi_lead_parsing():
    assert db._konvoi_lead("waermeplan_konvoi_hessigheim_20260401.pdf") == "Hessigheim"
    assert db._konvoi_lead("waermeplan_denzlingen_konvoi_2024q2.pdf") == "Denzlingen"
    assert db._konvoi_lead("waermeplan__asperg_et_al_konvoi_2024q2.pdf") == "Asperg Et Al"
    assert db._konvoi_lead("waermeplan_by6_konvoi_250327.pdf") == "By6"


def test_document_label_convoy_uses_ou_and_count():
    # a convoy covering 4 municipalities is labelled by its unit + count + Konvoi,
    # NOT by one arbitrary member up front.
    label = db.document_label(
        _doc_row(organisation_unit_name="GVV Besigheim"),
        covered=["Gemmrigheim", "Hessigheim", "Mundelsheim", "Walheim"],
    )
    assert "GVV Besigheim" in label
    assert "4 Gemeinden" in label
    assert "Konvoi" in label
    assert not label.startswith("Gemmrigheim")


def test_document_label_single_municipality_has_no_convoy_tag():
    label = db.document_label(
        _doc_row(filename="waermeplan_flensburg_20240701.pdf",
                 municipality_name="Flensburg"),
        covered=["Flensburg"],
    )
    assert "Konvoi" not in label
    assert "Flensburg" in label


# ---------------------------------------------------------------------------
# db.py – municipality-coverage rule (pure)
# ---------------------------------------------------------------------------
def test_covered_names_single_doc_ou_covers_all_members():
    members = {1: "A", 2: "B", 3: "C"}
    assert db._covered_names(1, "A", True, 1, {1}, members) == ["A", "B", "C"]


def test_covered_names_standalone_in_multidoc_ou_covers_only_self():
    members = {1: "A", 2: "B"}
    assert db._covered_names(1, "A", False, 2, {1, 2}, members) == ["A"]


def test_covered_names_konvoi_mops_up_unclaimed_members():
    members = {10: "Besigheim", 11: "Gemmrigheim", 12: "Hessigheim",
               13: "Mundelsheim", 14: "Walheim"}
    # OU has 2 plans: Besigheim's own (ags 10) + this convoy (own ags 11).
    got = db._covered_names(11, "Gemmrigheim", True, 2, {10, 11}, members)
    assert got == ["Gemmrigheim", "Hessigheim", "Mundelsheim", "Walheim"]
    assert "Besigheim" not in got          # kept by its own standalone plan


# ---------------------------------------------------------------------------
# pdf_link.py – locate a verbatim search phrase for the source-PDF deep link
# ---------------------------------------------------------------------------
def test_locate_quote_finds_page_and_verbatim_phrase():
    # refined quote vs. raw segments (page 18 holds the matching run)
    segments = [
        (17, "Vorbemerkung zum Beteiligungsprozess der Kommune."),
        (18, "Der Steuerungskreis setzt sich aus Vertretern der Gemeindeverwaltungen "
             "und der endura kommunal GmbH zusammen."),
    ]
    quote = "Der Steuerungskreis setzt sich aus Vertretern der Gemeindeverwaltungen zusammen"
    page, phrase = pdf_link.locate_quote(quote, segments)
    assert page == 18
    assert "Steuerungskreis setzt sich" in phrase
    assert phrase in segments[1][1]              # a literal substring of the raw text


def test_locate_quote_keeps_punctuation_verbatim():
    # the phrase must occur LITERALLY in the PDF text layer, so hyphens/periods
    # are preserved (a space-joined "Emmy Noether Str" would not highlight).
    seg = "endura kommunal GmbH Emmy-Noether-Str. 2 79110 Freiburg info@endura-kommunal.de"
    quote = "erstellt durch die endura kommunal GmbH Emmy-Noether-Str 2 79110 Freiburg"
    page, phrase = pdf_link.locate_quote(quote, [(2, seg)])
    assert page == 2
    assert "Emmy-Noether-Str." in phrase
    assert phrase in seg


def test_best_search_phrase_graceful_on_missing_file():
    # returns None (never raises) if the PDF/page is unavailable or deps missing
    assert pdf_link.best_search_phrase("/no/such/file.pdf", 1, "irgendein Zitat hier") is None


def test_locate_quote_returns_none_when_no_shared_run():
    segments = [(2, "Auftragnehmer ist die Musterbüro Energie GmbH aus Freiburg.")]
    # a quote with no 3-word contiguous overlap
    assert pdf_link.locate_quote("völlig anderer Wortlaut ohne Bezug", segments) is None


def test_locate_quote_none_for_too_short_quote():
    assert pdf_link.locate_quote("zwei Wörter", [(1, "zwei Wörter hier stehen")]) is None


def test_pdf_page_url_page_only_and_with_search():
    assert pdf_link.pdf_page_url("/app/static/pdf", "waermeplan_x.pdf", 5) \
        == "/app/static/pdf/waermeplan_x.pdf#page=5"
    url = pdf_link.pdf_page_url("/app/static/pdf/", "waermeplan_x.pdf", 5, "Der Steuerungskreis")
    # the search value is wrapped in double quotes (%22)
    assert url == "/app/static/pdf/waermeplan_x.pdf#page=5&search=%22Der%20Steuerungskreis%22"


def test_pdf_page_url_encodes_raw_umlaut_filename():
    # DB filenames are stored raw (e.g. tönning); the path segment is encoded once.
    url = pdf_link.pdf_page_url("/app/static/pdf", "waermepaln_tönning_20241129.pdf", 3)
    assert url == "/app/static/pdf/waermepaln_t%C3%B6nning_20241129.pdf#page=3"


def test_pdf_viewer_url_wraps_pdfjs_with_encoded_file_param():
    url = pdf_link.pdf_viewer_url("/app/static/pdfjs/web", "/app/static/pdf",
                                  "waermeplan_x.pdf", 9, "Der Steuerungskreis")
    # file= is the fully-encoded same-origin PDF path; hash carries page+phrase.
    assert url == ("/app/static/pdfjs/web/viewer.html"
                   "?file=%2Fapp%2Fstatic%2Fpdf%2Fwaermeplan_x.pdf"
                   "#page=9&search=%22Der%20Steuerungskreis%22&phrase=true")


def test_pdf_viewer_url_page_only_when_no_phrase():
    url = pdf_link.pdf_viewer_url("/app/static/pdfjs/web", "/app/static/pdf",
                                  "waermeplan_x.pdf", 4)
    assert url.endswith("viewer.html?file=%2Fapp%2Fstatic%2Fpdf%2Fwaermeplan_x.pdf#page=4")


# ---------------------------------------------------------------------------
# pdf_link.py – coordinate highlight overlay (bbox)
# ---------------------------------------------------------------------------
def test_best_segment_rects_picks_matched_segment_geometry():
    segs = [
        (17, "Vorbemerkung zum Beteiligungsprozess der Kommune.", [[1, 2, 3, 4]]),
        (18, "Der Steuerungskreis setzt sich aus Vertretern der "
             "Gemeindeverwaltungen zusammen.", [[5, 6, 7, 8], [5, 9, 7, 11]]),
    ]
    quote = ("Der Steuerungskreis setzt sich aus Vertretern der "
             "Gemeindeverwaltungen zusammen")
    assert pdf_link.best_segment_rects(quote, segs) == (18, [[5, 6, 7, 8], [5, 9, 7, 11]])


def test_best_segment_rects_none_without_geometry_or_match():
    # matching segment but no stored rects → None (caller uses the phrase fallback)
    assert pdf_link.best_segment_rects(
        "Der Steuerungskreis setzt sich zusammen",
        [(18, "Der Steuerungskreis setzt sich zusammen.", None)]) is None
    # geometry present but no shared 3-word run → None
    assert pdf_link.best_segment_rects(
        "völlig anderer Wortlaut", [(3, "Ganz etwas anderes hier.", [[1, 2, 3, 4]])]) is None


def test_encode_rects_is_urlsafe_and_roundtrips():
    import base64
    import json as _json
    rects = [[10.5, 20.0, 100.25, 40.0], [12.0, 60.0, 90.0, 75.5]]
    tok = pdf_link.encode_rects(rects)
    assert not any(c in tok for c in "+/=")          # url-safe, unpadded
    pad = "=" * (-len(tok) % 4)
    assert _json.loads(base64.urlsafe_b64decode(tok + pad)) == rects


def test_pdf_viewer_url_rects_overlay_supersedes_search():
    url = pdf_link.pdf_viewer_url("/app/static/pdfjs/web", "/app/static/pdf",
                                  "waermeplan_x.pdf", 9, phrase="ignored",
                                  rects=[[1, 2, 3, 4]])
    assert "#page=9&mhl=" in url
    assert "search" not in url                       # overlay replaces the text find
    assert url.startswith("/app/static/pdfjs/web/viewer.html?file=%2Fapp")


def test_section_segments_geo_parses_bbox_and_nulls(kwp_db):
    db_path, con = kwp_db
    con.executescript(
        """
        INSERT INTO Sections (id, document, section_number, title, content, page_number)
            VALUES (1, 1, 0, 'S', 'c', 7);
        INSERT INTO Pages (id, document, page_number) VALUES (10, 1, 7);
        INSERT INTO Segments (section, ordinal, page, kind, text, bbox) VALUES
            (1, 0, 10, 'text', 'Hallo Welt hier', '[[10.0,20.0,100.0,40.0]]'),
            (1, 1, 10, 'text', 'Absatz ohne Geometrie', NULL);
        """
    )
    con.commit()
    conn = db.connect_readonly(db_path)
    assert db.section_segments_geo(conn, 1) == [
        (7, 'Hallo Welt hier', [[10.0, 20.0, 100.0, 40.0]]),
        (7, 'Absatz ohne Geometrie', None),
    ]


def test_section_segments_geo_degrades_on_pre_bbox_db(tmp_path):
    import sqlite3 as _sq
    p = tmp_path / "old.db"
    c = _sq.connect(p)
    c.executescript(
        """
        CREATE TABLE Pages (id INTEGER PRIMARY KEY, document INTEGER, page_number INTEGER);
        CREATE TABLE Segments (id INTEGER PRIMARY KEY, section INTEGER, ordinal INTEGER,
                               page INTEGER, kind TEXT, ref TEXT, text TEXT);
        INSERT INTO Pages VALUES (10, 1, 7);
        INSERT INTO Segments (section, ordinal, page, kind, text)
            VALUES (1, 0, 10, 'text', 'Hallo Welt hier');
        """
    )
    c.commit()
    c.row_factory = _sq.Row
    # no `bbox` column → falls back to (page, text, None), never raises
    assert db.section_segments_geo(c, 1) == [(7, 'Hallo Welt hier', None)]


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


# ---------------------------------------------------------------------------
# llm_client.py – grounding gate (anti-hallucination)
# ---------------------------------------------------------------------------
def _excerpt(text):
    return [{"index": 0, "source": "Abschnitt „X“, Seite 1", "text": text}]


def test_quote_grounded_accepts_verbatim_span():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    items = _excerpt("Der Wärmeplan wurde durch die Musterbüro GmbH erstellt und geprüft.")
    # whitespace/case-tolerant verbatim substring
    assert llm._quote_is_grounded("durch die  MUSTERBÜRO GmbH  erstellt", items) is True


def test_quote_grounded_rejects_fabrication():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    items = _excerpt("Der Auszug behandelt Fernwärme, Wärmepumpen und Sanierung.")
    # a plausible but absent company name must NOT validate
    assert llm._quote_is_grounded("erstellt von der endura kommunal GmbH", items) is False


def test_quote_grounded_rejects_too_short():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    items = _excerpt("Beauftragt wurde die Beispiel GmbH aus Musterstadt.")
    assert llm._quote_is_grounded("GmbH", items) is False        # stray common token


def test_ask_chunk_stub_quote_is_grounded():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    if not llm.LLM_STUB_MODE:
        pytest.skip("stub mode off")
    items = _excerpt("Die Beispiel GmbH hat den Plan erstellt.")
    out = llm.ask_chunk("Wer hat den Plan erstellt?", items)
    assert out["found"] is True
    assert llm._quote_is_grounded(out["quote"], items)


# ---------------------------------------------------------------------------
# llm_client.py – search-anchor guard (reject evaluation/refusal phrases)
# ---------------------------------------------------------------------------
def test_non_anchor_detects_refusal_phrase():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    # the exact self-contradictory string the gateway produced for an image query
    assert llm._looks_like_non_anchor(
        "Abbildung: Keine ähnlichen Diagramme im bereitgestellten Kontext nachweisbar."
    ) is True


@pytest.mark.parametrize("bad", [
    "Die Information ist nicht enthalten.",
    "Dazu liegen keine Angaben vor.",
    "Lässt sich aus dem Kontext nicht ableiten.",
])
def test_non_anchor_detects_variants(bad):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    assert llm._looks_like_non_anchor(bad) is True


@pytest.mark.parametrize("good", [
    "Abbildung: Gestapeltes Balkendiagramm des jährlichen Wärmebedarfs nach Sektoren in MWh/a.",
    "Die kommunale Wärmeplanung wurde durch die Musterplan Energie GmbH aus Freiburg erstellt.",
    "Säulendiagramm der Baualtersklassen der Gebäude im Gemeindegebiet, Anteile in Prozent.",
])
def test_non_anchor_passes_real_anchors(good):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    assert llm._looks_like_non_anchor(good) is False


# ---------------------------------------------------------------------------
# code_exec.py + llm_client ReAct compute loop
# ---------------------------------------------------------------------------
def test_code_exec_disabled_returns_error(monkeypatch):
    ce = pytest.importorskip("scripts.inference_app.code_exec")
    monkeypatch.setattr(ce.config, "CODE_EXEC_URL", "")
    assert ce.is_enabled() is False
    out = ce.run_code("print(1)")
    assert out["ok"] is False and "disabled" in out["error"]


def test_format_exec_result_ok_and_error():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    assert "50" in llm._format_exec_result({"ok": True, "stdout": "50\n"})
    r = llm._format_exec_result({"ok": False, "error": "Boom"})
    assert "fehlgeschlagen" in r.lower() and "Boom" in r


def test_answer_from_sources_runs_react_compute_loop(monkeypatch):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    calls = {"n": 0}

    def fake_chat_json(messages, temperature):
        calls["n"] += 1
        if calls["n"] == 1:                      # first: request a computation
            return {"action": "python", "code": "print(50)"}
        return {"found": True, "complete": True, "answer": "Die Summe ist 50",
                "supports": [{"index": 0, "quote": "x"}]}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    ran = {}

    def runner(code, ctx):
        ran["code"], ran["ctx"] = code, ctx
        return {"ok": True, "stdout": "50\n"}

    out = llm.answer_from_sources("Summe?", [{"index": 0, "source": "s", "text": "t"}],
                                  code_runner=runner, code_context={"tables": []}, max_compute=2)
    assert calls["n"] == 2                        # one action call + one final-answer call
    assert ran["code"] == "print(50)"
    assert out["answer"] == "Die Summe ist 50"
    assert len(out["compute"]) == 1
    assert out["compute"][0]["output"]["stdout"] == "50\n"


_TASK_WITH_SCHEMA = ('Welche Firma hat den Plan erstellt? Bitte Antwort als JSON im Format: '
                     '{"Firmname": str, "Postleitzahl": int}')
_HIJACKED = {"Firmname": "Energieservice Westfalen Weser GmbH", "Postleitzahl": 32278}
_ITEMS = [{"index": 0, "source": "s", "text": "Auftragnehmer: Energieservice Westfalen Weser GmbH"}]


def test_answer_from_sources_retries_when_the_task_schema_hijacks_the_envelope(monkeypatch):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    seen = []

    def fake_chat_json(messages, temperature):
        seen.append(messages[0]["content"])
        if len(seen) == 1:               # model answers in the task's schema instead
            return dict(_HIJACKED)
        return {"found": True, "complete": True, "answer": "Energieservice Westfalen Weser GmbH",
                "supports": [{"index": 0, "quote": "Auftragnehmer: Energieservice"}]}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    out = llm.answer_from_sources(_TASK_WITH_SCHEMA, _ITEMS)

    # A reply in the task's own schema parses fine but has no "found", so without
    # the retry it reads as "the document does not say" and the answer is lost.
    assert len(seen) == 2
    assert llm._ENVELOPE_CORRECTION in seen[1]
    assert out["found"] and out["supports"]


def test_answer_from_sources_flags_a_persistent_envelope_violation(monkeypatch):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_chat_json", lambda messages, temperature: dict(_HIJACKED))

    out = llm.answer_from_sources(_TASK_WITH_SCHEMA, _ITEMS)

    # Must stay distinguishable from an honest miss, or the next diagnosis starts
    # from scratch again.
    assert out["found"] is False and out["off_envelope"] is True


def test_answer_from_sources_treats_an_honest_miss_as_a_miss(monkeypatch):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    calls = {"n": 0}

    def fake_chat_json(messages, temperature):
        calls["n"] += 1
        return {"found": False}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    out = llm.answer_from_sources(_TASK_WITH_SCHEMA, _ITEMS)

    # {"found": false} carries the key, so it must not trigger a retry.
    assert calls["n"] == 1
    assert out["found"] is False and not out.get("off_envelope")


def test_answer_prompt_scopes_task_format_specs_to_the_answer_field():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    tail = llm._ANSWER_PROMPT_TAIL.lower()
    # Measured on the live model: without this the envelope is lost 4/4 times for
    # a task carrying its own JSON schema, with it 4/4 times correct.
    assert "formatvorgaben" in tail and '"answer"' in llm._ANSWER_PROMPT_TAIL


def test_history_context_includes_recent_turns_but_frames_as_non_source():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    hist = [{"task": "Wer hat den Plan erstellt?", "phrase": "anker1", "answer": "Firma X"},
            {"task": "Und der Projektleiter?", "phrase": "anker2", "answer": "Herr Y"}]
    ctx = llm._history_context(hist, limit=5)
    assert "Firma X" in ctx and "Und der Projektleiter?" in ctx and "anker2" in ctx
    assert "keine faktenquelle" in ctx.lower()          # framed as reference-only
    assert llm._history_context([]) == "" and llm._history_context(None) == ""


def test_history_context_caps_to_limit():
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    hist = [{"task": f"Frage {i}", "answer": f"A{i}"} for i in range(8)]
    ctx = llm._history_context(hist, limit=5)
    assert "Frage 7" in ctx and "Frage 2" not in ctx       # only the last 5


def test_answer_from_sources_no_action_no_compute(monkeypatch):
    llm = pytest.importorskip("scripts.inference_app.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_chat_json",
                        lambda messages, temperature: {"found": True, "complete": True,
                                                       "answer": "direkt", "supports": []})
    # no code_runner → the compute hint is never added and compute stays empty
    out = llm.answer_from_sources("x", [{"index": 0, "source": "s", "text": "t"}])
    assert out["answer"] == "direkt"
    assert out["compute"] == []
