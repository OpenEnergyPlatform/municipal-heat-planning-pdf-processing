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
import copy
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import addressed, blocks, conditions, fields
from . import flow as flow_map
from .addressed import (Asking, Counts, Found, Plan, Read, field_shown,
                        field_shown_of, joined, years_in)
from .fields import (EXHAUSTED, NUMBER, OUT_OF_SLICE, READ, SAID_UNSTATED,
                     UNBACKED)
from .pipeline import (Batch, Row, Source, WorkItem, mark_unanswered,
                       row_label)
from .reading import groups_of, in_group_order, link_ranges, slots_of


class Stop(Exception):
    """The drawing holds something the run cannot do; the check of the flow
    (`flow.problems`) refuses it before a run."""


# -- what a frame holds -----------------------------------------------------------

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
    shown: dict                     # the field as a request shows it
    sentences: list
    numbers: bool = False
    listed: Optional[tuple] = None
    parameter: object = None
    settled: Optional[dict] = None
    found: list = field(default_factory=list)
    lost: Optional[str] = None
    asked_by: Optional[str] = None  # the id of the box that asked it
    reads: Optional[list] = None


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


class ListSupply:
    """The pieces a field of the document is asked over: the title page with
    the first request, then the pieces in their order, a few a request."""

    def __init__(self, pieces: list):
        self.pieces = list(pieces)
        self.at = 0
        self.started = False

    def take(self, size: int):
        """(first request?, pieces) of the next request, None where the
        supply is used up."""
        if not self.started:
            self.started = True
            self.at = size
            return True, self.pieces[:size]
        if self.at >= len(self.pieces):
            return None
        batch = self.pieces[self.at:self.at + size]
        self.at += size
        return False, batch

    def left(self) -> int:
        return max(0, len(self.pieces) - self.at)


class SearchSupply:
    """The pieces a coordinate's search shows: the pieces it was given
    (*first*, shown together in the first request), then the pieces of its
    order a few at a time (*ranked*, made the first time it is needed), the
    pieces a reply fetched itself first in the next request; no piece twice
    (`seen`, the coordinate's)."""

    def __init__(self, first: list, ranked: Optional[Callable], label: str):
        self.first = list(first)
        self.ranked = ranked
        self.order: Optional[list] = None
        self.label = label
        self.fetched: list = []
        self.started = False

    def _ranked(self) -> list:
        if self.ranked is None:
            return []
        if self.order is None:
            self.order = list(self.ranked() or [None])
        return [c for c in self.order if c is not None]

    def take(self, size: int, seen: set) -> tuple:
        """(pieces, what they are: the supply's label or "fetched") of the
        next request; ([], None) where nothing is left."""
        if not self.started:
            self.started = True
            batch = [c for c in dict.fromkeys(self.fetched + self.first)
                     if c.key not in seen]
            label = self.label
        else:
            batch = [c for c in dict.fromkeys(self.fetched)
                     if c.key not in seen]
            label = "fetched"
        self.fetched = []
        if not batch:
            left = [c for c in self._ranked() if c.key not in seen]
            if not left:
                return [], None
            batch, label = left[:size], self.label
        return batch, label

    def left(self, seen: set) -> int:
        return len([c for c in self._ranked() if c.key not in seen]) \
            + len([c for c in self.first if c.key not in seen])


@dataclass
class Answer:
    """What the last question of an item came to."""
    answered: bool = False
    finds: int = 0
    zero: bool = True
    other_passage: bool = False
    words: str = ""
    quote: str = ""


# -- the engine --------------------------------------------------------------------

class Engine:
    """The drawing *tree* of a flow done for documents with the reading
    *reader* (`addressed.Reader`)."""

    def __init__(self, reader, tree: Optional[list] = None):
        self.reader = reader
        self.tree = tree if tree is not None else flow_map.tree_of(None)
        said = flow_map.problems(self.tree)
        if said:
            raise Stop("; ".join((f"{p['id']}: " if p["id"] else "")
                                 + p["message"] for p in said[:3]))
        top = [node for node in self.tree if isinstance(node, dict)]
        prepares = [n for n in top if n.get("box") in flow_map.PREPARES]
        self.split_node = next(n for n in prepares if n["box"] == "split")
        self.transcribe_id = next(n["id"] for n in prepares
                                  if n["box"] == "transcribe")
        self.settled_frames = [n for n in top if n.get("each") == "settled"]
        self.reading = [n for n in top if n.get("box") not in
                        flow_map.PREPARES + ("write", "compute")
                        and n.get("each") != "settled"]
        values = [n for n in top if n.get("each") == "value"]
        self.sweep_frame = next(
            (child for frame in values for child in frame.get("steps") or []
             if child.get("each") == "coordinate"), None)
        if self.sweep_frame is None:
            self.sweep_frame = next((n for n, _ in flow_map.walk(self.tree)
                                     if n.get("each") == "coordinate"), None)

    # -- numbers and settings of a box -------------------------------------------

    def number(self, node: dict, key: str) -> int:
        """A number setting of a box: its own value, else the named number
        of the flow as the run reads it (a setting of the run won over the
        file already, `flow.in_effect`)."""
        own = node.get("own") or {}
        if key in own:
            return int(own[key])
        setting = next(s for s in blocks.LIBRARY[node["box"]].settings
                       if s.key == key)
        reader = self.reader
        name = setting.number
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
    def setting(node: dict, key: str):
        sets = node.get("set") or {}
        if key in sets:
            return sets[key]
        setting = next(s for s in blocks.LIBRARY[node["box"]].settings
                       if s.key == key)
        return setting.default

    def shares_of(self, node: dict) -> dict:
        return {"table": self.number(node, "tables"),
                "figure": self.number(node, "figures"),
                "section": self.number(node, "text")}

    # -- facts for conditions ----------------------------------------------------

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
                        "takes_group": bool(getattr(parameter,
                                                    "takes_group", False)),
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
                return {"field": read.batch.parameter.uri, "words": words,
                        "length": len(words),
                        "scenario_name": bool(getattr(
                            read.batch.parameter, "merged", None)),
                        "passage": owner[0] if owner else ""}[prop]
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
                    return slot.name in tuple(
                        getattr(group, "own_passage", ()) or ()) + tuple(
                        getattr(group, "own_value", ()) or ())
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
                            "words_empty": not answer.words.strip()}[prop]
                quote = answer.quote or ""
                return {"length": len(quote),
                        "lines": len([q for q in quote.split("\n")
                                      if q.strip()]),
                        "number": any(ch.isdigit() for ch in quote),
                        "year": bool(years_in(quote))}[prop]
            raise LookupError(f"{subject} {prop} is not known here")
        return conditions.Facts(get)

    def holds(self, condition, scope: Scope) -> bool:
        if condition is None:
            return True
        return conditions.holds(condition, self.facts(scope))

    # -- the document --------------------------------------------------------------

    def cut(self) -> addressed.Cut:
        """How the drawing cuts a document into pieces (its split box)."""
        node = self.split_node
        return addressed.Cut(
            lines=self.number_of_split("lines"),
            new_piece=self.setting(node, "new_piece"),
            across=bool(self.setting(node, "across")),
            table_head=bool(self.setting(node, "table_head")),
            caption=bool(self.setting(node, "caption")),
            figure_numbers=bool(self.setting(node, "figure_numbers")),
            headings=self.number_of_split("headings"))

    def number_of_split(self, key: str) -> int:
        node = self.split_node
        own = node.get("own") or {}
        if key in own:
            return int(own[key])
        name = {"lines": "piece_lines", "headings": "headings"}[key]
        return int(getattr(self.reader.numbers, name))

    def plan(self, document_id: int, sources: list, transcripts=None,
             each=None, numbers=None) -> tuple:
        """(Plan, Counts) of a document: its figures transcribed
        (*transcripts*), its pieces cut as the split box says, then the
        lists and what it settles (`prepare`)."""
        counts = Counts()
        figures = [s for s in sources if s.owner_kind == "figure"]
        lines, asked = {}, 0
        if transcripts is not None and figures:
            with addressed.asking(Asking(self.transcribe_id)):
                lines, asked = transcripts(document_id, figures, each)
        plan = Plan(document_id, sources, lines,
                    numbers=numbers or self.reader.numbers, cut=self.cut())
        if asked:
            counts.ask("transcribe", asked)
        self.prepare(plan, counts)
        return plan, counts

    def prepare(self, plan: Plan, counts: Counts) -> None:
        """The lists of the document and what it settles, as the drawing
        says."""
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

    # -- running the drawing ---------------------------------------------------------

    def run_steps(self, steps: list, scope: Scope) -> None:
        for node in steps:
            if isinstance(node, dict) and not node.get("off"):
                self.run_node(node, scope)

    def run_node(self, node: dict, scope: Scope) -> None:
        kind = flow_map.kind_of(node)
        if kind == "box":
            if blocks.LIBRARY[node["box"]].attached:
                return          # applied by the question before it
            if "when" in node and not self.holds(node["when"], scope):
                return
            getattr(self, f"box_{node['box']}")(node, scope)
        elif kind == "each":
            self.each(node, scope)
        elif kind == "round":
            self.round(node, scope)
        elif kind == "if":
            for way in node.get("if") or []:
                if self.holds(way.get("when"), scope):
                    self.run_steps(way.get("steps") or [], scope)
                    return
            self.run_steps(node.get("else") or [], scope)

    def round(self, node: dict, scope: Scope) -> None:
        spec = node.get("round") or {}
        most = spec.get("most")
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
            if spec.get("supply") and not turn.values.get("drew"):
                return

    # -- each -------------------------------------------------------------------------

    def items(self, node: dict, scope: Scope) -> list:
        """[(child scope values)] of the items *node* iterates at *scope*."""
        what = node["each"]
        doc: Doc = scope.get("doc")
        plan = doc.plan
        reader = self.reader
        if what == "settled":
            out = []
            field_ = reader.plan_fields.get("settings")
            if field_:
                out.append(FieldItem("settings", field_shown_of(field_),
                                     [field_.get("sentence")
                                      or field_["name"]], settled=field_))
            year = next((slot for slot in reader.frame_slots
                         if slot.kind == NUMBER), None)
            for state in ("base", "target"):
                field_ = reader.plan_fields.get(f"{state}_year")
                if field_ and year is not None:
                    out.append(FieldItem(f"{state}_year",
                                         field_shown_of(field_),
                                         [field_.get("sentence")
                                          or field_["name"]],
                                         settled={**field_, "_year": year,
                                                  "_state": state}))
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
                        parameter.uri, field_shown(parameter, full=True),
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
            # One pool: each item of this frame with each of its own.
            pooled = []
            for _node, child in jobs:
                for values in self.items(inner, child):
                    grand = child.child(True, **values)
                    if self.holds(inner.get("when"), grand):
                        pooled.append(grand)
            self.reader.each(pooled, lambda grand: self.run_steps(
                inner.get("steps") or [], grand))
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

                    def read_of(member) -> Read:
                        key = (parameter.uri, member.owner)
                        read = doc.by_find.get(key)
                        if read is None:
                            read = doc.by_find[key] = Read(Batch(
                                plan.document_id, parameter,
                                [WorkItem(plan.document_id, parameter,
                                          member.passage.source)],
                                spec=self.reader.spec), [])
                            doc.find_reads.append(read)
                        return read
                    first = read_of(members[0])
                    by_owner = {member.owner: member for member in members}
                    first.asked += got["asked"]
                    for claim in got["claims"]:
                        owner = tuple((claim.get("at") or {}).get("owner")
                                      or ())
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
                    source = plan.sources[0] if plan.sources \
                        else Source("section", 0, "")
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
        if node.get("order", "names_first") == "names_first":
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
        for group, group_slots in groups_of(self.reader.spec, slots):
            for slot in in_group_order(group, group_slots):
                for one in list(value.rows):
                    item = CoordItem(value.read, one, slot, group,
                                     list(before), value.clone,
                                     seen_of=scope.get("doc").seen_of)
                    child = scope.child(True, coord=item)
                    if self.holds(node.get("when"), child):
                        self.run_steps(steps, child)
                    value.rows += item.made
                before.append(slot)

    # -- the boxes ----------------------------------------------------------------------

    def box_settle(self, node: dict, scope: Scope) -> None:
        """What a thing the document settles came to, kept for every
        request after it."""
        item: FieldItem = scope.get("field_item")
        plan = scope.get("doc").plan
        if item.key == "settings":
            lines: list = []
            for got in item.found:
                for line, source in got.lines:
                    if all(line is not one for one, _ in lines):
                        lines.append((line, source))
            plan.settings = lines
            return
        year, state = item.settled["_year"], item.settled["_state"]
        for got in item.found:
            for number in years_in(got.words):
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
            scope.put("supply", SearchSupply([], ranked, "found"))
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
        scope.put("supply", SearchSupply(first, None, "near"))

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
        coord.seen = {coord.chunk.key} if coord.chunk is not None else set()
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
        about, checks = None, []
        for after in steps_after:
            if flow_map.kind_of(after) != "box":
                break
            kind = blocks.LIBRARY.get(after.get("box"))
            if kind is None or not kind.attached:
                break
            if after.get("off"):
                continue
            if kind.type == "about":
                about = after["id"]
            else:
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
                      self.follow_ups_of(node))

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
        with addressed.asking(self.asking_of(node, scope,
                                             self.after(node))):
            got = reader.ask_window(
                plan, item.shown, batch, doc.counts, item.key,
                numbers=item.numbers, listed=item.listed,
                title_page=first and bool(self.setting(node, "title_page")))
        held, lost = got
        if lost is not None:
            item.lost = item.lost or lost
            scope.put("answer", Answer(False))
            return
        item.found = joined(item.found, held)
        scope.put("answer", Answer(True, len(held), not held, False,
                                   held[0].words if held else "",
                                   held[0].quote if held else ""))

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
        with addressed.asking(self.asking_of(node, scope, self.after(node))):
            got = self.reader.find(doc.plan, parameter, chunk, doc.counts)
        owner = scope.owner()
        owner.values.setdefault("finds", []).append(got)
        owner.values["answer"] = Answer(
            not got["lost"] or bool(got["claims"]), len(got["claims"]),
            not got["claims"], False,
            str((got["claims"][0].get("value_raw")
                 or got["claims"][0].get("value") or "")
                if got["claims"] else ""),
            got["claims"][0].get("quote", "") if got["claims"] else "")

    def box_sentences(self, node: dict, scope: Scope) -> None:
        doc: Doc = scope.get("doc")
        if doc.order_fields is None:
            return
        located = [p for p in doc.parameters
                   if not getattr(p, "once_per_document", False)]
        if located:
            with addressed.asking(Asking(node["id"])):
                doc.order_of = dict(doc.order_fields(located) or {})

    def box_works(self, node: dict, scope: Scope) -> None:
        reader = self.reader
        doc: Doc = scope.get("doc")
        plan = doc.plan
        if reader.works_field is None or "work" not in plan.names:
            return
        with addressed.asking(Asking(node["id"], follow_ups=self.number(
                node, "follow_ups"))):
            doc.reads.extend(reader.works(plan, plan.pieces(False),
                                          doc.counts))

    def box_names(self, node: dict, scope: Scope) -> None:
        value: ValueItem = scope.get("value")
        doc: Doc = scope.get("doc")
        plan = doc.plan
        parameter = value.read.batch.parameter
        merged = getattr(parameter, "merged", None)
        if not merged or merged not in plan.names:
            return
        with addressed.asking(Asking(node["id"])):
            for one in value.rows:
                self.reader.named_value(plan, parameter, one, doc.counts)

    # -- the boxes of a coordinate ---------------------------------------------------

    def coord_base(self, coord: CoordItem, plan: Plan) -> None:
        """What every request about the coordinate shows, made once."""
        if coord.payload is None:
            _shown, coord.payload, coord.noted = self.reader.coord_payload(
                plan, coord.read, coord.row, coord.slot)

    def box_coord(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        with addressed.asking(self.asking_of(node, scope, self.after(node))):
            answered, made, payload, noted = self.reader.ask_own_place(
                doc.plan, coord.read, coord.row, coord.slot, doc.counts,
                coord.clone)
        if payload is not None:
            coord.payload, coord.noted = payload, noted
        coord.made += made
        state = coord.row.claim.get(f"{coord.slot.name}_state")
        scope.put("answer", Answer(answered, 1 if state == READ else 0,
                                   state != READ, False))

    def box_quantity(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        with addressed.asking(Asking(node["id"])):
            self.reader.quantity(doc.plan, coord.read.batch.parameter,
                                 coord.row, coord.slot, doc.counts)
        scope.put("answer", Answer(True))

    def box_work_coordinate(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        if "work" not in doc.plan.names:
            return
        with addressed.asking(Asking(node["id"], follow_ups=self.number(
                node, "follow_ups"))):
            self.reader.work_coordinate(
                doc.plan, coord.read, coord.row, coord.slot, doc.counts)
        scope.put("answer", Answer(True))

    def box_phrase(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        anew = bool(self.setting(node, "anew")) \
            and scope.get("round", 1) >= 2 and coord.sentences
        with addressed.asking(Asking(node["id"])):
            sentence = self.reader.search_sentence(
                doc.plan, coord.read, coord.row, coord.slot, doc.counts,
                before=list(coord.sentences) if anew else None)
        coord.sentence = sentence
        coord.sentences.append(sentence)

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
        with addressed.asking(self.asking_of(node, scope, self.after(node))):
            made, held, more = reader.search_round(
                plan, coord.read, coord.row, coord.slot, coord.payload,
                batch, doc.counts, coord.clone, (supply.label, 1),
                {**coord.noted, "shows": label})
        state = coord.row.claim.get(f"{coord.slot.name}_state")
        if held or state == UNBACKED:
            coord.made += made
            supply.fetched = []
        else:
            supply.fetched = reader.fetch(plan, more, batch, coord.seen,
                                          numbers)
        scope.put("answer", Answer(True, 1 if held else 0, not held, False))

    def box_last_year(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        doc: Doc = scope.get("doc")
        self.coord_base(coord, doc.plan)
        with addressed.asking(Asking(node["id"])):
            self.reader.last_year(doc.plan, coord.read.batch.parameter,
                                  coord.row, coord.slot, doc.counts,
                                  coord.noted or {})

    def box_state(self, node: dict, scope: Scope) -> None:
        coord: CoordItem = scope.get("coord")
        plan = scope.get("doc").plan
        key = f"{coord.slot.name}_state"
        mode = self.setting(node, "mode")
        if mode == "out_of_slice":
            coord.row.claim.setdefault(key, OUT_OF_SLICE)
        elif mode == "unstated":
            coord.row.claim[key] = SAID_UNSTATED
        else:
            self.locate(coord, plan)
            numbers = coord.read.batch.parameter.is_numeric
            rest = any(c.key not in coord.seen
                       for c in plan.pieces(numbers))
            coord.row.claim[key] = EXHAUSTED if rest else SAID_UNSTATED

    # Boxes the run does elsewhere: the preparation (`plan`, `prepare`) and
    # writing and computing (`runner`).
    def box_document(self, node, scope):
        return None

    box_transcribe = box_split = box_lists = box_write = box_compute = \
        box_document


def compute_on(profile=None) -> bool:
    """Is the calculation after the reading on in the drawing of
    *profile*?"""
    return flow_map.compute_on(flow_map.tree_of(profile))


