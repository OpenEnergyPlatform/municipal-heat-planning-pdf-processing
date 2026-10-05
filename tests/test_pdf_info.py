"""A PDF says its own title and date, and the built-in catalog shows them.

Promised: the folder source reads the information dictionary of each PDF and
keeps its title and its creation date in the built-in profile's DocumentMeta;
AND the catalog shows the PDF's title when it has one, else the file stem,
and the date beside it; AND a PDF whose dictionary is empty or cannot be read
is ingested as before, with the file stem for a title and no date, and the
run does not stop.
"""
import sqlite3
from pathlib import Path

import pytest

from docpipe.ingest import SourceDoc, pdf_info
from docpipe.ingest import pipeline as ingest
from docpipe.ingest.folder import FolderSource
from docpipe.inference.catalog import load_catalog
from docpipe.profile import load_profile
from docpipe.store import schema

DEFAULT = load_profile("default")


class FakeDocument:
    def __init__(self, metadata):
        self._metadata = metadata
        self.closed = False

    @property
    def metadata(self):
        if isinstance(self._metadata, Exception):
            raise self._metadata
        return self._metadata

    def close(self):
        self.closed = True


class FakeFailure(Exception):
    """Raised by the metadata of an opened document, not by opening it."""


class Dictionaries(dict):
    """What each file name says, and the documents PyMuPDF opened."""

    def __init__(self):
        super().__init__()
        self.opened: list = []
        self.asked: list = []       # the names PyMuPDF was asked to open


@pytest.fixture
def dictionaries(monkeypatch):
    """fitz.open as a lookup by file name: a dict is what the PDF says, an
    exception is a file PyMuPDF cannot open or read."""
    said = Dictionaries()

    def open_(path):
        said.asked.append(Path(path).name)
        entry = said[Path(path).name]
        if isinstance(entry, Exception) and not isinstance(entry, FakeFailure):
            raise entry
        document = FakeDocument(entry)
        said.opened.append(document)
        return document

    monkeypatch.setattr(pdf_info.fitz, "open", open_, raising=False)
    return said


def _pdf(path: Path, body: bytes = b"%PDF-1.4 stand-in\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


# -- the date ----------------------------------------------------------------

@pytest.mark.parametrize("written, read", [
    ("D:20240708134500+02'00'", "2024-07-08"),
    ("D:20240708", "2024-07-08"),
    ("  D:20240708134500Z", "2024-07-08"),
    ("D:202407", "2024-07"),
    ("D:2024", "2024"),
    ("D:20240229", "2024-02-29"),           # a leap day
])
def test_a_date_is_read_as_far_as_the_pdf_gives_it(written, read):
    assert pdf_info.parse_date(written) == read


@pytest.mark.parametrize("written", [
    "D:20230229",                   # not a leap year
    "D:20241301",                   # no thirteenth month
    "D:20240000",                   # no day 0
    "D:20240732",
    "D:00000101",                   # no year 0
    "2024-07-08",                   # not how a PDF writes it
    "20240708",
    "D:24",
    "D:\uff12\uff10\uff12\uff14\uff10\uff17\uff10\uff18",    # fullwidth digits
    "D:\u0662\u0660\u0662\u0664",                            # Arabic-Indic digits
    "", None, 2024, b"D:2024",
])
def test_a_text_that_is_no_date_gives_none(written):
    assert pdf_info.parse_date(written) is None


# -- the dictionary ----------------------------------------------------------

def test_a_title_is_one_line_and_a_missing_key_is_missing():
    got = pdf_info.from_metadata({"title": "  Wärmeplan\n Musterstadt \x00 2024 ",
                                  "creationDate": "D:20240708"})
    assert got == {"title": "Wärmeplan Musterstadt 2024", "created": "2024-07-08"}
    assert pdf_info.from_metadata({"title": "Only a title"}) == {
        "title": "Only a title"}
    assert pdf_info.from_metadata({"creationDate": "D:2024"}) == {
        "created": "2024"}


@pytest.mark.parametrize("empty", [
    {}, None, "text", [], {"title": "", "creationDate": ""},
    {"title": "  \n ", "creationDate": None}, {"title": 7}, {"title": "\x00\x01"},
])
def test_an_empty_dictionary_says_nothing(empty):
    assert pdf_info.from_metadata(empty) == {}


def test_a_file_is_read_through_its_dictionary_and_closed(tmp_path, dictionaries):
    dictionaries["a.pdf"] = {"title": "A plan", "creationDate": "D:20240708"}
    assert pdf_info.read(_pdf(tmp_path / "a.pdf")) == {
        "title": "A plan", "created": "2024-07-08"}
    assert all(document.closed for document in dictionaries.opened)


def test_a_dictionary_that_cannot_be_read_is_said_once_and_gives_nothing(
        tmp_path, dictionaries, caplog):
    dictionaries["damaged.pdf"] = RuntimeError("cannot open broken document")
    dictionaries["metadata.pdf"] = FakeFailure("cannot read the trailer")
    html = _pdf(tmp_path / "page.pdf", b"<html>not a pdf</html>")
    with caplog.at_level("WARNING"):
        for path in (_pdf(tmp_path / "damaged.pdf"), _pdf(tmp_path / "metadata.pdf"),
                     html, tmp_path / "missing.pdf"):
            assert pdf_info.read(path) == {}
    said = [r.getMessage() for r in caplog.records]
    assert len(said) == 4
    for name, text in zip(("damaged.pdf", "metadata.pdf", "page.pdf", "missing.pdf"),
                          said):
        assert text.startswith(name) and "information dictionary" in text
    # the one that opened was closed, and the one that is no PDF was never given
    # to PyMuPDF at all
    assert all(document.closed for document in dictionaries.opened)
    assert len(dictionaries.opened) == 1
    assert "page.pdf" not in dictionaries.asked


# -- the folder source -------------------------------------------------------

def test_the_folder_source_carries_what_the_pdf_says(tmp_path, dictionaries):
    folder = tmp_path / "in"
    for name in ("2023/titled.pdf", "empty.pdf", "damaged.pdf", "titleless.pdf"):
        _pdf(folder / name)
    dictionaries["titled.pdf"] = {"title": "Wärmeplan Musterstadt",
                                  "creationDate": "D:20240708120000Z"}
    dictionaries["empty.pdf"] = {"title": "", "creationDate": ""}
    dictionaries["damaged.pdf"] = RuntimeError("cannot open broken document")
    dictionaries["titleless.pdf"] = {"title": None, "creationDate": "D:2022"}

    docs = {d.filename: d.meta for d in FolderSource(folder).documents(None)}

    assert docs == {
        "titled.pdf": {"title": "Wärmeplan Musterstadt", "folder": "2023",
                       "created": "2024-07-08"},
        # as before: the file name for a title, and no key for the date
        "empty.pdf": {"title": "empty", "folder": None},
        "damaged.pdf": {"title": "damaged", "folder": None},
        "titleless.pdf": {"title": "titleless", "folder": None,
                          "created": "2022"},
    }


# -- the catalog -------------------------------------------------------------

def _meta_table(connection, columns, rows):
    """Documents and a DocumentMeta of just these columns."""
    schema.apply(connection, None)
    connection.execute("DROP TABLE IF EXISTS DocumentMeta")
    connection.execute('CREATE TABLE "DocumentMeta" ("document" INTEGER PRIMARY '
                       'KEY' + "".join(f', "{c}" TEXT' for c in columns) + ")")
    for index, (filename, values) in enumerate(rows, 1):
        connection.execute("INSERT INTO Documents (id, filename, external_id) "
                           "VALUES (?, ?, ?)", (index, filename, filename))
        connection.execute(
            f'INSERT INTO DocumentMeta (document{"".join("," + c for c in values)}) '
            f'VALUES (?{", ?" * len(values)})', (index, *values.values()))


def _labels(connection):
    connection.row_factory = sqlite3.Row
    return [entry.label for entry in load_catalog(DEFAULT).entries(connection)]


def test_the_catalog_shows_the_pdf_s_title_else_the_file_stem_and_the_date(
        tmp_path):
    with sqlite3.connect(tmp_path / "db") as connection:
        _meta_table(connection, ("title", "folder", "created"), [
            ("a_report.pdf", {"title": "Wärmeplan Musterstadt",
                              "created": "2024-07-08"}),
            ("b_report.pdf", {"title": None, "created": "2022"}),
            ("c_report.pdf", {"title": None, "created": None}),
            ("d_report.pdf", {"title": "A title and no date", "created": None}),
        ])
        assert _labels(connection) == [
            "Wärmeplan Musterstadt · 2024-07-08",
            "b_report · 2022",
            "c_report",
            "A title and no date",
        ]


def test_a_profile_whose_table_has_no_title_or_date_column_is_still_shown(
        tmp_path):
    with sqlite3.connect(tmp_path / "db") as connection:
        _meta_table(connection, ("folder",), [("plain.pdf", {"folder": "x"})])
        assert _labels(connection) == ["plain"]


def test_the_built_in_table_has_a_column_for_the_date(tmp_path):
    with sqlite3.connect(tmp_path / "db") as connection:
        schema.apply(connection, DEFAULT)
        assert {"title", "folder", "created"} <= schema.columns(
            connection, "DocumentMeta")


# -- from the PDF to the picker ----------------------------------------------

def test_a_folder_reaches_the_picker_with_what_its_pdfs_say(tmp_path,
                                                            dictionaries,
                                                            monkeypatch):
    folder, data = tmp_path / "in", tmp_path / "data"
    for name in ("2023/plan.pdf", "blank.pdf", "damaged.pdf"):
        _pdf(folder / name)
    dictionaries["plan.pdf"] = {"title": "Wärmeplan Musterstadt",
                                "creationDate": "D:20240708120000Z"}
    dictionaries["blank.pdf"] = {}
    dictionaries["damaged.pdf"] = RuntimeError("cannot open broken document")
    monkeypatch.setattr(ingest, "get_num_pages", lambda name, where: 3)
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda path: (True, ""))
    unreachable: dict = {}

    ingest.ingest(FolderSource(folder), tmp_path / "db", data, DEFAULT,
                  unreachable=unreachable)

    assert unreachable == {}, "a PDF whose dictionary cannot be read is still in"
    with sqlite3.connect(tmp_path / "db") as connection:
        stored = connection.execute(
            "SELECT d.filename, m.title, m.created FROM Documents d "
            "JOIN DocumentMeta m ON m.document = d.id ORDER BY d.filename"
        ).fetchall()
        assert stored == [
            ("blank.pdf", "blank", None),
            ("damaged.pdf", "damaged", None),
            ("plan.pdf", "Wärmeplan Musterstadt", "2024-07-08")]
        assert sorted(_labels(connection)) == [
            "Wärmeplan Musterstadt · 2024-07-08", "blank", "damaged"]


def test_a_pdf_the_source_never_read_is_not_read_for_its_dictionary(
        tmp_path, dictionaries):
    """The dictionary is read as the document is yielded, one at a time:
    stopping at the first one asks PyMuPDF for no more than that."""
    folder = tmp_path / "in"
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        _pdf(folder / name)
        dictionaries[name] = {"title": name}
    documents = FolderSource(folder).documents(None)
    next(documents)
    assert len(dictionaries.opened) == 1
    assert isinstance(next(documents), SourceDoc)
    assert len(dictionaries.opened) == 2


# -- a database made before the date was kept --------------------------------

def _before_the_date(connection):
    """The built-in schema as it was before DocumentMeta had a `created`."""
    sql = DEFAULT.schema_sql.read_text(encoding="utf-8")
    start = sql.index(",\n    -- the creation date")
    end = sql.index('"created"  TEXT') + len('"created"  TEXT')
    old = sql[:start] + sql[end:]
    assert '"created"' not in old, "the stand-in for the old schema is not old"
    connection.executescript("BEGIN;\n" + schema.core_sql() + old + "\nCOMMIT;")
    assert "created" not in schema.columns(connection, "DocumentMeta")


def test_a_database_made_before_the_date_was_kept_takes_it(tmp_path,
                                                           dictionaries,
                                                           monkeypatch):
    """CREATE TABLE IF NOT EXISTS leaves DocumentMeta as it was made, so a
    source that fills a new column has to add it, or the first PDF with a
    date stops the run on a column that is not there."""
    folder, data = tmp_path / "in", tmp_path / "data"
    _pdf(folder / "old.pdf")
    _pdf(folder / "new.pdf")
    dictionaries["old.pdf"] = {"title": "Old", "creationDate": "D:2020"}
    dictionaries["new.pdf"] = {"title": "New", "creationDate": "D:20240708"}
    monkeypatch.setattr(ingest, "get_num_pages", lambda name, where: 3)
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda path: (True, ""))
    with sqlite3.connect(tmp_path / "db") as connection:
        _before_the_date(connection)
        connection.execute("INSERT INTO Documents (id, filename, external_id) "
                           "VALUES (1, 'old.pdf', 'old.pdf')")
        connection.execute("INSERT INTO DocumentMeta (document, title) "
                           "VALUES (1, 'Old, as it was')")
    data.mkdir()
    (data / "old.pdf").write_bytes(b"%PDF-1.4 stand-in\n")

    ingest.ingest(FolderSource(folder), tmp_path / "db", data, DEFAULT)

    with sqlite3.connect(tmp_path / "db") as connection:
        assert connection.execute(
            "SELECT d.filename, m.title, m.created FROM Documents d "
            "JOIN DocumentMeta m ON m.document = d.id ORDER BY d.filename"
        ).fetchall() == [
            # what was there stays as it was; the new one has its date
            ("new.pdf", "New", "2024-07-08"),
            ("old.pdf", "Old, as it was", None)]


def test_a_missing_table_is_not_made_by_adding_a_column(tmp_path):
    """The write that needs the table is the one to fail, and loudly."""
    with sqlite3.connect(tmp_path / "db") as connection:
        assert schema.add_missing_column(
            connection, "DocumentMeta", "created", "TEXT") is False
        assert schema.columns(connection, "DocumentMeta") == set()
        schema.apply(connection, DEFAULT)
        assert schema.add_missing_column(
            connection, "DocumentMeta", "created", "TEXT") is False   # there


# -- a registered PDF is not opened again ------------------------------------

def test_a_pdf_that_is_registered_is_not_opened_for_its_dictionary_again(
        tmp_path, dictionaries, monkeypatch, caplog):
    """The row it has takes nothing from the dictionary on the next run, so
    opening every file of the corpus again would cost PyMuPDF, and a line in
    the log for each one it cannot read, for nothing."""
    folder, data = tmp_path / "in", tmp_path / "data"
    _pdf(folder / "first.pdf")
    _pdf(folder / "damaged.pdf")
    dictionaries["first.pdf"] = {"title": "First"}
    dictionaries["damaged.pdf"] = RuntimeError("cannot open broken document")
    monkeypatch.setattr(ingest, "get_num_pages", lambda name, where: 3)
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda path: (True, ""))
    ingest.ingest(FolderSource(folder), tmp_path / "db", data, DEFAULT)
    assert sorted(dictionaries.asked) == ["damaged.pdf", "first.pdf"]

    _pdf(folder / "later.pdf")
    dictionaries["later.pdf"] = {"title": "Later"}
    dictionaries.asked.clear()
    caplog.clear()
    with caplog.at_level("WARNING"):
        ingest.ingest(FolderSource(folder), tmp_path / "db", data, DEFAULT)

    assert dictionaries.asked == ["later.pdf"]
    assert not [r for r in caplog.records if "dictionary" in r.getMessage()]
    with sqlite3.connect(tmp_path / "db") as connection:
        assert connection.execute(
            "SELECT m.title FROM DocumentMeta m JOIN Documents d "
            "ON d.id = m.document WHERE d.filename = 'later.pdf'"
        ).fetchone() == ("Later",)
