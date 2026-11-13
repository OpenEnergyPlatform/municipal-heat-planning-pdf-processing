"""
flow.py: How a document is read, as a drawing of boxes and frames, and the
numbers that bound it, read from a file of the profile.

    <profile folder>/flow.json

Since 2026-11-11 (owner decisions 2026-11-10 evening, "Freie Ablaufgrafik")
the file is the drawing itself, a tree: boxes in their order, frames with
their boxes, an "if" with its ways side by side. The run does exactly what
it says (`engine.Engine`); there is no second order in the code. Each box is
a kind of the library (`blocks.LIBRARY`): what it takes and gives, its
settings, where it has to stand. What a box does with an answer stays code.

    {"numbers": {"piece_lines": 8, ...},
     "flow": [{"id": "document", "box": "document"},
              ...,
              {"id": "values", "each": "value", "order": "names_first",
               "together": true, "steps": [...]},
              {"id": "write", "box": "write"}]}

A box: {"id", "box": kind, "set": {setting: value}, "own": {setting: whole
number}, "rules": {name: value}, "when": condition, "off": true}. "own"
gives a number setting a value of its own ("only here") instead of the
named number. A frame: {"id", "each": what, "which", "when", "together",
"order", "rules", "steps"}, {"id", "round": {"most": n} or {"supply":
true}, "stop": condition, "rules", "steps"}, {"id", "if": [{"when":
condition, "steps"}], "else": steps, "rules"}. Conditions are
`conditions.py`'s.

"rules" gives a rule (`docpipe.rules`) or a number of the flow a value of
its own while the box runs, or while anything in the frame runs (owner
2026-11-11: "alles soll anpassbar sein"): the step's own value, then the
frames' from the inside out, then the setting of the start, then the file.
Only a rule the step reads may be set at it (`Rule.steps`,
`Number.steps`).

The default profile writes the whole file: every number (`NUMBERS`) and the
drawing. A profile that extends it writes the numbers it sets differently,
laid over the default's number by number (`load`), and may write a drawing
of its own, which is then the whole drawing. A setting of the run wins over
the file for the numbers that have one (`Number.env`), never over a box's
own value.

Before a drawing is kept, `problems` says everything the run could not do
with it (owner decisions 2026-11-10, section 11 of the plan): a box where it
cannot stand (a question of a coordinate outside "each coordinate", a find
outside "each piece"), a round that may not end, a frame of coordinates
without a state, a condition that cannot be evaluated where it stands, the
order the run needs (the document first, its pieces before anything shows
them, writing before computing). A file with a problem is refused with it.

Nothing here decides whether a harvest is current. A stamp names, in the
entry of each pass that asked a model, the numbers the pass read with and
the sha256 of the flow's files (`runner.producer`, `Numbers.sha256`), for a
reader, as it names every prompt (owner decision 2026-09-10).

Author: Felix Vossel
"""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import blocks, conditions

FILE = "flow.json"
# The file every flow starts from.
DEFAULT_NAME = "default"
DEFAULT = Path(__file__).resolve().parent.parent / "builtin" / DEFAULT_NAME \
    / FILE


class FlowError(ValueError):
    """A flow a run cannot read. It names the file or the setting."""


@dataclass(frozen=True)
class Number:
    """One number the reading takes."""
    name: str
    least: int
    help: str
    env: Optional[str] = None       # the setting that wins over the file
    part: Optional[int] = None      # its place where the setting lists several
    steps: tuple = ()               # the kinds of steps that read it


# Every number the reading takes from the flow, in the order a file writes
# them. What each is by default stands in the default profile's file and
# nowhere in the code.
NUMBERS = (
    Number("piece_lines", 1,
           "The most lines one chunk has. The document is cut into chunks of "
           "this size, and a request reads one chunk at a time. A table's "
           "head is shown with each of its chunks. A larger number sends "
           "fewer, longer chunks; a smaller number sends more, shorter "
           "chunks and more requests."),
    Number("title_page_lines", 1,
           "The number of lines from the document's first page that a "
           "request shows as its title page. The title page tells the model "
           "which document it reads. "
           "A larger number shows more of the first page in every request "
           "that uses it."),
    Number("headings", 0,
           "The number of headings a request shows above the line it asks "
           "about, the nearest heading last. Headings tell the model which "
           "section a line belongs to. A larger number shows more of the "
           "outline above the line; 0 shows no heading."),
    Number("list_meanings", 0,
           "The longest list that is shown with what each entry means. A "
           "longer list shows only the names of its entries. A list whose "
           "entries belong to groups is then asked in two steps, first the "
           "group, then the entry. A larger number explains more lists "
           "entry by entry and makes their requests longer."),
    Number("search_pieces", 1,
           "The number of chunks a search shows when it looks for an open "
           "dimension or for a field asked once per document. A larger "
           "number searches further down the ranking and finds more, at the "
           "price of more requests. A smaller number is cheaper and can "
           "miss a value.", "EXTRACT_SEARCH_PIECES"),
    Number("search_tables", 0,
           "The share of a search's chunks that are the best chunks of "
           "tables; these are taken first. The shares of tables, figures and "
           "text are scaled to the number of chunks of the search, and the "
           "rest are the best chunks of any kind. A larger share favours "
           "tables.",
           "EXTRACT_SEARCH_SHARES", 0),
    Number("search_figures", 0,
           "The share of a search's chunks that are the best chunks of "
           "figures; these are taken first, as for tables. A larger share "
           "favours figures and leaves fewer places for the other kinds. A "
           "share of 0 takes no figure first.", "EXTRACT_SEARCH_SHARES", 1),
    Number("search_text", 0,
           "The share of a search's chunks that are the best chunks of "
           "running text; these are taken first, as for tables. A larger "
           "share favours text and leaves fewer places for the other kinds. "
           "A share of 0 takes no text first.", "EXTRACT_SEARCH_SHARES", 2),
    Number("search_per_request", 1,
           "The number of chunks of a search that one request shows. A "
           "search with more chunks than this is split into several "
           "requests. A larger number needs fewer requests, each longer; a "
           "smaller number needs more requests, each shorter.",
           "EXTRACT_SEARCH_CHUNKS"),
    Number("listed_field_factor", 1,
           "The factor by which a search for a field asked once per "
           "document shows more chunks when the field's values come from a "
           "list. Such a field has to be found among many possible entries. "
           "A larger factor searches more chunks for it; 1 searches as many "
           "as for any other field."),
    Number("follow_ups", 0,
           "How often a request is asked again when its answer failed a "
           "check. Each time the request shows the answer and what failed. "
           "A larger number gives the model more chances to correct a "
           "value; 0 never asks again."),
    Number("replies", 1,
           "How many answers in the wrong form a request accepts before it "
           "is left without an answer. A request the server refuses is asked "
           "as often. A larger number is more patient with a model that "
           "answers badly, at the price of more requests.",
           "EXTRACT_MAX_RETRIES"),
)
# Which steps read each number (`rules.step_kind`), as for the rules
# (`rules.STEPS`).
# The steps that send a request the model answers: each has its own value of
# the numbers that bound how it is asked again (plan 2026-11-11, 5.2).
ASKING = ("transcribe", "sentences", "docfield", "works", "find", "coord",
          "quantity", "work_coordinate", "phrase", "search", "last_year",
          "names", "about", "compute", "list")
def _with_general(steps: tuple, searching: bool) -> tuple:
    from ..ruleset.kit import with_general
    return with_general(steps, searching)


# The numbers of the search: how many chunks it gives and of which kind.
SEARCH_NUMBERS = ("search_pieces", "search_tables", "search_figures",
                  "search_text", "listed_field_factor")


STEPS = {
    "piece_lines": ("split",),
    "title_page_lines": ("document",),
    "headings": ("split", "find", "coord", "phrase", "search",
                 "work_coordinate", "works", "last_year", "about"),
    "list_meanings": ASKING + ("order", "each field", "each value"),
    "search_pieces": ("order",),
    "search_tables": ("order",),
    "search_figures": ("order",),
    "search_text": ("order",),
    "search_per_request": ("docfield", "search", "round"),
    "listed_field_factor": ("order",),
    "follow_ups": ASKING + ("each value",),
    "replies": ASKING + ("order",),
}
# A general step reads the numbers of the steps whose work it does
# (ruleset/kit.py STANDS_FOR).
NUMBERS = tuple(dataclasses.replace(
    number, steps=_with_general(STEPS.get(number.name, ()),
                                number.name in SEARCH_NUMBERS))
    for number in NUMBERS)
BY_NAME = {number.name: number for number in NUMBERS}
FRAME_KEYS = {"each": ("id", "each", "which", "when", "together", "order",
                       "rules", "steps", "off", "note", "list", "as"),
              "round": ("id", "round", "stop", "rules", "steps", "off",
                        "note"),
              "if": ("id", "if", "else", "rules", "off", "note")}
BOX_KEYS = ("id", "box", "preset", "set", "own", "rules", "when", "off",
            "note")


@dataclass(frozen=True)
class Numbers:
    """The numbers one run reads with, and where each comes from."""
    piece_lines: int
    title_page_lines: int
    headings: int
    list_meanings: int
    search_pieces: int
    search_tables: int
    search_figures: int
    search_text: int
    search_per_request: int
    listed_field_factor: int
    follow_ups: int
    replies: int
    # name -> where its value comes from: "flow.json of <profile>", or what
    # set the setting that won over the file (`settings.origin`).
    origin: dict = field(default_factory=dict, compare=False, repr=False)
    # Of the flow's file as laid over each other, drawing and numbers; the
    # settings that won are not in it.
    sha256: str = field(default="", compare=False, repr=False)
    # The names of the numbers a setting of the run set.
    set_by_run: frozenset = field(default=frozenset(), compare=False,
                                  repr=False)

    def shares(self) -> dict:
        """{kind of passage: its share of a search's pieces}."""
        return {"table": self.search_tables, "figure": self.search_figures,
                "section": self.search_text}

    def as_dict(self) -> dict:
        return {number.name: getattr(self, number.name)
                for number in NUMBERS}


if tuple(f.name for f in dataclasses.fields(Numbers)
         if f.name not in ("origin", "sha256", "set_by_run")) \
        != tuple(number.name for number in NUMBERS):
    raise AssertionError("flow.Numbers and flow.NUMBERS name different "
                         "numbers")


@dataclass(frozen=True)
class Flow:
    """A profile's flow as its files say it, no setting applied."""
    numbers: dict                   # name -> value, in the order of NUMBERS
    owners: dict                    # name -> the profile whose file says it
    tree: list                      # the drawing
    files: tuple                    # ((profile name, path)), nearest first
    sha256: str
    tree_from: str = ""             # the profile whose file draws it


def number(numbers: Numbers, name: str) -> int:
    """The number *name* of the flow as the step that runs reads it: its
    own value or that of a frame around it (`rules.STEP`), else the run's
    (*numbers*). The one way a number of the flow is read."""
    from .. import rules
    own, value = rules.stepped_value(name)
    return int(value) if own else int(getattr(numbers, name))


# -- walking a drawing --------------------------------------------------------

def kind_of(node: dict) -> str:
    """"box", "each", "round" or "if"."""
    for key in ("box", "each", "round", "if"):
        if key in node:
            return key
    return ""


def children(node: dict) -> list:
    """[(label, steps)] of a frame: its steps, or each way of an "if"."""
    kind = kind_of(node)
    if kind in ("each", "round"):
        return [("steps", node.get("steps") or [])]
    if kind == "if":
        out = [(f"way {i}", way.get("steps") or [])
               for i, way in enumerate(node.get("if") or [], start=1)
               if isinstance(way, dict)]
        if "else" in node:
            out.append(("else", node.get("else") or []))
        return out
    return []


def walk(tree: list, frames: tuple = ()):
    """(node, its frames outermost first) of every node of *tree*, in
    order."""
    for node in tree:
        if not isinstance(node, dict):
            continue
        yield node, frames
        for _label, steps in children(node):
            yield from walk(steps, frames + (node,))


def on(tree: list):
    """(node, its frames outermost first) of every node of *tree* that
    takes part in a run, in order: one that is off, or stands in a frame
    that is off, is not asked, checked or counted anywhere."""
    for node, frames in walk(tree):
        if not node.get("off") and not any(f.get("off") for f in frames):
            yield node, frames


def boxes(tree: list) -> list:
    return [node for node, _ in walk(tree) if kind_of(node) == "box"]


def asked(tree: list) -> set:
    """The requests the boxes of *tree* ask, of the boxes that are on."""
    out = set()
    for node, _frames in on(tree):
        if kind_of(node) != "box":
            continue
        asks = blocks.asks_of(node)
        if asks:
            out.add(asks)
    return out


def box_on(tree: list, kind: str) -> bool:
    """Does the top step of *kind* (`rules.step_kind`) stand in *tree* and
    is it on? The steps the runner does after the reading (compute,
    catalogue) run only so."""
    from ..rules import step_kind
    return any("box" in node and step_kind(node) == kind
               and not node.get("off")
               for node in tree if isinstance(node, dict))


def compute_on(tree: list) -> bool:
    """Is the calculation after the reading on in *tree*?"""
    return box_on(tree, "compute")


# -- what a drawing may say ---------------------------------------------------

def _nearest(name, known) -> str:
    close = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def problem(name: str, value) -> Optional[str]:
    """Why *value* is not the number *name* of the flow, None where it
    is: *name* is none of its numbers, or *value* no whole number of at
    least its least value."""
    number = BY_NAME.get(name)
    if number is None:
        return (f"{name!r} is no number of the flow"
                f"{_nearest(name, BY_NAME)}")
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{name} must be a whole number, not {value!r}"
    if value < number.least:
        return f"{name} must be at least {number.least}, not {value}"
    return None


def checked(where, name: str, value) -> int:
    """*value* as the number *name* of the flow, FlowError where it is
    none (`problem`). *where* names the file in what is said about it."""
    said = problem(name, value)
    if said is not None:
        raise FlowError(f"{where}: {said}")
    return value


def availability(tree: list) -> dict:
    """{id(node): the variables there before *node* runs} of every step of
    *tree* (owner decision 2026-11-12: what may stand where follows from
    the inputs and outputs alone): what the run starts with, the item of
    each frame around the step, and what the steps before it gave. An
    output that lasts for the whole document (`variables.lasting`) is
    there for every step after the one that made it; any other only in the
    item it was made for, which a round's turn or an if's way shares with
    the steps around it. A step that is off gives nothing."""
    from . import variables
    out: dict = {}
    lasting: set = set(variables.START)

    def go(steps, local: set) -> set:
        local = set(local)
        for node in steps if isinstance(steps, list) else []:
            if not isinstance(node, dict):
                continue
            out[id(node)] = frozenset(local | lasting)
            if node.get("off"):
                continue
            kind = kind_of(node)
            if kind == "box":
                for name in outputs_of(node):
                    (lasting if lasting_of(node, name) else local).add(name)
            elif kind == "each":
                item = node.get("as") or "item" if node.get("each") == "list" \
                    else variables.ITEMS.get(node.get("each"), (None, None))[0]
                items = {item} if item else set()
                # A field asked once per document is a fact of it; a value
                # is a value of its field (what the frame holds besides its
                # item, `engine.Engine.items`).
                if node.get("each") == "field" \
                        and node.get("which", "all") == "once":
                    items.add("fact")
                if node.get("each") == "value":
                    items.add("field")
                go(node.get("steps") or [], local | items)
            elif kind == "round":
                local |= go(node.get("steps") or [], local | {"round"}) \
                    - {"round"}
            elif kind == "if":
                made: set = set()
                for _label, steps in children(node):
                    made |= go(steps, local)
                local |= made
        return local

    go(tree, set())
    return out


# The general steps (`general`, owner decision 2026-11-12): what they take
# and give is named by their settings.
GENERAL = ("ask", "retrieve", "rerank", "set", "filter", "merge", "python")


def _root(path) -> Optional[str]:
    return str(path).split(".")[0] if isinstance(path, str) and path \
        else None


def available_by_id(tree: list) -> dict:
    """{id of a step: [the variables there before it], in order} of every
    step of *tree*, for the page's choice of a variable."""
    avail = availability(tree) if isinstance(tree, list) else {}
    return {node.get("id"): sorted(avail.get(id(node), ()))
            for node, _frames in walk(tree if isinstance(tree, list) else [])
            if isinstance(node.get("id"), str)}


def outputs_of(node: dict) -> list:
    """The variables a box gives: its kind's, for a step of "Ask the model"
    its target's, and for a general step the ones its settings name."""
    kind = blocks.LIBRARY.get(node.get("box"))
    if kind is None:
        return []
    sets = node.get("set") or {}
    if not isinstance(sets, dict):
        return []
    if kind.type == "ask":
        from . import targets
        from .general import parts_of
        into = parts_of(node)["into"]
        target = targets.TARGETS.get(into.get("to"))
        if into.get("to") == "var":
            return ["answer", into.get("var") or node.get("id")]
        return list(target.outputs) if target is not None else []
    if kind.type in ("retrieve", "rerank", "filter", "merge"):
        default = "hits" if kind.type == "retrieve" else node.get("id")
        return [sets.get("into") or default]
    if kind.type == "set":
        return [sets["name"]] if isinstance(sets.get("name"), str) else []
    if kind.type == "python":
        return [one for one in sets.get("outputs") or ()
                if isinstance(one, str)]
    return list(kind.outputs)


def inputs_of(node: dict) -> tuple:
    """What a box takes (`variables.wanted`): its kind's, and for a general
    step the variables its settings name."""
    kind = blocks.LIBRARY.get(node.get("box"))
    if kind is None:
        return ()
    sets = node.get("set") or {}
    if not isinstance(sets, dict) or kind.type not in GENERAL:
        return kind.inputs
    if kind.type == "ask":
        from . import targets
        from .general import parts_of
        parts = parts_of(node)
        target = targets.TARGETS.get(parts["into"].get("to"))
        given = set(target.gives) if target is not None else set()
        paths = [one.get("from") for one in parts["inputs"] or ()
                 if isinstance(one, dict)
                 and _root(one.get("from")) not in given]
    elif kind.type == "retrieve":
        paths = [sets.get("query")]
    elif kind.type == "rerank":
        paths = [sets.get("list"), sets.get("query")]
    elif kind.type in ("set", "filter"):
        paths = [sets.get("from" if kind.type == "set" else "list")]
    else:
        paths = list(sets.get("lists" if kind.type == "merge"
                              else "inputs") or ())
    return tuple(dict.fromkeys(root for root in map(_root, paths) if root))


def lasting_of(node: dict, name: str) -> bool:
    """Does the variable *name* that *node* gives last for the whole
    document?"""
    from . import variables
    kind = blocks.LIBRARY.get(node.get("box"))
    if kind is None or kind.type not in GENERAL:
        return variables.lasting(name)
    if name == "values":
        return True
    if name == "answer":
        return False
    sets = node.get("set") or {}
    if kind.type == "ask":
        from .general import parts_of
        return bool(parts_of(node)["into"].get("lasting"))
    return bool(sets.get("lasting"))


def makers(tree: list) -> dict:
    """{variable: [the labels of the boxes that are on and give it]}."""
    out: dict = {}
    for node, _frames in on(tree):
        if kind_of(node) != "box":
            continue
        kind = blocks.LIBRARY.get(node.get("box"))
        for name in outputs_of(node):
            out.setdefault(name, []).append(kind.label)
    return out


class _Check:
    """The problems of one drawing, each with the id of its node."""

    def __init__(self, known: Optional[dict] = None):
        self.out: list = []
        self.ids: dict = {}
        self.known = known          # the rules of the profile's line
        # What is there before each step, and which boxes give what.
        self.avail: dict = {}
        self.makers: dict = {}
        self.profile = None         # whose boxes the drawing may take

    def inputs(self, node: dict, label: str, inputs: tuple) -> None:
        """The inputs of a step: each one there before it, an optional one
        where a step of the flow gives it (owner decision 2026-11-12)."""
        from . import variables
        there = self.avail.get(id(node))
        if there is None:
            return
        for spec in inputs:
            names, optional = variables.wanted(spec)
            if any(name in there for name in names):
                continue
            words = " or ".join(variables.label(name) for name in names)
            given = [maker for name in names
                     for maker in self.makers.get(name, ())]
            if optional:
                if given:
                    self.say(node, f"{label} stands after {given[0]}: it "
                             f"takes {words} where the flow gives it")
                continue
            if given:
                self.say(node, f"{label} takes {words}, which "
                         f"{given[0]} gives only after it or in another "
                         f"frame")
            else:
                self.say(node, f"{label} takes {words}, and no step of the "
                         f"flow gives it")

    def say(self, node, message: str) -> None:
        ident = node.get("id") if isinstance(node, dict) else None
        self.out.append({"id": ident if isinstance(ident, str) else None,
                         "message": message})


def _innermost(frames: tuple, kind: str = "each") -> Optional[dict]:
    return next((f for f in reversed(frames) if kind_of(f) == kind), None)


def _eaches(frames: tuple) -> list:
    return [f.get("each") for f in frames if kind_of(f) == "each"]


def _vars(check, node: dict) -> set:
    """What a condition at *node* can say of variables: every variable
    there before it (`conditions.VAR`)."""
    return {"var"} | {f"var:{name}"
                      for name in check.avail.get(id(node), ())}


def _known(frames: tuple, before: list) -> set:
    """The things a condition can be about at a place inside *frames*,
    after the boxes *before* of its own item."""
    out = {"document", "run"}
    eaches = _eaches(frames)
    if any(e in ("field", "piece", "value", "coordinate") for e in eaches):
        out.add("field")
    if any(e in ("value", "coordinate") for e in eaches):
        out.add("value")
    if "piece" in eaches:
        out.add("chunk")
    if "coordinate" in eaches:
        out |= {"coordinate", "pieces", "chunk"}
    if any(kind_of(f) == "round" for f in frames):
        out.add("round")
    for node in before:
        # A box that is off is not there: it gives nothing.
        kind = blocks.box_of(node) \
            if kind_of(node) == "box" and _on(node) else None
        if kind is not None and kind.asks:
            out |= {"answer", "quote"}
        if kind is not None and kind.gives == "supply":
            out.add("pieces")
    return out


def _value_problem(box: blocks.Box, setting: blocks.Setting, value,
                   where: set) -> Optional[str]:
    if setting.kind == blocks.SWITCH and not isinstance(value, bool):
        return f"{setting.label} is yes or no, not {value!r}"
    if setting.kind == blocks.CHOICE and value not in setting.choices:
        return (f"{setting.label} is one of {', '.join(setting.choices)}, "
                f"not {value!r}")
    if setting.kind == blocks.TEXT and not (isinstance(value, str)
                                            and value.strip()):
        return f"{setting.label} must be a text, not empty"
    if setting.kind == blocks.CONDITION:
        said = conditions.problems(value, where)
        if said:
            return f"{setting.label}: {said[0]}"
    if setting.kind in (blocks.NUMBER, blocks.COUNT, blocks.RULE):
        return f"{setting.label} is a number of the flow; give it under own"
    return _general_problem(setting, value)


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")


def _general_problem(setting: blocks.Setting, value) -> Optional[str]:
    """Why *value* is no value of a setting of a general step
    (`general`), None where it is one."""
    from . import general
    label = setting.label
    if setting.kind == blocks.PROMPT:
        if isinstance(value, dict):
            return None if isinstance(value.get("text"), str) \
                and value["text"].strip() else \
                f"{label}: a text of its own is empty"
        if isinstance(value, str) and "/" in value.strip():
            return None
        return f"{label} is the id of a prompt (stage/name) or a text"
    if setting.kind == blocks.INPUTS:
        if not isinstance(value, list):
            return f"{label} is a list of inputs"
        keys = set()
        from . import shows
        for one in value:
            if not isinstance(one, dict) or set(one) - {
                    "key", "from", "show", "when", "first_only",
                    "several_only"}:
                return (f"{label}: each input has key, from and show, and "
                        f"may have when, first_only and several_only")
            if not _NAME.match(str(one.get("key") or "")):
                return f"{label}: {one.get('key')!r} is no key"
            if one["key"] in keys:
                return f"{label}: the key {one['key']} stands twice"
            keys.add(one["key"])
            if not _PATH.match(str(one.get("from") or "")):
                return f"{label}: {one.get('from')!r} is no variable"
            if one.get("show", "as_is") not in shows.SHOWS:
                return (f"{label}: shows as one of "
                        f"{', '.join(shows.SHOWS)}")
        return None
    if setting.kind == blocks.SCHEMA:
        from . import forms
        said = forms.problem(value)
        return f"{label}: {said}" if said else None
    if setting.kind == blocks.INTO:
        from . import targets
        if not isinstance(value, dict) or set(value) - {
                "to", "var", "lasting", "field", "keep", "where"}:
            return (f"{label} is a target (to) with what it takes: a "
                    f"variable (var, lasting), a field (field, keep), a "
                    f"place (where)")
        if "to" in value and value["to"] not in targets.TARGETS:
            return f"{label}: there is no target {value['to']!r}"
        if value.get("keep") not in (None, "now", "gathered"):
            return f"{label}: values are kept now or gathered"
        if value.get("where") not in (None, "own", "hits"):
            return f"{label}: a dimension is asked at its own place or " \
                f"over the hits"
        if "field" in value:
            return None if isinstance(value["field"], str) \
                and value["field"] else f"{label}: which field"
        if value.get("to") not in (None, "var"):
            return None
        if not value.get("var"):
            return None             # the step's id names the variable
        if not _NAME.match(str(value.get("var") or "")):
            return f"{label}: {value.get('var')!r} is no name of a variable"
        return None
    if setting.kind == blocks.VARNAME:
        return None if _NAME.match(str(value)) else \
            f"{label}: {value!r} is no name of a variable"
    if setting.kind == blocks.PATH:
        return None if _PATH.match(str(value)) else \
            f"{label}: {value!r} is no variable"
    if setting.kind in (blocks.PATHS, blocks.VARNAMES):
        pattern = _PATH if setting.kind == blocks.PATHS else _NAME
        if not isinstance(value, list) or not value:
            return f"{label} names one at least"
        wrong = [one for one in value if not pattern.match(str(one))]
        return f"{label}: {wrong[0]!r} is no variable" if wrong else None
    if setting.kind == blocks.JSON:
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return f"{label} is a value in JSON"
        return None
    if setting.kind == blocks.CODE:
        said = general.python_problem(value)
        return f"{label}: {said}" if said else None
    if setting.kind == blocks.MULTI:
        if not isinstance(value, list):
            return f"{label} is a list of choices"
        wrong = [one for one in value if one not in setting.choices]
        return (f"{label} is some of {', '.join(setting.choices)}, not "
                f"{wrong[0]!r}") if wrong else None
    return None


# What a general step cannot do without.
NEEDED = {"retrieve": ("query",),
          "rerank": ("list", "query", "into"), "set": ("name",),
          "filter": ("list", "keep", "into"), "merge": ("lists", "into"),
          "python": ("code", "outputs")}


def _given(node: dict) -> set:
    """The variables the target of a step of "Ask the model" gives its
    request (`targets.Target.gives`), for its conditions."""
    from . import targets
    target = targets.TARGETS.get(blocks.target_of(node))
    return {f"var:{name}" for name in target.gives} if target else set()


def _ask_parts(check: _Check, node: dict, where: set) -> None:
    """The parts of a step of "Ask the model", as its preset and its own
    values make them: a target there is, an answer form it takes, inputs
    whose conditions can be told where it stands."""
    from . import forms, targets
    from .general import parts_of
    parts = parts_of(node)
    target = targets.TARGETS.get(parts["into"].get("to"))
    if target is None:
        check.say(node, f"there is no target {parts['into'].get('to')!r}"
                  f"{_nearest(parts['into'].get('to'), targets.TARGETS)}")
        return
    said = forms.problem(parts["reply"])
    # A target that names the forms it reads takes no other, named or of
    # the step's own: it could read none of its answers.
    taken = " or ".join(forms.FORMS[name][0] for name in target.forms
                        if name in forms.FORMS)
    if said:
        check.say(node, f"form of the answer: {said}")
    elif target.forms and not isinstance(parts["reply"], str):
        check.say(node, f"{target.label} takes an answer as {taken}, not "
                  f"a form of its own")
    elif target.forms and parts["reply"] not in target.forms:
        check.say(node, f"{target.label} takes an answer as {taken}, not "
                  f"as {forms.FORMS[parts['reply']][0]}")
    if target.nested and not blocks.is_attached(node):
        check.say(node, f"{target.label} is asked inside the answer of "
                  f"another question: give the step a preset that stands "
                  f"after one")
    if target.apart:
        for one in parts["inputs"] or ():
            if isinstance(one, dict) \
                    and _root(one.get("from")) not in target.gives:
                check.say(node, f"input {one.get('key')}: {target.label} "
                          f"is asked apart from the reading, from "
                          f"{' and '.join(target.gives)} alone")
    for one in parts["inputs"] or ():
        if isinstance(one, dict) and one.get("when") is not None:
            said = conditions.problems(one["when"], where)
            if said:
                check.say(node, f"the input {one.get('key')}: {said[0]}")


def _kinds_in(node: dict) -> set:
    """The kinds of steps (`rules.step_kind`) *node* is or holds."""
    from .. import rules
    found = {rules.step_kind(node)}
    for _label, steps in children(node):
        for child, _frames in walk(steps):
            found.add(rules.step_kind(child))
    return found


SHARES = ("search_tables", "search_figures", "search_text")


def _search_values(check: _Check, node: dict, given: dict) -> None:
    """The values *given* at *node* for what a search shows: the three
    shares, when all three are given, must leave a kind of chunk to take
    first (`addressed.shares_problem`), and the chunks a request shows must
    each have a letter to be addressed by (`units.places_problem`)."""
    from . import addressed, units
    if all(name in given and isinstance(given[name], int)
           for name in SHARES):
        said = addressed.shares_problem({name: given[name]
                                         for name in SHARES})
        if said:
            check.say(node, said)
    per = given.get("search_per_request")
    if isinstance(per, int) and not isinstance(per, bool):
        said = units.places_problem(per)
        if said:
            check.say(node, said)


def _rules_of(check: _Check, node: dict) -> None:
    """The values a box or frame sets for itself: each a rule or a number
    of the flow, read by the step or by a step in the frame, and a value
    its rule allows."""
    own = node.get("rules")
    if own is None:
        return
    if not isinstance(own, dict):
        check.say(node, "rules is an object: rule -> value")
        return
    from .. import rules
    known = check.known if check.known is not None else rules.BY_NAME
    kinds = _kinds_in(node)
    for name, value in own.items():
        one = known.get(name) or BY_NAME.get(name)
        if one is None:
            check.say(node, f"{name!r} is no rule and no number of the "
                      f"flow{_nearest(name, list(known) + list(BY_NAME))}")
            continue
        said = (rules.problem(name, value, known) if name in known
                else problem(name, value))
        if said:
            check.say(node, said)
            continue
        if not kinds & set(one.steps):
            readers = ', '.join(one.steps) or 'no step (the run reads it)'
            check.say(node, f"{name} is not read here: it is read by "
                      f"{readers}")
    _search_values(check, node, own)


def _box(check: _Check, node: dict, frames: tuple, before: list,
         top: bool) -> None:
    kind = blocks.LIBRARY.get(node.get("box"))
    if kind is None:
        check.say(node, f"there is no box {node.get('box')!r}"
                  f"{_nearest(node.get('box'), blocks.LIBRARY)}")
        return
    if "preset" in node:
        from .presets import PRESETS
        if node.get("box") != "ask":
            check.say(node, "only a step of \"Ask the model\" has a preset")
            return
        if blocks.preset_of(node) is None:
            check.say(node, f"there is no preset {node.get('preset')!r}"
                      f"{_nearest(node.get('preset'), PRESETS)}")
            return
    kind = blocks.box_of(node)
    if kind.flow:
        check.say(node, f"{kind.label} is a step of a follow-up pass "
                  f"(`flows/`), and this flow reads documents: it has no "
                  f"use for the steps that work on a harvest that is "
                  f"written")
        return
    if not blocks.offered(kind, check.profile):
        check.say(node, f"{kind.label} is a step of the profile "
                  f"{kind.profile} (profiles/{kind.profile}/blocks.py), "
                  f"and this profile neither is it nor builds on it")
        return
    for key in node:
        if key not in BOX_KEYS:
            check.say(node, f"a box has no key {key!r}")
    _rules_of(check, node)
    if node.get("off") and (kind.fixed or not kind.switch):
        check.say(node, f"{kind.label} cannot be off: {kind.fixed}")
    if kind.top and not top:
        check.say(node, f"{kind.label} stands at the top of the drawing "
                  f"only")
    eaches = _eaches(frames)
    inner = eaches[-1] if eaches else None
    # Where a box may stand follows from what it takes (owner decision
    # 2026-11-12); a question that shows a supply a few chunks at a time
    # stands in a round.
    if _on(node, frames):
        check.inputs(node, kind.label, inputs_of(node))
    if "round" in kind.needs and not any(kind_of(f) == "round"
                                         for f in frames):
        check.say(node, f"{kind.label} stands in a round: it shows a "
                  f"supply a few pieces at a time")
    if kind.type == "ask" and inner == "field" \
            and blocks.target_of(node) == "values":
        from .general import parts_of
        frame = _innermost(frames)
        if frame.get("which", "all") == "pieces" \
                and parts_of(node)["into"].get("keep") == "gathered":
            check.say(node, "a field read in pieces is asked by finds, "
                      "not as a field of the document")
    where = _known(frames, before) | _vars(check, node)
    if kind.type == "filter":
        where = where | {"var:item"}
    if kind.type == "ask":
        from . import targets
        target = targets.TARGETS.get(blocks.target_of(node))
        if target is not None and target.facts:
            # A step asked once a figure, before any chunk is cut, knows
            # only the figure's own properties.
            where = set(target.facts)
    sets = node.get("set") or {}
    own = node.get("own") or {}
    if not isinstance(sets, dict) or not isinstance(own, dict):
        check.say(node, "set and own are objects: setting -> value")
        return
    by_key = {s.key: s for s in kind.settings}
    if kind.type == "ask":
        where = where | _given(node)
    for key, value in sets.items():
        setting = by_key.get(key)
        if setting is None:
            check.say(node, f"{kind.label} has no setting {key!r}"
                      f"{_nearest(key, by_key)}")
            continue
        said = _value_problem(kind, setting, value,
                              {"line"} if kind.type == "split"
                              and setting.kind == blocks.CONDITION
                              else where | ({"answer", "quote"}
                                            if kind.type == "check"
                                            else set()))
        if said:
            check.say(node, said)
    for key, value in own.items():
        setting = by_key.get(key)
        if setting is None or setting.kind != blocks.NUMBER:
            check.say(node, f"{kind.label} has no number {key!r} to give a "
                      f"value of its own")
            continue
        said = problem(setting.number, value)
        if said:
            check.say(node, said)
    _search_values(check, node, {by_key[k].number: v for k, v in own.items()
                                 if k in by_key
                                 and by_key[k].kind == blocks.NUMBER})
    if kind.type == "check":
        for key in ("name", "refuse", "sentence"):
            if key not in sets:
                check.say(node, f"a check needs its {key}")
    if kind.type == "ask":
        _ask_parts(check, node, where)
    for key in NEEDED.get(kind.type, ()):
        setting = next((x for x in kind.settings if x.key == key), None)
        # a setting with a standard needs no value of its own
        if key not in sets and (setting is None or setting.default is None):
            label = setting.label if setting is not None else key
            check.say(node, f"{kind.label} needs its {label}")
    if kind.type == "set" and "from" not in sets and "value" not in sets:
        check.say(node, f"{kind.label} takes the value of a variable or a "
                  f"value of its own")
    if kind.attached:
        previous = [n for n in before if kind_of(n) == "box"]
        chain = list(reversed(previous))
        while chain and blocks.is_attached(chain[0]):
            chain.pop(0)
        asking = blocks.asks_of(chain[0]) if chain else None
        if not before or kind_of(before[-1]) != "box" \
                or asking not in kind.attached:
            check.say(node, f"{kind.label} stands right after a question "
                      f"that reads a value or coordinate "
                      f"({', '.join(kind.attached)})")
    if "when" in node:
        said = conditions.problems(node["when"], where)
        if said:
            check.say(node, f"only when: {said[0]}")


def _on(node: dict, frames: tuple = ()) -> bool:
    """Is *node* there for the run: neither it nor a frame around it off?
    A box that is off is not there for any check of the drawing."""
    return not node.get("off") and not any(f.get("off") for f in frames)


def _supply_before(before: list) -> bool:
    return any(kind_of(n) == "box" and _on(n)
               and blocks.LIBRARY.get(n.get("box")) is not None
               and blocks.LIBRARY[n["box"]].gives == "supply"
               for n in before)


def hits_question(node: dict) -> Optional[str]:
    """The target of a question that shows the next search hits a few a
    request (an input shown as "next_chunks"): "dimension" for a search of
    a value's dimension, "values" for a field of the whole document; None
    for any other step."""
    if kind_of(node) != "box" or node.get("box") != "ask":
        return None
    from .general import parts_of
    parts = parts_of(node)
    if not any(isinstance(one, dict) and one.get("show") == "next_chunks"
               for one in parts["inputs"] or ()):
        return None
    return parts["into"].get("to")


def _draws(steps: list) -> bool:
    """Does a question in *steps* draw from a supply?"""
    return any(kind_of(n) == "box" and _on(n, frames)
               and hits_question(n) is not None
               for n, frames in walk(steps))


def _searches(node: dict) -> bool:
    """Does a search of this item stand in *node*: in it, not in a frame of
    other items inside it?"""
    if not _on(node):
        return False
    if kind_of(node) == "box":
        return hits_question(node) == "dimension"
    if kind_of(node) == "each":
        return False
    return any(_searches(child) for _label, steps in children(node)
               for child in steps if isinstance(child, dict))


def _has_state(steps: list) -> bool:
    return any(kind_of(n) == "box" and _on(n, frames)
               and n.get("box") == "state"
               for n, frames in walk(steps))


def _steps(check: _Check, steps, frames: tuple, top: bool,
           outer: Optional[list] = None, state_after: bool = False) -> None:
    """The problems of a list of steps inside *frames*. *outer* are the
    boxes before this list in the same item (an "if" sees what stands
    before it); *state_after* whether a state follows this list in the
    frames around it."""
    if not isinstance(steps, list):
        check.say(frames[-1] if frames else {}, "steps are a list")
        return
    before: list = list(outer or [])
    for node in steps:
        if not isinstance(node, dict):
            check.say({}, f"a step is an object, not {node!r}")
            continue
        ident = node.get("id")
        if not isinstance(ident, str) or not ident.strip():
            check.say(node, "every box and frame needs an id")
        elif ident in check.ids:
            check.say(node, f"the id {ident} stands twice")
        else:
            check.ids[ident] = node
        kind = kind_of(node)
        if not kind:
            check.say(node, "a step is a box, an each, a round or an if")
            continue
        if kind == "box":
            _box(check, node, frames, before, top)
        else:
            at = steps.index(node)
            _frame(check, node, kind, frames, before, top,
                   state_after or _has_state(steps[at + 1:]))
        before.append(node)
    # A search round needs a state after it, in its list or after the
    # frames around it.
    for i, node in enumerate(steps):
        if kind_of(node) == "round" and _searches(node) \
                and not (state_after or _has_state(steps[i + 1:])):
            check.say(node, "a coordinate searched to its end needs a state "
                      "after the round (exhausted where pieces are left, "
                      "else unstated)")


def _list_frame(check: _Check, node: dict, frames: tuple,
                before: list) -> None:
    """A loop over any list (owner decision 2026-11-12): the list it goes
    through, there before it, and the name of its entry."""
    path = node.get("list")
    if not isinstance(path, str) or not _PATH.match(path):
        check.say(node, "a loop over a list names the list (a variable)")
    elif _on(node, frames):
        check.inputs(node, blocks.EACH_TITLES["list"], (_root(path),))
    name = node.get("as", "item")
    if not _NAME.match(str(name)):
        check.say(node, f"{name!r} is no name for the entry of a list")
    for key in ("which", "order"):
        if key in node:
            check.say(node, f"a loop over a list has no {key}")
    if "together" in node and not isinstance(node["together"], bool):
        check.say(node, "together is yes or no")
    inner = frames + (node,)
    if "when" in node:
        where = _known(inner, []) | _vars(check, node) | {f"var:{name}"}
        said = conditions.problems(node["when"], where)
        if said:
            check.say(node, f"only when: {said[0]}")
    _steps(check, node.get("steps"), inner, False)


def _frame(check: _Check, node: dict, kind: str, frames: tuple,
           before: list, top: bool, state_after: bool = False) -> None:
    for key in node:
        if key not in FRAME_KEYS[kind]:
            check.say(node, f"a frame {kind} has no key {key!r}")
    _rules_of(check, node)
    where = _known(frames, before) | _vars(check, node)
    inner = frames + (node,)
    if kind == "each":
        what = node.get("each")
        if what not in blocks.EACH:
            check.say(node, f"each {what!r} is nothing a frame iterates; "
                      f"it iterates {', '.join(blocks.EACH)}")
            return
        eaches = _eaches(frames)
        outer = eaches[-1] if eaches else None
        if what == "list":
            _list_frame(check, node, frames, before)
            return
        allowed = {"settled": (None,), "field": (None,),
                   "piece": ("field",), "value": (None, "field"),
                   "coordinate": ("value",)}[what]
        if outer not in allowed:
            check.say(node, f"each {what} stands in "
                      f"{' or '.join('the document' if a is None else 'each ' + a for a in allowed)}")
        from . import variables
        listed = variables.ITEMS.get(what, (None, None))[1]
        if listed and _on(node, frames):
            check.inputs(node, blocks.EACH_TITLES.get(what, what),
                         (listed,) + (("order?",) if what == "piece"
                                      and node.get("order", "best_first")
                                      == "best_first" else ()))
        if what == "settled" and not top:
            check.say(node, "each thing the document settles stands at the "
                      "top")
        if "which" in node and (what != "field"
                                or node["which"] not in blocks.WHICH):
            check.say(node, f"which is one of {', '.join(blocks.WHICH)}, "
                      f"for each field only")
        if "order" in node and node["order"] not in blocks.ORDERS.get(
                what, ()):
            check.say(node, f"each {what} takes the order "
                      f"{', '.join(blocks.ORDERS.get(what, ()))}")
        if "together" in node and not isinstance(node["together"], bool):
            check.say(node, "together is yes or no")
        if node.get("together"):
            outer_together = [f for f in frames if kind_of(f) == "each"
                              and f.get("together")]
            if outer_together:
                parent = outer_together[-1]
                if frames[-1] is not parent or len(parent.get("steps")
                                                   or []) != 1:
                    check.say(node, "side by side inside side by side only "
                              "as the one step of its frame")
        if "when" in node:
            from . import variables
            item = variables.ITEMS.get(what, (None, None))[0]
            said = conditions.problems(
                node["when"], _known(inner, []) | _vars(check, node)
                | ({f"var:{item}"} if item else set()))
            if said:
                check.say(node, f"only when: {said[0]}")
        if what == "coordinate" and not _has_state(node.get("steps") or []):
            check.say(node, "each coordinate needs a state box: every "
                      "coordinate ends with a state")
        _steps(check, node.get("steps"), inner, False)
    elif kind == "round":
        spec = node.get("round")
        if not isinstance(spec, dict) or set(spec) - {"most", "supply"} \
                or not spec:
            check.say(node, "a round is {\"most\": n} or {\"supply\": "
                      "true}")
        else:
            most = spec.get("most")
            if most is not None and (isinstance(most, bool)
                                     or not isinstance(most, int)
                                     or most < 1):
                check.say(node, f"a round runs at most a whole number of "
                          f"times, 1 or more, not {most!r}")
            if spec.get("supply") is not None and spec.get("supply") \
                    is not True:
                check.say(node, "supply is true where it is set")
            if most is None and not spec.get("supply"):
                check.say(node, "a round needs at most N times or until the "
                          "supply is used up, else it may not end")
            if spec.get("supply") and not _draws(node.get("steps") or []):
                check.say(node, "until the supply is used up: a question in "
                          "the round has to show the supply")
        if "stop" in node:
            made = {f"var:{name}" for one, _f in walk(node.get("steps") or [])
                    if kind_of(one) == "box" for name in outputs_of(one)}
            said = conditions.problems(
                node["stop"], _known(inner, before + list(
                    node.get("steps") or [])) | _vars(check, node) | made
                | {"var:round"})
            if said:
                check.say(node, f"stop when: {said[0]}")
        steps = node.get("steps") or []
        if any(hits_question(n) == "dimension" for n in steps
               if isinstance(n, dict)) \
                and not _supply_before(before) \
                and not _supply_before(steps):
            check.say(node, "a search in the round needs a supply before it "
                      "(order the pieces, or the pieces beside)")
        if any(hits_question(n) == "values" for n in steps
               if isinstance(n, dict)) \
                and not _supply_before(before):
            check.say(node, "a field asked in the round needs the pieces "
                      "ordered before it")
        _steps(check, node.get("steps"), inner, False, before, state_after)
    else:
        ways = node.get("if")
        if not isinstance(ways, list) or not ways:
            check.say(node, "an if has one way at least, each with when and "
                      "steps")
            return
        for way in ways:
            if not isinstance(way, dict) or "when" not in way \
                    or set(way) - {"when", "steps"}:
                check.say(node, "each way of an if has when and steps")
                continue
            said = conditions.problems(way["when"], where)
            if said:
                check.say(node, f"when: {said[0]}")
            _steps(check, way.get("steps") or [], inner, False, before,
                   state_after)
        if "else" in node:
            _steps(check, node.get("else"), inner, False, before,
                   state_after)


PREPARES = ("document", "transcribe", "split", "lists")
# What the runner does once a document is read and written, in its order
# (`engine.AFTER`).
ENDS = ("compute", "catalogue")


def known_rules(profile) -> dict:
    """{name: Rule} of every rule a box or frame of *profile*'s flow may
    set for itself: the rules of its line (`rules.registry`) and those its
    graph file declares (`graphfile.declared`), which steps read too (the
    rounding a compute box checks a computed number with)."""
    from .. import graphfile, rules
    return {**graphfile.declared(profile), **rules.registry(profile)}


# The profile of a drawing that may take the boxes of every profile: the
# drawing the engine is given was held to its profile when it was loaded
# or saved.
ANY_PROFILE = "*"


def problems(tree, known: Optional[dict] = None, profile=None) -> list:
    """Everything the run could not do with the drawing *tree*: [{"id": the
    box or frame or None, "message"}], [] where it can run. *profile* (a
    profile or its name) is the profile the drawing belongs to, whose boxes
    it may take; *known* are the rules a step may set (`known_rules`), the
    profile's where not given. Without a profile, the active one."""
    if profile is None:
        from ..profile import active_profile
        profile = active_profile()
    if profile == ANY_PROFILE:
        from ..profile import active_profile
        profile, ambient = None, active_profile()
    else:
        ambient = profile
    if known is None:
        known = known_rules(_profile_of(ambient))
    check = _Check(known)
    check.profile = profile
    if not isinstance(tree, list) or not tree:
        return [{"id": None, "message": "the flow is a list of boxes and "
                 "frames, not empty"}]
    check.avail = availability(tree)
    check.makers = makers(tree)
    _steps(check, tree, (), True)
    from ..rules import step_kind
    # a step of "Ask the model" counts as the step its preset stands for
    top = [step_kind(node) if kind_of(node) == "box" else None
           for node in tree if isinstance(node, dict)]
    every = [step_kind(n) for n, _ in walk(tree) if kind_of(n) == "box"]
    # Only writing the harvest is fixed (owner decision 2026-11-12: "Ernte
    # schreiben am Ende darf fest sein"); what prepares the document is
    # done once, where it stands at the top.
    if top.count("write") != 1 or every.count("write") != 1:
        check.say({}, "write stands once, at the top")
    for kind in PREPARES + ("compute", "catalogue", "sentences", "works"):
        if every.count(kind) > 1:
            check.say({}, f"{kind} stands once at most")
    # What the runner does once a document is read, in its order, before
    # it writes the file (owner decision 2026-11-13, point 12).
    later = list(ENDS)
    if "write" in top:
        at = top.index("write")
        if any(isinstance(node, dict) for node in tree[at + 1:]):
            check.say({}, "write stands at the end: nothing comes after it")
        if any(kind in later for kind in top[at + 1:]):
            check.say({}, "compute and catalogue stand before write: the "
                      "run does them before it writes the file")
    ends = [kind for kind in top if kind in later]
    if ends != sorted(ends, key=later.index):
        check.say({}, f"{' and '.join(later)} stand in this order: the run "
                  f"does them so")
    return check.out


def prompt_problems(tree: list, profile) -> list:
    """The boxes of *tree* that are on and ask a request whose prompt
    *profile* writes not, nor the profiles it extends: [{"id", "message"}].
    A request a profile may leave unwritten (`addressed.OPTIONAL`) is no
    problem: its box is never taken by that profile."""
    from .. import prompts
    from . import addressed, compute
    out = []
    for node, _frames in on(tree):
        if kind_of(node) != "box":
            continue
        kind = blocks.box_of(node)
        if kind is None or not kind.asks:
            continue
        prompt_id = compute.COMPUTE_PROMPT_ID if kind.asks == "compute" \
            else f"extraction/{kind.asks}"
        if node.get("box") == "ask":
            from .general import parts_of
            prompt_id = parts_of(node)["prompt"]
            if not isinstance(prompt_id, str):
                continue        # a text of the step's own
        try:
            prompts.load(prompt_id, profile)
        except (FileNotFoundError, LookupError):
            if kind.asks not in addressed.OPTIONAL \
                    and kind.asks != "compute":
                out.append({"id": node.get("id"),
                            "message": f"{kind.label} asks {kind.asks}, and "
                            f"the profile writes no prompt for it "
                            f"({prompt_id})"})
    return out


# -- the file -----------------------------------------------------------------

def path_of(profile) -> Path:
    """Where *profile* writes its flow."""
    return Path(profile.package_dir) / FILE


def kinds() -> tuple:
    """The requests the code can send while it reads a document: those of
    the reading (`addressed.KINDS`) and the calculation after it."""
    from . import addressed, compute
    return tuple(addressed.KINDS) + (
        compute.COMPUTE_PROMPT_ID.rsplit("/", 1)[-1],)


def _profile_of(profile):
    """*profile* as a profile, where it is given by its name."""
    if isinstance(profile, str):
        from ..profile import load_profile
        try:
            return load_profile(profile)
        except LookupError:
            return None
    return profile


def parse(raw: str, where, whole: bool, profile=None) -> dict:
    """{"numbers": {name: value}, "flow": [...]} of the text *raw*, read
    strictly. A *whole* file names every number and the drawing; any other
    is laid over one and names numbers, and may draw a whole drawing of
    its own. *where* names the file in what is said about it, *profile*
    (a profile or its name) the profile it belongs to."""
    def once(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise FlowError(f"{where}: {key!r} stands twice")
            out[key] = value
        return out

    try:
        data = json.loads(raw, object_pairs_hook=once)
    except FlowError:
        raise
    except ValueError as exc:
        raise FlowError(f"{where}: {exc}") from exc
    if not isinstance(data, dict):
        raise FlowError(f"{where}: a flow file is one JSON object with "
                        f"\"numbers\" and, in the file a flow starts from, "
                        f"\"flow\"")
    for key in data:
        if key not in ("numbers", "flow"):
            raise FlowError(f"{where}: has no key {key!r}; a flow file "
                            f"holds \"numbers\" and \"flow\""
                            + (" (the list of steps of before 2026-11-11 "
                               "is now a drawing, \"flow\")"
                               if key == "steps" else ""))
    numbers = data.get("numbers", {})
    if not isinstance(numbers, dict):
        raise FlowError(f"{where}: numbers must be an object, the name of a "
                        f"number -> its value")
    read = {name: checked(where, name, value)
            for name, value in numbers.items()}
    if whole:
        missing = [n.name for n in NUMBERS if n.name not in read]
        if missing:
            raise FlowError(f"{where}: names no {', '.join(missing)}; the "
                            f"file a flow starts from names every number")
        if "flow" not in data:
            raise FlowError(f"{where}: the file a flow starts from draws "
                            f"the flow")
    if "flow" not in data:
        return {"numbers": read}
    said = problems(data["flow"], profile=profile)
    if said:
        first = said[0]
        raise FlowError(f"{where}: "
                        + (f"{first['id']}: " if first["id"] else "")
                        + first["message"])
    return {"numbers": read, "flow": data["flow"]}


def dump(data: dict, newline: str = "\n") -> str:
    """A flow file's text in the one form it is written in."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return text if newline == "\n" else text.replace("\n", newline)


def line(profile) -> list:
    """[(profile name, path)] of the files a profile's flow can stand in,
    nearest first; the default's alone where no profile is given or it has
    no folder of its own."""
    if profile is None or getattr(profile, "package_dir", None) is None:
        return [(DEFAULT_NAME, DEFAULT)]
    lineage = getattr(profile, "lineage", None)
    line = lineage() if callable(lineage) else [profile]
    return [(one.name, path_of(one)) for one in line]


_loaded: dict = {}
LOADED_KEPT = 16


def _merged(written: list) -> Flow:
    """The flow of the files *written* ([(profile name, path)], nearest
    first, each a file): the farthest is the whole flow, the numbers of
    every nearer one are laid over it, and a nearer drawing is the
    drawing. Read once per state of the files."""
    key = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                for _, path in written)
    if key in _loaded:
        return _loaded[key]
    (first, start), nearer = written[-1], written[:-1]
    whole = parse(start.read_text(encoding="utf-8"), start, True, first)
    numbers = dict(whole["numbers"])
    owners = {name: first for name in numbers}
    tree, tree_from = whole["flow"], first
    for name, path in reversed(nearer):
        own = parse(path.read_text(encoding="utf-8"), path, False, name)
        for number, value in own["numbers"].items():
            numbers[number], owners[number] = value, name
        if "flow" in own:
            tree, tree_from = own["flow"], name
    numbers = {number.name: numbers[number.name] for number in NUMBERS}
    sha = hashlib.sha256(json.dumps(
        {"numbers": numbers, "flow": tree}, ensure_ascii=False,
        sort_keys=True).encode("utf-8")).hexdigest()
    flow = Flow(numbers, owners, tree, tuple(written), sha, tree_from)
    while len(_loaded) >= LOADED_KEPT:
        _loaded.pop(next(iter(_loaded)))
    _loaded[key] = flow
    return flow


def load(profile=None) -> Flow:
    """The flow of *profile* as its files say it: the file of the farthest
    profile of its line that writes one is the whole flow, and the numbers
    of every nearer one are laid over it. LookupError where no profile of
    the line writes one."""
    written = [(name, path) for name, path in line(profile)
               if path.is_file()]
    if not written:
        names = [name for name, _ in line(profile)]
        raise LookupError(f"profile {names[0]!r} writes no {FILE}"
                          + (f", nor does {', '.join(names[1:])}, which it "
                             f"extends" if names[1:] else ""))
    return _merged(written)


def inherited(profile) -> Optional[Flow]:
    """The flow of the profiles *profile* extends, its own file left out:
    what a number is where the profile does not set it. None where no
    profile it extends writes a flow, so that its own file is the whole
    one."""
    written = [(name, path) for name, path in line(profile)[1:]
               if path.is_file()]
    return _merged(written) if written else None


def tree_of(profile=None) -> list:
    """The drawing a run of *profile* reads by (the default profile's where
    None)."""
    return load(profile).tree


# -- what a run reads with ----------------------------------------------------

def _setting(number: Number, raw: str) -> int:
    """The value of a number as its setting spells it."""
    text = raw
    if number.part is not None:
        parts = raw.split(",")
        if len(parts) != 3:
            raise FlowError(f"{number.env} must be three numbers (tables, "
                            f"figures, text), not {raw!r}")
        text = parts[number.part]
    try:
        value = int(text.strip())
    except ValueError:
        raise FlowError(f"{number.env} must be "
                        f"{'whole numbers' if number.part is not None else 'a whole number'}"
                        f", not {raw!r}") from None
    if value < number.least:
        raise FlowError(f"{number.env}: {number.name} must be at least "
                        f"{number.least}, not {value}")
    return value


def in_effect(profile=None, environ=None) -> Numbers:
    """The numbers a run of *profile* reads with: the flow of its files, and
    over it the settings that are set (*environ*, the environment where not
    given, into which the project file was put). `Numbers.origin` says for
    each where it comes from."""
    from .. import settings
    flow = load(profile)
    own = environ is None
    environ = os.environ if own else environ
    values: dict = {}
    origin: dict = {}
    by_run = set()
    for number in NUMBERS:
        raw = environ.get(number.env) if number.env else None
        if raw is None:
            values[number.name] = flow.numbers[number.name]
            origin[number.name] = f"{FILE} of {flow.owners[number.name]}"
        else:
            values[number.name] = _setting(number, raw)
            origin[number.name] = settings.origin(number.env) if own \
                else "environment"
            by_run.add(number.name)
    return Numbers(**values, origin=origin, sha256=flow.sha256,
                   set_by_run=frozenset(by_run))


def default() -> Numbers:
    """The numbers of the default profile's file, no setting applied: what
    a reading takes where it is given none."""
    return in_effect(None, environ={})
