"""Record identity: which bytes a document is, which format a database has,
which model built an index, which row a value is and who wrote a harvest.

Promised: all of it is RECORDED and nothing of it is compared or refused; a
database, a stamp and a harvest written before any of it stay readable; a
row's name survives a re-chunk AND a re-harvest that reads the same thing;
and a row whose passage moved gets its new address only from a pass of its
own, and only when exactly one passage carries its quote.
"""
import json
import sqlite3
from types import SimpleNamespace as NS

import pytest

from docpipe.extraction import identity, remap, runner
from docpipe.extraction import schema as extraction_schema
from docpipe.ingest import pipeline as ingest
from docpipe.store import documents as docs
from docpipe.store import schema


# -- the database -------------------------------------------------------------

OLD_DOCUMENTS = """
CREATE TABLE "Documents" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT, "external_id" TEXT UNIQUE,
    "group_key" TEXT, "filename" TEXT NOT NULL UNIQUE, "published" TEXT,
    "num_pages" INTEGER, "page_text_transcribed" INTEGER, "added" TEXT,
    "is_current" INTEGER NOT NULL DEFAULT 1, "supersedes" INTEGER);
INSERT INTO Documents (filename) VALUES ('old.pdf');
"""


def test_a_database_from_before_is_brought_up_and_loses_nothing(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_DOCUMENTS)
        assert schema.meta(conn) == {}              # it says nothing yet
        assert docs.content_of("old.pdf", conn) == (None, None)
    with sqlite3.connect(path) as conn:
        schema.apply(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] \
            == schema.FORMAT
        assert {"sha256", "bytes"} <= schema.columns(conn, "Documents")
        assert conn.execute("SELECT filename, sha256 FROM Documents"
                            ).fetchall() == [("old.pdf", None)]
        assert schema.migrate(conn) == schema.FORMAT    # and again: nothing
        schema.set_meta(conn, {"embedding/model": "m", "embedding/dim": 8})
        schema.set_meta(conn, {"embedding/dim": 16})
        assert schema.meta(conn) == {"embedding/model": "m",
                                     "embedding/dim": "16"}


def _doc():
    return NS(filename="a.pdf", external_id="a", group_key=None,
              published=None, meta=None, url=None)


def test_a_new_document_is_registered_with_its_bytes(tmp_path, monkeypatch):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.7 the first file")
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda path: (True, ""))
    monkeypatch.setattr(ingest, "get_num_pages", lambda name, folder: 3)
    with sqlite3.connect(tmp_path / "db") as conn:
        schema.apply(conn)
        assert ingest.register(_doc(), conn, tmp_path) is True
        sha, size = docs.content_of("a.pdf", conn)
        assert (sha, size) == docs.file_sha256(tmp_path / "a.pdf")
        assert len(sha) == 64 and size == 23


def test_another_file_under_the_old_name_is_said_and_nothing_stops(
        tmp_path, caplog):
    file = tmp_path / "a.pdf"
    file.write_bytes(b"first")
    with sqlite3.connect(tmp_path / "db") as conn:
        schema.apply(conn)
        docs.add_document("a.pdf", "a", None, None, 1, "20260101", None, conn)
        # a row from before the record gets it once ...
        assert ingest.register(_doc(), conn, tmp_path) is False
        first = docs.content_of("a.pdf", conn)
        assert first == docs.file_sha256(file)
        # ... the same file says nothing ...
        with caplog.at_level("WARNING"):
            assert ingest.register(_doc(), conn, tmp_path) is False
        assert caplog.records == []
        # ... and another file is named, with the record left as it was
        file.write_bytes(b"a second, longer file")
        with caplog.at_level("WARNING"):
            assert ingest.register(_doc(), conn, tmp_path) is False
        assert "not the file that was registered" in caplog.text
        assert docs.content_of("a.pdf", conn) == first


# -- the name of a row --------------------------------------------------------

def _row(quote="Der Bedarf liegt bei 120 GWh", value=120.0, raw="120",
         owner=7, kind="section", **more):
    return {"kind": "tuple", "value": value, "value_raw": raw, "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": kind,
                           "owner_id": owner, "section_number": 4,
                           "page": 12}, **more}


def test_a_rows_name_is_its_document_its_quote_and_its_value():
    name = identity.tuple_id("sha-of-a", _row())
    assert len(name) == 24
    # the database's counters are not part of it, nor a coordinate read later
    assert name == identity.tuple_id("sha-of-a", _row(owner=99))
    assert name == identity.tuple_id("sha-of-a", _row(carrier="gas"))
    assert name == identity.tuple_id(
        "sha-of-a", _row(quote="Der  Bedarf liegt\nbei 120 GWh"))
    # another document, another quote, another value: another row
    assert name != identity.tuple_id("sha-of-b", _row())
    assert name != identity.tuple_id("sha-of-a", _row(quote="anders"))
    assert name != identity.tuple_id("sha-of-a", _row(raw="130"))
    # without the wording the value as read names it
    assert identity.tuple_id("d", _row(raw=None)) != identity.tuple_id(
        "d", _row(raw=None, value=5))


def test_a_row_that_says_what_an_earlier_one_says_is_the_second_of_its_name():
    names = identity.tuple_ids("d", [_row(), _row(raw="130"), _row()])
    assert names[2] == names[0] + ".2" and names[1] != names[0]
    assert len(set(names)) == 3


# -- a passage found again ----------------------------------------------------

def _corpus(tmp_path, sections):
    """A database with one document whose sections carry these texts."""
    path = tmp_path / "db"
    with sqlite3.connect(path) as conn:
        schema.apply(conn)
        conn.execute("INSERT INTO Documents (id, filename) "
                     "VALUES (1, 'a.pdf')")
        for number, (owner, text) in enumerate(sections.items()):
            conn.execute(
                "INSERT INTO Sections (id, document, section_number, content)"
                " VALUES (?, 1, ?, ?)", (owner, number, text))
    return path


def _sources(sections):
    def owner_sources(owners):
        return {(kind, owner): NS(text=sections[owner])
                for kind, owner in owners
                if kind == "section" and owner in sections}
    return owner_sources


def _carries(text, quote):
    return quote in text


def _reanchor(tmp_path, sections, rows, write=True):
    path = _corpus(tmp_path, sections)
    harvest = tmp_path / "a.jsonl"
    harvest.write_text("\n".join(json.dumps(row) for row in rows) + "\n",
                       encoding="utf-8")
    before = harvest.read_bytes()
    with sqlite3.connect(path) as conn:
        stats = identity.reanchor_file(harvest, conn, _sources(sections),
                                       _carries, write=write)
    after = [json.loads(line) for line in
             harvest.read_text(encoding="utf-8").splitlines()]
    return stats, after, before == harvest.read_bytes()


def test_a_row_whose_passage_moved_gets_its_new_address(tmp_path):
    rows = [_row(owner=7), {"kind": "summary", "tuples": 1}]
    stats, after, same = _reanchor(
        tmp_path, {41: "Vorwort", 42: "x Der Bedarf liegt bei 120 GWh y"},
        rows)
    assert after[0]["provenance"]["owner_id"] == 42
    assert after[1] == {"kind": "summary", "tuples": 1}
    assert stats["rows given their passage's new address"] == 1
    assert stats["rows"] == 1 and not same


@pytest.mark.parametrize("sections,counted", [
    # the row's own address still carries the quote
    ({7: "Der Bedarf liegt bei 120 GWh", 8: "Der Bedarf liegt bei 120 GWh"},
     "rows whose passage is where it was"),
    # no passage carries it
    ({41: "Vorwort", 42: "Anhang"},
     "rows whose passage was not found again"),
    # two carry it: a guess between them is no address
    ({41: "Der Bedarf liegt bei 120 GWh", 42: "Der Bedarf liegt bei 120 GWh"},
     "rows whose passage was not found again"),
])
def test_a_row_is_left_byte_for_byte_unless_one_passage_carries_its_quote(
        tmp_path, sections, counted):
    stats, after, same = _reanchor(tmp_path, sections, [_row(owner=7)])
    assert same and after[0]["provenance"]["owner_id"] == 7
    assert stats[counted] == 1


def test_a_dry_run_counts_and_writes_nothing(tmp_path):
    stats, _, same = _reanchor(tmp_path, {42: "Der Bedarf liegt bei 120 GWh"},
                               [_row(owner=7)], write=False)
    assert same and stats["rows given their passage's new address"] == 1


# -- who wrote a harvest ------------------------------------------------------

def test_a_stamp_names_its_version_its_document_and_its_harvest(tmp_path):
    path = tmp_path / "db"
    with sqlite3.connect(path) as conn:
        schema.apply(conn)
        conn.execute("INSERT INTO Documents (filename, sha256, bytes) "
                     "VALUES ('plan.pdf', ?, 10), ('older.pdf', NULL, NULL)",
                     ("a" * 64,))
    try:
        assert runner.note_documents(path) == 1
        record = runner.stamp_record("plan")
        assert record["document"] == {"sha256": "a" * 64, "bytes": 10}
        assert record["docpipe"]
        (first,) = record["producers"]
        assert first["pass"] == "harvest"
        assert first["model"] == runner.LLM_MODEL
        assert first["provider"] == "openai-compatible" and first["utc"]
        # a document the database has no record of: the stamp is silent on it
        assert "document" not in runner.stamp_record("older")
        assert runner.note_documents(tmp_path / "missing.db") == 0
        assert "document" not in runner.stamp_record("plan")
    finally:
        runner.DOCUMENT_CONTENT.clear()


def test_the_stamp_schema_takes_the_record_and_old_stamps_too():
    jsonschema = pytest.importorskip("jsonschema")
    shape = extraction_schema.stamp_schema()
    old = {key: "0" * 64 for key in shape["required"]}
    old.update(model="m", anchors="")
    jsonschema.validate(old, shape)                 # a stamp from before
    new = {**old, "docpipe": "0.1.0",
           "document": {"sha256": "a" * 64, "bytes": 10},
           "producers": [runner.producer("harvest", "m"),
                         remap._producer()]}
    jsonschema.validate(new, shape)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**old, "document": {"bytes": 1}}, shape)


def test_a_pass_that_writes_joins_the_list_and_one_that_does_not_stays_out(
        tmp_path):
    stamp = tmp_path / "a.stamp.json"
    stamp.write_text(json.dumps({"model": "first", "spec": "s",
                                 "axis/x/y": "1", "axis/x/z": "1"}))
    current = {"model": "second", "spec": "s", "axis/x/y": "2",
               "axis/x/z": "1"}
    # nothing earned: nothing written, nobody joins
    assert not remap.stamp_forward(stamp, current, set(),
                                   producer={"pass": "top-up"})
    assert "producers" not in json.loads(stamp.read_text())
    assert remap.stamp_forward(stamp, current, {"axis/x/y"},
                               producer={"pass": "top-up", "model": "second"})
    stored = json.loads(stamp.read_text())
    # the model of the harvest stays the stamp's; the list names both
    assert stored["model"] == "first" and stored["axis/x/y"] == "2"
    assert stored["producers"] == [{"pass": "harvest", "model": "first"},
                                   {"pass": "top-up", "model": "second"}]
    current["axis/x/z"] = "2"
    assert remap.stamp_forward(stamp, current, {"axis/x/z"},
                               producer=remap._producer())
    assert [p["pass"] for p in json.loads(stamp.read_text())["producers"]] \
        == ["harvest", "top-up", "remap"]


# -- which model built the index ----------------------------------------------

def test_the_database_remembers_what_built_its_index_and_says_both(tmp_path):
    with sqlite3.connect(tmp_path / "db") as conn:
        schema.apply(conn)
        # a database that records no model says nothing about a query's
        assert schema.embedding_mismatch(conn, "model-a") is None
        assert schema.note_embedding(conn, "model-a", 8, "local", 512,
                                     "0.1.0") is None
        assert schema.meta(conn)["embedding/model"] == "model-a"
        assert schema.meta(conn)["embedding/dim"] == "8"
        # an empty index may change its model: the record follows
        assert schema.note_embedding(conn, "model-b", 16, "api", 512,
                                     "0.1.0") is None
        assert schema.meta(conn)["embedding/model"] == "model-b"
        conn.execute("INSERT INTO Embeddings VALUES (1, 'section_text', "
                     "'section', 1)")
        # one that holds vectors keeps its first model and names the other
        said = schema.note_embedding(conn, "model-c", 16, "api", 512, "0.1.0")
        assert "model-b" in said and "model-c" in said
        schema.note_embedding(conn, "model-c", 16, "api", 512, "0.1.0")
        assert schema.meta(conn)["embedding/model"] == "model-b"
        assert schema.meta(conn)["embedding/also"] == "model-c"
        # the query side: the same model is silent, another is named
        assert schema.embedding_mismatch(conn, "model-b") is None
        assert "model-b" in schema.embedding_mismatch(conn, "model-x")


def test_a_database_without_a_table_of_vectors_holds_none(tmp_path):
    """The embedding run notes its model before it wrote a vector, also
    into a database whose vector table is not there yet."""
    with sqlite3.connect(tmp_path / "bare") as conn:
        assert schema.note_embedding(conn, "model-a", 8, "local", 512,
                                     "0.1.0") is None
        assert schema.meta(conn)["embedding/model"] == "model-a"
        # no vectors, so another model replaces the record and says nothing
        assert schema.note_embedding(conn, "model-b", 8, "local", 512,
                                     "0.1.0") is None
        assert schema.meta(conn)["embedding/model"] == "model-b"


def test_the_reanchor_pass_is_a_command_of_its_own():
    from docpipe import cli
    assert cli.STAGES["reanchor"][0] == "docpipe.extraction.identity"
