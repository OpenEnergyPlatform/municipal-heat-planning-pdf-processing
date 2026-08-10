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
    """The prompt ids the source asks for, read out of the calls themselves."""
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
    return ids


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
    missing = sorted(pid for pid in requested
                     if not prompts.path_for(pid, profile).is_file())

    assert not missing, f"{home.name} is missing {missing}"


@pytest.mark.parametrize("home", _profile_homes(), ids=lambda p: p.name)
def test_a_profile_carries_no_prompt_nobody_loads(home):
    """A file the code never asks for is either dead or a misspelt name — and a
    misspelt name reads as a prompt that exists while the real one is missing."""
    on_disk = {f"{p.parent.name}/{p.stem}" for p in (home / "prompts").rglob("*.md")}

    assert on_disk - _requested_prompt_ids(CORE, home) == set()
