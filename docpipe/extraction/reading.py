"""
reading.py: The values of one parameter in the passages the survey named for
it, one value per request: rounds name the values of a passage one by one,
then each value is asked once per group of the spec for that group's
coordinates.

Step 3 of the rebuilt harvest (owner decisions 2026-11-04 and 2026-11-05).
Every request has one task and reads exactly one value. A table is read like
a section: the model repeats each value as the passage prints it, quoted by
its sentence or its table row, and for a number in a table also the head of
its column as printed, which tells two equal numbers of one row apart. Code
reads no number by its place.

A round shows the whole passage (a table with its title, its head and all its
rows, or the survey's piece of a section), the text around a table or figure,
the parameter, the values already read, and the reading's tools, and asks for
the next value not yet read, until the model says there is none. A value may
stand in any passage the round showed: the passage, the text around it, or
one its tools fetched (owner decision 2026-11-05); it is read from the one its
quote stands in, which joins the reading's batch, so the fold checks it there
(`pipeline.route_claims`). A value the check refuses (its quote in no passage
shown, its number not in its quote, a quote over several table rows that
print it, a head no head line prints) is asked once more with the reason; one
named again is asked once more, and named again it ends the rounds.

A number in a table takes its column from its head, else from the one cell of
its row that prints it, and a head that prints exactly one year of the
document's pairs is its year, read off the head line and not asked
(`pipeline.with_head`, owner decision 2026-11-03); where exactly one pair has
that year, the pair's scenario is the value's too (`pipeline.head_pair`).
Then every group of the spec (`Spec.groups`, `groups_of`) is asked for this
one value, its coordinates still open only: the passage first, so a server
reads it once for all values, the value marked last, with what is already
read of it. Each group request has its own tools and its own correction
round, and only a group that asks a frame coordinate is shown the pairs and
the plan's base and target years.

Every coordinate asked is answered: the grammar of a group request requires
each of them, and "the passage does not say" is one of the answers
(`fields.UNSTATED`).

Nothing is checked here beyond what the harvest checks everywhere. Every
coordinate goes through `pipeline.merge_field` and every value through
`fold_batch`. What that check refuses is asked once more with its reason,
named by its coordinate; a coordinate the reply left out is asked for by
name. A frame coordinate still open takes the survey's tuple of the passage,
with its quote, where the survey named one (window `frame`). A coordinate no
reply answered ends `unanswered`. A request too long for the model's window
is split: a table into halves of its rows, until a single row is a hole of
its own (`Read.lost`).

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import json
import sys
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from . import fields, lookup
from .pipeline import (CELL, READ, YEAR_STATES, Batch, Row, Source, WorkItem,
                       cell_index, column_head, head_cells, head_pair,
                       in_several_rows, mark_unanswered, merge_field,
                       narrow_quote, option_named, printed_lines, row_label,
                       window_around, with_head)
from .verify import (canonical_number, flat, number_outside_quote, numbers_in,
                     quote_in)
from .wording import say

# The values of a passage, one per round; one group's coordinates of one of
# them.
READ_VALUES_PROMPT_ID = "extraction/read_values"
READ_TEXT_PROMPT_ID = "extraction/read_text"
PROMPT_IDS = (READ_VALUES_PROMPT_ID, READ_TEXT_PROMPT_ID)

# What a request came to besides a reply: too long to be sent, or an answer
# that did not fit its token limit.
CUT = "cut_off"
# And no readable reply at all: the `_why` of the hole the run writes for it.
NO_ANSWER = "no_answer"

# The hits of one ranked list a request shows, per kind (owner decision
# 2026-11-04: the best 15 sections, 20 tables and 20 figures).
SHOWN = {"section": 15, "table": 20, "figure": 20}

# Why the check refused a round's value, as `Read.failed` counts it: the value
# itself, its head, or a value already read.
VALUE, HEAD, REPEATED = "value", "head", "repeated"


def shown_hits(ranked: list) -> list:
    """The best of each kind of a ranked search, in its order (`SHOWN`)."""
    left = dict(SHOWN)
    out = []
    for source in ranked:
        if left.get(source.owner_kind, 0) > 0:
            left[source.owner_kind] -= 1
            out.append(source)
    return out


@dataclass
class Grid:
    """A transcribed table: its head lines and its body rows, cell by cell."""
    text: str
    heads: list           # the lines above the rule
    body: list            # [(line, [cells])] below it
    columns: int

    def row_numbers(self) -> list:
        return list(range(1, len(self.body) + 1))


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


def part_text(grid: Grid, shown) -> str:
    """The table's text with only the body rows *shown*, as the table numbers
    them: its title, its head lines and every line that is no body row stay
    where they stand."""
    out, k = [], 0
    for line in grid.text.splitlines():
        if k < len(grid.body) and line == grid.body[k][0]:
            k += 1
            if k in shown:
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def halves(view: Source) -> list:
    """A table too long for one request as two, each with half its rows and
    all its title and head lines; [] for anything else, or a single row."""
    grid = grid_of(view.text) if view.owner_kind == "table" else None
    if grid is None or len(grid.body) < 2:
        return []
    numbers = grid.row_numbers()
    half = len(numbers) // 2
    return [replace(view, text=part_text(grid, set(numbers[:half]))),
            replace(view, text=part_text(grid, set(numbers[half:])))]


def slots_of(spec, parameter) -> list:
    """The coordinates a value of *parameter* is read with: its unit, then
    every axis the spec does not decide."""
    out = []
    unit = fields.unit_slot(spec, parameter) if parameter.is_numeric else None
    if unit is not None:
        out.append(unit)
    return out + fields.asked_slots(parameter)


def groups_of(spec, slots: list) -> list:
    """[(group, its slots)] of *slots*, in the order of the spec's groups:
    one request each (owner decision 2026-11-04). The spec puts every
    coordinate in exactly one group (`spec._validate_groups`)."""
    return [(group, [slot for slot in slots
                     if slot.name in group.coordinates])
            for group in spec.groups.values()
            if any(slot.name in group.coordinates for slot in slots)]


def group_context(context: dict, group_slots: list, frame_slots: list,
                  bases: list) -> dict:
    """What a group's request shows beside the passage: the text around it,
    and the survey's pairs and the plan's years only where the group asks a
    frame coordinate."""
    names = {slot.name for slot in group_slots}
    shown = {"around": context["around"]} if context.get("around") else {}
    if names & {slot.name for slot in frame_slots}:
        shown["known"] = context.get("known") or []
    shown.update(years_of(bases, group_slots))
    return shown


def coordinate_shown(slot) -> dict:
    shown: dict = {"question": slot.question}
    if slot.is_closed:
        shown["options"] = slot.answerable()
    else:
        shown["kind"] = slot.kind
    return shown


def answer_schema(slot) -> dict:
    """One coordinate's answer as the grammar takes it."""
    return {"type": "object",
            "properties": {"value": fields.value_schema(slot),
                           "value_raw": {"type": "string"},
                           "quote": {"type": "string"}},
            "required": ["value"], "additionalProperties": False}


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


def heading_of(source: Source) -> list:
    """The heading a request shows with *source* under "section", as a
    passage a quote may stand in (owner decision 2026-11-05): a table's or
    figure's the heading of its section, a section's its own. None where the
    passage's text carries it already or no section holds it."""
    provenance = source.provenance or {}
    title = provenance.get("section_title")
    at = source.owner_id if source.owner_kind == "section" \
        else provenance.get("parent_section")
    if not title or not at or title in (source.text or ""):
        return []
    return [Source("section", int(at), title,
                   {**provenance, "owner_kind": "section"})]


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
                # A list no search made, the ranking's, has no pattern.
                if not pattern or any(h.get("pattern") == pattern
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


# -- the values of a passage, one per round -------------------------------------

def parameter_shown(parameter) -> dict:
    return {"key": parameter.uri, "label": parameter.label,
            "definition": parameter.description}


def value_classes(parameter) -> dict:
    """The entries a category parameter's value is one of, as a request shows
    a closed list (`fields.Slot.answerable`), without UNSTATED: a value the
    passage does not state is no value. Empty for a parameter with no list."""
    if parameter.is_numeric:
        return {}
    slot = fields.value_choice(parameter)
    if not slot.is_closed:
        return {}
    return {label: entry for label, entry in slot.answerable().items()
            if label != fields.UNSTATED}


def source_shown(source: Source) -> dict:
    provenance = source.provenance or {}
    return {"kind": source.owner_kind,
            "section": provenance.get("section_title"), "text": source.text}


def with_head_asked(parameter, source: Source) -> bool:
    """Does a value of *parameter* in *source* name the head of its column?
    A number in a table: the head tells two equal numbers of one row apart
    and dates the number (owner decision 2026-11-05)."""
    return bool(parameter.is_numeric) and source.owner_kind == "table"


def shown_value(claim: dict) -> dict:
    """A value as a request shows it: its value, wording, quote and head."""
    return {key: claim[key] for key in ("value", "value_raw", "quote", "head")
            if claim.get(key) not in (None, "") or key == "value"}


def values_payload(source: Source, parameter, context: dict, read: list,
                   corrections: Optional[list] = None) -> dict:
    """One round of the values of a passage: the passage, the text around a
    table or figure and the parameter, a category parameter with its entries
    (`value_classes`), first, the values already read (*read*) and what the
    round fetched with its tools after them; with *corrections* the value of
    the round the check refused, asked once more. Nothing of the value's
    coordinates."""
    classes = value_classes(parameter)
    payload = {"source": source_shown(source),
               **({"around": context["around"]} if context.get("around")
                  else {}),
               "parameter": {**parameter_shown(parameter),
                             **({"value_classes": classes} if classes
                                else {})},
               "read": list(read),
               **{key: value for key, value in context.items()
                  if key != "around"}}
    if corrections:
        payload["corrections"] = corrections
    return payload


def values_response_format(parameter, head: bool = False) -> dict:
    """The next value of the passage, with its wording, its quote and, with
    *head*, the head of its column; null where no further value stands in it.
    A category value is one of its entries, or "" where the model is unsure
    of them."""
    classes = value_classes(parameter)
    if parameter.is_numeric:
        value = {"type": "number"}
    elif classes:
        value = {"enum": [*classes, ""]}
    else:
        value = {"type": "string"}
    properties = {"value": value, "value_raw": {"type": "string"},
                  "quote": {"type": "string"}}
    if head:
        properties["head"] = {"type": "string"}
    entry = {"type": "object", "properties": properties,
             "required": ["value", "quote"], "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"next": {"anyOf": [entry, {"type": "null"}]},
                             "more": more_schema()},
              "required": ["next"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "values_reply", "schema": schema}}


def claim_of(reply, head: bool = False) -> Optional[dict]:
    """The value a round's reply names, as a row's claim, or None where it
    names none. A table row quoted with others is cut to the one row that
    prints the number (`narrow_quote`)."""
    entry = reply.get("next") if isinstance(reply, dict) else None
    if not isinstance(entry, dict):
        return None
    claim = {"source": "Q1", "value": entry.get("value"),
             "quote": entry.get("quote")}
    if entry.get("value_raw"):
        claim["value_raw"] = entry["value_raw"]
    if head and isinstance(entry.get("head"), str) and entry["head"].strip():
        claim["head"] = entry["head"].strip()
    return narrow_quote(claim)


def _same_text(a, b) -> bool:
    return flat(str(a or "")).casefold() == flat(str(b or "")).casefold()


def same_value(a: dict, b: dict) -> bool:
    """Do two claims name the same value: the same number or wording, in the
    same quote, under the same head?"""
    left, right = a.get("value"), b.get("value")
    numbers = canonical_number(left), canonical_number(right)
    same = numbers[0] == numbers[1] if None not in numbers \
        else _same_text(left, right)
    return (same and _same_text(a.get("value_raw"), b.get("value_raw"))
            and _same_text(a.get("quote"), b.get("quote"))
            and _same_text(a.get("head"), b.get("head")))


def head_matches(table: str, cell: int, cells: int, head: str) -> bool:
    """Does *head* name the head of this column: its words on one head line,
    or all of them as `column_head` joins them?"""
    words = [w for _line, w in head_cells(table, cell, cells)]
    joined = column_head(table, cell, cells)
    return any(_same_text(head, w) for w in words) or (
        joined is not None and _same_text(head, joined))


def column_of(source: Source, claim: dict) -> Optional[tuple]:
    """(column, cells of its row) of a number in a table, 1-based, or None:
    the one column whose head is the head the model wrote and whose cell in
    the quoted row prints the number, else the one cell of the row that
    prints it (`pipeline.cell_index`). None where neither is certain: a
    wrong column is worse than none."""
    if source.owner_kind != "table":
        return None
    lines = printed_lines(claim.get("quote"))
    if len(lines) != 1:
        return None
    cells = cells_of(lines[0])
    head = claim.get("head")
    wanted = canonical_number(claim.get("value"))
    if head and wanted is not None:
        found = [c for c in range(1, len(cells) + 1)
                 if head_matches(source.text, c, len(cells), head)
                 and wanted in numbers_in(cells[c - 1])]
        if len(found) == 1:
            return (found[0], len(cells))
    return cell_index(claim.get("quote"), claim.get("value"))


def head_in_table(source: Source, head: str) -> bool:
    """Does any head line of the table print *head* over one of its
    columns?"""
    grid = grid_of(source.text)
    if grid is None:
        return False
    return any(head_matches(source.text, c, grid.columns, head)
               for c in range(1, grid.columns + 1)) or any(
        _same_text(head, cell) for line in grid.heads
        for cell in cells_of(line))


def passage_of(claim: dict, shown: list) -> Optional[Source]:
    """The first passage of *shown* whose text carries the claim's quote:
    the one its value is read from. None where the quote stands in none."""
    quote = claim.get("quote")
    if not isinstance(quote, str):
        return None
    return next((source for source in shown
                 if quote_in(source.text or "", quote)), None)


def source_of(batch: Batch, claim: dict) -> Source:
    """The passage of *batch* a claim is read from, by the label it carries
    (`Batch.label`), else the passage the batch was made for."""
    for index, item in enumerate(batch.items):
        if batch.label(index) == claim.get("source"):
            return item.source
    return batch.items[0].source


def value_failure(claim: dict, source: Source) -> Optional[str]:
    """Why the check of a value refuses it, or None: a quote not in its
    passage, a number its quote does not print (the harvest's own
    `number_outside_quote`). Said as the harvest says it."""
    quote = claim.get("quote")
    if not isinstance(quote, str) or not quote_in(source.text or "", quote):
        return say("quote_not_in_source")
    if number_outside_quote(claim):
        return say("value_outside_quote", values=json.dumps(
            [{"value": claim.get("value"), "quote": quote}],
            ensure_ascii=False))
    return None


def round_failure(claim: dict, shown: list, read: list,
                  numeric: bool = False) -> Optional[tuple]:
    """(kind, reason) of what the check refuses of a round's value, or None:
    a value already read (`REPEATED`), the value itself (`VALUE`: its quote
    in no passage of *shown*, its number not in its quote, a number quoted
    over several rows of its table that print it), or a head no head line of
    its table prints (`HEAD`)."""
    if any(same_value(claim, other) for other in read):
        return REPEATED, say("value_already_read",
                             value=json.dumps(claim.get("value"),
                                              ensure_ascii=False),
                             quote=claim.get("quote"))
    passage = passage_of(claim, shown)
    if passage is None:
        return VALUE, say("quote_not_in_source")
    reason = value_failure(claim, passage)
    if reason:
        return VALUE, reason
    table = numeric and passage.owner_kind == "table"
    if table and in_several_rows(claim):
        return VALUE, say("value_in_several_rows", values=json.dumps(
            [{"value": claim.get("value"), "quote": claim.get("quote")}],
            ensure_ascii=False))
    if table and claim.get("head") and not head_in_table(passage,
                                                         claim["head"]):
        return HEAD, say("head_not_in_table", head=claim["head"])
    return None


# -- one group's coordinates of one value ---------------------------------------

def text_payload(source: Source, parameter, slots: list, row: Row,
                 where: str, context: dict,
                 corrections: Optional[list] = None) -> dict:
    """One group's request for one value: the passage, the text around a
    table or figure, the parameter, the group's coordinates with the spec's
    words for where a plan prints them (*where*) and, for a frame group, the
    pairs and years (`group_context`) first; then the value with its quote,
    under "passage" the passage it stands in where that is neither the
    passage nor the text around it, and, under "read", what is already read
    of it in the plan's words, and what the request fetched with its tools;
    with *corrections* the same request asked once more."""
    value = shown_value(row.claim)
    if context.get("passage"):
        value["passage"] = context["passage"]
    if context.get("read"):
        value["read"] = context["read"]
    payload = {"source": source_shown(source),
               **({"around": context["around"]} if context.get("around")
                  else {}),
               "parameter": parameter_shown(parameter),
               "coordinates": {slot.name: coordinate_shown(slot)
                               for slot in slots},
               "where": where,
               **{key: context[key] for key in ("known", "base_years",
                                                 "target_years")
                  if key in context},
               "value": value,
               **{key: context[key] for key in ("more", "hits", "not_found")
                  if key in context}}
    if corrections:
        payload["corrections"] = corrections
    return payload


def text_response_format(slots: list) -> dict:
    """Every coordinate of the group for the one value the request shows,
    and what the reply asks of the rest of the plan."""
    properties = {slot.name: answer_schema(slot) for slot in slots}
    properties["more"] = more_schema()
    schema = {"type": "object", "properties": properties,
              "required": [slot.name for slot in slots],
              "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "text_reply", "schema": schema}}


def answer_of(entry: dict) -> dict:
    return {key: entry[key] for key in ("value", "value_raw", "quote")
            if key in entry}


def value_replies(reply: dict, slot, label: str) -> list:
    """[(level, window, field reply)] of one coordinate of a group's reply
    for the value *label*."""
    entry = reply.get(slot.name) if isinstance(reply, dict) else None
    if not isinstance(entry, dict):
        return []
    return [("value", ("own", 1), {"answers": {label: answer_of(entry)}})]


def refused_of(failed: list) -> collections.Counter:
    """What the check refused of a reply, by reason."""
    return collections.Counter(failure.get("why")
                               for _name, _level, failure in failed)


def value_corrections(row: Row, failed: list, slots: list) -> list:
    """What the check refused of a group's reply for one value, each named
    by its coordinate: [{coordinate, what}]. A coordinate the reply left out
    is named as missing."""
    out = []
    for slot in slots:
        if not row.claim.get(f"{slot.name}_state"):
            out.append({"coordinate": slot.name,
                        "what": say("key_missing", key=slot.name)})
    named = {entry["coordinate"] for entry in out}
    for name, _level, failure in failed:
        if failure.get("row") == row.label and name not in named:
            named.add(name)
            out.append({"coordinate": name, "what": failure.get("reason")})
    return out


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
    unread: bool = False          # no readable reply
    why: Optional[str] = None     # and why: cut_off or no_answer
    # Why each half of a table no reply answered came to nothing, the other
    # halves read: one hole each (`surveyed.taken_of`).
    lost: list = field(default_factory=list)
    corrected: int = 0            # corrections asked
    # what the check refused of the first replies, by reason
    failed: dict = field(default_factory=dict)
    unanswered: int = 0           # coordinates no reply answered
    fetched: int = 0              # passages shown under "more"
    searched: int = 0             # hit lists shown under "hits"
    missed: int = 0               # asks that found nothing


@dataclass
class _Job:
    """One parameter in one passage, as its requests share it."""
    document_id: int
    parameter: object
    source: Source
    shown: Source
    slots: list
    context: dict
    bases: list
    origin: tuple
    parent: tuple
    fixed: list
    frames: list
    merged: Callable
    passages: dict
    budget: Optional[int]
    result: Read
    pairs: list = field(default_factory=list)
    hits: list = field(default_factory=list)
    fetched: list = field(default_factory=list)
    # the piece of the passage each value was read in, by its label
    views: dict = field(default_factory=dict)

    def passages_shown(self, gathered: Gathered) -> list:
        """Every passage a request of this reading shows: the passage, its
        heading and the text around it, and what its tools fetched."""
        return [self.source, *self.fixed, *gathered.sources]

    def label_of(self, passage: Source) -> str:
        """The batch's label of *passage*, which joins the batch where it is
        not in it yet, so the fold checks a value read from it there."""
        batch = self.result.batch
        for index, item in enumerate(batch.items):
            if item.source is passage or (
                    (item.source.owner_kind, item.source.owner_id,
                     item.source.text)
                    == (passage.owner_kind, passage.owner_id, passage.text)):
                return batch.label(index)
        batch.items.append(WorkItem(self.document_id, self.parameter,
                                    passage))
        return batch.label(len(batch.items) - 1)

    def gathered(self) -> Gathered:
        """The tools of one request, the ranked list a search of the whole
        plan read this passage for (*hits*) shown first."""
        out = Gathered(seen={self.origin, self.parent},
                       cursor={"next": self.origin, "previous": self.parent})
        listed = [source for source in shown_hits(self.hits)
                  if (source.owner_kind, source.owner_id) not in out.seen]
        if listed:
            out.list_hits([((s.owner_kind, s.owner_id), lookup.title_of(s),
                            first_line(s)) for s in listed])
        return out


class Reader:
    """(document_id, survey, passages) -> [Read], one per parameter and
    passage the survey named for it.

    Two requests, each with one task and one value (owner decisions
    2026-11-04 and 2026-11-05), each the reply as a dict, CUT, or None:
    *ask_values(source, parameter, context, read, corrections)* the next
    value of a passage not among *read*; *ask_text(source, parameter, group,
    slots, row, context, corrections)* one group's coordinates of that
    value. *context* is what the request shows beside its passage,
    *corrections* None the first time and what was wrong the second.
    *shown_with(source)* is what a coordinate's quote may stand in besides
    the passage: the heading it stands under (`heading_of`).
    *known(claim, asked)* is what a value has read in the plan's words
    (`runner.row_context`). *pool* reads passages side by side.
    """

    def __init__(self, spec, ask_values: Callable, ask_text: Callable,
                 frame_slots: list, *, shown_with: Optional[Callable] = None,
                 bases: Optional[Callable] = None,
                 known: Optional[Callable] = None, pool=None, trace=None):
        self.spec = spec
        self.ask_values = ask_values
        self.ask_text = ask_text
        self.frame_slots = frame_slots
        self.shown_with = shown_with or (lambda source: [])
        self.bases = bases or (lambda pairs: [])
        self.known = known or (lambda claim, asked: {})
        self.pool = pool
        self.trace = trace

    def __call__(self, document_id: int, found, passages: dict,
                 budget: Optional[int] = None) -> list:
        """One Read per parameter and passage the survey named for it. A
        section or figure longer than *budget* characters, the survey's two
        pages, is read in the survey's pieces. A passage a search of the
        whole plan named for a parameter (`Found.hits`) shows that search's
        list in its reading for that parameter."""
        from .survey import pieces

        pairs: list = []
        for answer in found.answers.values():
            for one in answer.tuples.get("frame", ()):
                if one not in pairs:
                    pairs.append(one)
        hits = getattr(found, "hits", None) or {}
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
                             shown=shown, budget=budget,
                             hits=hits.get((parameter.uri,) + owner))
        if self.pool is None:
            return [one(job) for job in jobs]
        return list(self.pool.map(one, jobs))

    def context_of(self, source: Source, tuples: list, passages: dict,
                   budget: Optional[int]) -> tuple:
        """(what the requests of a passage show beside it, the section it
        was cut from): the text around a table or figure (`around_of`) and
        the survey's pairs of the passage, which only a group that asks a
        frame coordinate shows (`group_context`)."""
        around = around_of(source, passages, budget)
        context = {"around": around.text} if around is not None else {}
        context["known"] = known_of(tuples, self.frame_slots)
        return context, around

    def read(self, document_id: int, parameter, source: Source,
             tuples: list, pairs: list, passages: dict,
             shown: Optional[Source] = None,
             budget: Optional[int] = None,
             hits: Optional[list] = None) -> Read:
        """*source* is the passage a value is verified against, *shown* the
        piece of it the requests show, *budget* the survey's two pages,
        *hits* the ranked list a search of the whole plan read it for. The
        values in rounds (`_values`), each placed in its table
        (`_placed`), then each group of the spec for each value
        (`_value_group`)."""
        shown = shown or source
        slots = slots_of(self.spec, parameter)
        # The reading's spec rides on the batch, so the fold checks a value
        # against the lists this document closes (`runner.spec_of`).
        batch = Batch(document_id, parameter,
                      [WorkItem(document_id, parameter, source)],
                      spec=self.spec)
        bases = self.bases(pairs)
        context, around = self.context_of(source, tuples, passages, budget)
        origin = (source.owner_kind, source.owner_id)
        parent = (around.owner_kind, around.owner_id) \
            if around is not None else origin
        result = Read(batch, [])
        # What a coordinate's quote may stand in besides what a request
        # shows of the passage: its heading, the text around it, the frame.
        fixed = list(self.shown_with(source)) + (
            [around] if around is not None else [])
        frames = [passages[tuple(one[f"{s.name}_source"])] for one in tuples
                  for s in self.frame_slots
                  if tuple(one.get(f"{s.name}_source") or ()) in passages]

        def merged(rows: list, replies: dict, evidence: list) -> list:
            """Every coordinate's answers onto *rows*; [(coordinate, level,
            failure)] of what the check refused."""
            failed = []
            for slot in slots:
                for level, window, field_reply in replies.get(slot.name, ()):
                    got = merge_field(rows, evidence, slot, field_reply,
                                      window=window, bases=bases)
                    failed.extend((slot.name, level, failure)
                                  for failure in got["failed"])
            return failed

        job = _Job(document_id, parameter, source, shown, slots, context,
                   bases, origin, parent, fixed, frames, merged, passages,
                   budget, result, pairs=list(pairs), hits=list(hits or ()))
        rows, views = self._values(job)
        if not views:
            result.unread = True
            result.why = result.lost[0] if result.lost else NO_ANSWER
            result.lost = []
            if self.trace is not None:
                self.trace("read", document_id, parameter=parameter.uri,
                           kind=source.owner_kind, owner=source.owner_id,
                           values=0, unread=True, why=result.why,
                           asked=result.asked)
            return result
        for row in rows:
            self._placed(job, row)
        groups = groups_of(self.spec, slots)
        for row in rows:
            for group, group_slots in groups:
                self._value_group(job, row, group, group_slots)
        evidence = list(views) + fixed + job.fetched + frames
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
                       values=len(rows), asked=result.asked,
                       corrected=result.corrected, failed=result.failed,
                       unanswered=result.unanswered, fetched=result.fetched,
                       searched=result.searched, missed=result.missed)
        return result

    @staticmethod
    def _noted(job: _Job, gathered: Gathered) -> None:
        """What one request's tools fetched, onto the reading of the
        passage."""
        job.fetched.extend(gathered.sources)
        job.result.fetched += len(gathered.sources)
        job.result.searched += len(gathered.hits)
        job.result.missed += len(gathered.missed)

    def _values(self, job: _Job) -> tuple:
        """(rows, [each piece shown]) of the passage, its values read in
        rounds (`_rounds`). A table whose request no longer fits the model's
        window is read in halves of its rows; a single row, or any other
        passage, that does not fit is a hole of its own, as is a piece no
        round answered (`Read.lost`)."""
        result = job.result
        pending = [job.shown]
        rows: list = []
        views: list = []
        while pending:
            view = pending.pop(0)
            got = self._rounds(job, view, start=len(rows))
            if got == CUT:
                split = halves(view)
                if split:
                    pending[:0] = split
                    continue
                result.lost.append(CUT)
                continue
            if got is None:
                result.lost.append(NO_ANSWER)
                continue
            for row in got:
                job.views[row.label] = view
            rows.extend(got)
            views.append(view)
        return rows, views

    def _rounds(self, job: _Job, view: Source, start: int = 0):
        """The values of one piece, one per round, until the model names no
        further value; CUT or None where its first round came to nothing. A
        value the check refuses is asked once more with the reason; one
        named again is asked once more, and named again it ends the rounds
        (owner decision 2026-11-05). The rounds of a piece share their
        tools: what one fetched, the next one shows."""
        result = job.result
        head = with_head_asked(job.parameter, view)
        numeric = bool(job.parameter.is_numeric)
        gathered = job.gathered()
        shows = ({"around": job.context["around"]}
                 if job.context.get("around") else {})
        rows: list = []
        read: list = []

        def ask(corrections: Optional[list] = None):
            return self.ask_values(view, job.parameter,
                                   {**shows, **gathered.context()},
                                   list(read), corrections)
        first = True
        while True:
            reply = ask()
            result.asked += 1
            if not isinstance(reply, dict):
                if first:
                    self._noted(job, gathered)
                    return CUT if reply == CUT else None
                break
            first = False
            reply, more = gather(ask, reply, gathered,
                                 list(job.passages.values()), job.passages,
                                 job.budget)
            result.asked += more
            claim = claim_of(reply, head)
            if claim is None:
                break
            failure = round_failure(claim, job.passages_shown(gathered),
                                    [r.claim for r in rows], numeric)
            if failure is not None:
                kind, reason = failure
                result.failed = dict(collections.Counter(result.failed)
                                     + collections.Counter({kind: 1}))
                result.corrected += 1
                again = ask([{**shown_value(claim), "what": reason}])
                result.asked += 1
                claim = claim_of(again, head)
                if claim is None:
                    break
                failure = round_failure(claim, job.passages_shown(gathered),
                                        [r.claim for r in rows], numeric)
                if failure is not None and failure[0] == REPEATED:
                    break
                if failure is not None and failure[0] == HEAD:
                    # Asked once: a head no head line prints says nothing of
                    # the column, and the number's own cell may still.
                    claim.pop("head", None)
            passage = passage_of(claim, job.passages_shown(gathered))
            if passage is not None:
                claim["source"] = job.label_of(passage)
            rows.append(Row(label=row_label(start + len(rows)), item_index=0,
                            claim=claim))
            read.append(shown_value(claim))
        self._noted(job, gathered)
        return rows

    def _placed(self, job: _Job, row: Row) -> None:
        """A number in a table placed in its column: the head over it on the
        claim, and the year that head names read off the head line
        (`pipeline.with_head`); where exactly one pair of the document has
        that year, the pair's other frame coordinates, through the field
        check with the pair's quotes (`pipeline.head_pair`). The table is the
        one the value is read from."""
        own = source_of(job.result.batch, row.claim)
        if own.owner_kind != "table" or not job.parameter.is_numeric:
            row.claim.pop("head", None)
            return
        claim = dict(row.claim)
        cell = column_of(own, claim)
        claim.pop("head", None)
        if cell is not None:
            claim[CELL] = cell
        row.claim = with_head(claim, own, tuple(job.pairs),
                              self.frame_slots)
        found = head_pair(row.claim, tuple(job.pairs), None, self.frame_slots)
        if found is None:
            return
        pair, index = found
        for slot in self.frame_slots:
            if row.claim.get(f"{slot.name}_state") == READ \
                    or slot.name not in {s.name for s in job.slots}:
                continue
            source = tuple(pair.get(f"{slot.name}_source") or ())
            shown = [job.passages[source]] if source in job.passages else []
            answer = {"value": pair.get(slot.name),
                      "quote": pair.get(f"{slot.name}_quote")}
            if pair.get(f"{slot.name}_raw"):
                answer["value_raw"] = pair[f"{slot.name}_raw"]
            merge_field([row], shown + job.frames, slot,
                        {"groups": [dict(answer, rows=[row.label])]},
                        window=("frame", index + 1))

    def _value_group(self, job: _Job, row: Row, group,
                     group_slots: list) -> None:
        """One group's coordinates of one value, those still open only, in a
        request with the group's own tools; what the check refuses asked
        once more, by its coordinate."""
        asked = [slot for slot in group_slots
                 if row.claim.get(f"{slot.name}_state") != READ]
        if not asked:
            return
        result = job.result
        view = job.views.get(row.label, job.shown)
        gathered = job.gathered()
        base = group_context(job.context, asked, self.frame_slots, job.bases)
        read = self.known(row.claim, [slot.name for slot in asked])
        # A value read from a passage its round fetched is shown with it.
        own = source_of(job.result.batch, row.claim)
        apart = [] if any(own is s for s in (job.source, *job.fixed)) \
            else [own]
        if apart:
            base["passage"] = {"kind": own.owner_kind,
                               "title": lookup.title_of(own),
                               "text": own.text}

        def ask(corrections: Optional[list] = None):
            return self.ask_text(view, job.parameter, group, asked, row,
                                 {**base, **({"read": read} if read else {}),
                                  **gathered.context()}, corrections)
        reply = ask()
        result.asked += 1
        if not isinstance(reply, dict):
            self._noted(job, gathered)
            return
        reply, more = gather(ask, reply, gathered,
                             list(job.passages.values()), job.passages,
                             job.budget)
        result.asked += more
        self._noted(job, gathered)
        evidence = [view] + job.fixed + apart + gathered.sources + job.frames
        failed = job.merged([row], {slot.name: value_replies(reply, slot,
                                                             row.label)
                                    for slot in asked}, evidence)
        corrections = value_corrections(row, failed, asked)
        result.failed = dict(collections.Counter(result.failed)
                             + refused_of(failed))
        if corrections:
            result.corrected += len(corrections)
            result.asked += 1
            again = ask(corrections)
            if isinstance(again, dict):
                job.merged([row], {slot.name: value_replies(again, slot,
                                                            row.label)
                                   for slot in asked}, evidence)
