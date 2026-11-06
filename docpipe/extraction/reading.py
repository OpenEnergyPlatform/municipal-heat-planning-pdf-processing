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

A round shows the parameter in short (its `brief`), the whole passage (a table
with its title, its head and all its rows, or the survey's piece of a
section), the text around a table or figure and the values already read, and
asks for the next value not yet read, until the model says there is none. A
value may stand in any passage the round showed: the passage, its heading or
the text around it; it is read from the one its quote stands in, which joins
the reading's batch, so the fold checks it there (`pipeline.route_claims`).
The requests that read have no tools; only the combing has (owner decision
2026-11-05, ticket 26: no reading of 2,231 in an eight-plan probe used them). A value the check refuses (its quote in no passage
shown, its number not in its quote, whatever else the fold refuses of the
value and its quote, such as an answer its quote does not hold or one off
its closed list (`verify.value_refused`), a quote over several table rows
that print it, a head no head line prints) is asked once more with the
reason; one named again is asked once more, and named again it ends the
rounds.

A number in a table takes its column from its head, else from the one cell of
its row that prints it, and a head that prints exactly one year of the
document's pairs is its year, read off the head line and not asked
(`pipeline.with_head`, owner decision 2026-11-03); where exactly one pair has
that year, the pair's scenario is the value's too (`pipeline.head_pair`).
Then every group of the spec (`Spec.groups`, `groups_of`) is asked for this
one value, its coordinates still open only. A request begins with what is the
same for every request of its parameter and group (the parameter, in full
only where the group classifies, its questions with their lists), then what
is the same in a plan (its base and target years), then the passage, and the
value comes last, marked, with what is already read of it, so a server reads
each shared beginning once (owner decision 2026-11-05, ticket 26). Each group
has its own system prompt, its section of the prompt (`group_prompts`), and
its own correction round, and only a group that asks a frame coordinate is
shown the pairs and the plan's base and target years.

Every coordinate asked is answered: the grammar of a group request requires
each of them, and "the passage does not say" is one of the answers
(`fields.UNSTATED`).

A coordinate whose answer is the name the document gives a thing, such as
a scenario, is read as the document prints it (`fields.Slot.merged`). A
value the passage states for several of them is one row per name, each
checked on its own (`answers_each`, owner decision 2026-11-06); a
correction for one of them names its name. Which names mean the same thing
is asked once the document is read (`naming.py`).

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
import copy
import json
import re
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
                     quote_in, value_refused)
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

# What a reading request tells of a quote that stands in nothing it showed,
# in the names of what it shows: "source", the heading of its section,
# "around" (owner decision 2026-11-06).
NOT_SHOWN = "quote_not_in_passage"

# A group's section of a prompt the groups share opens with this line; what
# stands before the first section is every group's (`group_prompts`).
GROUP_SECTION = re.compile(r"^<!-- group: ([A-Za-z_]+) -->[ \t]*$",
                           re.MULTILINE)

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


def coordinate_shown(slot, unstated: bool = True) -> dict:
    """A coordinate as a request shows it: its question, and its list, or
    the kind of its answer; without *unstated* a list without UNSTATED, as
    the combing asks (`fields.value_schema`)."""
    shown: dict = {"question": slot.question}
    if slot.is_closed:
        shown["options"] = {label: entry
                            for label, entry in slot.answerable().items()
                            if unstated or label != fields.UNSTATED}
    else:
        shown["kind"] = slot.kind
    return shown


def several(slot) -> bool:
    """May one value name several things for *slot*, one row each: a
    coordinate whose answer is the name the document gives a thing, merged
    with the document's other names for it after the reading (`naming.py`,
    owner decisions 2026-11-06)?"""
    return bool(getattr(slot, "merged", None))


def answer_schema(slot, probe: bool = False, unstated: bool = True) -> dict:
    """One coordinate's answer as the grammar takes it, its printed wording
    only where `fields.wording_asked`; with *probe* also the sentence a reply
    writes to a coordinate its passage does not state, as the plan would
    print it, which the combing searches with (owner decision 2026-11-05:
    HyDE). A coordinate that may name several things (`several`) takes a
    list of such answers too. Without *unstated* its answer is never
    UNSTATED (`fields.value_schema`)."""
    properties = {"value": fields.value_schema(slot, unstated)}
    if fields.wording_asked(slot):
        properties["value_raw"] = {"type": "string"}
    properties["quote"] = {"type": "string"}
    if probe:
        properties["probe"] = {"type": "string"}
    one = {"type": "object", "properties": properties,
           "required": ["value"], "additionalProperties": False}
    if several(slot):
        return {"anyOf": [one, {"type": "array", "items": one,
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


def answers_each(reply, slots: list) -> list:
    """The reply for one value as one reply per row (owner decision
    2026-11-06): a coordinate that may name several things (`several`) and
    names a list of them gives one reply per name, with every other
    coordinate's answer the same on each; an empty list is no answer. Any
    other reply is the one reply."""
    if not isinstance(reply, dict):
        return [reply]
    out = [reply]
    for slot in slots:
        given = reply.get(slot.name)
        if not several(slot) or not isinstance(given, list):
            continue
        each = [one for one in given if isinstance(one, dict)] or [None]
        out = [{**one, slot.name: answer} for one in out for answer in each]
    return out


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


def more_schema() -> dict:
    """The asks a reply may carry under "more"."""
    return {"type": "array", "items": {
        "type": "object",
        "properties": {"get": {"enum": list(GETS)},
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
        """What the request shows of the gathering so far, as it stands
        now: a later round adds to the gathering, not to a request sent.
        Each hit list without what it was searched with (`SEARCHED_WITH`)."""
        out = {}
        if self.shown:
            out["more"] = list(self.shown)
        if self.hits:
            out["hits"] = [{key: value for key, value in listed.items()
                            if key not in SEARCHED_WITH}
                           for listed in self.hits]
        if self.missed:
            out["not_found"] = list(self.missed)
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
    the rest of the plan is fetched and the request sent again, until a round
    asks for nothing the request has not shown or the request no longer fits
    the model's window (`Gathered.unfit`). The reply before such a round
    stands. *then(reply)*, where given, is asked when a round asks for
    nothing new: True when it showed the request something new, which sends
    it again (the combing lists the next passages of its ranking, owner
    decision 2026-11-06)."""
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
    """One round of the values of a passage: the parameter in short, a
    category parameter with its entries (`value_classes`), first, the same
    in every round of the parameter; then the passage and the text around a
    table or figure, the same in every round of the passage; the values
    already read (*read*) last; with *corrections* the value of the round
    the check refused, asked once more (ticket 26: what requests share
    stands first). Nothing of the value's coordinates."""
    classes = value_classes(parameter)
    payload = {"parameter": {**parameter_shown(parameter, full=False),
                             **({"value_classes": classes} if classes
                                else {})},
               "source": source_shown(source),
               **({"around": context["around"]} if context.get("around")
                  else {}),
               "read": list(read)}
    if corrections:
        payload["corrections"] = corrections
    return payload


def values_response_format(parameter, head: bool = False) -> dict:
    """The next value of the passage as the reply itself, with no wrapper
    (owner decision 2026-11-06): its value and quote, its printed wording
    only where the value is an entry of a list or a number (a free text value
    is its own wording, `verify.wording_of`), and with *head* the head of its
    column; {"value": null} where no further value stands in it. A category
    value is one of its entries, or "" where the model is unsure of them."""
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
    if head:
        properties["head"] = {"type": "string"}
    entry = {"type": "object", "properties": properties,
             "required": ["value", "quote"], "additionalProperties": False}
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


def values_example(parameter, head: bool = False) -> dict:
    """The reply of a value request as its example shows it: a value read,
    with exactly the keys `values_response_format` asks for this parameter
    and this passage, in its order (owner decision 2026-11-06). The reply
    that names no further value stays in the prompt's rule line."""
    entry = {"value": NUMBER_SAID if parameter.is_numeric else fields.SAID}
    if parameter.is_numeric or value_classes(parameter):
        entry["value_raw"] = fields.SAID
    entry["quote"] = fields.SAID
    if head:
        entry["head"] = fields.SAID
    return entry


def claim_of(reply, head: bool = False) -> Optional[dict]:
    """The value a round's reply names, as a row's claim, or None where it
    names none: {"value": null}, or no object. A table row quoted with
    others is cut to the one row that prints the number (`narrow_quote`)."""
    if not isinstance(reply, dict) or reply.get("value") is None:
        return None
    claim = {"source": "Q1", "value": reply.get("value"),
             "quote": reply.get("quote")}
    if reply.get("value_raw"):
        claim["value_raw"] = reply["value_raw"]
    if head and isinstance(reply.get("head"), str) and reply["head"].strip():
        claim["head"] = reply["head"].strip()
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
        return say(NOT_SHOWN)
    if number_outside_quote(claim):
        return say("value_outside_quote", values=json.dumps(
            [{"value": claim.get("value"), "quote": quote}],
            ensure_ascii=False))
    return None


def round_failure(claim: dict, shown: list, read: list,
                  parameter) -> Optional[tuple]:
    """(kind, reason) of what the check refuses of a round's value of
    *parameter*, or None: a value already read (`REPEATED`), the value
    itself (`VALUE`: its quote in no passage of *shown*, its number not in
    its quote, what the fold refuses of the value and its quote
    (`verify.value_refused`), a number quoted over several rows of its
    table that print it), or a head no head line of its table prints
    (`HEAD`). The fold's refusal is told in its own words: what the fold
    refuses, the model hears while it can still answer (owner decision
    2026-11-05)."""
    if any(same_value(claim, other) for other in read):
        named = claim.get("value")
        return REPEATED, say("value_already_read",
                             value=json.dumps(named, ensure_ascii=False),
                             quote=claim.get("quote"))
    passage = passage_of(claim, shown)
    if passage is None:
        return VALUE, say(NOT_SHOWN)
    reason = value_failure(claim, passage)
    if reason:
        return VALUE, reason
    refused = value_refused(claim, parameter, passage.text or "")
    if refused:
        return VALUE, say("value_rejected", reason=refused)
    table = bool(parameter.is_numeric) and passage.owner_kind == "table"
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
                 corrections: Optional[list] = None,
                 full: bool = False) -> dict:
    """One group's request for one value, what its requests share first
    (ticket 26): the parameter, with its full definition only where *full*
    (the group that classifies, `Group.full_definition`), and the group's
    coordinates with the spec's words for where a plan prints them
    (*where*), the same for every value of the parameter; then, for a frame
    group, the plan's base and target years, the same in a plan; then the
    passage, the text around a table or figure and, for a frame group, the
    survey's pairs of the passage (`group_context`); the value last, with
    its quote and, under "read", what is already read of it in the plan's
    words; with *corrections* the same request asked once more."""
    value = shown_value(row.claim)
    if context.get("read"):
        value["read"] = context["read"]
    payload = {"parameter": parameter_shown(parameter, full=full),
               "coordinates": {slot.name: coordinate_shown(slot)
                               for slot in slots},
               "where": where,
               **{key: context[key] for key in ("base_years", "target_years")
                  if key in context},
               "source": source_shown(source),
               **({"around": context["around"]} if context.get("around")
                  else {}),
               **({"known": context["known"]} if "known" in context
                  else {}),
               "value": value}
    if corrections:
        payload["corrections"] = corrections
    return payload


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


def group_prompts(prompt, groups) -> dict:
    """{group name: the prompt its requests send}: what stands before the
    first section (`GROUP_SECTION`) is every group's, then the group's own
    section (owner decision 2026-11-05, ticket 26: one system prompt per kind
    of request, with only its rules). A prompt without sections is every
    group's as it is, the one prompt of a profile with one group. A prompt
    with sections has one for each of *groups* and none for any other group:
    a group without its rules, or rules no group reads, raises LookupError,
    which the run raises at its start (`runner.surveyed_flow`)."""
    marks = list(GROUP_SECTION.finditer(prompt.text))
    names = [group.name if hasattr(group, "name") else group
             for group in groups]
    if not marks:
        return {name: prompt for name in names}
    common = prompt.text[:marks[0].start()]
    sections: dict = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) \
            else len(prompt.text)
        if mark.group(1) in sections:
            raise LookupError(f"{prompt.id}: two sections for group "
                              f"{mark.group(1)!r}")
        sections[mark.group(1)] = prompt.text[mark.end():end]
    missing = [name for name in names if name not in sections]
    extra = sorted(set(sections) - set(names))
    if missing or extra:
        raise LookupError(
            f"{prompt.id}: the spec's groups and the prompt's sections "
            f"differ: no section for {missing}, a section for no group "
            f"{extra}")
    return {name: replace(prompt, text=(common.rstrip() + "\n\n"
                                        + sections[name].strip() + "\n"))
            for name in names}


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
    # Per claim, in its order: the sentences its group replies wrote to the
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
    frames: list
    merged: Callable
    passages: dict
    result: Read
    pairs: list = field(default_factory=list)
    # the piece of the passage each value was read in, by its label
    views: dict = field(default_factory=dict)
    # the sentences of each value's unstated coordinates, by its label
    probes: dict = field(default_factory=dict)
    # rows of the passage so far, which the label of the next copy follows
    made: int = 0

    def clone(self, row: Row) -> Row:
        """A copy of *row* under a label of its own, for one more name of
        a value the reply names several of (`answers_each`): the piece it
        was read in and its sentences go with it."""
        label = row_label(self.made)
        self.made += 1
        self.views[label] = self.views.get(row.label, self.shown)
        if row.label in self.probes:
            self.probes[label] = dict(self.probes[row.label])
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
    the passage: the heading it stands under (`heading_of`); so may what
    the value has read, as its request shows it (`known_shown`).
    *known(claim, asked)* is what a value has read in the plan's words
    (`runner.row_context`). *pool* reads passages side by side. No request
    of the reading has tools (owner decision 2026-11-05, ticket 26).
    """

    def __init__(self, spec, ask_values: Callable, ask_text: Callable,
                 frame_slots: list, *, shown_with: Optional[Callable] = None,
                 bases: Optional[Callable] = None,
                 known: Optional[Callable] = None,
                 pool=None, trace=None):
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
        section or figure longer than *budget* characters, two pages of the
        plan, is read in pieces of that size (`survey.pieces`)."""
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

    def context_of(self, source: Source, tuples: list, passages: dict,
                   budget: Optional[int] = None) -> tuple:
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
             budget: Optional[int] = None) -> Read:
        """*source* is the passage a value is verified against, *shown* the
        piece of it the requests show, *budget* two pages of the plan, which
        the text around a table or figure fits (`around_of`). The values in
        rounds (`_values`), each placed in its table (`_placed`), then each
        group of the spec for each value (`_value_group`)."""
        shown = shown or source
        slots = slots_of(self.spec, parameter)
        # The reading's spec rides on the batch, so the fold checks a value
        # against the lists this document closes (`runner.spec_of`).
        batch = Batch(document_id, parameter,
                      [WorkItem(document_id, parameter, source)],
                      spec=self.spec)
        bases = self.bases(pairs)
        context, around = self.context_of(source, tuples, passages, budget)
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
                                      window=window, bases=bases,
                                      not_shown=NOT_SHOWN)
                    failed.extend((slot.name, level, failure)
                                  for failure in got["failed"])
            return failed

        job = _Job(document_id, parameter, source, shown, slots, context,
                   bases, fixed, frames, merged, passages, result,
                   pairs=list(pairs))
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
        job.made = len(rows)
        groups = groups_of(self.spec, slots)
        grouped: list = []
        for row in rows:
            # A value stated for several names of a coordinate that may name
            # several is one row per name, and each asks the groups after it
            # alone.
            each = [row]
            for group, group_slots in groups:
                each += [made for one in list(each)
                         for made in self._value_group(job, one, group,
                                                       group_slots)]
            grouped.extend(each)
        rows = grouped
        evidence = list(views) + fixed + frames
        for axis in fields.axis_slots(parameter):
            fields.apply_derived(rows, axis)
        inherit(rows, [s for s in self.frame_slots
                       if s.name in {x.name for x in slots}],
                tuples, pairs, evidence)
        result.unanswered = mark_unanswered(rows, slots)
        result.claims = [row.claim for row in rows]
        result.probes = [job.probes.get(row.label, {}) for row in rows]
        if self.trace is not None:
            self.trace("read", document_id, parameter=parameter.uri,
                       kind=source.owner_kind, owner=source.owner_id,
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

    def _rounds(self, job: _Job, view: Source, start: int = 0):
        """The values of one piece, one per round, until the model names no
        further value; CUT or None where its first round came to nothing. A
        value the check refuses is asked once more with the reason; one
        named again is asked once more, and named again it ends the rounds
        (owner decision 2026-11-05)."""
        result = job.result
        head = with_head_asked(job.parameter, view)
        shows = ({"around": job.context["around"]}
                 if job.context.get("around") else {})
        shown = job.passages_shown()
        rows: list = []
        read: list = []

        def ask(corrections: Optional[list] = None):
            return self.ask_values(view, job.parameter, dict(shows),
                                   list(read), corrections)
        first = True
        while True:
            reply = ask()
            result.asked += 1
            if not isinstance(reply, dict):
                if first:
                    return CUT if reply == CUT else None
                break
            first = False
            claim = claim_of(reply, head)
            if claim is None:
                break
            failure = round_failure(claim, shown, [r.claim for r in rows],
                                    job.parameter)
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
                failure = round_failure(claim, shown,
                                        [r.claim for r in rows],
                                        job.parameter)
                if failure is not None and failure[0] == REPEATED:
                    break
                if failure is not None and failure[0] == HEAD:
                    # Asked once: a head no head line prints says nothing of
                    # the column, and the number's own cell may still.
                    claim.pop("head", None)
            passage = passage_of(claim, shown)
            if passage is not None:
                claim["source"] = job.label_of(passage)
            rows.append(Row(label=row_label(start + len(rows)), item_index=0,
                            claim=claim))
            read.append(shown_value(claim))
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
                     group_slots: list) -> list:
        """One group's coordinates of one value, those still open only, in a
        request of the group's own; what the check refuses asked once more,
        by its coordinate. A reply that names several things for a
        coordinate that may name several makes one row per name
        (`answers_each`), each checked and asked once more on its own: [the
        rows made beside *row*]."""
        asked = [slot for slot in group_slots
                 if row.claim.get(f"{slot.name}_state") != READ]
        if not asked:
            return []
        result = job.result
        view = job.views.get(row.label, job.shown)
        base = group_context(job.context, asked, self.frame_slots, job.bases)
        read = self.known(row.claim, [slot.name for slot in asked])

        def ask(corrections: Optional[list] = None):
            return self.ask_text(view, job.parameter, group, asked, row,
                                 {**base, **({"read": read} if read else {})},
                                 corrections)
        reply = ask()
        result.asked += 1
        if not isinstance(reply, dict):
            return []
        # What the value has read is shown too, and may be quoted (owner
        # decision 2026-11-05).
        evidence = ([view] + job.fixed + job.frames
                    + known_shown(row.claim, read, job.passages))
        replies = answers_each(reply, asked)
        rows = [row] + [job.clone(row) for _ in replies[1:]]
        for one, answer in zip(rows, replies):
            self._answered(job, one, answer, asked, ask, evidence, view,
                           named=len(rows) > 1)
        return rows[1:]

    def _answered(self, job: _Job, row: Row, reply: dict, asked: list,
                  ask: Callable, evidence: list, view: Source,
                  named: bool = False) -> None:
        """*reply*'s answers onto *row*; what the check refuses asked once
        more by its coordinate. With *named*, *row* is one of several a reply
        made of one value: its correction names the name it was given and
        its quote (`named_corrections`), and a reply that names several again
        counts with its first."""
        result = job.result
        answers = reply
        self._probed(job, row, answers, asked)
        failed = job.merged([row], {slot.name: value_replies(answers, slot,
                                                             row.label)
                                    for slot in asked}, evidence)
        corrections = value_corrections(row, failed, asked, reply)
        result.failed = dict(collections.Counter(result.failed)
                             + refused_of(failed))
        if not corrections:
            return
        if named:
            corrections = named_corrections(corrections, reply, asked)
        result.corrected += len(corrections)
        result.asked += 1
        again = ask(corrections)
        if isinstance(again, dict):
            again = answers_each(again, asked)[0]
            self._probed(job, row, again, asked)
            job.merged([row], {slot.name: value_replies(again, slot,
                                                        row.label)
                               for slot in asked}, evidence)
