"""The core stays generic: docpipe knows neither a project nor a UI.

This is the test that keeps the split alive once the modules move into
docpipe/ — without it, the first "just this once" import rots the boundary.
"""
import ast
import pathlib

import pytest

CORE = pathlib.Path(__file__).resolve().parent.parent / "docpipe"
FORBIDDEN = ("profiles", "streamlit")


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


def test_every_core_prompt_is_reachable():
    ids = [f"{p.parent.parent.name}/{p.stem}"
           for p in CORE.rglob("prompts/*.md")]
    assert ids, "no prompts found — did the layout change?"
    from docpipe import prompts
    for pid in ids:
        assert prompts.load(pid, use_ambient=False).sha256
