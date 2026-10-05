"""`docpipe status`: which stage has left output for which document.

The promise: for the profile in effect it shows every document of the
corpus once, and for each stage whether that stage's output for the document
is there by the stage's own rule of being done, then how many documents each
stage has output for; and it changes nothing, also where a later stage has
not run at all. Each clause has a test, and each test has a case that
violates it.
"""
import json
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from docpipe import cli, run, status
from docpipe.artifacts import (DOCUMENT_JSON, PAGES_JSON,
                               REFINEMENT_PARTIAL_JSON, SECTIONS_JSON,
                               SECTIONS_REFINED_JSON, VISUALS_JSON)
from docpipe.inference import lexical
from docpipe.profile import Profile
from docpipe.store import schema
from docpipe.visuals import pipeline as visuals
from tests.test_cli import _docpipe



def _fts5() -> bool:
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(a)")
    except sqlite3.OperationalError:
        return False
    return True


needs_fts5 = pytest.mark.skipif(not _fts5(),
                                reason="this SQLite has no FTS5")

PLAIN = {"sections": [{
    "title": "Bestand", "content": "Text [p1_tbl0] [p1_img0]",
    "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png",
                "caption": "Tabelle"}],
    "figures": [{"id": "p1_img0", "path": "images/p1_img0.png",
                 "caption": "Abbildung"}]}]}
ENRICHED = {"sections": [{
    "title": "Bestand", "content": "Text [p1_tbl0] [p1_img0]",
    "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png",
                "caption": "Tabelle", "markdown": "| a |"}],
    "figures": [{"id": "p1_img0", "path": "images/p1_img0.png",
                 "caption": "Abbildung", "description": "ein Netz"}]}]}
EARLIER, LATER = 1_000_000_000, 1_000_000_100      # seconds


def _put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _at(path, seconds):
    os.utime(path, (seconds, seconds))


class Corpus:
    """A profile's data directory, built by hand one stage at a time."""

    def __init__(self, root: Path):
        self.profile = Profile(name="demo", data_root=root)
        self.processed = self.profile.processed_dir
        self.processed.mkdir(parents=True)
        self.db = self.profile.db_path
        with closing(sqlite3.connect(self.db)) as connection:
            schema.apply(connection)

    def sql(self, statement, *values):
        with closing(sqlite3.connect(self.db)) as connection:
            cursor = connection.execute(statement, values)
            connection.commit()
            return cursor.lastrowid

    def value(self, statement, *values):
        with closing(sqlite3.connect(self.db)) as connection:
            return connection.execute(statement, values).fetchone()[0]

    def pdf(self, key):
        (self.profile.pdf_dir / f"{key}.pdf").write_bytes(b"%PDF-1.4")

    def register(self, key):
        return self.sql("INSERT INTO Documents (filename) VALUES (?)",
                        f"{key}.pdf")

    def folder(self, key):
        return self.processed / key

    def preprocessed(self, key):
        _put(self.folder(key) / PAGES_JSON, [])
        _put(self.folder(key) / SECTIONS_JSON, PLAIN)

    def refined(self, key):
        _put(self.folder(key) / SECTIONS_REFINED_JSON, PLAIN)

    def enriched(self, key, data=ENRICHED):
        _put(self.folder(key) / VISUALS_JSON, data)

    def merged(self, key):
        """document.json newer than what it was made from."""
        folder = self.folder(key)
        for name in (SECTIONS_REFINED_JSON, VISUALS_JSON):
            if (folder / name).exists():
                _at(folder / name, EARLIER)
        _at(_put(folder / DOCUMENT_JSON, ENRICHED), LATER)

    def stored(self, key, *, embedded=True):
        """The document's rows, and a vector recorded for a section."""
        document = self.document(key)
        section = self.sql(
            "INSERT INTO Sections (document, section_number, title, content) "
            "VALUES (?, 0, 'Bestand', ?)", document, f"Wärmenetz {key}")
        if embedded:
            self.sql("INSERT INTO Embeddings (faiss_id, embedding_type, "
                     "owner_kind, owner_id) VALUES (?, 'section_text', "
                     "'section', ?)", section, section)
        return section

    def document(self, key):
        return self.value("SELECT id FROM Documents WHERE filename = ?",
                          f"{key}.pdf")

    def everything(self, key):
        """What a document that went through all of it has."""
        self.pdf(key)
        self.register(key)
        self.preprocessed(key)
        self.refined(key)
        self.enriched(key)
        self.merged(key)
        self.stored(key)

    def report(self):
        return status.collect(self.profile)


@pytest.fixture
def corpus(tmp_path):
    return Corpus(tmp_path / "demo")


def _there(report, stage):
    return sorted(report.there[stage])


def _snapshot(root: Path):
    """Every file under *root* with its size, time and bytes."""
    return sorted(
        (str(path.relative_to(root)), path.stat().st_size,
         path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*") if path.is_file())


# ---------------------------------------------------------------------------
# the documents: every name the corpus knows, once
# ---------------------------------------------------------------------------

def test_a_document_is_every_name_the_corpus_knows_and_listed_once(corpus):
    corpus.everything("alpha")                    # in all three places
    corpus.pdf("charlie")                         # a PDF nobody registered
    corpus.preprocessed("delta")                  # a directory without either
    corpus.register("echo")                       # a row without a file
    # what is not a document: files among the directories, other file types
    _put(corpus.processed / "_index.json", {})
    (corpus.profile.pdf_dir / "notes.txt").write_text("x", encoding="utf-8")
    assert corpus.report().documents == ["alpha", "charlie", "delta", "echo"]


@pytest.mark.parametrize("filename", ["alpha.pdf", "Plan 2020.pdf",
                                      "a.b.pdf", "Upper.PDF"])
def test_a_document_is_named_as_the_directory_preprocessing_makes_for_it(
        filename):
    """The processed directory is the file's name without its suffix, and
    that is what chunking looks the Documents row up by."""
    assert status.key_of(filename) == Path(filename).with_suffix("").name
    assert status.key_of("plain") == "plain"
    assert status.key_of("notes.pdf.bak") == "notes.pdf.bak"


def test_what_the_stage_counts_as_enriched_is_a_markdown_or_a_description():
    cached: dict = {}
    visuals.collect_cached({"sections": [
        {"tables": [{"id": "t1", "markdown": "| a |"}, {"id": "t2"},
                    {"id": "t3", "markdown": ""}],
         "figures": [{"id": "f1", "description": "ein Netz"}, {"id": "f2"},
                     {"id": "f3", "markdown": "| not a figure's |"}]},
        {"title": "no media"}]}, cached)
    assert sorted(cached) == ["f1", "t1"]
    assert cached["t1"]["markdown"] == "| a |"
    visuals.collect_cached({}, cached)             # nothing to add
    assert sorted(cached) == ["f1", "t1"]


def test_a_filename_that_is_not_a_pdf_name_is_looked_up_as_it_stands(corpus):
    """Chunking asks for `name + '.pdf'` and then for `name`."""
    corpus.sql("INSERT INTO Documents (filename) VALUES ('plain')")
    corpus.preprocessed("plain")
    report = corpus.report()
    assert report.documents == ["plain"]
    assert _there(report, "ingest") == ["plain"]


def test_a_row_registered_under_an_upper_case_suffix_is_ingested(corpus):
    """Ingest skips a document by the file name its row has, and a folder
    source registers `Plan.PDF` as it is called. Asked for `Plan.pdf` only,
    the row that ingest would skip showed as not ingested."""
    corpus.sql("INSERT INTO Documents (filename) VALUES ('Plan.PDF')")
    (corpus.profile.pdf_dir / "Plan.PDF").write_bytes(b"%PDF-1.4")
    # a file of that kind that nobody registered is still not ingested
    (corpus.profile.pdf_dir / "Lone.PDF").write_bytes(b"%PDF-1.4")
    corpus.preprocessed("Lone")
    report = corpus.report()
    assert report.documents == ["Lone", "Plan"]
    assert _there(report, "ingest") == ["Plan"]


# ---------------------------------------------------------------------------
# one test per stage: its own rule of being done
# ---------------------------------------------------------------------------

def test_ingest_is_a_documents_row_and_a_file_alone_is_not(corpus):
    corpus.pdf("lying")
    corpus.register("entered")
    assert _there(corpus.report(), "ingest") == ["entered"]


def test_preprocess_needs_the_pages_and_the_sections(corpus):
    corpus.preprocessed("both")
    _put(corpus.folder("sections_only") / SECTIONS_JSON, PLAIN)
    _put(corpus.folder("pages_only") / PAGES_JSON, [])
    corpus.folder("empty").mkdir()
    assert _there(corpus.report(), "preprocess") == ["both"]


def test_refine_is_the_refined_sections_with_no_unfinished_pass_beside_them(
        corpus):
    corpus.refined("done")
    corpus.refined("resuming")                    # a pass was started again
    _put(corpus.folder("resuming") / REFINEMENT_PARTIAL_JSON,
         {"sections": [], "windows": {"0": {}}})
    corpus.refined("junk_beside")                 # an unreadable pass is none
    (corpus.folder("junk_beside") / REFINEMENT_PARTIAL_JSON).write_text(
        "{not json", encoding="utf-8")
    corpus.preprocessed("not_yet")                # structured, not refined
    assert _there(corpus.report(), "refine") == ["done", "junk_beside"]


def test_visuals_is_the_output_with_every_table_and_figure_enriched(corpus):
    corpus.preprocessed("whole")
    corpus.enriched("whole")
    corpus.preprocessed("no_table_text")
    corpus.enriched("no_table_text", {"sections": [{
        "tables": [{"id": "p1_tbl0"}],
        "figures": [{"id": "p1_img0", "description": "ein Netz"}]}]})
    corpus.preprocessed("no_figure_text")
    corpus.enriched("no_figure_text", {"sections": [{
        "tables": [{"id": "p1_tbl0", "markdown": "| a |"}],
        "figures": [{"id": "p1_img0", "description": ""}]}]})
    corpus.preprocessed("not_run")                # items, and no output
    corpus.enriched("no_input")                   # output, and no input
    corpus.preprocessed("unreadable")
    (corpus.folder("unreadable") / VISUALS_JSON).write_text(
        "{not json", encoding="utf-8")
    assert _there(corpus.report(), "visuals") == ["whole"]


def test_visuals_has_no_items_to_wait_for_where_the_input_has_none(corpus):
    corpus.preprocessed("bare")
    _put(corpus.folder("bare") / SECTIONS_JSON, {"sections": [{"title": "T"}]})
    assert _there(corpus.report(), "visuals") == []       # no output yet
    corpus.enriched("bare", {"sections": [{"title": "T"}]})
    assert _there(corpus.report(), "visuals") == ["bare"]


def test_visuals_agrees_with_what_the_stage_itself_would_ask_for(
        corpus, caplog):
    """The stage's dry run counts the items it would send to the model; a
    document is there exactly when that is none."""
    cases = {
        "whole": ENRICHED,
        "table_open": {"sections": [{
            "tables": [{"id": "p1_tbl0"}],
            "figures": [{"id": "p1_img0", "description": "ein Netz"}]}]},
        "figure_open": {"sections": [{
            "tables": [{"id": "p1_tbl0", "markdown": "| a |"}],
            "figures": [{"id": "p1_img0"}]}]},
    }
    for key, output in cases.items():
        corpus.preprocessed(key)
        corpus.enriched(key, output)
    there = _there(corpus.report(), "visuals")
    for key in cases:
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=visuals.log.name):
            visuals.run_single(corpus.folder(key), dry_run=True)
        asked = [r.args for r in caplog.records if r.msg.startswith("Found:")]
        (tables, cached_tables, pending_tables,
         figures, cached_figures, pending_figures, _sections) = asked[0]
        assert (key in there) == (pending_tables + pending_figures == 0), key
    assert there == ["whole"]


def test_chunk_needs_the_merge_current_the_rows_and_an_embedding(corpus):
    corpus.everything("whole")
    # the merge is older than what it was made from
    corpus.everything("stale_merge")
    _at(corpus.folder("stale_merge") / DOCUMENT_JSON, EARLIER)
    _at(corpus.folder("stale_merge") / VISUALS_JSON, LATER)
    # no merged file at all
    corpus.everything("not_merged")
    (corpus.folder("not_merged") / DOCUMENT_JSON).unlink()
    # merged, and not in the database
    corpus.pdf("no_rows")
    corpus.register("no_rows")
    corpus.refined("no_rows")
    corpus.merged("no_rows")
    # rows, and no vector recorded
    corpus.everything("no_vector")
    corpus.sql("DELETE FROM Embeddings WHERE owner_id IN (SELECT id FROM "
               "Sections WHERE document = ?)", corpus.document("no_vector"))
    # a directory the database does not know
    corpus.refined("orphan")
    corpus.merged("orphan")
    assert _there(corpus.report(), "chunk") == ["whole"]


def test_chunk_counts_a_vector_of_a_table_or_a_figure_as_well(corpus):
    corpus.everything("tables_only")
    document = corpus.document("tables_only")
    corpus.sql("DELETE FROM Embeddings")
    section = corpus.value("SELECT id FROM Sections WHERE document = ?",
                           document)
    table = corpus.sql("INSERT INTO Tables (section, block_id, path) "
                       "VALUES (?, 'p1_tbl0', 'x.png')", section)
    assert _there(corpus.report(), "chunk") == []
    corpus.sql("INSERT INTO Embeddings (faiss_id, embedding_type, "
               "owner_kind, owner_id) VALUES (7, 'table_text', 'table', ?)",
               table)
    assert _there(corpus.report(), "chunk") == ["tables_only"]


@needs_fts5
def test_lexical_is_a_current_word_index_that_holds_a_passage_of_the_document(
        corpus):
    corpus.everything("alpha")
    corpus.everything("bravo")
    corpus.pdf("bare")
    corpus.register("bare")                       # a row, no passage
    corpus.sql("DELETE FROM Sections WHERE document = ?",
               corpus.document("bravo"))
    assert corpus.report().word_index == "missing"
    assert _there(corpus.report(), "lexical") == []
    lexical.build(corpus.db)
    report = corpus.report()
    assert report.word_index == "current"
    assert _there(report, "lexical") == ["alpha"]


@needs_fts5
def test_a_word_index_gone_stale_is_output_of_no_document(corpus):
    corpus.everything("alpha")
    lexical.build(corpus.db)
    assert _there(corpus.report(), "lexical") == ["alpha"]
    corpus.sql("UPDATE Sections SET content = 'ganz anderer Text'")
    report = corpus.report()
    assert report.word_index == "stale"
    assert _there(report, "lexical") == []


# ---------------------------------------------------------------------------
# the counts
# ---------------------------------------------------------------------------

@needs_fts5
def test_the_counts_say_what_they_count_and_follow_the_output(corpus):
    corpus.everything("alpha")
    corpus.everything("bravo")
    corpus.pdf("charlie")
    lexical.build(corpus.db)
    shown = status.render(corpus.report())
    assert "ingest      2 of 3 document(s) have its output" in shown
    assert "chunk       2 of 3 document(s) have its output" in shown
    assert "lexical     2 of 3 document(s) have its output" in shown
    assert "word index: current" in shown
    # take one output away and its count moves, the others do not
    (corpus.folder("bravo") / VISUALS_JSON).unlink()
    shown = status.render(corpus.report())
    assert "visuals     1 of 3" in shown and "refine      2 of 3" in shown


def test_one_line_per_document_and_one_column_per_stage(corpus):
    corpus.everything("alpha")
    corpus.register("bravo")
    corpus.preprocessed("bravo")
    lines = status.render(corpus.report()).splitlines()
    head = lines[1].split()
    assert head == ["document", *run.STAGES]
    rows = {line.split()[0]: line.split()[1:] for line in lines[2:4]}
    assert rows["alpha"] == ["x", "x", "x", "x", "x", "-"]
    assert rows["bravo"] == ["x", "x", "-", "-", "-", "-"]


def test_a_long_name_does_not_shift_the_columns(corpus):
    corpus.register("a_much_longer_name_than_the_header")
    corpus.register("b")
    lines = status.render(corpus.report()).splitlines()
    header, first, second = lines[1], lines[2], lines[3]
    assert first.startswith("a_much_longer") and second.startswith("b ")
    assert header.index("ingest") == first.index("x") == second.index("x")


# ---------------------------------------------------------------------------
# a stage that has not run, and a command that changes nothing
# ---------------------------------------------------------------------------

def test_a_corpus_nothing_has_run_for_is_zero_everywhere_and_creates_nothing(
        tmp_path):
    profile = Profile(name="demo", data_root=tmp_path / "never")
    report = status.collect(profile)
    assert report.documents == []
    assert all(report.count(stage) == 0 for stage in run.STAGES)
    assert report.word_index == "missing"
    shown = status.render(report)
    assert "no document found" in shown and "0 of 0 document(s)" in shown
    assert not (tmp_path / "never").exists()      # not the folder, not a db


def test_where_only_ingest_has_run_the_later_columns_are_dashes(corpus):
    corpus.processed.rmdir()
    corpus.pdf("alpha")
    corpus.register("alpha")
    report = corpus.report()
    assert _there(report, "ingest") == ["alpha"]
    assert all(_there(report, stage) == [] for stage in run.STAGES[1:])


def test_a_database_without_its_tables_is_a_corpus_without_rows(tmp_path):
    profile = Profile(name="demo", data_root=tmp_path)
    profile.pdf_dir.mkdir(parents=True)
    profile.db_path.write_bytes(b"")
    (profile.pdf_dir / "alpha.pdf").write_bytes(b"%PDF")
    report = status.collect(profile)
    assert report.documents == ["alpha"]
    assert all(_there(report, stage) == [] for stage in run.STAGES)
    assert profile.db_path.read_bytes() == b""


def test_a_database_with_only_the_documents_table_is_ingested_and_no_more(
        tmp_path):
    """The rows of the documents are ingest's output whether or not the
    tables of the later stages are there; chunk is asked for only where
    they are, and does not fail where they are not."""
    profile = Profile(name="demo", data_root=tmp_path)
    profile.db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(profile.db_path)) as connection:
        connection.execute("CREATE TABLE Documents "
                           "(id INTEGER PRIMARY KEY, filename TEXT)")
        connection.execute("INSERT INTO Documents (filename) VALUES ('a.pdf')")
        connection.commit()
    report = status.collect(profile)
    assert report.documents == ["a"]
    assert _there(report, "ingest") == ["a"]
    assert all(_there(report, stage) == [] for stage in run.STAGES[1:])


@needs_fts5
def test_it_changes_nothing_not_a_file_and_not_the_database(corpus):
    corpus.everything("alpha")
    corpus.pdf("charlie")
    lexical.build(corpus.db)
    before = _snapshot(corpus.profile.root)
    corpus.report()
    status.render(corpus.report())
    assert _snapshot(corpus.profile.root) == before


def test_the_database_it_opens_cannot_be_written_through(corpus):
    with closing(status._open(corpus.db)) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO Documents (filename) VALUES ('x')")
    assert status._open(corpus.db.with_name("none.db")) is None
    assert not corpus.db.with_name("none.db").exists()


def test_a_file_that_is_not_a_database_ends_the_command_with_its_name(
        tmp_path, monkeypatch, capsys):
    profile = Profile(name="demo", data_root=tmp_path)
    profile.db_path.parent.mkdir(parents=True, exist_ok=True)
    profile.db_path.write_bytes(b"this is not a database" * 100)
    monkeypatch.setattr(status, "require_profile", lambda: profile)
    with pytest.raises(SystemExit) as ended:
        status.main([])
    assert str(profile.db_path) in str(ended.value)
    assert profile.db_path.read_bytes() == b"this is not a database" * 100


# ---------------------------------------------------------------------------
# the command
# ---------------------------------------------------------------------------

def test_the_command_prints_the_matrix_and_needs_a_profile(tmp_path):
    data = tmp_path / "data"
    shown = _docpipe("--profile", "default", "status", cwd=tmp_path,
                     DOCPIPE_DATA_ROOT=str(data))
    assert shown.returncode == 0, shown.stdout + shown.stderr
    assert "profile default" in shown.stdout
    assert "ingest      0 of 0 document(s)" in shown.stdout
    assert not data.exists()                      # asking created nothing
    bare = _docpipe("status", cwd=tmp_path)
    assert bare.returncode != 0 and "no profile" in bare.stderr
    assert "Traceback" not in bare.stderr


def test_the_command_is_listed_beside_run(tmp_path):
    for name in ("run", "status"):
        assert name in cli.OWN
    helped = _docpipe("--help", cwd=tmp_path)
    assert "  run " in helped.stdout and "  status " in helped.stdout
