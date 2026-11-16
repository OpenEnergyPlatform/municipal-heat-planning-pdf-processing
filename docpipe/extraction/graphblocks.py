"""
graphblocks.py: The blocks a drawing of the graph is made of, beside the
bricks it names (owner request 2026-11-14, wish 4: "Beim Graphen ... sollten
die Baublöcke und Einstellungsmöglichkeiten genau wie im Flow fein sein,
sodass man da wirklich alles konfigurieren kann").

Wherever a drawing names a brick (`{"brick": name, "settings": {...}}`) it
may set one of these instead:

  {"if": condition, "reason": "..."}      a condition (`conditions.py`) about
        the reading and what is known of the document; where it does not
        hold, the reading is left out for the reason, whose {key} stands for
        that key of the reading and {a|b|'?'} for the first of them that is
        there, else the words in quotes
  {"steps": [block, ...]}                 one block after another: each
        takes the value the one before it gave; the last one writes
  {"python": "def run(call): ...", "per", "writes", "settings"}
        Python of the drawing's own, run in the run's process as the flow's
        Python step is (owner decision 2026-11-12, point 12); it sees the
        profile's own module `kg`, `log`, `literal`, `in_graph`, `is_class`
        and `ttl_string`

and an address may be made of parts (`address_part`). Every block becomes a
`Brick`, so the writer calls a block as it calls a brick, and a drawing
that names only bricks is written as before. A block put in from a preset
keeps the preset's name under "preset" (`name_of`), changed or not.

Author: Felix Vossel
"""
from __future__ import annotations

import ast
import builtins
import dataclasses
import inspect
import logging
import re
import textwrap
from typing import Callable, Optional

from . import conditions
from .bricks import KINDS, Brick, Call, in_graph, is_class, literal
from .graphkit import NOT_IN_GRAPH, ttl_string

log = logging.getLogger(__name__)

# What a part of an address is made from, and how it is written.
PART_FROM = ("reading", "chosen", "name", "key", "fact", "answer_address",
             "wording")
PART_FORMS = ("text", "iri", "class", "fold")
PART_ABSENT = ("refuse", "empty", "omit")
# The kinds a step of a chain may be: what writes an object, what spells a
# name, what turns a value into another.
STEP_KINDS = ("object", "name", "value")


class BlockError(ValueError):
    """A block the program cannot run. It names what is wrong."""


def name_of(ref) -> Optional[str]:
    """The name a block of a drawing goes by: the brick it names, else the
    preset it was put in from, else None."""
    if isinstance(ref, str):
        return ref
    if not isinstance(ref, dict):
        return None
    if shape(ref) == "brick":
        return ref.get("brick")
    return ref.get("preset")


def shape(ref) -> str:
    """Which form a block of a drawing has: brick, if, steps or python."""
    if isinstance(ref, str):
        return "brick"
    if not isinstance(ref, dict):
        return ""
    for form in ("if", "steps", "python"):
        if form in ref:
            return form
    return "brick" if "brick" in ref else ""


# -- the reading as a condition and a part see it ------------------------------

def derived(spec, row: dict, key: str):
    """A key of a reading the harvest does not write but the spec decides:
    `unit_target`, the unit its number was converted onto (the entry's own
    target, else the field's)."""
    if key == "unit_target":
        parameter = spec.by_uri.get(row.get("parameter")) if spec else None
        return parameter.target_of(row.get("unit")) if parameter else None
    return None


def value_at(doc, row: Optional[dict], path: str):
    """The value at *path* of a reading ("quantity", "provenance.page"),
    a key the spec decides where the reading has none (`derived`)."""
    first, *rest = str(path).split(".")
    row = row or {}
    value = row.get(first) if first in row else derived(
        getattr(doc, "spec", None), row, first)
    for key in rest:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def listed(doc, row: dict, path: str) -> bool:
    """Is the answer at *path* an entry of the list the spec gives that
    dimension of the reading's field (the field's own list for its value),
    and no out: entry?"""
    value = value_at(doc, row, path)
    if not isinstance(value, str) or value.startswith(NOT_IN_GRAPH):
        return False
    parameter = doc.spec.by_uri.get(row.get("parameter"))
    if parameter is None:
        return False
    if path in ("value", "value_uri"):
        return value in (parameter.vocabulary or {})
    axis = (parameter.axes or {}).get(path)
    return value in ((getattr(axis, "vocabulary", None) or {}) if axis
                     else {})


def facts(doc, row: Optional[dict]) -> conditions.Facts:
    """What a condition of the drawing knows of one reading."""
    def get(subject: str, path: str):
        if subject == "reading":
            return value_at(doc, row, path)
        if subject == "fact":
            value = doc.facts or {}
            for key in str(path).split("."):
                value = value.get(key) if isinstance(value, dict) else None
            return value
        raise LookupError(f"{subject} is not known in a drawing of the graph")

    def test(subject: str, path: str, op: str, want) -> bool:
        have = get(subject, path)
        if op == "listed":
            return listed(doc, row or {}, path)
        if op == "names":
            return isinstance(have, str) and bool(doc.fold(have))
        if op == "answer_of":
            box = doc.writer.drawing.box.get(want) or {}
            return have in (box.get("table") or {})
        raise LookupError(f"{op} is not known in a drawing of the graph")

    return conditions.Facts(get, test)


_SLOT = re.compile(r"\{([^{}]*)\}")


def reason(template: str, doc, row: Optional[dict]) -> str:
    """The reason a reading is left out, its {key} filled from the reading:
    {a|b|'?'} is the first of a and b that is there, else the words in
    quotes; a single {key} is that key as Python writes it, None too."""
    def fill(match) -> str:
        options = [one.strip() for one in match.group(1).split("|")]
        if len(options) == 1:
            return str(value_at(doc, row, options[0]))
        for one in options:
            if len(one) >= 2 and one[0] == one[-1] and one[0] in "'\"":
                return one[1:-1]
            value = value_at(doc, row, one)
            if value:
                return str(value)
        return ""
    return _SLOT.sub(fill, str(template or ""))


# -- Python of the drawing ----------------------------------------------------

def python_problem(code) -> Optional[str]:
    """Why *code* is no block, None where it is one: Python that defines
    run(call)."""
    if not isinstance(code, str) or not code.strip():
        return "the code is empty"
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"the code is no Python: line {exc.lineno}: {exc.msg}"
    if not any(isinstance(node, ast.FunctionDef) and node.name == "run"
               for node in tree.body):
        return "the code defines run(call), which gives what the block gives"
    return None


def compiled(code: str, space: dict) -> Callable:
    """run(call) of *code*, with the names of *space* beside it."""
    said = python_problem(code)
    if said:
        raise BlockError(said)
    names = {"__name__": "docpipe_graph_block", "literal": literal,
             "in_graph": in_graph, "is_class": is_class,
             "ttl_string": ttl_string, "NOT_IN_GRAPH": NOT_IN_GRAPH,
             "re": re, "log": log, **space}
    exec(compile(code, "<graph block>", "exec"), names)
    return names["run"]


# The names a block of Python sees without an import, beside "kg" where the
# profile has a module of the graph.
BLOCK_NAMES = ("literal", "in_graph", "is_class", "ttl_string",
               "NOT_IN_GRAPH", "re", "log", "kg")


def _bound(tree: ast.AST) -> set:
    """The names a piece of code makes itself: arguments, assignments,
    imports, definitions, loop and handler names."""
    out: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx,
                                                      (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add((alias.asname or alias.name).split(".")[0])
    return out


def python_of(brick: Brick, names=BLOCK_NAMES) -> str:
    """The logic of a brick as the Python of a block: its own function with
    the def line `def run(call):`, and an import line for every name its body
    uses that a block does not have (*names*), taken from the brick's own
    module, so the code runs as it stands. Relative imports in the body are
    written out in full. The empty text where the source is not to be had."""
    function = brick.run
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError):
        return ""
    func = ast.parse(source).body[0]
    if not isinstance(func, ast.FunctionDef):
        return ""
    module = getattr(function, "__module__", "") or ""
    lines = source.splitlines()
    for node in ast.walk(func):
        if isinstance(node, ast.ImportFrom) and node.level:
            parent = module.rsplit(".", node.level)[0]
            full = f"{parent}.{node.module}" if node.module else parent
            lines[node.lineno - 1] = re.sub(
                r"from\s+\.+\w*(?:\.\w+)*\s+import", f"from {full} import",
                lines[node.lineno - 1], count=1)
    body = "\n".join(lines[func.body[0].lineno - 1:]) + "\n"
    own = _bound(func)
    # The body only: the annotations of the def line are not carried over.
    used = {node.id for statement in func.body for node in ast.walk(statement)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    scope = getattr(function, "__globals__", {})
    imports, taken = [], []
    for name in sorted(used - own - set(names) - set(dir(builtins))):
        if name not in scope:
            continue
        if inspect.ismodule(scope[name]):
            real = scope[name].__name__
            imports.append(f"import {real}" if real == name
                           else f"import {real} as {name}")
        elif module:
            taken.append(name)
    if taken:
        imports.append(f"from {module} import {', '.join(taken)}")
    head = ("\n".join(imports) + "\n\n\n") if imports else ""
    return head + "def run(call):\n" + body


def python_block(ref, kind: str, bricks: dict, space: Optional[dict] = None
                 ) -> str:
    """Any block of a drawing as the Python of a block that does the same:
    a brick as its own logic (`python_of`), a condition as the test and the
    reason it gives, steps as each step's code in a function of its own and
    the chain that hands each step what the step before gave, its settings
    beside it. The code runs as it stands where a block of Python runs.
    The empty text where a step's source is not to be had; BlockError where
    *ref* is no block of *kind*."""
    form = shape(ref)
    if form == "python":
        return str(ref["python"])
    if form == "brick":
        return python_of(resolve(ref, kind, bricks, space))
    if form == "if":
        resolve(ref, kind, bricks, space)
        why = str(ref.get("reason") or "condition")
        return (f"import {conditions.__name__} as conditions\n"
                f"from {__name__} import facts, reason\n\n\n"
                f"CONDITION = {ref['if']!r}\n\n\n"
                "def run(call):\n"
                "    # Nothing where the condition holds, else the reason.\n"
                "    if conditions.holds(CONDITION, facts(call.doc, "
                "call.row)):\n"
                "        return None\n"
                f"    return reason({why!r}, call.doc, call.row)\n")
    if form != "steps":
        raise BlockError(f"no block: {ref!r}")
    resolve(ref, kind, bricks, space)
    parts, chain = ["import dataclasses\n"], []
    for i, step in enumerate(ref["steps"], 1):
        if shape(step) == "python":
            code = str(step["python"])
        else:
            brick = None
            for one in (kind,) + tuple(k for k in STEP_KINDS if k != kind):
                try:
                    brick = resolve(step, one, bricks, space)
                    break
                except BlockError:
                    continue
            code = python_of(brick) if brick is not None else ""
        if not code:
            return ""
        settings = step.get("settings") or {} if isinstance(step, dict) \
            else {}
        parts.append(f"\ndef _step_{i}():\n"
                     f"    # Step {i}: its own code, which defines run(call).\n"
                     + textwrap.indent(code.rstrip() + "\n", "    ")
                     + "    return run\n\n\n"
                     f"step_{i} = _step_{i}()\n")
        chain.append(f"(step_{i}, {settings!r})")
    last = ("    # The first answer, else the value as it came.\n"
            "    return items[0][1] if items else call.value\n"
            if kind == "name" else
            "    # Every answer that names a term.\n"
            "    return [item for item in items or () if item[0] is not "
            "None]\n")
    parts.append(
        "\n\nSTEPS = (" + ", ".join(chain) + ("," if len(chain) == 1 else "")
        + ")\n\n\n"
        "def _items(result):\n"
        "    # What a step gave, as [(term, value, ...)].\n"
        "    if result is None:\n"
        "        return []\n"
        "    if isinstance(result, (str, int, float)) and not "
        "isinstance(result, bool):\n"
        "        return [(None, result)]\n"
        "    return list(result)\n\n\n"
        "def run(call):\n"
        "    # Each step is called with its settings, from the second on once\n"
        "    # for each value the step before gave.\n"
        "    items = None\n"
        "    for step, settings in STEPS:\n"
        "        here = dataclasses.replace(call, settings=dict(settings))\n"
        "        if items is None:\n"
        "            items = _items(step(here))\n"
        "            continue\n"
        "        out = []\n"
        "        for item in items:\n"
        "            out += _items(step(dataclasses.replace(here, "
        "value=item[1])))\n"
        "        items = out\n" + last)
    return "".join(parts)


# -- every block as a brick ---------------------------------------------------

def _items(result, value) -> list:
    """What one step of a chain gave, as [(term, value, ...)]: a name or a
    turned value is a value with no term yet."""
    if result is None:
        return []
    if isinstance(result, (str, int, float)) and not isinstance(result, bool):
        return [(None, result)]
    return list(result)


def _chain(steps: list, kind: str) -> Callable:
    def run(call: Call):
        items = None
        for brick, settings in steps:
            here = dataclasses.replace(call, settings=dict(settings))
            if items is None:
                items = _items(brick.run(here), here.value)
                continue
            out = []
            for item in items:
                out += _items(brick.run(dataclasses.replace(
                    here, value=item[1])), item[1])
            items = out
        if kind == "name":
            return items[0][1] if items else call.value
        return [item for item in items or () if item[0] is not None]
    return run


def resolve(ref, kind: str, bricks: dict, space: Optional[dict] = None,
            cache: Optional[dict] = None) -> Brick:
    """The brick a block of a drawing is, for a place that wants a block of
    *kind*. BlockError where there is none."""
    key = (id(ref), kind)
    if cache is not None and key in cache and cache[key][0] is ref:
        return cache[key][1]
    form = shape(ref)
    if form == "brick":
        # Named: looked up each time, nothing to keep.
        name = ref.get("brick") if isinstance(ref, dict) else ref
        found = bricks.get(name)
        if found is None or found.kind != kind:
            raise BlockError(f"no {kind} brick {name!r}")
        return found
    if form == "if":
        if kind != "condition":
            raise BlockError(f"a condition stands where a {kind} block "
                             f"stands")
        said = conditions.problems(ref["if"], conditions.GRAPH_SUBJECTS)
        if said:
            raise BlockError(said[0])
        condition, why = ref["if"], str(ref.get("reason") or "condition")

        def run(call: Call, condition=condition, why=why):
            if conditions.holds(condition, facts(call.doc, call.row)):
                return None
            return reason(why, call.doc, call.row)
        found = Brick("if", "condition", conditions.sentence(condition),
                      "a reading", "a reason", run)
    elif form == "steps":
        if kind not in ("object", "name"):
            raise BlockError(f"steps stand on an arrow or spell a name, not "
                             f"in a {kind} block")
        chain = []
        for step in ref["steps"] or ():
            brick = None
            for one in (kind,) + tuple(k for k in STEP_KINDS if k != kind):
                try:
                    brick = resolve(step, one, bricks, space, cache)
                    break
                except BlockError:
                    continue
            if brick is None:
                raise BlockError(f"no step {step!r}")
            settings = step.get("settings") or {} \
                if isinstance(step, dict) else {}
            chain.append((brick, settings))
        if not chain:
            raise BlockError("a chain has one step at least")
        if kind == "object" and chain[-1][0].kind != "object":
            raise BlockError("the last step of an arrow writes the object")
        found = Brick("steps", kind, " → ".join(b.does for b, _ in chain),
                      chain[0][0].takes, chain[-1][0].gives,
                      _chain(chain, kind), per=chain[0][0].per,
                      writes=ref.get("writes") or chain[-1][0].writes)
    elif form == "python":
        if kind not in KINDS:
            raise BlockError(f"no kind {kind!r}")
        found = Brick("python", kind, str(ref.get("does") or "own Python"),
                      "", "", compiled(ref["python"], space or {}),
                      per=ref.get("per") or "row",
                      writes=ref.get("writes") or "")
    else:
        raise BlockError(f"no block: {ref!r}")
    if cache is not None:
        cache[key] = (ref, found)
    return found


def settings_of(ref) -> dict:
    """The settings a block is called with."""
    if isinstance(ref, dict) and shape(ref) in ("brick", "python"):
        return dict(ref.get("settings") or {})
    return {}


# -- an address made of parts ---------------------------------------------------

def part_value(doc, box: dict, part, node=None, row: Optional[dict] = None,
               label: str = "", holds: Optional[Callable] = None):
    """What one part of an address is before it is written: a string token
    as a drawing has always had it (@name, @key, @fact:x, a field whose one
    reading the document gives), or a part {"from", "of", "box", "when"}."""
    if isinstance(part, str):
        if part == "@name":
            return None if node is None else node.name
        if part == "@key":
            return None if node is None else node.key
        if part.startswith("@fact:"):
            return doc.facts.get(part[len("@fact:"):])
        return doc.chosen(part)
    when = part.get("when")
    if when and not conditions.holds(when, facts(doc, row)):
        return None
    source, of = part.get("from") or "reading", part.get("of")
    if source == "reading":
        value = value_at(doc, row, of)
        if part.get("total") and value == f"{NOT_IN_GRAPH}total":
            value = next(((arrow.get("settings") or {}).get("total_class")
                          for arrow in doc.writer.drawing.arrows
                          if arrow.get("from") == of
                          and arrow.get("to") == box["id"]), None)
        return value
    if source == "chosen":
        return doc.chosen(of)
    if source == "name":
        return None if node is None else node.name
    if source == "key":
        return None if node is None else node.key
    if source == "fact":
        return doc.facts.get(of)
    if source == "answer_address":
        return doc.address_of_answer(part.get("box"), value_at(doc, row, of))
    if source == "wording":
        return label
    raise BlockError(f"a part is made from {', '.join(PART_FROM)}, not "
                     f"{source!r}")


def part_written(doc, part, value):
    """A part as the address writes it, None where it is absent."""
    if isinstance(part, str) or value in (None, ""):
        return None if value in (None, "") else value
    form = part.get("form") or "text"
    if form == "class" and not is_class(value, part.get("family") or ""):
        return None
    if form in ("iri", "class"):
        return doc.prefixes.get(part.get("prefix") or "", "") + str(value)
    if form == "fold":
        return doc.fold(value) or None
    return str(value)


def parts_name(doc, box: dict, parts: list, node=None,
               row: Optional[dict] = None, label: str = ""):
    """The words an address is minted from, the parts joined by |, or None
    where a part that refuses to be absent is."""
    out = []
    for part in parts:
        value = part_written(doc, part, part_value(doc, box, part, node, row,
                                                   label))
        if value is None:
            absent = "refuse" if isinstance(part, str) \
                else part.get("absent") or "refuse"
            if absent == "refuse":
                return None
            if absent == "empty":
                out.append("")
            continue
        out.append(value)
    return out


def part_problem(part, fields: set, boxes: dict) -> Optional[str]:
    """Why a part of an address cannot be made, None where it can."""
    if isinstance(part, str):
        return None
    if not isinstance(part, dict):
        return "a part is a field's name or an object"
    for key in part:
        if key not in ("from", "of", "box", "form", "prefix", "family",
                       "total", "when", "absent"):
            return f"a part has no {key!r}"
    source = part.get("from") or "reading"
    if source not in PART_FROM:
        return f"a part is made from {', '.join(PART_FROM)}, not {source!r}"
    if source in ("reading", "chosen", "fact", "answer_address") \
            and not part.get("of"):
        return f"a part from {source} names what of it"
    if source == "answer_address" and part.get("box") not in boxes:
        return f"a part names the box {part.get('box')!r}, which is not drawn"
    if (part.get("form") or "text") not in PART_FORMS:
        return f"a part is written as {', '.join(PART_FORMS)}"
    if (part.get("absent") or "refuse") not in PART_ABSENT:
        return f"an absent part is {', '.join(PART_ABSENT)}"
    if part.get("when"):
        said = conditions.problems(part["when"], conditions.GRAPH_SUBJECTS)
        if said:
            return said[0]
    return None


def names_in(ref) -> list:
    """The keys of a reading a block reads: the paths of its conditions'
    rows about the reading, the `of` of its parts, its steps' and its
    settings' strings."""
    out: list = []

    def strings(value) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for one in value.values():
                strings(one)
        elif isinstance(value, (list, tuple)):
            for one in value:
                strings(one)

    if not isinstance(ref, dict):
        return out
    form = shape(ref)
    if form == "if":
        for row in conditions._rows(ref["if"])[1] \
                if not conditions.problems(ref["if"]) else ():
            if isinstance(row, dict) and row.get("of") == "reading":
                out.append(str(row.get("is") or "").split(".")[0])
    elif form == "steps":
        for step in ref["steps"] or ():
            out += names_in(step)
    strings(ref.get("settings"))
    return out
