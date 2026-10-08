"""The core stays generic: docpipe knows neither a project nor a UI.

This is the test that keeps the split alive once the modules move into
docpipe/ — without it, the first "just this once" import rots the boundary.
"""
import ast
import pathlib
import re

import pytest

CORE = pathlib.Path(__file__).resolve().parent.parent / "docpipe"
PROFILES = CORE.parent / "profiles"
# The profile the package brings itself lies inside it.
BUILTIN = CORE / "builtin"
FORBIDDEN = ("profiles", "streamlit")
# The one module of the package that is a UI: the chat app's page. Every
# other module, the app's own configuration and link builder included, is
# imported by tests, by the command and by batch jobs, none of which have
# Streamlit.
UI = CORE / "app" / "app.py"
_PROMPT_ID = re.compile(r"\A[a-z_]+/[a-z_0-9]+\Z")


def _imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


@pytest.mark.parametrize("path", sorted(CORE.rglob("*.py")), ids=lambda p: p.name)
def test_core_imports_neither_profiles_nor_streamlit(path):
    forbidden = ("profiles",) if path == UI else FORBIDDEN
    for lineno, module in _imported_modules(path):
        root = module.split(".")[0]
        assert root not in forbidden, (
            f"{path.relative_to(CORE.parent)}:{lineno} imports {module!r}; "
            f"the core must receive a profile, not fetch one, and must stay "
            f"usable from the CLI and the batch module")


def test_the_one_ui_module_is_the_one_that_imports_streamlit():
    """The exception above is one file, and it is the file that needs it."""
    assert UI.is_file()
    assert "streamlit" in {module.split(".")[0]
                           for _line, module in _imported_modules(UI)}


def _requested_prompt_ids(*roots):
    """The prompt ids the source asks for: literal load()/text() arguments,
    the chat's `_prompt("stage/name")`, plus `*_PROMPT_ID = "stage/name"`
    constants (loaded through the name)."""
    ids = set()
    for root in roots:
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call)
                        and (isinstance(node.func, ast.Attribute)
                             and node.func.attr in ("load", "text")
                             or isinstance(node.func, ast.Name)
                             and node.func.id == "_prompt")
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and _PROMPT_ID.match(node.args[0].value)):
                    ids.add(node.args[0].value)
                elif (isinstance(node, ast.Assign)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                        and _PROMPT_ID.match(node.value.value)
                        and any(isinstance(t, ast.Name)
                                and t.id.endswith("_PROMPT_ID")
                                for t in node.targets)):
                    ids.add(node.value.value)
    return ids


# Stages a profile opts into via a component; their prompts are required
# exactly when the profile provides that component.
OPTIONAL_STAGES = {"extraction": ("extraction", "SPEC_PATH"),
                   "kg": ("kg", "VALUE_QUERY")}


def _required_for(profile, requested):
    out = set()
    for pid in requested:
        opt = OPTIONAL_STAGES.get(pid.split("/", 1)[0])
        if opt and profile.component(*opt) is None:
            continue
        out.add(pid)
    return out


def _profile_homes():
    return sorted(p for root in (PROFILES, BUILTIN) for p in root.iterdir()
                  if (p / "prompts").is_dir() and any((p / "prompts").rglob("*.md")))


def test_the_built_in_profile_is_among_the_profiles_checked():
    assert "default" in [home.name for home in _profile_homes()]


@pytest.mark.parametrize("home", _profile_homes(), ids=lambda p: p.name)
def test_a_profile_provides_every_prompt_the_core_loads(home):
    """The core has no prompts of its own to fall back on, so a stage this
    profile never wrote a prompt for fails at import — in a batch job, hours
    after it was submitted."""
    from docpipe import prompts
    from docpipe.profile import load_profile

    requested = _requested_prompt_ids(CORE)
    assert requested, "no prompt calls found — did the layout change?"
    profile = load_profile(home.name)
    missing = sorted(pid for pid in _required_for(profile, requested)
                     if not prompts.path_for(pid, profile).is_file())

    assert not missing, f"{home.name} is missing {missing}"


@pytest.mark.parametrize("home", _profile_homes(), ids=lambda p: p.name)
def test_a_profile_carries_no_prompt_nobody_loads(home):
    """A file the code never asks for is either dead or a misspelt name — and a
    misspelt name reads as a prompt that exists while the real one is missing."""
    on_disk = {f"{p.parent.name}/{p.stem}" for p in (home / "prompts").rglob("*.md")}

    assert on_disk - _requested_prompt_ids(CORE, home) == set()


def _required_components(*roots) -> set:
    """(module, attr) pairs the core demands of a profile, read from the
    profile.require / profile_value calls themselves."""
    wanted = set()
    for root in roots:
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", None))
                if name not in ("require", "profile_value") or len(node.args) < 2:
                    continue
                mod, attr = node.args[0], node.args[1]
                if (isinstance(mod, ast.Constant) and isinstance(mod.value, str)
                        and isinstance(attr, ast.Constant)
                        and isinstance(attr.value, str)):
                    wanted.add((mod.value, attr.value))
    return wanted


@pytest.mark.parametrize("home", _profile_homes(), ids=lambda p: p.name)
def test_a_profile_provides_every_component_the_core_requires(home):
    """Same motive as the prompt check, for everything that is not a prompt.

    The core asks the profile for the facts it must not invent — which words
    open a caption, how long one gets, which words hold a hyphen open. Missing
    ones used to surface as a LookupError deep inside a batch job, or worse,
    as a German default quietly applied to an English corpus.
    """
    from docpipe.profile import load_profile

    required = _required_components(CORE)
    assert required, "no profile.require/profile_value calls found — layout changed?"
    profile = load_profile(home.name)
    missing = sorted(f"{mod}.{attr}" for mod, attr in required
                     if profile.component(mod, attr) is None)

    assert not missing, f"{home.name} is missing {missing}"


# ---------------------------------------------------------------------------
# No stage repairs a model's JSON.
#
# Promised: refinement, the visuals stage and the page transcription read a
# reply through `docpipe.reading` and nowhere else AND none of them closes,
# strips, cuts out or salvages anything from it. A reply that is not the one
# object is asked again with its cause, and a cut one is split or given room.
# ---------------------------------------------------------------------------

STAGES = [*sorted((CORE / "refinement").glob("*.py")),
          *sorted((CORE / "visuals").glob("*.py")),
          CORE / "preprocessing" / "page_text_fallback.py"]

# A name that does what the old code did: it is a repair by its own account.
_SOFTENER_NAME = re.compile(
    r"repair|salvage|rescue|lenient|fix_?json|extract_?json|strip_?(fence|think)"
    r"|close_?(brackets|json)|balance", re.I)
# A cut of an object out of the text around it.
_CUTTERS = {"find", "rfind", "index", "rindex"}
_BRACKETS = {"{", "}", "[", "]"}
_RAW_READERS = {"loads", "raw_decode", "JSONDecoder"}


def _softeners(source: str) -> list:
    """(line, what) for each place the source softens a reply."""
    found = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _SOFTENER_NAME.search(node.name):
                found.append((line, f"def {node.name}"))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""])
            for name in names:
                if re.search(r"json_?repair|demjson|dirtyjson|json5", name):
                    found.append((line, f"imports {name}"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else getattr(func, "id", ""))
            if _SOFTENER_NAME.search(name):
                found.append((line, f"calls {name}"))
            elif name in _RAW_READERS:
                found.append((line, f"reads text itself with {name}"))
            elif name in _CUTTERS and any(
                    isinstance(a, ast.Constant) and a.value in _BRACKETS
                    for a in node.args):
                found.append((line, f"cuts at a bracket with {name}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if "```" in text or "<think>" in text or "</think>" in text:
                found.append((line, "names a fence or a think block"))
            elif "\\{" in text and "\\}" in text:
                found.append((line, "a pattern that cuts an object out"))
    return found


def test_the_stages_scanned_are_the_ones_that_read_a_reply():
    names = {p.name for p in STAGES}
    assert {"refine.py", "split.py", "vision.py", "process.py",
            "page_text_fallback.py"} <= names, names


@pytest.mark.parametrize("path", STAGES, ids=lambda p: p.name)
def test_no_stage_repairs_a_reply(path):
    found = _softeners(path.read_text(encoding="utf-8"))
    assert not found, (
        f"{path.relative_to(CORE.parent)} softens a reply: "
        + "; ".join(f"line {n}: {what}" for n, what in found)
        + ". Read it through docpipe.reading and ask again, split or "
          "give room; nothing is closed, stripped or cut out")


@pytest.mark.parametrize("snippet, what", [
    ("def _repair_json(raw):\n    return raw + '}'\n", "def _repair_json"),
    ("def close_json(raw):\n    return raw\n", "def close_json"),
    ("def _salvage_tuples(raw):\n    return []\n", "def _salvage_tuples"),
    ("raw = raw.strip().strip('```json')\n", "names a fence or a think block"),
    ("raw = re.sub(r'<think>.*?</think>', '', raw)\n",
     "names a fence or a think block"),
    ("data = raw[raw.find('{'):raw.rfind('}') + 1]\n", "cuts at a bracket"),
    ("data = json.loads(raw)\n", "reads text itself with loads"),
    ("obj, end = decoder.raw_decode(raw, 3)\n",
     "reads text itself with raw_decode"),
    ("import json_repair\n", "imports json_repair"),
    ("m = re.search(r'\\{.*\\}', raw, re.S)\n", "a pattern that cuts an object out"),
])
def test_the_guard_sees_the_bug_it_is_there_for(snippet, what):
    """Each softener the stages had, written out again: the scan has to name
    it. A guard that finds nothing in the code as it is, and finds nothing in
    the code as it was, is a decoration."""
    found = _softeners(snippet)
    assert found and any(w.startswith(what) for _n, w in found), (snippet, found)


def test_a_stage_that_reads_through_the_reader_and_asks_again_is_not_reported():
    clean = (
        "from docpipe import reading\n"
        "def ask(client, messages):\n"
        "    data, cause, fault = reading.read(choice, 'markdown', str)\n"
        "    if cause:\n"
        "        messages.append({'role': 'user', 'content': fault})\n"
        "    return data\n")
    assert _softeners(clean) == []
