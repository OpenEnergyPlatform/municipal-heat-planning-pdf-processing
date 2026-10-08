"""Stage 6 when a batch of inputs gets no vector.

Promised: a batch the embedder cannot serve leaves the other batches embedded,
AND the run then ends non-zero, AND says how many inputs of which embedding
type have no vector, AND counts nothing that failed as embedded, AND a rerun
embeds exactly the inputs that were left without. An input a text-only backend
leaves out on purpose is not a failure.
"""
import json
import logging
import sys
from collections import Counter

import numpy as np
import pytest

from docpipe.chunking import database as DB
from docpipe.chunking import embedding as emb
from docpipe.chunking import pipeline as pl
from docpipe.chunking.chunking import EmbeddingInput


class _Index:
    def __init__(self):
        self.ids = []

    @property
    def ntotal(self):
        return len(self.ids)

    def add_with_ids(self, vectors, ids):
        self.ids.extend(int(i) for i in ids)


class _Embedder:
    """Embeds every batch but the ones whose number it is told to fail."""

    def __init__(self, fail_calls=()):
        self.fail_calls = set(fail_calls)
        self.calls = 0

    def process(self, items):
        self.calls += 1
        if self.calls in self.fail_calls:
            raise RuntimeError("the endpoint did not answer")
        return np.ones((len(items), 4), dtype=np.float32)


def _inp(text, i, kind="section_text", pdf_name="doc"):
    return EmbeddingInput(embedding_type=kind, pdf_name=pdf_name,
                          section_index=i, item_id=None, text=text)


@pytest.fixture
def written(monkeypatch):
    calls = []

    class _Writer:
        def __init__(self, db_path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, pdf_name, records):
            calls.extend(records)

    monkeypatch.setattr(emb, "EmbeddingWriter", _Writer)
    return calls


# ------------------------------------------------- create_embeddings itself

def test_a_failed_batch_does_not_stop_the_batches_after_it(written, tmp_path):
    inputs = [_inp("x" * (n + 1), n) for n in range(6)]       # three batches of 2
    index, missed = _Index(), emb.Unembedded()
    end = emb.create_embeddings(inputs, index, 100, tmp_path / "db",
                                embedder=_Embedder(fail_calls={1}),
                                batch_size=2, unembedded=missed)
    assert end == 104 and index.ids == [100, 101, 102, 103]
    assert len(written) == 4                  # the rows of the later batches
    assert len(missed) == 2                   # and the first one is the loss


def test_what_is_left_without_a_vector_is_counted_by_type_and_document(
        written, tmp_path):
    inputs = [_inp("a", 0, "section_title", "one"),
              _inp("bb", 1, "section_text", "one"),
              _inp("ccc", 2, "table_text", "two"),
              _inp("dddd", 3, "section_text", "two")]
    missed = emb.Unembedded()
    emb.create_embeddings(inputs, _Index(), 0, tmp_path / "db",
                          embedder=_Embedder(fail_calls={1}), batch_size=3,
                          unembedded=missed)
    # sorted by length, the failed batch is the first three
    assert missed.by_type == {"section_title": 1, "section_text": 1,
                              "table_text": 1}
    assert missed.documents == {"one", "two"}
    assert missed.sentence() == (
        "3 input(s) of 2 document(s) have no vector (section_text=1, "
        "section_title=1, table_text=1); a rerun embeds them")


def test_without_a_collector_the_failure_is_raised_once_every_batch_was_tried(
        written, tmp_path):
    inputs = [_inp("x" * (n + 1), n) for n in range(6)]
    index = _Index()
    with pytest.raises(emb.IncompleteIndex, match=r"2 input\(s\) of 1 doc"):
        emb.create_embeddings(inputs, index, 0, tmp_path / "db",
                              embedder=_Embedder(fail_calls={2}),
                              batch_size=2)
    assert index.ntotal == 4                  # the others were finished first


def test_a_run_without_a_failure_raises_nothing_and_collects_nothing(
        written, tmp_path):
    missed = emb.Unembedded()
    inputs = [_inp("x" * (n + 1), n) for n in range(6)]
    assert emb.create_embeddings(inputs, _Index(), 0, tmp_path / "db",
                                 embedder=_Embedder(), batch_size=2,
                                 unembedded=missed) == 6
    assert len(missed) == 0 and not missed
    emb.create_embeddings(inputs, _Index(), 0, tmp_path / "db",
                          embedder=_Embedder(), batch_size=2)   # no raise


def test_an_input_a_text_only_backend_leaves_out_is_not_a_failure(
        written, tmp_path):
    """Nothing went wrong with it: that index holds text vectors by design,
    and a build through an endpoint must not end non-zero over every picture."""
    class _Endpoint:
        model = "embed-1"

        def embed(self, items):
            return [[1.0, 0.0, 0.0]] * len(items)

    inputs = [_inp("text", 0),
              EmbeddingInput(embedding_type="figure_vl", pdf_name="doc",
                             section_index=1, item_id="f", text="a figure",
                             image="crop.png")]
    missed = emb.Unembedded()
    end = emb.create_embeddings(inputs, _Index(), 0, tmp_path / "db",
                                embedder=emb.ApiIndexEmbedder(_Endpoint()),
                                unembedded=missed)
    assert end == 1 and len(missed) == 0


# ------------------------------------------------------- the stage over a database

def _document(tmp_path, n_sections=22):
    """One processed document of n sections, each with a title, a text and a
    table: three inputs of three lengths per section, 66 of them, which the
    stage packs into batches of 32, 32 and 2."""
    root = tmp_path / "processed"
    (root / "doc" / "results").mkdir(parents=True)
    merged = {"sections": [
        {"title": "T%d" % i, "content": "body %d" % i, "page_number": 1,
         "pages": [1], "segments": [], "figures": [],
         "tables": [{"id": "s%d_tbl0" % i, "path": "", "page_number": 1,
                     "caption": "table %d" % i, "markdown": "| %d |" % i}]}
        for i in range(n_sections)]}
    (root / "doc" / "results" / "document.json").write_text(
        json.dumps(merged), encoding="utf-8")
    return root, merged


@pytest.fixture
def stage(kwp_db, tmp_path, monkeypatch):
    """The embed step over a real database, with the model and the index
    file stood in for."""
    db_path, con = kwp_db
    root, merged = _document(tmp_path)
    DB._insert_sections(1, merged, con)
    con.commit()
    index, saved = _Index(), []
    monkeypatch.setattr(pl, "load_or_create_index", lambda path: (index, 0))
    monkeypatch.setattr(pl, "save_index",
                        lambda idx, path: saved.append(idx.ntotal))
    monkeypatch.setattr(pl.usage, "begin", lambda stage: None)

    class _Stage:
        pass

    made = _Stage()
    made.db_path, made.root, made.index, made.saved = db_path, root, index, saved
    made.con = con

    def run(embedder):
        monkeypatch.setattr(pl, "load_embedder", lambda name: embedder)
        pl.run(root, db_path, tmp_path / "faiss.index", step="embed")

    made.run = run
    made.inputs = pl.build_embedding_inputs(merged, "doc", root / "doc")
    return made


def _missing(stage):
    """The inputs of the document the database has no row for, by type: what
    the database says is missing, not what the code says it skipped."""
    existing = DB.get_existing_embeddings(stage.db_path, "doc")
    return Counter(i.embedding_type for i in stage.inputs
                   if (i.embedding_type, i.section_index, i.item_id)
                   not in existing)


def test_the_stage_ends_on_the_inputs_without_a_vector_and_keeps_the_rest(
        stage):
    assert len(stage.inputs) == 66
    with pytest.raises(emb.IncompleteIndex) as caught:
        stage.run(_Embedder(fail_calls={2}))
    missing = _missing(stage)
    assert sum(missing.values()) == 32 and len(missing) >= 2   # one whole batch
    said = str(caught.value)
    assert said.startswith("32 input(s) of 1 document(s) have no vector (")
    assert all(f"{kind}={n}" in said for kind, n in missing.items())
    assert stage.index.ntotal == 34           # the other batches were embedded
    assert stage.saved == [34]                # and saved before the run ended


def test_the_stage_counts_nothing_that_failed_as_embedded(stage, caplog):
    with caplog.at_level(logging.INFO):
        with pytest.raises(emb.IncompleteIndex):
            stage.run(_Embedder(fail_calls={2}))
    said = [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("Embedded ")]
    assert said == ["Embedded 34 new item(s) across 1/1 docs that had open "
                    "items; 32 item(s) failed"]
    assert not any("Embedding complete" in r.getMessage()
                   for r in caplog.records)


def test_a_rerun_embeds_exactly_the_inputs_that_were_left_without(stage):
    with pytest.raises(emb.IncompleteIndex):
        stage.run(_Embedder(fail_calls={2}))
    left = sum(_missing(stage).values())
    again = _Embedder()
    stage.run(again)                          # no failure: no raise
    assert again.calls == 1                   # one batch: what was left
    assert stage.index.ntotal == 34 + left == 66
    assert not _missing(stage)


def test_a_stage_that_failed_nothing_ends_whole(stage, caplog):
    with caplog.at_level(logging.INFO):
        stage.run(_Embedder())
    assert stage.index.ntotal == 66 and not _missing(stage)
    assert any("Embedding complete" in r.getMessage() for r in caplog.records)


def test_the_command_exits_non_zero_over_a_failed_batch_and_zero_without(
        stage, tmp_path, monkeypatch, caplog):
    def command(embedder):
        monkeypatch.setattr(pl, "load_embedder", lambda name: embedder)
        monkeypatch.setattr(sys, "argv", [
            "docpipe.chunking", str(stage.root), str(stage.db_path),
            str(tmp_path / "faiss.index"), "--step", "embed"])
        with pytest.raises(SystemExit) as ended:
            pl.main()
        return ended.value.code

    with caplog.at_level(logging.ERROR):
        assert command(_Embedder(fail_calls={2})) == 1
    assert any("Embedding incomplete: 32 input(s) of 1 document(s) have no "
               "vector" in r.getMessage() for r in caplog.records)
    assert command(_Embedder()) == 0          # the rerun finishes it


def _another_document(stage, name, document_id):
    """A second processed document with the content of the first, so that
    the stage has two of them to embed."""
    folder = stage.root / name / "results"
    folder.mkdir(parents=True)
    merged = json.loads((stage.root / "doc" / "results" / "document.json")
                        .read_text(encoding="utf-8"))
    (folder / "document.json").write_text(json.dumps(merged),
                                          encoding="utf-8")
    stage.con.execute("INSERT INTO Documents (id, filename, num_pages) "
                      "VALUES (?, ?, 9)", (document_id, name + ".pdf"))
    DB._insert_sections(document_id, merged, stage.con)
    stage.con.commit()


@pytest.mark.parametrize("failing, said, kept", [
    ({2}, "32 input(s) of 1 document(s) have no vector (", 100),   # first flush
    ({5}, "32 input(s) of 1 document(s) have no vector (", 100),   # last flush
    ({2, 5}, "64 input(s) of 2 document(s) have no vector (", 68),  # both
])
def test_one_tally_runs_across_every_flush_of_the_stage(
        stage, monkeypatch, caplog, failing, said, kept):
    """The stage embeds in flushes. A batch lost in one of them is named at
    the end of the run whatever the other flushes did, and is counted as
    embedded in none."""
    _another_document(stage, "other", 2)
    monkeypatch.setattr(pl, "EMBED_FLUSH_ITEMS", 60)   # a flush per document
    embedder = _Embedder(fail_calls=failing)
    with caplog.at_level(logging.INFO):
        with pytest.raises(emb.IncompleteIndex) as caught:
            stage.run(embedder)
    assert embedder.calls == 6                # three batches in each flush
    assert str(caught.value).startswith(said)
    assert stage.index.ntotal == kept         # inputs embedded, of 132
    assert stage.saved == [kept]
    assert [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("Embedded ")] == [
        f"Embedded {kept} new item(s) across 2/2 docs that had open items; "
        f"{132 - kept} item(s) failed"]
