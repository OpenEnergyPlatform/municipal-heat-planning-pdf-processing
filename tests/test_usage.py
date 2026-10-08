"""Token counts per run: what the server reported, written once per run.

The promise: after `begin(stage)`, every chat reply and every embedding the
server reports adds its input, output and embedding tokens to one row per
stage and model; a repeated flush writes the same row and never counts twice;
and before `begin` nothing is counted or written.

The second promise, of the profile and the cache: every row says which profile
its run was under AND how many of its input tokens the provider served from
its cache, a ledger written before those two columns gets them on its next
write AND is read as it is before that, AND the report can be limited to one
profile.
"""
import os
import sqlite3
import types
from pathlib import Path

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
    from docpipe.visuals import replies, vision

    png = tmp_path / "t.png"
    png.write_bytes(b"\x89PNG\r\n")
    reply = _reply(900, 40)
    reply.choices = [types.SimpleNamespace(
        message=types.SimpleNamespace(content='{"markdown": "m"}'))]
    usage.begin("visuals")
    client = make_client(lambda _kw: reply)
    assert vision.call_vision(client, "sys", "user", png, model="vlm",
                              reply=replies.TABLE) == {"markdown": "m"}
    usage.flush()
    assert _rows(db) == [("visuals", "vlm", 1, 900, 40, 0)]


def test_the_refinement_splitter_books_its_reply(db, make_client, monkeypatch):
    from docpipe.refinement import refine

    reply = _reply(300, 20)
    reply.choices = [types.SimpleNamespace(
        message=types.SimpleNamespace(content='{"cuts": []}'))]
    usage.begin("refinement")
    refine._make_splitter(make_client(lambda _kw: reply))("sys", "user")
    usage.flush()
    assert _rows(db) == [("refinement", refine.LLM_MODEL, 1, 300, 20, 0)]


def test_every_window_request_books_its_reply_and_a_cut_one_too(
        db, make_client, monkeypatch):
    """A reply that was cut off cost its tokens all the same, and a window
    asked in halves is three requests: the ledger counts what the server was
    asked, not what was used."""
    from docpipe.refinement import refine

    def answer(content, finish, prompt, completion):
        reply = _reply(prompt, completion)
        reply.choices = [types.SimpleNamespace(
            finish_reason=finish, message=types.SimpleNamespace(
                content=content, reasoning_content=None))]
        return reply

    replies = iter([
        answer('{"sections": [', "length", 300, 20),
        answer('{"sections": [{"_action": "keep", "title": "A"}]}', "stop",
               100, 10),
        answer('{"sections": [{"_action": "keep", "title": "B"}]}', "stop",
               100, 10)])
    usage.begin("refinement")
    client = make_client(lambda _kw: next(replies))
    got = refine._ask_window([{"title": "A", "content": "a"},
                              {"title": "B", "content": "b"}], client, None)
    assert [s["title"] for s in got] == ["A", "B"]
    usage.flush()
    assert _rows(db) == [("refinement", refine.LLM_MODEL, 3, 500, 40, 0)]


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


# -- what the tokens cost ------------------------------------------------------

def _project(tmp_path, monkeypatch, text):
    from docpipe import settings
    file = tmp_path / "docpipe.toml"
    file.write_text(text, encoding="utf-8")
    monkeypatch.setenv("DOCPIPE_CONFIG", str(file))
    settings.apply()
    return settings


def test_the_report_prices_the_models_the_project_file_prices(
        db, tmp_path, monkeypatch, capsys):
    """Cost is tokens times the price per million, per kind; a model without
    a price is shown without a cost and is not in the sum."""
    settings = _project(tmp_path, monkeypatch, '''
[prices]
"big" = { input = 4.0, output = 20.0 }
"vectors" = { embedding = 0.5 }
''')
    try:
        usage.begin("extraction")
        usage.add("big", input_tokens=2_000_000, output_tokens=500_000)
        usage.add("vectors", embedding_tokens=3_000_000, requests=3)
        usage.add("unpriced", input_tokens=9_000_000)
        usage.flush()
        assert usage.cost(("extraction", "big", 1, 1, 2_000_000, 500_000, 0),
                          settings.prices()) == 18.0
        assert usage.main([str(db)]) == 0
        out = capsys.readouterr().out
        lines = {line.split()[1]: line.split()[-1]
                 for line in out.splitlines() if line.startswith("extraction")}
        assert lines == {"big": "18.00", "vectors": "1.50", "unpriced": "-"}
        assert "cost: 19.50 over 2 of 3 rows" in out
        assert "per million tokens" in out
    finally:
        monkeypatch.setenv("DOCPIPE_CONFIG", "")
        settings.apply()


def test_without_prices_the_report_has_no_cost_column(db, capsys):
    usage.begin("extraction")
    usage.add("big", input_tokens=10)
    usage.flush()
    usage.main([str(db)])
    out = capsys.readouterr().out
    assert "cost" not in out and "big" in out


@pytest.mark.parametrize("table,complaint", [
    ('"m" = 3.0', "must be a table"),
    ('"m" = { input = "cheap" }', "must be a number"),
    ('"m" = { input = -1 }', "must be a number"),
    ('"m" = { prompt = 1.0 }', "is no price"),
    ('"m" = { input = true }', "must be a number"),
    ('"m" = {}', "must be a table"),
    ('"m" = { cached = -0.1 }', "must be a number"),
    ('"m" = { cached = "free" }', "must be a number"),
])
def test_a_price_that_cannot_be_one_is_refused_when_the_file_is_read(
        tmp_path, monkeypatch, table, complaint):
    from docpipe import settings
    file = tmp_path / "docpipe.toml"
    file.write_text(f"[prices]\n{table}\n", encoding="utf-8")
    with pytest.raises(settings.ConfigError, match=complaint):
        settings.read(file)


def test_a_cached_price_is_read_and_a_near_miss_of_its_name_is_not(
        tmp_path, monkeypatch):
    from docpipe import settings
    file = tmp_path / "docpipe.toml"
    file.write_text('[prices]\n"m" = { input = 4.0, cached = 0.4 }\n',
                    encoding="utf-8")
    monkeypatch.setattr(settings, "_file", file)
    assert settings.prices() == {"m": {"input": 4.0, "cached": 0.4}}
    file.write_text('[prices]\n"m" = { input = 4.0, cache = 0.4 }\n',
                    encoding="utf-8")
    with pytest.raises(settings.ConfigError, match="cache is no price"):
        settings.prices()


# -- where the counts go -------------------------------------------------------

@pytest.fixture
def project_state(monkeypatch):
    """What a test that applies a project file leaves behind is put back:
    the settings module's record of the last file, and the environment."""
    from docpipe import settings
    before = dict(os.environ)
    state = (settings._file, dict(settings._said), set(settings._set),
             settings._env_file)
    monkeypatch.delenv("DOCPIPE_USAGE_DB", raising=False)
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    monkeypatch.setattr(usage, "_warned", False)
    monkeypatch.setattr(usage.atexit, "register", lambda fn: None)
    yield settings
    for name in set(os.environ) - set(before):
        del os.environ[name]
    os.environ.update(before)
    (settings._file, settings._said, settings._set,
     settings._env_file) = state


def test_the_counts_go_beside_the_project_file(project_state, tmp_path):
    project = tmp_path / "docpipe.toml"
    project.write_text('profile = "kwp"\n', encoding="utf-8")
    project_state.apply(project)
    where = usage.db_path()
    assert where == tmp_path.resolve() / "data" / "usage.db"
    # and a run writes there, the folder made on the way
    usage.begin("extraction")
    usage.add("m", input_tokens=5)
    usage.flush()
    assert _rows(where) == [("extraction", "m", 1, 5, 0, 0)]


def test_without_a_project_file_the_counts_go_where_they_always_did(
        project_state, monkeypatch):
    monkeypatch.setenv("DOCPIPE_CONFIG", "")
    project_state.apply()
    assert project_state.project_file() is None
    assert usage.db_path() == Path("data/usage.db")


def test_a_named_database_wins_over_the_project_file(project_state, tmp_path,
                                                     monkeypatch):
    project = tmp_path / "docpipe.toml"
    project.write_text('profile = "kwp"\n', encoding="utf-8")
    project_state.apply(project)
    named = tmp_path / "elsewhere" / "counts.db"
    monkeypatch.setenv("DOCPIPE_USAGE_DB", str(named))
    assert usage.db_path() == named


# ---------------------------------------------------------------------------
# The profile and the cache
# ---------------------------------------------------------------------------

def _all(path):
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute(
            "SELECT stage, model, profile, requests, input_tokens, "
            "output_tokens, cached_tokens FROM token_usage "
            "ORDER BY stage, model, profile").fetchall()
    conn.close()
    return rows


def _begin_as(monkeypatch, profile, stage="extraction"):
    """A new process of `stage`, started under `profile` (None: no profile in
    effect)."""
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    if profile is None:
        monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    else:
        monkeypatch.setenv("DOCPIPE_PROFILE", profile)
    usage.begin(stage)


def test_a_row_says_the_profile_its_run_was_under(db, monkeypatch):
    _begin_as(monkeypatch, "alpha")
    usage.add("m", input_tokens=10)
    usage.flush()
    _begin_as(monkeypatch, "beta")
    usage.add("m", input_tokens=7)
    usage.flush()
    assert [(r[2], r[4]) for r in _all(db)] == [("alpha", 10), ("beta", 7)]
    # limited to one profile, the sums hold that profile's runs and nobody's
    # else; a profile that never ran holds nothing
    assert usage.sums(db, "alpha")[("extraction", "m")].input_tokens == 10
    assert usage.sums(db, "beta")[("extraction", "m")].input_tokens == 7
    assert usage.sums(db, "gamma") == {}
    assert usage.totals(db, "alpha") == [("extraction", "m", 1, 1, 10, 0, 0)]


def test_a_run_under_no_profile_is_no_profile_s(db, monkeypatch):
    _begin_as(monkeypatch, None)
    usage.add("m", input_tokens=10)
    usage.flush()
    assert _all(db)[0][2] is None
    assert usage.sums(db, "kwp") == {}
    assert usage.unattributed(db) == 1
    # but it is in the total of a report that is not limited
    assert usage.totals(db) == [("extraction", "m", 1, 1, 10, 0, 0)]


def test_the_cached_part_of_the_input_is_counted_beside_it(db):
    usage.begin("extraction")
    # as the hosted adapters report it
    usage.reply(types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=1000, completion_tokens=50, cached_tokens=600)), "llm")
    # as the OpenAI client of a server of one's own does
    usage.reply(types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=500, completion_tokens=5,
        prompt_tokens_details=types.SimpleNamespace(cached_tokens=200))), "llm")
    usage.reply(_reply(100, 1), "llm")          # a server that says nothing
    usage.flush()
    assert [r[3:] for r in _all(db)] == [(3, 1600, 56, 800)]
    assert usage.sums(db)[("extraction", "llm")].cached_tokens == 800


def test_cached_of_reads_the_two_shapes_and_nothing_else():
    shape = types.SimpleNamespace
    assert usage.cached_of(shape(cached_tokens=7)) == 7
    assert usage.cached_of(shape(
        prompt_tokens_details=shape(cached_tokens=5))) == 5
    # the adapters' own count wins where both are there
    assert usage.cached_of(shape(
        cached_tokens=7, prompt_tokens_details=shape(cached_tokens=5))) == 7
    for says_nothing in (None, shape(), shape(cached_tokens="7"),
                         shape(prompt_tokens_details=None),
                         shape(prompt_tokens_details=shape(cached_tokens=None))):
        assert usage.cached_of(says_nothing) == 0


@pytest.mark.parametrize("claimed", [True, "9", 2.5, None, -4])
def test_a_cached_count_that_is_no_count_is_not_counted(db, claimed):
    """A server that sends something else where a token count belongs must
    not move the ledger: the input is counted, the cache is not."""
    usage.begin("extraction")
    usage.reply(types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=100, completion_tokens=1, cached_tokens=claimed)), "llm")
    usage.reply(types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=100, completion_tokens=1,
        prompt_tokens_details=types.SimpleNamespace(cached_tokens=claimed))),
        "llm")
    usage.flush()
    assert [(r[4], r[6]) for r in _all(db)] == [(200, 0)]


def test_the_extraction_counter_books_the_cached_tokens_too(db):
    from docpipe.extraction import runner

    usage.begin("extraction")
    runner._observe_usage(types.SimpleNamespace(
        prompt_tokens=12000, completion_tokens=300, cached_tokens=9000))
    usage.flush()
    assert [(r[4], r[6]) for r in _all(db)] == [(12000, 9000)]


def _old_ledger(path):
    """The ledger as it was written before the profile and the cached
    tokens: the table, its view and one run."""
    with sqlite3.connect(str(path)) as conn:
        conn.executescript("""
        CREATE TABLE token_usage (
            run TEXT NOT NULL, job TEXT, host TEXT NOT NULL,
            stage TEXT NOT NULL, model TEXT NOT NULL, started TEXT NOT NULL,
            updated TEXT NOT NULL, requests INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
            embedding_tokens INTEGER NOT NULL,
            PRIMARY KEY (run, stage, model));
        CREATE VIEW token_totals AS
            SELECT stage, model, COUNT(DISTINCT run) AS runs,
                   SUM(requests) AS requests,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(embedding_tokens) AS embedding_tokens
            FROM token_usage GROUP BY stage, model;
        INSERT INTO token_usage VALUES
            ('old', NULL, 'h', 'extraction', 'm', 't', 't', 5, 500, 50, 0);
        """)
    conn.close()


def test_an_older_ledger_gets_the_columns_on_the_next_write(db, monkeypatch,
                                                            caplog):
    _old_ledger(db)
    _begin_as(monkeypatch, "alpha")
    usage.add("m", input_tokens=10, cached_tokens=4)
    usage.flush()
    usage.add("m", input_tokens=10, cached_tokens=4)
    usage.flush()                                   # the columns exist now
    assert not [r for r in caplog.records if "could not write" in r.message]
    old, new = sorted(_all(db), key=lambda r: r[4], reverse=True)
    assert old == ("extraction", "m", None, 5, 500, 50, 0)      # as it was
    assert new == ("extraction", "m", "alpha", 2, 20, 0, 8)
    with sqlite3.connect(str(db)) as conn:
        cursor = conn.execute("SELECT * FROM token_totals")
        names = [d[0] for d in cursor.description]
        view = cursor.fetchall()
    conn.close()
    assert "cached_tokens" in names and view[0][names.index("requests")] == 7
    # the run it adds is the profile's and the run it kept is nobody's
    assert usage.sums(db, "alpha")[("extraction", "m")].input_tokens == 20
    assert usage.sums(db)[("extraction", "m")].input_tokens == 520


def test_an_older_ledger_is_read_as_it_is_and_never_written(db, capsys):
    _old_ledger(db)
    before = db.read_bytes()
    assert usage.totals(db) == [("extraction", "m", 1, 5, 500, 50, 0)]
    assert usage.sums(db)[("extraction", "m")].cached_tokens == 0
    assert usage.sums(db, "alpha") == {}            # nobody's rows are alpha's
    assert usage.unattributed(db) == 1
    assert usage.main([str(db)]) == 0
    assert "500" in capsys.readouterr().out
    assert usage.main([str(db), "--profile", "alpha"]) == 0
    said = capsys.readouterr().out
    assert "no token counts for profile alpha" in said
    assert "1 row(s)" in said and "belong to none" in said
    assert db.read_bytes() == before


def test_the_report_can_be_limited_to_one_profile(db, monkeypatch, capsys):
    _begin_as(monkeypatch, "alpha")
    usage.add("m", input_tokens=1_111)
    usage.flush()
    _begin_as(monkeypatch, "beta")
    usage.add("m", input_tokens=2_222)
    usage.flush()
    assert usage.main([str(db), "--profile", "alpha"]) == 0
    only = capsys.readouterr().out
    assert "profile alpha" in only and "1,111" in only and "2,222" not in only
    usage.main([str(db)])
    assert "3,333" in capsys.readouterr().out       # not limited: both
    usage.main([str(db), "--profile", "gamma"])
    assert "no token counts for profile gamma" in capsys.readouterr().out


def test_a_profile_given_as_its_directory_is_limited_by_its_name(
        db, tmp_path, monkeypatch, capsys):
    """The flag reads as the stages read it. The ledger keeps names, so a
    path taken as it stands would match no run and report an empty ledger."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", "")      # put back afterwards
    folder = tmp_path / "somewhere" / "alpha"
    folder.mkdir(parents=True)
    (folder / "profile.py").write_text("", encoding="utf-8")
    _begin_as(monkeypatch, "alpha")
    usage.add("m", input_tokens=1_111)
    usage.flush()
    _begin_as(monkeypatch, "beta")
    usage.add("m", input_tokens=2_222)
    usage.flush()
    assert usage.main([str(db), "--profile", str(folder)]) == 0
    only = capsys.readouterr().out
    assert "profile alpha" in only and "1,111" in only and "2,222" not in only
    assert "no token counts" not in only


def test_cached_input_costs_the_cached_price_and_without_one_the_input_price():
    row = ("extraction", "m", 1, 1, 1_000_000, 0, 0)
    both = {"m": {"input": 4.0, "cached": 0.5}}
    assert usage.cost(row, both, cached=600_000) == pytest.approx(
        0.4 * 4.0 + 0.6 * 0.5)
    # a cache the table says nothing about never makes the bill smaller
    assert usage.cost(row, {"m": {"input": 4.0}}, cached=600_000) == 4.0
    # more cached than there is input is not a refund
    assert usage.cost(row, both, cached=5_000_000) == pytest.approx(0.5)
    assert usage.cost(row, both, cached=-5) == 4.0


def test_the_report_prices_what_the_ledger_says_was_cached(
        db, tmp_path, monkeypatch, capsys):
    settings = _project(tmp_path, monkeypatch, '''
[prices]
"big" = { input = 4.0, cached = 0.4, output = 20.0 }
''')
    try:
        usage.begin("extraction")
        usage.add("big", input_tokens=1_000_000, cached_tokens=500_000,
                  output_tokens=100_000)
        usage.flush()
        assert usage.main([str(db)]) == 0
        out = capsys.readouterr().out
        assert "cached" in out.splitlines()[0]
        # 0.5 M at 4.0, 0.5 M at 0.4, 0.1 M at 20.0
        assert "cost: 4.20 over 1 of 1 rows" in out
    finally:
        monkeypatch.setenv("DOCPIPE_CONFIG", "")
        settings.apply()
