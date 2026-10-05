"""The one command, the profile search path, and the doctor.

The command is run the way a user runs it: in a process of its own, from a
directory that is not the repository, with nothing in the environment but
what the test puts there.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import cli, profile as profiles, settings
from tests.test_entry_points import PROBE

ROOT = Path(__file__).resolve().parent.parent
STRIP = ("DOCPIPE_PROFILE", "DOCPIPE_PROFILE_PATH", "DOCPIPE_CONFIG",
         "DOCPIPE_DATA_ROOT", "DOCPIPE_ENV_FILE", "INFERENCE_ENV_FILE",
         "LLM_MODEL", "LLM_BASE_URL")


def _docpipe(*args, cwd, stubs=True, **env):
    """`docpipe args`. With `stubs`, the libraries a laptop lacks are stood
    in for, as a stage needs them to be imported at all."""
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child.update(env, PYTHONPATH=str(ROOT),
                 DOCPIPE_USAGE_DB=str(Path(cwd) / "usage.db"))
    start = ["-c", PROBE, "docpipe"] if stubs else ["-m", "docpipe"]
    return subprocess.run([sys.executable, *start, *args],
                          cwd=str(cwd), env=child, capture_output=True,
                          text=True)


def _module(module, *args, cwd, **env):
    """`python -m module`, with the libraries a laptop lacks stubbed."""
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child.update(env, PYTHONPATH=str(ROOT),
                 DOCPIPE_USAGE_DB=str(Path(cwd) / "usage.db"))
    return subprocess.run([sys.executable, "-c", PROBE, module, *args],
                          cwd=str(cwd), env=child, capture_output=True,
                          text=True)


def _own_profile(folder, name="myproj"):
    """A profile kept outside the repository, two modules that import each
    other and one prompt."""
    home = folder / name
    (home / "prompts" / "refinement").mkdir(parents=True)
    (home / "profile.py").write_text(
        "from docpipe.profile import Profile\n"
        f"PROFILE = Profile(name={name!r}, title='Mine')\n", encoding="utf-8")
    (home / "words.py").write_text("WORDS = ('alpha', 'beta')\n",
                                   encoding="utf-8")
    (home / "preprocessing.py").write_text(
        "from .words import WORDS\nHYPHEN_EXCEPTIONS = WORDS\n",
        encoding="utf-8")
    (home / "prompts" / "refinement" / "refine.md").write_text(
        "own prompt", encoding="utf-8")
    return home


@pytest.fixture
def clean(monkeypatch):
    """Profiles found during a test are forgotten after it."""
    before = dict(os.environ)
    state = (settings._file, dict(settings._said), set(settings._set),
             settings._env_file)
    modules = set(sys.modules)
    package = sys.modules.get(profiles.PROFILES_PACKAGE)
    path = list(getattr(package, "__path__", ()))
    yield monkeypatch
    for name in set(sys.modules) - modules:
        del sys.modules[name]
    if package is not None:
        package.__path__ = path
    for name in set(os.environ) - set(before):
        del os.environ[name]
    os.environ.update(before)
    (settings._file, settings._said, settings._set,
     settings._env_file) = state


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def test_the_command_lists_what_it_runs(tmp_path):
    run = _docpipe("--help", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    for name in (*cli.STAGES, *cli.OWN):
        assert f"  {name} " in run.stdout, name
    bare = _docpipe(cwd=tmp_path)
    assert bare.returncode == 2 and "usage:" in bare.stdout


def test_an_unknown_command_is_refused_with_the_list(tmp_path):
    run = _docpipe("harvest", cwd=tmp_path)
    assert run.returncode != 0
    assert "unknown command 'harvest'" in run.stderr
    assert "extract" in run.stderr and "Traceback" not in run.stderr


@pytest.mark.parametrize("command, module, args", [
    ("refine", "docpipe.refinement", ["--print-context-budget"]),
    ("visuals", "docpipe.visuals", ["--print-context-budget"]),
])
def test_a_stage_runs_as_its_module_does(tmp_path, command, module, args):
    """Same arguments, same output: the command adds nothing of its own, and
    the profile may stand before the command or after it."""
    direct = _module(module, "--profile", "kwp", *args, cwd=tmp_path)
    assert direct.returncode == 0, direct.stderr
    after = _docpipe(command, "--profile", "kwp", *args, cwd=tmp_path)
    before = _docpipe("--profile", "kwp", command, *args, cwd=tmp_path)
    assert after.returncode == before.returncode == 0, after.stderr
    assert after.stdout == before.stdout == direct.stdout
    assert int(direct.stdout.strip().splitlines()[-1]) > 1000


def test_a_stage_s_own_help_is_reached_through_the_command(tmp_path):
    run = _docpipe("extract", "--help", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "usage: docpipe extract" in run.stdout
    assert "--top-up" in run.stdout
    # Started as a module, it is named as one.
    direct = _module("docpipe.extraction", "--help", cwd=tmp_path)
    assert "usage: python -m docpipe.extraction" in direct.stdout


def test_a_stage_s_exit_code_is_the_command_s(tmp_path):
    run = _docpipe("refine", str(tmp_path / "missing"), cwd=tmp_path)
    assert run.returncode != 0
    assert "no profile" in run.stderr and "Traceback" not in run.stderr


def test_the_project_file_reaches_a_stage_through_the_command(tmp_path):
    (tmp_path / settings.PROJECT_FILE).write_text(
        'profile = "kwp"\n[llm]\nmodel = "from-file"\n', encoding="utf-8")
    run = _docpipe("config", "--set", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "llm.model" in run.stdout and "from-file" in run.stdout
    assert f"[{settings.PROJECT_FILE}; LLM_MODEL]" in run.stdout
    assert "profile:      kwp" in run.stdout
    # And a file named on the command line replaces the one found.
    other = tmp_path / "other.toml"
    other.write_text('profile = "scenarios"\n', encoding="utf-8")
    named = _docpipe("--config", str(other), "config", "--set", cwd=tmp_path)
    assert "profile:      scenarios" in named.stdout
    assert "from-file" not in named.stdout


def test_a_secret_is_not_printed(tmp_path):
    run = _docpipe("config", "--set", cwd=tmp_path, LLM_API_KEY="sk-visible")
    assert run.returncode == 0, run.stderr
    assert "sk-visible" not in run.stdout and "****" in run.stdout


def test_options_are_split_from_the_command():
    assert cli._split(["--profile", "kwp", "extract", "db", "--force"]) == (
        {"profile": "kwp"}, "extract", ["db", "--force"])
    assert cli._split(["--config=x.toml", "doctor"]) == (
        {"config": "x.toml"}, "doctor", [])
    with pytest.raises(SystemExit):
        cli._split(["--profile"])
    with pytest.raises(SystemExit):
        cli._split(["--nonsense", "extract"])


# ---------------------------------------------------------------------------
# Where a profile is found
# ---------------------------------------------------------------------------

def test_a_profile_outside_the_repository_is_named_by_its_directory(
        tmp_path, clean):
    home = _own_profile(tmp_path / "elsewhere")
    clean.delenv(profiles.PATH_ENV, raising=False)
    assert profiles.name_profile(str(home)) == "myproj"
    assert os.environ[profiles.PATH_ENV].split(os.pathsep)[0] == str(
        home.parent.resolve())
    loaded = profiles.load_profile("myproj")
    assert loaded.title == "Mine"
    assert loaded.package_dir == home.resolve()
    assert loaded.prompts_dir == home.resolve() / "prompts"
    # Its modules import each other, as the built-in ones do.
    assert loaded.component("preprocessing", "HYPHEN_EXCEPTIONS") == (
        "alpha", "beta")
    assert loaded.component("extraction", "SPEC_PATH") is None
    assert "myproj" in profiles.available_profiles()
    assert {"kwp", "scenarios"} <= set(profiles.available_profiles())


def test_a_name_stays_a_name_and_a_wrong_directory_is_refused(tmp_path, clean):
    assert profiles.name_profile("kwp") == "kwp"
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit, match="holds no profile.py"):
        profiles.name_profile(str(tmp_path / "empty"))


def test_the_first_directory_on_the_path_wins(tmp_path, clean):
    _own_profile(tmp_path / "first", "kwp")
    clean.setenv(profiles.PATH_ENV, str(tmp_path / "first"))
    assert profiles.profile_locations()["kwp"] == (
        tmp_path / "first" / "kwp").resolve()
    assert profiles.profile_locations()["scenarios"] == (
        ROOT / "profiles" / "scenarios")


def test_a_project_keeps_its_profiles_beside_its_file(tmp_path, clean):
    _own_profile(tmp_path / "profiles")
    (tmp_path / settings.PROJECT_FILE).write_text(
        'profile = "myproj"\n', encoding="utf-8")
    clean.delenv(profiles.ENV_VAR, raising=False)
    clean.delenv("DOCPIPE_DATA_ROOT", raising=False)
    settings.apply(tmp_path / settings.PROJECT_FILE)
    loaded = profiles.load_profile()
    assert loaded.name == "myproj"
    # And its data lives beside the file, not in the installation.
    assert loaded.root == tmp_path.resolve() / "data" / "myproj"


def test_without_a_project_file_a_checkout_keeps_its_data(clean):
    clean.setenv(settings.CONFIG_ENV, "")
    clean.delenv("DOCPIPE_DATA_ROOT", raising=False)
    settings.apply()
    assert profiles.data_dir() == ROOT / "data"


def test_a_stage_runs_under_a_profile_kept_elsewhere(tmp_path):
    """The whole way, in a process of its own: found by its directory, its
    prompt read, its modules imported."""
    home = _own_profile(tmp_path / "elsewhere")
    code = ("from docpipe.profile import bind_command_line, load_profile;"
            "bind_command_line();"
            "from docpipe import prompts;"
            "print(load_profile().name, prompts.text('refinement/refine'))")
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child["PYTHONPATH"] = str(ROOT)
    run = subprocess.run([sys.executable, "-c", code, "--profile", str(home)],
                         cwd=str(tmp_path), env=child, capture_output=True,
                         text=True)
    assert run.returncode == 0, run.stderr
    assert run.stdout.split(None, 1) == ["myproj", "own prompt\n"]
    listed = _docpipe("--profile", str(home), "profiles", cwd=tmp_path)
    assert listed.returncode == 0, listed.stderr
    assert "* myproj" in listed.stdout and "kwp" in listed.stdout


# ---------------------------------------------------------------------------
# The doctor
# ---------------------------------------------------------------------------

def _checks(run):
    return {(c["area"], c["name"]): c for c in json.loads(run.stdout)}


def test_the_doctor_fails_without_a_profile_and_says_what_to_do(tmp_path):
    run = _docpipe("doctor", "--offline", "--json", cwd=tmp_path, stubs=False)
    assert run.returncode == 1, run.stderr
    check = _checks(run)[("profile", "name")]
    assert check["status"] == "fail"
    assert "--profile" in check["hint"] and "kwp" in check["hint"]


def test_the_doctor_passes_an_installation_that_only_lacks_a_stage(tmp_path):
    """A missing stage is a warning. Named with --stage, it is a failure."""
    run = _docpipe("--profile", "kwp", "doctor", "--offline", "--json",
                   cwd=tmp_path, stubs=False,
                   DOCPIPE_DATA_ROOT=str(tmp_path / "data"))
    checks = _checks(run)
    assert checks[("profile", "kwp")]["status"] == "ok"
    assert checks[("profile", "extraction spec")]["detail"] == "provided"
    assert checks[("profile", "source")]["status"] in ("ok", "warn")
    assert checks[("endpoint", "all")]["status"] == "skip"
    assert checks[("data", "database")]["status"] == "warn"
    failed = [c for c in checks.values() if c["status"] == "fail"]
    assert run.returncode == (1 if failed else 0)
    assert all(c["area"] == "packages" and c["name"] == "core"
               for c in failed), failed


def test_the_doctor_reports_a_server_that_does_not_answer(tmp_path,
                                                         monkeypatch):
    from docpipe import doctor, llm_preflight

    def down(base_url, api_key, timeout=30.0, role="llm"):
        raise llm_preflight.PreflightError(f"no answer from {base_url}")

    monkeypatch.setattr(llm_preflight, "serving_limits", down)
    check = doctor._endpoint("llm", "http://localhost:1/v1", "k", "m")
    assert check.status == "fail" and "no answer" in check.detail

    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda *a, **k: (["other"], 4096))
    check = doctor._endpoint("llm", "http://x/v1", "k", "m")
    assert check.status == "fail" and "it serves: other" in check.hint

    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda *a, **k: (["m"], 4096))
    check = doctor._endpoint("llm", "http://x/v1", "k", "m")
    assert check.status == "ok" and "context 4096" in check.detail

    # a hosted role is named by its API, and a name nobody knows is a failure
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    check = doctor._endpoint("llm", "http://localhost:8000/v1", "k", "m")
    assert check.status == "ok" and "the gemini API serves m" in check.detail
    monkeypatch.setenv("LLM_PROVIDER", "telepathy")
    check = doctor._endpoint("llm", "http://x/v1", "k", "m")
    assert check.status == "fail" and "LLM_PROVIDER" in check.detail

    # a hosted model that does not answer: the key, by the name a .env is
    # read under, and not by the project file's, which takes no secret
    monkeypatch.setattr(llm_preflight, "serving_limits", down)
    for role, name in (("llm", "LLM_API_KEY"), ("vlm", "VLM_API_KEY")):
        monkeypatch.setenv(f"{role.upper()}_PROVIDER", "gemini")
        check = doctor._endpoint(role, "http://x/v1", "k", "m")
        assert check.status == "fail" and f"set {name} in .env" in check.hint
        assert f"{role}.api_key" not in check.hint


def test_config_lists_the_settings_of_the_stages_that_have_some(tmp_path):
    from docpipe import settings
    with_settings = sorted({stage for setting in settings.SETTINGS
                            for stage in setting.stages})
    run = _docpipe("config", "--stage", "serve", cwd=tmp_path, stubs=False)
    assert run.returncode == 0 and "DOCPIPE_API_TOKEN" in run.stdout
    for stage in with_settings:
        assert settings.rows(stage), stage
    # a command without settings of its own is not offered: it listed none
    run = _docpipe("config", "--stage", "compile", cwd=tmp_path, stubs=False)
    assert run.returncode == 2 and "invalid choice" in run.stderr
    assert run.stderr.count("'sandbox'") == 1       # and each stage once


def test_the_sandbox_shows_its_help_and_starts_nothing(tmp_path):
    """Also where the library the service needs is not installed, and
    without the token it does not start without."""
    run = _docpipe("sandbox", "--help", cwd=tmp_path, stubs=False,
                   KWP_SANDBOX_TOKEN="")
    assert run.returncode == 0, run.stderr[-800:]
    assert "usage: docpipe sandbox" in run.stdout
    assert "KWP_SANDBOX_TOKEN" in run.stdout
    assert "listening" not in run.stdout


def test_compile_names_the_extra_that_reads_shapes(tmp_path, monkeypatch):
    from docpipe.compile import cli as compile_cli
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "rdflib", None)    # as if not installed
    with pytest.raises(SystemExit) as caught:
        compile_cli.main(["spec", "--shapes", str(shapes), "--out",
                          str(tmp_path / "draft.json")])
    assert "docpipe[kg]" in str(caught.value)
    assert not (tmp_path / "draft.json").exists()


def test_reanchor_refuses_a_harvest_that_is_not_there(tmp_path, monkeypatch):
    """A directory that does not exist has no rows that moved, and said
    so with 0. Now it is said that nothing was looked at."""
    import sqlite3

    from docpipe.extraction import identity
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    database = tmp_path / "corpus.db"
    sqlite3.connect(database).close()
    with pytest.raises(SystemExit) as caught:
        identity.main([str(database), str(tmp_path / "typo")])
    assert "is not a directory" in str(caught.value)
    empty = tmp_path / "harvest"
    empty.mkdir()
    with pytest.raises(SystemExit) as caught:
        identity.main([str(database), str(empty)])
    assert "holds no harvest file" in str(caught.value)


def test_the_doctor_counts_the_documents_of_a_database(tmp_path):
    import sqlite3

    from docpipe import doctor
    from docpipe.profile import Profile
    probe = Profile(name="probe", data_root=tmp_path)
    assert {c.name: c.status for c in doctor.check_data(probe)}[
        "database"] == "warn"
    with sqlite3.connect(probe.db_path) as conn:
        conn.execute("CREATE TABLE Documents (id INTEGER)")
        conn.executemany("INSERT INTO Documents VALUES (?)", [(1,), (2,)])
    found = {c.name: c for c in doctor.check_data(probe)}
    assert found["database"].status == "ok"
    assert found["database"].detail.startswith("2 document(s)")


# ---------------------------------------------------------------------------
# What a review of the first version found
# ---------------------------------------------------------------------------

def test_the_options_are_taken_after_the_command_too():
    assert cli._pull(["--profile", "kwp", "--offline"],
                     ("--profile", "--config")) == (
        {"profile": "kwp"}, ["--offline"])
    assert cli._pull(["db", "--config=x.toml", "--", "--config", "y"],
                     ("--config",)) == (
        {"config": "x.toml"}, ["db", "--", "--config", "y"])
    # a stage takes --profile itself: it stays among its arguments
    assert cli._pull(["--profile", "kwp"], ("--config",)) == (
        {}, ["--profile", "kwp"])
    with pytest.raises(SystemExit):
        cli._pull(["--config"], ("--config",))


def test_the_doctor_takes_the_profile_where_its_hint_says(tmp_path):
    before = _docpipe("--profile", "kwp", "doctor", "--offline", cwd=tmp_path)
    after = _docpipe("doctor", "--profile", "kwp", "--offline", cwd=tmp_path)
    assert after.returncode == before.returncode, after.stderr
    assert "unrecognized" not in after.stderr
    assert after.stdout == before.stdout


def test_profiles_takes_no_arguments(tmp_path):
    run = _docpipe("profiles", "--nonsense", cwd=tmp_path)
    assert run.returncode == 2 and "usage: docpipe profiles" in run.stdout
    assert _docpipe("profiles", "--help", cwd=tmp_path).returncode == 0


def test_a_named_project_file_is_the_one_a_started_process_finds(tmp_path,
                                                                clean):
    clean.delenv(settings.CONFIG_ENV, raising=False)
    path = tmp_path / "prod.toml"
    path.write_text('profile = "kwp"\n', encoding="utf-8")
    cli._settle({"config": str(path)})
    assert os.environ[settings.CONFIG_ENV] == str(path.resolve())
    assert settings.find() == path.resolve()


def test_a_stage_gets_the_project_file_named_after_it(tmp_path):
    (tmp_path / "prod.toml").write_text(
        '[llm]\nmodel = "from-prod"\n', encoding="utf-8")
    run = _docpipe("config", "--set", "--config", "prod.toml", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "from-prod" in run.stdout


def test_a_registration_whose_package_is_gone_is_skipped(tmp_path, clean,
                                                         caplog):
    """One stale entry point is not the end of every profile lookup."""
    left = tmp_path / "gone-1.0.dist-info"
    left.mkdir()
    (left / "METADATA").write_text("Name: gone\nVersion: 1.0\n",
                                   encoding="utf-8")
    (left / "entry_points.txt").write_text(
        "[docpipe.profiles]\nacme = acme_profiles_gone.kwp\n",
        encoding="utf-8")
    clean.syspath_prepend(str(tmp_path))
    profiles._registered.cache_clear()
    try:
        with caplog.at_level("WARNING"):
            assert profiles._scan_registered() == []
        assert "acme_profiles_gone.kwp" in caplog.text
        assert "kwp" in profiles.profile_locations()
    finally:
        profiles._registered.cache_clear()


def test_the_chat_s_own_files_sit_with_the_project_s(tmp_path):
    (tmp_path / "docpipe.toml").write_text('profile = "kwp"\n',
                                           encoding="utf-8")
    (tmp_path / "sub").mkdir()
    code = ("from docpipe.profile import shared_file; from pathlib import "
            "Path; print(shared_file('inference_app_query_cache.db', "
            "Path('data/inference_app_query_cache.db')))")
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child["PYTHONPATH"] = str(ROOT)
    inside = subprocess.run([sys.executable, "-c", code],
                            cwd=str(tmp_path / "sub"), env=child,
                            capture_output=True, text=True)
    assert Path(inside.stdout.strip()) == (
        tmp_path / "data" / "inference_app_query_cache.db")
    text = (ROOT / "docpipe" / "app" / "config.py").read_text(
        encoding="utf-8")
    for name in ("inference_app_query_cache.db",
                 "inference_app_request_log.db"):
        assert f'shared_file(\n    "{name}"' in text


# ---------------------------------------------------------------------------
# The command, once more: what it promises before a stage is imported
# ---------------------------------------------------------------------------

STAGE_PACKAGES = ("docpipe.preprocessing", "docpipe.refinement",
                  "docpipe.visuals", "docpipe.chunking", "docpipe.extraction")


def test_importing_the_command_imports_no_stage(tmp_path):
    """A stage binds the profile and the project file when it is imported, so
    the module that settles both must not have imported one."""
    code = ("import sys, docpipe.cli;"
            f"stages = {STAGE_PACKAGES!r};"
            "print(sorted(n for n in sys.modules if any("
            "n == s or n.startswith(s + '.') for s in stages)));"
            "print('docpipe.cli' in sys.modules)")
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child["PYTHONPATH"] = str(ROOT)
    run = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path),
                         env=child, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert run.stdout.split("\n")[:2] == ["[]", "True"], run.stdout


def _budget(run):
    assert run.returncode == 0, run.stderr
    return int(run.stdout.strip().splitlines()[-1])


def test_a_project_file_named_to_the_command_changes_what_the_stage_reads(
        tmp_path):
    """Before the command or after it, and a stage never sees the option."""
    (tmp_path / "other.toml").write_text("[refine]\nwindow_size = 7\n",
                                         encoding="utf-8")
    budget = ("--print-context-budget",)
    plain = _budget(_docpipe("--profile", "kwp", "refine", *budget,
                             cwd=tmp_path))
    before = _docpipe("--config", "other.toml", "--profile", "kwp", "refine",
                      *budget, cwd=tmp_path)
    after = _docpipe("--profile", "kwp", "refine", "--config", "other.toml",
                     *budget, cwd=tmp_path)
    assert "unrecognized" not in after.stderr
    assert _budget(before) != plain
    assert _budget(after) == _budget(before)


def test_a_stage_s_argument_error_is_exit_code_two(tmp_path):
    run = _docpipe("--profile", "kwp", "refine", "--no-such-option",
                   cwd=tmp_path)
    assert run.returncode == 2, run.stderr
    assert "unrecognized arguments: --no-such-option" in run.stderr
    assert "Traceback" not in run.stderr


def test_the_version_is_printed_and_nothing_else_runs(tmp_path):
    run = _docpipe("--version", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    from docpipe import __version__
    assert run.stdout == f"docpipe {__version__}\n"


def test_a_project_file_that_is_not_there_is_one_line_and_not_a_traceback(
        tmp_path):
    run = _docpipe("--config", "missing.toml", "profiles", cwd=tmp_path)
    assert run.returncode != 0
    assert "missing.toml" in run.stderr and "Traceback" not in run.stderr


def test_config_lists_only_what_was_set_and_only_what_a_command_reads(
        tmp_path):
    (tmp_path / settings.PROJECT_FILE).write_text(
        'profile = "kwp"\n[llm]\nmodel = "from-file"\n', encoding="utf-8")
    everything = _docpipe("config", cwd=tmp_path)
    changed = _docpipe("config", "--set", cwd=tmp_path)
    assert everything.returncode == changed.returncode == 0, changed.stderr
    # the default-valued name is listed by the full listing and not by --set
    assert "ANSWER_CONTEXT_TOKENS" in everything.stdout
    assert "ANSWER_CONTEXT_TOKENS" not in changed.stdout
    assert "LLM_MODEL" in changed.stdout and "from-file" in changed.stdout
    # a stage's own listing leaves out the other stages' settings
    chat = _docpipe("config", "--stage", "chat", cwd=tmp_path)
    harvest = _docpipe("config", "--stage", "extract", cwd=tmp_path)
    assert chat.returncode == harvest.returncode == 0, chat.stderr
    assert "ANSWER_CONTEXT_TOKENS" in chat.stdout
    assert "EXTRACT_" not in chat.stdout
    assert "EXTRACT_FIELD_ROWS" in harvest.stdout
    assert "ANSWER_CONTEXT_TOKENS" not in harvest.stdout


@pytest.mark.parametrize("name", ["DOCPIPE_ENV_FILE", "INFERENCE_ENV_FILE"])
def test_a_child_process_does_not_inherit_the_callers_env_file(
        tmp_path, monkeypatch, name):
    """The helper that starts the command says what its child may read."""
    leak = tmp_path / "leak.env"
    leak.write_text("LLM_TIMEOUT=4321\n", encoding="utf-8")
    monkeypatch.setenv(name, str(leak))
    run = _docpipe("config", "--set", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "LLM_TIMEOUT" not in run.stdout


def test_the_profiles_command_lists_every_profile_and_marks_the_active_one(
        tmp_path):
    run = _docpipe("--profile", "kwp", "profiles", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    rows = {line[2:].split()[0]: line for line in run.stdout.splitlines()}
    assert {"kwp", "scenarios", "default"} <= set(rows)
    assert rows["kwp"].startswith("* ") and rows["scenarios"].startswith("  ")
    for name in ("kwp", "scenarios"):
        assert rows[name].endswith(str(ROOT / "profiles" / name)), rows[name]


# ---------------------------------------------------------------------------
# The doctor, once more
# ---------------------------------------------------------------------------

def test_a_missing_package_fails_only_the_stage_that_was_named(tmp_path):
    if importlib.util.find_spec("streamlit") is not None:
        pytest.skip("streamlit is installed: the chat has nothing missing")
    named = _docpipe("--profile", "kwp", "doctor", "--stage", "chat",
                     "--offline", "--json", cwd=tmp_path, stubs=False)
    everything = _docpipe("--profile", "kwp", "doctor", "--offline", "--json",
                          cwd=tmp_path, stubs=False)
    check = _checks(named)[("packages", "chat")]
    assert check["status"] == "fail" and "docpipe[app]" in check["hint"]
    assert named.returncode == 1
    # the other stages' packages are not looked at, and unnamed it is a warning
    assert ("packages", "extract") not in _checks(named)
    assert _checks(everything)[("packages", "chat")]["status"] == "warn"


def test_a_missing_package_is_a_failure_with_a_stage_and_a_warning_without(
        monkeypatch):
    """The same finding in this process, whether or not streamlit is here."""
    from docpipe import doctor
    monkeypatch.setattr(doctor, "_missing", lambda modules: [
        name for name in modules if name == "streamlit"])
    named = {c.name: c for c in doctor.check_packages("chat")}
    assert set(named) == {"core", "chat"}
    assert named["chat"].status == doctor.FAIL
    everything = {c.name: c for c in doctor.check_packages(None)}
    assert everything["chat"].status == doctor.WARN
    assert everything["extract"].status == doctor.OK


def test_the_doctor_prints_a_hint_under_its_line_and_counts_what_it_printed(
        tmp_path):
    run = _docpipe("--profile", "kwp", "doctor", "--offline", cwd=tmp_path,
                   stubs=False, DOCPIPE_DATA_ROOT=str(tmp_path / "data"))
    *printed, summary = run.stdout.splitlines()
    found = re.fullmatch(r"(\d+) check\(s\), (\d+) failure\(s\), "
                         r"(\d+) warning\(s\)", summary)
    assert found, run.stdout
    checks = [line for line in printed if not line.startswith(" ")]
    states = [line.split()[1] for line in checks]
    assert tuple(map(int, found.groups())) == (
        len(checks), states.count("fail"), states.count("warn"))
    assert run.returncode == (1 if "fail" in states else 0)
    # a hint stands on the line after the check it belongs to
    at = next(i for i, line in enumerate(printed)
              if line.split()[:3] == ["data", "warn", "database:"])
    assert printed[at + 1].strip() == "-> `docpipe chunk` writes it"
    assert all(line.strip().startswith("-> ")
               for line in printed if line.startswith(" "))


@pytest.fixture
def asked(monkeypatch):
    """The doctor's endpoint check with a server that serves each role's own
    model, recording the role it was asked about."""
    from docpipe import doctor, llm_preflight
    roles = []

    def serving(base_url, api_key, timeout=30.0, role="llm"):
        roles.append(role)
        return [f"{role}-model"], 4096

    monkeypatch.setattr(llm_preflight, "serving_limits", serving)
    # the openai package is a stand-in here: whether it is there is not asked
    monkeypatch.setattr(doctor, "importlib", NS(util=NS(
        find_spec=lambda name: object())))
    for name in ("LLM_PROVIDER", "VLM_PROVIDER", "LLM_BASE_URL",
                 "VLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MODEL", "llm-model")
    monkeypatch.setenv("VLM_MODEL", "vlm-model")
    return roles


@pytest.mark.parametrize("stage, wanted", [
    (None, ["llm"]), ("refine", ["llm"]), ("extract", ["llm"]),
    ("chat", ["llm"]), ("visuals", ["vlm"]),
    ("ingest", []), ("preprocess", []), ("chunk", []), ("graph", []),
])
def test_the_doctor_asks_about_the_role_each_stage_uses(asked, stage, wanted):
    from docpipe import doctor
    checks = doctor.check_endpoints(stage, offline=False)
    assert [c.name for c in checks] == wanted
    assert asked == wanted                      # the role reached the server
    assert [c.status for c in checks] == ["ok"] * len(wanted)
    assert all(f"{c.name}-model" in c.detail for c in checks)


def test_a_vision_model_that_was_set_is_asked_about_with_the_text_model(
        asked, monkeypatch):
    from docpipe import doctor
    monkeypatch.setenv("VLM_PROVIDER", "gemini")
    checks = doctor.check_endpoints(None, offline=False)
    assert [c.name for c in checks] == ["llm", "vlm"] == asked


def test_offline_the_doctor_asks_no_server_at_all(asked):
    from docpipe import doctor
    (check,) = doctor.check_endpoints("extract", offline=True)
    assert (check.status, check.detail) == (doctor.SKIP, "--offline")
    assert asked == []


# ---------------------------------------------------------------------------
# --profile after the command, for the commands that are their own module
# ---------------------------------------------------------------------------

TOO_LATE = ("was named after the stage was imported", "Traceback",
            # a module run as a command that its package had imported before
            "RuntimeWarning")


def _a_harvest(tmp_path):
    folder = tmp_path / "harvest"
    folder.mkdir()
    (folder / "a.jsonl").write_text(json.dumps({
        "kind": "tuple", "parameter": "p", "value": 1.0, "value_raw": "1",
        "quote": "the value is 1 here", "provenance": {"page": 1}}) + "\n",
        encoding="utf-8")
    return folder


@pytest.mark.parametrize("command, module, rest, says", [
    ("export", "docpipe.serve.export", (), "document"),
    ("evaluate", "docpipe.extraction.evaluate", (), "without decisions"),
    # the profile's database, there or not: either way it was looked for
    ("lexical", "docpipe.inference.lexical", ("--check",), "kwp"),
    ("serve", "docpipe.serve", ("--mcp",), ""),
])
def test_a_profile_named_after_the_command_reaches_it(tmp_path, command,
                                                     module, rest, says):
    """`docpipe export H --profile kwp` and `python -m docpipe.serve.export
    H --profile kwp`. Either was refused as named too late, with a message
    that said to do what had just been done."""
    folder = _a_harvest(tmp_path)
    words = (() if command == "lexical" else (str(folder),)) + rest + (
        "--profile", "kwp")
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child.update(PYTHONPATH=str(ROOT),
                 DOCPIPE_USAGE_DB=str(tmp_path / "usage.db"))
    for start in (["-c", PROBE, "docpipe", command], ["-c", PROBE, module]):
        run = subprocess.run([sys.executable, *start, *words],
                             cwd=str(tmp_path), env=child, input="",
                             capture_output=True, text=True)
        said = run.stdout + run.stderr
        assert not any(text in said for text in TOO_LATE), said[-1500:]
        assert says in said, said[-1500:]


def test_the_inference_package_loads_the_answer_loop_only_when_asked():
    """Importing the package imports none of its modules: one of them run
    as a command (`lexical`) is then run once, and without the libraries
    the answer loop needs."""
    import ast
    tree = ast.parse((ROOT / "docpipe" / "inference" / "__init__.py")
                     .read_text(encoding="utf-8"))
    assert not [node for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom))]
    import docpipe.inference as package
    from docpipe.inference import answer
    assert package.Corpus is answer.Corpus
    assert package.answer_question is answer.answer_question
    with pytest.raises(AttributeError):
        package.no_such_thing


def test_preflight_is_a_command_and_ends_one_on_a_failure(tmp_path):
    """The gate before a corpus run, for whoever has only installed the
    package. The built-in profile has no spec, which is a hard failure."""
    shown = _docpipe("preflight", "--help", cwd=tmp_path, stubs=False)
    assert shown.returncode == 0, shown.stderr[-800:]
    assert "usage: docpipe preflight" in shown.stdout
    run = _docpipe("preflight", "default", cwd=tmp_path)
    assert run.returncode == 1, run.stderr[-800:]
    assert "=== default ===" in run.stdout
    assert "X spec present" in run.stdout
    # the profile in effect is the one checked when none is named
    same = _docpipe("--profile", "default", "preflight", cwd=tmp_path)
    assert same.returncode == 1 and "=== default ===" in same.stdout
    # and one that passes ends 0
    passing = _docpipe("preflight", "kwp", cwd=tmp_path)
    assert passing.returncode == 0, passing.stdout[-1500:]
    assert "0 failure(s)" in passing.stdout
