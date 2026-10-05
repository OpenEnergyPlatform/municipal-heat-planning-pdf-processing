"""The project file and the one list of settings.

Two things are held here. The list against the code: every environment name
a stage reads is declared, and nothing is declared that no stage reads. And
the file against the environment: what it fills in, what it leaves alone,
and what it refuses.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe import settings

ROOT = Path(__file__).resolve().parent.parent
AREAS = ("docpipe", "profiles", "scripts", "utils")
# Facts of the machine a run finds itself on, not settings of this tool.
AMBIENT_SUFFIXES = ("_JOB_ID",)
READERS = ("os.environ.get", "os.getenv", "environ.get", "getenv")


def _trees() -> list:
    return [(path, ast.parse(path.read_text(encoding="utf-8")))
            for area in AREAS
            for path in sorted((ROOT / area).rglob("*.py"))]


def _constants(trees) -> dict:
    """{NAME: {its texts}} of every module-level `NAME = "text"`: what a
    read through a constant (`os.environ.get(TOKEN_ENV)`) names."""
    found: dict = {}
    for _path, tree in trees:
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id.isupper() \
                    and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                found.setdefault(node.targets[0].id, set()).add(
                    node.value.value)
    return found


def _named(argument, constants: dict) -> list:
    """The environment names an argument of a read can stand for."""
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return [argument.value]
    if isinstance(argument, ast.Name):
        return sorted(constants.get(argument.id, ()))
    if isinstance(argument, ast.Attribute):         # module.CONSTANT
        return sorted(constants.get(argument.attr, ()))
    return []


def _read_of(node, constants: dict) -> list:
    """The names one node reads from the environment, or []."""
    if isinstance(node, ast.Call) and node.args \
            and ast.unparse(node.func) in READERS:
        return _named(node.args[0], constants)
    if isinstance(node, ast.Subscript) \
            and ast.unparse(node.value) in ("os.environ", "environ") \
            and isinstance(node.ctx, ast.Load):
        return _named(node.slice, constants)
    return []


def _names_read() -> dict:
    """{environment name: [file:line]} over the code, by its syntax tree.
    A name read through a module-level constant counts as read."""
    trees = _trees()
    constants = _constants(trees)
    found: dict = {}
    for path, tree in trees:
        for node in ast.walk(tree):
            for name in _read_of(node, constants):
                if not name.endswith(AMBIENT_SUFFIXES):
                    found.setdefault(name, []).append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return found


@pytest.fixture
def clean(monkeypatch):
    """A test that applies a file leaves neither the environment nor the
    module's record of the last file behind."""
    before = dict(os.environ)
    state = (settings._file, dict(settings._said), set(settings._set),
             settings._env_file)
    yield monkeypatch
    for name in set(os.environ) - set(before):
        del os.environ[name]
    os.environ.update(before)
    (settings._file, settings._said, settings._set,
     settings._env_file) = state


def _file(tmp_path, text, name=settings.PROJECT_FILE):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The list against the code
# ---------------------------------------------------------------------------

def test_every_name_the_code_reads_is_a_declared_setting():
    missing = {name: sites for name, sites in _names_read().items()
               if name not in settings.BY_ENV}
    assert not missing, missing


def test_a_name_read_through_a_constant_is_seen_as_read():
    """Or a setting read as `os.environ.get(TOKEN_ENV)` would never be
    held against the list."""
    tree = ast.parse('SOME_ENV = "BRAND_NEW_UNDECLARED"\n'
                     'import os\n'
                     'a = os.environ.get(SOME_ENV)\n'
                     'b = os.environ.get("LITERAL_UNDECLARED", "1")\n'
                     'c = os.environ[SOME_ENV]\n'
                     'd = os.environ.get(other.SOME_ENV)\n'
                     'e = os.environ.get(a_variable)\n')
    constants = _constants([(None, tree)])
    read = [name for node in ast.walk(tree)
            for name in _read_of(node, constants)]
    assert sorted(read) == ["BRAND_NEW_UNDECLARED"] * 3 + [
        "LITERAL_UNDECLARED"]
    found = _names_read()
    for through_a_constant in ("DOCPIPE_API_TOKEN", "DOCPIPE_CASSETTE_REPLAY",
                               "EXTRACT_PROVENANCE", "DOCPIPE_PROFILE"):
        assert through_a_constant in found, through_a_constant


def test_every_declared_setting_is_named_by_the_code():
    """Some names are read through a constant or a helper, which the scan
    above cannot follow. Every one is at least written out somewhere."""
    literals = set()
    for area in AREAS:
        for path in sorted((ROOT / area).rglob("*.py")):
            if path.name == "settings.py" and path.parent.name == "docpipe":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literals.add(node.value)
    own = {settings.CONFIG_ENV}        # named in settings.py itself
    dead = [s.env for s in settings.SETTINGS
            if s.env not in literals and s.env not in own]
    assert not dead, dead


def test_the_list_is_well_formed():
    envs = [s.env for s in settings.SETTINGS]
    keys = [s.key for s in settings.SETTINGS]
    assert len(set(envs)) == len(envs)
    assert len(set(keys)) == len(keys)
    for s in settings.SETTINGS:
        assert s.kind in settings.KINDS, s
        assert s.help and s.help == s.help.strip() and len(s.help) <= 110, s
        assert s.key == s.key.lower() and s.key.count(".") <= 1, s
        assert not s.key.startswith(settings.FREE_TABLE + "."), s
        assert s.stages, s
        if s.kind == "flag":
            assert s.on != s.off, s


def test_a_declared_default_is_the_one_the_code_uses():
    """Where every read of a name gives the same literal default. A default
    the code computes, or one that differs between two readers, is declared
    as None and explained in the help."""
    literal: dict = {}
    for area in AREAS:
        for path in sorted((ROOT / area).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and node.args \
                        and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str) \
                        and ast.unparse(node.func) in READERS:
                    given = node.args[1] if len(node.args) > 1 else None
                    literal.setdefault(node.args[0].value, set()).add(
                        given.value if isinstance(given, ast.Constant)
                        else ast.unparse(given) if given is not None else None)
    wrong = {}
    for name, defaults in literal.items():
        setting = settings.BY_ENV.get(name)
        if setting is None or len(defaults) != 1:
            continue
        (default,) = defaults
        if setting.default is None:
            continue                    # computed, or explained in the help
        code = None if default in (None, "") else str(default)
        if (setting.default or None) != code:
            wrong[name] = (setting.default, default)
    assert not wrong, wrong


# ---------------------------------------------------------------------------
# The file against the environment
# ---------------------------------------------------------------------------

def test_the_file_fills_what_the_environment_leaves_open(tmp_path, clean):
    clean.delenv("LLM_MODEL", raising=False)
    clean.setenv("LLM_BASE_URL", "http://from-the-environment/v1")
    path = _file(tmp_path, '[llm]\nmodel = "m"\n'
                           'base_url = "http://from-the-file/v1"\n')
    assert settings.apply(path) == path.resolve()
    assert os.environ["LLM_MODEL"] == "m"
    assert settings.origin("LLM_MODEL") == settings.PROJECT_FILE
    # A variable that is set wins, and the listing says what the file holds.
    assert os.environ["LLM_BASE_URL"] == "http://from-the-environment/v1"
    assert settings.origin("LLM_BASE_URL") == "environment"
    row = {s.env: (value, origin, shadowed)
           for s, value, origin, shadowed in settings.rows()}
    assert row["LLM_BASE_URL"] == ("http://from-the-environment/v1",
                                   "environment", "http://from-the-file/v1")
    assert row["LLM_MODEL"] == ("m", settings.PROJECT_FILE, None)


def test_the_top_level_names_the_profile(tmp_path, clean):
    clean.delenv("DOCPIPE_PROFILE", raising=False)
    settings.apply(_file(tmp_path, 'profile = "scenarios"\n'))
    assert os.environ["DOCPIPE_PROFILE"] == "scenarios"


def test_a_second_file_takes_back_what_the_first_put_in(tmp_path, clean):
    clean.delenv("LLM_MODEL", raising=False)
    clean.delenv("LLM_TIMEOUT", raising=False)
    settings.apply(_file(tmp_path, '[llm]\nmodel = "first"\ntimeout = 5\n'))
    assert os.environ["LLM_TIMEOUT"] == "5"
    settings.apply(_file(tmp_path, '[llm]\nmodel = "second"\n', "other.toml"))
    assert os.environ["LLM_MODEL"] == "second"
    assert "LLM_TIMEOUT" not in os.environ


GONE = {"EXTRACT_POOL_TOP": "extract.pool_top",
        "EXTRACT_TOP_K": "extract.top_k",
        "EXTRACT_MAX_ROUNDS": "extract.max_rounds",
        "EXTRACT_EDGE_SECTIONS": "extract.edge_sections"}


def test_a_setting_that_decided_nothing_is_not_listed():
    """Four names were listed and decided nothing: one was read and never
    used, two were only printed, one was read by a function nobody called.
    A list that shows them offers a knob that turns nothing."""
    for name, key in GONE.items():
        assert name not in settings.BY_ENV, name
        assert key not in settings.BY_KEY, key


def test_no_setting_says_of_itself_that_it_does_nothing():
    said = [s.env for s in settings.SETTINGS
            if "no effect" in s.help.lower()]
    assert not said, said


def test_a_setting_that_decided_nothing_is_not_read():
    read = _names_read()
    for name in GONE:
        assert name not in read, (name, read.get(name))
    # and the scan would have seen one: a name that is read is in it
    assert "EXTRACT_PROSE_TOP" in read


@pytest.mark.parametrize("key", sorted(GONE.values()))
def test_a_setting_that_is_gone_is_an_unknown_key_in_the_file(
        tmp_path, clean, key):
    section, name = key.split(".")
    with pytest.raises(settings.ConfigError) as exc:
        settings.read(_file(tmp_path, f"[{section}]\n{name} = 5\n"))
    assert f"{key} is no setting" in str(exc.value)


def test_an_unknown_key_is_refused_with_the_nearest_ones(tmp_path, clean):
    with pytest.raises(settings.ConfigError) as exc:
        settings.read(_file(tmp_path, '[llm]\nbase_ulr = "x"\n'))
    assert "llm.base_ulr is no setting" in str(exc.value)
    assert "llm.base_url" in str(exc.value)


def test_a_secret_is_not_read_from_the_file(tmp_path, clean):
    with pytest.raises(settings.ConfigError, match="LLM_API_KEY"):
        settings.read(_file(tmp_path, '[llm]\napi_key = "sk-123"\n'))


def test_what_decides_which_file_is_read_cannot_be_in_it(tmp_path, clean):
    boot = [s for s in settings.SETTINGS if s.bootstrap]
    assert boot
    for s in boot:
        table, _, key = s.key.rpartition(".")
        text = f'[{table}]\n{key} = "x"\n' if table else f'{key} = "x"\n'
        with pytest.raises(settings.ConfigError, match=s.env):
            settings.read(_file(tmp_path, text))


def test_a_value_of_the_wrong_type_is_refused(tmp_path, clean):
    kinds = {s.kind: s for s in settings.SETTINGS
             if not (s.secret or s.bootstrap) and "." in s.key}
    for kind, wrong in (("int", '"three"'), ("int", "true"), ("float", '"x"'),
                        ("flag", '"yes"'), ("flag", "1"), ("str", "3"),
                        ("path", "3"), ("list", "3")):
        if kind not in kinds:
            continue
        table, _, key = kinds[kind].key.rpartition(".")
        with pytest.raises(settings.ConfigError, match=kinds[kind].key):
            settings.read(_file(tmp_path, f"[{table}]\n{key} = {wrong}\n"))


def _flag_readers() -> dict:
    """{flag: [(place, comparison, the read inside it)]}: every comparison
    in the code that decides something from one flag's text."""
    flags = {s.env for s in settings.SETTINGS if s.kind == "flag"}
    trees = _trees()
    constants = _constants(trees)
    found: dict = {}
    for path, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            reads = [(inner, name) for inner in ast.walk(node)
                     for name in _read_of(inner, constants)]
            if len(reads) == 1 and reads[0][1] in flags:
                found.setdefault(reads[0][1], []).append((
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno}",
                    node, reads[0][0]))
    return found


def _decides(comparison, read, text: str) -> bool:
    """What a reader's comparison gives for one spelling of its flag."""
    def place(node):
        # with its end: a read and the `.strip()` around it begin together
        return tuple(getattr(node, name, None) for name in (
            "lineno", "col_offset", "end_lineno", "end_col_offset"))

    class Put(ast.NodeTransformer):
        def visit(self, node):
            if type(node) is type(read) and place(node) == place(read):
                return ast.copy_location(ast.Constant(text), node)
            return self.generic_visit(node)

    import copy
    made = ast.fix_missing_locations(ast.Expression(
        Put().visit(copy.deepcopy(comparison))))
    return bool(eval(compile(made, "<flag reader>", "eval"), {}))


def test_a_flag_is_spelled_as_its_reader_parses_it(tmp_path, clean):
    """What the project file writes for `true` and for `false` is told
    apart by every reader of the flag in the code. A flag spelled
    "true"/"false" for a reader that asks `!= "0"` would be on either way."""
    flags = [s for s in settings.SETTINGS if s.kind == "flag" and "." in s.key]
    assert flags
    readers = _flag_readers()
    assert not [s.env for s in flags if s.env not in readers], \
        "a flag no comparison in the code reads"
    for s in flags:
        table, _, key = s.key.rpartition(".")
        on = settings.read(_file(tmp_path, f"[{table}]\n{key} = true\n"))
        off = settings.read(_file(tmp_path, f"[{table}]\n{key} = false\n"))
        for place, comparison, read in readers[s.env]:
            assert _decides(comparison, read, on[s.env]) != _decides(
                comparison, read, off[s.env]), (s.env, place)


def test_a_reader_that_cannot_tell_a_flags_spellings_apart_is_seen():
    """The check above, on a reader that takes both spellings for on."""
    tree = ast.parse('import os\n'
                     'A = os.environ.get("X", "1") != "0"\n'
                     'B = os.environ.get("X", "").strip().lower() in '
                     '("1", "true")\n')
    first, second = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Compare)]
    read = lambda node: next(inner for inner in ast.walk(node)  # noqa: E731
                             if isinstance(inner, ast.Call)
                             and ast.unparse(inner.func) == "os.environ.get")
    assert _decides(first, read(first), "1") != _decides(
        first, read(first), "0")
    assert _decides(first, read(first), "true") == _decides(
        first, read(first), "false")            # both on: not told apart
    assert _decides(second, read(second), " TRUE ") != _decides(
        second, read(second), "false")


def test_a_relative_path_is_relative_to_the_file(tmp_path, clean):
    said = settings.read(_file(tmp_path, 'data_root = "corpus"\n'))
    assert Path(said["DOCPIPE_DATA_ROOT"]) == tmp_path / "corpus"
    absolute = (tmp_path / "elsewhere").as_posix()
    said = settings.read(_file(tmp_path, f'data_root = "{absolute}"\n'))
    assert Path(said["DOCPIPE_DATA_ROOT"]) == tmp_path / "elsewhere"


def test_a_list_is_joined_the_way_its_reader_splits_it(tmp_path, clean):
    lists = [s for s in settings.SETTINGS if s.kind == "list" and "." in s.key]
    for s in lists:
        table, _, key = s.key.rpartition(".")
        said = settings.read(_file(
            tmp_path, f'[{table}]\n{key} = ["a", "b"]\n'))
        assert said[s.env] == f"a{s.sep}b"


def test_a_profile_s_own_names_go_through_the_free_table(tmp_path, clean):
    said = settings.read(_file(tmp_path, '[env]\nMY_PROFILE_KNOB = 3\n'))
    assert said == {"MY_PROFILE_KNOB": "3"}
    with pytest.raises(settings.ConfigError, match="llm.model"):
        settings.read(_file(tmp_path, '[env]\nLLM_MODEL = "m"\n'))
    with pytest.raises(settings.ConfigError, match="not an environment name"):
        settings.read(_file(tmp_path, '[env]\nlower = "m"\n'))


def test_a_file_that_is_not_toml_says_where(tmp_path, clean):
    with pytest.raises(settings.ConfigError, match="docpipe.toml"):
        settings.read(_file(tmp_path, "profile = \n"))


# ---------------------------------------------------------------------------
# Which file
# ---------------------------------------------------------------------------

def test_the_nearest_file_upwards_is_the_project(tmp_path, clean):
    clean.delenv(settings.CONFIG_ENV, raising=False)
    outer = _file(tmp_path, 'profile = "kwp"\n')
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    assert settings.find(inner) == outer
    nearer = _file(tmp_path / "a", 'profile = "scenarios"\n')
    assert settings.find(inner) == nearer


def test_the_environment_names_the_file_or_none(tmp_path, clean):
    _file(tmp_path, 'profile = "kwp"\n')
    clean.setenv(settings.CONFIG_ENV, "")
    assert settings.find(tmp_path) is None
    other = _file(tmp_path, 'profile = "scenarios"\n', "other.toml")
    clean.setenv(settings.CONFIG_ENV, str(other))
    assert settings.find(tmp_path) == other.resolve()
    clean.setenv(settings.CONFIG_ENV, str(tmp_path / "missing.toml"))
    with pytest.raises(settings.ConfigError, match="not a file"):
        settings.find(tmp_path)


def test_the_project_is_where_its_file_is(tmp_path, clean):
    clean.setenv(settings.CONFIG_ENV, "")
    settings.apply()
    assert settings.project_file() is None
    assert settings.project_dir() == Path.cwd()
    settings.apply(_file(tmp_path, 'profile = "kwp"\n'))
    assert settings.project_dir() == tmp_path.resolve()


def _python(code, cwd, **env):
    child = {k: v for k, v in os.environ.items()
             if k not in (settings.CONFIG_ENV, "LLM_MODEL", "DOCPIPE_PROFILE",
                          "DOCPIPE_ENV_FILE", "INFERENCE_ENV_FILE")}
    child.update(env, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-c", code], cwd=str(cwd), env=child,
                          capture_output=True, text=True)


def test_importing_the_package_applies_the_project_file(tmp_path):
    """Before any stage is imported: a stage reads the environment when it
    is, and a file applied afterwards would be read by nothing."""
    _file(tmp_path, 'profile = "scenarios"\n[llm]\nmodel = "from-file"\n')
    (tmp_path / "sub").mkdir()
    run = _python("import os, docpipe; from docpipe.refinement import config;"
                  "print(config.LLM_MODEL, os.environ['DOCPIPE_PROFILE'])",
                  tmp_path / "sub")
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["from-file", "scenarios"]


def test_a_project_s_own_dotenv_is_read_from_a_subdirectory(tmp_path):
    _file(tmp_path, 'profile = "kwp"\n')
    (tmp_path / ".env").write_text("LLM_MODEL=from-dotenv\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    run = _python("import os, docpipe; from docpipe import settings;"
                  "print(os.environ['LLM_MODEL'], settings.origin('LLM_MODEL'))",
                  tmp_path / "sub")
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["from-dotenv", ".env"]


def test_a_broken_project_file_stops_the_import_with_one_line(tmp_path):
    _file(tmp_path, '[llm]\nmodle = "x"\n')
    run = _python("import docpipe", tmp_path)
    assert run.returncode != 0
    assert "Traceback" not in run.stderr
    assert "llm.modle is no setting" in run.stderr


# ---------------------------------------------------------------------------
# What a review of the first version found
# ---------------------------------------------------------------------------

def test_a_secret_is_refused_in_the_free_table_by_its_name(tmp_path, clean):
    for name in ("HF_TOKEN", "MY_API_KEY", "DB_PASSWORD", "CLIENT_SECRET"):
        with pytest.raises(settings.ConfigError, match="secret"):
            settings.read(_file(tmp_path, f'[env]\n{name} = "x"\n'))
    # and the provider's own key is a declared secret, refused as one
    assert settings.BY_ENV["GEMINI_API_KEY"].secret
    assert settings.BY_ENV["GOOGLE_API_KEY"].secret
    with pytest.raises(settings.ConfigError, match="GEMINI_API_KEY"):
        settings.read(_file(tmp_path, '[gemini]\napi_key = "x"\n'))
    # a name that only contains such a word is a profile's own knob
    assert settings.read(_file(tmp_path, '[env]\nKEYWORD_LIMIT = 3\n')) == {
        "KEYWORD_LIMIT": "3"}


def test_a_second_file_takes_back_the_first_project_s_dotenv(tmp_path, clean):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "DOCPIPE_ENV_FILE",
                 "INFERENCE_ENV_FILE"):
        clean.delenv(name, raising=False)
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(), second.mkdir()
    (first / ".env").write_text("LLM_BASE_URL=http://a/v1\nLLM_API_KEY=ka\n",
                                encoding="utf-8")
    settings.apply(_file(first, 'profile = "kwp"\n'))
    assert os.environ["LLM_BASE_URL"] == "http://a/v1"
    settings.apply(_file(second, '[llm]\nbase_url = "http://b/v1"\n'))
    assert os.environ["LLM_BASE_URL"] == "http://b/v1"
    assert "LLM_API_KEY" not in os.environ
    assert settings.origin("LLM_BASE_URL") == settings.PROJECT_FILE
    # what the user set meanwhile is theirs, and the first file reads again
    settings.apply(first / settings.PROJECT_FILE)
    assert os.environ["LLM_API_KEY"] == "ka"
    os.environ["LLM_API_KEY"] = "mine"
    settings.apply(second / settings.PROJECT_FILE)
    assert os.environ["LLM_API_KEY"] == "mine"


def test_a_named_env_file_is_the_one_file_loaded(tmp_path, clean):
    clean.delenv("LLM_API_KEY", raising=False)
    (tmp_path / ".env").write_text("LLM_API_KEY=project\n", encoding="utf-8")
    clean.setenv("DOCPIPE_ENV_FILE", str(tmp_path / "other.env"))
    settings.apply(_file(tmp_path, 'profile = "kwp"\n'))
    assert "LLM_API_KEY" not in os.environ
    clean.delenv("DOCPIPE_ENV_FILE")
    settings.apply(tmp_path / settings.PROJECT_FILE)
    assert os.environ["LLM_API_KEY"] == "project"


def test_a_file_in_another_encoding_stops_with_one_line(tmp_path, clean):
    path = tmp_path / settings.PROJECT_FILE
    path.write_bytes('profile = "kwp"\n'.encode("utf-16"))
    with pytest.raises(settings.ConfigError, match="UTF-8"):
        settings.read(path)
    run = _python("import docpipe", tmp_path)
    assert run.returncode != 0 and "Traceback" not in run.stderr
    assert "UTF-8" in run.stderr
    # a byte order mark in front of UTF-8 is an editor's, not the file's
    path.write_bytes(b"\xef\xbb\xbf" + b'profile = "kwp"\n')
    assert settings.read(path) == {"DOCPIPE_PROFILE": "kwp"}


# ---------------------------------------------------------------------------
# What a second review found
# ---------------------------------------------------------------------------

def _written(setting, text):
    """The project file text that sets *setting* to the TOML in *text*."""
    table, _, key = setting.key.rpartition(".")
    return f"[{table}]\n{key} = {text}\n" if table else f"{key} = {text}\n"


def test_every_secret_is_refused_in_the_file_and_names_its_variable(
        tmp_path, clean):
    secrets = [s for s in settings.SETTINGS if s.secret]
    assert secrets
    for s in secrets:
        with pytest.raises(settings.ConfigError, match=s.env) as refused:
            settings.read(_file(tmp_path, _written(s, '"x"')))
        assert "secret" in str(refused.value), s.env


def test_every_name_that_reads_as_a_secret_is_declared_one():
    """The [env] table refuses a secret by its name's ending; a declared
    setting that ends the same way has to be refused in its own table too."""
    open_names = [s.env for s in settings.SETTINGS
                  if settings.SECRET_NAME.search(s.env) and not s.secret]
    assert not open_names, open_names
    assert settings.SECRET_NAME.search("HF_TOKEN")      # and the test sees one


@pytest.mark.parametrize("kind, wrong, wanted", [
    ("float", "true", "a number"), ("float", "false", "a number"),
    ("int", "true", "a whole number"), ("int", "1.5", "a whole number"),
])
def test_a_boolean_is_no_number_for_any_number_setting(
        tmp_path, clean, kind, wrong, wanted):
    numbers = [s for s in settings.SETTINGS if s.kind == kind
               and not (s.secret or s.bootstrap) and "." in s.key]
    assert numbers
    for s in numbers:
        with pytest.raises(settings.ConfigError, match=wanted) as refused:
            settings.read(_file(tmp_path, _written(s, wrong)))
        assert s.key in str(refused.value)


def test_a_float_setting_takes_a_whole_number_and_a_fraction(tmp_path, clean):
    floats = [s for s in settings.SETTINGS if s.kind == "float"
              and not (s.secret or s.bootstrap) and "." in s.key]
    for s in floats:
        assert settings.read(_file(tmp_path, _written(s, "3"))) == {s.env: "3"}
        assert settings.read(_file(tmp_path, _written(s, "0.5"))) == {
            s.env: "0.5"}


def test_a_list_is_joined_with_the_separator_of_its_own_setting(
        tmp_path, clean):
    """No setting of the list is a list today, so a synthetic one."""
    path = tmp_path / settings.PROJECT_FILE
    semicolon = settings.Setting("X_LIST", "x.list", "list", None, "h",
                                 sep=";")
    assert settings._spell(semicolon, ["a", "b", 3, 1.5], path) == "a;b;3;1.5"
    assert settings._spell(semicolon, [], path) == ""
    assert settings._spell(semicolon, "a;b", path) == "a;b"   # taken as it is
    plain = settings.Setting("X_LIST", "x.list", "list", None, "h")
    assert settings._spell(plain, ["a", "b"], path) == "a,b"
    # and through the file's own reading of it
    clean.setitem(settings.BY_KEY, "x.list", semicolon)
    assert settings.read(_file(tmp_path, '[x]\nlist = ["a", "b"]\n')) == {
        "X_LIST": "a;b"}


@pytest.mark.parametrize("wrong", [
    "[true]", '[["a"]]', "3", "[1, true]", '{ a = "b" }', "[[1]]"])
def test_a_list_of_anything_but_strings_and_numbers_is_refused(
        tmp_path, clean, wrong):
    semicolon = settings.Setting("X_LIST", "x.list", "list", None, "h",
                                 sep=";")
    clean.setitem(settings.BY_KEY, "x.list", semicolon)
    with pytest.raises(settings.ConfigError, match="list of strings or numbers"):
        settings.read(_file(tmp_path, f"[x]\nlist = {wrong}\n"))


@pytest.mark.parametrize("name", ["DOCPIPE_ENV_FILE", "INFERENCE_ENV_FILE"])
def test_a_child_process_does_not_inherit_the_callers_env_file(
        tmp_path, monkeypatch, name):
    """The helper that starts a child says what the child may read."""
    leak = tmp_path / "leak.env"
    leak.write_text("DOCPIPE_LEAK_PROBE=read\n", encoding="utf-8")
    monkeypatch.setenv(name, str(leak))
    _file(tmp_path, 'profile = "kwp"\n')
    run = _python("import os, docpipe;"
                  "print(os.environ.get('DOCPIPE_LEAK_PROBE'))", tmp_path)
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["None"]
