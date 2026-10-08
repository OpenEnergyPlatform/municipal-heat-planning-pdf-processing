"""An index is not continued with another embedding model by accident.

What is promised, sentence by sentence:

  * appending to an index that holds vectors of another model stops before
    a vector is written AND names the recorded model AND the configured one;
  * a setting allows the mixture on purpose, and then both are recorded;
  * an empty index may change its model, and a run with --force that drops
    the embeddings first is not stopped;
  * an index that records no model cannot be checked: the first append
    records the configured one and the message says so;
  * the command ends 1 with the cause in one error line and no traceback;
  * `compile examples` says the same warning the harvest says when the
    index was built with another model than the one that embeds its probes,
    and nothing when it is the same.
"""
import json
import logging
import sqlite3
import sys
import types
from argparse import Namespace
from pathlib import Path

import pytest

from docpipe.artifacts import DOCUMENT_JSON
from docpipe.chunking import database as DB
from docpipe.chunking import pipeline as pl
from docpipe.store import schema

BUILT_WITH, EMBEDDING_WITH = "model-built", "model-asked"


class _Index:
    ntotal = 0


# One thing to embed that the database does not have a vector of yet.
INPUT = types.SimpleNamespace(embedding_type="figure_vl", section_index=99,
                              item_id="new")


def _corpus(db, tmp_path, *, model=BUILT_WITH, vectors=True):
    """A processed root with one document, the database that holds it, and
    (when asked) one vector of `model` for its section."""
    root = tmp_path / "processed"
    folder = root / "doc"
    (folder / DOCUMENT_JSON).parent.mkdir(parents=True)
    (folder / DOCUMENT_JSON).write_text(json.dumps({"sections": [
        {"title": "T", "content": "text", "page_number": 1, "pages": [1],
         "segments": [], "tables": [], "figures": []}]}), encoding="utf-8")
    DB.update_database(db, root)
    with sqlite3.connect(db) as conn:
        if model:
            schema.set_meta(conn, {"embedding/model": model})
        if vectors:
            (section,) = conn.execute("SELECT id FROM Sections").fetchone()
            conn.execute("INSERT INTO Embeddings VALUES (0, 'section_text', "
                         "'section', ?)", (section,))
        conn.commit()
    return root


@pytest.fixture
def embedding(monkeypatch):
    """The run of the embed step with the model and the index stubbed: what
    it embeds with is `EMBEDDING_WITH`, and what it writes is counted."""
    wrote = types.SimpleNamespace(batches=[], saved=[])
    monkeypatch.setattr(pl, "load_embedder",
                        lambda name: types.SimpleNamespace(model=EMBEDDING_WITH))
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_Index(), 0))
    monkeypatch.setattr(pl, "index_ids", lambda index: set())
    # a stand-in for the real one, which would drop every row the empty
    # stand-in index does not hold, and so the very rows these tests are about
    monkeypatch.setattr(pl, "drop_embeddings_missing_from_index",
                        lambda db, held: 0)
    monkeypatch.setattr(pl, "remove_ids_from_index", lambda index, ids: None)
    monkeypatch.setattr(pl, "merge_batch", lambda *a, **k: None)
    monkeypatch.setattr(pl, "enrich_page_source", lambda *a, **k: None)
    monkeypatch.setattr(pl, "enrich_caption", lambda *a, **k: None)
    # one input that is not yet embedded, so a run that is not stopped
    # writes a batch
    monkeypatch.setattr(pl, "build_embedding_inputs",
                        lambda merged, name, d: [INPUT])
    monkeypatch.setattr(pl, "create_embeddings", lambda inputs, index, next_id,
                        db, **kw: wrote.batches.append(list(inputs))
                        or next_id + len(inputs))
    monkeypatch.setattr(pl, "save_index",
                        lambda index, path: wrote.saved.append(path))
    monkeypatch.setattr(pl, "ALLOW_MIXED_INDEX", False)
    return wrote


def _recorded(db) -> dict:
    with sqlite3.connect(db) as conn:
        return schema.meta(conn)


# The stop
def test_an_append_with_another_model_stops_before_a_vector_is_written(
        kwp_db, tmp_path, embedding):
    db, _con = kwp_db
    root = _corpus(db, tmp_path)
    before = _recorded(db)

    with pytest.raises(schema.MixedIndex) as stopped:
        pl.run(root, db, tmp_path / "index", step="embed")

    # both models are named
    assert BUILT_WITH in str(stopped.value) \
        and EMBEDDING_WITH in str(stopped.value)
    assert (stopped.value.recorded, stopped.value.configured) \
        == (BUILT_WITH, EMBEDDING_WITH)
    # no vector was written, the index was not saved, and the database
    # still says what built it
    assert embedding.batches == [] and embedding.saved == []
    assert _recorded(db) == before


def test_the_same_run_with_the_same_model_appends(kwp_db, tmp_path, embedding):
    """The case the stop must not touch: what builds the index is what built
    it, and the run writes."""
    db, _con = kwp_db
    root = _corpus(db, tmp_path, model=EMBEDDING_WITH)

    pl.run(root, db, tmp_path / "index", step="embed")

    assert embedding.batches == [[INPUT]] and len(embedding.saved) == 1


def test_a_setting_allows_the_mixture_and_the_database_says_both(
        kwp_db, tmp_path, embedding, monkeypatch, caplog):
    db, _con = kwp_db
    root = _corpus(db, tmp_path)
    monkeypatch.setattr(pl, "ALLOW_MIXED_INDEX", True)

    with caplog.at_level(logging.WARNING, logger=pl.log.name):
        pl.run(root, db, tmp_path / "index", step="embed")

    assert embedding.batches == [[INPUT]]
    said = _recorded(db)
    assert said["embedding/model"] == BUILT_WITH
    assert said["embedding/also"] == EMBEDDING_WITH
    (line,) = [r.getMessage() for r in caplog.records
               if BUILT_WITH in r.getMessage()]
    assert EMBEDDING_WITH in line


def test_the_setting_is_read_from_the_environment_by_its_declared_name():
    from docpipe import settings
    from docpipe.chunking import config
    declared = settings.BY_ENV["EMBEDDING_ALLOW_MIXED_INDEX"]
    assert declared.kind == "flag" and declared.default == "0"
    assert declared.stages == ("chunk",)
    assert config.ALLOW_MIXED_INDEX is False        # off unless it is set


@pytest.mark.parametrize("value,allowed", [("1", True), ("0", False)])
def test_the_setting_is_off_unless_it_is_set(monkeypatch, value, allowed):
    import importlib
    from docpipe.chunking import config
    monkeypatch.setenv("EMBEDDING_ALLOW_MIXED_INDEX", value)
    try:
        assert importlib.reload(config).ALLOW_MIXED_INDEX is allowed
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# What is not stopped
def test_an_index_without_vectors_may_change_its_model(kwp_db, tmp_path,
                                                       embedding):
    db, _con = kwp_db
    root = _corpus(db, tmp_path, vectors=False)

    pl.run(root, db, tmp_path / "index", step="embed")

    assert embedding.batches == [[INPUT]]
    assert _recorded(db)["embedding/model"] == EMBEDDING_WITH
    assert "embedding/also" not in _recorded(db)


def test_a_run_with_force_that_drops_the_embeddings_first_is_not_stopped(
        kwp_db, tmp_path, embedding, monkeypatch):
    """The database step of a forced run deletes the document's vectors
    before the embedding step looks at the index, so what is left to
    continue is empty and the model may change. The real step does it here."""
    db, _con = kwp_db
    root = _corpus(db, tmp_path)
    monkeypatch.setattr(pl, "get_document_faiss_ids", lambda db, name: [0])

    pl.run(root, db, tmp_path / "index", force=True)

    assert embedding.batches == [[INPUT]]
    assert _recorded(db)["embedding/model"] == EMBEDDING_WITH
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM Embeddings").fetchone()[0] == 0


def test_a_run_with_force_that_drops_nothing_first_is_stopped(
        kwp_db, tmp_path, embedding):
    """The twin of the case above, and what makes it mean something: the
    embedding step alone drops the vectors only after it has looked at the
    index, so it is an append."""
    db, _con = kwp_db
    root = _corpus(db, tmp_path)

    with pytest.raises(schema.MixedIndex):
        pl.run(root, db, tmp_path / "index", step="embed", force=True)

    assert embedding.batches == []


def test_a_forced_run_over_part_of_the_corpus_is_stopped(kwp_db, tmp_path,
                                                         embedding):
    """Vectors of a document the run does not cover stay in the index, and
    they are of the other model."""
    db, con = kwp_db
    root = _corpus(db, tmp_path)
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'other.pdf', 3)")
    con.execute("INSERT INTO Sections (document, section_number, title, "
                "content, page_number) VALUES (2, 1, 'O', 'o', 1)")
    (section,) = con.execute("SELECT id FROM Sections WHERE document = 2"
                             ).fetchone()
    con.execute("INSERT INTO Embeddings VALUES (5, 'section_text', "
                "'section', ?)", (section,))
    con.commit()

    with pytest.raises(schema.MixedIndex):
        pl.run(root, db, tmp_path / "index", force=True)      # covers `doc`

    assert embedding.batches == []


def test_an_index_that_records_no_model_records_the_configured_one_and_says_so(
        kwp_db, tmp_path, embedding, caplog):
    db, _con = kwp_db
    root = _corpus(db, tmp_path, model=None)
    assert "embedding/model" not in _recorded(db)

    with caplog.at_level(logging.WARNING, logger=pl.log.name):
        pl.run(root, db, tmp_path / "index", step="embed")

    assert embedding.batches == [[INPUT]]
    assert _recorded(db)["embedding/model"] == EMBEDDING_WITH
    (line,) = [r.getMessage() for r in caplog.records
               if "records no embedding model" in r.getMessage()]
    assert EMBEDDING_WITH in line and "cannot be checked" in line
    # and the next append is checked against it like any other
    with pytest.raises(schema.MixedIndex):
        pl.note_embedding(db, types.SimpleNamespace(model="a-third-model"))


# The command
def test_the_command_ends_one_with_the_cause_and_no_traceback(
        tmp_path, monkeypatch, caplog):
    def stopped(*args, **kwargs):
        raise schema.MixedIndex(BUILT_WITH, EMBEDDING_WITH)

    monkeypatch.setattr(pl, "run", stopped)
    monkeypatch.setattr(sys, "argv", [
        "chunk", str(tmp_path), str(tmp_path / "db"), str(tmp_path / "ix")])

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as ended:
            pl.main()

    assert ended.value.code == 1
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    said = " ".join(r.getMessage() for r in errors)
    assert BUILT_WITH in said and EMBEDDING_WITH in said
    # and the three ways on: the recorded model, a rebuild, the mixture
    assert f"EMBEDDING_MODEL to {BUILT_WITH}" in said
    assert "--force" in said and "EMBEDDING_ALLOW_MIXED_INDEX" in said
    assert all(r.exc_info is None for r in errors), "no traceback"


def test_the_command_over_a_real_append_ends_one_and_writes_nothing(
        kwp_db, tmp_path, embedding, monkeypatch, caplog):
    """The two halves together: the stop that `run` raises is the one the
    command ends on, and the same command with the mixture allowed ends 0."""
    db, _con = kwp_db
    root = _corpus(db, tmp_path)
    argv = ["chunk", str(root), str(db), str(tmp_path / "index"),
            "--step", "embed"]
    monkeypatch.setattr(sys, "argv", argv)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as ended:
            pl.main()

    assert ended.value.code == 1
    assert embedding.batches == [] and embedding.saved == []
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert all(r.exc_info is None for r in errors), "no traceback"
    assert any(BUILT_WITH in r.getMessage() and EMBEDDING_WITH
               in r.getMessage() for r in errors)

    # the violating twin: with the mixture allowed the same command goes on
    monkeypatch.setattr(pl, "ALLOW_MIXED_INDEX", True)
    with pytest.raises(SystemExit) as ended:
        pl.main()
    assert ended.value.code == 0
    assert embedding.batches == [[INPUT]]


# The query side: compile examples
class _Reached(Exception):
    """Raised by the stand-in that comes right after the note, so the test
    does not need a corpus."""


def _examples(tmp_path, monkeypatch, *, built):
    from docpipe.compile import cli
    from docpipe.embedding import config as embedding_config
    from docpipe.inference import faiss_store
    db = tmp_path / "corpus.db"
    with sqlite3.connect(db) as conn:
        schema.apply(conn)
        if built:
            schema.set_meta(conn, {"embedding/model": built})
    index = tmp_path / "corpus.index"
    index.write_bytes(b"")
    monkeypatch.setattr(embedding_config, "EMBEDDING_MODEL", EMBEDDING_WITH)

    def load(path):
        raise _Reached

    monkeypatch.setattr(faiss_store, "load_global_index", load)
    with pytest.raises(_Reached):
        cli._corpus(Namespace(db=str(db), index=str(index), documents=1),
                    None)
    return db


def test_compile_examples_say_what_the_harvest_says(tmp_path, monkeypatch,
                                                    caplog):
    from docpipe.extraction import runner
    with caplog.at_level(logging.WARNING):
        db = _examples(tmp_path, monkeypatch, built=BUILT_WITH)
        compile_lines = [r.getMessage() for r in caplog.records
                         if BUILT_WITH in r.getMessage()]
        caplog.clear()
        runner.note_index_model(db)
        harvest_lines = [r.getMessage() for r in caplog.records
                         if BUILT_WITH in r.getMessage()]

    (compile_line,), (harvest_line,) = compile_lines, harvest_lines
    assert BUILT_WITH in compile_line and EMBEDDING_WITH in compile_line
    # the sentence is the harvest's own; only whose line it is differs
    assert compile_line.split(": ", 1)[1] == harvest_line.split(": ", 1)[1]
    assert compile_line.startswith("compile: ")
    assert harvest_line.startswith("extraction: ")


def test_compile_examples_say_nothing_when_the_model_is_the_same(
        tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        _examples(tmp_path, monkeypatch, built=EMBEDDING_WITH)
    assert [r for r in caplog.records if "do not compare" in r.getMessage()] \
        == []


def test_compile_examples_say_nothing_of_a_database_that_records_no_model(
        tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        _examples(tmp_path, monkeypatch, built=None)
    assert [r for r in caplog.records if "do not compare" in r.getMessage()] \
        == []
