"""A harvest recorded once and made again.

What is promised, sentence by sentence:

  * both runs have the same command line AND the benchmark's settings AND
    the profile it names, and differ only in which cassette variable is set;
  * no setting of the shell reaches either run AND how a model is reached
    reaches the recording only AND neither run reads a project file or a
    .env of its own AND both ask one request at a time AND both run the
    package the benchmark itself runs;
  * a profile can be named by its directory, as seen from the benchmark;
  * a replay counts the levels as `docpipe evaluate` does;
  * a recording is refused for a profile whose documents may not be passed
    on AND where a recorded run already lies AND fails when the harvest
    failed or asked no model;
  * a replay starts from the recorded run's query cache and from no harvest
    AND fails when the harvest did AND holds the result against the
    recorded harvest AND against the benchmark's floors;
  * a replay leaves nothing behind unless it is told where to keep it;
  * a description that is not one is refused, key by key.
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from docpipe import cli
from docpipe.extraction import benchmark, fields, gold
from docpipe.profile import ENV_VAR, PATH_ENV
from docpipe.providers import cassette
from docpipe.extraction.verify import TIER_TEXT

P = "https://x/energy_consumption"


def row(value=241.0, quote="| Erdgas | 241 |"):
    return {"kind": "tuple", "parameter": P, "value": value,
            "value_raw": str(value), "unit": "GWh/a", "tier": TIER_TEXT,
            "quote": quote, "provenance": {"document_id": 1},
            "year": 2040, "year_state": fields.READ}


def write_rows(folder, name, rows):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in rows),
        encoding="utf-8")


def bench(tmp_path, profile="kwp", **more):
    folder = tmp_path / "bench"
    folder.mkdir()
    described = {"profile": profile, "db": "corpus.db",
                 "index": "faiss_index.bin",
                 "arguments": ["--document", "3"],
                 "environment": {"EXTRACT_FIELD_MAX_WINDOWS": "4"}}
    described.update(more)
    (folder / benchmark.MANIFEST).write_text(json.dumps(described),
                                             encoding="utf-8")
    return folder


def recorded(folder, rows=None):
    (folder / benchmark.CASSETTE).write_text("", encoding="utf-8")
    write_rows(folder / benchmark.HARVEST, "a",
               [row()] if rows is None else rows)
    (folder / benchmark.HARVEST / benchmark.QUERY_CACHE).write_bytes(b"vec")


class Harvest:
    """Stands in for the harvest process: notes how it was started and
    writes what it is told to."""

    def __init__(self, rows=None, code=0, tape=None):
        self.rows, self.code, self.tape = rows, code, tape
        self.calls = []

    def __call__(self, words, env):
        self.calls.append((words, env))
        # the .env the harvest is given, while it runs
        self.env_file = Path(env["DOCPIPE_ENV_FILE"]).read_bytes()
        out = __import__("pathlib").Path(words[5])
        self.seen = sorted(path.name for path in out.iterdir()) \
            if out.exists() else []
        if self.rows is not None:
            write_rows(out, "a", self.rows)
        if self.tape is not None:
            __import__("pathlib").Path(
                env[cassette.RECORD_ENV]).write_text(self.tape,
                                                     encoding="utf-8")
        return self.code


# --------------------------------------------------------------- the two runs

def test_both_runs_are_started_the_same_way(tmp_path, monkeypatch):
    monkeypatch.setenv(cassette.REPLAY_ENV, "left over")
    monkeypatch.setenv(ENV_VAR, "scenarios")
    folder = bench(tmp_path)
    first = Harvest(rows=[row()], tape="{}\n")
    assert benchmark.record(folder, run=first) == 0
    second = Harvest(rows=[row()])
    assert benchmark.replay(folder, tmp_path / "again", run=second) == 0

    (words, env), (again, env_again) = first.calls[0], second.calls[0]
    assert words[1:3] == ["-m", "docpipe.extraction"]
    assert words[3:5] == [str(folder / "corpus.db"),
                          str(folder / "faiss_index.bin")]
    assert words[5] == str(folder / benchmark.HARVEST)
    assert again[5] == str(tmp_path / "again")
    assert words[6:] == again[6:] == ["--document", "3"]
    assert words[:5] == again[:5]
    for started in (env, env_again):
        assert started[ENV_VAR] == "kwp"
        assert started["EXTRACT_FIELD_MAX_WINDOWS"] == "4"
    tape = str(folder / benchmark.CASSETTE)
    assert env[cassette.RECORD_ENV] == tape
    assert cassette.REPLAY_ENV not in env
    assert env_again[cassette.REPLAY_ENV] == tape
    assert cassette.RECORD_ENV not in env_again


def test_only_the_benchmarks_settings_reach_the_harvest(tmp_path,
                                                        monkeypatch):
    monkeypatch.setenv("EXTRACT_FIELD_WINDOW", "7")         # the shell's
    monkeypatch.setenv("EXTRACT_LLM_PARALLEL", "128")
    monkeypatch.setenv("LLM_MODEL", "the model of this shell")
    monkeypatch.setenv("LLM_BASE_URL", "http://model.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "a key")
    monkeypatch.setenv("VLM_PROVIDER", "gemini")
    monkeypatch.setenv("DOCPIPE_ENV_FILE", "somewhere/.env")
    monkeypatch.setenv("INFERENCE_ENV_FILE", "elsewhere/.env")
    monkeypatch.setenv("DOCPIPE_CONFIG", "a/docpipe.toml")
    monkeypatch.setenv("NOT_A_SETTING", "kept")
    folder = bench(tmp_path)
    first = Harvest(rows=[row()], tape="{}\n")
    assert benchmark.record(folder, run=first) == 0
    second = Harvest(rows=[row()])
    assert benchmark.replay(folder, tmp_path / "again", run=second) == 0
    env, env_again = first.calls[0][1], second.calls[0][1]
    package = str(Path(benchmark.__file__).resolve().parents[2])
    for harvest, started in ((first, env), (second, env_again)):
        assert "EXTRACT_FIELD_WINDOW" not in started
        assert "LLM_MODEL" not in started
        assert started["EXTRACT_FIELD_MAX_WINDOWS"] == "4"
        assert started["NOT_A_SETTING"] == "kept"
        assert {name: started[name] for name in benchmark.ONE_AT_A_TIME} \
            == benchmark.ONE_AT_A_TIME
        assert started["DOCPIPE_CONFIG"] == ""          # no project file
        assert harvest.env_file == b""                  # and an empty .env
        assert not Path(started["DOCPIPE_ENV_FILE"]).exists()   # now gone
        assert "INFERENCE_ENV_FILE" not in started
        assert started["PYTHONPATH"].split(os.pathsep)[0] == package
    reached = {"LLM_BASE_URL": "http://model.example/v1",
               "LLM_API_KEY": "a key", "VLM_PROVIDER": "gemini"}
    assert {name: env[name] for name in reached} == reached
    assert not set(reached) & set(env_again)


def test_a_profile_beside_the_benchmark_is_named_by_its_directory(
        tmp_path, monkeypatch):
    monkeypatch.setenv(PATH_ENV, "")
    home = tmp_path / "profiles" / "mine"
    home.mkdir(parents=True)
    (home / "profile.py").write_text("", encoding="utf-8")
    folder = bench(tmp_path, profile="../profiles/mine")
    described = benchmark.manifest(folder)
    assert benchmark.profile_of(folder, described) == "mine"
    started = benchmark.environment(folder, described, cassette.REPLAY_ENV,
                                    folder / benchmark.CASSETTE,
                                    tmp_path / "empty.env")
    assert started[ENV_VAR] == "mine"
    assert str(home.parent.resolve()) in started[PATH_ENV].split(os.pathsep)
    # a name stays a name
    assert benchmark.profile_of(folder, {"profile": "kwp"}) == "kwp"


# -------------------------------------------------------------------- record

@pytest.mark.parametrize("profile", ["scenarios", "default"])
def test_nothing_is_recorded_for_documents_that_may_not_be_passed_on(
        tmp_path, profile):
    folder = bench(tmp_path, profile=profile)
    harvest = Harvest(rows=[row()], tape="{}\n")
    with pytest.raises(SystemExit) as caught:
        benchmark.record(folder, run=harvest)
    assert "documents_shareable" in str(caught.value)
    assert harvest.calls == []


@pytest.mark.parametrize("left", ["cassette", "harvest"])
def test_a_second_recording_is_not_appended_to_the_first(tmp_path, left):
    folder = bench(tmp_path)
    if left == "cassette":
        (folder / benchmark.CASSETTE).write_text("{}\n", encoding="utf-8")
    else:
        write_rows(folder / benchmark.HARVEST, "a", [row()])
    harvest = Harvest(rows=[row()], tape="{}\n")
    with pytest.raises(SystemExit) as caught:
        benchmark.record(folder, run=harvest)
    assert "already holds a recorded run" in str(caught.value)
    assert harvest.calls == []


def test_an_empty_harvest_folder_is_no_recorded_run(tmp_path):
    folder = bench(tmp_path)
    (folder / benchmark.HARVEST).mkdir()
    assert benchmark.record(folder, run=Harvest(rows=[row()],
                                                tape="{}\n")) == 0


def test_a_recording_whose_harvest_failed_fails(tmp_path, capsys):
    folder = bench(tmp_path)
    assert benchmark.record(folder, run=Harvest(code=3, tape="{}\n")) == 3
    assert "not a whole run" in capsys.readouterr().err


def test_a_recording_that_asked_no_model_fails(tmp_path, capsys):
    folder = bench(tmp_path)
    assert benchmark.record(folder, run=Harvest(rows=[row()])) == 1
    assert "asked no model" in capsys.readouterr().err


# -------------------------------------------------------------------- replay

def test_a_replay_starts_from_the_recorded_query_cache(tmp_path):
    folder = bench(tmp_path)
    recorded(folder)
    harvest = Harvest(rows=[row()])
    assert benchmark.replay(folder, tmp_path / "again", run=harvest) == 0
    assert harvest.seen == [benchmark.QUERY_CACHE]
    assert (tmp_path / "again" / benchmark.QUERY_CACHE).read_bytes() == b"vec"


def test_a_replay_does_not_start_on_a_harvest(tmp_path):
    folder = bench(tmp_path)
    recorded(folder)
    write_rows(tmp_path / "again", "a", [row()])
    harvest = Harvest(rows=[row()])
    with pytest.raises(SystemExit) as caught:
        benchmark.replay(folder, tmp_path / "again", run=harvest)
    assert "already holds a harvest" in str(caught.value)
    assert harvest.calls == []


@pytest.mark.parametrize("missing", [benchmark.CASSETTE, benchmark.HARVEST])
def test_a_replay_needs_a_recorded_run(tmp_path, missing):
    folder = bench(tmp_path)
    recorded(folder)
    if missing == benchmark.CASSETTE:
        (folder / missing).unlink()
    else:
        __import__("shutil").rmtree(folder / missing)
    harvest = Harvest(rows=[row()])
    with pytest.raises(SystemExit) as caught:
        benchmark.replay(folder, run=harvest)
    assert "--record" in str(caught.value)
    assert harvest.calls == []


def test_a_replay_whose_harvest_failed_fails(tmp_path, capsys):
    folder = bench(tmp_path)
    recorded(folder)
    assert benchmark.replay(folder, run=Harvest(code=1)) == 1
    captured = capsys.readouterr()
    assert "not the recorded run made again" in captured.err
    assert "precision" not in captured.out          # and nothing is counted


def test_a_replay_is_held_against_the_recorded_harvest(tmp_path, capsys):
    folder = bench(tmp_path)
    lost = row(value=5.0, quote="| Strom | 5,0 |")
    recorded(folder, rows=[row(), lost])
    gold.decide(folder / gold.FILE_NAME, "a", lost, "value", gold.CORRECT)
    assert benchmark.replay(folder, run=Harvest(rows=[row()])) == 0
    printed = capsys.readouterr().out
    assert "against the baseline" in printed
    assert "1 row(s) in both" in printed
    assert "lost   1: 1 correct" in printed


@pytest.mark.parametrize("pages, level", [(3, "B"), (0, "A")])
def test_a_replay_counts_the_levels_as_the_evaluation_does(tmp_path, capsys,
                                                           pages, level):
    """A document whose pages a model transcribed is level B at best. The
    benchmark names the database that says which ones were."""
    folder = bench(tmp_path)
    recorded(folder)
    conn = sqlite3.connect(folder / "corpus.db")
    conn.execute('CREATE TABLE "Documents" ("id" INTEGER PRIMARY KEY, '
                 '"filename" TEXT, "page_text_transcribed" INTEGER)')
    conn.execute('INSERT INTO "Documents" VALUES (1, \'a.pdf\', ?)',
                 (pages,))
    conn.commit()
    conn.close()
    for field in gold.fields_of(row()):
        gold.decide(folder / gold.FILE_NAME, "a", row(), field, gold.CORRECT)
    assert benchmark.replay(folder, run=Harvest(rows=[row()])) == 0
    printed = capsys.readouterr().out
    by_level = printed.split("precision by level")[1].split(
        "precision by origin")[0].split()
    assert by_level[0] == level and "correct" in by_level


@pytest.mark.parametrize("floor, code", [(0.5, 0), (0.9, 1)])
def test_a_replay_is_held_against_the_floors_of_the_benchmark(
        tmp_path, capsys, floor, code):
    folder = bench(tmp_path, min_precision=floor)
    good, bad = row(), row(value=5.0, quote="| Strom | 5,0 |")
    recorded(folder, rows=[good, bad])
    for entry, verdict in ((good, gold.CORRECT), (bad, gold.WRONG)):
        for field in gold.fields_of(entry):
            gold.decide(folder / gold.FILE_NAME, "a", entry, field, verdict)
    assert benchmark.replay(folder, run=Harvest(rows=[good, bad])) == code
    assert ("the floor is" in capsys.readouterr().err) is bool(code)


def test_a_replay_leaves_nothing_behind(tmp_path, monkeypatch):
    folder = bench(tmp_path)
    recorded(folder)
    harvest = Harvest(rows=[row()])
    assert benchmark.replay(folder, run=harvest) == 0
    out = __import__("pathlib").Path(harvest.calls[0][0][5])
    assert not out.exists()
    kept = tmp_path / "kept"
    assert benchmark.replay(folder, kept, run=Harvest(rows=[row()])) == 0
    assert (kept / "a.jsonl").is_file()


# ------------------------------------------------------------ the description

@pytest.mark.parametrize("change, says", [
    ({"profile": ""}, "'profile' is missing"),
    ({"db": None}, "'db' is missing"),
    ({"index": 3}, "'index' is missing"),
    ({"arguments": "--force"}, "list of strings"),
    ({"arguments": ["--document", 3]}, "list of strings"),
    ({"environment": {"A": 1}}, "names to strings"),
    ({"environment": {cassette.REPLAY_ENV: "x"}}, "must not set"),
    ({"environment": {ENV_VAR: "x"}}, "must not set"),
    ({"environment": {"EXTRACT_LLM_PARALLEL": "8"}}, "sets it itself"),
    ({"environment": {"PYTHONHASHSEED": "1"}}, "sets it itself"),
    ({"environment": {"LLM_BASE_URL": "http://x/v1"}}, "is reached"),
    ({"environment": {"GEMINI_API_KEY": "k"}}, "is reached"),
    ({"min_precision": "high"}, "must be a number"),
    ({"model": "x"}, "unknown key(s) model"),
])
def test_a_description_that_is_not_one_is_refused(tmp_path, change, says):
    folder = bench(tmp_path, **change)
    with pytest.raises(SystemExit) as caught:
        benchmark.manifest(folder)
    assert says in str(caught.value)
    assert benchmark.MANIFEST in str(caught.value)


@pytest.mark.parametrize("text, says", [
    (None, benchmark.MANIFEST), ("{nope", "not JSON"), ("[]", "an object"),
])
def test_a_folder_without_a_readable_description(tmp_path, text, says):
    folder = tmp_path / "bench"
    folder.mkdir()
    if text is not None:
        (folder / benchmark.MANIFEST).write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        benchmark.manifest(folder)
    assert says in str(caught.value)


def test_the_command(tmp_path):
    assert cli.STAGES["benchmark"][0] == "docpipe.extraction.benchmark"
    folder = bench(tmp_path)
    with pytest.raises(SystemExit) as caught:
        benchmark.main([str(folder), "--record", "--out", str(tmp_path)])
    assert "--out is for a replay" in str(caught.value)
