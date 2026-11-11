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
number}, "when": condition, "off": true}. "own" gives a number setting a
value of its own ("only here") instead of the named number. A frame:
{"id", "each": what, "which", "when", "together", "order", "steps"},
{"id", "round": {"most": n} or {"supply": true}, "stop": condition,
"steps"}, {"id", "if": [{"when": condition, "steps"}], "else": steps}.
Conditions are `conditions.py`'s.

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
BY_NAME = {number.name: number for number in NUMBERS}
FRAME_KEYS = {"each": ("id", "each", "which", "when", "together", "order",
                       "steps", "off", "note"),
              "round": ("id", "round", "stop", "steps", "off", "note"),
              "if": ("id", "if", "else", "off", "note")}
BOX_KEYS = ("id", "box", "set", "own", "when", "off", "note")


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


# -- walking a drawing -----------------------------------------------------------

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


def boxes(tree: list) -> list:
    return [node for node, _ in walk(tree) if kind_of(node) == "box"]


def asked(tree: list) -> set:
    """The requests the boxes of *tree* ask, of the boxes that are on."""
    out = set()
    for node, frames in walk(tree):
        if kind_of(node) != "box" or node.get("off") \
                or any(f.get("off") for f in frames):
            continue
        kind = blocks.LIBRARY.get(node.get("box"))
        if kind is not None and kind.asks:
            out.add(kind.asks)
    return out


def compute_on(tree: list) -> bool:
    """Is the calculation after the reading on in *tree*?"""
    return any(node.get("box") == "compute" and not node.get("off")
               for node in tree if isinstance(node, dict))


# -- what a drawing may say ------------------------------------------------------

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


class _Check:
    """The problems of one drawing, each with the id of its node."""

    def __init__(self):
        self.out: list = []
        self.ids: dict = {}

    def say(self, node, message: str) -> None:
        ident = node.get("id") if isinstance(node, dict) else None
        self.out.append({"id": ident if isinstance(ident, str) else None,
                         "message": message})


def _innermost(frames: tuple, kind: str = "each") -> Optional[dict]:
    return next((f for f in reversed(frames) if kind_of(f) == kind), None)


def _eaches(frames: tuple) -> list:
    return [f.get("each") for f in frames if kind_of(f) == "each"]


def _known(frames: tuple, before: list) -> set:
    """The things a condition can be about at a place inside *frames*,
    after the boxes *before* of its own item."""
    out = {"document", "run"}
    eaches = _eaches(frames)
    if any(e in ("field", "piece", "value", "coordinate") for e in eaches):
        out.add("field")
    if any(e in ("value", "coordinate") for e in eaches):
        out.add("value")
    if "coordinate" in eaches:
        out |= {"coordinate", "pieces"}
    if any(kind_of(f) == "round" for f in frames):
        out.add("round")
    for node in before:
        # A box that is off is not there: it gives nothing.
        kind = blocks.LIBRARY.get(node.get("box")) \
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
    return None


def _box(check: _Check, node: dict, frames: tuple, before: list,
         top: bool) -> None:
    kind = blocks.LIBRARY.get(node.get("box"))
    if kind is None:
        check.say(node, f"there is no box {node.get('box')!r}"
                  f"{_nearest(node.get('box'), blocks.LIBRARY)}")
        return
    for key in node:
        if key not in BOX_KEYS:
            check.say(node, f"a box has no key {key!r}")
    if node.get("off") and (kind.fixed or not kind.switch):
        check.say(node, f"{kind.label} cannot be off: {kind.fixed}")
    if kind.top and not top:
        check.say(node, f"{kind.label} stands at the top of the drawing "
                  f"only")
    eaches = _eaches(frames)
    inner = eaches[-1] if eaches else None
    if kind.needs:
        wanted = [n for n in kind.needs if n != "round"]
        if "round" in kind.needs and not any(kind_of(f) == "round"
                                             for f in frames):
            check.say(node, f"{kind.label} stands in a round: it shows a "
                      f"supply a few pieces at a time")
        if wanted and inner not in wanted:
            check.say(node, f"{kind.label} stands in "
                      f"{' or '.join('each ' + n for n in wanted)}, not "
                      f"{('each ' + inner) if inner else 'the document'}")
        if kind.type == "find" and len(eaches) < 2 \
                or kind.type == "find" and eaches[-2] != "field":
            check.say(node, "a find stands in each piece of each field")
        if kind.type == "docfield" and inner == "field":
            frame = _innermost(frames)
            if frame.get("which", "all") == "pieces":
                check.say(node, "a field read in pieces is asked by finds, "
                          "not as a field of the document")
    where = _known(frames, before)
    sets = node.get("set") or {}
    own = node.get("own") or {}
    if not isinstance(sets, dict) or not isinstance(own, dict):
        check.say(node, "set and own are objects: setting -> value")
        return
    by_key = {s.key: s for s in kind.settings}
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
    if kind.type == "check":
        for key in ("name", "refuse", "sentence"):
            if key not in sets:
                check.say(node, f"a check needs its {key}")
    if kind.attached:
        previous = [n for n in before if kind_of(n) == "box"]
        chain = list(reversed(previous))
        while chain and blocks.LIBRARY.get(chain[0].get("box")) is not None \
                and blocks.LIBRARY[chain[0]["box"]].attached:
            chain.pop(0)
        asking = chain[0].get("box") if chain else None
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


def _draws(steps: list) -> bool:
    """Does a question in *steps* draw from a supply?"""
    return any(kind_of(n) == "box" and _on(n, frames)
               and n.get("box") in ("docfield", "search")
               for n, frames in walk(steps))


def _searches(node: dict) -> bool:
    """Does a search of this item stand in *node*: in it, not in a frame of
    other items inside it?"""
    if not _on(node):
        return False
    if kind_of(node) == "box":
        return node.get("box") == "search"
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


def _frame(check: _Check, node: dict, kind: str, frames: tuple,
           before: list, top: bool, state_after: bool = False) -> None:
    for key in node:
        if key not in FRAME_KEYS[kind]:
            check.say(node, f"a frame {kind} has no key {key!r}")
    where = _known(frames, before)
    inner = frames + (node,)
    if kind == "each":
        what = node.get("each")
        if what not in blocks.EACH:
            check.say(node, f"each {what!r} is nothing a frame iterates; "
                      f"it iterates {', '.join(blocks.EACH)}")
            return
        eaches = _eaches(frames)
        outer = eaches[-1] if eaches else None
        allowed = {"settled": (None,), "field": (None,),
                   "piece": ("field",), "value": (None, "field"),
                   "coordinate": ("value",)}[what]
        if outer not in allowed:
            check.say(node, f"each {what} stands in "
                      f"{' or '.join('the document' if a is None else 'each ' + a for a in allowed)}")
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
            said = conditions.problems(node["when"], _known(inner, []))
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
            said = conditions.problems(
                node["stop"], _known(inner, before + list(
                    node.get("steps") or [])))
            if said:
                check.say(node, f"stop when: {said[0]}")
        steps = node.get("steps") or []
        if any(n.get("box") == "search" for n in steps) \
                and not _supply_before(before) \
                and not _supply_before(steps):
            check.say(node, "a search in the round needs a supply before it "
                      "(order the pieces, or the pieces beside)")
        if any(n.get("box") == "docfield" for n in steps) \
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


def problems(tree) -> list:
    """Everything the run could not do with the drawing *tree*: [{"id": the
    box or frame or None, "message"}], [] where it can run."""
    check = _Check()
    if not isinstance(tree, list) or not tree:
        return [{"id": None, "message": "the flow is a list of boxes and "
                 "frames, not empty"}]
    _steps(check, tree, (), True)
    top = [node.get("box") if kind_of(node) == "box" else None
           for node in tree if isinstance(node, dict)]
    if top[:len(PREPARES)] != list(PREPARES):
        check.say({}, "the drawing starts with document, transcribe, split "
                  "and lists, in this order: every request shows the "
                  "figures' lines and the pieces")
    every = [n.get("box") for n, _ in walk(tree) if kind_of(n) == "box"]
    for kind in PREPARES + ("write",):
        if top.count(kind) != 1 or every.count(kind) != 1:
            check.say({}, f"{kind} stands once, at the top")
    for kind in ("compute", "sentences", "works"):
        if every.count(kind) > 1:
            check.say({}, f"{kind} stands once at most")
    if "write" in top:
        after = top[top.index("write") + 1:]
        if any(kind not in (None, "compute") for kind in after) \
                or any(kind_of(node) != "box" for node in tree[
                    top.index("write") + 1:] if isinstance(node, dict)):
            check.say({}, "write stands at the end; only compute comes "
                      "after it")
    if "compute" in top and "write" in top \
            and top.index("compute") < top.index("write"):
        check.say({}, "compute stands after write: it computes from the "
                  "rows the reading wrote")
    # The fields read in pieces come before the values of their finds.
    order = [node for node in tree if isinstance(node, dict)]
    pieces_at = [i for i, node in enumerate(order)
                 if node.get("each") == "field"
                 and node.get("which", "all") != "once"]
    values_at = [i for i, node in enumerate(order)
                 if node.get("each") == "value"]
    if values_at and pieces_at and values_at[0] < pieces_at[0]:
        check.say(order[values_at[0]], "each value comes after the finds of "
                  "the fields read in pieces")
    settled_at = [i for i, node in enumerate(order)
                  if node.get("each") == "settled"]
    first_read = next((i for i, node in enumerate(order)
                       if node.get("box") not in PREPARES
                       and node.get("each") != "settled"), len(order))
    if any(i > first_read for i in settled_at):
        check.say(order[settled_at[0]], "what the document settles is asked "
                  "before the reading: every request after it shows it")
    return check.out


def prompt_problems(tree: list, profile) -> list:
    """The boxes of *tree* that are on and ask a request whose prompt
    *profile* writes not, nor the profiles it extends: [{"id", "message"}].
    A request a profile may leave unwritten (`addressed.OPTIONAL`) is no
    problem: its box is never taken by that profile."""
    from .. import prompts
    from . import addressed, compute
    out = []
    for node, frames in walk(tree):
        if kind_of(node) != "box" or node.get("off") \
                or any(f.get("off") for f in frames):
            continue
        kind = blocks.LIBRARY.get(node.get("box"))
        if kind is None or not kind.asks:
            continue
        prompt_id = compute.COMPUTE_PROMPT_ID if kind.asks == "compute" \
            else f"extraction/{kind.asks}"
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


# -- the file ------------------------------------------------------------------

def path_of(profile) -> Path:
    """Where *profile* writes its flow."""
    return Path(profile.package_dir) / FILE


def kinds() -> tuple:
    """The requests the code can send while it reads a document: those of
    the reading (`addressed.KINDS`) and the calculation after it."""
    from . import addressed, compute
    return tuple(addressed.KINDS) + (
        compute.COMPUTE_PROMPT_ID.rsplit("/", 1)[-1],)


def parse(raw: str, where, whole: bool) -> dict:
    """{"numbers": {name: value}, "flow": [...]} of the text *raw*, read
    strictly. A *whole* file names every number and the drawing; any other
    is laid over one and names numbers, and may draw a whole drawing of
    its own. *where* names the file in what is said about it."""
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
    said = problems(data["flow"])
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
    whole = parse(start.read_text(encoding="utf-8"), start, True)
    numbers = dict(whole["numbers"])
    owners = {name: first for name in numbers}
    tree, tree_from = whole["flow"], first
    for name, path in reversed(nearer):
        own = parse(path.read_text(encoding="utf-8"), path, False)
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


# -- what a run reads with -----------------------------------------------------

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
