"""
reading.py: What the reading of a plan shares with the steps around it: the
coordinates a value of a field is asked, in the order of the spec's groups;
a value stated for a span of years as one row per year; the two ends of a
range linked; what a request fetches of the rest of a plan itself
(`Gathered`, the compute step's tools); and what reading one field in one
passage came to (`Read`).

The reading itself is `addressed.py` (owner decisions 2026-11-08 evening):
pieces of numbered lines, one question per request, every answer an
address.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from . import fields, lookup
from .pipeline import (READ, Batch, Row, Source, answer_in_quote,
                       window_around)
from .verify import flat, quote_in

# A request that did not fit its room, and one that came to no answer: the
# reasons of a hole (`surveyed.hole`).
CUT = "cut_off"
NO_ANSWER = "no_answer"

# The hits of one ranked list a request shows, per kind (owner decision
# 2026-11-04: the best 15 sections, 20 tables and 20 figures).
SHOWN = {"section": 15, "table": 20, "figure": 20}


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


def shown_hits(ranked: list) -> list:
    """The best of each kind of a ranked search, in its order (`SHOWN`)."""
    left = dict(SHOWN)
    out = []
    for source in ranked:
        if left.get(source.owner_kind, 0) > 0:
            left[source.owner_kind] -= 1
            out.append(source)
    return out


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
    order they are asked in, one request each."""
    order = list(group.coordinates)
    return sorted(group_slots, key=lambda slot: order.index(slot.name)
                  if slot.name in order else len(order))


def groups_of(spec, slots: list) -> list:
    """[(group, its slots)] of *slots*, in the order of the spec's groups
    (owner decision 2026-11-04). The spec puts every coordinate in exactly
    one group (`spec._validate_groups`)."""
    return [(group, [slot for slot in slots
                     if slot.name in group.coordinates])
            for group in spec.groups.values()
            if any(slot.name in group.coordinates for slot in slots)]


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
                # The best of each kind, as a search shows them
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


def passage_of(claim: dict, shown: list) -> Optional[Source]:
    """The first passage of *shown* whose text carries the claim's quote:
    the one its value is read from. None where the quote stands in none."""
    quote = claim.get("quote")
    if not isinstance(quote, str):
        return None
    return next((source for source in shown
                 if quote_in(source.text or "", quote)), None)


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
    # what the check refused of the first replies, by reason
    failed: dict = field(default_factory=dict)
    unanswered: int = 0           # coordinates no reply answered
