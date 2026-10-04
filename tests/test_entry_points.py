"""A stage started with nothing but its command line.

`python -m docpipe.refinement --profile kwp` ended in a traceback saying it
"needs a profile; set $DOCPIPE_PROFILE or pass one", which is what had just
been done, and `--help` ended the same way. Two stages read their prompts
when they were imported, and the command line is parsed after the import.

A subprocess per call, as in test_every_profile_loads: what is tested is what
happens before and during the import, and that cannot be undone in a process
that conftest has already given a profile.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe import profile as profile_module
from docpipe import prompts
from docpipe.profile import ENV_VAR, bind_command_line

ROOT = Path(__file__).resolve().parents[1]

# The entry point, as `python -m <stage>` runs it, with the heavy optional
# dependencies stubbed where a laptop does not have them.
PROBE = r"""
import runpy, sys, types


class _Permissive(types.ModuleType):
    def __getattr__(self, item):
        return type(item, (), {})


for _name in ("openai", "faiss", "cv2", "fitz", "torch", "ollama", "PIL",
              "PIL.Image", "transformers", "numpy"):
    try:
        __import__(_name)
    except Exception:
        sys.modules[_name] = _Permissive(_name)

stage = sys.argv[1]
sys.argv = [stage] + sys.argv[2:]
runpy.run_module(stage, run_name="__main__")
"""

STAGES = ("docpipe.preprocessing", "docpipe.refinement", "docpipe.visuals",
          "docpipe.chunking", "docpipe.extraction")
# What a stage says when a profile reaches it too late, or not at all.
TOO_LATE = ("needs a profile", "was imported", "LookupError")


def _run(tmp_path, stage, *args, env=None):
    """`python -m stage args` from an empty directory: no .env, no profile."""
    clean = {k: v for k, v in os.environ.items()
             if k not in (ENV_VAR, "DOCPIPE_ENV_FILE", "INFERENCE_ENV_FILE")}
    clean.update({"PYTHONPATH": str(ROOT),
                  "DOCPIPE_USAGE_DB": str(tmp_path / "usage.db")}, **(env or {}))
    return subprocess.run([sys.executable, "-c", PROBE, stage, *args],
                          cwd=tmp_path, env=clean, capture_output=True,
                          text=True)


def _budget(proc) -> int:
    assert proc.returncode == 0, proc.stderr[-2000:]
    return int(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("stage", STAGES)
def test_help_needs_no_profile(tmp_path, stage):
    proc = _run(tmp_path, stage, "--help")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "usage:" in proc.stdout and "--profile" in proc.stdout
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("stage,args", [
    ("docpipe.refinement", ()),
    ("docpipe.visuals", ()),
    ("docpipe.extraction", ("db", "index", "out")),
])
@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_flag_alone_runs_the_stage_as_the_environment_does(tmp_path, stage,
                                                              args, name):
    """The number the model server gets as --max-model-len: it rests on the
    profile's prompts and on what the stage binds when it is imported (how
    many sections fit one request), so it says whether both saw the flag."""
    ask = (*args, "--print-context-budget")
    by_flag = _budget(_run(tmp_path, stage, *ask, "--profile", name))
    by_equals = _budget(_run(tmp_path, stage, f"--profile={name}", *ask))
    by_env = _budget(_run(tmp_path, stage, *ask, env={ENV_VAR: name}))
    assert by_flag == by_equals == by_env > 0


def test_an_abbreviation_the_parser_accepts_is_bound_as_well(tmp_path):
    """argparse reads --prof as --profile. Bound only under its full name,
    the flag was refused as named too late, with a message telling the user
    to pass the flag."""
    ask = ("--print-context-budget",)
    assert _budget(_run(tmp_path, "docpipe.refinement", "--prof", "kwp",
                        *ask)) == _budget(_run(
                            tmp_path, "docpipe.refinement", *ask,
                            env={ENV_VAR: "kwp"}))


def test_the_two_profiles_do_not_ask_for_the_same_window(tmp_path):
    """Or the test above would pass on a stage that ignores the flag."""
    ask = ("db", "index", "out", "--print-context-budget")
    budgets = {name: _budget(_run(tmp_path, "docpipe.extraction", *ask,
                                  "--profile", name))
               for name in ("kwp", "scenarios")}
    assert budgets["kwp"] != budgets["scenarios"], budgets


@pytest.mark.parametrize("stage", ["docpipe.preprocessing",
                                   "docpipe.chunking"])
def test_the_flag_alone_gets_a_stage_to_its_own_work(tmp_path, stage):
    """These two have no number to print. Pointed at a folder that is not
    there they fail on the folder, which is past the profile."""
    proc = _run(tmp_path, stage, str(tmp_path / "nowhere"), "--profile",
                "scenarios")
    said = proc.stdout + proc.stderr
    assert "nowhere" in said, said[-2000:]
    assert not any(text in said for text in TOO_LATE), said[-2000:]


@pytest.mark.parametrize("stage,args", [
    ("docpipe.refinement", ("--print-context-budget",)),
    ("docpipe.visuals", ("--print-context-budget",)),
    ("docpipe.extraction", ("db", "index", "out", "--print-context-budget")),
])
def test_no_profile_at_all_is_said_in_one_line(tmp_path, stage, args):
    proc = _run(tmp_path, stage, *args)
    assert proc.returncode != 0
    assert "no profile" in proc.stderr and "--profile" in proc.stderr
    assert "kwp" in proc.stderr, "which ones there are"
    assert "Traceback" not in proc.stderr


# ---------------------------------------------------------------------------
# The two pieces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("argv,name", [
    (["in", "--profile", "kwp"], "kwp"),
    (["--profile=scenarios", "in"], "scenarios"),
    (["--profile", "kwp", "--profile", "scenarios"], "scenarios"),
    (["in", "--batch"], None),
    (["--prof", "kwp"], "kwp"),
    (["--pro=scenarios", "in"], "scenarios"),
    (["--profile"], None),
    (["--", "--profile", "kwp"], None),
])
def test_the_flag_is_read_off_the_command_line(monkeypatch, argv, name):
    monkeypatch.delenv(ENV_VAR, raising=False)
    bind_command_line(argv)
    assert os.environ.get(ENV_VAR) == name


def test_a_command_line_without_the_flag_leaves_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "kwp")
    bind_command_line(["in", "--batch"])
    assert os.environ[ENV_VAR] == "kwp"


def test_a_prompt_is_read_once_per_profile_and_not_before_it_is_asked_for(
        monkeypatch):
    read: list = []

    @prompts.per_profile
    def system_prompt():
        read.append(os.environ.get(ENV_VAR))
        return f"prompt of {os.environ.get(ENV_VAR)}"

    assert read == [], "defining it reads nothing"
    monkeypatch.setenv(ENV_VAR, "kwp")
    assert system_prompt() == system_prompt() == "prompt of kwp"
    monkeypatch.setenv(ENV_VAR, "scenarios")
    assert system_prompt() == "prompt of scenarios", (
        "a second profile in the same process gets its own")
    monkeypatch.setenv(ENV_VAR, "kwp")
    assert system_prompt() == "prompt of kwp"
    assert read == ["kwp", "scenarios"]


def test_a_stage_that_cannot_run_without_a_profile_says_which_there_are(
        monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    with pytest.raises(SystemExit) as refused:
        profile_module.require_profile()
    message = str(refused.value)
    assert "--profile" in message and ENV_VAR in message
    on_disk = sorted(path.parent.name
                     for path in (ROOT / "profiles").glob("*/profile.py"))
    assert profile_module.available_profiles() == on_disk
    assert "kwp" in on_disk and "__pycache__" not in on_disk
    assert f"(available: {', '.join(on_disk)})" in message
    monkeypatch.setenv(ENV_VAR, "kwp")
    assert profile_module.require_profile().name == "kwp"
