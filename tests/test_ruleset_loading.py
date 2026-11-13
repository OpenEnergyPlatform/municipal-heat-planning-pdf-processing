"""
The ruleset's modules load without rules.py: whichever of them, or of
rules.py, a program imports first, the import succeeds and rules.RULES
holds their rules. rules.py gathers the ruleset's rules while it loads, so
a module of the ruleset that imported rules.py while it loads would make
the two wait for each other whenever the ruleset came first
(`profiles.scenarios.oekg_api` reached it through the archive).
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULESET = ROOT / "docpipe" / "ruleset"


def outside(text: str) -> list:
    """The modules of docpipe outside the ruleset package that a module
    imports while it loads (at its top level), as written."""
    out = []
    for node in ast.parse(text).body:
        if isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            if node.level > 1 or name.startswith("docpipe"):
                out.append(name)
        elif isinstance(node, ast.Import):
            out += [one.name for one in node.names
                    if one.name.startswith("docpipe")]
    return out


def test_the_kit_imports_nothing_of_docpipe():
    text = (RULESET / "kit.py").read_text(encoding="utf-8")
    assert outside(text) == []
    assert not [node for node in ast.parse(text).body
                if isinstance(node, ast.ImportFrom) and node.level]


def test_no_module_of_the_ruleset_imports_docpipe_outside_it_as_it_loads():
    found = {path.name: outside(path.read_text(encoding="utf-8"))
             for path in sorted(RULESET.glob("*.py"))}
    assert len(found) >= 8
    assert {name: names for name, names in found.items() if names} == {}


def test_an_import_of_rules_py_at_the_top_is_found():
    assert outside("from ..rules import ASKING, rule\n") == ["..rules"]
    assert outside("import docpipe.rules\n") == ["docpipe.rules"]
    assert outside("from .kit import rule\n") == []
    assert outside("def run_value(name):\n"
                   "    from .. import rules\n") == []


def test_the_ruleset_imported_first_loads_and_rules_holds_its_rules():
    script = ("import docpipe.ruleset.passes\n"
              "from docpipe import rules\n"
              "from docpipe.ruleset import passes\n"
              "names = {one.name for one in passes.RULES}\n"
              "assert names and names <= set(rules.BY_NAME), names\n"
              "print(len(names))\n")
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert int(done.stdout.split()[-1]) > 0
