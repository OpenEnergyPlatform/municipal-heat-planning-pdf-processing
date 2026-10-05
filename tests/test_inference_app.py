"""
Tests for the inference_app read-side + pure-logic helpers.

Covers db.py (candidate-faiss-id UNION + content/citation lookup), chunker.py
(token-budget packing + citation labels), and query_cache.py (round-trip +
key derivation). Streamlit / FAISS / torch paths are exercised on the server,
not here.

What the chat offers is what the index holds: its search scopes are those whose
embedding types the database has vectors of, in the order of the fixed list;
the cache key of a query vector names the embedding model and its size, so the
vectors of two models are never mixed, AND an entry written without them
matches nothing; and a database that records another model than the one that
embeds the queries is said so in the profile's sentence, which is a notice and
refuses nothing.
"""
import hashlib
import json
import sqlite3
import sys
import threading
import types

import pytest

from docpipe.inference import chunker, db, pdf_locate, query_cache
from docpipe.app import pdf_link
from docpipe.embedding import config as EC
from docpipe.inference import config as C


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
        UPDATE Documents SET published = '20240101', is_current = 1,
            group_key = '12345' WHERE id = 1;
        INSERT INTO DocumentMeta (document, organisation_unit, municipality_ags)
            VALUES (1, 1, 12345);

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


# ---------------------------------------------------------------------------
# db.available_scopes: the scopes the index really holds
# ---------------------------------------------------------------------------
def _delete_embeddings(db_path, where):
    con = sqlite3.connect(db_path)
    con.execute(f"DELETE FROM Embeddings WHERE {where}")
    con.commit()
    con.close()


def test_an_index_with_every_type_offers_every_scope_in_the_fixed_order(corpus):
    assert db.available_scopes(db.connect_readonly(corpus)) == C.ALL_SCOPES


def test_a_text_only_index_offers_no_scope_over_pictures(corpus):
    _delete_embeddings(corpus, "embedding_type LIKE '%_vl'")
    got = db.available_scopes(db.connect_readonly(corpus))
    assert got == [C.SCOPE_HEADINGS, C.SCOPE_TEXT,
                   C.SCOPE_TABLES_TEXT, C.SCOPE_FIGURES_TEXT]
    assert not set(got) & {C.SCOPE_TABLES_VL, C.SCOPE_FIGURES_VL}


def test_a_scope_is_offered_for_the_type_the_index_holds_and_no_other(corpus):
    _delete_embeddings(corpus, "embedding_type != 'table_vl'")
    assert db.available_scopes(db.connect_readonly(corpus)) == [
        C.SCOPE_TABLES_VL]


def test_an_index_that_holds_nothing_offers_nothing(corpus):
    _delete_embeddings(corpus, "1 = 1")
    assert db.available_scopes(db.connect_readonly(corpus)) == []


def test_a_type_no_scope_names_opens_no_scope(corpus):
    _delete_embeddings(corpus, "embedding_type != 'section_text'")
    con = sqlite3.connect(corpus)
    con.execute("INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, "
                "owner_id) VALUES (900, 'mystery', 'section', 1)")
    con.commit()
    con.close()
    assert db.available_scopes(db.connect_readonly(corpus)) == [C.SCOPE_TEXT]


def test_the_scopes_cost_one_query(corpus):
    conn = db.connect_readonly(corpus)
    statements = []
    conn.set_trace_callback(statements.append)
    db.available_scopes(conn)
    assert len(statements) == 1
    assert "embedding_type" in statements[0] and "Embeddings" in statements[0]


# ---------------------------------------------------------------------------
# db.index_model_notice: the model of the index against the one that asks
# ---------------------------------------------------------------------------
def _record_model(db_path, model):
    from docpipe.store import schema
    con = sqlite3.connect(db_path)
    schema.set_meta(con, {"embedding/model": model})
    con.close()


def test_a_notice_is_the_sentence_filled_in_when_the_models_differ(corpus):
    _record_model(corpus, "model-a")
    conn = db.connect_readonly(corpus)
    got = db.index_model_notice(
        conn, "model-b", "Built with {built}, asked with {queried}.")
    assert got == "Built with model-a, asked with model-b."


def test_there_is_no_notice_where_the_models_are_the_same(corpus):
    _record_model(corpus, "model-a")
    conn = db.connect_readonly(corpus)
    assert db.index_model_notice(conn, "model-a", "{built} {queried}") is None


def test_a_database_that_records_no_model_says_nothing(corpus):
    # the shared fixture's database has no Meta table at all, one that was
    # made before the index said anything
    conn = db.connect_readonly(corpus)
    assert db.index_model_notice(conn, "model-b", "{built} {queried}") is None
    _record_model(corpus, "")
    assert db.index_model_notice(
        db.connect_readonly(corpus), "model-b", "{built} {queried}") is None


@pytest.mark.parametrize("name, begins", [
    ("kwp", "Der Index wurde mit "), ("scenarios", "The index was built with "),
    ("default", "The index was built with ")])
def test_each_profile_words_the_notice_in_its_own_language(
        corpus, name, begins):
    from docpipe.inference import wording
    from docpipe.profile import load_profile
    _record_model(corpus, "model-a")
    sentence = wording.ui(load_profile(name))["index_model_differs"]
    got = db.index_model_notice(db.connect_readonly(corpus), "model-b",
                                sentence)
    assert got.startswith(begins) and "model-a" in got and "model-b" in got
    assert "{" not in got


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


# ---------------------------------------------------------------------------
# pdf_link.py: the cited page, drawn with PyMuPDF
# ---------------------------------------------------------------------------
class FakePDF:
    """What PyMuPDF is to render_page: a file of `pages` pages that notes
    what is drawn on it and whether it was closed."""

    def __init__(self, pages=3, fail_on_render=False, size=(595, 842)):
        self.page_count = pages
        self.rect = types.SimpleNamespace(width=size[0], height=size[1])
        self.fail_on_render = fail_on_render
        self.log = []
        self.closed = False

    def load_page(self, index):
        self.log.append(("load", index))
        return self

    def add_highlight_annot(self, rect):
        self.log.append(("highlight", rect))

    def get_pixmap(self, matrix):
        if self.fail_on_render:
            raise RuntimeError("out of memory")
        self.log.append(("pixmap", matrix))
        return types.SimpleNamespace(tobytes=lambda form: f"{form}:image".encode())

    def close(self):
        self.closed = True


@pytest.fixture
def fitz_with(monkeypatch):
    """Installs a PyMuPDF whose `open` hands out the given file; returns the
    file so a test can see what was done to it."""
    def install(pdf=None, opens=None):
        pdf = pdf or FakePDF()

        def open_(path):
            if opens is not None:
                raise opens
            return pdf

        fake = types.SimpleNamespace(
            open=open_, Rect=lambda *corners: ("rect",) + corners,
            Matrix=lambda zoom_x, zoom_y: ("matrix", zoom_x, zoom_y))
        monkeypatch.setitem(sys.modules, "fitz", fake)
        return pdf
    return install


def test_render_page_draws_a_highlight_over_each_rect_and_returns_the_png(
        fitz_with):
    pdf = fitz_with()
    rects = [[10, 20, 200, 32], [10, 34, 90, 46]]
    assert pdf_link.render_page("x.pdf", 2, rects, zoom=1.5) == b"png:image"
    assert pdf.log == [("load", 1),
                       ("highlight", ("rect", 10, 20, 200, 32)),
                       ("highlight", ("rect", 10, 34, 90, 46)),
                       ("pixmap", ("matrix", 1.5, 1.5))]
    assert pdf.closed


def test_render_page_draws_a_poster_smaller_than_it_is_asked_to(fitz_with):
    """A page of a size a server cannot hold at full zoom is scaled down to
    the longest side it may have, and an ordinary one is left alone."""
    poster = fitz_with(FakePDF(size=(2384, 3370)))          # A0, in points
    pdf_link.render_page("x.pdf", 1, zoom=2.0)
    (_, matrix), = [step for step in poster.log if step[0] == "pixmap"]
    assert matrix[1] == matrix[2]
    assert matrix[1] * 3370 == pytest.approx(pdf_link.PAGE_MAX_SIDE)
    sheet = fitz_with(FakePDF(size=(595, 842)))             # A4
    pdf_link.render_page("x.pdf", 1, zoom=2.0)
    assert ("pixmap", ("matrix", 2.0, 2.0)) in sheet.log


def test_render_page_without_rects_marks_nothing(fitz_with):
    pdf = fitz_with()
    pdf_link.render_page("x.pdf", 1, None)
    pdf_link.render_page("x.pdf", 1, [])
    assert not [step for step in pdf.log if step[0] == "highlight"]


@pytest.mark.parametrize("number", [0, 4, -1])
def test_render_page_refuses_a_page_the_file_does_not_have(fitz_with, number):
    pdf = fitz_with(FakePDF(pages=3))
    with pytest.raises(pdf_link.PageNotRendered) as caught:
        pdf_link.render_page("x.pdf", number)
    assert "3 pages" in str(caught.value) and str(number) in str(caught.value)
    assert caught.value.reason == pdf_link.NO_SUCH_PAGE
    assert pdf.closed                         # not left open on the way out


def test_render_page_says_when_the_file_does_not_open(fitz_with):
    fitz_with(opens=RuntimeError("no such file"))
    with pytest.raises(pdf_link.PageNotRendered) as caught:
        pdf_link.render_page("missing.pdf", 1)
    assert "does not open" in str(caught.value)
    assert "no such file" in str(caught.value)
    assert caught.value.reason == pdf_link.NOT_OPENED


def test_render_page_says_when_the_drawing_fails_and_closes_the_file(fitz_with):
    pdf = fitz_with(FakePDF(fail_on_render=True))
    with pytest.raises(pdf_link.PageNotRendered) as caught:
        pdf_link.render_page("x.pdf", 1)
    assert "did not render" in str(caught.value)
    assert "out of memory" in str(caught.value)
    assert caught.value.reason == pdf_link.NOT_DRAWN
    assert pdf.closed


def test_render_page_says_when_pymupdf_is_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "fitz", None)      # import fails
    with pytest.raises(pdf_link.PageNotRendered) as caught:
        pdf_link.render_page("x.pdf", 1)
    assert "PyMuPDF is not installed" in str(caught.value)
    assert caught.value.reason == pdf_link.NOT_INSTALLED


class Crowd:
    """A PyMuPDF that counts how many callers are inside it at once."""

    def __init__(self):
        self.inside = 0
        self.peak = 0
        self.guard = threading.Lock()
        self.page_count = 1
        self.rect = types.SimpleNamespace(width=595, height=842)

    def open(self, path):
        with self.guard:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        # long enough for another thread to arrive; not time.sleep, which the
        # suite turns into a no-op for every test
        threading.Event().wait(0.03)
        return self

    def load_page(self, index):
        return self

    def get_text(self, *kind):
        return [] if kind else ""

    def get_pixmap(self, matrix):
        return types.SimpleNamespace(tobytes=lambda form: b"png")

    def close(self):
        with self.guard:
            self.inside -= 1


def together(calls):
    """Every call on a thread of its own, all let go at the same moment; what
    one of them raised is raised here."""
    start = threading.Barrier(len(calls))
    failed = []

    def run(call):
        try:
            start.wait()
            call()
        except BaseException as exc:
            failed.append(exc)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if failed:
        raise failed[0]


@pytest.fixture
def crowd(monkeypatch):
    """The Crowd as `fitz`, with the one other library the locating needs."""
    found = Crowd()
    monkeypatch.setitem(sys.modules, "fitz", types.SimpleNamespace(
        open=found.open, Rect=lambda *corners: corners,
        Matrix=lambda zoom_x, zoom_y: (zoom_x, zoom_y)))
    monkeypatch.setitem(sys.modules, "rapidfuzz", types.SimpleNamespace(
        fuzz=types.SimpleNamespace(partial_ratio_alignment=lambda a, b: None)))
    monkeypatch.setattr(pdf_locate, "_MISSING", "")      # both libraries here
    return found


def test_the_crowd_shows_two_threads_in_the_library_where_nothing_stops_them(
        crowd):
    """The instrument: without the lock, threads do overlap in it."""
    def enter():
        crowd.open("x.pdf")
        crowd.close()

    together([enter] * 4)
    assert crowd.peak > 1


def test_no_two_threads_are_inside_pymupdf_at_once(crowd):
    """The chat runs a session on each thread, and a rerun starts while the
    script it replaced is still drawing. Drawing, finding the words of a
    page and finding a phrase on it each enter the library, and each holds
    the one lock."""
    quote = "Der Waermebedarf betraegt 241 GWh im Jahr"
    together([lambda: pdf_link.render_page("x.pdf", 1),
              lambda: pdf_locate.page_words("x.pdf", 1),
              lambda: pdf_link.best_search_phrase("x.pdf", 1, quote),
              lambda: pdf_link.render_page("x.pdf", 1),
              lambda: pdf_locate.page_words("x.pdf", 1),
              lambda: pdf_link.best_search_phrase("x.pdf", 1, quote)])
    assert crowd.peak == 1 and crowd.inside == 0


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
    vec = np.arange(EC.EMBEDDING_DIM, dtype="float32")
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


def test_the_key_names_the_model_and_the_size_of_its_vectors():
    key = query_cache.make_key("text", text="abc", model="m1", dim=4096)
    assert key == query_cache.make_key("text", text="abc", model="m1", dim=4096)
    assert key != query_cache.make_key("text", text="abc", model="m2", dim=4096)
    assert key != query_cache.make_key("text", text="abc", model="m1", dim=1024)


def test_a_key_without_model_and_size_is_the_configured_ones(monkeypatch):
    dim = EC.EMBEDDING_DIM
    key = query_cache.make_key("text", text="abc")
    assert key == query_cache.make_key(
        "text", text="abc", model=EC.EMBEDDING_MODEL, dim=dim)
    monkeypatch.setattr(EC, "EMBEDDING_MODEL", "the-next-model")
    moved = query_cache.make_key("text", text="abc")
    assert moved != key                                         # read now
    assert moved == query_cache.make_key(
        "text", text="abc", model="the-next-model", dim=dim)
    monkeypatch.setattr(EC, "EMBEDDING_DIM", dim + 1)
    assert query_cache.make_key("text", text="abc") not in (key, moved)


def test_the_vectors_of_two_models_never_mix_in_one_cache_file(tmp_path):
    import numpy as np
    conn = query_cache.connect(tmp_path / "cache.db")
    first = query_cache.make_key("text", text="abc", model="m1", dim=3)
    second = query_cache.make_key("text", text="abc", model="m2", dim=3)
    query_cache.put(conn, first, np.array([1, 0, 0], dtype="float32"))
    assert query_cache.get(conn, second) is None     # the same words, a miss
    query_cache.put(conn, second, np.array([0, 1, 0], dtype="float32"))
    assert query_cache.get(conn, first).tolist() == [1, 0, 0]
    assert query_cache.get(conn, second).tolist() == [0, 1, 0]


def test_an_entry_written_under_the_key_without_a_model_matches_nothing(
        tmp_path):
    import numpy as np
    # the key as it was made before it named a model
    old = hashlib.sha256()
    for part in (b"text", "abc".encode("utf-8"), b""):
        old.update(part)
        old.update(bytes([0]))
    conn = query_cache.connect(tmp_path / "cache.db")
    query_cache.put(conn, old.hexdigest(), np.ones(3, dtype="float32"))
    assert query_cache.get(conn, old.hexdigest()) is not None   # it is there
    assert query_cache.get(
        conn, query_cache.make_key("text", text="abc")) is None


# ---------------------------------------------------------------------------
# llm_client.py – grounding gate (anti-hallucination)
# ---------------------------------------------------------------------------
def _excerpt(text):
    return [{"index": 0, "source": "Abschnitt „X“, Seite 1", "text": text}]


def test_quote_grounded_accepts_verbatim_span():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    items = _excerpt("Der Wärmeplan wurde durch die Musterbüro GmbH erstellt und geprüft.")
    # whitespace/case-tolerant verbatim substring
    assert llm._quote_is_grounded("durch die  MUSTERBÜRO GmbH  erstellt", items) is True


def test_quote_grounded_rejects_fabrication():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    items = _excerpt("Der Auszug behandelt Fernwärme, Wärmepumpen und Sanierung.")
    # a plausible but absent company name must NOT validate
    assert llm._quote_is_grounded("erstellt von der endura kommunal GmbH", items) is False


def test_quote_grounded_rejects_too_short():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    items = _excerpt("Beauftragt wurde die Beispiel GmbH aus Musterstadt.")
    assert llm._quote_is_grounded("GmbH", items) is False        # stray common token


def test_ask_chunk_stub_quote_is_grounded():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    if not llm.LLM_STUB_MODE:
        pytest.skip("stub mode off")
    items = _excerpt("Die Beispiel GmbH hat den Plan erstellt.")
    out = llm.ask_chunk("Wer hat den Plan erstellt?", items)
    assert out["found"] is True
    assert llm._quote_is_grounded(out["quote"], items)


# ---------------------------------------------------------------------------
# llm_client.py – the search anchor is the sentence the model wrote
# ---------------------------------------------------------------------------
def test_the_search_phrase_is_the_sentence_the_model_wrote(monkeypatch):
    """No filter on the anchor: none was ever approved, and the answer still
    comes from the retrieved text under the grounding gate. Only an empty
    phrase falls back to the task."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    said = {"phrase": "Dazu liegen keine Angaben vor.", "repetition": False}
    monkeypatch.setattr(llm, "_chat_json", lambda *a, **k: dict(said))
    assert llm.make_search_phrase("Wer hat den Plan erstellt?") == (
        "Dazu liegen keine Angaben vor.", False)
    said["phrase"] = ""
    assert llm.make_search_phrase("Wer hat den Plan erstellt?") == (
        "Wer hat den Plan erstellt?", False)
    assert not hasattr(llm, "_looks_like_non_anchor")


# ---------------------------------------------------------------------------
# code_exec.py + llm_client ReAct compute loop
# ---------------------------------------------------------------------------
def test_code_exec_disabled_returns_error(monkeypatch):
    ce = pytest.importorskip("docpipe.inference.code_exec")
    monkeypatch.setattr(ce.config, "CODE_EXEC_URL", "")
    assert ce.is_enabled() is False
    out = ce.run_code("print(1)")
    assert out["ok"] is False and "disabled" in out["error"]


def test_format_exec_result_ok_and_error():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    assert "50" in llm._format_exec_result({"ok": True, "stdout": "50\n"})
    r = llm._format_exec_result({"ok": False, "error": "Boom"})
    assert "fehlgeschlagen" in r.lower() and "Boom" in r


def test_answer_from_sources_runs_react_compute_loop(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
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
    llm = pytest.importorskip("docpipe.inference.llm_client")
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
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_chat_json", lambda messages, temperature: dict(_HIJACKED))

    out = llm.answer_from_sources(_TASK_WITH_SCHEMA, _ITEMS)

    # Must stay distinguishable from an honest miss, or the next diagnosis starts
    # from scratch again.
    assert out["found"] is False and out["off_envelope"] is True


def test_answer_from_sources_treats_an_honest_miss_as_a_miss(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
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


def test_make_search_phrase_flags_a_recheck(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: {"phrase": "Impressum. Auftragnehmer: ...",
                                                "repetition": True})
    hist = [{"task": "Welche Firma hat den Plan erstellt?", "answer": "(keine belegte Antwort gefunden)"}]

    phrase, recheck = llm.make_search_phrase("Schau bitte noch einmal nach", history=hist)
    assert recheck is True and phrase.startswith("Impressum")

    # Without history there is nothing to re-check — the flag must not survive.
    phrase, recheck = llm.make_search_phrase("Schau bitte noch einmal nach", history=None)
    assert recheck is False


def test_make_search_phrase_fallbacks_return_no_recheck(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", True)
    assert llm.make_search_phrase("Frage?") == ("Frage?", False)

    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)

    def _boom(m, temperature):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(llm, "_chat_json", _boom)
    assert llm.make_search_phrase("Frage?", history=[{"task": "x"}]) == ("Frage?", False)


def test_retrieve_excludes_already_examined_owners(monkeypatch):
    fs = pytest.importorskip("docpipe.inference.faiss_store")
    rows = [(10, "section_text", "section", 1),
            (11, "section_text", "section", 2),
            (12, "table_text", "table", 7)]
    monkeypatch.setattr(fs.db, "get_candidate_faiss_ids", lambda c, d, t: rows)

    built = {}

    def fake_build(index, id_to_pos, faiss_ids):
        built["ids"] = faiss_ids
        return object()

    import numpy as np
    monkeypatch.setattr(fs, "build_subindex", fake_build)
    monkeypatch.setattr(fs, "search_subindex",
                        lambda sub, q, k: (np.ones((1, len(built["ids"]))),
                                           np.arange(len(built["ids"])).reshape(1, -1)))

    hits = fs.retrieve(None, None, {10: 0, 11: 1, 12: 2}, 1, ["section_text"], None, 50,
                       content_fetcher=lambda c, k, i: {"owner_kind": k, "owner_id": i},
                       exclude={("section", 1), ("table", 7)})

    # An excluded owner must not even enter the sub-index, let alone the hits.
    assert built["ids"] == [11]
    assert [(h["owner_kind"], h["owner_id"]) for h in hits] == [("section", 2)]


def test_phrase_prompt_forbids_invented_names_but_keeps_invented_quantities():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    p = llm.PHRASE_SYSTEM_PROMPT
    # An invented firm/address in the anchor pulls the search towards towns that
    # do not occur in the plan: median rank of the imprint section 37 -> 0 over
    # 9 documents. Quantities stay invented — a wrong number costs nothing.
    assert "erfinde KEINEN" in p and "Eigenname" in p
    assert "plausiblen Wert" in p
    assert "GmbH" not in p               # no invented firm in the example either


def test_answer_from_sources_attaches_labelled_crops(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_image_part",
                        lambda path: {"type": "image_url",
                                      "image_url": {"url": f"data:{path}"}})
    sent = {}

    def fake_chat_json(messages, temperature):
        sent["content"] = messages[0]["content"]
        return {"found": True, "complete": True, "answer": "ca. 650 GWh (abgelesen)",
                "supports": [{"index": 1, "image": True,
                              "reading": "Erdgas-Balken 2035: ca. 650 GWh/a"}]}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    items = [{"index": 0, "source": "s0", "text": "t0"},
             {"index": 1, "source": "s1", "text": "t1"}]

    out = llm.answer_from_sources("Gas 2035?", items, images={1: "b.png", 0: "a.png"})

    content = sent["content"]
    # Multimodal content array: text first, then per crop a label + the image,
    # in index order — the label is what lets a "image" support cite its index.
    assert isinstance(content, list) and content[0]["type"] == "text"
    assert [p.get("text") for p in content if p["type"] == "text"][1:] == \
           ["Bild zum Auszug index=0:", "Bild zum Auszug index=1:"]
    assert out["attached_images"] == [0, 1]

    out = llm.answer_from_sources("Gas 2035?", items)
    # Without crops the message must stay a plain string (gateway compatibility).
    assert isinstance(sent["content"], str)
    assert out["attached_images"] == []


def test_visual_reading_requires_an_actually_attached_image():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    s = {"index": 1, "image": True, "reading": "Erdgas-Balken 2035: ca. 650 GWh/a"}
    assert llm.visual_reading(s, {1}) == "Erdgas-Balken 2035: ca. 650 GWh/a"
    # A "image" support for a crop that was never sent could launder parametric
    # knowledge past the grounding gate — must die here.
    assert llm.visual_reading(s, {0, 2}) is None
    assert llm.visual_reading({"index": 1, "image": True, "reading": "650"}, {1}) is None
    assert llm.visual_reading({"index": 1, "quote": "text"}, {1}) is None


def test_read_off_image_returns_parsed_reading(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_image_part",
                        lambda path, max_side=None, png=False: {"type": "image_url",
                                                                "image_url": {"url": "d"}})
    sent = {}

    def fake_chat_json(messages, temperature):
        sent["content"] = messages[0]["content"]
        return {"reading": "Erdgas-Segment 2035: ca. 600 GWh/a",
                "value": 600.0, "unit": "GWh/a", "confidence": "hoch"}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    ro = llm.read_off_image("Gas 2035?", "chart.png", "Erdgas-Balken 2035")
    assert ro["value"] == 600.0
    # Exactly ONE image in the focused call — that is the whole point.
    assert sum(1 for p in sent["content"] if p.get("type") == "image_url") == 1


def test_read_off_image_splices_the_value_into_an_echoed_reading(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_image_part",
                        lambda path, max_side=None, png=False: {"type": "image_url",
                                                                "image_url": {"url": "d"}})
    # Seen live: "reading" just echoes the hint, the number sits only in
    # "value" — a revision fed the bare sentence has nothing to correct with.
    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: {"reading": "Graues Segment 2035 in Abb. 85",
                                                "value": 600.0, "unit": "GWh/a",
                                                "confidence": "hoch"})
    ro = llm.read_off_image("Gas 2035?", "c.png", "Graues Segment 2035 in Abb. 85")
    assert "600" in ro["reading"] and "GWh/a" in ro["reading"]

    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: (_ for _ in ()).throw(RuntimeError("down")))
    assert llm.read_off_image("Gas 2035?", "chart.png", "x") is None


def test_read_off_image_retries_when_task_schema_hijacks(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_image_part",
                        lambda path, max_side=None, png=False: {"type": "image_url",
                                                                "image_url": {"url": "d"}})
    calls = []

    def fake_chat_json(messages, temperature):
        calls.append(messages[0]["content"][0]["text"])
        if len(calls) == 1:                # the task's own format spec wins
            return {"amount": 1000.0, "unit": "GWh/a"}
        return {"reading": "Erdgas 2035: ca. 600 GWh/a", "value": 600.0,
                "unit": "GWh/a", "confidence": "hoch"}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    ro = llm.read_off_image('Gas 2035? Als JSON {"amount":float}', "c.png", "Erdgas-Balken")
    # Without the retry the hijacked reply reads as "no reading" and the wrong
    # inline value survives — the exact bug seen live.
    assert len(calls) == 2 and llm._READOFF_CORRECTION in calls[1]
    assert ro["value"] == 600.0


def test_revise_with_readings_falls_back_to_the_original(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: {"answer": "korrigiert: 600 GWh/a"})
    assert llm.revise_with_readings("t", "alt: 1200", ["Abb 85: 600 GWh/a"]) \
        == "korrigiert: 600 GWh/a"
    # A failed revision must never eat the answer that already exists.
    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: (_ for _ in ()).throw(RuntimeError("down")))
    assert llm.revise_with_readings("t", "alt: 1200", ["r"]) == "alt: 1200"
    assert llm.revise_with_readings("t", "alt", []) == "alt"


def test_readoff_prompt_forbids_total_for_segment():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    # The observed failure mode: a stacked bar's total height returned as one
    # segment's value. The focused prompt must address it head-on.
    assert "Gesamthöhe" in llm.READOFF_PROMPT and "Differenz" in llm.READOFF_PROMPT


def test_answer_prompt_defines_the_image_support_contract():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    tail = llm._ANSWER_PROMPT_TAIL
    assert '"image"' in tail and '"reading"' in tail
    # Read-off values must carry the literal marker phrase in the answer; the
    # app additionally appends a deterministic note when the model forgets.
    assert "aus der Abbildung abgelesen" in tail and "Schätzwert" in tail


def test_answer_prompt_scopes_task_format_specs_to_the_answer_field():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    tail = llm._ANSWER_PROMPT_TAIL.lower()
    # Measured on the live model: without this the envelope is lost 4/4 times for
    # a task carrying its own JSON schema, with it 4/4 times correct.
    assert "formatvorgaben" in tail and '"answer"' in llm._ANSWER_PROMPT_TAIL


def test_history_context_includes_recent_turns_but_frames_as_non_source():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    hist = [{"task": "Wer hat den Plan erstellt?", "phrase": "anker1", "answer": "Firma X"},
            {"task": "Und der Projektleiter?", "phrase": "anker2", "answer": "Herr Y"}]
    ctx = llm._history_context(hist, limit=5)
    assert "Firma X" in ctx and "Und der Projektleiter?" in ctx and "anker2" in ctx
    assert "keine faktenquelle" in ctx.lower()          # framed as reference-only
    assert llm._history_context([]) == "" and llm._history_context(None) == ""


def test_history_context_caps_to_limit():
    llm = pytest.importorskip("docpipe.inference.llm_client")
    hist = [{"task": f"Frage {i}", "answer": f"A{i}"} for i in range(8)]
    ctx = llm._history_context(hist, limit=5)
    assert "Frage 7" in ctx and "Frage 2" not in ctx       # only the last 5


def test_answer_from_sources_no_action_no_compute(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_chat_json",
                        lambda messages, temperature: {"found": True, "complete": True,
                                                       "answer": "direkt", "supports": []})
    # no code_runner → the compute hint is never added and compute stays empty
    out = llm.answer_from_sources("x", [{"index": 0, "source": "s", "text": "t"}])
    assert out["answer"] == "direkt"
    assert out["compute"] == []


def test_fetching_a_table_owner_costs_one_statement(corpus):
    """A harvest fetches over a thousand owners per document off an
    NFS-hosted database. This used to be four statements per table — the row,
    then the same Sections row twice, then the document's filename."""
    conn = db.connect_readonly(corpus)
    statements = []
    conn.set_trace_callback(statements.append)
    content = db.fetch_owner_content(conn, "table", 1)
    conn.set_trace_callback(None)

    assert content["section_title"] == "Wärmebedarf"
    assert content["image_path"] == "doc/images/p12_tbl0.png"
    assert len(statements) == 1, statements


def test_compare_answers_keeps_the_answers_when_the_call_fails(monkeypatch):
    """The per-document answers are grounded and already on screen. A failed
    comparison must cost the comparison, not the answers."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    plans = [{"label": "Kassel", "answer": "1 Prozent."},
             {"label": "Leipzig", "answer": None}]
    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: {"comparison": "K 1, L nichts."})
    assert llm.compare_answers("Rate?", plans) == "K 1, L nichts."
    monkeypatch.setattr(llm, "_chat_json",
                        lambda m, temperature: (_ for _ in ()).throw(RuntimeError("down")))
    assert llm.compare_answers("Rate?", plans) is None
    # An empty comparison is no comparison either.
    monkeypatch.setattr(llm, "_chat_json", lambda m, temperature: {"comparison": "  "})
    assert llm.compare_answers("Rate?", plans) is None


def test_compare_answers_sends_only_labels_and_answers(monkeypatch):
    """The one prompt on this screen that no citation backs. What it is handed
    is the whole guarantee: a source passage in here could become a statement
    about a plan that never said it."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    sent = {}

    def _chat(messages, temperature):
        sent["text"] = messages[0]["content"]
        return {"comparison": "V"}
    monkeypatch.setattr(llm, "_chat_json", _chat)
    llm.compare_answers("Rate?", [{"label": "Kassel", "answer": "1 Prozent."}])
    payload = json.loads(sent["text"][len(llm.COMPARE_PROMPT):].strip())
    assert payload == {"task": "Rate?",
                       "documents": [{"label": "Kassel", "answer": "1 Prozent."}]}


def test_compare_prompt_forbids_inventing_and_computing():
    """Three failure modes the answers cannot defend against, because the call
    sees no sources: filling an empty answer, converting a unit, and averaging
    across plans whose reference years differ."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    text = llm.COMPARE_PROMPT
    assert "null" in text and "rate nicht" in text
    assert "Rechne nichts um" in text
    assert "Bezugsjahre" in text and "vergleiche nicht" in text
    assert '{"comparison"' in text
