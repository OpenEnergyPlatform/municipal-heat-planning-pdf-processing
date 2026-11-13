"""
Every value a run or a step may change is read where it is used, at the
time of use, and never while a module loads (owner decision 2026-11-11:
a rule is read where it is used, never at import). A value read while its
module loads is the one of the first moment the module was imported: a value a
step sets for itself, a graph file the editor saved, a rule a test
overlays come too late for it, and the setting has no effect there.

The promise: importing the modules of docpipe and of the profiles calls no
reader of the rules, the graph file or the flow (`rules.get`,
`rules.current`, `graphfile.get`, `graphfile.get_map`, `flow.number`,
`flow.tree_of`, `flow.load`), neither directly nor through a function of
theirs. Broken by construction: a module that sets `X = rules.get(...)` at
its top, and one that calls at its top a function reading the graph file,
are both found.

AND every rule is read by some code: a rule that only its declaration
names changes nothing however it is set. Broken by construction: a rule
whose value the code writes as a number of its own (`payload = 2000`) is
found.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The readers, by file and function: the profile hook below knows them
# before their modules are imported, so a module imported on the way to
# them is watched too.
READERS = {("docpipe/rules.py", "get"), ("docpipe/rules.py", "current"),
           ("docpipe/graphfile.py", "get"),
           ("docpipe/graphfile.py", "get_map"),
           ("docpipe/extraction/flow.py", "number"),
           ("docpipe/extraction/flow.py", "tree_of"),
           ("docpipe/extraction/flow.py", "load")}

# The modules that own the readers build their own defaults while they load.
OWNERS = ("docpipe.rules", "docpipe.graphfile", "docpipe.ruleset")

WATCH = """
import importlib, json, sys
readers = set(tuple(one) for one in json.loads(sys.argv[1]))
root = sys.argv[2].replace(chr(92), "/").rstrip("/") + "/"
found = []

def where(path):
    path = path.replace(chr(92), "/")
    return path[len(root):] if path.startswith(root) else path

def hook(frame, event, arg):
    if event != "call":
        return
    code = frame.f_code
    if (where(code.co_filename), code.co_name) not in readers:
        return
    back = frame.f_back
    while back is not None and back.f_code.co_name != "<module>":
        back = back.f_back
    if back is not None:
        found.append([back.f_globals.get("__name__") or "",
                      back.f_lineno, code.co_name])

skipped, failed = [], []
sys.setprofile(hook)
for name in sys.argv[3:]:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        top = (exc.name or "").split(".")[0]
        if top in ("docpipe", "profiles"):
            failed.append([name, repr(exc)])
        else:
            skipped.append([name, exc.name])
    except Exception as exc:
        failed.append([name, repr(exc)])
sys.setprofile(None)
print(json.dumps({"found": found, "skipped": skipped, "failed": failed}))
"""


def modules() -> list:
    """Every module of docpipe and of the profiles, by its dotted name."""
    out = []
    for base in ("docpipe", "profiles"):
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = path.relative_to(ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__main__" or "__pycache__" in parts:
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            out.append(".".join(parts))
    return out


def reads_at_import(names: list, extra_path: str = "") -> dict:
    """{"found": [[module, line, reader]], "skipped": [[module, missing]]}
    for importing *names* in a fresh interpreter."""
    env_path = [str(ROOT)] + ([extra_path] if extra_path else [])
    script = "import sys; sys.path[:0] = " + json.dumps(env_path) + WATCH
    done = subprocess.run(
        [sys.executable, "-c", script, json.dumps(sorted(READERS)),
         str(ROOT)] + names, cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", timeout=600)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def own(found: list) -> list:
    return sorted({(module, line, reader) for module, line, reader in found
                   if not module.startswith(OWNERS)})


def test_no_module_reads_a_rule_the_graph_file_or_the_flow_while_it_loads():
    result = reads_at_import(modules())
    assert result["failed"] == []
    assert own(result["found"]) == []


def names_read(names: set, paths) -> set:
    """The names of *names* that code in *paths* names, as a string or an
    attribute, outside the declaration of a rule (`rule(name, ...)`)."""
    out = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        declared = {id(node.args[0]) for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and node.args
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("rule", "_r")}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in names \
                    and id(node) not in declared:
                out.add(node.value)
            elif isinstance(node, ast.Attribute) and node.attr in names:
                out.add(node.attr)
    return out


def every_rule() -> dict:
    """{name: Rule} of the rules of both profiles' lines and graph files."""
    from docpipe import graphfile, rules
    from docpipe.profile import load_profile
    out = dict(rules.BY_NAME)
    for name in ("kwp", "scenarios"):
        profile = load_profile(name)
        out.update(rules.registry(profile))
        out.update(graphfile.declared(profile))
    return out


def test_every_rule_is_read_by_the_code_that_its_value_changes():
    """A rule nobody reads is a setting without effect: the page offers it,
    and whatever it is set to, the run does the same. A rule with one
    choice states the only way there is, and needs no reader."""
    rules_ = {name: one for name, one in every_rule().items()
              if len(one.choices) != 1}
    paths = [path for base in ("docpipe", "profiles")
             for path in sorted((ROOT / base).rglob("*.py"))]
    assert sorted(set(rules_) - names_read(set(rules_), paths)) == []


def test_a_rule_named_only_where_it_is_declared_is_found(tmp_path):
    declared = tmp_path / "declares.py"
    declared.write_text(
        "RULES = (rule('a_floor', 'flow', 'G', 'whole', 'help'),\n"
        "         rule('a_read', 'flow', 'G', 'whole', 'help'))\n"
        "def budget():\n"
        "    payload = 2000\n"
        "    return payload + rules.get('a_read')\n", encoding="utf-8")
    names = {"a_floor", "a_read"}
    assert names_read(names, [declared]) == {"a_read"}


def test_a_module_that_reads_a_rule_while_it_loads_is_found(tmp_path):
    (tmp_path / "reads_rule_at_top.py").write_text(
        "from docpipe import rules\n"
        "TRACE = rules.get('trace_on')\n", encoding="utf-8")
    (tmp_path / "reads_drawing_through_a_function.py").write_text(
        "from docpipe import graphfile\n"
        "def drawing():\n"
        "    return graphfile.get_map('kwp')\n"
        "BOXES = drawing().get('boxes')\n", encoding="utf-8")
    (tmp_path / "reads_at_use.py").write_text(
        "from docpipe import rules\n"
        "def trace():\n"
        "    return rules.get('trace_on')\n", encoding="utf-8")
    result = reads_at_import(
        ["reads_rule_at_top", "reads_drawing_through_a_function",
         "reads_at_use"], extra_path=str(tmp_path))
    modules_found = {module for module, _line, _reader in result["found"]}
    assert "reads_rule_at_top" in modules_found
    assert "reads_drawing_through_a_function" in modules_found
    assert "reads_at_use" not in modules_found
