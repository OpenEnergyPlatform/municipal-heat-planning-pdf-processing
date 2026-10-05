"""The profile the package brings itself, and a profile that extends another.

Promised: a profile that names another one in `extends` gets that profile's
part wherever it has none of its own (a module's attribute, a prompt, the
schema, one phrase) AND a profile that names none gets nothing from anybody;
the built-in profile is found last, so a project's own of the same name
wins; a folder of PDFs is a document source; and `docpipe init` leaves a
project that the next command runs in.
"""
import ast
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe import profile as profiles, prompts, settings
from docpipe.inference import wording
from docpipe.inference.catalog import load_catalog
from docpipe.ingest.folder import FolderSource
from docpipe.ingest.models import Source
from docpipe.profile import Profile, load_profile
from docpipe.store import schema

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "docpipe" / "builtin" / "default"
STRIP = ("DOCPIPE_PROFILE", "DOCPIPE_PROFILE_PATH", "DOCPIPE_CONFIG",
         "DOCPIPE_DATA_ROOT")


@pytest.fixture
def clean(monkeypatch):
    """Profiles found during a test are forgotten after it."""
    before = dict(os.environ)
    state = (settings._file, dict(settings._said), set(settings._set),
             settings._env_file)
    modules = set(sys.modules)
    package = sys.modules.get(profiles.PROFILES_PACKAGE)
    path = list(getattr(package, "__path__", ()))
    checked = dict(wording._checked)
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
    wording._checked.clear()
    wording._checked.update(checked)
    profiles._BOUND = None


def _child(folder, name="mine", extends="default", **files):
    """A profile outside the repository; `files` are {relative path: text}."""
    home = folder / name
    home.mkdir(parents=True)
    (home / "__init__.py").write_text("", encoding="utf-8")
    line = f", extends={extends!r}" if extends else ""
    (home / "profile.py").write_text(
        "from docpipe.profile import Profile\n"
        f"PROFILE = Profile(name={name!r}{line})\n", encoding="utf-8")
    for relative, text in files.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return home


def _bound(clean, folder):
    clean.setenv(profiles.PATH_ENV, str(folder))


# -- where the built-in profile is found --------------------------------------

def test_the_built_in_profile_is_found_last(tmp_path, clean):
    assert profiles.search_path()[-1] == DEFAULT.parent.resolve()
    assert profiles.profile_locations()["default"] == DEFAULT.resolve()
    # a project's own profile of that name is the one that is loaded
    _child(tmp_path, "default", extends=None)
    _bound(clean, tmp_path)
    assert profiles.profile_locations()["default"] == (
        tmp_path / "default").resolve()


def test_no_profile_is_taken_when_none_is_named(clean):
    clean.delenv(profiles.ENV_VAR, raising=False)
    assert profiles.active_profile() is None
    with pytest.raises(LookupError, match="no profile given"):
        load_profile()
    with pytest.raises(SystemExit) as stopped:
        profiles.require_profile()
    assert "default" in str(stopped.value)      # and it is on the list


# -- what a profile gets from the one it extends ------------------------------

def test_an_attribute_comes_from_the_nearest_profile_that_has_it(tmp_path,
                                                                 clean):
    _child(tmp_path, "mine",
           **{"preprocessing.py": "CAPTION_MAX_WORDS = 7\n"})
    _child(tmp_path, "theirs")
    _bound(clean, tmp_path)
    mine, theirs = load_profile("mine"), load_profile("theirs")
    default = load_profile("default")
    assert mine.component("preprocessing", "CAPTION_MAX_WORDS") == 7
    # the module is there and lacks the name: that one is the default's
    assert mine.component("preprocessing", "HYPHEN_EXCEPTIONS") == \
        default.component("preprocessing", "HYPHEN_EXCEPTIONS")
    # no module at all
    assert theirs.component("preprocessing", "CAPTION_MAX_WORDS") == \
        default.component("preprocessing", "CAPTION_MAX_WORDS")
    assert theirs.component("preprocessing", "NOBODY_HAS_THIS") is None
    assert [p.name for p in mine.lineage()] == ["mine", "default"]


def test_a_profile_that_extends_nothing_gets_nothing(tmp_path, clean):
    _child(tmp_path, "alone", extends=None)
    _bound(clean, tmp_path)
    alone = load_profile("alone")
    assert [p.name for p in alone.lineage()] == ["alone"]
    assert alone.component("preprocessing", "CAPTION_MAX_WORDS") is None
    assert alone.component("source", "SOURCE") is None
    assert alone.schema_sql is None and not alone.has_prompts()
    with pytest.raises(FileNotFoundError, match="provides no prompt"):
        prompts.load("refinement/refine", alone)
    with pytest.raises(LookupError, match="inference.PHRASES"):
        wording.phrases(alone)


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_profiles_of_this_repository_take_nothing_from_the_default(name):
    """They extend it and write every part of it themselves: each prompt,
    each name of each module, the schema, every phrase. So extending changed
    nothing for them, and a prompt one of them loses is seen here instead of
    being answered for, silently, by the English one."""
    profile = load_profile(name)
    assert [p.name for p in profile.lineage()] == [name, "default"]
    theirs = profile.package_dir
    missing = [path.relative_to(DEFAULT).as_posix()
               for path in sorted((DEFAULT / "prompts").rglob("*.md"))
               if not (theirs / path.relative_to(DEFAULT)).is_file()]
    assert not missing, missing
    assert (theirs / "schema.sql").is_file()
    default = load_profile("default")
    for module in sorted(DEFAULT.glob("*.py")):
        if module.stem in ("__init__", "profile"):
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = [target.id for node in tree.body
                 if isinstance(node, ast.Assign) for target in node.targets
                 if isinstance(target, ast.Name) and target.id.isupper()]
        assert names, module.name
        for attr in names:
            assert default._own(module.stem, attr) is not None
            assert profile._own(module.stem, attr) is not None, (
                f"{name} takes {module.stem}.{attr} from the default")
    own_phrases = profile._own("inference", "PHRASES")
    assert set(default._own("inference", "PHRASES")) <= set(own_phrases)
    assert wording.phrases(profile) == own_phrases


def test_a_prompt_is_the_nearest_one(tmp_path, clean):
    _child(tmp_path, "mine", **{"prompts/refinement/refine.md": "my own"})
    _bound(clean, tmp_path)
    mine = load_profile("mine")
    assert prompts.load("refinement/refine", mine).text == "my own"
    inherited = prompts.load("refinement/split", mine)
    assert inherited.path == DEFAULT / "prompts" / "refinement" / "split.md"
    assert inherited.sha256 == prompts.load(
        "refinement/split", load_profile("default")).sha256
    assert mine.has_prompts()
    with pytest.raises(FileNotFoundError, match="nor does default"):
        prompts.load("refinement/nobody_wrote_this", mine)


def test_one_phrase_is_laid_over_the_extended_profile_s(tmp_path, clean):
    _child(tmp_path, "mine", **{
        "inference.py": 'PHRASES = {"task_heading": "Aufgabe"}\n'})
    _bound(clean, tmp_path)
    got = wording.phrases(load_profile("mine"))
    base = wording.phrases(load_profile("default"))
    assert got["task_heading"] == "Aufgabe"
    assert base["task_heading"] != "Aufgabe"
    assert {k: v for k, v in got.items() if k != "task_heading"} == \
        {k: v for k, v in base.items() if k != "task_heading"}
    # and what it does not word at all is the extended profile's
    assert wording.readoff(load_profile("mine")) == wording.readoff(
        load_profile("default"))


def test_the_schema_is_the_nearest_file(tmp_path, clean):
    own = 'CREATE TABLE IF NOT EXISTS "DocumentMeta" ("document" INTEGER ' \
          'PRIMARY KEY, "title" TEXT, "folder" TEXT, "region" TEXT);\n'
    _child(tmp_path, "mine", **{"schema.sql": own})
    _child(tmp_path, "theirs")
    _bound(clean, tmp_path)
    assert load_profile("mine").schema_sql == (
        tmp_path / "mine" / "schema.sql").resolve()
    assert load_profile("theirs").schema_sql == DEFAULT / "schema.sql"


def test_a_circle_and_a_missing_parent_are_named(tmp_path, clean):
    _child(tmp_path, "one", extends="two")
    _child(tmp_path, "two", extends="one")
    _child(tmp_path, "orphan", extends="nobody")
    _bound(clean, tmp_path)
    with pytest.raises(ValueError, match="one -> two -> one"):
        load_profile("one").lineage()
    with pytest.raises(LookupError, match="'orphan' extends 'nobody'"):
        load_profile("orphan").component("source", "SOURCE")
    with pytest.raises(ValueError, match="extends itself"):
        Profile(name="x", extends="x")


# -- the built-in profile is complete -----------------------------------------

def test_the_built_in_profile_names_no_subject():
    """It is for any documents: no word of the two corpora this repository
    was written for may be in what it tells a model."""
    words = ("AR6", "IPCC", "IAM", "scenario database", "heat plan",
             "Wärme", "Kommun", "municipal", "Szenario", "KWP", "OEKG")
    hits = []
    for path in sorted(DEFAULT.rglob("*")):
        if path.suffix not in (".md", ".py", ".sql"):
            continue
        text = path.read_text(encoding="utf-8")
        hits += [(path.relative_to(DEFAULT).as_posix(), word)
                 for word in words if word in text]
    assert not hits, hits


def _prompt_shape(path):
    """(front matter keys, {{placeholders}}) of one prompt file."""
    import re
    text = path.read_text(encoding="utf-8")
    head = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    keys = sorted(line.split(":")[0].strip()
                  for line in (head.group(1) if head else "").splitlines()
                  if ":" in line and not line.startswith(" "))
    body = text[head.end():] if head else text
    return keys, sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", body)))


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_built_in_prompt_is_filled_and_set_like_the_profiles_own(name):
    """The code fills a prompt's placeholders and reads its settings by
    name, whichever profile's file it got. A built-in prompt with another
    placeholder or another setting would fail, or be asked differently,
    only for a project that has no prompt of its own there."""
    own = ROOT / "profiles" / name / "prompts"
    built_in = DEFAULT / "prompts"
    compared = 0
    for path in sorted(built_in.rglob("*.md")):
        other = own / path.relative_to(built_in)
        if not other.is_file():
            continue
        compared += 1
        assert _prompt_shape(path) == _prompt_shape(other), \
            path.relative_to(built_in).as_posix()
    assert compared >= 30


def test_the_built_in_profile_has_every_prompt_a_stage_asks_for():
    """Every prompt id the core names is a file of the built-in profile."""
    import re
    folders = sorted(path.name for path in (DEFAULT / "prompts").iterdir()
                     if path.is_dir()) + ["kg"]
    prompt_id = re.compile(r'"((?:%s)/[a-z_0-9]+)"' % "|".join(folders))
    named = set()
    for path in sorted((ROOT / "docpipe").rglob("*.py")):
        if "builtin" in path.parts:
            continue
        named |= set(prompt_id.findall(path.read_text(encoding="utf-8")))
    assert len(named) >= 30
    lacking = sorted(prompt for prompt in named
                     if not (DEFAULT / "prompts" / f"{prompt}.md").is_file())
    assert lacking == []


# -- a folder as the source ---------------------------------------------------

def _pdf(path, text=b"%PDF-1.4 stand-in\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text)
    return path


def test_a_folder_is_read_with_its_subfolders_and_copied_once(tmp_path):
    folder, data = tmp_path / "in", tmp_path / "data"
    _pdf(folder / "a.pdf")
    _pdf(folder / "2023" / "b.PDF")
    (folder / "notes.txt").write_text("not a document", encoding="utf-8")
    data.mkdir()
    source = FolderSource(folder)
    source.prepare(data)
    assert sorted(p.name for p in data.iterdir()) == ["a.pdf", "b.PDF"]
    docs = list(source.documents(None))
    assert [(d.filename, d.external_id, d.url) for d in docs] == [
        ("b.PDF", "b.PDF", None), ("a.pdf", "a.pdf", None)]
    assert {d.filename: d.meta for d in docs} == {
        "a.pdf": {"title": "a", "folder": None},
        "b.PDF": {"title": "b", "folder": "2023"}}
    assert len(source) == 2
    # a second run copies nothing over what lies there
    (data / "a.pdf").write_bytes(b"edited in place")
    FolderSource(folder).prepare(data)
    assert (data / "a.pdf").read_bytes() == b"edited in place"


def test_the_data_directory_itself_is_read_without_what_lies_below(tmp_path):
    data = tmp_path / "pdf"
    _pdf(data / "a.pdf")
    _pdf(data / "processed" / "a" / "page.pdf")     # a stage's own output
    source = FolderSource(FolderSource.default_location(data))
    source.prepare(data)
    assert [d.filename for d in source.documents(None)] == ["a.pdf"]
    assert sorted(p.name for p in data.iterdir()) == ["a.pdf", "processed"]


def test_one_name_twice_is_refused_and_both_places_are_named(tmp_path):
    folder = tmp_path / "in"
    _pdf(folder / "x" / "report.pdf")
    _pdf(folder / "y" / "report.pdf")
    with pytest.raises(SystemExit) as stopped:
        FolderSource(folder).prepare(tmp_path / "data")
    assert "report.pdf" in str(stopped.value)
    assert "x" in str(stopped.value) and "y" in str(stopped.value)
    with pytest.raises(SystemExit, match="is not a folder"):
        len(FolderSource(tmp_path / "nowhere"))


def test_a_source_with_a_list_still_has_to_be_given_it():
    assert Source.default_location(Path("anywhere")) is None
    from docpipe.ingest import cli
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--profile", "kwp"])
    assert "needs --source" in str(stopped.value)


def test_the_picker_filters_by_what_the_source_wrote(tmp_path):
    default = load_profile("default")
    with sqlite3.connect(tmp_path / "db") as connection:
        connection.row_factory = sqlite3.Row
        schema.apply(connection, default)
        from docpipe.store import documents
        documents.add_document("a.pdf", "a.pdf", None, None, 3, "20260101",
                               {"title": "a", "folder": "2023"}, connection)
        documents.add_document("b.pdf", "b.pdf", None, None, 3, "20260101",
                               {"title": "Better title", "folder": None},
                               connection)
        catalog = load_catalog(default)
        entries = {entry.label: entry for entry in catalog.entries(connection)}
    assert set(entries) == {"a", "Better title"}
    assert entries["a"].facets == {"folder": ["2023"]}
    assert entries["Better title"].facets == {}
    assert [facet.field for facet in catalog.facets] == ["folder"]


# -- the first steps of somebody who has only installed the package -----------

def _docpipe(*args, cwd):
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "docpipe", *args],
                          cwd=str(cwd), env=child, capture_output=True,
                          text=True)


def test_init_leaves_a_project_the_next_command_runs_in(tmp_path):
    home = tmp_path / "My Reports 2024"
    home.mkdir()
    run = _docpipe("init", cwd=home)
    assert run.returncode == 0, run.stderr
    name = "my_reports_2024"
    assert (home / "profiles" / name / "profile.py").is_file()
    assert (home / "data" / name / "pdf").is_dir()
    assert f'profile = "{name}"' in (home / "docpipe.toml").read_text(
        encoding="utf-8")
    # no key is set by copying the example as it is
    example = (home / ".env.example").read_text(encoding="utf-8")
    assert "LLM_API_KEY" in example
    assert all(line.startswith("#") for line in example.splitlines())
    assert ".env" in (home / ".gitignore").read_text(encoding="utf-8")

    listed = _docpipe("profiles", cwd=home)
    assert f"* {name}" in listed.stdout and "default" in listed.stdout
    doctor = _docpipe("doctor", "--offline", cwd=home)
    assert f"{name}:" in doctor.stdout and "(extends default)" in doctor.stdout
    assert "0 of its own" in doctor.stdout
    assert "0 prompt file(s)" not in doctor.stdout
    assert "Traceback" not in doctor.stderr

    again = _docpipe("init", cwd=home)
    assert again.returncode != 0 and "exists already" in again.stderr

    # The project's own extraction module is there, with no spec yet; and
    # the spec, once written beside it, is found where the project is and
    # not in the checkout this test runs from.
    assert (home / "profiles" / name / "extraction.py").is_file()
    code = ("from docpipe.extraction.schema import schema_path; "
            f"print(schema_path({name!r}))")
    env = {k: v for k, v in os.environ.items() if k not in STRIP}
    env["PYTHONPATH"] = str(ROOT)
    found = subprocess.run([sys.executable, "-c", code], cwd=str(home),
                           env=env, capture_output=True, text=True)
    assert found.returncode == 0, found.stderr
    assert Path(found.stdout.strip()).parent == home / "profiles" / name


def test_init_refuses_a_name_that_cannot_be_a_profile(tmp_path):
    for bad in ("9lives", "has-dash", "kwp", "default"):
        run = _docpipe("init", bad, cwd=tmp_path)
        assert run.returncode != 0, bad
    assert not (tmp_path / "docpipe.toml").exists()
    assert not (tmp_path / "profiles").exists()
