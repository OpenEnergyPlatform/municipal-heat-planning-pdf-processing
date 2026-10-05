"""How much of a stored table the PDF itself prints, counted without a model.

The promise, in one sentence: scripts/table_numbers_in_pdf.py reports, per
table, how many of the distinct numbers of the stored transcription stand in
the PDF text inside the table's stored frame, AND per parameter how many
harvested table values have their digits in that text, AND names the tables
and values it could not judge with the reason and leaves them out of every
share, AND changes nothing and refuses nothing it reads.

Each AND has its own tests, and each has a case built to break it: a number
the model misread, a page with no text layer, a harvest from a database that
was rebuilt since, a database that predates the bbox column, a corpus in which
nothing can be judged at all.
"""
import hashlib
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.chunking import database as DB                 # noqa: E402
from scripts import table_numbers_in_pdf as T                # noqa: E402

PARAM = "https://example.org/energy_consumption"
OTHER_PARAM = "https://example.org/share"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

class FakeFrames:
    """What PdfFrames answers, from a table of (file, page) -> the text of the
    frame, or the reason it cannot be read."""

    def __init__(self, frames):
        self.frames = frames
        self.asked: list = []
        self.closed = False

    def text(self, filename, page, rect):
        self.asked.append((filename, page, rect))
        got = self.frames.get((filename, page), T.NO_PDF)
        return (None, got) if got in T.REASONS else (got, None)

    def close(self):
        self.closed = True


def _table(block="p3_tbl0", markdown="| Erdgas | 1.234,5 |", page=3,
           bbox=((10, 20, 300, 200),), **more):
    table = {"id": block, "path": f"images/{block}.png", "page_number": page,
             "markdown": markdown}
    if bbox is not None:
        table["bbox"] = [list(r) for r in bbox]
    table.update(more)
    return table


def _database(kwp_db, tables, document=1):
    """The tables go into one section of *document*; returns (db path, the
    Tables.id of each, in the order given)."""
    db, con = kwp_db
    merged = {"sections": [{"title": "S", "content": "x", "page_number": 3,
                            "pages": [3], "segments": [], "tables": tables,
                            "figures": []}]}
    DB._insert_sections(document, merged, con)
    con.commit()
    ids = {block: table_id for table_id, block in con.execute(
        "SELECT t.id, t.block_id FROM Tables t JOIN Sections s ON "
        "t.section = s.id WHERE s.document = ?", (document,))}
    return db, [ids[t["id"]] for t in tables]


def _measure(db, frames, harvest=None, documents=None):
    connection = sqlite3.connect(db)
    try:
        return T.measure(connection, frames, harvest, documents)
    finally:
        connection.close()


def _row(report, block):
    return next(r for r in report["rows"] if r["block_id"] == block)


def _tuple(owner, value, parameter=PARAM, kind="table", document=1,
           block="p3_tbl0", **more):
    row = {"kind": "tuple", "parameter": parameter, "value": value,
           "tier": "visual_source", "quote": "| Erdgas | 1.234,5 |",
           "provenance": {"document_id": document, "owner_kind": kind,
                          "owner_id": owner, "block_id": block}}
    row.update(more)
    return row


def _harvest(directory, *plans):
    """One <plan>.jsonl per list of rows; a trace file beside them, which is
    not a plan, and a line that is not JSON, which is skipped."""
    directory.mkdir(parents=True, exist_ok=True)
    for n, rows in enumerate(plans):
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        (directory / f"plan{n}.jsonl").write_text(
            "this line is torn {\n" + text + "\n", encoding="utf-8")
    (directory / "plan0.trace.jsonl").write_text(
        json.dumps(_tuple(1, 99999)) + "\n", encoding="utf-8")
    return directory


# ---------------------------------------------------------------------------
# AND 1: per table, the numbers of the transcription against the frame
# ---------------------------------------------------------------------------

def test_a_table_whose_numbers_all_stand_in_the_frame_is_counted_whole(
        kwp_db):
    db, _ = _database(kwp_db, [_table(markdown="| Erdgas | 1.234,5 |\n"
                                                "| Solar | 12 |")])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "Erdgas 1.234,5 Solar 12"}))
    row = _row(report, "p3_tbl0")
    assert (row["numbers_in_transcription"], row["numbers_in_pdf_text"],
            row["missing"]) == (2, 2, [])
    assert report["tables"]["by_share"]["every number"] == 1


def test_a_number_the_model_misread_is_counted_as_not_in_the_pdf_text(
        kwp_db):
    """The transcription says 1.543, the PDF prints 1.534: one of two numbers
    stands in the frame, and the one that does not is named."""
    db, _ = _database(kwp_db, [_table(markdown="| Erdgas | 1.543 |\n"
                                                "| Solar | 12 |")])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "Erdgas 1.534 Solar 12"}))
    row = _row(report, "p3_tbl0")
    assert (row["numbers_in_transcription"], row["numbers_in_pdf_text"]) \
        == (2, 1)
    assert row["missing"] == ["1543"]
    assert report["tables"]["by_share"]["every number"] == 0
    assert report["tables"]["by_share"]["50 % to under 90 %"] == 1


def test_a_number_that_stands_in_six_cells_is_one_number_in_any_spelling(
        kwp_db):
    db, _ = _database(kwp_db, [_table(
        markdown="| a | 1.234,5 |\n| b | 1234,5 |\n| c | 1.234,5 |")])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "x 1234,5 y"}))
    row = _row(report, "p3_tbl0")
    assert (row["numbers_in_transcription"], row["numbers_in_pdf_text"]) \
        == (1, 1)


def test_the_frame_asked_is_the_stored_bbox_of_the_stored_page(kwp_db):
    db, _ = _database(kwp_db, [_table(page=3, bbox=((10, 20, 300, 200),))])
    frames = FakeFrames({("doc.pdf", 3): "1.234,5"})
    _measure(db, frames)
    assert frames.asked == [("doc.pdf", 3, (10, 20, 300, 200))]


def test_the_shares_are_taken_over_the_judged_tables_only(kwp_db):
    db, _ = _database(kwp_db, [
        _table("p3_tbl0", "| a | 11 |\n| b | 22 |"),
        _table("p4_tbl0", "| a | 33 |", page=4),          # no text layer
    ])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "11 22",
                                      ("doc.pdf", 4): T.NO_TEXT_LAYER}))
    t = report["tables"]
    assert (t["in_database"], t["judged"]) == (2, 1)
    # 33 is in no frame, and it is not counted against the table that was read
    assert (t["numbers_in_transcriptions"], t["numbers_in_pdf_text"]) == (2, 2)
    assert t["by_share"]["every number"] == 1


@pytest.mark.parametrize("reason", [T.NO_TEXT_LAYER, T.NO_TEXT_IN_FRAME,
                                    T.NO_PDF, T.UNREADABLE, T.PAGE_NOT_IN_PDF])
def test_a_frame_that_cannot_be_read_is_not_judged_and_not_a_miss(kwp_db,
                                                                  reason):
    db, _ = _database(kwp_db, [_table(markdown="| a | 77 |")])
    report = _measure(db, FakeFrames({("doc.pdf", 3): reason}))
    t = report["tables"]
    assert _row(report, "p3_tbl0")["not_judged"] == reason
    assert t["not_judged"] == {reason: 1}
    assert (t["judged"], t["numbers_in_transcriptions"],
            t["numbers_in_pdf_text"]) == (0, 0, 0)
    assert t["by_share"]["none"] == 0, "not judged is not a table with no hit"


@pytest.mark.parametrize("what,table,reason", [
    ("no transcription", {"markdown": None}, T.NO_TRANSCRIPTION),
    ("a blank transcription", {"markdown": "  "}, T.NO_TRANSCRIPTION),
    ("no number in it", {"markdown": "| Erdgas | Solar |"}, T.NO_NUMBERS),
    ("no bbox", {"bbox": None}, T.NO_BBOX),
    ("a bbox without area", {"bbox": ((5, 5, 5, 9),)}, T.NO_BBOX),
    ("no page", {"page": None}, T.NO_PAGE),
])
def test_a_table_the_stored_data_cannot_place_is_not_judged(kwp_db, what,
                                                            table, reason):
    db, _ = _database(kwp_db, [_table(**table)])
    frames = FakeFrames({("doc.pdf", 3): "1.234,5"})
    report = _measure(db, frames)
    assert _row(report, "p3_tbl0")["not_judged"] == reason, what
    assert report["tables"]["numbers_in_transcriptions"] == 0
    assert report["tables"]["judged"] == 0


def test_a_database_that_predates_the_bbox_column_has_no_table_to_judge(
        kwp_db):
    db, con = kwp_db
    con.execute("DROP TABLE Tables")
    con.execute('CREATE TABLE "Tables" ("id" INTEGER PRIMARY KEY, "section" '
                'INTEGER, "block_id" TEXT, "path" TEXT, "page_number" '
                'INTEGER, "caption" TEXT, "markdown" TEXT)')
    con.execute("INSERT INTO Sections (id, document, section_number, title) "
                "VALUES (5, 1, 0, 'S')")
    con.execute("INSERT INTO Tables VALUES (1, 5, 'p3_tbl0', 'a.png', 3, "
                "NULL, '| a | 5 |')")
    con.commit()
    report = _measure(db, FakeFrames({("doc.pdf", 3): "5"}))
    assert report["tables"]["not_judged"] == {T.NO_BBOX: 1}


def test_a_document_filter_leaves_the_other_documents_out(kwp_db):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'two.pdf', 9)")
    con.commit()
    _database(kwp_db, [_table("p3_tbl0")], document=1)
    _database(kwp_db, [_table("p3_tbl1")], document=2)
    frames = FakeFrames({("doc.pdf", 3): "1.234,5", ("two.pdf", 3): "1.234,5"})
    report = _measure(db, frames, documents={2})
    assert [r["block_id"] for r in report["rows"]] == ["p3_tbl1"]
    assert {f for f, _, _ in frames.asked} == {"two.pdf"}


def test_the_decimal_mark_of_the_profile_decides_what_a_number_is(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    assert T.numbers_of("| a | 3,251 |") == {"3.251"}
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    assert T.numbers_of("| a | 3,251 |") == {"3251"}


# ---------------------------------------------------------------------------
# frame_of: the stored bbox
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stored,frame", [
    ("[[10, 20, 300, 200]]", (10, 20, 300, 200)),
    ("[[10, 20, 100, 50], [90, 40, 300, 200]]", (10, 20, 300, 200)),
    ("[[10, 20, 100, 50], [1, 1, 1, 9]]", (10, 20, 100, 50)),
    ("[[10, 20, 100]]", None),
    ("[[10, 20, 10, 60]]", None),
    ("[[10, 20, \"a\", 60]]", None),
    ("[[true, 20, 100, 60]]", None),
    ("[]", None),
    ("{\"x\": 1}", None),
    ("not json", None),
    (None, None),
    ("", None),
])
def test_frame_of_reads_the_stored_rect_and_nothing_else(stored, frame):
    assert T.frame_of(stored) == frame


# ---------------------------------------------------------------------------
# PdfFrames, against the library's own shape
# ---------------------------------------------------------------------------

class _Page:
    def __init__(self, whole, frame):
        self.whole, self.frame = whole, frame

    def get_text(self, kind, clip=None):
        assert kind == "text"
        return self.frame if clip is not None else self.whole


class _Document:
    opened: list = []

    def __init__(self, pages):
        self.pages, self.page_count, self.closed = pages, len(pages), False

    def load_page(self, index):
        return self.pages[index]

    def close(self):
        self.closed = True


@pytest.fixture
def library(monkeypatch, tmp_path):
    """A stand-in for PyMuPDF and the files it is asked to open."""
    documents: dict = {}
    made: list = []

    def open_(path):
        name = Path(path).name
        if documents.get(name) is Exception:
            raise RuntimeError("cannot open")
        document = _Document(documents[name])
        made.append(document)
        return document

    monkeypatch.setitem(sys.modules, "fitz", types.SimpleNamespace(
        open=open_, Rect=lambda *a: tuple(a)))

    def put(name, pages):
        (tmp_path / name).write_bytes(b"%PDF")
        documents[name] = pages
    library.put, library.made = put, made
    return library


def test_the_text_inside_the_frame_is_what_comes_back(library, tmp_path):
    library.put("a.pdf", [_Page("whole page", "inside the frame")])
    frames = T.PdfFrames(tmp_path)
    assert frames.text("a.pdf", 1, (0, 0, 1, 1)) == ("inside the frame", None)
    frames.close()


def test_the_pages_are_one_based_and_a_page_beyond_the_end_is_said_so(
        library, tmp_path):
    library.put("a.pdf", [_Page("p1", "one"), _Page("p2", "two")])
    frames = T.PdfFrames(tmp_path)
    assert frames.text("a.pdf", 2, (0, 0, 1, 1)) == ("two", None)
    assert frames.text("a.pdf", 3, (0, 0, 1, 1)) == (None, T.PAGE_NOT_IN_PDF)
    assert frames.text("a.pdf", 0, (0, 0, 1, 1)) == (None, T.PAGE_NOT_IN_PDF)


def test_a_page_with_text_but_none_in_the_frame_is_told_from_one_with_none(
        library, tmp_path):
    library.put("a.pdf", [_Page("text elsewhere", "  \n"), _Page(" ", "")])
    frames = T.PdfFrames(tmp_path)
    assert frames.text("a.pdf", 1, (0, 0, 1, 1)) == (None, T.NO_TEXT_IN_FRAME)
    assert frames.text("a.pdf", 2, (0, 0, 1, 1)) == (None, T.NO_TEXT_LAYER)


def test_a_missing_file_and_an_unreadable_one_are_two_reasons(library,
                                                              tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"x")
    library.put("a.pdf", [])
    frames = T.PdfFrames(tmp_path)
    assert frames.text("gone.pdf", 1, (0, 0, 1, 1)) == (None, T.NO_PDF)
    assert frames.text(None, 1, (0, 0, 1, 1)) == (None, T.NO_PDF)
    # a file the library cannot open
    (tmp_path / "bad.pdf").write_bytes(b"x")
    library.put("bad.pdf", Exception)
    assert frames.text("bad.pdf", 1, (0, 0, 1, 1)) == (None, T.UNREADABLE)


def test_one_document_is_held_open_at_a_time(library, tmp_path):
    library.put("a.pdf", [_Page("a", "a")])
    library.put("b.pdf", [_Page("b", "b")])
    frames = T.PdfFrames(tmp_path)
    frames.text("a.pdf", 1, (0, 0, 1, 1))
    frames.text("a.pdf", 1, (0, 0, 1, 1))
    assert len(library.made) == 1                 # not opened per table
    frames.text("b.pdf", 1, (0, 0, 1, 1))
    assert [d.closed for d in library.made] == [True, False]
    frames.close()
    assert library.made[1].closed


# ---------------------------------------------------------------------------
# AND 2: per parameter, the digits of the values read out of a table
# ---------------------------------------------------------------------------

def _book(report, parameter=PARAM):
    return report["harvest"]["parameters"][parameter]


def test_a_value_whose_digits_stand_in_the_frame_is_counted_and_one_whose_do_not_is_not(
        kwp_db, tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| Erdgas | 1.234,5 |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [
        _tuple(table, 1234.5), _tuple(table, 1234.6), _tuple(table, 1234.5)]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): "Erdgas 1.234,5"}),
                      harvest)
    book = _book(report)
    assert (book["tuples"], book["digits_in_pdf_text"],
            book["digits_not_in_pdf_text"]) == (3, 2, 1)


def test_each_parameter_is_counted_by_itself(kwp_db, tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 1.234,5 |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [
        _tuple(table, 1234.5), _tuple(table, 55, parameter=OTHER_PARAM)]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): "1.234,5"}), harvest)
    assert _book(report)["digits_in_pdf_text"] == 1
    assert _book(report, OTHER_PARAM)["digits_not_in_pdf_text"] == 1


def test_values_are_counted_apart_where_the_page_cannot_say_anything_of_them(
        kwp_db, tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 1.234,5 |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [
        _tuple(table, 1234.5, computed=True),         # sandbox, not the page
        _tuple(table, "Erdgas"),                      # a wording, no digits
        _tuple(table, True),                          # not a number either
        _tuple(table, 1234.5, kind="figure"),         # not from a table
        _tuple(table, 1234.5, kind="section"),
    ]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): "1.234,5"}), harvest)
    book = _book(report)
    assert book["tuples"] == 3
    assert (book[T.COMPUTED], book[T.NOT_A_NUMBER]) == (1, 2)
    assert book.get("digits_in_pdf_text", 0) == 0
    assert report["harvest"]["tuples_by_owner"] == {
        "table": 3, "figure": 1, "section": 1}


def test_a_harvest_of_a_rebuilt_database_is_not_read_as_a_table_of_this_one(
        kwp_db, tmp_path):
    """The harvest names a table by Tables.id, which a rebuild renews. An id
    that is no table here, or is a table of another block, says nothing about
    this one: counting it would put a number against the wrong frame."""
    db, (one, two) = _database(kwp_db, [
        _table("p3_tbl0", "| a | 11 |"), _table("p3_tbl1", "| a | 22 |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [
        _tuple(99999, 11),                                  # no such table
        _tuple(two, 22, block="p3_tbl0"),                   # another block
        _tuple(two, 22, document=7, block="p3_tbl1"),       # another document
        _tuple(two, 22, block="p3_tbl1"),                   # the real one
    ]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): "11 22"}), harvest)
    book = _book(report)
    assert book["tuples"] == 4
    assert book[T.NOT_IN_DATABASE] == 1
    assert book[T.OTHER_TABLE] == 2
    assert book["digits_in_pdf_text"] == 1


def test_a_value_of_a_table_whose_frame_cannot_be_read_is_not_a_miss(
        kwp_db, tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 77 |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [_tuple(table, 77)]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): T.NO_TEXT_LAYER}),
                      harvest)
    book = _book(report)
    assert book[T.TABLE_NOT_JUDGED] == 1
    assert book.get("digits_not_in_pdf_text", 0) == 0


def test_a_value_is_compared_with_the_frame_even_where_the_table_has_no_numbers(
        kwp_db, tmp_path):
    """The transcription holds no number, so (a) cannot count the table. A
    value read out of it is still compared with what the PDF prints there."""
    db, (table,) = _database(kwp_db, [_table(markdown="| Erdgas | Solar |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [_tuple(table, 41)]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): "Erdgas 41"}), harvest)
    assert _row(report, "p3_tbl0")["not_judged"] == T.NO_NUMBERS
    assert _book(report)["digits_in_pdf_text"] == 1


def test_only_the_plans_are_read_and_a_torn_line_loses_nothing(kwp_db,
                                                               tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 5 |")])
    directory = _harvest(tmp_path / "h", [_tuple(table, 5)],
                         [_tuple(table, 5)])
    harvest = T.read_harvest(directory)
    assert harvest["files"] == 2          # the trace file is not a plan
    assert harvest["tuples"] == 2         # and the torn line is skipped
    report = _measure(db, FakeFrames({("doc.pdf", 3): "5"}), harvest)
    assert _book(report)["tuples"] == 2


def test_the_documents_asked_for_limit_the_tuples_too(kwp_db, tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 5 |")])
    directory = _harvest(tmp_path / "h", [_tuple(table, 5),
                                          _tuple(table, 5, document=2)])
    assert T.read_harvest(directory, {1})["tuples"] == 1
    assert T.read_harvest(directory)["tuples"] == 2


# ---------------------------------------------------------------------------
# AND 3: what it could not judge is named, and the lines say what they count
# ---------------------------------------------------------------------------

def test_the_report_names_every_reason_with_its_count_in_tables(kwp_db):
    db, _ = _database(kwp_db, [
        _table("p3_tbl0", "| a | 1 |"),
        _table("p3_tbl1", "| a | 2 |", page=4),
        _table("p3_tbl2", None)])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "1",
                                      ("doc.pdf", 4): T.NO_TEXT_LAYER}))
    text = "\n".join(T.render(report, 5))
    assert f"1 tables: {T.REASONS[T.NO_TEXT_LAYER]}" in text.replace(
        "      ", " ").replace("  ", " ")
    assert T.REASONS[T.NO_TRANSCRIPTION] in text
    assert "judged: 1 tables; not judged: 2 tables" in text


def test_every_count_in_the_report_says_what_it_counts(kwp_db, tmp_path):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 1.234,5 |")])
    harvest = T.read_harvest(_harvest(tmp_path / "h", [_tuple(table, 1234.5)]))
    report = _measure(db, FakeFrames({("doc.pdf", 3): "1.234,5"}), harvest)
    lines = T.render(report, 5)
    text = "\n".join(lines)
    assert "tables in the database: 1 (1 documents)" in text
    assert ("1 numbers in the transcriptions (each counted once per table), "
            "1 of them") in text
    assert "harvest: 1 plans, 1 tuples" in text
    assert "1 tuples from tables" in text
    # no bare number: each line that carries a count names its unit
    units = ("tables", "documents", "numbers", "tuples", "plans")
    for line in lines:
        if any(ch.isdigit() for ch in line) and not line.startswith(
                "decimal"):
            assert any(unit in line for unit in units), line


def test_the_tables_with_the_lowest_share_are_listed_first(kwp_db):
    db, _ = _database(kwp_db, [
        _table("p3_tbl0", "| a | 1 |\n| b | 2 |"),
        _table("p3_tbl1", "| a | 3 |\n| b | 4 |")])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "1 2 3"}))
    assert [r["block_id"] for r in T.worst(report, 1)] == ["p3_tbl1"]


# ---------------------------------------------------------------------------
# AND 4: it changes nothing and refuses nothing
# ---------------------------------------------------------------------------

def _digest(*paths):
    out = {}
    for path in paths:
        files = [path] if path.is_file() else sorted(path.rglob("*"))
        for f in files:
            if f.is_file():
                out[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def _run(monkeypatch, capsys, *argv, frames=None):
    monkeypatch.setattr(T, "PdfFrames", lambda root: frames or FakeFrames({}))
    code = T.main([str(a) for a in argv])
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def test_it_changes_neither_the_database_nor_the_harvest_nor_the_folder(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, (table,) = _database(kwp_db, [_table(markdown="| a | 1.234,5 |")])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    (pdfs / "doc.pdf").write_bytes(b"%PDF")
    harvest = _harvest(tmp_path / "h", [_tuple(table, 1234.5)])
    before = _digest(db, harvest, pdfs)
    folder_before = sorted(p.name for p in db.parent.iterdir())
    code, out, _ = _run(monkeypatch, capsys, db, pdfs, "--harvest", harvest,
                        "--json", tmp_path / "counts.json",
                        frames=FakeFrames({("doc.pdf", 3): "1.234,5"}))
    assert code == 0
    assert _digest(db, harvest, pdfs) == before
    # the one new file is the one asked for
    assert sorted(p.name for p in db.parent.iterdir()) \
        == sorted(folder_before + ["counts.json"])
    counts = json.loads((tmp_path / "counts.json").read_text("utf-8"))
    assert counts["tables"]["numbers_in_pdf_text"] == 1
    assert counts["rows"][0]["block_id"] == "p3_tbl0"
    assert counts["harvest"]["parameters"][PARAM]["digits_in_pdf_text"] == 1


def test_the_database_is_opened_for_reading_only(kwp_db, tmp_path):
    db, _ = _database(kwp_db, [_table()])
    kwp_db[1].close()
    connection = sqlite3.connect(T.schema.readonly_uri(db), uri=True)
    with pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM Tables")
    connection.close()


def test_a_corpus_in_which_nothing_can_be_judged_is_reported_not_refused(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, (table, *_) = _database(kwp_db, [
        _table("p3_tbl0", "| a | 5 |"), _table("p3_tbl1", None),
        _table("p3_tbl2", bbox=None)])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    harvest = _harvest(tmp_path / "h", [_tuple(424242, 5), _tuple(table, 5)])
    code, out, err = _run(monkeypatch, capsys, db, pdfs, "--harvest", harvest,
                          frames=FakeFrames({}))
    assert code == 0 and err == ""
    assert "judged: 0 tables; not judged: 3 tables" in out
    assert T.REASONS[T.NO_PDF] in out


def test_a_database_without_tables_is_a_usage_error_not_a_traceback(
        tmp_path, monkeypatch, capsys):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    code, _, err = _run(monkeypatch, capsys, db, pdfs)
    assert code == 1 and "not a corpus database" in err


def test_what_it_cannot_open_at_all_it_says_and_stops_before_reading(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, _ = _database(kwp_db, [_table()])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _run(monkeypatch, capsys, tmp_path / "none.db", pdfs)[0] == 1
    assert _run(monkeypatch, capsys, db, tmp_path / "nowhere")[0] == 1
    code, _, err = _run(monkeypatch, capsys, db, pdfs, "--harvest", empty)
    assert code == 1 and "no harvest" in err


def test_the_decimal_mark_of_a_named_profile_reaches_the_comparison(
        kwp_db, tmp_path, monkeypatch, capsys):
    """'3,251' is 3.251 where the comma is the decimal mark and 3251 where it
    groups. The PDF prints 3251: found under one profile, not under the other."""
    db, _ = _database(kwp_db, [_table(markdown="| a | 3,251 |")])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    frames = FakeFrames({("doc.pdf", 3): "a 3251"})
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    _, kwp_out, _ = _run(monkeypatch, capsys, db, pdfs, "--profile", "kwp",
                         frames=frames)
    _, scenarios_out, _ = _run(monkeypatch, capsys, db, pdfs, "--profile",
                               "scenarios", frames=frames)
    assert "0 of them in the PDF text" in kwp_out
    assert "1 of them in the PDF text" in scenarios_out
    assert "decimal mark of the documents: ','" in kwp_out
    assert "decimal mark of the documents: '.'" in scenarios_out


def test_the_command_opens_the_database_for_reading_only(
        kwp_db, tmp_path, monkeypatch, capsys):
    """The read-only open is the command's own. The test above holds the
    helper; this holds that the command uses it: a write tried on the very
    connection the measuring runs on is refused by SQLite."""
    db, _ = _database(kwp_db, [_table()])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    outcomes, measure = [], T.measure

    def probe(connection, *args, **kwargs):
        try:
            connection.execute("DELETE FROM Tables")
            outcomes.append("written")
        except sqlite3.OperationalError as exc:
            outcomes.append(str(exc))
        return measure(connection, *args, **kwargs)

    monkeypatch.setattr(T, "measure", probe)
    code, out, _ = _run(monkeypatch, capsys, db, pdfs,
                        frames=FakeFrames({("doc.pdf", 3): "1.234,5"}))
    assert code == 0
    assert outcomes == ["attempt to write a readonly database"]
    assert "tables in the database: 1 (1 documents)" in out


def test_the_command_lets_go_of_the_pdf_it_held_whether_the_run_ends_or_fails(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, _ = _database(kwp_db, [_table()])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    done = FakeFrames({("doc.pdf", 3): "1.234,5"})
    assert _run(monkeypatch, capsys, db, pdfs, frames=done)[0] == 0
    assert done.closed

    def fails(*args, **kwargs):
        raise sqlite3.DatabaseError("the file is damaged")

    monkeypatch.setattr(T, "measure", fails)
    broken = FakeFrames({})
    assert _run(monkeypatch, capsys, db, pdfs, frames=broken)[0] == 1
    assert broken.closed


def test_the_documents_asked_for_limit_the_tables_and_the_harvest_of_a_run(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'two.pdf', 9)")
    con.commit()
    _, (one,) = _database(kwp_db, [_table("p3_tbl0")], document=1)
    _, (two,) = _database(kwp_db, [_table("p3_tbl1")], document=2)
    con.close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    harvest = _harvest(tmp_path / "h", [
        _tuple(one, 1234.5, document=1, block="p3_tbl0"),
        _tuple(two, 1234.5, document=2, block="p3_tbl1")])
    frames = FakeFrames({("doc.pdf", 3): "1.234,5",
                         ("two.pdf", 3): "1.234,5"})
    _, out, _ = _run(monkeypatch, capsys, db, pdfs, "--harvest", harvest,
                     "--document", 2, frames=frames)
    assert "tables in the database: 1 (1 documents)" in out
    assert "harvest: 1 plans, 1 tuples" in out
    assert {f for f, _, _ in frames.asked} == {"two.pdf"}


def test_as_many_of_the_lowest_tables_are_listed_as_asked(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, _ = _database(kwp_db, [
        _table("p3_tbl0", "| a | 1 |\n| b | 2 |"),
        _table("p4_tbl0", "| a | 3 |", page=4),
        _table("p5_tbl0", "| a | 4 |", page=5)])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    frames = FakeFrames({("doc.pdf", page): "words only" for page in (3, 4, 5)})
    _, out, _ = _run(monkeypatch, capsys, db, pdfs, "--worst", 2,
                     frames=frames)
    assert "the 2 judged tables with the lowest share:" in out
    assert out.count(" numbers; not in the PDF text:") == 2


def test_the_numbers_a_table_misses_are_listed_up_to_a_line(kwp_db):
    cells = [str(100 + n) for n in range(T.MISSING_SHOWN + 5)]
    db, _ = _database(kwp_db, [_table(
        markdown="| " + " | ".join(cells) + " |")])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "no digits here"}))
    row = _row(report, "p3_tbl0")
    assert row["numbers_in_transcription"] == T.MISSING_SHOWN + 5
    assert row["numbers_in_pdf_text"] == 0
    assert len(row["missing"]) == T.MISSING_SHOWN


def test_a_number_that_stands_in_two_tables_is_counted_in_each(kwp_db):
    """The total of the report says each number is counted once per table, so
    the same 5 in two tables is two numbers and not one."""
    db, _ = _database(kwp_db, [_table("p3_tbl0", "| a | 5 |"),
                               _table("p4_tbl0", "| a | 5 |", page=4)])
    report = _measure(db, FakeFrames({("doc.pdf", 3): "5",
                                      ("doc.pdf", 4): "5"}))
    assert report["tables"]["numbers_in_transcriptions"] == 2
    assert report["tables"]["numbers_in_pdf_text"] == 2


def test_a_profile_it_does_not_know_is_said_and_stops_before_reading(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, _ = _database(kwp_db, [_table()])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    # set first, so that the profile the command binds is undone afterwards
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    code, out, err = _run(monkeypatch, capsys, db, pdfs, "--profile",
                          "no_such_profile")
    assert code == 1 and out == ""
    assert "unknown profile 'no_such_profile'" in err


def test_a_missing_pymupdf_is_said_and_stops_before_reading(
        kwp_db, tmp_path, monkeypatch, capsys):
    db, _ = _database(kwp_db, [_table()])
    kwp_db[1].close()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    monkeypatch.setitem(sys.modules, "fitz", None)   # an import that fails
    code, out, err = _run(monkeypatch, capsys, db, pdfs)
    assert code == 1 and out == ""
    assert "PyMuPDF is not installed" in err


# ---------------------------------------------------------------------------
# The pieces, one by one
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("found,numbers,name", [
    (3, 3, "every number"), (10, 10, "every number"),
    (9, 10, "90 % to under 100 %"), (5, 10, "50 % to under 90 %"),
    (4, 10, "under 50 %, some"), (1, 10, "under 50 %, some"),
    (0, 10, "none"),
])
def test_a_table_is_put_in_the_class_of_its_share(found, numbers, name):
    assert T.share_class(found, numbers) == name


def test_frame_numbers_gives_the_numbers_of_the_text_or_the_reason_it_has_none():
    frames = FakeFrames({("doc.pdf", 3): "Erdgas 1.234,5 und 12 Anlagen",
                         ("doc.pdf", 4): "Erdgas ohne Zahl",
                         ("doc.pdf", 5): T.NO_TEXT_LAYER})
    table = {"filename": "doc.pdf", "page": 3,
             "bbox": json.dumps([[0, 0, 5, 5]])}
    assert T.frame_numbers(frames, table) == ({"1234.5", "12"}, None)
    # text without a digit is a frame that was read and holds no number
    assert T.frame_numbers(frames, dict(table, page=4)) == (set(), None)
    assert T.frame_numbers(frames, dict(table, page=5)) \
        == (None, T.NO_TEXT_LAYER)
    # nothing is asked of the PDF where the stored data cannot place the table
    asked = len(frames.asked)
    assert T.frame_numbers(frames, dict(table, page=None)) == (None, T.NO_PAGE)
    assert T.frame_numbers(frames, dict(table, bbox=None)) == (None, T.NO_BBOX)
    assert len(frames.asked) == asked


def test_table_rows_come_in_document_and_page_order_and_can_be_limited(
        kwp_db):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'two.pdf', 9)")
    con.commit()
    _database(kwp_db, [_table("p9_tbl0", page=9), _table("p2_tbl0", page=2)],
              document=2)
    _database(kwp_db, [_table("p5_tbl0", page=5)], document=1)
    got = [(r["document"], r["filename"], r["page"], r["block_id"])
           for r in T.table_rows(con)]
    assert got == [(1, "doc.pdf", 5, "p5_tbl0"), (2, "two.pdf", 2, "p2_tbl0"),
                   (2, "two.pdf", 9, "p9_tbl0")]
    assert [r["block_id"] for r in T.table_rows(con, {2})] \
        == ["p2_tbl0", "p9_tbl0"]
    assert json.loads(next(iter(T.table_rows(con)))["bbox"]) \
        == [[10, 20, 300, 200]]


def test_judge_values_books_each_value_in_exactly_one_place():
    from collections import Counter, defaultdict
    table = {"document": 1, "block_id": "p3_tbl0"}
    entry = {"parameter": PARAM, "number": "1234.5", "computed": False,
             "document": 1, "block_id": "p3_tbl0"}
    cases = [
        (dict(entry), {"1234.5"}, "digits_in_pdf_text"),
        (dict(entry), {"99"}, "digits_not_in_pdf_text"),
        (dict(entry), None, T.TABLE_NOT_JUDGED),
        (dict(entry, computed=True), {"1234.5"}, T.COMPUTED),
        (dict(entry, number=None), {"1234.5"}, T.NOT_A_NUMBER),
        (dict(entry, block_id="p9_tbl9"), {"1234.5"}, T.OTHER_TABLE),
        (dict(entry, document=2), {"1234.5"}, T.OTHER_TABLE),
    ]
    for tuple_, frame, expected in cases:
        counts = defaultdict(Counter)
        T.judge_values(table, frame, [tuple_], counts)
        assert dict(counts[PARAM]) == {"tuples": 1, expected: 1}, expected
