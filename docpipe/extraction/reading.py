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

Nothing is checked here. Every coordinate goes through `pipeline.merge_field`,
the check every field answer of the harvest goes through, and every value
through `fold_batch`. A frame coordinate the request leaves open is taken from
the survey's tuple of the passage, with its quote, where the survey named one
(window `frame`).

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, replace
from typing import Callable, Optional

from . import fields
from .pipeline import (READ, Batch, Row, Source, WorkItem, column_head,
                       merge_field, option_named, printed_lines, row_label)
from .verify import numbers_in

READ_TABLE_PROMPT_ID = "extraction/read_table"
READ_TEXT_PROMPT_ID = "extraction/read_text"

# What a request came to besides a reply: too long to be sent, or an answer
# that did not fit its token limit.
CUT = "cut_off"

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
    if slot.is_closed:
        value = {"enum": sorted(slot.answerable())}
    elif slot.kind == fields.NUMBER:
        value = {"type": "integer"}
    else:
        value = {"type": "string"}
    properties = {"value": value, "value_raw": {"type": "string"},
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


# -- a table -------------------------------------------------------------------

def table_payload(source: Source, grid: Grid, parameter, slots: list,
                  known: list) -> dict:
    provenance = source.provenance or {}
    return {
        "table": {"section": provenance.get("section_title"),
                  "text": source.text},
        "columns": [{"column": c, "head": column_head(grid.text, c,
                                                      grid.columns)}
                    for c in range(1, grid.columns + 1)],
        "rows": [{"row": r, "label": next((cell for cell in cells if cell),
                                          "")}
                 for r, (_line, cells) in enumerate(grid.body, start=1)],
        "parameter": {"key": parameter.uri, "label": parameter.label,
                      "definition": parameter.description},
        "coordinates": {slot.name: coordinate_shown(slot) for slot in slots},
        "known": known}


def table_response_format(slots: list) -> dict:
    coordinates = {
        slot.name: {"type": "object", "properties": {
            "table": answer_schema(slot),
            "columns": {"type": "array",
                        "items": answer_schema(slot, "column")},
            "rows": {"type": "array", "items": answer_schema(slot, "row")}},
            "additionalProperties": False}
        for slot in slots}
    schema = {"type": "object", "properties": {
        "value_columns": {"type": "array", "items": {"type": "integer"}},
        "value_rows": {"type": "array", "items": {"type": "integer"}},
        "coordinates": {"type": "object", "properties": coordinates,
                        "additionalProperties": False},
        "faulty": {"type": "string"}},
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


def _answer(entry: dict) -> dict:
    return {key: entry[key] for key in ("value", "value_raw", "quote")
            if key in entry}


def table_replies(reply: dict, slot, at: dict) -> list:
    """[(window, field reply)] of one coordinate of a table reply, the most
    particular first: a row label, then a column head, then the table."""
    entry = ((reply.get("coordinates") or {}).get(slot.name)
             if isinstance(reply.get("coordinates"), dict) else None) or {}
    by_row, by_column = collections.defaultdict(list), \
        collections.defaultdict(list)
    for label, (r, c) in at.items():
        by_row[r].append(label)
        by_column[c].append(label)
    out = []
    for key, where, labels in (("rows", "row", by_row),
                               ("columns", "column", by_column)):
        groups = [dict(_answer(answer), rows=labels[answer[where]])
                  for answer in entry.get(key) or ()
                  if isinstance(answer, dict) and answer.get(where) in labels]
        if groups:
            out.append((("own", 1), {"groups": groups}))
    whole = entry.get("table")
    if isinstance(whole, dict) and at:
        out.append((("table", 1),
                    {"groups": [dict(_answer(whole), rows=list(at))]}))
    return out


# -- a section or a figure -----------------------------------------------------

def text_payload(source: Source, parameter, slots: list,
                 known: list) -> dict:
    provenance = source.provenance or {}
    return {"source": {"kind": source.owner_kind,
                       "section": provenance.get("section_title"),
                       "text": source.text},
            "parameter": {"key": parameter.uri, "label": parameter.label,
                          "definition": parameter.description},
            "coordinates": {slot.name: coordinate_shown(slot)
                            for slot in slots},
            "known": known}


def text_response_format(parameter, slots: list) -> dict:
    value = ({"type": "number"} if parameter.is_numeric
             else {"type": "string"})
    properties = {"value": value, "value_raw": {"type": "string"},
                  "quote": {"type": "string"}}
    properties.update({slot.name: answer_schema(slot) for slot in slots})
    entry = {"type": "object", "properties": properties,
             "required": ["value", "quote"], "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"values": {"type": "array", "items": entry}},
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
    answers = {label: _answer(entry[slot.name])
               for label, entry in entries.items()
               if isinstance(entry.get(slot.name), dict)}
    return [(("own", 1), {"answers": answers})] if answers else []


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


class Reader:
    """(document_id, survey, passages) -> [Read], one per parameter and
    passage the survey named for it.

    *ask_table(source, grid, parameter, slots, known)* and
    *ask_text(source, parameter, slots, known)* are one request each: the
    reply as a dict, CUT, or None. *shown_with(source)* is what a
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
                             shown=shown)
        if self.pool is None:
            return [one(job) for job in jobs]
        return list(self.pool.map(one, jobs))

    def read(self, document_id: int, parameter, source: Source,
             tuples: list, pairs: list, passages: dict,
             shown: Optional[Source] = None) -> Read:
        """*source* is the passage a value is verified against, *shown* the
        piece of it the request shows."""
        shown = shown or source
        slots = slots_of(self.spec, parameter)
        known = known_of(tuples, self.frame_slots)
        batch = Batch(document_id, parameter,
                      [WorkItem(document_id, parameter, source)])
        grid = grid_of(source.text) if source.owner_kind == "table" else None
        if grid is not None:
            reply = self.ask_table(source, grid, parameter, slots, known)
        else:
            reply = self.ask_text(shown, parameter, slots, known)
        result = Read(batch, [], asked=1)
        if not isinstance(reply, dict):
            result.unread = True
            return result
        evidence = [shown] + list(self.shown_with(source)) + [
            passages[tuple(one[f"{s.name}_source"])] for one in tuples
            for s in self.frame_slots
            if tuple(one.get(f"{s.name}_source") or ()) in passages]
        if grid is not None:
            rows, at, result.skipped = table_rows(reply, grid)
            result.faulty = reply.get("faulty") or None
            replies = {slot.name: table_replies(reply, slot, at)
                       for slot in slots}
        else:
            rows, entries = text_rows(reply)
            replies = {slot.name: text_replies(entries, slot)
                       for slot in slots}
        bases = self.bases(pairs)
        for slot in slots:
            for window, field_reply in replies[slot.name]:
                merge_field(rows, evidence, slot, field_reply, window=window,
                            bases=bases)
            if slot.name == fields.UNIT:
                for axis in fields.axis_slots(parameter):
                    fields.apply_derived(rows, axis)
        inherit(rows, [s for s in self.frame_slots
                       if s.name in {x.name for x in slots}],
                tuples, pairs, evidence)
        result.claims = [row.claim for row in rows]
        if self.trace is not None:
            self.trace("read", document_id, parameter=parameter.uri,
                       kind=source.owner_kind, owner=source.owner_id,
                       table=grid is not None, values=len(rows),
                       skipped=result.skipped, faulty=result.faulty)
        return result
