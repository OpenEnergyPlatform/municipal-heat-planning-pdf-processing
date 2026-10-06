"""The profile the package brings itself, and a profile that extends another.

Promised: a profile that names another one in `extends` gets that profile's
part wherever it has none of its own (a module's attribute, a prompt, the
schema, one phrase) AND a profile that names none gets nothing from anybody;
the built-in profile is found last, so a project's own of the same name
wins; the two profiles of this repository take from it only the prompts
listed in INHERITED, each of them what the copy it replaced was; a folder of
PDFs is a document source; and `docpipe init` leaves a project that the next
command runs in.
"""
import ast
import hashlib
import json
import os
import re
import shutil
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


# The prompts each of the two profiles does not copy: the built-in one is its
# prompt, byte for byte, and was before the copy was taken out. A prompt of
# the built-in profile that is neither on a profile's list nor a file of it
# fails below, so none is answered for, silently, by the English one.
INHERITED = {
    "scenarios": ("inference/json_format", "visuals/caption_keep"),
    "kwp": ("visuals/caption_keep",),
}


def _prompt_faults(home, inherited):
    """What is wrong with the prompts under *home*, set against the
    built-in ones: a prompt of the built-in profile that is neither on the
    list nor a file of the profile, a listed one the profile has a file for
    (then it is not inherited, whatever its bytes), and a listed name that
    is no built-in prompt."""
    built_in = DEFAULT / "prompts"
    faults = []
    for path in sorted(built_in.rglob("*.md")):
        relative = path.relative_to(built_in)
        prompt_id = f"{relative.parent.as_posix()}/{relative.stem}"
        own = home / "prompts" / relative
        if prompt_id in inherited:
            if own.is_file():
                faults.append(
                    f"{prompt_id}: on the inherited list, and a file of the "
                    "profile with "
                    + ("other bytes" if own.read_bytes() != path.read_bytes()
                       else "the built-in bytes"))
        elif not own.is_file():
            faults.append(f"{prompt_id}: not on the inherited list and "
                          "not a file of the profile")
    faults += [f"{prompt_id}: on the inherited list and no built-in prompt"
               for prompt_id in inherited
               if not (built_in / f"{prompt_id}.md").is_file()]
    return faults


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_profiles_of_this_repository_take_only_the_listed_prompts(name):
    """They extend it and write every part of it themselves: each prompt but
    the ones listed in INHERITED, each name of each module, the schema, every
    phrase. So a prompt one of them loses is seen here instead of being
    answered for, silently, by the English one, and a listed one is the
    built-in file itself."""
    profile = load_profile(name)
    assert [p.name for p in profile.lineage()] == [name, "default"]
    theirs = profile.package_dir
    assert _prompt_faults(theirs, INHERITED[name]) == []
    for prompt_id in INHERITED[name]:
        assert prompts.path_for(prompt_id, profile) == \
            DEFAULT / "prompts" / f"{prompt_id}.md"
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


def _folder_of_copies(tmp_path):
    """A profile folder that holds a copy of every built-in prompt."""
    home = tmp_path / "copies"
    shutil.copytree(DEFAULT / "prompts", home / "prompts")
    return home


def test_the_guard_of_the_prompts_fails_where_the_promise_is_broken(tmp_path):
    inherited = ("inference/json_format", "visuals/caption_keep")
    home = _folder_of_copies(tmp_path)
    # a profile that holds every prompt and lists none passes: it can pass
    assert _prompt_faults(home, ()) == []
    # a prompt that is missing and not on the list is named
    (home / "prompts" / "refinement" / "split.md").unlink()
    faults = _prompt_faults(home, ())
    assert len(faults) == 1 and faults[0].startswith("refinement/split:")
    assert "not on the inherited list" in faults[0]
    # one that is listed and has no file is what the list promises
    for prompt_id in inherited:
        (home / "prompts" / f"{prompt_id}.md").unlink()
    assert _prompt_faults(home, inherited) == faults
    # a listed one that reappears with other bytes is named, and so is one
    # that reappears as it was: then it is not inherited any more
    changed = home / "prompts" / "inference" / "json_format.md"
    changed.write_bytes((DEFAULT / "prompts" / "inference"
                         / "json_format.md").read_bytes() + b"\nand more")
    again = home / "prompts" / "visuals" / "caption_keep.md"
    shutil.copyfile(DEFAULT / "prompts" / "visuals" / "caption_keep.md", again)
    got = _prompt_faults(home, inherited)
    assert [fault.split(":")[0] for fault in got] == [
        "inference/json_format", "refinement/split", "visuals/caption_keep"]
    assert "other bytes" in got[0] and "the built-in bytes" in got[2]
    # a name on the list that no built-in prompt has is a misspelling
    assert _prompt_faults(home, inherited + ("visuals/caption_kept",))[-1] \
        .startswith("visuals/caption_kept:")


# The prompts the copies were taken out for, as the file the copy was:
# its sha256 is what a stage records, and no front matter lies before the
# text, so it is also the text a model reads. Taken from the files before
# they were deleted, and equal to the built-in ones then too. A built-in
# prompt that is changed on purpose changes what these profiles ask, and
# that is where a change of it has to be entered.
BEFORE = {
    ("scenarios", "inference/json_format"):
        "b65239b69d87e432452c88d8c339fad4ea359d19974274d2d571ed139ec5e139",
    ("scenarios", "visuals/caption_keep"):
        "78b24d39d4af63c1f2acde81cdc7e4d411f85a8ab0fe6005e19f442ad540811f",
    ("kwp", "visuals/caption_keep"):
        "78b24d39d4af63c1f2acde81cdc7e4d411f85a8ab0fe6005e19f442ad540811f",
}


def test_every_copy_that_was_taken_out_was_on_the_list():
    assert {(name, prompt_id) for name, ids in INHERITED.items()
            for prompt_id in ids} == set(BEFORE)


@pytest.mark.parametrize("name, prompt_id", sorted(BEFORE))
def test_an_inherited_prompt_reads_and_records_as_its_copy_did(name, prompt_id):
    """The model reads the text the copy had AND the hash a stage records for
    it is the one the copy had, so no request, no fingerprint and no stamp
    moved with the copies."""
    profile = load_profile(name)
    prompt = prompts.load(prompt_id, profile)
    assert prompt.path == DEFAULT / "prompts" / f"{prompt_id}.md"
    assert prompt.meta == {}
    assert hashlib.sha256(prompt.text.encode("utf-8")).hexdigest() == \
        BEFORE[name, prompt_id]
    assert prompt.sha256 == BEFORE[name, prompt_id]
    assert prompts.versions([prompt_id], profile) == {
        prompt_id: BEFORE[name, prompt_id]}


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_visuals_record_made_with_the_copy_still_holds(name, tmp_path):
    """Stage 3 compares the hashes it recorded with the ones of today, and
    a prompt that differs makes it say 'described with older prompts'. A
    record that holds the hash the copy had is current for that prompt,
    and a record that holds another one is stale for that prompt only."""
    from docpipe.visuals import config
    profile = load_profile(name)
    stored = prompts.versions(config.PROMPT_IDS, profile)
    stored["visuals/caption_keep"] = BEFORE[name, "visuals/caption_keep"]
    folder = tmp_path / "visuals"
    folder.mkdir()
    (folder / prompts.VERSION_FILE).write_text(json.dumps(stored),
                                               encoding="utf-8")
    assert prompts.check(folder, config.PROMPT_IDS, profile) == []
    # what a stage writes today is that record
    prompts.record(tmp_path / "again", config.PROMPT_IDS, profile)
    assert json.loads((tmp_path / "again" / prompts.VERSION_FILE).read_text(
        encoding="utf-8")) == stored
    # a record that holds another hash for it is stale for that prompt only
    stored["visuals/caption_keep"] = "0" * 64
    (folder / prompts.VERSION_FILE).write_text(json.dumps(stored),
                                               encoding="utf-8")
    assert prompts.check(folder, config.PROMPT_IDS, profile) == [
        "visuals/caption_keep"]


def test_a_copy_with_other_words_is_not_what_the_record_holds(tmp_path, clean):
    """The case the two tests above are built against: a profile that does
    write its own caption instruction reads another text and records
    another hash, which is what 'inherited' keeps from happening."""
    from docpipe.visuals import config
    _child(tmp_path, "mine", **{
        "prompts/visuals/caption_keep.md": "Keep the caption as it is."})
    _bound(clean, tmp_path)
    mine = load_profile("mine")
    prompt = prompts.load("visuals/caption_keep", mine)
    assert prompt.text == "Keep the caption as it is."
    assert prompt.sha256 != BEFORE["kwp", "visuals/caption_keep"]
    folder = tmp_path / "visuals"
    folder.mkdir()
    (folder / prompts.VERSION_FILE).write_text(json.dumps(
        {"visuals/caption_keep": BEFORE["kwp", "visuals/caption_keep"]}),
        encoding="utf-8")
    assert "visuals/caption_keep" in prompts.check(
        folder, config.PROMPT_IDS, mine)


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
    files = sorted(built_in.rglob("*.md"))
    for path in files:
        other = own / path.relative_to(built_in)
        if not other.is_file():
            continue
        compared += 1
        assert _prompt_shape(path) == _prompt_shape(other), \
            path.relative_to(built_in).as_posix()
    # an inherited prompt is the built-in file itself: nothing to compare
    assert len(files) >= 30
    assert compared == len(files) - len(INHERITED[name])


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
    # None, and not a count that ends in a zero, as thirty does.
    assert not re.search(r"(?<!\d)0 prompt file\(s\)", doctor.stdout)
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
