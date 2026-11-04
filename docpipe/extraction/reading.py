"""
reading.py: The values of one parameter in the passages the survey named for
it, every coordinate of a value in the same request.

Step 3 of the rebuilt harvest (owner decision 2026-11-04). A table is read as
one unit: one request says which of its columns and rows hold the
parameter's values and where each coordinate stands, at a row label, a
column head or for the whole table, each with its quote. Code then makes one
row per cell and reads the number by its place, never by its value: a table
row "27 % | 28 % | 27 % | 23 %" gives each 27 % its own column. A section or
a figure is read in one request that names its values with every coordinate
at once, each with its own quote.

Every coordinate is answered: the grammar requires each of them, a value's
entry in text and a table's entry for the whole table, and "the passage does
not say" is one of the answers (`fields.UNSTATED`). One request for all
coordinates is otherwise the request that lets a model drop the one it is
unsure of (fields.py).

Nothing is checked here. Every coordinate goes through `pipeline.merge_field`,
the check every field answer of the harvest goes through, and every value
through `fold_batch`. What that check refuses is asked once more, with the
reason it was refused for, as the harvest asks a failed field answer again;
a coordinate the reply left out is asked for by name. A frame coordinate the
passage leaves open is taken from the survey's tuple of the passage, with its
quote, where the survey named one (window `frame`). A coordinate no reply
answered ends `unanswered`.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import json
import re
import sys
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from . import fields, lookup
from .pipeline import (READ, YEAR_STATES, Batch, Row, Source, WorkItem,
                       column_head, mark_unanswered, merge_field,
                       option_named, printed_lines, row_label, window_around)
from .verify import number_outside_quote, numbers_in, quote_in
from .wording import say

READ_TABLE_PROMPT_ID = "extraction/read_table"
READ_TEXT_PROMPT_ID = "extraction/read_text"

# What a request came to besides a reply: too long to be sent, or an answer
# that did not fit its token limit.
CUT = "cut_off"
# And no readable reply at all: the `_why` of the hole the run writes for it.
NO_ANSWER = "no_answer"

_IN_A_NAME = re.compile(r"(?<=[^\W\d_])\d+")


@dataclass
class Grid:
    """A transcribed table: its head lines and its body rows, cell by cell."""
    text: str
    heads: list           # the lines above the rule
    body: list            # [(line, [cells])] below it
    columns: int


def cells_of(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def grid_of(text: str) -> Optional[Grid]:
    """The table of *text*, or None when it has no Markdown table."""
    lines = [line for line in (text or "").splitlines()
             if line.count("|") >= 2]
    rule = next((i for i, line in enumerate(lines)
                 if "-" in line and set(line) <= set("|:- \t")), None)
    if rule is None:
        return None
    body = [(line, cells_of(line)) for line in lines[rule + 1:]
            if line in printed_lines(line)]
    if not body:
        return None
    return Grid(text, lines[:rule], body, max(len(c) for _, c in body))


def cell_number(cell: str):
    """The one number a cell prints, as int or float, or None for a cell
    with none or with several. Digits after a letter are part of a name,
    "CO2" or "Q3", and no number of the cell."""
    found = numbers_in(_IN_A_NAME.sub("", cell or ""))
    signed = {n for n in found if n.startswith("-")}
    plain = found - signed - {n[1:] for n in signed}
    if len(signed) + len(plain) != 1:
        return None
    text = (signed or plain).pop()
    return float(text) if "." in text else int(text)


def slots_of(spec, parameter) -> list:
    """The coordinates a value of *parameter* is read with: its unit, then
    every axis the spec does not decide."""
    out = []
    unit = fields.unit_slot(spec, parameter) if parameter.is_numeric else None
    if unit is not None:
        out.append(unit)
    return out + fields.asked_slots(parameter)


def coordinate_shown(slot) -> dict:
    shown: dict = {"question": slot.question}
    if slot.is_closed:
        shown["options"] = slot.answerable()
    else:
        shown["kind"] = slot.kind
    return shown


def answer_schema(slot, where: Optional[str] = None) -> dict:
    """One coordinate's answer as the grammar takes it, at a row or a column
    when *where* names it."""
    properties = {"value": fields.value_schema(slot),
                  "value_raw": {"type": "string"},
                  "quote": {"type": "string"}}
    required = ["value"]
    if where:
        properties = {where: {"type": "integer"}, **properties}
        required = [where, "value"]
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


def known_of(tuples: list, frame_slots: list) -> list:
    return [{slot.name: one.get(slot.name) for slot in frame_slots}
            for one in tuples]


def years_of(bases: list, slots: list) -> dict:
    """The plan's base years and target years, numbers only, where a
    coordinate asked is the one they date: what the field request shows
    (`runner._field_payload`), so a value whose passage names its state by
    the plan's word and prints no year can answer one of them
    (`pipeline.named_year`)."""
    names = {slot.name for slot in slots}
    out = {}
    for state, key in YEAR_STATES.items():
        dated = sorted({b["year"] for b in bases or ()
                        if b.get("axis") in names and b.get("state") == state})
        if dated:
            out[key] = dated
    return out


def around_of(source: Source, passages: dict,
              budget: Optional[int]) -> Optional[Source]:
    """The text of the section a table or figure stands in, as its request
    shows it (owner decision 2026-11-04): the sentence that announces it,
    the heading over it and the paragraph under it, where its year and its
    scenario are printed. The whole section when it fits *budget*, the
    survey's two pages, else that many characters around the table's place
    in it. None for a section, and for a table or figure whose section is
    not among *passages*."""
    provenance = source.provenance or {}
    parent = provenance.get("parent_section")
    if source.owner_kind == "section" or parent is None:
        return None
    section = passages.get(("section", int(parent)))
    if section is None or not section.text:
        return None
    text = section.text
    if budget and len(text) > budget:
        block = provenance.get("block_id") or ""
        text = window_around(text, f"[{block}", budget)
    return replace(section, text=text)


# -- what a reply may ask of the rest of the plan -----------------------------

# What a reply may ask for under "more" (owner decision 2026-11-04): the next
# or the previous section, a table or figure by its placeholder, the passages
# of the plan matching a pattern as a list, a passage of such a list by its id.
GETS = ("next", "previous", "item", "search", "hit")
# Why an ask found nothing, as the reply's "not_found" says it: past the end
# of the plan, or a name that fits no passage or more than one. A pattern
# that does not compile or does not finish says `lookup.matching`'s fault.
END, UNKNOWN = "end", "unknown"


def more_schema() -> dict:
    """The asks a reply may carry under "more"."""
    return {"type": "array", "items": {
        "type": "object",
        "properties": {"get": {"enum": list(GETS)},
                       "id": {"type": "string"},
                       "pattern": {"type": "string"}},
        "required": ["get"], "additionalProperties": False}}


@dataclass
class Gathered:
    """What one read fetched of the rest of the plan, in the order the model
    asked for it: the passages its request shows under "more", the hit lists
    of its searches under "hits", and what could not be found, with why,
    under "not_found". *seen* are the passages the request already shows,
    *cursor* where "next" and "previous" go on from."""
    seen: set = field(default_factory=set)
    cursor: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    shown: list = field(default_factory=list)
    hits: list = field(default_factory=list)
    missed: list = field(default_factory=list)
    by_hit: dict = field(default_factory=dict)

    def context(self) -> dict:
        out = {}
        if self.shown:
            out["more"] = self.shown
        if self.hits:
            out["hits"] = self.hits
        if self.missed:
            out["not_found"] = self.missed
        return out

    def _show(self, source: Source, text: str) -> bool:
        owner = (source.owner_kind, source.owner_id)
        if owner in self.seen or not text:
            return False
        self.seen.add(owner)
        self.sources.append(replace(source, text=text))
        self.shown.append({"id": f"M{len(self.shown) + 1}",
                           "kind": source.owner_kind,
                           "title": lookup.title_of(source), "text": text})
        return True

    def _miss(self, ask: dict, why: str, detail: str = "") -> None:
        entry = {"get": ask.get("get"),
                 **{key: ask[key] for key in ("id", "pattern")
                    if ask.get(key)}, "why": why}
        if detail:
            entry["detail"] = detail
        if entry not in self.missed:
            self.missed.append(entry)

    def list_hits(self, found: list, **about) -> int:
        """Show *found*, [(owner, title, line)], as one list of hits, each
        with the id a later ask names it by. Returns how many."""
        listed = []
        for owner, title, line in found:
            ref = f"H{len(self.by_hit) + 1}"
            self.by_hit[ref] = (tuple(owner), line)
            listed.append({"id": ref, "kind": owner[0], "title": title,
                           "line": line})
        if listed:
            self.hits.append({**about, "hits": listed})
        return len(listed)

    def fetch(self, asks, order: list, passages: dict,
              budget: Optional[int]) -> bool:
        """The asks of one reply resolved (`lookup`), each passage cut to
        *budget*, the survey's two pages. True when a passage or a hit list
        came of them the request has not shown yet: an ask for something
        shown already, or for nothing, ends the gathering."""
        new = False
        for ask in asks if isinstance(asks, list) else ():
            if not isinstance(ask, dict):
                continue
            get = ask.get("get")
            if get in ("next", "previous"):
                step = 1 if get == "next" else -1
                found = lookup.following(order, self.cursor[get], step)
                if found is None:
                    self._miss(ask, END)
                    continue
                self.cursor[get] = (found.owner_kind, found.owner_id)
                text = found.text or ""
                if budget and len(text) > budget:
                    text = text[:budget] if step > 0 else text[-budget:]
                new = self._show(found, text) or new
            elif get == "item":
                found = lookup.item(order, ask.get("id") or "")
                if found is None:
                    self._miss(ask, UNKNOWN)
                    continue
                new = self._show(found, (found.text or "")[:budget or None]) \
                    or new
            elif get == "search":
                pattern = ask.get("pattern")
                if not pattern or any(h["pattern"] == pattern
                                      for h in self.hits):
                    continue
                matches = lookup.matching(order, pattern,
                                          budget or sys.maxsize)
                if matches.fault:
                    self._miss(ask, matches.fault, matches.detail)
                    continue
                self.list_hits([(hit["owner"], hit["title"], hit["line"])
                                for hit in matches.hits],
                               pattern=pattern, total=matches.total)
                if not matches.hits:
                    self.hits.append({"pattern": pattern,
                                      "total": matches.total, "hits": []})
                new = True
            elif get == "hit":
                ref = self.by_hit.get(ask.get("id") or "")
                found = passages.get(ref[0]) if ref else None
                if found is None:
                    self._miss(ask, UNKNOWN)
                    continue
                text = found.text or ""
                if budget and len(text) > budget:
                    text = window_around(text, ref[1], budget)
                new = self._show(found, text) or new
            else:
                self._miss(ask, UNKNOWN)
        return new


def first_line(source: Source) -> str:
    """The first line of a passage under its title: what a hit list shows
    of it."""
    title = lookup.title_of(source)
    return next((line.strip()[:200] for line in (source.text or "").splitlines()
                 if line.strip() and line.strip() != title), "")


def gather(ask: Callable, reply: dict, gathered: Gathered, order: list,
           passages: dict, budget: Optional[int]) -> tuple:
    """(the reply that stands, the requests made): what each reply asks of
    the rest of the plan is fetched and the request sent again, until a round
    asks for nothing the request has not shown or the request no longer fits
    the model's window. The reply before such a round stands."""
    asked = 0
    while gathered.fetch(reply.get("more"), order, passages, budget):
        again = ask()
        asked += 1
        if not isinstance(again, dict):
            break
        reply = again
    return reply, asked


# -- a table -------------------------------------------------------------------

def table_payload(source: Source, grid: Grid, parameter, slots: list,
                  context: dict, corrections: Optional[list] = None) -> dict:
    """The table request: the table, the text around it and *context*
    (`Reader.context_of`); with *corrections* the same request asked once
    more, what was wrong with the first reply beside it."""
    provenance = source.provenance or {}
    payload = {
        "table": {"section": provenance.get("section_title"),
                  "text": source.text},
        **({"around": context["around"]} if context.get("around") else {}),
        "columns": [{"column": c, "head": column_head(grid.text, c,
                                                      grid.columns)}
                    for c in range(1, grid.columns + 1)],
        "rows": [{"row": r, "label": next((cell for cell in cells if cell),
                                          "")}
                 for r, (_line, cells) in enumerate(grid.body, start=1)],
        "parameter": {"key": parameter.uri, "label": parameter.label,
                      "definition": parameter.description},
        "coordinates": {slot.name: coordinate_shown(slot) for slot in slots},
        **{key: value for key, value in context.items() if key != "around"}}
    if corrections:
        payload["corrections"] = corrections
    return payload


def table_response_format(slots: list) -> dict:
    """Every coordinate answered, at least for the whole table: its entry
    there is the answer of every value no row or column entry answers, and
    UNSTATED when the table does not print it."""
    coordinates = {
        slot.name: {"type": "object", "properties": {
            "table": answer_schema(slot),
            "columns": {"type": "array",
                        "items": answer_schema(slot, "column")},
            "rows": {"type": "array", "items": answer_schema(slot, "row")}},
            "required": ["table"], "additionalProperties": False}
        for slot in slots}
    schema = {"type": "object", "properties": {
        "value_columns": {"type": "array", "items": {"type": "integer"}},
        "value_rows": {"type": "array", "items": {"type": "integer"}},
        "coordinates": {"type": "object", "properties": coordinates,
                        "required": [slot.name for slot in slots],
                        "additionalProperties": False},
        "faulty": {"type": "string"}, "more": more_schema()},
        "required": ["value_columns", "value_rows", "coordinates"],
        "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "table_reply", "schema": schema}}


def table_rows(reply: dict, grid: Grid) -> tuple:
    """(rows, {label: (row, column)}, cells not read) of a table reply: one
    row per cell of a value row and a value column that prints one number,
    its quote the table row, its head the words over its column."""
    columns = sorted({c for c in reply.get("value_columns") or ()
                      if isinstance(c, int) and 1 <= c <= grid.columns})
    numbers = sorted({r for r in reply.get("value_rows") or ()
                      if isinstance(r, int) and 1 <= r <= len(grid.body)})
    rows, at, skipped = [], {}, 0
    for r in numbers:
        line, cells = grid.body[r - 1]
        for c in columns:
            value = cell_number(cells[c - 1]) if c <= len(cells) else None
            if value is None:
                skipped += 1
                continue
            claim = {"source": "Q1", "value": value, "quote": line.strip()}
            head = column_head(grid.text, c, len(cells))
            if head:
                claim["head"] = head
            label = row_label(len(rows))
            rows.append(Row(label=label, item_index=0, claim=claim))
            at[label] = (r, c)
    return rows, at, skipped


def answer_of(entry: dict) -> dict:
    return {key: entry[key] for key in ("value", "value_raw", "quote")
            if key in entry}


ROWS, COLUMNS, TABLE = "rows", "columns", "table"


def table_replies(reply: dict, slot, at: dict) -> list:
    """[(level, window, field reply)] of one coordinate of a table reply,
    the most particular first: a row label, then a column head, then the
    table."""
    entry = ((reply.get("coordinates") or {}).get(slot.name)
             if isinstance(reply.get("coordinates"), dict) else None) or {}
    by_row, by_column = collections.defaultdict(list), \
        collections.defaultdict(list)
    for label, (r, c) in at.items():
        by_row[r].append(label)
        by_column[c].append(label)
    out = []
    for key, where, labels in ((ROWS, "row", by_row),
                               (COLUMNS, "column", by_column)):
        groups = [dict(answer_of(answer), rows=labels[answer[where]])
                  for answer in entry.get(key) or ()
                  if isinstance(answer, dict) and answer.get(where) in labels]
        if groups:
            out.append((key, ("own", 1), {"groups": groups}))
    whole = entry.get(TABLE)
    if isinstance(whole, dict) and at:
        out.append((TABLE, ("table", 1),
                    {"groups": [dict(answer_of(whole), rows=list(at))]}))
    return out


def table_corrections(failed: list, at: dict) -> list:
    """What the check refused of a table reply, once per coordinate and
    place: [{coordinate, row | column, what}], the row or column numbered as
    the request numbered it, neither for the whole table."""
    out, seen = [], set()
    for name, level, failure in failed:
        place = at.get(failure.get("row"))
        if level == ROWS and place:
            where = {"row": place[0]}
        elif level == COLUMNS and place:
            where = {"column": place[1]}
        else:
            where = {}
        key = (name, level, tuple(where.values()), failure.get("why"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"coordinate": name, **where,
                    "what": failure.get("reason")})
    return out


# -- a section or a figure -----------------------------------------------------

def text_payload(source: Source, parameter, slots: list,
                 context: dict, corrections: Optional[list] = None) -> dict:
    """The request of a section or a figure, the text around a figure and
    *context* (`Reader.context_of`) beside it; with *corrections* the same
    request asked once more for the values the check refused something of."""
    provenance = source.provenance or {}
    payload = {"source": {"kind": source.owner_kind,
                          "section": provenance.get("section_title"),
                          "text": source.text},
               **({"around": context["around"]} if context.get("around")
                  else {}),
               "parameter": {"key": parameter.uri, "label": parameter.label,
                             "definition": parameter.description},
               "coordinates": {slot.name: coordinate_shown(slot)
                               for slot in slots},
               **{key: value for key, value in context.items()
                  if key != "around"}}
    if corrections:
        payload["corrections"] = corrections
    return payload


def text_response_format(parameter, slots: list,
                         labels: Optional[list] = None) -> dict:
    """Every value with every coordinate. Asked again, each entry names the
    value of the first reply it answers for, one of *labels*."""
    value = ({"type": "number"} if parameter.is_numeric
             else {"type": "string"})
    properties = {"value": value, "value_raw": {"type": "string"},
                  "quote": {"type": "string"}}
    properties.update({slot.name: answer_schema(slot) for slot in slots})
    required = ["value", "quote", *(slot.name for slot in slots)]
    if labels:
        properties = {"row": {"enum": list(labels)}, **properties}
        required = ["row", *required]
    entry = {"type": "object", "properties": properties,
             "required": required, "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"values": {"type": "array", "items": entry},
                             "more": more_schema()},
              "required": ["values"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "text_reply", "schema": schema}}


def text_rows(reply: dict) -> tuple:
    """(rows, the entry of each row) of a text reply."""
    rows, entries = [], {}
    for entry in reply.get("values") or ():
        if not isinstance(entry, dict):
            continue
        claim = {"source": "Q1", "value": entry.get("value"),
                 "quote": entry.get("quote")}
        if entry.get("value_raw"):
            claim["value_raw"] = entry["value_raw"]
        label = row_label(len(rows))
        rows.append(Row(label=label, item_index=0, claim=claim))
        entries[label] = entry
    return rows, entries


def text_replies(entries: dict, slot) -> list:
    answers = {label: answer_of(entry[slot.name])
               for label, entry in entries.items()
               if isinstance(entry.get(slot.name), dict)}
    return [(ROWS, ("own", 1), {"answers": answers})] if answers else []


def value_failure(claim: dict, source: Source) -> Optional[str]:
    """Why the check of a value refuses it, or None: a number its quote does
    not print (the harvest's own `number_outside_quote`), a quote not in its
    passage. Said as the harvest says it."""
    quote = claim.get("quote")
    if not isinstance(quote, str) or not quote_in(source.text or "", quote):
        return say("quote_not_in_source")
    if number_outside_quote(claim):
        return say("value_outside_quote", values=json.dumps(
            [{"value": claim.get("value"), "quote": quote}],
            ensure_ascii=False))
    return None


def text_corrections(rows: list, failed: list, source: Source,
                     slots: list) -> list:
    """What the check refused of a text reply, one entry per value it
    refused something of: [{row, value, quote, what: {value | coordinate:
    reason}}]. A coordinate the reply left out is named as missing."""
    what: dict = collections.defaultdict(dict)
    for row in rows:
        reason = value_failure(row.claim, source)
        if reason:
            what[row.label]["value"] = reason
        for slot in slots:
            if not row.claim.get(f"{slot.name}_state"):
                what[row.label][slot.name] = say("key_missing", key=slot.name)
    for name, _level, failure in failed:
        if failure.get("row") in {row.label for row in rows}:
            what[failure["row"]].setdefault(name, failure.get("reason"))
    return [{"row": row.label, "value": row.claim.get("value"),
             "quote": row.claim.get("quote"), "what": what[row.label]}
            for row in rows if what.get(row.label)]


# -- one parameter in one passage ----------------------------------------------

def same(slot, a, b) -> bool:
    if slot.is_closed:
        first, second = option_named(slot, a), option_named(slot, b)
        return first is not None and second is not None \
            and first.uri == second.uri
    return str(a) == str(b)


def inherit(rows: list, slots: list, tuples: list, pairs: list,
            shown: list) -> int:
    """A frame coordinate still open on a row takes the survey's tuple of
    the passage, when the survey named exactly one, through the field check
    with the tuple's own quote. Not on a row that read a frame coordinate of
    its own the tuple contradicts: a year under its column head is not the
    year of the table's title. Returns the coordinates taken."""
    if len(tuples) != 1:
        return 0
    one = tuples[0]
    index = next((i for i, pair in enumerate(pairs, start=1)
                  if all(pair.get(s.name) == one.get(s.name) for s in slots)),
                 1)
    agree = [row.label for row in rows
             if all(row.claim.get(f"{s.name}_state") != READ
                    or same(s, row.claim.get(s.name), one.get(s.name))
                    for s in slots)]
    taken = 0
    for slot in slots:
        if not agree:
            break
        answer = {"value": one.get(slot.name),
                  "quote": one.get(f"{slot.name}_quote")}
        if one.get(f"{slot.name}_raw"):
            answer["value_raw"] = one[f"{slot.name}_raw"]
        got = merge_field(rows, shown, slot,
                          {"groups": [dict(answer, rows=agree)]},
                          window=("frame", index))
        taken += got["filled"]
    return taken


@dataclass
class Read:
    """What reading one parameter in one passage came to."""
    batch: Batch
    claims: list
    asked: int = 0
    skipped: int = 0              # cells of value rows and columns not read
    faulty: Optional[str] = None
    unread: bool = False          # no readable reply
    why: Optional[str] = None     # and why: cut_off or no_answer
    corrected: int = 0            # corrections the second request carried
    # what the check refused of the first reply, by reason
    failed: dict = field(default_factory=dict)
    unanswered: int = 0           # coordinates no reply answered
    fetched: int = 0              # passages shown under "more"
    searched: int = 0             # hit lists shown under "hits"
    missed: int = 0               # asks that found nothing


class Reader:
    """(document_id, survey, passages) -> [Read], one per parameter and
    passage the survey named for it.

    *ask_table(source, grid, parameter, slots, context, corrections)* and
    *ask_text(source, parameter, slots, context, corrections)* are one
    request each: the reply as a dict, CUT, or None; *context* is what the
    request shows beside its passage (`context_of`), *corrections* None the
    first time and what was wrong the second. *shown_with(source)* is what a
    coordinate's quote may stand in besides the passage: its section's
    heading. *pool* reads passages side by side.
    """

    def __init__(self, spec, ask_table: Callable, ask_text: Callable,
                 frame_slots: list, *, shown_with: Optional[Callable] = None,
                 bases: Optional[Callable] = None, pool=None, trace=None):
        self.spec = spec
        self.ask_table = ask_table
        self.ask_text = ask_text
        self.frame_slots = frame_slots
        self.shown_with = shown_with or (lambda source: [])
        self.bases = bases or (lambda pairs: [])
        self.pool = pool
        self.trace = trace

    def __call__(self, document_id: int, found, passages: dict,
                 budget: Optional[int] = None) -> list:
        """One Read per parameter and passage the survey named for it. A
        section or figure longer than *budget* characters, the survey's two
        pages, is read in the survey's pieces, each its own request."""
        from .survey import pieces

        pairs: list = []
        for answer in found.answers.values():
            for one in answer.tuples.get("frame", ()):
                if one not in pairs:
                    pairs.append(one)
        jobs = []
        for parameter in self.spec.parameters:
            for owner in found.passages_of(parameter.uri):
                source = passages.get(tuple(owner))
                if source is None:
                    continue
                text = source.text or ""
                if budget and source.owner_kind != "table" \
                        and len(text) > budget:
                    jobs.extend((parameter, source, replace(source,
                                                            text=piece))
                                for piece in pieces(text, budget))
                else:
                    jobs.append((parameter, source, source))

        def one(job):
            parameter, source, shown = job
            owner = (source.owner_kind, source.owner_id)
            return self.read(document_id, parameter, source,
                             found.tuples_at(owner, "frame"), pairs, passages,
                             shown=shown, budget=budget)
        if self.pool is None:
            return [one(job) for job in jobs]
        return list(self.pool.map(one, jobs))

    def context_of(self, source: Source, slots: list, tuples: list,
                   bases: list, passages: dict,
                   budget: Optional[int]) -> tuple:
        """(what a request shows beside its passage, the section it was
        cut from): the text around a table or figure (`around_of`), the
        survey's pairs of the passage and the plan's years (`years_of`)."""
        around = around_of(source, passages, budget)
        context = {"around": around.text} if around is not None else {}
        context["known"] = known_of(tuples, self.frame_slots)
        context.update(years_of(bases, slots))
        return context, around

    def read(self, document_id: int, parameter, source: Source,
             tuples: list, pairs: list, passages: dict,
             shown: Optional[Source] = None,
             budget: Optional[int] = None) -> Read:
        """*source* is the passage a value is verified against, *shown* the
        piece of it the request shows, *budget* the survey's two pages."""
        shown = shown or source
        slots = slots_of(self.spec, parameter)
        # The reading's spec rides on the batch, so the fold checks a value
        # against the lists this document closes (`runner.spec_of`).
        batch = Batch(document_id, parameter,
                      [WorkItem(document_id, parameter, source)],
                      spec=self.spec)
        grid = grid_of(source.text) if source.owner_kind == "table" else None
        bases = self.bases(pairs)
        context, around = self.context_of(source, slots, tuples, bases,
                                          passages, budget)
        origin = (source.owner_kind, source.owner_id)
        parent = (around.owner_kind, around.owner_id) \
            if around is not None else origin
        gathered = Gathered(seen={origin, parent},
                            cursor={"next": origin, "previous": parent})

        def ask(corrections: Optional[list] = None):
            shows = {**context, **gathered.context()}
            if grid is not None:
                return self.ask_table(source, grid, parameter, slots, shows,
                                      corrections)
            return self.ask_text(shown, parameter, slots, shows, corrections)

        reply = ask()
        result = Read(batch, [], asked=1)
        if not isinstance(reply, dict):
            result.unread = True
            result.why = CUT if reply == CUT else NO_ANSWER
            if self.trace is not None:
                self.trace("read", document_id, parameter=parameter.uri,
                           kind=source.owner_kind, owner=source.owner_id,
                           table=grid is not None, values=0, unread=True,
                           why=result.why, asked=result.asked)
            return result
        reply, more = gather(ask, reply, gathered, list(passages.values()),
                             passages, budget)
        result.asked += more
        result.fetched = len(gathered.sources)
        result.searched = len(gathered.hits)
        result.missed = len(gathered.missed)
        evidence = [shown] + list(self.shown_with(source)) + (
            [around] if around is not None else []) + gathered.sources + [
            passages[tuple(one[f"{s.name}_source"])] for one in tuples
            for s in self.frame_slots
            if tuple(one.get(f"{s.name}_source") or ()) in passages]

        def merged(rows: list, replies: dict) -> list:
            """Every coordinate's answers onto *rows*, the most particular
            first; [(coordinate, level, failure)] of what the check refused."""
            failed = []
            for slot in slots:
                for level, window, field_reply in replies.get(slot.name, ()):
                    got = merge_field(rows, evidence, slot, field_reply,
                                      window=window, bases=bases)
                    failed.extend((slot.name, level, failure)
                                  for failure in got["failed"])
            return failed

        if grid is not None:
            rows, at, result.skipped = table_rows(reply, grid)
            result.faulty = reply.get("faulty") or None
            failed = merged(rows, {slot.name: table_replies(reply, slot, at)
                                   for slot in slots})
            corrections = table_corrections(failed, at) + [
                {"coordinate": slot.name,
                 "what": say("key_missing", key=slot.name)}
                for slot in slots
                if any(not row.claim.get(f"{slot.name}_state")
                       for row in rows)]
        else:
            rows, entries = text_rows(reply)
            failed = merged(rows, {slot.name: text_replies(entries, slot)
                                   for slot in slots})
            corrections = text_corrections(rows, failed, source, slots)
        result.failed = dict(collections.Counter(
            [failure.get("why") for _name, _level, failure in failed]
            + ["value" for c in corrections if "value" in c.get("what", ())]))
        if corrections and rows:
            result.corrected = len(corrections)
            result.asked += 1
            again = ask(corrections)
            if isinstance(again, dict) and grid is not None:
                merged(rows, {slot.name: table_replies(again, slot, at)
                              for slot in slots})
            elif isinstance(again, dict):
                merged(rows, self._again(rows, again, corrections, slots))
        for axis in fields.axis_slots(parameter):
            fields.apply_derived(rows, axis)
        inherit(rows, [s for s in self.frame_slots
                       if s.name in {x.name for x in slots}],
                tuples, pairs, evidence)
        result.unanswered = mark_unanswered(rows, slots)
        result.claims = [row.claim for row in rows]
        if self.trace is not None:
            self.trace("read", document_id, parameter=parameter.uri,
                       kind=source.owner_kind, owner=source.owner_id,
                       table=grid is not None, values=len(rows),
                       skipped=result.skipped, faulty=result.faulty,
                       asked=result.asked, corrected=result.corrected,
                       failed=result.failed, unanswered=result.unanswered,
                       fetched=result.fetched, searched=result.searched,
                       missed=result.missed)
        return result

    @staticmethod
    def _again(rows: list, reply: dict, corrections: list,
               slots: list) -> dict:
        """The second text reply onto the values it was asked about: an
        entry answers for the value its "row" names. A value the check
        refused takes the entry's value and quote; its coordinates are
        merged as the first reply's were, and one read the first time
        stays as it was read."""
        asked = {c["row"]: c for c in corrections}
        by_label = {row.label: row for row in rows}
        entries: dict = {}
        for entry in reply.get("values") or ():
            label = entry.get("row") if isinstance(entry, dict) else None
            if label not in asked or label in entries:
                continue
            entries[label] = entry
            if "value" in asked[label]["what"]:
                claim = by_label[label].claim
                claim["value"] = entry.get("value")
                claim["quote"] = entry.get("quote")
                claim.pop("value_raw", None)
                if entry.get("value_raw"):
                    claim["value_raw"] = entry["value_raw"]
        return {slot.name: text_replies(entries, slot) for slot in slots}
