"""`docpipe run`: the stages from a folder to a corpus, one after the other.

The promise: it starts the stages that --from, --to and --skip leave, of
ingest, preprocess, refine, visuals, chunk and lexical, in that order and
each as `docpipe <stage>` with the arguments the profile gives it; it says
which stage starts; it stops at the first stage that ends non-zero with that
stage's exit code; and it starts none while a selected stage lacks an
argument the profile cannot give. Each clause has a test, and each test has
a case that violates it.
"""
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import cli, run
from docpipe.profile import load_profile
from docpipe.store import schema
from tests.test_cli import _docpipe
from tests.test_status import needs_fts5

ROOT = Path(__file__).resolve().parent.parent


class Launcher:
    """Stands in for the process: records what was started, ends with the
    exit code the test chose for the stage."""

    def __init__(self, codes=None):
        self.codes = codes or {}
        self.started = []

    def __call__(self, command):
        assert command[:3] == [sys.executable, "-m", "docpipe"], command
        self.started.append((command[3], command[4:]))
        return self.codes.get(command[3], 0)

    @property
    def stages(self):
        return [stage for stage, _ in self.started]


def _profile(**given):
    """A profile that names its paths and answers for its source."""
    source = given.get("source", NS(default_location=lambda data: data))
    return NS(name="demo", pdf_dir=Path("demo") / "pdf",
              processed_dir=Path("demo") / "pdf" / "processed",
              component=lambda module, attr: source)


# ---------------------------------------------------------------------------
# which stages, in which order, each as its own command
# ---------------------------------------------------------------------------

def test_the_stages_run_in_order_each_as_its_own_command():
    started = Launcher()
    assert run.run_stages(_profile(), run.select(), started) == 0
    assert started.stages == ["ingest", "preprocess", "refine", "visuals",
                              "chunk", "lexical"]
    # nothing but these six: the harvest is its own, costly command
    assert "extract" not in started.stages
    assert set(run.STAGES) <= set(cli.STAGES) and "extract" not in run.STAGES


@pytest.mark.parametrize("first, last, skip, expected", [
    (None, None, [], ["ingest", "preprocess", "refine", "visuals", "chunk",
                      "lexical"]),
    ("preprocess", "chunk", ["visuals"], ["preprocess", "refine", "chunk"]),
    (None, "preprocess", [], ["ingest", "preprocess"]),
    ("chunk", None, [], ["chunk", "lexical"]),
    (None, None, ["ingest", "lexical"], ["preprocess", "refine", "visuals",
                                         "chunk"]),
    ("refine", "refine", [], ["refine"]),
])
def test_from_to_and_skip_choose_the_stages(first, last, skip, expected):
    started = Launcher()
    run.run_stages(_profile(), run.select(first, last, skip), started)
    assert started.stages == expected


@pytest.mark.parametrize("args, says", [
    (["--from", "chunk", "--to", "refine"], "comes after"),
    (["--skip", "ingest", "preprocess", "refine", "visuals", "chunk",
      "lexical"], "no stage is left"),
    (["--from", "chunk", "--skip", "chunk", "lexical"], "no stage is left"),
])
def test_a_range_that_holds_no_stage_is_refused_before_anything_starts(
        args, says, monkeypatch, capsys):
    started = Launcher()
    monkeypatch.setattr(run, "launch", started)
    with pytest.raises(SystemExit) as refused:
        run.main(args)
    assert refused.value.code == 2
    assert says in capsys.readouterr().err
    assert started.started == []


def test_a_stage_that_is_not_one_of_the_six_is_refused(monkeypatch, capsys):
    started = Launcher()
    monkeypatch.setattr(run, "launch", started)
    for args in (["--from", "extract"], ["--skip", "reanchor"],
                 ["--to", "nonsense"]):
        with pytest.raises(SystemExit) as refused:
            run.main(args)
        assert refused.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert started.started == []
    with pytest.raises(ValueError, match="not a stage"):
        run.select("extract")


# ---------------------------------------------------------------------------
# the arguments the profile gives each stage
# ---------------------------------------------------------------------------

def test_each_stage_is_given_what_its_command_line_needs_from_the_profile():
    started = Launcher()
    profile = _profile()
    run.run_stages(profile, run.select(), started)
    given = dict(started.started)
    assert given["ingest"] == []
    assert given["preprocess"] == [str(profile.pdf_dir)]
    assert given["refine"] == given["visuals"] == ["--batch"]
    assert given["chunk"] == given["lexical"] == []


def test_those_arguments_are_ones_the_stages_own_parsers_take():
    """So a stage that renames its input or its batch switch fails here
    and not on a corpus. Under a profile the paths a stage is left to find
    itself are the profile's own."""
    from docpipe.chunking import pipeline as chunking
    from docpipe.ingest import cli as ingesting
    from docpipe.preprocessing import pipeline as preprocessing
    from docpipe.refinement import pipeline as refining
    from docpipe.visuals import pipeline as visuals

    profile = load_profile("default")
    started = Launcher()
    run.run_stages(profile, run.select(), started)
    given = dict(started.started)

    asked = preprocessing._build_parser().parse_args(given["preprocess"])
    assert asked.input == str(profile.pdf_dir) and asked.output is None
    for stage, module in (("refine", refining), ("visuals", visuals)):
        parsed = module._build_parser().parse_args(given[stage])
        assert parsed.batch is True and parsed.input is None
    assert ingesting._build_parser().parse_args(given["ingest"]).source is None
    chunked = chunking._build_parser().parse_args(given["chunk"])
    assert (chunked.data_dir, chunked.db_path, chunked.index_path) == (
        None, None, None)
    # and without the batch switch the processed folder is one document,
    # which is what the stage would do with the folder of all of them
    assert refining._build_parser().parse_args([]).batch is False


def test_a_profile_that_names_its_document_list_by_default_is_not_asked_for_it():
    started = Launcher()
    folder = load_profile("default")
    assert run.run_stages(folder, run.select("ingest", "ingest"), started) == 0
    assert started.started == [("ingest", [])]


# ---------------------------------------------------------------------------
# an argument the profile cannot give: nothing starts
# ---------------------------------------------------------------------------

def test_nothing_starts_while_a_stage_lacks_an_argument(capsys):
    """kwp reads its documents from a register that has to be named."""
    started = Launcher()
    code = run.run_stages(load_profile("kwp"), run.select(), started)
    said = capsys.readouterr().err
    assert code == 2 and started.started == []
    assert "nothing was started" in said and "ingest needs --source" in said
    assert "--skip" in said and "--from" in said
    # the same run without that stage has nothing missing
    assert run.run_stages(load_profile("kwp"), run.select("preprocess"),
                          started) == 0
    assert started.stages == ["preprocess", "refine", "visuals", "chunk",
                              "lexical"]


def test_a_profile_without_a_source_and_one_whose_source_will_not_load_are_named(
        capsys):
    def broken(module, attr):
        raise ImportError("No module named 'pandas'")

    for profile, says in (
            (_profile(source=None), "a document source"),
            (NS(**{**vars(_profile()), "component": broken}),
             "No module named 'pandas'")):
        started = Launcher()
        assert run.run_stages(profile, run.select(), started) == 2
        assert started.started == []
        assert says in capsys.readouterr().err


def test_a_stage_that_is_skipped_is_not_asked_for_its_argument():
    started = Launcher()
    needs_source = _profile(source=NS(default_location=lambda data: None))
    assert run.run_stages(needs_source, run.select(), started) == 2
    assert started.started == []
    assert run.run_stages(needs_source, run.select(skip=["ingest"]),
                          started) == 0
    assert started.stages[0] == "preprocess"


def test_every_stage_that_lacks_something_is_named_not_only_the_first(capsys):
    """Two stages in one run cannot start; a user who fixes one finds the
    other only on the next call otherwise. (Today only ingest can lack an
    argument, so the second is made up here.)"""
    started = Launcher()
    saved = dict(run._GIVEN)
    try:
        run._GIVEN["chunk"] = lambda profile: ([], ["--db: nowhere"])
        code = run.run_stages(
            _profile(source=NS(default_location=lambda data: None)),
            run.select(), started)
    finally:
        run._GIVEN.clear()
        run._GIVEN.update(saved)
    said = capsys.readouterr().err
    assert code == 2 and started.started == []
    assert "ingest needs --source" in said and "chunk needs --db" in said
    assert "2 stage(s)" in said


# ---------------------------------------------------------------------------
# which stage starts, and where the run stops
# ---------------------------------------------------------------------------

def test_the_stage_that_starts_is_said_before_it_starts(capsys):
    seen = []

    def watching(command):
        seen.append(capsys.readouterr().out)
        return 0

    run.run_stages(_profile(), run.select("refine", "chunk"), watching)
    assert len(seen) == 3
    assert "3 stage(s) under the profile 'demo': refine, visuals, chunk" \
        in seen[0]
    for line, stage in zip(seen, ("refine", "visuals", "chunk")):
        assert f"docpipe {stage}" in line, line
    assert "stage 1 of 3" in seen[0] and "stage 3 of 3" in seen[2]
    assert "docpipe refine --batch" in seen[0]


def test_the_first_stage_that_ends_non_zero_stops_the_run_with_its_code(capsys):
    started = Launcher({"refine": 3, "chunk": 5})
    code = run.run_stages(_profile(), run.select(), started)
    said = capsys.readouterr().err
    assert code == 3                       # its own, not 1 and not the later 5
    assert started.stages == ["ingest", "preprocess", "refine"]
    assert "refine ended with exit code 3" in said
    assert "not run: visuals, chunk, lexical" in said


def test_a_run_that_ends_0_in_every_stage_ends_0_and_says_how_many(capsys):
    assert run.run_stages(_profile(), run.select("chunk"), Launcher()) == 0
    out = capsys.readouterr()
    assert "2 stage(s) ended 0" in out.out and out.err == ""


def test_the_last_stage_failing_leaves_nothing_unrun(capsys):
    started = Launcher({"lexical": 1})
    assert run.run_stages(_profile(), run.select("chunk"), started) == 1
    said = capsys.readouterr().err
    assert "lexical ended with exit code 1" in said and "not run" not in said


def test_an_interrupted_stage_ends_the_run_and_says_so(capsys):
    def interrupted(command):
        if command[3] == "refine":
            raise KeyboardInterrupt
        return 0

    code = run.run_stages(_profile(), run.select(), interrupted)
    assert code == run.INTERRUPTED
    said = capsys.readouterr().err
    assert "refine was interrupted" in said and "not run: visuals" in said


def test_a_stage_command_is_the_one_command_with_the_stage_and_its_arguments():
    assert run.stage_command("refine", ["--batch"]) == [
        sys.executable, "-m", "docpipe", "refine", "--batch"]
    assert run.stage_command("lexical", []) == [
        sys.executable, "-m", "docpipe", "lexical"]
    # and it is a command that exists: the one command takes the stage
    assert run.stage_command("lexical", [])[3] in cli.STAGES


def test_a_stage_is_a_process_of_its_own_and_its_exit_code_is_returned():
    ends = lambda code: run.launch(
        [sys.executable, "-c", f"raise SystemExit({code})"])
    assert ends(0) == 0 and ends(7) == 7


def test_a_process_a_signal_ended_is_told_as_a_shell_tells_it(monkeypatch):
    monkeypatch.setattr(run.subprocess, "call", lambda command: -9)
    assert run.launch(["any"]) == 137


# ---------------------------------------------------------------------------
# through the one command, and in processes of their own
# ---------------------------------------------------------------------------

def test_the_command_reaches_the_run_with_the_profile_named_before_it(
        monkeypatch):
    started = Launcher()
    monkeypatch.setattr(run, "launch", started)
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    assert cli.main(["--profile", "default", "run", "--from", "chunk"]) == 0
    assert started.stages == ["chunk", "lexical"]
    # a profile that cannot start a stage is a refusal of the whole run
    started.started.clear()
    assert cli.main(["--profile", "kwp", "run"]) == 2
    assert started.started == []


def test_a_run_through_the_command_ends_with_the_exit_code_of_a_real_stage(
        tmp_path):
    """No stub: preprocess is started as a process, finds no folder of PDFs
    where the profile says they are, and ends 1; the stages after it are
    not started and the run ends 1."""
    data = tmp_path / "data"
    done = _docpipe("--profile", "default", "run", "--from", "preprocess",
                    "--to", "refine", cwd=tmp_path, DOCPIPE_DATA_ROOT=str(data))
    assert done.returncode == 1, done.stdout + done.stderr
    assert "stage 1 of 2: docpipe preprocess" in done.stdout
    # the stage's own reason, so a stage that died on a missing library or
    # on an argument it was not given does not pass for this
    assert "neither a PDF nor a folder" in done.stderr, done.stderr
    assert "preprocess ended with exit code 1; not run: refine" in done.stderr
    assert "docpipe refine" not in done.stdout


@needs_fts5
def test_a_run_through_the_command_runs_a_real_stage_to_its_end(tmp_path):
    from docpipe.inference import lexical
    data = tmp_path / "data"
    db = data / "default" / "default.db"
    db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db)) as connection:
        schema.apply(connection)
        connection.execute(
            "INSERT INTO Documents (id, filename) VALUES (1, 'a.pdf')")
        connection.execute(
            "INSERT INTO Sections (document, section_number, title, content) "
            "VALUES (1, 0, 'Wärme', 'Das Netz')")
        connection.commit()
    ran = _docpipe("--profile", "default", "run", "--from", "lexical",
                   cwd=tmp_path, DOCPIPE_DATA_ROOT=str(data))
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "stage 1 of 1: docpipe lexical" in ran.stdout
    assert lexical.state(db) == "current"
    # and the same without a database: the stage ends 1, and so does the run
    lexical.path_for(db).unlink()
    db.unlink()
    missing = _docpipe("--profile", "default", "run", "--from", "lexical",
                       cwd=tmp_path, DOCPIPE_DATA_ROOT=str(data))
    assert missing.returncode == 1, missing.stdout + missing.stderr
    assert "lexical ended with exit code 1" in missing.stderr
    assert not lexical.path_for(db).exists()


def test_what_init_tells_a_newcomer_to_type_is_what_works(tmp_path):
    """It printed preprocess, refine and visuals as they stand, and run on
    their own they take no folder (preprocess) or take the processed folder
    for one document (refine, visuals). Every command it lists is one, and
    the stages are one command."""
    home = tmp_path / "reports"
    home.mkdir()
    made = _docpipe("init", cwd=home)
    assert made.returncode == 0, made.stderr
    typed = [line.split()[1] for line in made.stdout.splitlines()
             if line.startswith("  docpipe ")]
    assert typed == ["doctor", "run", "chat"]
    assert set(typed) <= set(cli.STAGES) | set(cli.OWN)
    assert "docpipe status" in made.stdout
    assert "docpipe run --skip ingest" in made.stdout
