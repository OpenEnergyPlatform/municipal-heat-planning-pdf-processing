"""
engine.py: The run does what the drawing of its flow says (owner decisions
2026-11-10 evening: "Freie Ablaufgrafik"; plan of 2026-11-10, sections 2,
9 and 10).

The flow (`flow.py`) is a tree of boxes and frames. This module walks it for
one document and does what each box says, in the order it stands; there is
no second order in the code. What a box does with an answer stays the
reading's (`addressed.Reader`): building a request, looking up an address,
the two checks, folding a value. The engine decides only which box runs
when, for what, how often and in which order:

- "each" iterates what the document settles, its fields, a field's pieces,
  the values read, a value's coordinates; side by side where it says so (one
  pool for a frame side by side whose only step is another side by side:
  each field and each of its pieces, as the reading always asked them), and
  only for the items its condition holds for.
- "round" runs its steps again, at most N times or until the supply its
  question shows is used up, and stops where its condition holds after a
  turn.
- "if" takes the first way whose condition holds, else the last.

Every request carries the id of the box that asked it (`box` in the trace,
owner decision 2026-11-10: the page counts requests per box); a request a
box asks while it reads an answer (the entry of a list, the name of a
scenario, a follow-up) is that box's.

A box that checks answers (`about`, an own check, `check`) stands right
after the question whose answers it checks and is applied while that
question reads them. An own check refuses an answer where its condition
holds; what it refuses is asked again with its sentence, as often as the
question's follow-ups, then stays unbacked, and is counted under
`check:<name>` (owner decision 2026-11-10: own checks are allowed in the
page; the flow the code brings has none).

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import contextlib
import copy
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import rules
from . import addressed, blocks, conditions, fields, general
from . import flow as flow_map
from .addressed import (Asking, Counts, Found, Plan, Read, field_shown,
                        field_shown_of, joined, years_in)
from .fields import NUMBER, READ, UNBACKED, state_for
from .pipeline import (Batch, Row, Source, WorkItem, mark_unanswered,
                       row_label)
from .reading import groups_of, in_group_order, link_ranges, slots_of
from .spec import group_taken


class Stop(Exception):
    """The drawing holds something the run cannot do; the check of the flow
    (`flow.problems`) refuses it before a run."""


# -- what a frame holds -------------------------------------------------------

class Scope:
    """What the run knows at one place of the drawing: the document, the
    item of each frame around it, the round. An item's own values (its
    answer, its supply) live in the scope of its frame's turn."""

    def __init__(self, parent: Optional["Scope"] = None, item: bool = False,
                 **values):
        self.parent = parent
        self.item = item
        self.values = values

    def get(self, key, default=None):
        scope = self
        while scope is not None:
            if key in scope.values:
                return scope.values[key]
            scope = scope.parent
        return default

    def has(self, key) -> bool:
        scope = self
        while scope is not None:
            if key in scope.values:
                return True
            scope = scope.parent
        return False

    def owner(self) -> "Scope":
        """The scope of the innermost item: where a box keeps its answer."""
        scope = self
        while scope is not None and not scope.item:
            scope = scope.parent
        return scope or self

    def put(self, key, value) -> None:
        self.owner().values[key] = value

    def used_up(self) -> None:
        """The question of the innermost round has nothing left to show:
        that round ends."""
        scope = self
        while scope is not None and "used_up" not in scope.values:
            scope = scope.parent
        if scope is not None:
            scope.values["used_up"] = True

    def drew(self) -> None:
        """A question of the innermost round showed pieces of its supply."""
        scope = self
        while scope is not None and "drew" not in scope.values:
            scope = scope.parent
        if scope is not None:
            scope.values["drew"] = True

    def child(self, item: bool = False, **values) -> "Scope":
        return Scope(self, item, **values)


@dataclass
class Doc:
    """One reading of a document."""
    plan: Plan
    counts: Counts
    parameters: list
    chunks: object = None           # None, [pieces] or {uri: [...] or None}
    order_of: dict = field(default_factory=dict)
    order_fields: Optional[Callable] = None
    reads: list = field(default_factory=list)       # works, document fields
    field_reads: list = field(default_factory=list)  # document fields
    find_reads: list = field(default_factory=list)
    by_find: dict = field(default_factory=dict)     # (uri, owner) -> Read
    valued: dict = field(default_factory=dict)      # id(read) -> frame
    seen_of: dict = field(default_factory=dict)     # coordinate -> seen
    started: float = field(default_factory=time.monotonic)
    about: dict = field(default_factory=dict)       # facts made once
    # The variables the page's steps made for the whole document
    # (`general.put`, owner decision 2026-11-12).
    made: dict = field(default_factory=dict)

    @property
    def whole(self) -> bool:
        """Is the whole document read (no pass over a part of it)?"""
        return self.chunks is None or (isinstance(self.chunks, dict) and any(
            got is None for got in self.chunks.values()))

    def pieces_of(self, uri: str) -> list:
        got = self.chunks.get(uri) if isinstance(self.chunks, dict) \
            else self.chunks
        return list(self.plan.chunks) if got is None else list(got)


@dataclass
class FieldItem:
    """A field of the document asked once, or a thing it settles."""
    key: str                        # the field's uri or the settled key
    shown: Optional[dict]           # as a request shows it; None for a
    #                                 parameter: built by the box that asks
    sentences: list
    numbers: bool = False
    listed: Optional[tuple] = None
    parameter: object = None
    settled: Optional[dict] = None
    found: list = field(default_factory=list)
    lost: Optional[str] = None
    asked_by: Optional[str] = None  # the id of the box that asked it
    reads: Optional[list] = None
    first_source: Optional[Source] = None   # of the first request's chunks


@dataclass
class ValueItem:
    read: Read
    row: Row
    rows: list
    clone: Callable


@dataclass
class CoordItem:
    read: Read
    row: Row
    slot: object
    group: object
    before: list
    clone: Callable
    made: list = field(default_factory=list)
    payload: Optional[dict] = None
    noted: Optional[dict] = None
    sentence: Optional[str] = None
    sentences: list = field(default_factory=list)
    seen: Optional[set] = None
    ordered: set = field(default_factory=set)
    chunk: object = None
    located: bool = False
    seen_of: Optional[dict] = None
    # The rules whose second way the requests of this coordinate went
    # through (`second_ways`), noted on them.
    ways: list = field(default_factory=list)
    # The pieces the request at the value's own place asked to see, shown
    # first by the search that follows it, and the pictures of figures its
    # requests saw, each once (owner decision 2026-11-12).
    fetched: list = field(default_factory=list)
    pictures: set = field(default_factory=set)


class ListSupply:
    """The pieces a field of the document is asked over: the title page with
    the first request, then the pieces in their order, a few a request. The
    pieces a reply asked to see (*fetched*) come first in the next request,
    beyond the pieces of the order and not counted in them; no piece is
    shown twice (*seen*, owner decision 2026-11-12)."""

    def __init__(self, pieces: list):
        self.pieces = list(pieces)
        self.at = 0
        self.started = False
        self.fetched: list = []
        self.seen: set = set()

    def take(self, size: int):
        """(first request?, pieces) of the next request, None where the
        supply is used up."""
        first = not self.started
        self.started = True
        fetched = [c for c in dict.fromkeys(self.fetched)
                   if c.key not in self.seen]
        self.fetched = []
        batch: list = []
        while self.at < len(self.pieces) and len(batch) < size:
            piece = self.pieces[self.at]
            self.at += 1
            if piece.key not in self.seen and piece not in fetched:
                batch.append(piece)
        if first and not fetched:
            # The first request takes its size of the order, as it always
            # did, whether or not a piece of it was shown.
            batch = self.pieces[:size]
            self.at = size
        batch = fetched + batch
        if not batch and not first:
            return None
        self.seen.update(c.key for c in batch)
        return first, batch

    def left(self) -> int:
        return max(0, len(self.pieces) - self.at) + len(self.fetched)


class SearchSupply:
    """The pieces a coordinate's search shows: the pieces it was given
    (*first*, shown together in the first request), then the pieces of its
    order a few at a time (*ranked*, made the first time it is needed), the
    pieces a reply fetched itself first in the next request; no piece twice
    (`seen`, the coordinate's) unless the rule `show_twice` says it may be
    shown a second time. *limit* is the most pieces the search shows (the
    flow's number of chunks), *reorder* puts the pieces left in order again
    with the sentence of the round (the rule `rerank_when`)."""

    def __init__(self, first: list, ranked: Optional[Callable], label: str,
                 limit: Optional[int] = None,
                 reorder: Optional[Callable] = None):
        self.first = list(first)
        self.ranked = ranked
        self.order: Optional[list] = None
        self.label = label
        self.fetched: list = []
        self.started = False
        self.limit = limit
        self.reorder = reorder
        # How often each piece was shown by this supply, the pieces of its
        # order taken, the pieces a reply fetched that were shown, and the
        # rules whose second way a request went through.
        self.shown: dict = {}
        self.walked: set = set()
        self.fetched_shown = 0
        self.ways: set = set()

    def _ranked(self) -> list:
        if self.ranked is None:
            return []
        if self.order is None:
            self.order = list(self.ranked() or [None])
        return [c for c in self.order if c is not None]

    def _open(self, piece, seen: set, twice: bool) -> bool:
        """May *piece* be shown now? Not if it was shown, or twice where
        the rule `show_twice` allows a second time."""
        if not twice:
            return piece.key not in seen
        times = self.shown.get(piece.key, 0) or (
            1 if piece.key in seen else 0)
        return times < 2

    def take(self, size: int, seen: set) -> tuple:
        """(pieces, what they are: the supply's label or "fetched") of the
        next request; ([], None) where nothing is left. The kinds of pieces
        come in the order of the rule `supply_order`: those before the
        ranked ones are shown together, the ranked ones only where none of
        them is left."""
        first = not self.started
        self.started = True
        twice = rules.get("show_twice")
        counted = rules.get("fetched_count")
        batch: list = []
        label = "fetched"
        used = False
        for kind in rules.get("supply_order"):
            if kind == "fetched":
                batch += self.fetched
                used = True
            elif kind == "beside" and first:
                batch += self.first
                label = self.label
            elif kind == "ranked":
                batch = [c for c in dict.fromkeys(batch)
                         if self._open(c, seen, twice)]
                if batch:
                    break
                left = [c for c in self._ranked()
                        if self._open(c, seen, twice)
                        and not (twice and c.key in self.walked)]
                if left and rules.get("rerank_when") == "each_round" \
                        and self.reorder is not None:
                    left = self.reorder(left)
                    self.ways.add("rerank_when")
                if left and counted and self.limit is not None:
                    left = left[:max(0, self.limit - len(self.walked)
                                     - self.fetched_shown)]
                    self.ways.add("fetched_count")
                if left:
                    if used:
                        self.fetched = []
                    left = left[:size]
                    self.walked.update(c.key for c in left)
                    if twice and any(self.shown.get(c.key) or c.key in seen
                                     for c in left):
                        self.ways.add("show_twice")
                    for c in left:
                        self.shown[c.key] = self.shown.get(c.key, 0) + 1
                    return left, self.label
        fetched = {c.key for c in self.fetched}
        if used:
            self.fetched = []
        batch = [c for c in dict.fromkeys(batch)
                 if self._open(c, seen, twice)]
        if not batch:
            return [], None
        if twice and any(self.shown.get(c.key) or c.key in seen
                         for c in batch):
            self.ways.add("show_twice")
        if counted:
            self.fetched_shown += len([c for c in batch
                                       if c.key in fetched])
        for c in batch:
            self.shown[c.key] = self.shown.get(c.key, 0) + 1
        return batch, label

    def left(self, seen: set) -> int:
        twice = rules.get("show_twice")
        return len([c for c in self._ranked()
                    if self._open(c, seen, twice)]) \
            + len([c for c in self.first if self._open(c, seen, twice)])


@dataclass
class Answer:
    """What the last question of an item came to."""
    answered: bool = False
    finds: int = 0
    zero: bool = True
    other_passage: bool = False
    words: str = ""
    quote: str = ""
    follow_ups: int = 0             # follow-up questions it took
    refusal: str = "none"           # why a find of it was refused


# Where the language of a document is told from: words that stand in one
# language and hardly in the other.
GERMAN = frozenset("der die das und nicht mit von für ist auf den im zu "
                   "werden wird eine sich auch dem des als bei".split())
ENGLISH = frozenset("the and of to is in for with that are on as by this "
                    "be from or an at which".split())


def language_of(texts) -> str:
    """"de", "en" or "other": which of two languages the *texts* are
    written in, by the words each has more of."""
    words = re.findall(r"[^\W\d_]+", " ".join(texts).casefold())
    german = sum(1 for word in words if word in GERMAN)
    english = sum(1 for word in words if word in ENGLISH)
    if german == english:
        return "other"
    return "de" if german > english else "en"


def refusal_of(failed) -> str:
    """The reason most of the refusals of a question came to, as a
    condition names it (`conditions.REFUSALS`)."""
    if not failed:
        return "none"
    why = max(failed, key=lambda one: failed[one])
    if str(why).startswith("check:"):
        return "own_check"
    return why if why in conditions.REFUSALS else "other"


# -- the engine ---------------------------------------------------------------

# The top boxes the runner does once a document is read, each in its own
# step (`Engine.step_of`).
AFTER = ("write", "compute", "catalogue")

class Engine:
    """The drawing *tree* of a flow done for documents with the reading
    *reader* (`addressed.Reader`)."""

    def __init__(self, reader, tree: Optional[list] = None):
        self.reader = reader
        self.tree = tree if tree is not None else flow_map.tree_of(None)
        # the boxes were held to their profile when the drawing was loaded
        said = flow_map.problems(self.tree, profile=flow_map.ANY_PROFILE)
        if said:
            raise Stop("; ".join((f"{p['id']}: " if p["id"] else "")
                                 + p["message"] for p in said[:3]))
        top = [node for node in self.tree if isinstance(node, dict)]
        # What prepares the document is done once, where it stands and is
        # on (owner decision 2026-11-12: no step but writing is fixed); a
        # step that is not there is not done, the chunks are then cut as
        # the rules say.
        prepares = [n for n in top if n.get("box") in flow_map.PREPARES
                    and not n.get("off")]
        self.prepares = {n["box"]: n for n in prepares}
        self.split_node = self.prepares.get("split")
        self.transcribe_id = (self.prepares.get("transcribe")
                              or {}).get("id")
        self.settled_frames = [n for n in top if n.get("each") == "settled"]
        self.reading = [n for n in top if n.get("box") not in
                        flow_map.PREPARES + AFTER
                        and n.get("each") != "settled"]
        values = [n for n in top if n.get("each") == "value"]
        self.sweep_frame = next(
            (child for frame in values for child in frame.get("steps") or []
             if child.get("each") == "coordinate"), None)
        if self.sweep_frame is None:
            self.sweep_frame = next((n for n, _ in flow_map.walk(self.tree)
                                     if n.get("each") == "coordinate"), None)

    # -- the values a step sets for itself ------------------------------------

    @staticmethod
    def own_values(node: dict) -> dict:
        """What *node* sets for itself while it runs: its "rules", and a
        box's own numbers ("own") under the names of the flow's numbers."""
        values = dict(node.get("rules") or {})
        if "box" in node:
            kind = blocks.LIBRARY.get(node["box"])
            by_key = {s.key: s for s in kind.settings} if kind else {}
            for key, value in (node.get("own") or {}).items():
                setting = by_key.get(key)
                if setting is not None and setting.number:
                    values[setting.number] = value
        return values

    def step(self, node: Optional[dict]):
        """Read with *node*'s own values laid over those of the frames it
        stands in, while it runs (`rules.STEP`); work it hands to other
        threads takes them along (`runner.run_each` copies the context).
        No node (a step of the preparation that is not drawn): the run's
        values."""
        if node is None:
            return contextlib.nullcontext()
        return rules.in_step(rules.stepped(node, self.own_values(node)))

    # -- numbers and settings of a box ----------------------------------------

    def number(self, node: dict, key: str) -> int:
        """A number setting of a box: its own value, else that of a frame
        around it, else the named number of the flow as the run reads it (a
        setting of the run won over the file already, `flow.in_effect`)."""
        own = node.get("own") or {}
        if key in own:
            rules.noted(next(s for s in blocks.LIBRARY[node["box"]].settings
                             if s.key == key).number)
            return int(own[key])
        setting = next(s for s in blocks.LIBRARY[node["box"]].settings
                       if s.key == key)
        reader = self.reader
        name = setting.number
        stepped, value = rules.stepped_value(name)
        if stepped:
            return int(value)
        if name == "search_pieces":
            return reader.budget
        if name in ("search_tables", "search_figures", "search_text"):
            return reader.shares[{"search_tables": "table",
                                  "search_figures": "figure",
                                  "search_text": "section"}[name]]
        if name == "search_per_request":
            return reader.per_request
        return int(getattr(reader.numbers, name))

    @staticmethod
    def setting(node: Optional[dict], key: str, kind: str = ""):
        """A setting of a box: its own value, else its rule's, else its
        default. A box of *kind* that is not drawn (*node* None) has the
        rule's or the default."""
        sets = (node or {}).get("set") or {}
        if key in sets:
            return sets[key]
        setting = next(s for s in blocks.LIBRARY[
            node["box"] if node is not None else kind].settings
            if s.key == key)
        if setting.rule:
            return rules.get(setting.rule)
        return setting.default

    @contextlib.contextmanager
    def counted(self, doc):
        """The counts of one question, apart from the counts of the other
        questions asked side by side, so that what it came to (the
        follow-ups it took, why its finds were refused) is its own; they
        are added to the document's when it is through."""
        part = Counts()
        try:
            yield part
        finally:
            with doc.counts.lock:
                doc.counts.asked.update(part.asked)
                doc.counts.failed.update(part.failed)
                doc.counts.questions += part.questions

    @staticmethod
    def came_to(part: Counts) -> dict:
        """What a question's own counts say of its answer (`Answer`)."""
        return {"follow_ups": part.asked.get("follow", 0),
                "refusal": refusal_of(part.failed)}

    def shares_of(self, node: dict) -> dict:
        return {"table": self.number(node, "tables"),
                "figure": self.number(node, "figures"),
                "section": self.number(node, "text")}

    # -- facts for conditions -------------------------------------------------

    def facts(self, scope: Scope, got: Optional[Found] = None
              ) -> conditions.Facts:
        """What a condition can know at *scope*; *got* is the find an own
        check is looking at."""
        reader = self.reader

        def get(subject: str, prop: str):
            doc: Doc = scope.get("doc")
            plan = doc.plan if doc is not None else scope.get("plan")
            coord: Optional[CoordItem] = scope.get("coord")
            value: Optional[ValueItem] = scope.get("value")
            parameter = scope.get("parameter")
            if subject == "document":
                if prop == "works":
                    return "work" in plan.names
                if prop == "plan_years":
                    return bool(plan.bases)
                if prop == "pieces":
                    return len(plan.chunks)
                if prop in ("language", "pages", "title"):
                    return self.about_document(doc, plan)[prop]
                if prop == "requests":
                    return sum(doc.counts.asked.values()) \
                        if doc is not None else 0
                if prop == "seconds":
                    return time.monotonic() - doc.started \
                        if doc is not None else 0
            if subject == conditions.VAR:
                return general.get(scope, prop)
            if subject == "run":
                return doc.whole if doc is not None else True
            if subject == "round":
                return scope.get("round", 0)
            if subject == "field":
                if parameter is None:
                    raise LookupError("no field here")
                return {"has_list": reader.listed(parameter) is not None,
                        "numbers": parameter.is_numeric,
                        "once": bool(getattr(parameter, "once_per_document",
                                             False)),
                        "takes_group": group_taken(parameter),
                        "unit": parameter.unit_target or "",
                        "kind": parameter.value_type,
                        "rows": self.rows_read(doc, parameter)
                        if prop == "rows" else 0,
                        "name": parameter.uri}[prop]
            if subject == "value":
                row = coord.row if coord is not None else (
                    value.row if value is not None else None)
                if row is None:
                    raise LookupError("no value here")
                claim = row.claim
                words = str(claim.get("value_raw") or claim.get("value")
                            or "")
                read = coord.read if coord is not None else value.read
                at = claim.get("at") or {}
                owner = tuple(at.get("owner") or ())
                number = claim.get("value")
                return {"field": read.batch.parameter.uri, "words": words,
                        "length": len(words),
                        "scenario_name": bool(getattr(
                            read.batch.parameter, "merged", None)),
                        "passage": owner[0] if owner else "",
                        "in_table": bool(owner) and owner[0] == "table",
                        "in_text": bool(owner) and owner[0] == "section",
                        "number": number if isinstance(number, (int, float))
                        and not isinstance(number, bool) else 0,
                        "quote": str(claim.get("quote") or "")}[prop]
            if subject == "chunk":
                chunk = scope.get("chunk")
                if isinstance(chunk, list):
                    chunk = chunk[0] if chunk else None
                if chunk is None and coord is not None:
                    at = coord.row.claim.get("at") or {}
                    chunk = plan.chunk_of(
                        tuple(at.get("owner") or ()),
                        int(at.get("line") or 1),
                        coord.read.batch.parameter.is_numeric)
                if chunk is None:
                    raise LookupError("no chunk here")
                return chunk.passage.kind
            if subject == "coordinate":
                if coord is None:
                    raise LookupError("no coordinate here")
                slot, claim = coord.slot, coord.row.claim
                if prop == "name":
                    return slot.name
                if prop == "state":
                    return claim.get(f"{slot.name}_state") or ""
                if prop == "kind":
                    if slot.name == "quantity" and slot.is_closed:
                        return "quantity"
                    if slot.name == "work":
                        return "work"
                    if getattr(slot, "merged", None):
                        return "name"
                    if slot.kind == NUMBER:
                        return "number"
                    return "list" if slot.is_closed else "text"
                if prop == "own_only":
                    group = coord.group
                    own = slot.name in tuple(
                        getattr(group, "own_passage", ()) or ()) + tuple(
                        getattr(group, "own_value", ()) or ())
                    # An open unit is searched like an open dimension where
                    # the rule `unit_searched` is on.
                    return own and not (slot.name == fields.UNIT
                                        and rules.get("unit_searched"))
                if prop == "required":
                    return bool(getattr(slot, "keep", False))
                if prop == "year":
                    return slot.kind == NUMBER
                if prop == "closed_before":
                    return fields.closed(coord.before, claim)
                if prop == "plan_years":
                    return any(b.get("axis") == slot.name
                               for b in plan.bases)
            if subject == "pieces":
                supply = scope.get("supply")
                seen = coord.seen if coord is not None and coord.seen \
                    is not None else set()
                if prop == "shown":
                    return len(seen)
                if prop == "left":
                    if isinstance(supply, SearchSupply):
                        return supply.left(seen)
                    if isinstance(supply, ListSupply):
                        return supply.left()
                    return 0
                if prop == "never_shown":
                    numbers = coord.read.batch.parameter.is_numeric \
                        if coord is not None else False
                    return len([c for c in plan.pieces(numbers)
                                if c.key not in seen])
            if subject in ("answer", "quote"):
                answer = None
                if got is not None:
                    answer = Answer(True, 1, False, False, got.words or "",
                                    got.quote)
                    if coord is not None and got.source is not None:
                        own = tuple((coord.row.claim.get("at") or {})
                                    .get("owner") or ())
                        answer.other_passage = \
                            (got.source.owner_kind,
                             got.source.owner_id) != own
                else:
                    # The answer of the condition's own item, never one of
                    # an item around it: where no box of it asked (off, or
                    # passed by its condition), nothing came back.
                    answer = scope.owner().values.get("answer") \
                        or Answer(False)
                if subject == "answer":
                    return {"answered": answer.answered,
                            "zero": answer.zero, "finds": answer.finds,
                            "other_passage": answer.other_passage,
                            "words_empty": not answer.words.strip(),
                            "follow_ups_used": answer.follow_ups,
                            "refusal": answer.refusal}[prop]
                quote = answer.quote or ""
                return {"length": len(quote),
                        "lines": len([q for q in quote.split("\n")
                                      if q.strip()]),
                        "number": any(ch.isdigit() for ch in quote),
                        "year": bool(years_in(quote))}[prop]
            raise LookupError(f"{subject} {prop} is not known here")
        return conditions.Facts(get)

    def rows_read(self, doc, parameter) -> int:
        """How many values of the field the document's reads hold so far."""
        if doc is None:
            return 0
        return sum(len(read.claims) for read in doc.field_reads
                   + doc.find_reads
                   if read.batch.parameter.uri == parameter.uri)

    def about_document(self, doc, plan: Plan) -> dict:
        """What the document says of itself, made once per reading: its
        language, its pages and its title."""
        made = doc.about if doc is not None else {}
        if "language" not in made:
            texts = [source.text or "" for source in plan.sources][:200]
            pages = [(source.provenance or {}).get("page")
                     for source in plan.sources]
            context = self.reader.context(plan.document_id) or {}
            made.update(
                language=language_of(texts),
                pages=max([p for p in pages if isinstance(p, int)] or [0]),
                title=str(context.get("name") or ""))
        return made

    def holds(self, condition, scope: Scope) -> bool:
        if condition is None:
            return True
        return conditions.holds(condition, self.facts(scope))

    @staticmethod
    def figure_facts(source: Source) -> conditions.Facts:
        """What a condition of the transcribe box knows of a figure."""
        def size() -> tuple:
            try:
                from PIL import Image
                with Image.open(source.image_path) as image:
                    return image.size
            except Exception:
                return (0, 0)

        def get(subject: str, prop: str):
            if subject != "figure":
                raise LookupError(f"{subject} {prop} is not known here")
            if prop == "description":
                return source.text or ""
            if prop == "has_image":
                return bool(source.image_path)
            if prop == "page":
                page = (source.provenance or {}).get("page")
                return page if isinstance(page, int) else 0
            return size()[0 if prop == "image_width" else 1]
        return conditions.Facts(get)

    def included(self, sources: list) -> list:
        """The sources the document step reads: the kinds of passages of
        the rule `include_kinds`, on the pages of the rule `pages`."""
        kinds = set(rules.get("include_kinds"))
        pages = rules.get("pages")
        if len(kinds) == 3 and pages is None:
            return sources
        out = []
        for source in sources:
            if source.owner_kind not in kinds:
                continue
            if pages is not None:
                page = (source.provenance or {}).get("page")
                if not isinstance(page, int) \
                        or not pages[0] <= page <= pages[1]:
                    continue
            out.append(source)
        return out

    # -- the document ---------------------------------------------------------

    def cut(self) -> addressed.Cut:
        """How the drawing cuts a document into pieces (its split box)."""
        node = self.split_node
        return addressed.Cut(
            lines=self.number_of_split("lines"),
            new_piece=self.setting(node, "new_piece", "split"),
            across=bool(self.setting(node, "across", "split")),
            table_head=bool(self.setting(node, "table_head", "split")),
            caption=bool(self.setting(node, "caption", "split")),
            figure_numbers=bool(self.setting(node, "figure_numbers",
                                             "split")),
            headings=self.number_of_split("headings"))

    def number_of_split(self, key: str) -> int:
        node = self.split_node
        own = (node or {}).get("own") or {}
        name = {"lines": "piece_lines", "headings": "headings"}[key]
        if key in own:
            rules.noted(name)
            return int(own[key])
        return flow_map.number(self.reader.numbers, name)

    def plan(self, document_id: int, sources: list, transcripts=None,
             each=None, numbers=None) -> tuple:
        """(Plan, Counts) of a document: its figures transcribed
        (*transcripts*), its pieces cut as the split box says, then the
        lists and what it settles (`prepare`)."""
        counts = Counts()
        with self.step(self.prepares.get("document")):
            sources = self.included(sources)
        node = self.prepares.get("transcribe")
        figures = [] if node is None else \
            [s for s in sources if s.owner_kind == "figure"]
        if figures and "when" in node:
            figures = [s for s in figures if conditions.holds(
                node["when"], self.figure_facts(s))]
        lines, asked = {}, 0
        if transcripts is not None and figures:
            with self.step(node), addressed.asking(
                    Asking(node["id"], follow_ups=self.follow_ups_of(node))):
                lines, asked = transcripts(document_id, figures, each)
        with self.step(self.split_node):
            cut = self.cut()
        with self.step(self.prepares.get("document")):
            plan = Plan(document_id, sources, lines,
                        numbers=numbers or self.reader.numbers, cut=cut,
                        cutting=lambda: self.step(self.split_node))
        if asked:
            counts.ask("transcribe", asked)
        self.prepare(plan, counts)
        return plan, counts

    def prepare(self, plan: Plan, counts: Counts) -> None:
        """The lists of the document and what it settles, as the drawing
        says."""
        if "lists" in self.prepares:
            with self.step(self.prepares["lists"]):
                self.reader.lists_of(plan)
        doc = Doc(plan, counts, [])
        scope = Scope(None, True, doc=doc, plan=plan)
        for frame in self.settled_frames:
            if not frame.get("off"):
                self.run_node(frame, scope)

    def read(self, plan: Plan, parameters: list, chunks=None,
             counts: Optional[Counts] = None,
             order_of: Optional[dict] = None,
             order_fields: Optional[Callable] = None) -> list:
        """[Read] of *parameters* in *plan*: one per field and passage it
        was read in. *chunks* are the pieces read: all where None, else a
        list, or {uri: list or None} per field; *order_of* {uri: [piece
        key]} the order each field reads them in, or *order_fields(located
        fields)* makes it where the drawing orders them (`sentences`)."""
        counts = counts or Counts()
        if "lists" in self.prepares:
            with self.step(self.prepares["lists"]):
                self.reader.lists_of(plan)
        doc = Doc(plan, counts, list(parameters), chunks,
                  dict(order_of or {}), order_fields)
        scope = Scope(None, True, doc=doc, plan=plan)
        for node in self.reading:
            self.run_node(node, scope)
        reader = self.reader
        for read in doc.find_reads:
            if not read.claims and read.lost:
                read.unread = True
                read.why = read.lost[0]
                read.lost = []
            reader._traced("read", plan.document_id,
                           parameter=read.batch.parameter.uri,
                           kind=read.batch.items[0].source.owner_kind,
                           owner=read.batch.items[0].source.owner_id,
                           values=len(read.claims), asked=read.asked,
                           failed=dict(read.failed),
                           unanswered=read.unanswered,
                           **({"unread": True, "why": read.why}
                              if read.unread else {}))
        return doc.reads + doc.find_reads

    def coordinate(self, plan: Plan, read: Read, row: Row, group, slot,
                   counts: Counts, clone: Callable) -> list:
        """One coordinate of one value asked as the drawing's frame of
        coordinates asks it (a pass over a stored harvest,
        `surveyed.SurveyedHarvest.sweep`): [the rows made beside it]."""
        if self.sweep_frame is None:
            return []
        doc = Doc(plan, counts, [read.batch.parameter])
        scope = Scope(None, True, doc=doc, plan=plan)
        value = ValueItem(read, row, [row], clone)
        vscope = scope.child(True, value=value,
                             parameter=read.batch.parameter)
        item = CoordItem(read, row, slot, group, [], clone)
        cscope = vscope.child(True, coord=item)
        if self.holds(self.sweep_frame.get("when"), cscope):
            self.run_steps(self.sweep_frame.get("steps") or [], cscope)
        return item.made

    # -- running the drawing --------------------------------------------------

    def run_steps(self, steps: list, scope: Scope) -> None:
        for node in steps:
            if isinstance(node, dict) and not node.get("off"):
                self.run_node(node, scope)

    def run_node(self, node: dict, scope: Scope) -> None:
        kind = flow_map.kind_of(node)
        if kind == "box":
            kind = blocks.LIBRARY[node["box"]]
            if kind.attached:
                return          # applied by the question before it
            with self.step(node):
                if "when" in node and not self.holds(node["when"], scope):
                    return
                # A box of a profile runs the code its profile gives it
                # (`blocks.Box.run`), one of the core the engine's own.
                if kind.run is not None:
                    kind.run(self, node, scope)
                else:
                    getattr(self, f"box_{node['box']}")(node, scope)
        elif kind == "each":
            with self.step(node):
                self.each(node, scope)
        elif kind == "round":
            with self.step(node):
                self.round(node, scope)
        elif kind == "if":
            with self.step(node):
                for way in node.get("if") or []:
                    if self.holds(way.get("when"), scope):
                        self.run_steps(way.get("steps") or [], scope)
                        return
                self.run_steps(node.get("else") or [], scope)

    def round(self, node: dict, scope: Scope) -> None:
        spec = node.get("round") or {}
        most = spec.get("most")
        # Where a round that has a most of its own may go on after a turn
        # that reached no question; one without a most always ends there,
        # so that it cannot run for ever.
        goes_on = rules.get("round_ends") == "supply_used_up" \
            and most is not None
        number = 0
        while most is None or number < most:
            number += 1
            turn = scope.child(False, round=number, used_up=False,
                               drew=False)
            self.run_steps(node.get("steps") or [], turn)
            if turn.values.get("used_up"):
                return
            if "stop" in node and self.holds(node["stop"], turn):
                return
            # A turn that showed nothing of the supply (its question was
            # passed by its condition) cannot use it up: the round ends.
            if spec.get("supply") and not turn.values.get("drew") \
                    and not goes_on:
                return

    # -- each -----------------------------------------------------------------

    def items(self, node: dict, scope: Scope) -> list:
        """[(child scope values)] of the items *node* iterates at *scope*."""
        what = node["each"]
        if what == "list":
            return general.list_items(node, scope)
        doc: Doc = scope.get("doc")
        plan = doc.plan
        reader = self.reader
        if what == "settled":
            out = []
            year = next((slot for slot in reader.frame_slots
                         if slot.kind == NUMBER), None)
            for name in rules.get("settled_fields"):
                field_ = reader.plan_fields.get(name)
                if name == "settings":
                    if field_:
                        out.append(FieldItem(
                            "settings", field_shown_of(field_),
                            [field_.get("sentence") or field_["name"]],
                            settled=field_))
                elif name in ("base_year", "target_year"):
                    if field_ and year is not None:
                        out.append(FieldItem(
                            name, field_shown_of(field_),
                            [field_.get("sentence") or field_["name"]],
                            settled={**field_, "_year": year,
                                     "_state": name.split("_")[0]}))
                else:
                    parameter = next((p for p in reader.spec.parameters
                                      if p.uri == name), None)
                    if parameter is None:
                        raise Stop(f"settled_fields names {name!r}, which "
                                   f"is neither settings, base_year, "
                                   f"target_year nor a field of the spec")
                    out.append(FieldItem(
                        parameter.uri, None,
                        None, parameter.is_numeric,
                        reader.listed(parameter), parameter,
                        settled={"_field": True}))
            return [{"field_item": item} for item in out]
        if what == "field":
            which = node.get("which", "all")
            out = []
            for parameter in doc.parameters:
                once = bool(getattr(parameter, "once_per_document", False))
                if which == "once" and not once \
                        or which == "pieces" and once:
                    continue
                values = {"parameter": parameter}
                if once:
                    listed = reader.listed(parameter)
                    values["field_item"] = FieldItem(
                        parameter.uri, None,
                        None, parameter.is_numeric, listed, parameter)
                out.append(values)
            return out
        if what == "piece":
            parameter = scope.get("parameter")
            view = set(plan.pieces(parameter.is_numeric))
            chosen = [c for c in doc.pieces_of(parameter.uri) if c in view]
            pieces = chosen
            if node.get("order", "best_first") == "best_first":
                held = set(chosen)
                ranked = doc.order_of.get(parameter.uri) or []
                pieces = [plan.by_key[tuple(key)] for key in ranked
                          if tuple(key) in plan.by_key
                          and plan.by_key[tuple(key)] in held]
                taken = set(pieces)
                pieces += [c for c in chosen if c not in taken]
            if not plan.groups:
                return [{"chunk": chunk} for chunk in pieces]
            # A piece of several passages is asked once, where its first
            # chunk the field reads stands in the order.
            out, asked = [], set()
            for chunk in pieces:
                group = plan.group_of.get(chunk.key)
                if group is None:
                    out.append({"chunk": chunk})
                    continue
                if id(group) in asked:
                    continue
                asked.add(id(group))
                members = [c for c in group if c in view]
                out.append({"chunk": members if len(members) > 1
                            else members[0]})
            return out
        raise Stop(f"each {what} is iterated where it stands")

    def each(self, node: dict, scope: Scope) -> None:
        what = node["each"]
        if what == "value":
            return self.each_value(node, scope)
        if what == "coordinate":
            return self.each_coordinate(node, scope)
        jobs = []
        for values in self.items(node, scope):
            child = scope.child(True, **values)
            if self.holds(node.get("when"), child):
                jobs.append((node, child))
        steps = node.get("steps") or []
        inner = steps[0] if len(steps) == 1 and isinstance(steps[0], dict) \
            else None
        if node.get("together") and inner is not None \
                and inner.get("each") and inner.get("together") \
                and not inner.get("off"):
            # One pool: each item of this frame with each of its own; or,
            # where the rule says so, the items of this frame side by side
            # and each one's own items one after the other.
            by_child, pooled = [], []
            with self.step(inner):
                for _node, child in jobs:
                    own = []
                    for values in self.items(inner, child):
                        grand = child.child(True, **values)
                        if self.holds(inner.get("when"), grand):
                            own.append(grand)
                    by_child.append(own)
                    pooled += own

            def run_inner(grand) -> None:
                with self.step(inner):
                    self.run_steps(inner.get("steps") or [], grand)
            if rules.get("together_pooled"):
                self.reader.each(pooled, run_inner)
            else:
                self.reader.each(
                    by_child, lambda own: [run_inner(g) for g in own])
            self.after_items(inner, pooled, scope)
            self.after_items(node, [child for _n, child in jobs], scope)
            return
        if node.get("together"):
            self.reader.each([child for _n, child in jobs],
                             lambda child: self.run_steps(steps, child))
        else:
            for _node, child in jobs:
                self.run_steps(steps, child)
        self.after_items(node, [child for _n, child in jobs], scope)

    def after_items(self, node: dict, done: list, scope: Scope) -> None:
        """What a frame does once its items are through: the finds of each
        piece become the reads of their field and passage, a field of the
        document its reads, what the document settles its trace."""
        what = node["each"]
        doc: Doc = scope.get("doc")
        plan = doc.plan
        if what == "piece":
            for child in done:
                for got in child.values.get("finds", ()):
                    parameter = child.get("parameter")
                    chunk = child.values["chunk"]
                    members = list(chunk) if isinstance(chunk, list) \
                        else [chunk]

                    def read_at(owner, source) -> Read:
                        key = (parameter.uri, owner)
                        read = doc.by_find.get(key)
                        if read is None:
                            read = doc.by_find[key] = Read(Batch(
                                plan.document_id, parameter,
                                [WorkItem(plan.document_id, parameter,
                                          source)],
                                spec=self.reader.spec), [])
                            doc.find_reads.append(read)
                        return read

                    def read_of(member) -> Read:
                        return read_at(member.owner, member.passage.source)
                    first = read_of(members[0])
                    by_owner = {member.owner: member for member in members}
                    first.asked += got["asked"]
                    # Found in another passage of the document, which is
                    # its place (`addressed.Found.elsewhere`, owner
                    # decision 2026-11-12).
                    elsewhere = {id(claim)
                                 for claim in got.get("elsewhere", ())}
                    for claim in got["claims"]:
                        owner = tuple((claim.get("at") or {}).get("owner")
                                      or ())
                        passage = plan.passages.get(owner)
                        if id(claim) in elsewhere and passage is not None \
                                and owner not in by_owner:
                            read_at(owner, passage.source).claims \
                                .append(claim)
                            continue
                        read_of(by_owner.get(owner, members[0])).claims \
                            .append(claim)
                    first.lost.extend(got["lost"])
                    for why, n in got["failed"].items():
                        first.failed[why] = first.failed.get(why, 0) + n
        elif what == "field":
            for child in done:
                item: Optional[FieldItem] = child.values.get("field_item")
                if item is None or item.parameter is None \
                        or item.asked_by is None:
                    continue
                out = self.field_reads(item, child)
                lost = None if item.found else item.lost
                if not out and lost:
                    source = self.hole_source(plan, item)
                    out.append(Read(Batch(plan.document_id, item.parameter,
                                          [WorkItem(plan.document_id,
                                                    item.parameter, source)],
                                          spec=self.reader.spec), [],
                                    unread=True, why=lost))
                self.reader._traced(
                    "docfield", plan.document_id, parameter=item.key,
                    values=sum(len(r.claims) for r in out),
                    **({"why": lost} if lost else {}))
                doc.reads.extend(out)
                doc.field_reads.extend(out)
        elif what == "settled":
            self.reader._traced(
                "settled", plan.document_id, settings=len(plan.settings),
                base=[b["year"] for b in plan.bases if b["state"] == "base"],
                target=[b["year"] for b in plan.bases
                        if b["state"] == "target"])

    @staticmethod
    def hole_source(plan: Plan, item: FieldItem) -> Source:
        """The passage the hole of a field read nothing of names (rule
        `hole_passage`)."""
        sources = plan.sources
        where = rules.get("hole_passage")
        if where == "first_asked" and item.first_source is not None:
            return item.first_source
        if where == "last_passage" and sources:
            return sources[-1]
        return sources[0] if sources else Source("section", 0, "")

    def field_reads(self, item: FieldItem, scope: Scope) -> list:
        """The reads of a field of the document: one per passage a value of
        it was found in, made once from what its questions found."""
        if item.reads is not None:
            return item.reads
        doc: Doc = scope.get("doc")
        plan = doc.plan
        reads: dict = {}
        with addressed.asking(Asking(item.asked_by)):
            for got in item.found:
                source = got.source
                owner = (source.owner_kind, source.owner_id)
                got.passage = got.passage or plan.passages.get(owner)
                claim = self.reader.claim(plan, item.parameter, got,
                                          doc.counts)
                if claim is None:
                    continue
                read = reads.get(owner)
                if read is None:
                    read = reads[owner] = Read(Batch(
                        plan.document_id, item.parameter,
                        [WorkItem(plan.document_id, item.parameter,
                                  got.passage.source)],
                        spec=self.reader.spec), [])
                read.claims.append(claim)
        item.reads = list(reads.values())
        return item.reads

    def each_value(self, node: dict, scope: Scope) -> None:
        """Every value of the reads at *scope* (a field's, else the finds of
        the document) through the frame's steps; each read's claims become
        the rows its values came to."""
        doc: Doc = scope.get("doc")
        item: Optional[FieldItem] = scope.get("field_item")
        if item is not None and item.parameter is not None:
            reads = self.field_reads(item, scope)
        elif scope.get("parameter") is not None:
            uri = scope.get("parameter").uri
            reads = [r for r in doc.find_reads
                     if r.batch.parameter.uri == uri]
        else:
            # At the top: every value of the finds, and of the fields of the
            # document no frame inside their field went through; a second
            # frame of values, or a round around one, is a second pass.
            reads = [r for r in doc.field_reads
                     if doc.valued.get(id(r)) != "field"] + doc.find_reads
        inside_field = scope.get("field_item") is not None
        order = node.get("order")
        if (order == "names_first") if order is not None \
                else rules.get("names_first"):
            parts = [[r for r in reads
                      if bool(getattr(r.batch.parameter, "merged", None))
                      == first] for first in (True, False)]
        else:
            parts = [reads]
        steps = node.get("steps") or []
        for part in parts:
            values = []
            for read in part:
                for i, claim in enumerate(read.claims):
                    row = Row(row_label(i), 0, claim)
                    values.append(self.value_scope(scope, read, row))
            values = [v for v in values if self.holds(node.get("when"), v)]
            if node.get("together"):
                self.reader.each(values, lambda v: self.run_steps(steps, v))
            else:
                for v in values:
                    self.run_steps(steps, v)
            per_read: dict = collections.defaultdict(list)
            for v in values:
                per_read[id(v.values["value"].read)].extend(
                    v.values["value"].rows)
            for read in part:
                rows = per_read.get(id(read), [])
                slots = slots_of(self.reader.spec, read.batch.parameter)
                link_ranges(rows, slots)
                read.unanswered = mark_unanswered(rows, slots)
                read.claims = [row.claim for row in rows]
                if inside_field:
                    doc.valued[id(read)] = "field"

    def value_scope(self, scope: Scope, read: Read, row: Row) -> Scope:
        made = {"n": 0}

        def clone(one: Row) -> Row:
            made["n"] += 1
            return Row(f"{one.label}.{made['n']}", one.item_index,
                       copy.deepcopy(one.claim))
        return scope.child(True, value=ValueItem(read, row, [row], clone),
                           parameter=read.batch.parameter)

    def each_coordinate(self, node: dict, scope: Scope) -> None:
        """Each coordinate of the value, in the order of the spec's groups,
        for the value's row and every row made beside it."""
        value: ValueItem = scope.get("value")
        parameter = value.read.batch.parameter
        slots = slots_of(self.reader.spec, parameter)
        before: list = []
        steps = node.get("steps") or []
        sequence = [(group, slot)
                    for group, group_slots in groups_of(self.reader.spec,
                                                        slots)
                    for slot in in_group_order(group, group_slots)]
        named = {name: i for i, name in
                 enumerate(rules.get("coordinate_order"))}
        if named:
            sequence = sorted(
                (one for one in sequence if one[1].name in named),
                key=lambda one: named[one[1].name]) + [
                one for one in sequence if one[1].name not in named]
        for group, slot in sequence:
            for one in list(value.rows):
                item = CoordItem(value.read, one, slot, group,
                                 list(before), value.clone,
                                 seen_of=scope.get("doc").seen_of)
                child = scope.child(True, coord=item)
                if self.holds(node.get("when"), child):
                    self.run_steps(steps, child)
                value.rows += item.made
            before.append(slot)

    # -- the boxes ------------------------------------------------------------

    def box_settle(self, node: dict, scope: Scope) -> None:
        """What a thing the document settles came to, kept for every
        request after it."""
        item: FieldItem = scope.get("field_item")
        plan = scope.get("doc").plan
        if item.key == "settings" or item.settled.get("_field"):
            lines: list = list(plan.settings)
            for got in item.found:
                for line, source in got.lines:
                    if all(line is not one for one, _ in lines):
                        lines.append((line, source))
            plan.settings = lines
            return
        year, state = item.settled["_year"], item.settled["_state"]
        for got in item.found:
            numbers = years_in(got.words)
            if rules.get("settled_years_taken") == "first":
                numbers = numbers[:1]
            for number in numbers:
                value = int(number)
                if any(b["state"] == state and b["year"] == value
                       for b in plan.bases):
                    continue
                plan.bases.append({
                    "state": state, "axis": year.name, "year": value,
                    "quote": got.quote,
                    "source": [got.source.owner_kind, got.source.owner_id],
                    "index": len(plan.bases)})

    def box_order(self, node: dict, scope: Scope) -> None:
        """The supply of the item: its pieces best first for its sentence,
        the budget of them by kind, those already shown left out."""
        with addressed.asking(Asking(node["id"])):
            self._order(node, scope)

    def _order(self, node: dict, scope: Scope) -> None:
        reader = self.reader
        doc: Doc = scope.get("doc")
        plan = doc.plan
        coord: Optional[CoordItem] = scope.get("coord")
        shares = self.shares_of(node)
        budget = self.number(node, "pieces")
        if coord is not None:
            numbers = coord.read.batch.parameter.is_numeric
            self.locate(coord, plan)
            sentence = coord.sentence if coord.sentence is not None \
                else reader.field_sentence(plan, coord.read, coord.slot)
            # The pieces an earlier order of this coordinate showed stay out
            # of its budget; those beside it and its own stay in, as they
            # always have, and are left out where they are shown.
            pieces = [c for c in plan.pieces(numbers)
                      if c.key not in coord.ordered]

            def ranked() -> list:
                return reader.shown_order(plan, [sentence], pieces, budget,
                                          shares)
            def reordered(left: list) -> list:
                again = coord.sentence if coord.sentence is not None \
                    else sentence
                return reader.rerank_left(plan, [again], left)
            supply = SearchSupply([], ranked, "found", budget, reordered)
            supply.fetched, coord.fetched = coord.fetched, []
            scope.put("supply", supply)
            return
        item: FieldItem = scope.get("field_item")
        if item.sentences is None:
            item.sentences = list(reader.probes(
                item.parameter, plan.document_id) or ()) \
                or [item.parameter.label]
        pieces = plan.pieces(item.numbers)
        factor = self.number(node, "factor") \
            if item.listed and self.setting(node, "list_factor") else 1
        order = reader.shown_order(plan, list(item.sentences), pieces,
                                   budget * factor, shares)
        if self.setting(node, "rest_after"):
            taken = set(order)
            order += [c for c in reader.search_order(
                plan.document_id, list(item.sentences), pieces)
                if c not in taken]
        scope.put("supply", ListSupply(order))

    def box_beside(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        plan = scope.get("doc").plan
        self.locate(coord, plan)
        numbers = coord.read.batch.parameter.is_numeric
        first = plan.beside(coord.chunk, numbers) \
            if coord.chunk is not None else []
        supply = SearchSupply(first, None, "near")
        # What the answer at the value's own place asked to see comes first,
        # before the pieces beside it (owner decision 2026-11-12).
        supply.fetched, coord.fetched = coord.fetched, []
        scope.put("supply", supply)

    @staticmethod
    def locate(coord: CoordItem, plan: Plan) -> None:
        """The piece the value stands in, shown first so that no search
        shows it again."""
        if coord.located:
            return
        coord.located = True
        numbers = coord.read.batch.parameter.is_numeric
        at = coord.row.claim.get("at") or {}
        coord.chunk = plan.chunk_of(tuple(at.get("owner") or ()),
                                    int(at.get("line") or 1), numbers)
        coord.seen = {coord.chunk.key} if coord.chunk is not None \
            and rules.get("search_skips_own_piece") else set()
        if coord.seen_of is not None:
            # The pieces shown for this coordinate in an earlier pass of a
            # round around it are not shown again.
            key = (id(coord.read), coord.row.label, coord.slot.name)
            coord.seen, coord.ordered = coord.seen_of.setdefault(
                key, (coord.seen, coord.ordered))

    def asking_of(self, node: dict, scope: Scope, steps_after: list
                  ) -> Asking:
        """What a question asks with: its box, the boxes after it that check
        its answers (the place of a find, own checks)."""
        about, about_node, checks = None, None, []
        for after in steps_after:
            if flow_map.kind_of(after) != "box":
                break
            kind = blocks.LIBRARY.get(after.get("box"))
            if kind is None or not kind.attached:
                break
            if after.get("off"):
                continue
            if kind.type == "about":
                about, about_node = after["id"], after
            elif kind.type == "check":
                checks.append((self.setting(after, "name"),
                               self.setting(after, "refuse"),
                               self.setting(after, "sentence"), after["id"]))
        engine = self

        def refused(got: Found) -> Optional[tuple]:
            for name, condition, sentence, _ident in checks:
                if conditions.holds(condition, engine.facts(scope, got)):
                    return f"check:{name}", sentence
            return None
        return Asking(node["id"], about, refused if checks else None,
                      self.follow_ups_of(node),
                      about_step=(lambda n=about_node: engine.step(n))
                      if about_node is not None else None)

    def own_checks(self, node: dict) -> list:
        """[(name, condition, sentence, id)] of the own checks that stand
        right after *node* and are on."""
        out = []
        for after in self.after(node):
            if flow_map.kind_of(after) != "box":
                break
            kind = blocks.LIBRARY.get(after.get("box"))
            if kind is None or not kind.attached:
                break
            if after.get("off") or kind.type != "check":
                continue
            out.append((self.setting(after, "name"),
                        self.setting(after, "refuse"),
                        self.setting(after, "sentence"), after["id"]))
        return out

    def keep(self, doc: Doc, parameter, claims: list) -> None:
        """Each value a general step read of *parameter* in the read of its
        field and passage, as a find's are (`after_items`)."""
        plan = doc.plan
        for claim in claims:
            owner = tuple((claim.get("at") or {}).get("owner") or ())
            passage = plan.passages.get(owner)
            if passage is None:
                continue
            key = (parameter.uri, owner)
            with doc.counts.lock:
                read = doc.by_find.get(key)
                if read is None:
                    read = doc.by_find[key] = Read(Batch(
                        plan.document_id, parameter,
                        [WorkItem(plan.document_id, parameter,
                                  passage.source)],
                        spec=self.reader.spec), [])
                    doc.find_reads.append(read)
                read.claims.append(claim)

    def follow_ups_of(self, node: dict) -> Optional[int]:
        """The box's own number of follow-ups, None for the flow's."""
        kind = blocks.LIBRARY[node["box"]]
        if any(s.key == "follow_ups" for s in kind.settings):
            return self.number(node, "follow_ups")
        return None

    def box_docfield(self, node: dict, scope: Scope) -> None:
        reader = self.reader
        doc: Doc = scope.get("doc")
        plan = doc.plan
        item: FieldItem = scope.get("field_item")
        supply: ListSupply = scope.get("supply")
        size = self.number(node, "per_request")
        taken = supply.take(size) if supply is not None else None
        if taken is None:
            scope.used_up()
            return
        first, batch = taken
        scope.drew()
        item.asked_by = node["id"]
        if item.shown is None:
            # Built here, in the step of the box that asks, so that the
            # rule `field_text` is the box's own.
            item.shown = field_shown(item.parameter)
        if item.first_source is None and batch:
            item.first_source = batch[0].passage.source
        with addressed.asking(self.asking_of(node, scope,
                                             self.after(node))), \
                self.counted(doc) as part:
            got = reader.ask_window(
                plan, item.shown, batch, part, item.key,
                numbers=item.numbers, listed=item.listed,
                title_page=first and bool(self.setting(node, "title_page")))
        held, lost, more = got
        if more:
            # What the answer asked to see comes first in the field's next
            # request (owner decision 2026-11-12).
            supply.fetched = reader.fetch(plan, more, batch, supply.seen,
                                          item.numbers)
        if lost is not None:
            item.lost = item.lost or lost
        # The finds of the parts that were read count even where another
        # part of the window was a hole (as a `find` does).
        item.found = joined(item.found, held)
        scope.put("answer", Answer(lost is None or bool(held), len(held),
                                   not held, False,
                                   held[0].words if held else "",
                                   held[0].quote if held else "",
                                   **self.came_to(part)))

    def after(self, node: dict) -> list:
        """The steps after *node* in its list of steps."""
        return self._after.get(node["id"], [])

    @property
    def _after(self) -> dict:
        cached = getattr(self, "_after_cache", None)
        if cached is None:
            cached = {}
            for parent, _frames in flow_map.walk(self.tree):
                for _label, steps in flow_map.children(parent):
                    for i, one in enumerate(steps):
                        if isinstance(one, dict):
                            cached[one.get("id")] = steps[i + 1:]
            for i, one in enumerate(self.tree):
                if isinstance(one, dict):
                    cached[one.get("id")] = self.tree[i + 1:]
            self._after_cache = cached
        return cached

    def box_find(self, node: dict, scope: Scope) -> None:
        doc: Doc = scope.get("doc")
        parameter = scope.get("parameter")
        chunk = scope.get("chunk")
        with addressed.asking(self.asking_of(node, scope,
                                             self.after(node))), \
                self.counted(doc) as part:
            got = self.reader.find(doc.plan, parameter, chunk, part)
        owner = scope.owner()
        owner.values.setdefault("finds", []).append(got)
        owner.values["answer"] = Answer(
            not got["lost"] or bool(got["claims"]), len(got["claims"]),
            not got["claims"], False,
            str((got["claims"][0].get("value_raw")
                 or got["claims"][0].get("value") or "")
                if got["claims"] else ""),
            got["claims"][0].get("quote", "") if got["claims"] else "",
            **self.came_to(part))

    def box_sentences(self, node: dict, scope: Scope) -> None:
        doc: Doc = scope.get("doc")
        if doc.order_fields is None:
            return
        located = [p for p in doc.parameters
                   if not getattr(p, "once_per_document", False)]
        if located:
            with addressed.asking(Asking(
                    node["id"], follow_ups=self.follow_ups_of(node))):
                doc.order_of = dict(doc.order_fields(located) or {})

    # -- the boxes of a coordinate --------------------------------------------

    def coord_base(self, coord: CoordItem, plan: Plan) -> None:
        """What every request about the coordinate shows, made once."""
        if coord.payload is None:
            _shown, coord.payload, coord.noted = self.reader.coord_payload(
                plan, coord.read, coord.row, coord.slot)

    def box_coord(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        with addressed.asking(self.asking_of(node, scope,
                                             self.after(node))), \
                self.counted(doc) as part:
            answered, made, payload, noted, more = \
                self.reader.ask_own_place(doc.plan, coord.read, coord.row,
                                          coord.slot, part, coord.clone,
                                          coord.pictures)
        if payload is not None:
            coord.payload, coord.noted = payload, noted
        coord.made += made
        state = coord.row.claim.get(f"{coord.slot.name}_state")
        if more and state != READ:
            # What the answer at the value's own place asked to see comes
            # first in the search after it (owner decision 2026-11-12).
            self.locate(coord, doc.plan)
            if coord.chunk is not None:
                coord.fetched = self.reader.fetch(
                    doc.plan, more, [coord.chunk], coord.seen,
                    coord.read.batch.parameter.is_numeric)
        scope.put("answer", Answer(answered, 1 if state == READ else 0,
                                   state != READ, False,
                                   **self.came_to(part)))

    def box_phrase(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        anew = bool(self.setting(node, "anew")) \
            and scope.get("round", 1) >= rules.get("phrase_new_from_round") \
            and coord.sentences
        with addressed.asking(Asking(
                node["id"], follow_ups=self.follow_ups_of(node))):
            sentence = self.reader.search_sentence(
                doc.plan, coord.read, coord.row, coord.slot, doc.counts,
                before=list(coord.sentences) if anew else None)
        coord.sentence = sentence
        coord.sentences.append(sentence)
        if rules.get("search_with") != "phrase":
            coord.ways.append("search_with")

    def box_search(self, node: dict, scope: Scope) -> None:
        reader = self.reader
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        plan = doc.plan
        supply = scope.get("supply")
        self.locate(coord, plan)
        self.coord_base(coord, plan)
        if not isinstance(supply, SearchSupply):
            scope.used_up()
            return
        size = self.number(node, "per_request")
        batch, label = supply.take(size, coord.seen)
        if not batch:
            scope.used_up()
            return
        scope.drew()
        coord.seen.update(c.key for c in batch)
        if label == supply.label and supply.ranked is not None:
            coord.ordered.update(c.key for c in batch)
        numbers = coord.read.batch.parameter.is_numeric
        ways = sorted(set(coord.ways) | supply.ways)
        with addressed.asking(self.asking_of(node, scope,
                                             self.after(node))), \
                self.counted(doc) as part:
            made, held, more = reader.search_round(
                plan, coord.read, coord.row, coord.slot, coord.payload,
                batch, part, coord.clone, (supply.label, 1),
                {**coord.noted, "shows": label,
                 **addressed.second_ways(ways)}, coord.pictures)
        state = coord.row.claim.get(f"{coord.slot.name}_state")
        found = bool(held) or state == UNBACKED
        if found:
            coord.made += made
        if found and not rules.get("fetch_after_found"):
            supply.fetched = []
        else:
            supply.fetched = reader.fetch(
                plan, more, batch,
                {c.key for c in batch} if rules.get("show_twice")
                else coord.seen, numbers)
        scope.put("answer", Answer(True, 1 if held else 0, not held, False,
                                   **self.came_to(part)))

    def box_state(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        plan = scope.get("doc").plan
        key = f"{coord.slot.name}_state"
        mode = self.setting(node, "mode")
        if mode == "out_of_slice":
            coord.row.claim.setdefault(key, state_for("out_of_slice"))
        elif mode == "unstated":
            coord.row.claim[key] = state_for("unstated_after_combing")
        else:
            self.locate(coord, plan)
            numbers = coord.read.batch.parameter.is_numeric
            rest = any(c.key not in coord.seen
                       for c in plan.pieces(numbers))
            coord.row.claim[key] = state_for(
                "exhausted" if rest else "unstated_after_combing")

    # -- the general steps (`general`, owner decision 2026-11-12) ------------

    def box_ask(self, node: dict, scope: Scope) -> None:
        general.ask_step(self, node, scope)

    def box_retrieve(self, node: dict, scope: Scope) -> None:
        general.retrieve_step(self, node, scope)

    def box_rerank(self, node: dict, scope: Scope) -> None:
        general.rerank_step(self, node, scope)

    def box_set(self, node: dict, scope: Scope) -> None:
        general.set_step(self, node, scope)

    def box_filter(self, node: dict, scope: Scope) -> None:
        general.filter_step(self, node, scope)

    def box_merge(self, node: dict, scope: Scope) -> None:
        general.merge_step(self, node, scope)

    def box_python(self, node: dict, scope: Scope) -> None:
        general.python_step(self, node, scope)

    def step_of(self, kind: str):
        """The values of the top box of *kind* (one of `AFTER`), for
        the run that does it outside the engine (`runner`); no values where
        the drawing has none."""
        node = next((n for n in self.tree if isinstance(n, dict)
                     and n.get("box") == kind), None)
        return self.step(node) if node is not None \
            else contextlib.nullcontext()

    # Boxes the run does elsewhere: the preparation (`plan`, `prepare`) and
    # writing and computing (`runner`).
    def box_document(self, node, scope):
        return None

    box_transcribe = box_split = box_lists = box_write = box_compute = \
        box_catalogue = box_document


def compute_on(profile=None) -> bool:
    """Is the calculation after the reading on in the drawing of
    *profile*?"""
    return flow_map.compute_on(flow_map.tree_of(profile))


