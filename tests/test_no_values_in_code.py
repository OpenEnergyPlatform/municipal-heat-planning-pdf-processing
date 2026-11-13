"""
No value of the reading stands in its code (owner 2026-11-11: "alles
soll anpassbar sein").

The promise: in the modules of the reading no module-level constant is a
number or a switch, AND no code reads the environment, AND no code reads
the rules past `rules.get` (`rules.current()[...]`), except the entries of
`NOT_VALUES`, each with the reason why it is no value of the run (the
plan's Anhang B: a key name, an enumeration the code dispatches on, a
format, a version, a fact of a unit). A value of the run is a rule
(`docpipe/rules.py`, `docpipe/ruleset/`) or a number of the flow, read where
it is used; an environment variable sets it as the rule's `env`.

Broken by construction: a module with `LIMIT = 5`, and one that reads
`os.environ.get("X")`, are both found (`found_in`).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTION_SKIPPED = {
    # the graph stage has its own tab; these write or check files after
    # the harvest, or are entry points
    "graph.py", "graphkit.py", "serialize.py", "gold.py", "benchmark.py",
    "evaluate.py", "scratch.py", "shapemodel.py", "provenance.py",
    "gate.py", "contract.py", "__init__.py", "__main__.py", "bricks.py",
    "readings.py"}
MODULES = sorted(
    [p for p in (ROOT / "docpipe" / "extraction").glob("*.py")
     if p.name not in EXTRACTION_SKIPPED]
    + [ROOT / "docpipe" / "inference" / name for name in (
        "rerank.py", "faiss_store.py", "code_exec.py", "pdf_locate.py")]
    + [p for p in (ROOT / "docpipe" / "providers").glob("*.py")]
    + [ROOT / "docpipe" / "llm_preflight.py", ROOT / "docpipe" / "settings.py",
       ROOT / "docpipe" / "inference" / "pool.py"]
    + [p for name in ("kwp", "scenarios")
       for p in (ROOT / "profiles" / name).glob("*.py")
       if p.name not in ("kg.py", "vocabulary.py", "__init__.py",
                         "profile.py", "config.py", "source.py",
                         "store.py", "preprocessing.py", "inference.py",
                         "mhpkg.py", "oekg_api.py")
       and not p.name.startswith("migrate_")])
ENV_CALLS = {("os.environ", "get"), ("os", "getenv"), ("environ", "get")}

# (module path from the repository root, name): why it is no value of the
# run. Filled from the plan's Anhang B; every entry names its reason.
NOT_VALUES: dict = {
    ("docpipe/extraction/runner.py", "STOPPED_EXIT"):
        "the exit code of a run that SIGTERM stopped, a fact of the shell",
    ("docpipe/extraction/runner.py", "REST_TO_END"):
        "stands for no limit where a search shows every piece of its plan",
    ("docpipe/extraction/runner.py", "TO_END"):
        "the state of the process: a pass that reads to the end set it",
    ("docpipe/extraction/runner.py", "_UNPARSABLE_SHOWN"):
        "a count of the process of the replies shown so far in the log",
    ("docpipe/extraction/flow.py", "LOADED_KEPT"):
        "the size of a cache of loaded files that changes no result",
}


def number_of(value):
    """The number or switch a module-level expression of literals makes:
    a literal, a sign before one, arithmetic of them (`10 * 60`), or a
    tuple or list of them; None for anything else."""
    if isinstance(value, ast.Constant):
        return value.value if isinstance(value.value, (int, float)) \
            else None
    if isinstance(value, ast.UnaryOp) \
            and isinstance(value.op, (ast.USub, ast.UAdd)):
        inner = number_of(value.operand)
        if inner is None:
            return None
        return -inner if isinstance(value.op, ast.USub) else inner
    if isinstance(value, ast.BinOp):
        left, right = number_of(value.left), number_of(value.right)
        if not isinstance(left, (int, float)) \
                or not isinstance(right, (int, float)):
            return None
        try:
            return eval(compile(ast.Expression(value), "<n>", "eval"), {})
        except ArithmeticError:
            return None
    if isinstance(value, (ast.Tuple, ast.List)) and value.elts:
        items = [number_of(one) for one in value.elts]
        return None if any(one is None for one in items) else tuple(items)
    return None


def found_in(path: Path, text: str) -> list:
    """[(line, what)] of the values *text* holds in its code."""
    tree = ast.parse(text)
    rel = path.relative_to(ROOT).as_posix() if path.is_absolute() \
        else path.as_posix()
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name) \
                    or not target.id.isupper():
                continue
            literal = number_of(value)
            if literal is not None \
                    and (rel, target.id) not in NOT_VALUES:
                out.append((node.lineno, f"{target.id} = {literal!r}"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) \
                and isinstance(node.func, ast.Attribute) \
                and (ast.unparse(node.func.value), node.func.attr) \
                in ENV_CALLS and node.args \
                and isinstance(node.args[0], ast.Constant):
            name = node.args[0].value
            if (rel, name) not in NOT_VALUES:
                out.append((node.lineno, f"reads the environment: {name}"))
        if isinstance(node, ast.Subscript) \
                and isinstance(node.value, ast.Subscript) is False \
                and ast.unparse(node.value) in ("rules.current()",
                                                "current()"):
            out.append((node.lineno, "reads a rule past rules.get"))
    return out


def test_found_in_finds_a_constant_and_an_environment_read():
    made = ROOT / "docpipe" / "extraction" / "made_up.py"
    got = found_in(made, "import os\nLIMIT = 5\n\ndef f():\n"
                         "    return os.environ.get('X')\n")
    assert [what for _line, what in got] == [
        "LIMIT = 5", "reads the environment: X"]
    # a number made of numbers, a switch and a tuple of numbers are values
    got = found_in(made, "WAIT = 10 * 60\nON = True\nSHARES = (20, 15)\n"
                         "NAMES = ('a', 'b')\n")
    assert [what for _line, what in got] == [
        "WAIT = 600", "ON = True", "SHARES = (20, 15)"]


def test_no_value_of_the_reading_stands_in_its_code():
    found = {}
    for path in MODULES:
        got = found_in(path, path.read_text(encoding="utf-8"))
        if got:
            found[path.relative_to(ROOT).as_posix()] = got
    assert found == {}, "\n".join(
        f"{module}:{line} {what}" for module, rows in found.items()
        for line, what in rows)


def test_every_exception_names_its_reason():
    assert all(isinstance(why, str) and len(why.split()) >= 3
               for why in NOT_VALUES.values())
