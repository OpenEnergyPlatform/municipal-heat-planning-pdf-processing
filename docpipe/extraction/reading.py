"""
reading.py: What the reading of a plan shares with the steps around it: the
coordinates a value of a field is asked, in the order the spec asks them;
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
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Sequence

from .. import rules
from .. import window as window_map
from . import fields, lookup, units
from .pipeline import (READ, Batch, Row, Source, answer_in_quote,
                       place_of)
from .verify import flat

# A request that did not fit its room, and one that came to no answer: the
# reasons of a hole (`surveyed.hole`).
CUT = "cut_off"
NO_ANSWER = "no_answer"

# The hits of one ranked list a request shows, per kind (owner decision
# 2026-11-04: the best 15 sections, 20 tables and 20 figures; rule
# `compute_shown`).
def shown_counts() -> dict:
    return dict(rules.get("compute_shown"))


# What a reply may ask for under "more" (owner decisions 2026-11-04 and
# 2026-11-05): the next or the previous section, a table or figure by its
# placeholder, the passages of the plan matching a pattern as a list, the
# passages nearest to a sentence the model wrote as the plan would print it
# as a list ("similar", HyDE), a passage of such a list by its id.
GETS = ("next", "previous", "item", "search", "similar", "hit")

# What the compute step may also ask for: the next part of a passage that
# came in parts (owner decision 2026-11-17: a passage that does not fit the
# request's window comes in parts, each with its heading, and the answer
# says which part of how many it is; the model asks for the next in turn).
PART_GETS = GETS + ("part",)


# Why an ask found nothing, as the reply's "not_found" says it: past the end
# of the plan, or a name that fits no passage or more than one. A pattern
# that does not compile or does not finish says `lookup.matching`'s fault.
END, UNKNOWN = "end", "unknown"

# A passage no split makes fit the request's window, or a part that no
# longer fits it: told to the model, never cut to fit.
TOO_LONG = "too_long"


# What a hit list was searched with, kept by the gathering and not shown: a
# request shows the plan's text, and the run's own sentences were quoted as
# the plan's (owner decision 2026-11-06).
SEARCHED_WITH = ("query", "similar", "pattern")


def shown_hits(ranked: list) -> list:
    """The best of each kind of a ranked search, in its order
    (`shown_counts`)."""
    left = shown_counts()
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
    unit = fields.unit_slot(spec, parameter) if parameter.has_units \
        else None
    if unit is not None:
        out.append(unit)
    return out + fields.axis_slots(parameter)


def in_order(spec, slots: list) -> list:
    """*slots* in the order the spec asks them, one request each (spec:
    "coordinates": "order", which names every coordinate once,
    `spec._validate_coordinates`); as given where the spec names no order."""
    if spec.coordinates is None:
        return list(slots)
    return spec.coordinates.in_order(slots)


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
                       "text": {"type": "string"},
                       "part": {"type": "integer"}},
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
    # The parts of each passage that came in parts, in order, by owner (a
    # `window.Part` each, a number's slot), the owner of each shown entry
    # by its id, and the parts shown (`fetch`).
    parts: dict = field(default_factory=dict)
    entries: dict = field(default_factory=dict)
    part_shown: dict = field(default_factory=dict)
    # The pattern each hit was found by, by its id (`lookup.hit_line`), and
    # the hit lists that came in parts, by their id (`_hit_list`).
    hit_pattern: dict = field(default_factory=dict)
    hit_lists: dict = field(default_factory=dict)

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
            out["hits"] = [shown_list(listed) for listed in self.hits[hits:]]
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

    def _entry(self, source: Source, text: str,
               part: Optional[tuple] = None) -> dict:
        """The entry that shows *text* of *source* (next in line), as a
        message carries it; *part* is (which, of how many) where it is one
        part of a passage that came in parts."""
        entry = {"id": f"M{len(self.shown) + 1}", "kind": source.owner_kind,
                 "title": lookup.title_of(source), "text": text}
        if part is not None:
            entry["part"] = f"{part[0]} of {part[1]}"
        return entry

    def _show(self, source: Source, text: str,
              part: Optional[tuple] = None) -> bool:
        """Show *text* of *source*; *part* is (which, of how many) where it
        is one part of a passage that came in parts."""
        owner = (source.owner_kind, source.owner_id)
        if not text or (part is None and owner in self.seen):
            return False
        self.seen.add(owner)
        self.sources.append(replace(source, text=text))
        entry = self._entry(source, text, part)
        if part is not None:
            self.part_shown.setdefault(owner, set()).add(part[0])
        self.entries[entry["id"]] = owner
        self.shown.append(entry)
        return True

    @staticmethod
    def _frame(source: Source) -> tuple:
        """(passage, own, render) of *source*: its lines, the numbers of the
        lines a part holds of its own, and `render(numbers, replaced,
        text)`, the text of a part that holds the own lines *numbers*, with
        every line the part stands under: a table's title and head, the
        rows it stands under (group rows, indented parent rows), the lines
        under it, a figure's title, a section's heading. A line in
        *replaced* is shown as the text given there, else as *text(n)*."""
        passage = units.passage_of(source)
        own = [line.number for line in passage.lines
               if line.number not in passage.fixed]
        section = source.owner_kind == "section"
        head: list = []
        if section:
            title = lookup.title_of(source)
            if own and passage.line(own[0]).text.strip() == title:
                own = own[1:]
            head = [title] if title else []

        def render(numbers: list, replaced: dict, text=None) -> str:
            text = text or (lambda n: passage.line(n).text)
            if section:
                return "\n".join(head + [replaced.get(n, text(n))
                                         for n in numbers])
            held = set(numbers)
            shown = sorted(set(passage.fixed) | held
                           | passage.parents_of(numbers))
            return "\n".join(replaced.get(n, text(n)) if n in held
                             else passage.line(n).text for n in shown)
        return passage, own, render

    def _split(self, source: Source, room: Callable) -> list:
        """The `window.Part`s of *source* that each fit *room*(text, part):
        its own lines in their order, as many as fit, each part with the
        lines it stands under (`_frame`). A part is judged with the label
        it will carry, at the most digits it can have. Raises
        `window.TooLong` where no part can fit."""
        passage, own, render = self._frame(source)
        bound = len((source.text or "").encode("utf-8"))
        return window_map.split(
            own, render, lambda n: passage.line(n).text,
            lambda text: room(text, (bound, bound)), units.sentences_of,
            name=f"{source.owner_kind} {source.owner_id}")

    def _bring(self, source: Source, ask: dict, room_for: Callable,
               added: list, at: Optional[str] = None,
               pattern: Optional[str] = None) -> bool:
        """Show *source* whole where it fits, else its first part (the part
        that holds the line *at*, a hit's, found by its number, where one
        does): the others follow when the model asks for them (`get`
        "part"). A passage that cannot be split to fit is missed, never
        cut."""
        owner = (source.owner_kind, source.owner_id)
        text = source.text or ""
        if owner in self.seen or not text:
            return False
        room = room_for(source)
        if room(text):
            added.append(text)
            return self._show(source, text)
        try:
            done = self._split(source, room)
        except window_map.TooLong as exc:
            self._miss(ask, TOO_LONG, str(exc))
            return False
        if not done:
            self._miss(ask, TOO_LONG)
            return False
        self.parts[owner] = done
        first = 0
        if at:
            number = lookup.hit_line(units.passage_of(source).lines, at,
                                     pattern)
            first = next((i for i, part in enumerate(done)
                          if number in part.numbers), 0)
        added.append(done[first].text)
        return self._show(source, done[first].text, (first + 1, len(done)))

    def _resplit(self, source: Source, owner: tuple, room: Callable) -> list:
        """The parts of *owner* after the ones not shown yet are split anew
        to fit *room*(text, part): the parts shown keep their numbers, the
        new ones take the numbers of the others in order, those that remain
        come after the last number (the count grows); a number the new
        split does not need is empty and counts as shown. The own lines
        (or the words of a split line) no part shown holds are what is
        split; every one stands in exactly one part. Raises
        `window.TooLong` where no part can fit, and then changes nothing."""
        slots = self.parts[owner]
        done = self.part_shown.get(owner, set())
        passage, _own, render = self._frame(source)
        left: dict = {}
        for number, part in enumerate(slots, start=1):
            if number in done:
                continue
            for line in part.numbers:
                text = part.replaced.get(line, passage.line(line).text)
                left[line] = f"{left[line]} {text}" if line in left else text
        bound = len((source.text or "").encode("utf-8"))
        made = window_map.split(
            list(left), lambda numbers, replaced: render(
                numbers, replaced, left.__getitem__), left.__getitem__,
            lambda text: room(text, (bound, bound)), units.sentences_of,
            name=f"{source.owner_kind} {source.owner_id}") if left else []
        free = [i for i in range(len(slots)) if i + 1 not in done]
        out = list(slots)
        for at, part in zip(free, made):
            out[at] = part
        out.extend(made[len(free):])
        shown = self.part_shown.setdefault(owner, set())
        for at in free[len(made):]:
            out[at] = window_map.Part((), {}, "")
            shown.add(at + 1)
        self.parts[owner] = out
        return out

    def _more_of(self, ask: dict, room_for: Callable, room_hits: Callable,
                 added: list, order: list) -> bool:
        """The part *ask* names of the passage, or the hit list, its id
        names. A part that no longer fits the room left now is split anew
        with the parts not shown yet (`_resplit`)."""
        which = ask.get("part")
        if isinstance(ask.get("id"), str) and ask["id"] in self.hit_lists:
            return self._more_hits(ask, room_hits, added)
        owner = self.entries.get(ask.get("id") or "")
        slots = self.parts.get(owner)
        if not slots or not isinstance(which, int) \
                or not 1 <= which <= len(slots):
            self._miss(ask, UNKNOWN)
            return False
        if which in self.part_shown.get(owner, ()):
            return False
        source = next((p for p in order
                       if (p.owner_kind, p.owner_id) == owner), None)
        if source is None:
            self._miss(ask, UNKNOWN)
            return False
        room = room_for(source)
        if not room(slots[which - 1].text, (which, len(slots))):
            try:
                slots = self._resplit(source, owner, room)
            except window_map.TooLong as exc:
                self._miss(ask, TOO_LONG, str(exc))
                return False
        part = slots[which - 1]
        if not part.numbers:
            # A number a new split left empty: that part is no more.
            self._miss(ask, UNKNOWN)
            return False
        added.append(part.text)
        return self._show(source, part.text, (which, len(slots)))

    def _miss(self, ask: dict, why: str, detail: str = "") -> None:
        entry = {"get": ask.get("get"),
                 **{key: ask[key] for key in ("id", "pattern", "text", "part")
                    if ask.get(key)}, "why": why}
        if detail:
            entry["detail"] = detail
        if entry not in self.missed:
            self.missed.append(entry)

    @staticmethod
    def _hit_rows(found: list, start: int) -> list:
        """The hits *found*, [(owner, title, line)], as a list shows them,
        each with the id a later ask names it by, from the one after
        *start*."""
        return [{"id": f"H{start + i + 1}", "kind": owner[0], "title": title,
                 "line": line}
                for i, (owner, title, line) in enumerate(found)]

    def list_hits(self, found: list, **about) -> int:
        """Show *found*, [(owner, title, line)], as one list of hits, each
        with the id a later ask names it by. Returns how many."""
        listed = self._hit_rows(found, len(self.by_hit))
        for row, (owner, _title, line) in zip(listed, found):
            self.by_hit[row["id"]] = (tuple(owner), line)
            if about.get("pattern"):
                self.hit_pattern[row["id"]] = about["pattern"]
        if listed:
            self.hits.append({**about, "hits": listed})
        return len(listed)

    def _chunk_hits(self, found: list, start: int, fit: Callable) -> tuple:
        """([hits of a part], [hits left out]): *found* in parts that each
        fit, as many hits in a part as fit (`fit(hits, used)`: do these
        hits, with the ids from the one after *used*, fit?); a hit that
        does not fit alone is left out, never cut."""
        chunks: list = []
        left: list = []
        rest = list(found)
        used = start
        while rest:
            size = largest_prefix(rest, lambda items: fit(items, used))
            if size == 0:
                left.append(rest[0])
                rest = rest[1:]
                used += 1
                continue
            chunks.append(rest[:size])
            rest = rest[size:]
            used += size
        return chunks, left

    def _hit_fit(self, room_hits: Callable, about: dict,
                 list_id: Optional[str], bound: int) -> Callable:
        """`fit(hits, used)` for a list with *about*: the list as it is
        shown (`shown_list`), with the ids `list_hits` gives and, for a
        list in parts, its id and the label of its part (at the most digits
        it can have, *bound* parts)."""
        def fit(items: list, used: int) -> bool:
            entry = {**about, "hits": self._hit_rows(items, used)}
            if list_id is not None:
                entry = {**entry, "id": list_id,
                         "part": f"{bound} of {bound}"}
            return room_hits(shown_list(entry))
        return fit

    def _hit_list(self, ask: dict, found: list, about: dict,
                  room_hits: Callable, added: list) -> bool:
        """The hits *found* listed, whole where they fit the room, else in
        parts, the first now and the others when the model asks for them
        (`get` "part", the list's id); a hit that does not fit alone is
        missed, never cut. True where something came of it."""
        if not found:
            self.hits.append({**about, "hits": []})
            return True
        start = len(self.by_hit)
        if self._hit_fit(room_hits, about, None, 0)(found, start):
            self.list_hits(found, **about)
            added.append(json.dumps(self.hits[-1]["hits"],
                                    ensure_ascii=False))
            return True
        list_id = f"L{len(self.hit_lists) + 1}"
        chunks, left = self._chunk_hits(
            found, start, self._hit_fit(room_hits, about, list_id,
                                        len(found)))
        self._miss_hits(ask, left)
        if not chunks:
            return False
        self.hit_lists[list_id] = {
            "about": about, "shown": 1,
            "rest": [hit for chunk in chunks[1:] for hit in chunk]}
        self.list_hits(chunks[0], id=list_id, part=f"1 of {len(chunks)}",
                       **about)
        added.append(json.dumps(self.hits[-1]["hits"], ensure_ascii=False))
        return True

    def _more_hits(self, ask: dict, room_hits: Callable,
                   added: list) -> bool:
        """The next part of a hit list that came in parts, sized to the room
        left now: its number says how many have come, the count how many
        there are at this room."""
        state = self.hit_lists[ask["id"]]
        which = ask.get("part")
        if not isinstance(which, int):
            self._miss(ask, UNKNOWN)
            return False
        if which <= state["shown"]:
            return False
        if not state["rest"]:
            self._miss(ask, UNKNOWN)
            return False
        bound = state["shown"] + len(state["rest"])
        chunks, left = self._chunk_hits(
            state["rest"], len(self.by_hit),
            self._hit_fit(room_hits, state["about"], ask["id"], bound))
        self._miss_hits(ask, left)
        if not chunks:
            state["rest"] = []
            return False
        number = state["shown"] + 1
        state["shown"] = number
        state["rest"] = [hit for chunk in chunks[1:] for hit in chunk]
        self.list_hits(chunks[0], id=ask["id"],
                       part=f"{number} of {number - 1 + len(chunks)}",
                       **state["about"])
        added.append(json.dumps(self.hits[-1]["hits"], ensure_ascii=False))
        return True

    def _miss_hits(self, ask: dict, left: list) -> None:
        for _owner, title, _line in left:
            self._miss(ask, TOO_LONG,
                       f"the hit {title!r} does not fit the room beside "
                       f"its list")

    def fetch(self, asks, order: list, passages: dict,
              fits: Optional[Callable] = None,
              render: Optional[Callable] = None) -> bool:
        """The asks of one reply resolved (`lookup`). Each passage comes
        whole where it fits the request's window, else in parts, each with
        its heading, the answer saying which part of how many it is; so
        does a hit list. *fits*(texts) says whether texts together still
        fit the window, None where nothing bounds them. *render*(follow)
        is the message that tells the model what this fetch brought: where
        it is given, *fits* judges that message, the entries brought so far
        and the one tried, exactly as it will be sent (the size judged is
        the size sent); else it judges the texts alone. True when a passage
        or a hit list came of them the request has not shown yet: an ask
        for something shown already, or for nothing, ends the gathering."""
        new = False
        added: list = []
        start = self.mark()

        def judged(kind: str, entry: dict, text: str) -> bool:
            if fits is None:
                return True
            if render is None:
                return fits([*added, text])
            follow = self.since(start)
            follow[kind] = [*follow.get(kind, ()), entry]
            return fits([render(follow)])

        def room_for(source: Source) -> Callable:
            def room(text: str, part: Optional[tuple] = None) -> bool:
                return judged("more", self._entry(source, text, part), text)
            return room

        def room_hits(entry: dict) -> bool:
            return judged("hits", entry,
                          json.dumps(entry, ensure_ascii=False))
        for ask in asks if isinstance(asks, list) else ():
            if not isinstance(ask, dict):
                continue
            get = ask.get("get")
            if get in ("next", "previous"):
                step = 1 if get == "next" else -1
                run = lookup.fetch_run(order, self.cursor[get], step > 0)
                if not run:
                    self._miss(ask, END)
                    continue
                for found in run:
                    self.cursor[get] = (found.owner_kind, found.owner_id)
                    new = self._bring(found, ask, room_for, added) or new
            elif get == "item":
                found = lookup.item(order, ask.get("id") or "")
                if found is None:
                    self._miss(ask, UNKNOWN)
                    continue
                new = self._bring(found, ask, room_for, added) or new
            elif get == "part":
                new = self._more_of(ask, room_for, room_hits, added,
                                    order) or new
            elif get == "search":
                pattern = ask.get("pattern")
                # A list no search made, the ranking's, has no pattern.
                if not pattern or any(h.get("pattern") == pattern
                                      for h in self.hits):
                    continue
                matches = lookup.matching(order, pattern)
                if matches.fault:
                    self._miss(ask, matches.fault, matches.detail)
                    continue
                new = self._hit_list(
                    ask, [(hit["owner"], hit["title"], hit["line"])
                          for hit in matches.hits],
                    {"pattern": pattern, "total": matches.total},
                    room_hits, added) or new
            elif get == "similar":
                text = ask.get("text")
                if not isinstance(text, str) or not text.strip() \
                        or any(h.get("similar") == text for h in self.hits):
                    continue
                if self.rank is None:
                    self._miss(ask, UNKNOWN)
                    continue
                # The best of each kind, as a search shows them
                # (owner decision 2026-11-05: `shown_counts`), the passages the
                # request shows left out.
                ranked = shown_hits(self.rank([text], set(self.seen)))
                new = self._hit_list(
                    ask, [((s.owner_kind, s.owner_id), lookup.title_of(s),
                           first_line(s)) for s in ranked],
                    {"similar": text}, room_hits, added) or new
            elif get == "hit":
                ref = self.by_hit.get(ask.get("id") or "")
                found = passages.get(ref[0]) if ref else None
                if found is None:
                    self._miss(ask, UNKNOWN)
                    continue
                new = self._bring(found, ask, room_for, added, at=ref[1],
                                  pattern=self.hit_pattern.get(ask["id"])
                                  ) or new
            else:
                self._miss(ask, UNKNOWN)
        return new


def shown_list(listed: dict) -> dict:
    """A hit list as a message shows it: without what it was searched with
    (`SEARCHED_WITH`)."""
    return {key: value for key, value in listed.items()
            if key not in SEARCHED_WITH}


def largest_prefix(items: list, fits: Callable) -> int:
    """How many of *items*, from the first, still fit (`fits(prefix)`, which
    holds for fewer where it holds for more): found by doubling, then by
    halving, so that few and never much more than the room is judged."""
    if not items or not fits(items[:1]):
        return 0
    good, bad = 1, None
    while good < len(items):
        probe = min(len(items), good * 2)
        if fits(items[:probe]):
            good = probe
        else:
            bad = probe
            break
    if bad is None:
        return good
    while bad - good > 1:
        mid = (good + bad) // 2
        if fits(items[:mid]):
            good = mid
        else:
            bad = mid
    return good


def first_line(source: Source) -> str:
    """The first line of a passage under its title, whole: what a hit list
    shows of it (owner decision 2026-11-17: nothing is cut)."""
    title = lookup.title_of(source)
    return next((line.strip()
                 for line in (source.text or "").splitlines()
                 if line.strip() and line.strip() != title), "")


def passage_of(claim: dict, shown: list,
               document: Sequence = ()) -> Optional[Source]:
    """The first passage of *shown* whose text carries the claim's quote:
    the one its value is read from; where the rule `check_quote_shown` is
    off and none does, the first passage of *document*, the document's
    passages in its order, that does (`pipeline.place_of`). None where the
    quote stands in none."""
    return place_of(shown, claim.get("quote"), document)


def span_rows(row: Row, slot, until: Optional[int], marks: dict,
              clone: Callable) -> list:
    """A value the plan states for a span of years as one row per year of
    it (owner decision 2026-11-07: "als ca. für jedes distinkte Jahr
    erfassen"): *row*, read with the span's first year, and a copy of it
    (*clone(row)*) for each year after, the last read as the first is, those
    between derived from the span, which the quote prints and names neither
    of. Each takes *marks* ({coordinate: entry}, the rule `span_marks`)
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
    if not rules.get("link_range_ends"):
        return 0
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
    # A field of the document that found nothing while chunks of the
    # document were never shown to it: no reading, only the mark that its
    # state is `parameter_uncombed` (owner decision 2026-11-13, point 3).
    uncombed: bool = False
