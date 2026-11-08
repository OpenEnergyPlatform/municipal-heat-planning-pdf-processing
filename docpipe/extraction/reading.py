"""
reading.py: The values of one parameter in the passages the survey named for
it, one value per request: rounds name the values of a passage one by one,
then each value is asked its coordinates one by one, each a message of the
value's own conversation.

Step 3 of the rebuilt harvest (owner decisions 2026-11-04, 2026-11-05 and
2026-11-07). Every request has one task and reads exactly one value. A table
is read like a section: the model repeats each value as the passage prints
it, with a quote that pins it down, and code takes nothing from where it
stands (owner decision 2026-11-07: "streich diese ganze Code Logik").

A round shows the parameter in short (its `brief`), the whole passage (a table
with its title, its head and all its rows, or the survey's piece of a
section), the text around a table or figure, the line of the title page and
the table the passage may continue, and asks for the next value not yet read,
until the model says there is none. A value may stand in any passage the
round showed; it is read from the one its quote stands in, which joins the
reading's batch, so the fold checks it there (`pipeline.route_claims`). Its
quote stands in what was shown exactly once and holds the value exactly
once, each counted where it stands for itself and not as part of a longer
name or number (`verify.times_quoted`, `verify.times_stated`):
"410.662,44 | 1.109 | 6%" pins down the 1.109 of its row. A value the check
refuses (its quote in no passage shown, its number not in its quote, whatever
else the fold refuses of the value and its quote (`verify.value_refused`), a
quote that does not pin it down) is asked once more with the reason; one
named again is asked once more, and named again it ends the rounds. No
request that reads has tools.

A number a figure only draws, as a bar, a segment, an area or a point of a
curve, is a value of the plan and an estimate (owner decisions 2026-11-05 and
2026-11-07). Where a figure's image goes with the request, every value of the
round says whether the image only draws it; one no shown text states is read
off the image, its reading in place of a quote, and that reading is its
evidence (`verify.read_off`), trust level C.

Then the value's coordinates are asked one by one, in the order of the spec's
groups and of the coordinates in each (`Spec.groups`, `groups_of`), all in
one conversation (owner decision 2026-11-07: "Die Fragen A, B und C sind ja
eigentlich mehrere Fragen und sollten dann auch nacheinander gestellt
werden"): the first message shows the passage and the value, each later one
brings the words of the coordinate's group and that coordinate only, and the
model sees what it answered before. Every coordinate is asked, scenario and
year too, each for this value alone (owner decision 2026-11-07: nothing is
taken from its passage or its table). Every request about a value's
coordinates shows the titles of the last sections of the plan up to the
value's place, its own last (`SECTION_TITLES`). The system prompt is what
every message is told and the part of each field the first message carries.
The rounds of a passage's values are a conversation as well: each later
round asks for the next value after the answer it follows. A correction goes
after the answer it is about, in its conversation.

With a pool, the conversations of a passage's values run side by side once
its rounds have named them, as the passages do, and none waits for another
(owner decision 2026-11-07: every place stays taken to the end). A value
read as no value of its parameter is asked for once more when every value of
its passage is done, in the order of the values, so the rounds' conversation
gets the messages it got when the values went one after another. A passage
read goes to *on_read* the moment it is done, where its combing begins.

Every coordinate asked is answered: the grammar requires it, and "the
passage does not say" is one of the answers (`fields.UNSTATED`).

A coordinate whose answer is the name the document gives a thing, such as
a scenario, is read as the document prints it (`fields.Slot.merged`). A
value the passage states for several of them is one row per name, each
checked on its own (`answers_each`, owner decision 2026-11-06), and so is a
value stated for several entries of a list that may name several
(`fields.Slot.several`, owner decision 2026-11-07); names that
stand in one place may share one quote, which must hold each of them
(`spread`, owner decision 2026-11-07). What the check refuses on any of the
rows one answer made is asked once more in ONE message after that answer,
naming each refused name with its quote, and each answer of it goes to the
row of its name, a changed name to the next row still open, a further name
to a row of its own (`routed`, owner decisions 2026-11-07). Which names
mean the same thing is asked once the document is read (`naming.py`).

Nothing is checked here beyond what the harvest checks everywhere. Every
coordinate goes through `pipeline.merge_field` and every value through
`fold_batch`. What that check refuses is asked once more with its reason,
named by its coordinate; a coordinate the reply left out is asked for by
name. A year the plan states for a span of years ("im Mittel der Jahre 2019
bis 2021") is one row per year of the span, each marked as the profile
marks a span (`span_rows`, owner decision 2026-11-07). What is still open
then is asked in a conversation of its own, with the answers so far,
the sections around the value's place and the rest of the plan
(`combing.py`). A request too long for the model's window is split: a table
into halves of its rows, until a single row is a hole of its own
(`Read.lost`).

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import copy
import json
import re
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from . import fields, lookup
from .thread import CORRECTIONS, Thread
from .pipeline import (READ, YEAR_STATES, Batch, Row, Source, WorkItem,
                       answer_in_quote, mark_unanswered, merge_field,
                       printed_lines, row_label, window_around)
from .verify import (MIN_QUOTE_CHARS, canonical_number, flat,
                     number_outside_quote, quote_in, read_off, times_quoted,
                     times_stated, value_refused)
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

# The titles of the sections of the plan up to a value's place, its own last,
# that every request about the value's coordinates shows (owner decision
# 2026-11-07: "die vorigen 10 Section Titles mitgeben inklusive des
# aktuellen").
SECTION_TITLES = 10

# What a reading request tells of a quote that stands in nothing it showed,
# in the names of what it shows: "source", the heading of its section,
# "around" (owner decision 2026-11-06).
NOT_SHOWN = "quote_not_in_passage"

# What a message that follows an answer in the same conversation carries
# (owner decisions 2026-11-07, `thread.py`): the ask for the next value of a
# passage, what the check refused of the answer, and, in the conversation for
# what the reading left open (`combing.py`), the coordinate asked next.
NEXT = "next"
COORDINATES = "coordinates"
# A value its coordinates read as no value of its parameter (`fields.kept`),
# asked for once more in its passage's rounds, told that it was read wrongly
# and why (owner decision 2026-11-07: "noch einmal nachfragen mit dem
# hinweis, dass das falsch ist").
WRONG = "wrong"

# Why the check refused a round's value, as `Read.failed` counts it: the value
# itself, a quote that does not pin it down (owner decision 2026-11-07), or a
# value already read.
VALUE, UNIQUE, REPEATED = "value", "unique", "repeated"

# The request that asks of a find whether the place it was quoted from
# speaks about its value, where the value's own request did not show that
# place: a passage the combing fetched or listed, or a section before or
# after the value's place in its second reading (owner decisions 2026-11-07,
# after a probe in which the model took the scenario of a neighbouring
# sentence: "The green marker indicates projections of EC LTS Baseline for
# 2030" for years of other figures). Its answers, and the reason a find it
# says "no" to is not taken. The check is told what was wrong with its
# answer.
CHECK_PROMPT_ID = "extraction/comb_check"
ABOUT = ("yes", "no")
NOT_ABOUT = "not_about_value"
CHECK_FOLLOWS = (CORRECTIONS,)


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
    every axis, one the spec derives from the unit included, which is asked
    where the unit question chose no entry of the parameter's list
    (`fields.derived_by_unit`)."""
    out = []
    unit = fields.unit_slot(spec, parameter) if parameter.is_numeric else None
    if unit is not None:
        out.append(unit)
    return out + fields.axis_slots(parameter)


def in_group_order(group, group_slots: list) -> list:
    """A group's coordinates in the order its spec entry names them: the
    order their questions are asked in, one message each."""
    order = list(group.coordinates)
    return sorted(group_slots, key=lambda slot: order.index(slot.name)
                  if slot.name in order else len(order))


def groups_of(spec, slots: list) -> list:
    """[(group, its slots)] of *slots*, in the order of the spec's groups:
    one request each (owner decision 2026-11-04). The spec puts every
    coordinate in exactly one group (`spec._validate_groups`)."""
    return [(group, [slot for slot in slots
                     if slot.name in group.coordinates])
            for group in spec.groups.values()
            if any(slot.name in group.coordinates for slot in slots)]


def group_context(context: dict) -> dict:
    """What a group's request shows beside the passage: the text around it,
    the plan's settings, the titles of the sections up to the value's place
    (`sections_of`), the title page's line and the table it may continue
    (`beside_of`)."""
    return {key: context[key]
            for key in ("around", "settings", "sections") + BESIDE
            if context.get(key)}


def sections_of(source: Source, passages: dict) -> tuple:
    """([title], [passage a quote may stand in]) of the last
    `SECTION_TITLES` sections of the plan up to *source*, its own last: a
    table's or figure's own section is the one it stands in. Each title is
    shown, and may be quoted, under its section (`shown_as`)."""
    titles, pieces = [], []
    for section in lookup.sections_up_to(
            list(passages.values()), (source.owner_kind, source.owner_id),
            SECTION_TITLES):
        title = lookup.title_of(section)
        if title:
            titles.append(title)
            pieces += shown_as(section, title)
    return titles, pieces


def coordinate_shown(slot, unstated: bool = True) -> dict:
    """A coordinate as a request shows it: its question, and its list, or
    the kind of its answer; without *unstated* a list without UNSTATED, as
    the combing asks (`fields.value_schema`). A coordinate of names shows
    the entries it takes beside them under its kind (`fields.beside_names`,
    owner decision 2026-11-07), without UNSTATED, which a wording answers."""
    shown: dict = {"question": slot.question}
    if slot.is_closed:
        shown["options"] = {label: entry
                            for label, entry in slot.answerable().items()
                            if unstated or label != fields.UNSTATED}
    else:
        shown["kind"] = slot.kind
        if fields.beside_names(slot):
            shown["options"] = {label: entry
                                for label, entry in slot.answerable().items()
                                if label != fields.UNSTATED}
    return shown


def several(slot) -> bool:
    """May one value name several things for *slot*, one row each: a
    coordinate whose answer is the name the document gives a thing, merged
    with the document's other names for it after the reading (`naming.py`,
    owner decisions 2026-11-06), or one whose list may name several entries
    for one value (`fields.Slot.several`, owner decision 2026-11-07)?"""
    return bool(getattr(slot, "merged", None)) \
        or bool(getattr(slot, "several", False))


def answer_schema(slot, probe: bool = False, unstated: bool = True) -> dict:
    """One coordinate's answer as the grammar takes it, its printed wording
    only where `fields.wording_asked`; with *probe* also the sentence a reply
    writes to a coordinate its passage does not state, as the plan would
    print it, which the combing searches with (owner decision 2026-11-05:
    HyDE). A coordinate that may name several things (`several`) takes a
    list of such answers too, and an answer that names several of them with
    one quote, its names under "value" (owner decision 2026-11-07: one
    quote for several names; `spread`). Without *unstated* its answer is
    never UNSTATED (`fields.value_schema`)."""
    properties = {"value": fields.value_schema(slot, unstated)}
    if fields.wording_asked(slot):
        properties["value_raw"] = {"type": "string"}
    properties["quote"] = {"type": "string"}
    if slot.kind == fields.NUMBER:
        # The last year of a span the value is stated for (`span_rows`).
        properties["until"] = {"type": "integer"}
    if probe:
        properties["probe"] = {"type": "string"}
    one = {"type": "object", "properties": properties,
           "required": ["value"], "additionalProperties": False}
    if several(slot):
        shared = {"type": "object",
                  "properties": {
                      "value": {"type": "array",
                                "items": fields.value_schema(slot, False),
                                "minItems": 2},
                      "quote": {"type": "string"}},
                  "required": ["value", "quote"],
                  "additionalProperties": False}
        return {"anyOf": [one, shared,
                          {"type": "array", "items": {"anyOf": [one, shared]},
                           "minItems": 1}]}
    return one


def entry_example(slot) -> dict:
    """One coordinate's entry as the example of a request shows it: the
    keys `answer_schema` asks, in its order, read (owner decisions
    2026-11-06): its answer (`fields.value_example`), its printed wording
    wherever the grammar asks one, so beside every entry of a list, the unit
    included, and its quote. No probe: that is the sentence of an unstated
    entry, which the prompt's rule line shows. A coordinate that may name
    several things shows one, the form a list repeats."""
    entry = {"value": fields.value_example(slot)}
    if fields.wording_asked(slot):
        entry["value_raw"] = fields.SAID
    entry["quote"] = fields.SAID
    return entry


def names_several(given) -> bool:
    """Does a coordinate's answer name several things: a list, or an answer
    whose names share one quote?"""
    return isinstance(given, list) or (
        isinstance(given, dict) and isinstance(given.get("value"), list))


def entries_of(given) -> list:
    """A coordinate's answer as single answers: each entry of a list, and an
    answer that names several things with one quote (owner decision
    2026-11-07) once per name, each with that quote."""
    out = []
    for one in (given if isinstance(given, list) else [given]):
        names = one.get("value") if isinstance(one, dict) else None
        if isinstance(names, list):
            rest = {key: value for key, value in one.items() if key != "value"}
            out.extend({**rest, "value": name} for name in names)
        else:
            out.append(one)
    return out


def spread(reply, slots: list):
    """*reply* with each coordinate that may name several things
    (`several`) and names several as a list of single answers
    (`entries_of`): what follows a reply -- the check of a find, the rows of
    a value -- reads one name with its quote. Anything else is left as it
    is."""
    if not isinstance(reply, dict):
        return reply
    out = dict(reply)
    for slot in slots:
        if several(slot) and names_several(reply.get(slot.name)):
            out[slot.name] = entries_of(reply[slot.name])
    return out


def answers_each(reply, slots: list) -> list:
    """The reply for one value as one reply per row (owner decision
    2026-11-06): a coordinate that may name several things (`several`) and
    names several of them, in a list or with one quote for several
    (`entries_of`), gives one reply per name, with every other coordinate's
    answer the same on each; an empty list is no answer. Any other reply is
    the one reply."""
    if not isinstance(reply, dict):
        return [reply]
    out = [reply]
    for slot in slots:
        given = reply.get(slot.name)
        if not several(slot) or not names_several(given):
            continue
        each = [one for one in entries_of(given)
                if isinstance(one, dict)] or [None]
        out = [{**one, slot.name: answer} for one in out for answer in each]
    return out


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


def shown_as(source: Optional[Source], text) -> list:
    """*text*, which a request shows with *source*, as a passage a quote may
    stand in (owner decision 2026-11-05: whatever a request shows of a
    document may be quoted): a hit's line, a title, a wording a value has
    read. A coordinate quoting it cites *source*. Only the text shown
    counts, not the rest of *source*. [] for no text."""
    if source is None or not isinstance(text, str) or not text.strip():
        return []
    return [replace(source, text=text, body=None)]


def passage_at(passages: dict, owner) -> Optional[Source]:
    """The passage *owner*, [kind, id], names: the one among *passages*, else
    a bare one of that name. None for no owner."""
    if not isinstance(owner, (list, tuple)) or len(owner) != 2:
        return None
    try:
        at = (owner[0], int(owner[1]))
    except (TypeError, ValueError):
        return None
    return passages.get(at) or Source(at[0], at[1], "")


def known_shown(claim: dict, known: dict, passages: dict) -> list:
    """What a request shows of what a value has read (*known*, {coordinate:
    the plan's wording}, `runner.row_context`), each wording a passage a
    quote may stand in under the passage its coordinate was read in
    (`shown_as`)."""
    return [one for name, wording in (known or {}).items()
            for one in shown_as(passage_at(passages,
                                           claim.get(f"{name}_source")),
                                wording)]


def around_of(source: Source, passages: dict,
              budget: Optional[int]) -> Optional[Source]:
    """The text of the section a table or figure stands in, as its request
    shows it (owner decisions 2026-11-04 and 2026-11-05): the whole section,
    other tables and figures of it included, when it fits *budget*, two
    pages of the plan, else that many characters around the table's place
    in it. The model reads from it what it needs: a cut to 200 characters on
    each side would have hidden the text of 72 % of the quotes the m8 run
    took from a table's section. None for a section, and for a table or
    figure whose section is not among *passages*."""
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


# What the second reading of a value shows beside it, the sections before and
# after its place (owner decisions 2026-11-06 and 2026-11-07, `combing.py`),
# and what any reading request shows beside a passage: the line of the title
# page that names the plan's own place, and the title and head of the table
# right before a table, which it may continue.
NEAR = ("before", "after")
# The fields of the follow-ups each kind of reading request sends, whose
# words its prompt holds (`runner.FOLLOWS`).
VALUE_FOLLOWS = (NEXT, CORRECTIONS, WRONG)
TEXT_FOLLOWS = (CORRECTIONS,)
BESIDE = ("title_page", "table_before")


def near_of(source: Source, order: list,
            budget: Optional[int]) -> dict:
    """{"before": Source, "after": Source}: the sections before and after a
    value's place, which is the section a table or figure stands in, as the
    second reading shows them (owner decision 2026-11-06: where the reading
    said a coordinate is not stated, it is asked once more with the plan
    around it). Together at most *budget*, two pages of the plan, each side
    the part nearest the place. A side without a section is left out; {}
    where the plan has neither."""
    provenance = source.provenance or {}
    place = (source.owner_kind, source.owner_id)
    parent = provenance.get("parent_section")
    if source.owner_kind != "section" and parent is not None and any(
            (p.owner_kind, p.owner_id) == ("section", int(parent))
            for p in order):
        place = ("section", int(parent))
    found = {}
    for key, step in zip(NEAR, (-1, 1)):
        got = lookup.following(order, place, step)
        if got is not None and (got.text or "").strip():
            found[key] = got
    if not found:
        return {}
    share = budget // len(found) if budget else None
    out = {}
    for key, got in found.items():
        text = got.text
        if share and len(text) > share:
            text = text[-share:] if key == "before" else text[:share]
        out[key] = replace(got, text=text, body=None)
    return out


def table_before_of(source: Source) -> Optional[Source]:
    """The title and head of the table right before *source*, on its page
    or the page before, which *source* may continue (`lookup.continued`), as
    a passage a quote may stand in; whether the table continues it is the
    model's reading (owner decisions 2026-11-06 and 2026-11-07). None for
    any other passage."""
    before = (source.provenance or {}).get("table_before")
    if not isinstance(before, dict) or not before.get("text"):
        return None
    owner = before.get("owner") or ()
    try:
        kind, at = str(owner[0]), int(owner[1])
    except (IndexError, TypeError, ValueError):
        return None
    return Source(kind, at, before["text"], {"owner_kind": kind})


def settings_shown(settings: list) -> list:
    """The plan's settings as a request shows them: what each is about, what
    it settles and its quote (`settings.PlanSettings`, owner decision
    2026-11-07)."""
    return [{key: one[key] for key in ("about", "value", "quote")
             if one.get(key)} for one in settings or ()
            if isinstance(one, dict)]


def settings_evidence(settings: list, passages: dict) -> list:
    """The quotes of the plan's settings, each a passage a quote may stand
    in under the passage it was read from."""
    return [piece for one in settings or () if isinstance(one, dict)
            for piece in shown_as(passage_at(passages, one.get("source")),
                                  one.get("quote"))]


def beside_of(source: Source, title_page: Optional[Source]) -> tuple:
    """({key: text} a reading request shows beside *source*, [the passages
    a coordinate's quote may stand in for them]): the line of the title page
    that names the plan's own place (owner decision 2026-11-06) and the
    title and head of the table *source* may continue (`table_before_of`)."""
    shown, pieces = {}, []
    for key, piece in zip(BESIDE, (title_page, table_before_of(source))):
        if piece is not None and (piece.text or "").strip():
            shown[key] = piece.text
            pieces.append(piece)
    return shown, pieces


# -- what a reply may ask of the rest of the plan -----------------------------

# What a reply may ask for under "more" (owner decisions 2026-11-04 and
# 2026-11-05): the next or the previous section, a table or figure by its
# placeholder, the passages of the plan matching a pattern as a list, the
# passages nearest to a sentence the model wrote as the plan would print it
# as a list ("similar", HyDE), a passage of such a list by its id.
GETS = ("next", "previous", "item", "search", "similar", "hit")
# Why an ask found nothing, as the reply's "not_found" says it: past the end
# of the plan, or a name that fits no passage or more than one. A pattern
# that does not compile or does not finish says `lookup.matching`'s fault.
END, UNKNOWN = "end", "unknown"
# What a hit list was searched with, kept by the gathering and not shown: a
# request shows the plan's text, and the run's own sentences were quoted as
# the plan's (owner decision 2026-11-06).
SEARCHED_WITH = ("query", "similar", "pattern")


def more_schema(gets: tuple = GETS) -> dict:
    """The asks a reply may carry under "more": any of *gets*, by default
    every one."""
    return {"type": "array", "items": {
        "type": "object",
        "properties": {"get": {"enum": list(gets)},
                       "id": {"type": "string"},
                       "pattern": {"type": "string"},
                       "text": {"type": "string"}},
        "required": ["get"], "additionalProperties": False}}


@dataclass
class Gathered:
    """What one read fetched of the rest of the plan, in the order the model
    asked for it: the passages its request shows under "more", the hit lists
    of its searches under "hits", and what could not be found, with why,
    under "not_found". *seen* are the passages the request already shows,
    *cursor* where "next" and "previous" go on from, *rank(probes, exclude)*
    the plan's passages best first for sentences, which "similar" lists
    (`runner.make_more_sources`); None where the run ranks nothing. *unfit*
    is set when a request of the gathering no longer fit the model's window
    or came back unread (`gather`)."""
    seen: set = field(default_factory=set)
    cursor: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    shown: list = field(default_factory=list)
    hits: list = field(default_factory=list)
    missed: list = field(default_factory=list)
    by_hit: dict = field(default_factory=dict)
    rank: Optional[Callable] = None
    unfit: bool = False

    def context(self) -> dict:
        """What a first message shows of the gathering so far: the passages
        fetched under "more", the hit lists under "hits", each without what
        it was searched with (`SEARCHED_WITH`), and what could not be
        fetched under "not_found"."""
        return self.since((0, 0, 0))

    def mark(self) -> tuple:
        """Where the gathering stands: how many passages it showed, hit
        lists it made and misses it noted, for what a later message brings
        anew (`since`)."""
        return (len(self.shown), len(self.hits), len(self.missed))

    def since(self, mark: tuple) -> dict:
        """What the gathering added after *mark*, as `context` shows it: a
        later round of a search brings only what is new, after the answer
        it follows (owner decisions 2026-11-07)."""
        shown, hits, missed = mark
        out = {}
        if self.shown[shown:]:
            out["more"] = list(self.shown[shown:])
        if self.hits[hits:]:
            out["hits"] = [{key: value for key, value in listed.items()
                            if key not in SEARCHED_WITH}
                           for listed in self.hits[hits:]]
        if self.missed[missed:]:
            out["not_found"] = list(self.missed[missed:])
        return out

    def listed(self) -> set:
        """The passages the request has listed as a hit or shown."""
        return {owner for owner, _line in self.by_hit.values()} | self.seen

    def evidence(self, passages: dict) -> list:
        """What the request showed of the plan, as passages a quote may stand
        in (owner decision 2026-11-05: whatever a request shows of a document
        may be quoted): each passage it fetched as shown, then each one's
        title, and the line and title of each hit, under the passage it was
        shown with (`shown_as`)."""
        out = list(self.sources)
        for source, entry in zip(self.sources, self.shown):
            out += shown_as(source, entry.get("title"))
        for listed in self.hits:
            for hit in listed.get("hits") or ():
                owner = self.by_hit.get(hit.get("id"), (None,))[0]
                source = passage_at(passages, owner)
                out += shown_as(source, hit.get("line"))
                out += shown_as(source, hit.get("title"))
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
                 **{key: ask[key] for key in ("id", "pattern", "text")
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
        *budget*, two pages of the plan. True when a passage or a hit list
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
            elif get == "similar":
                text = ask.get("text")
                if not isinstance(text, str) or not text.strip() \
                        or any(h.get("similar") == text for h in self.hits):
                    continue
                if self.rank is None:
                    self._miss(ask, UNKNOWN)
                    continue
                # The best of each kind, as the combing's list shows them
                # (owner decision 2026-11-05: `SHOWN`), the passages the
                # request shows left out.
                ranked = shown_hits(self.rank([text], set(self.seen)))
                if not self.list_hits(
                        [((s.owner_kind, s.owner_id), lookup.title_of(s),
                          first_line(s)) for s in ranked], similar=text):
                    self.hits.append({"similar": text, "hits": []})
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
           passages: dict, budget: Optional[int],
           then: Optional[Callable] = None) -> tuple:
    """(the reply that stands, the requests made): what each reply asks of
    the rest of the plan is fetched and *ask()* sends the next round, a
    message after that reply bringing what is new (owner decisions
    2026-11-07: the rounds are one conversation), until a round asks for
    nothing the conversation has not shown or it no longer fits the model's
    window (`Gathered.unfit`). The reply before such a round stands.
    *then(reply)*, where given, is asked when a round asks for nothing new:
    True when it showed the request something new, which sends it again
    (the combing lists the next passages of its ranking, owner decision
    2026-11-06)."""
    asked = 0
    while (gathered.fetch(reply.get("more"), order, passages, budget)
           or (then is not None and then(reply))):
        again = ask()
        asked += 1
        if not isinstance(again, dict):
            gathered.unfit = True
            break
        reply = again
    return reply, asked


# -- the values of a passage, one per round -------------------------------------

def parameter_shown(parameter, full: bool = True) -> dict:
    """The parameter as a request shows it: with its full definition, or,
    without *full*, with its `brief` where the spec writes one (owner
    decision 2026-11-05, ticket 26)."""
    definition = parameter.description if full \
        else (getattr(parameter, "brief", None) or parameter.description)
    return {"key": parameter.uri, "label": parameter.label,
            "definition": definition}


def value_classes(parameter) -> dict:
    """The entries a category parameter's value is one of, as a request shows
    a closed list (`fields.Slot.answerable`), without UNSTATED: a value the
    passage does not state is no value. Empty for a parameter with no
    list."""
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


def shown_value(claim: dict) -> dict:
    """A value as a request shows it: its value, wording and quote, or for
    one read off a figure the sentence of what was read."""
    return {key: claim[key] for key in ("value", "value_raw", "quote",
                                        "reading")
            if claim.get(key) not in (None, "") or key == "value"}


def values_payload(source: Source, parameter, context: dict,
                   read: list = (), drawn: bool = False) -> dict:
    """The first message of the values of a passage: the parameter in
    short, a category parameter with its entries (`value_classes`), first,
    the same in every conversation of the parameter; then the passage and
    the text around a table or figure (ticket 26: what requests share
    stands first). Nothing of the value's coordinates. The line of the
    title page that names the plan's own place stands before the passage,
    the same in a plan; the title and head of the table the passage may
    continue after it (`beside_of`). The next value, and a value the check
    refused, are asked after the answer in the same conversation (owner
    decisions 2026-11-07); *read*, the values named so far, stands only in
    a conversation begun anew because the old one no longer fit the
    model's window (`Reader._rounds`). With *drawn*, a figure whose image
    goes with the request says so ("image"), and the system prompt tells how
    a number only the image shows is read off it."""
    classes = value_classes(parameter)
    return {"parameter": {**parameter_shown(parameter, full=False),
                          **({"value_classes": classes} if classes
                             else {})},
            **({"title_page": context["title_page"]}
               if context.get("title_page") else {}),
            "source": source_shown(source),
            **({"image": True} if drawn else {}),
            **{key: context[key] for key in ("around", "table_before")
               if context.get(key)},
            **({"read": list(read)} if read else {})}


def values_response_format(parameter, drawn: bool = False) -> dict:
    """The next value of the passage as the reply itself, with no wrapper
    (owner decision 2026-11-06): its value and quote, its printed wording
    only where the value is an entry of a list or a number (a free text value
    is its own wording, `verify.wording_of`); {"value": null} where no
    further value stands in it. A category value is one of its entries, or
    "" where the model is unsure of them. With *drawn*, a figure whose image
    goes with the request: always whether the image only draws the number
    (`drawn`), and in place of a quote the sentence of what was read off the
    image where no shown text states it (`reading`, owner decisions
    2026-11-05 and 2026-11-07)."""
    classes = value_classes(parameter)
    if parameter.is_numeric:
        value = {"type": "number"}
    elif classes:
        value = {"enum": [*classes, ""]}
    else:
        value = {"type": "string"}
    properties = {"value": value}
    if parameter.is_numeric or classes:
        properties["value_raw"] = {"type": "string"}
    properties["quote"] = {"type": "string"}
    required = ["value", "quote"]
    if drawn:
        properties["drawn"] = {"type": "boolean"}
        properties["reading"] = {"type": "string"}
        required = ["value", "drawn"]
    entry = {"type": "object", "properties": properties,
             "required": required, "additionalProperties": False}
    end = {"type": "object", "properties": {"value": {"type": "null"}},
           "required": ["value"], "additionalProperties": False}
    # "value" at the top as well: a reply without it is asked again
    # (`runner._lacking`).
    schema = {"type": "object", "anyOf": [entry, end], "required": ["value"]}
    return {"type": "json_schema",
            "json_schema": {"name": "values_reply", "schema": schema}}


# A number as the example of a value request writes it, with the point the
# prompt asks for.
NUMBER_SAID = 12.5


def values_example(parameter, drawn: bool = False) -> dict:
    """The reply of a value request as its example shows it: a value read,
    with exactly the keys `values_response_format` asks for this parameter
    and this passage, in its order (owner decision 2026-11-06): a printed
    value, so with *drawn* one the image does not only draw. The reply that
    names no further value stays in the prompt's rule line, and one read off
    an image in the part about the image."""
    entry = {"value": NUMBER_SAID if parameter.is_numeric else fields.SAID}
    if parameter.is_numeric or value_classes(parameter):
        entry["value_raw"] = fields.SAID
    entry["quote"] = fields.SAID
    if drawn:
        entry["drawn"] = False
    return entry


def claim_of(reply, drawn: bool = False) -> Optional[dict]:
    """The value a round's reply names, as a row's claim, or None where it
    names none: {"value": null}, or no object. Where the request sent the
    image (*drawn*), whether the image only draws the number, and a reading
    in place of a missing quote, which the switch `read_off` makes the
    value's evidence (`verify.read_off`)."""
    if not isinstance(reply, dict) or reply.get("value") is None:
        return None
    claim = {"source": "Q1", "value": reply.get("value"),
             "quote": reply.get("quote")}
    if reply.get("value_raw"):
        claim["value_raw"] = reply["value_raw"]
    if drawn:
        if isinstance(reply.get("drawn"), bool):
            claim["drawn"] = reply["drawn"]
        reading, quote = reply.get("reading"), reply.get("quote")
        if isinstance(reading, str) and reading.strip() \
                and not (isinstance(quote, str) and quote.strip()):
            claim.pop("quote")
            claim.update(reading=reading.strip(), read_off=True)
    return claim


def _same_text(a, b) -> bool:
    return flat(str(a or "")).casefold() == flat(str(b or "")).casefold()


def same_value(a: dict, b: dict) -> bool:
    """Do two claims name the same value: the same number or wording, in the
    same quote, read off the same way?"""
    left, right = a.get("value"), b.get("value")
    numbers = canonical_number(left), canonical_number(right)
    same = numbers[0] == numbers[1] if None not in numbers \
        else _same_text(left, right)
    return (same and _same_text(a.get("value_raw"), b.get("value_raw"))
            and _same_text(a.get("quote"), b.get("quote"))
            and _same_text(a.get("reading"), b.get("reading")))


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
        return say(NOT_SHOWN)
    if number_outside_quote(claim):
        return say("value_outside_quote", values=json.dumps(
            [{"value": claim.get("value"), "quote": quote}],
            ensure_ascii=False))
    return None


def round_failure(claim: dict, shown: list, read: list,
                  parameter, kind: str = "section") -> Optional[tuple]:
    """(kind, reason) of what the check refuses of a round's value of
    *parameter*, or None: a value already read (`REPEATED`), the value
    itself (`VALUE`: its quote in no passage of *shown*, its number not in
    its quote, what the fold refuses of the value and its quote,
    `verify.value_refused`), or a quote that does not pin the value down
    (`UNIQUE`, owner decision 2026-11-07: it stands in what *shown* holds
    more than once, or holds the value more than once). Of a value read off
    a figure of *kind*, the passage the round reads, only the value itself
    (`verify.read_off`). The fold's refusal is told in its own words: what
    the fold refuses, the model hears while it can still answer (owner
    decision 2026-11-05)."""
    if any(same_value(claim, other) for other in read):
        named = claim.get("value")
        return REPEATED, say("value_already_read",
                             value=json.dumps(named, ensure_ascii=False),
                             quote=claim.get("quote") or claim.get("reading"))
    if read_off(claim, kind):
        refused = value_refused(claim, parameter, "", owner_kind=kind)
        return (VALUE, say("value_rejected", reason=refused)) if refused \
            else None
    passage = passage_of(claim, shown)
    if passage is None:
        return VALUE, say(NOT_SHOWN)
    reason = value_failure(claim, passage)
    if reason:
        return VALUE, reason
    refused = value_refused(claim, parameter, passage.text or "")
    if refused:
        return VALUE, say("value_rejected", reason=refused)
    quote = claim["quote"]
    if times_quoted([source.text for source in shown], quote) > 1:
        return UNIQUE, say("quote_not_unique", quote=quote)
    if times_stated(claim, parameter, quote) > 1:
        return UNIQUE, say("value_not_once", value=json.dumps(
            claim.get("value"), ensure_ascii=False), quote=quote)
    return None


# -- one group's coordinates of one value ---------------------------------------

def text_payload(source: Source, parameter, slots: list, row: Row,
                 where: str, context: dict, full: bool = False) -> dict:
    """One group's request for one value, what its requests share first
    (ticket 26): the parameter, with its full definition only where *full*
    (the group that classifies, `Group.full_definition`), and the group's
    coordinates with the spec's words for where a plan prints them
    (*where*), the same for every value of the parameter; then the line of
    the title page and the plan's settings, the same in a plan; then the
    titles of the sections up to the passage (`sections_of`), the passage,
    the text around a table or figure and the table the passage may continue
    (`group_context`); the value last, with its quote and, under "read",
    what is already read of it in the plan's words. It is the first
    message of the value's conversation: its next coordinate and a
    correction follow the answer (`group_payload`, owner decisions
    2026-11-07)."""
    value = shown_value(row.claim)
    if context.get("read"):
        value["read"] = context["read"]
    payload = {"parameter": parameter_shown(parameter, full=full),
               "coordinates": {slot.name: coordinate_shown(slot)
                               for slot in slots},
               "where": where,
               **({"title_page": context["title_page"]}
                  if context.get("title_page") else {}),
               **({"settings": context["settings"]}
                  if context.get("settings") else {}),
               **({"sections": context["sections"]}
                  if context.get("sections") else {}),
               "source": source_shown(source),
               **{key: context[key] for key in ("around", "table_before")
                  if context.get(key)},
               "value": value}
    return payload


def group_payload(parameter, slots: list, where: str, context: dict,
                  full: bool = False) -> dict:
    """The message that asks the next group of a value in its conversation
    (owner decision 2026-11-07: one conversation per value, each group a
    message of its own): the group's coordinates and the spec's words for
    where a plan prints them, the parameter's full definition where the
    group classifies (*full*) and the conversation has not shown it. The
    passage, the titles of the sections up to it and the value stand in the
    first message; a row the conversation goes on for that its answers do
    not show, a further name a reply gave (`_Job.clone`), is shown again
    with what it has read ("value")."""
    return {**({"parameter": parameter_shown(parameter, full=True)}
               if full else {}),
            "coordinates": {slot.name: coordinate_shown(slot)
                            for slot in slots},
            "where": where,
            **({"value": context["value"]} if "value" in context else {})}


def text_response_format(slots: list) -> dict:
    """Every coordinate of the group for the one value the request shows,
    each with the sentence of one the passage does not state (`probe`)."""
    properties = {slot.name: answer_schema(slot, probe=True)
                  for slot in slots}
    schema = {"type": "object", "properties": properties,
              "required": [slot.name for slot in slots],
              "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "text_reply", "schema": schema}}


def text_example(slots: list) -> dict:
    """The reply of one group's request as its example shows it: exactly
    the coordinates this request asks, in its order, each read
    (`entry_example`). The model writes the keys its example shows: with one
    example per prompt, 183 of 184 heat load requests left out the
    "aggregation" it did not show (owner decision 2026-11-06)."""
    return {slot.name: entry_example(slot) for slot in slots}


def answer_of(entry: dict) -> dict:
    return {key: entry[key] for key in ("value", "value_raw", "quote")
            if key in entry}


def value_replies(reply: dict, slot, label: str,
                  window: tuple = ("own", 1)) -> list:
    """[(level, window, field reply)] of one coordinate of a group's reply
    for the value *label*; *window* is ("near", 1) in a second reading."""
    entry = reply.get(slot.name) if isinstance(reply, dict) else None
    if not isinstance(entry, dict):
        return []
    return [("value", tuple(window), {"answers": {label: answer_of(entry)}})]


def is_open(claim: dict, slot) -> bool:
    """Is a coordinate still open on a value after its reading: said not
    stated, answered without backing, or not answered at all?"""
    return claim.get(f"{slot.name}_state") in (
        None, fields.SAID_UNSTATED, fields.UNBACKED, fields.UNANSWERED)


def refused_of(failed: list) -> collections.Counter:
    """What the check refused of a reply, by reason."""
    return collections.Counter(failure.get("why")
                               for _name, _level, failure in failed)


def unanswered_what(entry, name: str) -> str:
    """What a correction says of the coordinate *name* that a reply about
    one value (*entry*) gave no answer for: that the reply lacked it, or,
    where it stands there in another form than the one asked (a bare word
    where an object with "value" is asked), that the reply did not have the
    form asked for (owner decision 2026-11-06: a correction names the
    fault)."""
    if isinstance(entry, dict) and name in entry:
        return say("wrong_shape")
    return say("key_missing", key=name)


def value_corrections(row: Row, failed: list, slots: list,
                      reply: Optional[dict] = None) -> list:
    """What the check refused of a group's reply for one value, each named
    by its coordinate: [{coordinate, what}]. A coordinate *reply* left out
    is named as missing, one it gave in another form than asked as given in
    the wrong form (`unanswered_what`)."""
    out = []
    for slot in slots:
        if not row.claim.get(f"{slot.name}_state"):
            out.append({"coordinate": slot.name,
                        "what": unanswered_what(reply, slot.name)})
    named = {entry["coordinate"] for entry in out}
    for name, _level, failure in failed:
        if failure.get("row") == row.label and name not in named:
            named.add(name)
            out.append({"coordinate": name, "what": failure.get("reason")})
    return out


def named_corrections(corrections: list, reply: dict, slots: list) -> list:
    """*corrections* for one of several rows a reply made of one value
    (`answers_each`): each correction of a coordinate that named several
    things names the name this row was given, and its quote, so the request
    asks again for that one."""
    by_name = {slot.name: slot for slot in slots}
    out = []
    for entry in corrections:
        name = entry.get("coordinate")
        answer = reply.get(name) if isinstance(reply, dict) else None
        if (name in by_name and several(by_name[name])
                and isinstance(answer, dict)):
            entry = {"coordinate": name,
                     **{key: answer[key] for key in ("value", "quote")
                        if answer.get(key) not in (None, "")},
                     "what": entry.get("what")}
        out.append(entry)
    return out


def told_once(corrections: dict, given: dict, slots: list,
              named: bool) -> list:
    """What ONE message after an answer tells of the rows it made (owner
    decision 2026-11-07: one follow-up per reply): each row's corrections
    (*corrections*, {row label: [{coordinate, what}]}) in the order of the
    rows, with *named* those of a coordinate that named several things
    naming the name and quote that row was given (*given*, {row label: its
    answer}; `named_corrections`), each correction told once."""
    out = []
    for label, told in corrections.items():
        if named:
            told = named_corrections(told, given.get(label), slots)
        for entry in told:
            if entry not in out:
                out.append(entry)
    return out


def routed(answers: list, rows: list, corrections: dict, given: dict,
           slots: list) -> list:
    """[(row or None, answer, {coordinate})]: where each answer of a
    follow-up (`answers_each`) goes, and which of its coordinates (owner
    decisions 2026-11-07). An answer for a coordinate that may name several
    things goes to the row its name was refused on, a changed name to the
    next such row still open (they differ only in the name refused), and a
    name for none of them to a row of its own (None); one that repeats
    another row's answer unchanged corrects nothing. A row corrected on the
    other coordinates takes them from the first answer, which holds them
    for every name. *corrections* is {row label: [{coordinate, ...}]},
    *given* {row label: the answer it got before}."""
    answers = [one for one in answers if isinstance(one, dict)]
    if not answers:
        return []
    names = [slot.name for slot in slots if several(slot)]

    def entry(answer, name):
        one = (answer or {}).get(name)
        return one if isinstance(one, dict) else {}

    def named(answer) -> tuple:
        return tuple(entry(answer, name).get("value") for name in names)

    def quoted(answer) -> tuple:
        return tuple((entry(answer, name).get("value"),
                      entry(answer, name).get("quote")) for name in names)

    def told(row) -> set:
        return {one.get("coordinate")
                for one in corrections.get(row.label) or ()}

    refused = [row for row in rows if told(row) & set(names)]
    out = [(row, answers[0], told(row)) for row in rows
           if row.label in corrections and row not in refused]
    if not names:
        return out
    kept = {quoted(given.get(row.label)) for row in rows
            if row not in refused}
    waiting = list(refused)
    leftover = []
    for answer in answers:
        if quoted(answer) in kept:
            continue
        match = next((row for row in waiting
                      if named(given.get(row.label)) == named(answer)), None)
        if match is None:
            leftover.append(answer)
            continue
        waiting.remove(match)
        out.append((match, answer, told(match)))
    for answer in leftover:
        if waiting:
            row = waiting.pop(0)
            out.append((row, answer, told(row)))
        else:
            out.append((None, answer, {slot.name for slot in slots}))
    # A row whose name came back from no answer still takes the corrections
    # of the other coordinates.
    out.extend((row, answers[0], told(row) - set(names)) for row in waiting
               if told(row) - set(names))
    return out


def cleared(claim: dict, names: list) -> dict:
    """*claim* with the coordinates *names* open again: a row of its own
    for a further name starts from a copy of its value."""
    for name in names:
        for suffix in fields.COORDINATE_KEYS:
            claim.pop(f"{name}{suffix}", None)
    return claim


# -- whether a place speaks about a value ---------------------------------------

def check_response_format() -> dict:
    """What the check of a find answers: whether the place it was quoted
    from speaks about the value, one of `ABOUT`."""
    schema = {"type": "object",
              "properties": {"about": {"enum": list(ABOUT)}},
              "required": ["about"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "comb_check", "schema": schema}}


def check_example() -> dict:
    """The reply of a check as its example shows it."""
    return {"about": ABOUT[0]}


def place_text(text: str, quote: str, budget: Optional[int]) -> str:
    """The text of the place a check shows: whole where it fits *budget*
    characters, else the stretch of *budget* around *quote*, so the quote
    stands in what is shown."""
    text = text or ""
    if not budget or len(text) <= budget:
        return text
    words = [re.escape(word) for word in (quote or "").split()]
    hit = re.search(r"\s+".join(words), text) if words else None
    start = max(0, (hit.start() if hit else 0)
                - max(0, budget - (len(hit.group(0)) if hit else 0)) // 2)
    return text[start:start + budget]


def check_shown(source: Source, parameter) -> dict:
    """The value's passage and parameter as the check shows them."""
    return {"passage": {"kind": source.owner_kind,
                        "title": lookup.title_of(source),
                        "section": (source.provenance or {}).get(
                            "section_title")},
            "parameter": {"key": parameter.uri, "label": parameter.label,
                          "definition": parameter.description}}


class Judge:
    """Whether the place a find was quoted from speaks about its value
    (`CHECK_PROMPT_ID`, owner decisions 2026-11-07), for one value: asked
    where the quote stands in a passage the value's own request did not show
    (*own*: the owners of those it did), never where the check of quote and
    answer refuses the find anyway (`merge_field`). Asked once per
    coordinate and quote, whatever name the find gives: the question is
    about the place (owner decision 2026-11-07); a reply that names neither
    answer is asked once more, told why. *check(payload, shape,
    document_id, source, group, example, thread, follow)* is the request,
    *shown* the value's passage and parameter as it shows them
    (`check_shown`), *counts* what counts its requests (`judged`) and the
    places it said do not speak about the value (`turned`)."""

    def __init__(self, check: Callable, document_id: int, shown: dict,
                 own: set, source: Source, group, passages: dict,
                 budget: Optional[int], counts) -> None:
        self.check = check
        self.document_id = document_id
        self.shown = shown
        self.own = own
        self.source = source
        self.group = group
        self.passages = passages
        self.budget = budget
        self.counts = counts
        self.verdicts: dict = {}

    def __call__(self, slot, one: dict, evidence: list,
                 row: dict) -> Optional[str]:
        """What the check says of the find *one* for *slot*: "yes" or "no"
        where its quote stands first in a passage of *evidence* other than
        the value's own; None where it stands in one of those, where the
        check of its quote and answer would refuse it, or where no reply
        gave one of `ABOUT`. *row* is the value as the check shows it."""
        value, quote = one.get("value"), one.get("quote")
        if not isinstance(quote, str) or len(quote.strip()) < MIN_QUOTE_CHARS:
            return None
        wording = one.get("value_raw")
        wording = wording.strip() if isinstance(wording, str) \
            and wording.strip() else None
        if not answer_in_quote(slot, value, wording, quote):
            return None
        cited = next((s for s in evidence if quote_in(s.text or "", quote)),
                     None)
        if cited is None or (cited.owner_kind, cited.owner_id) in self.own:
            return None
        key = (slot.name, quote)
        if key in self.verdicts:
            return self.verdicts[key]
        place = self.passages.get((cited.owner_kind, cited.owner_id)) \
            or cited
        payload = {**self.shown, "row": row,
                   "coordinate": {slot.name: coordinate_shown(
                       slot, unstated=False)},
                   "answer": {k: one[k] for k in ("value", "value_raw",
                                                  "quote")
                              if one.get(k) not in (None, "")},
                   "place": {"kind": place.owner_kind,
                             "title": lookup.title_of(place),
                             "section": (place.provenance or {}).get(
                                 "section_title"),
                             "text": place_text(place.text, quote,
                                                self.budget)}}
        verdict, follow = None, None
        thread = Thread()
        for _ in range(2):
            reply = self.check(payload, check_response_format(),
                               self.document_id, self.source,
                               group=getattr(self.group, "name", self.group),
                               example=check_example(), thread=thread,
                               follow=follow)
            self.counts.judged += 1
            about = reply.get("about") if isinstance(reply, dict) else None
            if about in ABOUT or not isinstance(reply, dict):
                verdict = about if about in ABOUT else None
                break
            follow = {CORRECTIONS: {"what": {"about": say(
                "verdict_not_an_option", given=about)}}}
        self.verdicts[key] = verdict
        if verdict == ABOUT[1]:
            self.counts.turned += 1
        return verdict


def turned_out(reply, slots: list, judge: Optional[Judge], evidence: list,
               row: dict) -> tuple:
    """(*reply* without each find whose place the check says does not speak
    about the value (`Judge`), {coordinate: [the answers taken out]})."""
    if judge is None or not isinstance(reply, dict):
        return reply, {}
    out, turned = dict(reply), {}
    for slot in slots:
        given = reply.get(slot.name)
        if given is None:
            continue
        kept = []
        for one in (given if isinstance(given, list) else [given]):
            if isinstance(one, dict) \
                    and judge(slot, one, evidence, row) == ABOUT[1]:
                turned.setdefault(slot.name, []).append(one.get("value"))
                continue
            kept.append(one)
        if kept:
            out[slot.name] = kept if isinstance(given, list) else kept[0]
        else:
            out.pop(slot.name)
    return out, turned


# -- one parameter in one passage ----------------------------------------------

def until_of(slot, answer) -> Optional[int]:
    """The last year of the span a number answer states its value for
    ("until", `answer_schema`), None for any other answer."""
    entry = answer.get(slot.name) if isinstance(answer, dict) else None
    until = entry.get("until") if isinstance(entry, dict) else None
    if slot.kind != fields.NUMBER or not isinstance(until, int) \
            or isinstance(until, bool):
        return None
    return until


def span_rows(row: Row, slot, until: Optional[int], marks: dict,
              clone: Callable) -> list:
    """A value the plan states for a span of years as one row per year of
    it (owner decision 2026-11-07: "als ca. für jedes distinkte Jahr
    erfassen"): *row*, read with the span's first year, and a copy of it
    (*clone(row)*) for each year after, the last read as the first is, those
    between derived from the span, which the quote prints and names neither
    of. Each takes *marks* ({coordinate: entry}, the profile's `SPAN_MARKS`)
    where it read nothing, derived from the span. Only where the year read
    holds and the last year stands in its quote as well, as any year must;
    [the copies]."""
    first = row.claim.get(slot.name)
    quote = row.claim.get(f"{slot.name}_quote")
    if (until is None or row.claim.get(f"{slot.name}_state") != READ
            or not isinstance(first, int) or until <= first
            or not isinstance(quote, str)
            or not answer_in_quote(slot, until, None, quote)):
        return []
    wording = row.claim.get(f"{slot.name}_raw") or quote
    made = []
    for year in range(first + 1, until + 1):
        copied = clone(row)
        copied.claim[slot.name] = year
        if year != until:
            copied.claim[f"{slot.name}_state"] = fields.DERIVED
        made.append(copied)
    for one in [row] + made:
        for name, entry in (marks or {}).items():
            if one.claim.get(f"{name}_state") == READ:
                continue
            for suffix in fields.COORDINATE_KEYS:
                one.claim.pop(f"{name}{suffix}", None)
            one.claim[name] = entry
            one.claim[f"{name}_state"] = fields.DERIVED
            one.claim[f"{name}_raw"] = wording
            one.claim[f"{name}_quote"] = quote
    return made


def link_ranges(rows: list, slots: list) -> int:
    """The two ends of each range a passage prints, linked (owner decision
    2026-11-06): a value read as the lower end of a range
    (`fields.RANGE_LOW`) and the next one read as the upper end
    (`fields.RANGE_HIGH`), under the same quote and with the same answer to
    every other coordinate, both carry [lower, upper] under `fields.RANGE`.
    Only a list that has both entries marks ends. Returns how many ranges
    were linked."""
    ends = {fields.RANGE_LOW, fields.RANGE_HIGH}
    marked = next((slot for slot in slots if slot.is_closed
                   and ends <= {option.uri for option in slot.options}),
                  None)
    if marked is None:
        return 0
    others = [slot.name for slot in slots if slot is not marked]

    def key(row: Row) -> tuple:
        return (flat(str(row.claim.get("quote") or "")).casefold(),
                tuple(json.dumps(row.claim.get(name), sort_keys=True,
                                 default=str) for name in others))
    waiting: dict = {}
    linked = 0
    for row in rows:
        if row.claim.get(f"{marked.name}_state") != READ:
            continue
        end = row.claim.get(marked.name)
        if end == fields.RANGE_LOW:
            waiting.setdefault(key(row), []).append(row)
        elif end == fields.RANGE_HIGH and waiting.get(key(row)):
            low = waiting[key(row)].pop(0)
            pair = [low.claim.get("value"), row.claim.get("value")]
            low.claim[fields.RANGE] = list(pair)
            row.claim[fields.RANGE] = list(pair)
            linked += 1
    return linked


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
    # Per claim, in its order: the sentences its replies wrote to the
    # coordinates they found unstated, as the plan would print them,
    # {coordinate: sentence}, which the combing ranks with. Not on the claim:
    # no sentence enters the harvest.
    probes: list = field(default_factory=list)


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
    fixed: list
    merged: Callable
    passages: dict
    result: Read
    # the piece of the passage each value was read in, by its label
    views: dict = field(default_factory=dict)
    # the sentences of each value's unstated coordinates, by its label
    probes: dict = field(default_factory=dict)
    # rows of the passage so far, which the label of the next copy follows
    made: int = 0
    # What a coordinate's quote may stand in beside the passage and its
    # section: the title page's line and the table it may continue
    # (`beside_of`); never a value's.
    extra: list = field(default_factory=list)
    # the plan's passages in its order, and two pages of it in characters
    order: list = field(default_factory=list)
    budget: Optional[int] = None
    # each value's conversation, by its label (owner decision 2026-11-07:
    # one conversation per value), and the rows that went on in a branch of
    # another's, whose messages show them again
    threads: dict = field(default_factory=dict)
    branched: set = field(default_factory=set)
    # the rounds of the piece each value was read in, by its label, which a
    # value read as no value of its parameter is asked again in (`_again`)
    rounds: dict = field(default_factory=dict)
    # the spec's groups of the parameter's coordinates (`groups_of`)
    groups: list = field(default_factory=list)
    # each piece of the passage that a round answered (`_values`)
    read_in: list = field(default_factory=list)
    # What the conversations of the passage's values share while they run
    # side by side (`Reader.__call__`): the counts of the reading and the
    # labels, pieces, sentences and conversations of the copies.
    lock: threading.Lock = field(default_factory=threading.Lock)

    def count(self, asked: int = 0, corrected: int = 0,
              failed: Optional[collections.Counter] = None) -> None:
        """Adds what one value's conversation asked, corrected and refused
        to the reading's counts (`Read`)."""
        with self.lock:
            self.result.asked += asked
            self.result.corrected += corrected
            if failed:
                self.result.failed = dict(
                    collections.Counter(self.result.failed) + failed)

    def clone(self, row: Row) -> Row:
        """A copy of *row* under a label of its own, for one more name of
        a value the reply names several of (`answers_each`): the piece it
        was read in, its sentences and its conversation so far go with it,
        the conversation as a branch of its own."""
        with self.lock:
            label = row_label(self.made)
            self.made += 1
            self.views[label] = self.views.get(row.label, self.shown)
            if row.label in self.probes:
                self.probes[label] = dict(self.probes[row.label])
            if row.label in self.threads:
                self.threads[label] = self.threads[row.label].branch()
                self.branched.add(label)
        return Row(label=label, item_index=row.item_index,
                   claim=copy.deepcopy(row.claim))

    def passages_shown(self) -> list:
        """Every passage a request of this reading shows: the passage, its
        heading and the text around it."""
        return [self.source, *self.fixed]

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


@dataclass
class _Rounds:
    """The rounds of one piece of a passage (`Reader._rounds`): *ask(follow)*
    sends a message of their conversation, *rows* the values they named,
    *read* those values as the requests show them."""
    ask: Callable
    rows: list
    read: list
    view: Source
    drawn: bool


class Reader:
    """(document_id, survey, passages) -> [Read], one per parameter and
    passage the survey named for it.

    Two kinds of request, each with one task and one value (owner
    decisions 2026-11-04 and 2026-11-05), each the reply as a dict, CUT, or
    None, and each a message of a conversation (`thread.Thread`, owner
    decisions 2026-11-07): *ask_values(source, parameter, context, read,
    thread, follow, drawn)* the first value of a passage not among *read*,
    or, with *follow*, what follows the answer of *thread*: the next value,
    a correction; with *drawn* the request sends the figure's image and
    takes a value read off it. *ask_text(source, parameter, group, slots,
    row, context, thread, follow)* one coordinate of that value (*slots*,
    one): the first message of the value's conversation, the message of
    its next coordinate, or, with *follow*, a correction. *context* is what
    the first message shows beside its passage.
    *shown_with(source)* is what a coordinate's quote may stand in besides
    the passage: the heading it stands under (`heading_of`); so may what
    the value has read, as its request shows it (`known_shown`).
    *known(claim, asked)* is what a value has read in the plan's words
    (`runner.row_context`). *drawn(source)* says whether a request about
    *source* sends a figure's image, which a value only the image shows is
    read off (owner decisions 2026-11-05 and 2026-11-07); None sends none.
    *span_marks* are what a value stated for a span of years takes on each of
    its rows (`span_rows`). *pool* reads passages side by side, and the
    values of a passage side by side once its rounds have named them (owner
    decision 2026-11-07). No request of the reading has tools (owner decision
    2026-11-05, ticket 26).
    """

    def __init__(self, spec, ask_values: Callable, ask_text: Callable, *,
                 shown_with: Optional[Callable] = None,
                 bases: Optional[Callable] = None,
                 known: Optional[Callable] = None,
                 drawn: Optional[Callable] = None,
                 span_marks: Optional[dict] = None,
                 pool=None, trace=None):
        self.spec = spec
        self.ask_values = ask_values
        self.ask_text = ask_text
        self.span_marks = dict(span_marks or {})
        self.shown_with = shown_with or (lambda source: [])
        self.bases = bases or (lambda pairs: [])
        self.known = known or (lambda claim, asked: {})
        self.drawn = drawn or (lambda source: False)
        self.pool = pool
        self.trace = trace

    def __call__(self, document_id: int, found, passages: dict,
                 budget: Optional[int] = None, *,
                 bases: Optional[list] = None,
                 title_page: Optional[Source] = None,
                 settings: Optional[list] = None,
                 on_read: Optional[Callable] = None) -> list:
        """One Read per parameter and passage the survey named for it. A
        section or figure longer than *budget* characters, two pages of the
        plan, is read in pieces of that size (`survey.pieces`). *bases* are
        the plan's base and target years as one request per plan read them
        (`years.PlanYears`), else those of the survey's pairs; *title_page*
        the line of its title page that names its own place, which every
        request shows (owner decisions 2026-11-06); *settings* what the plan
        settles for all its values (`settings.PlanSettings`), which every
        request about a value's coordinates shows and may quote (owner
        decision 2026-11-07). *on_read(read)* takes each Read the moment it
        is done, on the calling thread (`combing.Session.add`). The Reads
        come back in the order of the parameters and their passages."""
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

        def start(job):
            parameter, source, shown = job
            return self._start(document_id, parameter, source, pairs,
                               passages, shown=shown, budget=budget,
                               bases=bases, title_page=title_page,
                               settings=settings)
        if self.pool is not None:
            return self._side_by_side(jobs, start, on_read)
        reads = []
        for one in jobs:
            job, rows = start(one)
            got = job.result if rows is None else self._finish(
                job, rows, [self._coordinates(job, row) for row in rows])
            if on_read is not None:
                on_read(got)
            reads.append(got)
        return reads

    def _side_by_side(self, jobs: list, start: Callable,
                      on_read: Optional[Callable]) -> list:
        """The Reads of *jobs* on the pool, in their order: the rounds of
        each passage (`_start`), then the conversation of each value they
        named (`_coordinates`), then what ends the passage (`_finish`), each
        a task of its own that waits for no other. Only the calling thread
        waits, and hands in a passage's next tasks when its last ones are
        done; a task that fails takes back every task not yet begun, as a
        pool's map does."""
        reads: list = [None] * len(jobs)
        open_values: dict = {}
        pending: dict = {}

        def submit(step, index, task, *args) -> None:
            pending[self.pool.submit(task, *args)] = (step, index)
        for index, one in enumerate(jobs):
            submit("rounds", index, start, one)
        try:
            while pending:
                done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                for future in done:
                    step, index = pending.pop(future)
                    got = future.result()
                    if step == "rounds":
                        job, rows = got
                        if rows:
                            open_values[index] = (job, rows,
                                                  [None] * len(rows),
                                                  [len(rows)])
                            for at, row in enumerate(rows):
                                submit(("value", at), index,
                                       self._coordinates, job, row)
                            continue
                        if rows is not None:
                            submit("finish", index, self._finish, job,
                                   rows, [])
                            continue
                        got = job.result
                    elif step != "finish":
                        job, rows, eaches, left = open_values[index]
                        eaches[step[1]] = got
                        left[0] -= 1
                        if left[0]:
                            continue
                        del open_values[index]
                        submit("finish", index, self._finish, job, rows,
                               eaches)
                        continue
                    reads[index] = got
                    if on_read is not None:
                        on_read(got)
        except BaseException:
            for future in pending:
                future.cancel()
            raise
        return reads

    def context_of(self, source: Source, passages: dict,
                   budget: Optional[int] = None,
                   title_page: Optional[Source] = None) -> tuple:
        """(what the requests of a passage show beside it, the section it
        was cut from, the passages a coordinate may quote for what stands
        beside it): the text around a table or figure (`around_of`), the
        titles of the sections up to it (`sections_of`), the title page's
        line and the table the passage may continue (`beside_of`)."""
        around = around_of(source, passages, budget)
        context = {"around": around.text} if around is not None else {}
        titles, titled = sections_of(source, passages)
        if titles:
            context["sections"] = titles
        beside, pieces = beside_of(source, title_page)
        context.update(beside)
        return context, around, list(pieces) + titled

    def read(self, document_id: int, parameter, source: Source,
             pairs: list, passages: dict,
             shown: Optional[Source] = None,
             budget: Optional[int] = None, *,
             bases: Optional[list] = None,
             title_page: Optional[Source] = None,
             settings: Optional[list] = None) -> Read:
        """*source* is the passage a value is verified against, *shown* the
        piece of it the requests show, *budget* two pages of the plan, which
        the text around a table or figure fits (`around_of`). The values in
        rounds (`_values`), then each coordinate of the spec for each value,
        one message each in the order of the groups (`_value_group`); what
        that leaves open is asked in a conversation of its own
        (`combing.Comber`). *bases* are the plan's years (else those of
        *pairs*), *title_page* its title page's line (`Reader.__call__`).
        The values one after another: the steps `Reader.__call__` runs side
        by side with a pool."""
        job, rows = self._start(document_id, parameter, source,
                                pairs, passages, shown, budget, bases=bases,
                                title_page=title_page, settings=settings)
        if rows is None:
            return job.result
        return self._finish(job, rows,
                            [self._coordinates(job, row) for row in rows])

    def _start(self, document_id: int, parameter, source: Source,
               pairs: list, passages: dict,
               shown: Optional[Source] = None,
               budget: Optional[int] = None, *,
               bases: Optional[list] = None,
               title_page: Optional[Source] = None,
               settings: Optional[list] = None) -> tuple:
        """(the passage's job, the rows its rounds named): the values of the
        passage in rounds (`_values`). The rows are None where no round came
        to anything; the job's Read is then final (`Read.unread`)."""
        shown = shown or source
        slots = slots_of(self.spec, parameter)
        # The reading's spec rides on the batch, so the fold checks a value
        # against the lists this document closes (`runner.spec_of`).
        batch = Batch(document_id, parameter,
                      [WorkItem(document_id, parameter, source)],
                      spec=self.spec)
        bases = list(bases) if bases is not None else self.bases(pairs)
        context, around, beside = self.context_of(source, passages, budget,
                                                  title_page)
        if settings:
            # What the plan settles for all its values, shown with each
            # value's coordinates, and quotable there.
            context["settings"] = settings_shown(settings)
            beside = list(beside) + settings_evidence(settings, passages)
        result = Read(batch, [])
        # What a coordinate's quote may stand in besides what a request
        # shows of the passage: its heading and the text around it.
        fixed = list(self.shown_with(source)) + (
            [around] if around is not None else [])

        def merged(rows: list, replies: dict, evidence: list) -> list:
            """Every coordinate's answers onto *rows*; [(coordinate, level,
            failure)] of what the check refused. A year is read where its
            number stands in its quote: the plan's base and target years
            are asked of a value only once nothing found its year
            (`combing`, owner decision 2026-11-07)."""
            failed = []
            for slot in slots:
                for level, window, field_reply in replies.get(slot.name, ()):
                    got = merge_field(rows, evidence, slot, field_reply,
                                      window=window, not_shown=NOT_SHOWN)
                    failed.extend((slot.name, level, failure)
                                  for failure in got["failed"])
            return failed

        job = _Job(document_id, parameter, source, shown, slots, context,
                   bases, fixed, merged, passages, result,
                   extra=list(beside), order=list(passages.values()),
                   budget=budget, groups=groups_of(self.spec, slots))
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
            return job, None
        job.made = len(rows)
        job.read_in = list(views)
        return job, rows

    def _finish(self, job: _Job, rows: list, eaches: list) -> Read:
        """The Read of *job* once every value its rounds named (*rows*) has
        been asked its coordinates (*eaches*, per row the rows its
        conversation came to): a value read as no value of its parameter is
        asked for once more, in the order of the values (`_again`, owner
        decision 2026-11-07), then the ranges, and what no reply answered.
        What the spec derives from the unit waits for the combing: it is
        taken only where no request read the coordinate (owner decision
        2026-11-07, `fields.apply_derived`)."""
        slots = job.slots
        before = [slot for group, group_slots in job.groups
                  for slot in in_group_order(group, group_slots)]
        grouped: list = []
        for each in eaches:
            for one in list(each):
                if fields.closed(before, one.claim):
                    for named in self._again(job, one, before):
                        each = each + self._coordinates(job, named)
            grouped.extend(each)
        rows = grouped
        link_ranges(rows, slots)
        result = job.result
        result.unanswered = mark_unanswered(rows, slots)
        result.claims = [row.claim for row in rows]
        result.probes = [job.probes.get(row.label, {}) for row in rows]
        if self.trace is not None:
            self.trace("read", job.document_id,
                       parameter=job.parameter.uri,
                       kind=job.source.owner_kind, owner=job.source.owner_id,
                       values=len(rows), asked=result.asked,
                       corrected=result.corrected, failed=result.failed,
                       unanswered=result.unanswered)
        return result

    @staticmethod
    def _probed(job: _Job, row: Row, reply: dict, asked: list) -> None:
        """The sentences *reply* wrote to coordinates of *row*'s value as
        the plan would print them (`probe`, owner decision 2026-11-05:
        HyDE), kept for the combing; a later reply's sentence replaces an
        earlier one."""
        for slot in asked:
            entry = reply.get(slot.name)
            probe = entry.get("probe") if isinstance(entry, dict) else None
            if isinstance(probe, str) and probe.strip():
                with job.lock:
                    job.probes.setdefault(row.label, {})[slot.name] = \
                        probe.strip()

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

    def _coordinates(self, job: _Job, row: Row) -> list:
        """[*row* and the rows made beside it], each coordinate asked in
        one message, in the order of the groups and of each group's
        coordinates (owner decision 2026-11-07), a coordinate the spec could
        derive from the unit too (owner decision 2026-11-07: asked, derived
        only where no answer is read). A value stated for several names of a
        coordinate that may name several is one row per name, and each asks
        the coordinates after it alone; so is each year of a span. A
        coordinate with an entry
        a value must have (`fields.kept`) that reads a row as no value of
        its parameter closes the coordinates after it, which are never
        asked (`out_of_slice`); the value is asked for once more when every
        value of the passage is done (`_finish`)."""
        each = [row]
        before: list = []
        for group, group_slots in job.groups:
            for slot in in_group_order(group, group_slots):
                for one in list(each):
                    if fields.closed(before, one.claim):
                        one.claim.setdefault(f"{slot.name}_state",
                                             fields.OUT_OF_SLICE)
                        continue
                    each += self._value_group(job, one, group, [slot])
                before.append(slot)
        return each

    def _again(self, job: _Job, row: Row, slots: list) -> list:
        """The value of *row*, read as no value of its parameter by a
        coordinate of *slots* (`fields.kept`), asked for once more in the
        conversation of the rounds it was read in: told that it was read
        wrongly and why, the model names a value of the passage it has not
        named yet that is one, or none (owner decision 2026-11-07). [The row
        of the value named instead], checked as a round's value is; one the
        check refuses is not asked again."""
        rounds = job.rounds.get(row.label)
        if rounds is None:
            return []
        slot = next(one for one in slots
                    if fields.kept(one, row.claim) is False)
        reply = rounds.ask({WRONG: {**shown_value(row.claim), "what": say(
            "value_not_kept", given=row.claim.get(slot.name))}})
        job.count(asked=1, corrected=1)
        claim = claim_of(reply, rounds.drawn) if isinstance(reply, dict) \
            else None
        if claim is None:
            return []
        shown = job.passages_shown()
        if round_failure(claim, shown, [one.claim for one in rounds.rows],
                         job.parameter, rounds.view.owner_kind) is not None:
            return []
        passage = passage_of(claim, shown) if claim.get("quote") \
            else (rounds.view if read_off(claim, rounds.view.owner_kind)
                  else None)
        if passage is not None:
            claim["source"] = job.label_of(passage)
        named = Row(label=row_label(job.made), item_index=0, claim=claim)
        job.made += 1
        job.views[named.label] = rounds.view
        job.rounds[named.label] = rounds
        rounds.rows.append(named)
        rounds.read.append(shown_value(claim))
        return [named]

    def _rounds(self, job: _Job, view: Source, start: int = 0):
        """The values of one piece, one per round, until the model names no
        further value; CUT or None where its first round came to nothing.
        The rounds are one conversation (owner decisions 2026-11-07): the
        first message shows the piece, each later one asks for the next
        value after the answer it follows. A value the check refuses is
        asked once more with the reason, after that answer; one named again
        is asked once more, and named again it ends the rounds (owner
        decision 2026-11-05). A conversation that no longer fits the model's
        window begins anew, showing the values named so far."""
        result = job.result
        drawn = bool(self.drawn(view))
        shows = {key: job.context[key] for key in ("around",) + BESIDE
                 if job.context.get(key)}
        shown = job.passages_shown()
        rows: list = []
        read: list = []
        threads = [Thread()]

        def ask(follow: Optional[dict] = None):
            return self.ask_values(view, job.parameter, dict(shows),
                                   list(read), threads[-1], follow,
                                   drawn=drawn)
        rounds = _Rounds(ask, rows, read, view, drawn)
        first = True
        while True:
            reply = ask({NEXT: None} if threads[-1].begun else None)
            result.asked += 1
            if reply == CUT and threads[-1].begun:
                # The conversation outgrew the window: anew, showing the
                # values named so far.
                threads.append(Thread())
                reply = ask()
                result.asked += 1
            if not isinstance(reply, dict):
                if first:
                    return CUT if reply == CUT else None
                break
            first = False
            claim = claim_of(reply, drawn)
            if claim is None:
                break
            failure = round_failure(claim, shown, [r.claim for r in rows],
                                    job.parameter, view.owner_kind)
            if failure is not None:
                kind, reason = failure
                result.failed = dict(collections.Counter(result.failed)
                                     + collections.Counter({kind: 1}))
                result.corrected += 1
                again = ask({CORRECTIONS: [{**shown_value(claim),
                                            "what": reason}]})
                result.asked += 1
                claim = claim_of(again, drawn)
                if claim is None:
                    break
                failure = round_failure(claim, shown,
                                        [r.claim for r in rows],
                                        job.parameter, view.owner_kind)
                if failure is not None and failure[0] == REPEATED:
                    break
            passage = passage_of(claim, shown) if claim.get("quote") \
                else (view if read_off(claim, view.owner_kind) else None)
            if passage is not None:
                claim["source"] = job.label_of(passage)
            rows.append(Row(label=row_label(start + len(rows)), item_index=0,
                            claim=claim))
            job.rounds[rows[-1].label] = rounds
            read.append(shown_value(claim))
        return rows

    def _value_group(self, job: _Job, row: Row, group,
                     group_slots: list) -> list:
        """One coordinate of one value (*group_slots*, of *group*), where it
        is still open, in a message of the value's conversation (owner
        decisions 2026-11-07): its first message, or the next after the
        answers before; what the check refuses asked once more after that
        answer, by its coordinate. A reply that names several things for a
        coordinate that may name several makes one row per name
        (`answers_each`), each checked and asked once more on its own: [the
        rows made beside *row*]."""
        asked = [slot for slot in group_slots
                 if row.claim.get(f"{slot.name}_state") != READ]
        if not asked:
            return []
        view = job.views.get(row.label, job.shown)
        base = group_context(job.context)
        read = self.known(row.claim, [slot.name for slot in asked])
        window = ("own", 1)
        context = {**base, **({"read": read} if read else {})}
        if row.label in job.branched:
            # A further name of a value its conversation's answers do not
            # show alone: shown again with what it has read.
            context["value"] = {**shown_value(row.claim),
                                **({"read": read} if read else {})}
        with job.lock:
            job.threads.setdefault(row.label, Thread())

        def ask(one: Row, follow: Optional[dict] = None):
            return spread(self.ask_text(view, job.parameter, group, asked,
                                        one, context, job.threads[one.label],
                                        follow), asked)
        reply = ask(row)
        job.count(asked=1)
        if not isinstance(reply, dict):
            return []
        # What the value has read is shown too, and may be quoted (owner
        # decision 2026-11-05), and so is what stands beside the passage.
        evidence = ([view] + job.fixed + job.extra
                    + known_shown(row.claim, read, job.passages))
        return self._settled(job, row, reply, asked, ask, evidence,
                             window=window)

    def _settled(self, job: _Job, row: Row, reply: dict, asked: list,
                 ask: Callable, evidence: list, window: tuple = ("own", 1),
                 judge: Optional[Callable] = None,
                 turned: Optional[dict] = None) -> list:
        """*reply*, the answer to a message of *row*'s conversation, onto
        the rows it makes: one per name of a coordinate that may name
        several things (`answers_each`), each checked on its own. What the
        check refuses on any of them is asked once more in ONE message after
        that answer (owner decision 2026-11-07: one follow-up per reply),
        where the answer made several rows naming the name and quote each
        was given (`told_once`); each answer of it goes to the row of its
        name, a changed name to the next row still open, a further name to
        a row of its own (`routed`). A coordinate whose find the check took
        out (*turned*, `_judge`) is not asked again: it goes to the combing.
        *window* is where the answer was read: the value's own request, or
        ("near", 1) for the second reading. *ask(row, follow)* sends a
        message in *row*'s conversation. [The rows made beside *row*]."""
        turned = turned or {}
        replies = answers_each(reply, asked)
        rows = [row] + [job.clone(row) for _ in replies[1:]]
        corrections: dict = {}
        spans: list = []
        for one, answer in zip(rows, replies):
            self._probed(job, one, answer, asked)
            failed = job.merged([one], {slot.name: value_replies(
                answer, slot, one.label, window) for slot in asked}, evidence)
            job.count(failed=refused_of(failed))
            for slot in asked:
                spans += span_rows(one, slot, until_of(slot, answer),
                                   self.span_marks, job.clone)
            told = [entry for entry in value_corrections(one, failed, asked,
                                                         answer)
                    if entry["coordinate"] not in turned
                    or one.claim.get(f"{entry['coordinate']}_state")]
            if told:
                corrections[one.label] = told
        if not corrections:
            return rows[1:] + spans
        given = {one.label: answer for one, answer in zip(rows, replies)}
        told = told_once(corrections, given, asked, named=len(rows) > 1)
        job.count(asked=1, corrected=len(told))
        again = ask(row, {CORRECTIONS: told})
        if not isinstance(again, dict):
            return rows[1:] + spans
        if judge is not None:
            again, _ = judge(again)
        made = []
        names = [slot.name for slot in asked if several(slot)]
        for target, answer, coordinates in routed(
                answers_each(again, asked), rows, corrections, given, asked):
            if target is None:
                # A further name: a row of its own, a copy of the value.
                target = job.clone(row)
                cleared(target.claim, names)
                made.append(target)
            self._probed(job, target, answer, asked)
            job.merged([target], {slot.name: value_replies(
                answer, slot, target.label, window) for slot in asked
                if slot.name in coordinates}, evidence)
            for slot in asked:
                if slot.name in coordinates:
                    made += span_rows(target, slot, until_of(slot, answer),
                                      self.span_marks, job.clone)
        return rows[1:] + spans + made
