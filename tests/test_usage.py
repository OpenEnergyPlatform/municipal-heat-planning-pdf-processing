"""Token counts per run: what the server reported, written once per run.

The promise: after `begin(stage)`, every chat reply and every embedding the
server reports adds its input, output and embedding tokens to one row per
stage and model; a repeated flush writes the same row and never counts twice;
and before `begin` nothing is counted or written.
"""
import sqlite3
import types

import pytest

from docpipe import usage


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh, un-begun counter writing into tmp_path."""
    path = tmp_path / "usage.db"
    monkeypatch.setenv("DOCPIPE_USAGE_DB", str(path))
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    monkeypatch.setattr(usage, "_warned", False)
    monkeypatch.setattr(usage.atexit, "register", lambda fn: None)
    return path


def _reply(prompt, completion):
    return types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion))


def _rows(path):
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute(
            "SELECT stage, model, requests, input_tokens, output_tokens, "
            "embedding_tokens FROM token_usage ORDER BY model").fetchall()
    conn.close()
    return rows


def test_nothing_is_counted_or_written_before_begin(db):
    usage.reply(_reply(100, 10), "m")
    usage.add("m", embedding_tokens=5)
    usage.flush()
    assert not db.exists()


def test_input_and_output_are_written_per_stage_and_model(db):
    usage.begin("extraction")
    usage.reply(_reply(1000, 50), "llm")
    usage.reply(_reply(2000, 70), "llm")
    usage.add("emb", embedding_tokens=300, requests=4)
    usage.flush()
    assert _rows(db) == [("extraction", "emb", 4, 0, 0, 300),
                         ("extraction", "llm", 2, 3000, 120, 0)]


def test_a_repeated_flush_does_not_count_twice(db):
    usage.begin("visuals")
    usage.reply(_reply(10, 1), "llm")
    usage.flush()
    usage.flush()
    usage.reply(_reply(10, 1), "llm")
    usage.flush()
    assert _rows(db) == [("visuals", "llm", 2, 20, 2, 0)]


def test_totals_add_up_over_runs(db, monkeypatch):
    usage.begin("refinement")
    usage.reply(_reply(10, 1), "llm")
    usage.flush()
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    usage.begin("refinement")
    usage.reply(_reply(5, 2), "llm")
    usage.flush()
    assert usage.totals(db) == [("refinement", "llm", 2, 2, 15, 3, 0)]


def test_a_reply_without_a_usage_block_counts_nothing(db):
    usage.begin("extraction")
    usage.reply(types.SimpleNamespace(), "llm")
    usage.reply(_reply(None, None), "llm")
    usage.flush()
    assert not db.exists()


def test_rows_are_rewritten_while_the_run_goes_on(db, monkeypatch):
    """A job the scheduler kills never reaches atexit."""
    monkeypatch.setattr(usage, "FLUSH_SECONDS", 0.0)
    usage.begin("chunking")
    usage.add("emb", embedding_tokens=7)
    assert _rows(db) == [("chunking", "emb", 1, 0, 0, 7)]


def test_an_unwritable_database_does_not_take_the_run_down(db, monkeypatch,
                                                           caplog):
    db.mkdir()                          # a directory where the file should be
    usage.begin("extraction")
    usage.reply(_reply(1, 1), "llm")
    usage.flush()
    usage.flush()
    warnings = [r for r in caplog.records if "could not write" in r.message]
    assert len(warnings) == 1


def test_the_vision_call_books_its_reply(db, make_client, tmp_path):
    from docpipe.visuals import vision

    png = tmp_path / "t.png"
    png.write_bytes(b"\x89PNG\r\n")
    reply = _reply(900, 40)
    reply.choices = [types.SimpleNamespace(
        message=types.SimpleNamespace(content='{"a": 1}'))]
    usage.begin("visuals")
    client = make_client(lambda _kw: reply)
    assert vision.call_vision(client, "sys", "user", png, model="vlm") == {"a": 1}
    usage.flush()
    assert _rows(db) == [("visuals", "vlm", 1, 900, 40, 0)]


def test_the_refinement_splitter_books_its_reply(db, make_client, monkeypatch):
    from docpipe.refinement import refine

    reply = _reply(300, 20)
    reply.choices = [types.SimpleNamespace(
        message=types.SimpleNamespace(content="{}"))]
    usage.begin("refinement")
    refine._make_splitter(make_client(lambda _kw: reply))("sys", "user")
    usage.flush()
    assert _rows(db) == [("refinement", refine.LLM_MODEL, 1, 300, 20, 0)]


def test_the_extraction_counter_books_under_the_run_model(db):
    from docpipe.extraction import runner

    usage.begin("extraction")
    runner._observe_usage(types.SimpleNamespace(prompt_tokens=12000,
                                                completion_tokens=300))
    usage.flush()
    assert _rows(db) == [("extraction", runner.LLM_MODEL, 1, 12000, 300, 0)]


def test_the_api_embedder_books_the_tokens_the_endpoint_reports(db,
                                                                monkeypatch):
    from docpipe.embedding.api import ApiEmbedder

    class Client:
        def __init__(self):
            self.embeddings = self

        def create(self, model, input):
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.0]) for _ in input],
                usage=types.SimpleNamespace(prompt_tokens=11 * len(input)))

    emb = ApiEmbedder(base_url="https://example.test/v1", model="emb",
                      batch_size=2)
    client = Client()
    monkeypatch.setattr(emb, "client", lambda: client)
    usage.begin("extraction")
    emb.embed([{"text": "a"}, {"text": "b"}, {"text": "c"}])
    usage.flush()
    assert _rows(db) == [("extraction", "emb", 3, 0, 0, 33)]


def test_the_local_embedder_books_tokens_not_padding(db):
    torch = pytest.importorskip("torch")
    from tests.conftest import needs_real
    needs_real("torch")
    qwen = pytest.importorskip("docpipe.chunking.qwen3_vl_embedding")

    obj = qwen.Qwen3VLEmbedder.__new__(qwen.Qwen3VLEmbedder)
    obj.model_name = "emb"
    obj.param_dtype = torch.float32
    obj.model = types.SimpleNamespace(device="cpu")
    obj.format_model_input = lambda **kw: kw
    # Two inputs padded to 5: three real tokens and one.
    mask = torch.tensor([[1, 1, 1, 0, 0], [1, 0, 0, 0, 0]])
    obj._preprocess_inputs = lambda conv: {"attention_mask": mask}
    obj.forward = lambda inputs: {"last_hidden_state": torch.ones(2, 5, 3),
                                  "attention_mask": inputs["attention_mask"]}
    usage.begin("chunking")
    obj.process([{"text": "abc"}, {"text": "a"}])
    usage.flush()
    assert _rows(db) == [("chunking", "emb", 2, 0, 0, 4)]
