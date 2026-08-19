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
FORBIDDEN = ("profiles", "streamlit")
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
    for lineno, module in _imported_modules(path):
        root = module.split(".")[0]
        assert root not in FORBIDDEN, (
            f"{path.relative_to(CORE.parent)}:{lineno} imports {module!r}; "
            f"the core must receive a profile, not fetch one, and must stay "
            f"usable from the CLI and the batch module")


def _requested_prompt_ids(*roots):
    """The prompt ids the source asks for: literal load()/text() arguments
    plus `*_PROMPT_ID = "stage/name"` constants (loaded through the name)."""
    ids = set()
    for root in roots:
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("load", "text")
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
OPTIONAL_STAGES = {"extraction": ("extraction", "SPEC_PATH")}


def _required_for(profile, requested):
    out = set()
    for pid in requested:
        opt = OPTIONAL_STAGES.get(pid.split("/", 1)[0])
        if opt and profile.component(*opt) is None:
            continue
        out.add(pid)
    return out


def _profile_homes():
    return sorted(p for p in PROFILES.iterdir()
                  if (p / "prompts").is_dir() and any((p / "prompts").rglob("*.md")))


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
