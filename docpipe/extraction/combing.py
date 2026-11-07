"""
combing.py: The coordinates the reading left open, asked in a conversation of
their own: first with the sections around the value's place, then in the
rest of the plan. Step 4 of the rebuilt harvest (owner decisions 2026-11-04
to 2026-11-07).

The reading asks a value's coordinates in its own passage, one message each
(`reading.py`). What it leaves open (a coordinate the passage does not
state, one whose answer did not hold, one no reply answered) is asked here,
in a NEW conversation per value, not in the value's reading conversation
(owner decision 2026-11-07: „Es wird neues Gespräch, mit den bisherigen
Antworten / Ergebnissen“, to spare the context). Its first message shows the
value with its quote, its answers so far with their quotes, the title and
heading of its place, the line of the title page, the table it may continue,
the plan's settings and the coordinate asked; never the passage itself
(owner decision 2026-11-07: „Ohne die Tabelle“), which the value's quote and
answers pin down. Every request carries its document, so the run orders and
dedupes it with the document's other requests.

First the second reading (owner decision 2026-11-06): the sections before
and after the value's place (`reading.near_of`) are shown once, and each open
coordinate is asked on its own, one message after another, all but those
printed with the number itself (`Group.asked_near`). Its answer may be "not
stated", with the sentence of how the plan would print it (`probe`). A find
quoted from those sections is asked about once more: does that place speak
about the value (`reading.Judge`, owner decision 2026-11-07)?

Then the search, for each coordinate still open that another passage can
state (`Group.combed`): what a number counts and how it is aggregated says
its own passage, and a word like "ca." the number itself (owner decision
2026-11-06). One coordinate after another: its first message shows the hits
of a search with the sentence the reading wrote to it, as the plan would
print it (owner decision 2026-11-05: HyDE, `Read.probes`), as a list of titles
and first lines, without the sentence: it is the run's own writing, not the
plan's, and the model quoted it as the plan's (owner decision 2026-11-06).
That message lets the model fetch hits only; from its next message on it may
also search itself (owner decision 2026-11-07: „erst die retrievals
durchgehen und dann kann es agentisch suchen“), with the reading's own
tools: a hit by its id, the next or the previous section, a table or figure
by its placeholder, a pattern, a sentence of its own ("similar"). Where no
sentence was written, there is no list, and it searches itself at once. It
answers the coordinate where it finds it and leaves it out where it does not:
the search offers no "not stated" (owner decision 2026-11-06), and one the
model writes all the same is no answer (`found`). A round that asks for
nothing new while the coordinate is unfound gets the next passages of the
ranking, as many of each kind as the first list, or of the plan in its order
where there is no ranking, until every passage of the plan was listed (owner
decision 2026-11-06: the search runs empty). Only then is it `unstated`, a
finding about the plan; one whose request no longer fits the model's window
before that is `exhausted`, a finding about the run. A conversation that no
longer fits begins anew for the next coordinate. A find quoted from a passage
other than the value's own, its section and its heading is checked as the
second reading's are.

A table that prints no frame in its head and rows, its frame open on every
one of its values, gets one such conversation for the whole table, which
shows the table: its answers hold for every value of it, which take them
with their quotes (`taken_by`, owner decisions 2026-11-02 and 2026-11-06).
A value whose open coordinate may name several things, such as a scenario,
is shown every name of that kind read in the plan so far, each once, so the
model can give all of them a value holds for at once (`names_read`, owner
decision 2026-11-07); each still needs a quote that holds it, and each makes
a row of its own (`reading.answers_each`).

Nothing is checked here beyond what the harvest checks everywhere. Every
answer goes through `merge_field`, and what it refuses is asked once more in
ONE message after that answer, with the reason; in the search, a quote that
lacks its answer is to be fixed or the coordinate left out (`NOT_IN_QUOTE`).
Its quote may stand in whatever the conversation showed of the plan (owner
decision 2026-11-05): a section around the value, a passage the model
fetched, a hit's line or title, the title or heading of the value's place,
the quote of the value or of one of its answers, the plan's settings.

A pass over a stored harvest asks with the same conversation
(`Comber.comb_groups`): the coordinates it names (*coordinates*) whatever
their state, the value's own passage and its section shown first (*own*),
since the reading that asked them there ran under an older question, the
years of the stored rows (*bases*), and the passages a harvest before read
the coordinate in listed (*first*). A stored row carries no sentence, so the
model searches the rest of the plan itself.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import partial
from typing import Callable, Optional

from . import fields, lookup, naming
from .fields import (COORDINATE_KEYS, EXHAUSTED, READ, SAID_UNSTATED,
                     UNANSWERED, UNBACKED, UNIT, UNSTATED)
from .pipeline import Row, merge_field, row_label
from .reading import (ABOUT, CHECK_FOLLOWS, CHECK_PROMPT_ID, COORDINATES,
                      CORRECTIONS, GETS, NOT_ABOUT, SHOWN, Gathered, Judge,
                      answer_of, answer_schema, answers_each, around_of,
                      check_example, check_response_format, check_shown,
                      coordinate_shown, entry_example, first_line, gather,
                      groups_of, heading_of, in_group_order, more_schema,
                      near_of, passage_at, place_text, routed,
                      settings_evidence, settings_shown, several, shown_as,
                      shown_hits, shown_value, slots_of, source_of,
                      source_shown, spread, table_before_of, told_once,
                      turned_out, unanswered_what, years_of)
from .thread import Thread
from .wording import say

COMB_PROMPT_ID = "extraction/comb"
# A find quoted from a passage other than the value's own and its section is
# asked about once more, whether that place speaks about the value
# (`reading.Judge`, `CHECK_PROMPT_ID`, owner decision 2026-11-07); one it
# says "no" to is not taken, the requests that follow tell the model so,
# and the search goes on.

# The fields of the messages that follow an answer, whose words the prompts
# hold (`runner.FOLLOWS`, owner decisions 2026-11-07): the coordinate asked
# next ("coordinates"), what the search fetched ("more"), the next hits
# ("hits"), what could not be fetched ("not_found") and what was wrong with
# the answer before ("corrections"); the check is told what was wrong with
# its answer.
FOLLOWS = (COORDINATES, "more", "hits", "not_found", CORRECTIONS)

# What a combing request tells of a quote that stands in nothing it showed,
# in the names of what it shows: "more", "hits", "passage", "row" (owner
# decision 2026-11-06).
NOT_SHOWN = "quote_not_shown"
# How its correction for a quote that lacks the answer ends: the search
# offers no "not stated", so the model leaves the coordinate out (owner
# decision 2026-11-06).
NOT_IN_QUOTE = "or_leave_out"

# What the reading leaves for this step.
OPEN = (SAID_UNSTATED, UNBACKED, UNANSWERED)

# What the first message of a coordinate's search lets the model fetch: the
# hits of the list it shows (owner decision 2026-11-07: first the retrieval,
# then the model's own search).
FIRST_GETS = ("hit",)

# The hits of one search the request shows, per kind, are `reading.SHOWN`
# (owner decision 2026-11-04: the best 15 sections, 20 tables and 20
# figures), cut by `reading.shown_hits`; both are named here as before.
__all__ = ["ABOUT", "CHECK_FOLLOWS", "CHECK_PROMPT_ID", "COMB_PROMPT_ID",
           "FIRST_GETS", "NOT_ABOUT", "OPEN", "SHOWN", "Comber", "Combed",
           "answers_shown", "as_rows", "check_example",
           "check_response_format", "comb_example", "comb_response_format",
           "finds", "found", "names_read", "near_example",
           "near_response_format", "open_of", "place_text", "shown_hits"]

# What the example of a combing request asks of the rest of the plan, as the
# prompts' examples always showed it.
MORE_EXAMPLE = [{"get": "hit", "id": "H2"}]


def open_of(claim: dict, slots: list) -> list:
    """The coordinates of a value still open after its reading."""
    return [slot.name for slot in slots
            if claim.get(f"{slot.name}_state") in OPEN]


def comb_response_format(slots: list, gets: tuple = GETS) -> dict:
    """The coordinates a search message asks of the one value it is about,
    as far as the reply found them, at the top of the reply with no wrapper
    and no row label (owner decision 2026-11-06), none required and none
    UNSTATED, and what the reply asks of the rest of the plan: any of
    *gets* (`FIRST_GETS` in the first message of a coordinate's search)."""
    properties = {slot.name: answer_schema(slot, unstated=False)
                  for slot in slots}
    properties["more"] = more_schema(gets)
    schema = {"type": "object", "properties": properties,
              "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "comb_reply", "schema": schema}}


def near_response_format(slots: list) -> dict:
    """The coordinate a message of the second reading asks of its value:
    required, "not stated" one of its answers, with the sentence of how the
    plan would print it (`probe`), which the search ranks with."""
    properties = {slot.name: answer_schema(slot, probe=True)
                  for slot in slots}
    schema = {"type": "object", "properties": properties,
              "required": [slot.name for slot in slots],
              "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "near_reply", "schema": schema}}


def found(answer) -> bool:
    """Does *answer*, a reply's entry for one coordinate, name something: an
    answer that is not UNSTATED, alone or in a list? An entry the reply left
    out, one without a value, and UNSTATED name nothing: the search does
    not offer it, and one the model writes all the same is no answer (owner
    decision 2026-11-06). A name in another form than asked names something,
    and is asked for once more in the form asked."""
    if isinstance(answer, list):
        return any(found(one) for one in answer)
    if isinstance(answer, dict):
        answer = answer.get("value")
    if isinstance(answer, str):
        answer = answer.strip()
    return answer not in (None, "", UNSTATED)


def finds(reply, slots: list):
    """*reply* (`as_rows`) as the search reads it: each row's entries that
    name nothing (`found`) taken out, and each list without its entries
    that name nothing. Anything but an object is left as it is."""
    if not isinstance(reply, dict):
        return reply
    names = [slot.name for slot in slots]
    rows = []
    for entry in reply.get("rows") or ():
        if not isinstance(entry, dict):
            rows.append(entry)
            continue
        entry = dict(entry)
        for name in names:
            given = entry.get(name)
            if isinstance(given, list):
                given = [one for one in given if found(one)]
            if found(given):
                entry[name] = given
            else:
                entry.pop(name, None)
        rows.append(entry)
    return {**reply, "rows": rows}


def entry_of(reply, label: str) -> dict:
    """The entry of the row *label* in *reply* (`as_rows`), or {}."""
    for entry in (reply.get("rows") or ()) if isinstance(reply, dict) else ():
        if isinstance(entry, dict) and entry.get("row") == label:
            return entry
    return {}


def comb_example(slots: list) -> dict:
    """The reply of a search message as its example shows it: exactly the
    coordinates it asks, in its order, each read (`reading.entry_example`),
    then what it asks of the rest of the plan, as `comb_response_format`
    has them (owner decision 2026-11-06)."""
    return {**{slot.name: entry_example(slot) for slot in slots},
            "more": [dict(ask) for ask in MORE_EXAMPLE]}


def near_example(slots: list) -> dict:
    """The reply of a message of the second reading as its example shows
    it: exactly the coordinate it asks, read."""
    return {slot.name: entry_example(slot) for slot in slots}


def as_rows(reply, label: str):
    """A reply about the one row a request showed (`comb_response_format`)
    as the rows the step folds: its answers under that row's *label*, its
    requests for more beside them. Anything but an object is left as it
    is."""
    if not isinstance(reply, dict):
        return reply
    entry = {key: value for key, value in reply.items() if key != "more"}
    out = {"rows": [{**entry, "row": label}]}
    if "more" in reply:
        out["more"] = reply["more"]
    return out


def names_read(spec, reads: list) -> dict:
    """{kind: [name]}: every name read in the plan so far for a kind of
    thing the spec merges (`naming.merged_slots`), as a value or as a
    coordinate, each once, in the order the reading read them (owner
    decision 2026-11-07: "Alle gelesenen Namen")."""
    kinds = naming.merged_slots(spec)
    out: dict = {}
    for read in reads:
        for key, kind in (kinds.get(read.batch.parameter.uri) or {}).items():
            for claim in read.claims:
                got = naming.read_name(claim, key)
                if got is not None and got[0] not in out.setdefault(kind, []):
                    out[kind].append(got[0])
    return out


def answers_shown(claim: dict) -> dict:
    """{coordinate: {"value", "quote"}}: what a value has read so far, each
    coordinate the plan's wording (or the answer itself where it has none)
    with the quote it was read from, the unit included; what the spec
    derived is its decision and says nothing the plan printed (owner
    decision 2026-11-07: the conversation for what is open begins with the
    answers so far)."""
    out = {}
    for key in sorted(claim):
        if not key.endswith("_state") or claim[key] != READ:
            continue
        name = key[:-len("_state")]
        wording = claim.get(f"{name}_raw")
        given = wording if isinstance(wording, str) and wording.strip() \
            else claim.get(name)
        if given in (None, ""):
            continue
        entry = {"value": given}
        if claim.get(f"{name}_quote"):
            entry["quote"] = claim[f"{name}_quote"]
        out[name] = entry
    return out


def answers_evidence(claim: dict, passages: dict) -> list:
    """The quotes of a value's answers so far (`answers_shown`), each a
    passage a quote may stand in under the passage it was read from."""
    out = []
    for name in answers_shown(claim):
        out += shown_as(passage_at(passages, claim.get(f"{name}_source")),
                        claim.get(f"{name}_quote"))
    return out


@dataclass
class Combed:
    """What one conversation for the open coordinates of one value came
    to."""
    parameter: str
    owner: tuple
    rows: int
    open: int                     # coordinates open before
    filled: int = 0               # read by this step
    asked: int = 0
    near: int = 0                 # requests of the second reading
    near_read: int = 0            # coordinates it read
    hits: int = 0                 # hits of the search shown
    fetched: int = 0
    searched: int = 0
    missed: int = 0
    corrected: int = 0
    exhausted: int = 0
    listed: int = 0               # lists of the next passages the run added
    # rows made beside the value, one per further name it was stated for
    made: list = field(default_factory=list)
    # the other values of its table that took the answers asked for this
    # one, its frame open on all of them (owner decision 2026-11-06)
    table_rows: int = 0
    # finds quoted from a passage other than the value's own the check was
    # asked about, and those it said do not speak about the value (owner
    # decision 2026-11-07)
    judged: int = 0
    turned: int = 0
    # conversations begun anew because the one before outgrew the window
    anew: int = 0


# The keys of one coordinate a value takes from the value of its table that
# was asked for all of them (`taken_by`).
TAKEN = COORDINATE_KEYS


def taken_by(first: dict, others: list, names: list) -> None:
    """The coordinates *names* as the conversation left them on *first*, the
    value of a table it was asked for, taken by the table's other values,
    with their quotes and states (owner decisions 2026-11-02 and 2026-11-06:
    a table that prints no frame in its head and rows is asked once). A
    coordinate the search read on the first counts for the others as read
    for their table (`table`)."""
    for claim in others:
        for name in names:
            for suffix in TAKEN:
                claim.pop(f"{name}{suffix}", None)
                if f"{name}{suffix}" in first:
                    claim[f"{name}{suffix}"] = copy.deepcopy(
                        first[f"{name}{suffix}"])
            window = claim.get(f"{name}_window") or ()
            if claim.get(f"{name}_state") == READ and window \
                    and window[0] == "retrieval":
                claim[f"{name}_window"] = ["table", 2]


class Comber:
    """(document_id, reads, passages, pairs, budget) -> [Combed], one per
    read value with an open coordinate and one per table whose frame is
    open on every one of its values.

    *ask(payload, shape, document_id, source, group, example, thread,
    follow)* is one message of a conversation (`thread.Thread`): the first
    shows *payload*, a later one carries *follow*, what is new since the
    answer it follows (`FOLLOWS`); the reply as a dict, CUT, or None,
    *group* None, *example* the reply its prompt shows.
    *rank(document_id, probes, exclude)* is the plan's passages best first
    for the search sentences *probes* (`runner.make_more_sources`): the
    reading's sentences, and the model's own under "similar".
    *known(claim, asked)* is what a row has read in the plan's words
    (`runner.row_context`), which the check shows. *check(payload, shape,
    document_id, source, group, example, thread, follow)*, where given, is
    the request that asks of a find quoted from a passage other than the
    value's own and its section whether that place speaks about the value
    (`CHECK_PROMPT_ID`, owner decision 2026-11-07), a reply that names
    neither answer told so after it.
    """

    def __init__(self, spec, ask: Callable, rank: Optional[Callable],
                 known: Callable, *, bases: Optional[Callable] = None,
                 pool=None, trace=None, check: Optional[Callable] = None):
        self.spec = spec
        self.ask = ask
        self.rank = rank
        self.known = known
        self.bases = bases or (lambda pairs: [])
        self.pool = pool
        self.trace = trace
        self.check = check

    def _asked(self, parameter) -> list:
        """[(slot, group)] of *parameter* this step may ask, in the order of
        the spec's groups and of each group's coordinates: all but those
        printed with the number itself (`Group.asked_near`)."""
        slots = slots_of(self.spec, parameter)
        return [(slot, group) for group, group_slots in groups_of(self.spec,
                                                                  slots)
                for slot in in_group_order(group,
                                           group.asked_near(group_slots))]

    def __call__(self, document_id: int, reads: list, passages: dict,
                 pairs: list, budget: Optional[int] = None,
                 bases: Optional[list] = None, *,
                 title_page=None, settings: Optional[list] = None) -> list:
        """One conversation per read value with a coordinate still open
        after its reading (owner decisions 2026-11-04 to 2026-11-07: one
        value per request, a new conversation for what is open). A table's
        frame open on every one of its values is asked once, for its first
        value, and the others take the answers (`taken_by`); those
        conversations run first. *bases* are the plan's years
        (`years.PlanYears`), else those of *pairs*; *title_page* the line of
        the plan's title page, *settings* what the plan settles for all its
        values (`settings.PlanSettings`), both shown to every conversation."""
        tables: list = []
        values: list = []
        for read in reads:
            parameter = read.batch.parameter
            asked = self._asked(parameter)
            slots = [slot for slot, _group in asked]
            by_table: dict = {}
            for index, claim in enumerate(read.claims):
                source = source_of(read.batch, claim)
                if source.owner_kind == "table":
                    by_table.setdefault(source.owner_id, []).append(
                        (index, claim, source))
            taken: dict = {}
            for owner, entries in by_table.items():
                if len(entries) < 2:
                    continue
                common = [slot for slot, group in asked
                          if group.read_in == "survey" and not several(slot)
                          and all(claim.get(f"{slot.name}_state") in OPEN
                                  for _i, claim, _s in entries)]
                if not common:
                    continue
                index, claim, source = entries[0]
                tables.append((read, parameter, source, common, index,
                               [one for _i, one, _s in entries[1:]]))
                for i, _claim, _source in entries:
                    taken.setdefault(i, set()).update(s.name for s in common)
            for index, claim in enumerate(read.claims):
                names = set(open_of(claim, slots)) - taken.get(index, set())
                if names:
                    values.append((read, parameter,
                                   source_of(read.batch, claim),
                                   [slot for slot in slots
                                    if slot.name in names], index, []))

        read_so_far = names_read(self.spec, reads)

        def one(job):
            read, parameter, source, slots, index, others = job
            claim = read.claims[index]
            probes = read.probes[index] if index < len(read.probes) else {}
            shown = list(dict.fromkeys(
                name for slot in slots if several(slot)
                and slot.name in open_of(claim, slots)
                for name in read_so_far.get(slot.merged, ())))
            result = self.comb(document_id, parameter, source, slots,
                               [claim], passages, pairs, budget,
                               probes=probes, split=not others,
                               bases=tuple(bases) if bases is not None
                               else None, whole_table=len(others),
                               names_so_far=shown, title_page=title_page,
                               settings=settings)
            if others:
                taken_by(claim, others, [slot.name for slot in slots])
            return result

        def run(jobs: list) -> list:
            if self.pool is None:
                return [one(job) for job in jobs]
            return list(self.pool.map(one, jobs))
        # The tables first: a value of one shows the frame its table took.
        combed = run(tables)
        combed += run(values)
        # A value asked for several names is one row per name (owner
        # decision 2026-11-06): the rows made join their value's reading.
        for job, result in zip(tables + values, combed):
            read, index = job[0], job[4]
            probes = read.probes[index] if index < len(read.probes) else {}
            if result.made:
                read.probes = list(read.probes) + [{}] * max(
                    0, len(read.claims) - len(read.probes))
                read.claims.extend(row.claim for row in result.made)
                read.probes.extend(dict(probes) for _ in result.made)
        return combed

    def comb_groups(self, document_id: int, parameter, source, slots: list,
                    claims: list, passages: dict, pairs: list,
                    budget: Optional[int] = None, *,
                    coordinates: Optional[list] = None, own: bool = False,
                    bases: Optional[tuple] = None,
                    first: Optional[list] = None) -> list:
        """`comb` once per value of *claims* that has something to ask: with
        *coordinates* those of them *slots* has, whatever their state, else
        a coordinate open on the value. [Combed], one per value asked."""
        allowed = {slot.name for slot, _group in self._asked(parameter)}
        slots = [slot for slot in slots if slot.name in allowed]
        out = []
        for claim in claims:
            if coordinates is not None:
                asked = [name for name in coordinates
                         if name in {slot.name for slot in slots}]
            else:
                asked = open_of(claim, slots)
            if not asked:
                continue
            out.append(self.comb(document_id, parameter, source, slots,
                                 [claim], passages, pairs, budget,
                                 coordinates=asked if coordinates is not None
                                 else None, own=own, bases=bases,
                                 first=first))
        return out

    def comb(self, document_id: int, parameter, source, slots: list,
             claims: list, passages: dict, pairs: list,
             budget: Optional[int] = None, *,
             coordinates: Optional[list] = None, own: bool = False,
             bases: Optional[tuple] = None,
             first: Optional[list] = None,
             probes: Optional[dict] = None, split: bool = False,
             whole_table: int = 0,
             names_so_far: Optional[list] = None,
             title_page=None, settings: Optional[list] = None) -> Combed:
        """The coordinates of the one value *claims* holds, read from
        *source*, that its reading left open, asked in one conversation of
        their own: with *coordinates* those of *slots* whatever their state,
        else those still open. First each that the second reading asks once
        more with the sections around the value's place, then each that the
        rest of the plan can state, searched for one after another (module
        docstring). *own* shows *source* and its section in the first
        message, *bases* are the years a row may name by a word (instead of
        those of *pairs*), *first* passages listed before the hits of the
        first coordinate searched, *probes* the sentences the reading wrote
        to coordinates it found unstated ({coordinate: sentence}), which the
        search ranks with. *whole_table* is how many other values of the
        value's table take the answers (`taken_by`): the conversation shows
        the table and says so ("whole_table"). *names_so_far* are the names
        read in the plan so far for a coordinate asked that may name several
        things (`names_read`). With *split*, a value the reply states for
        several names of such a coordinate is one row per name
        (`reading.answers_each`, owner decision 2026-11-06), each a copy of
        the value's row in `Combed.made`; without it, as in a pass over a
        stored harvest that re-reads each stored row in place, the first
        name. *title_page* and *settings* are shown in the first message."""
        if len(claims) != 1:
            raise ValueError(f"a combing request shows one row, not "
                             f"{len(claims)}")
        order = list(passages.values())
        rows = [Row(label=row_label(0), item_index=0, claim=claims[0])]
        groups = groups_of(self.spec, slots)
        group_of = {slot.name: group for group, group_slots in groups
                    for slot in group_slots}
        ordered = [slot for group, group_slots in groups
                   for slot in in_group_order(group, group_slots)]
        if coordinates is not None:
            wanted = [slot for slot in ordered if slot.name in coordinates]
        else:
            opened = set(open_of(rows[0].claim, ordered))
            wanted = [slot for slot in ordered if slot.name in opened]
        origin = (source.owner_kind, source.owner_id)
        result = Combed(parameter.uri, origin, len(rows), len(wanted),
                        table_rows=whole_table)
        if not wanted:
            return result
        if coordinates is not None:
            # Asked afresh: what an older question read there stands no
            # more.
            for slot in wanted:
                rows[0].claim.pop(f"{slot.name}_state", None)
        around = around_of(source, passages, budget)
        parent = (around.owner_kind, around.owner_id) \
            if around is not None else origin
        bases = list(bases) if bases is not None else self.bases(pairs)
        probes = dict(probes or {})
        table = whole_table > 0
        near_slots = [slot for slot in wanted
                      if group_of[slot.name].asked_near([slot])]
        search_slots = [slot for slot in wanted
                        if group_of[slot.name].combed([slot])]
        near = near_of(source, order, budget) if near_slots else {}
        before = near.get("before")
        after = near.get("after")
        gathered = Gathered(
            seen={origin, parent} | {(s.owner_kind, s.owner_id)
                                     for s in near.values()},
            cursor={"next": (after.owner_kind, after.owner_id)
                    if after is not None else origin,
                    "previous": (before.owner_kind, before.owner_id)
                    if before is not None else parent},
            rank=(partial(self.rank, document_id)
                  if self.rank is not None else None))
        if own:
            # Shown, not listed: a pass over a stored harvest reads the
            # value's passage again, and its section with it.
            gathered.seen -= {origin, parent}
            for shown in [source] + ([around] if around is not None else []):
                gathered._show(shown, (shown.text or "")[:budget or None])
        beside = [piece for piece in (title_page, table_before_of(source))
                  if piece is not None and (piece.text or "").strip()]
        settled = [one for one in settings or () if isinstance(one, dict)]
        setting_pieces = settings_evidence(settled, passages)
        # What the value's own place is: a find quoted from it needs no
        # check (owner decision 2026-11-07).
        own_places = {origin, parent} | {(s.owner_kind, s.owner_id)
                                         for s in heading_of(source)}
        place_judge = Judge(self.check, document_id, check_shown(
            source, parameter), own_places, source, None, passages, budget,
            result) if self.check is not None else None

        def shown_now(row: Row) -> list:
            # Whatever the conversation showed of the plan may be quoted
            # (owner decision 2026-11-05), each piece under the passage it
            # was shown with.
            return ([source] + ([around] if around is not None else [])
                    if table else []) \
                + heading_of(source) \
                + shown_as(source, lookup.title_of(source)) \
                + shown_as(source, row.claim.get("quote")) \
                + answers_evidence(row.claim, passages) \
                + beside + setting_pieces + list(near.values()) \
                + gathered.evidence(passages)

        def coordinate_of(slot, unstated: bool) -> dict:
            # The coordinate as the conversation asks it: its question and
            # list, where a plan prints it, and for a year the plan's base
            # and target years.
            return {slot.name: {**coordinate_shown(slot, unstated=unstated),
                                "where": group_of[slot.name].where,
                                **years_of(bases, [slot])}}

        def row_shown(row: Row) -> dict:
            return {**shown_value(row.claim),
                    "known": self.known(row.claim, [s.name for s in wanted]),
                    "open": [slot.name for slot in wanted
                             if row.claim.get(f"{slot.name}_state") != READ]}
        value = rows[0].claim
        base = {
            "parameter": {"key": parameter.uri, "label": parameter.label,
                          "definition": parameter.description},
            "passage": {"kind": source.owner_kind,
                        "title": lookup.title_of(source),
                        "section": (source.provenance or {}).get(
                            "section_title")},
            **({"title_page": title_page.text}
               if title_page is not None and (title_page.text or "").strip()
               else {}),
            **({"table_before": table_before_of(source).text}
               if table_before_of(source) is not None else {}),
            **({"settings": settings_shown(settled)} if settled else {}),
            **({"source": source_shown(source), "whole_table": True}
               if table else {}),
            **({"names": list(names_so_far)} if names_so_far else {}),
            "value": {**shown_value(value),
                      **({"unit": value.get(f"{UNIT}_raw")
                          or value.get(UNIT)}
                         if value.get(f"{UNIT}_raw") or value.get(UNIT)
                         else {})},
            "read": answers_shown(value)}
        # The first message shows all the gathering has; each later one
        # what is new since the answer it follows.
        talk = {"thread": Thread(), "mark": (0, 0, 0)}
        # The finds the check turned, by coordinate, and those told already.
        turned: dict = {}
        told_turned: set = set()

        def send(first_shows: dict, follow: Optional[dict], shape: dict,
                 example: dict):
            """One message of the conversation: its first, showing *base*
            and *first_shows*, or one after the answer that stands,
            carrying *follow*."""
            thread = talk["thread"]
            if thread.begun:
                reply = self.ask(None, shape, document_id, source, group=None,
                                 example=example, thread=thread,
                                 follow=follow)
            else:
                reply = self.ask({**base, **first_shows}, shape, document_id,
                                 source, group=None, example=example,
                                 thread=thread, follow=None)
            if isinstance(reply, dict):
                talk["mark"] = gathered.mark()
            return reply

        def anew() -> None:
            # The conversation outgrew the model's window: the next
            # coordinate begins a new one, with the answers so far.
            talk["thread"] = Thread()
            base["read"] = answers_shown(rows[0].claim)
            result.anew += 1

        def judged(slot, reply) -> dict:
            # Each find quoted from a passage other than the value's own
            # place is asked about once per quote (`reading.Judge`); one the
            # check says "no" to is taken out, and what follows says so.
            if place_judge is None or not isinstance(reply, dict):
                return reply
            kept, out = turned_out(reply, [slot], place_judge,
                                   shown_now(rows[0]), row_shown(rows[0]))
            for name, answers in out.items():
                turned[name] = say(NOT_ABOUT, answer=answers[0]
                                   if len(answers) == 1 else answers)
            return kept

        def fresh_turned() -> list:
            told = [{"coordinate": name, "what": why}
                    for name, why in turned.items()
                    if (name, why) not in told_turned]
            told_turned.update((entry["coordinate"], entry["what"])
                               for entry in told)
            return told

        def settle(slot, reply: dict, window: tuple, not_in_quote: str,
                   search: bool) -> tuple:
            """*reply*'s answer for *slot* onto the rows it makes, one per
            name where the coordinate may name several (with *split*):
            ({row label: [corrections]} of what the check refused, {row
            label: the answer it got})."""
            replies = answers_each(reply, [slot])
            targets = [rows[0]] + [self._another(rows, wanted)
                                   for _ in (replies[1:] if split else ())]
            corrections: dict = {}
            given: dict = {}
            for row, answer in zip(targets, replies):
                given[row.label] = answer
                entry = answer.get(slot.name) if isinstance(answer, dict) \
                    else None
                if search and not found(entry):
                    continue
                if isinstance(entry, dict) and isinstance(answer, dict):
                    probe = entry.get("probe")
                    if isinstance(probe, str) and probe.strip():
                        probes[slot.name] = probe.strip()
                if not isinstance(entry, dict):
                    if isinstance(answer, dict) and slot.name in answer:
                        corrections[row.label] = [{
                            "coordinate": slot.name,
                            "what": unanswered_what(answer, slot.name)}]
                    continue
                got = merge_field([row], shown_now(row), slot,
                                  {"answers": {row.label: answer_of(entry)}},
                                  window=window, bases=bases,
                                  not_shown=NOT_SHOWN,
                                  not_in_quote=not_in_quote)
                refused = [{"coordinate": slot.name,
                            "what": failure.get("reason")}
                           for failure in got["failed"]]
                if refused and slot.name not in turned:
                    corrections[row.label] = refused
            return corrections, given

        def corrected(slot, corrections: dict, given: dict, window: tuple,
                      not_in_quote: str, shape: dict, example: dict,
                      search: bool) -> None:
            # ONE message after the answer for every row it made, naming
            # each refused name with its quote; each answer goes to the row
            # of its name, a changed name to the next row still open, a
            # further name to a row of its own (owner decisions 2026-11-07).
            if not corrections:
                return
            told = told_once(corrections, given, [slot],
                             named=len(rows) > 1)
            result.corrected += len(told)
            result.asked += 1
            again = send({}, {CORRECTIONS: told + fresh_turned()}, shape,
                         example)
            if not isinstance(again, dict):
                return
            again = judged(slot, spread(again, [slot]))
            for target, answer, names in routed(
                    answers_each(again, [slot]), rows, corrections, given,
                    [slot]):
                if target is None:
                    if not split:
                        continue
                    target = self._another(rows, wanted)
                entry = answer.get(slot.name) \
                    if isinstance(answer, dict) else None
                if slot.name not in names or not isinstance(entry, dict) \
                        or (search and not found(entry)):
                    continue
                target.claim.pop(f"{slot.name}_state", None)
                merge_field([target], shown_now(target), slot,
                            {"answers": {target.label: answer_of(entry)}},
                            window=window, bases=bases, not_shown=NOT_SHOWN,
                            not_in_quote=not_in_quote)

        # -- the second reading --------------------------------------------
        def shut(slot) -> bool:
            # A coordinate after one that read the value as no value of its
            # parameter (`fields.closed`) is not asked: never asked, as in
            # the reading (owner decisions 2026-11-07).
            before = ordered[:ordered.index(slot)]
            gone = [row for row in rows if fields.closed(before, row.claim)]
            for row in gone:
                if row.claim.get(f"{slot.name}_state") != READ:
                    row.claim[f"{slot.name}_state"] = fields.OUT_OF_SLICE
            return len(gone) == len(rows)

        near_window = ("table", 1) if table else ("near", 1)
        for slot in (near_slots if near else ()):
            if rows[0].claim.get(f"{slot.name}_state") == READ or shut(slot):
                continue
            shows = {**({key: piece.text for key, piece in near.items()}),
                     COORDINATES: coordinate_of(slot, unstated=True),
                     **gathered.context()}
            follow = {COORDINATES: coordinate_of(slot, unstated=True)}
            shape, example = near_response_format([slot]), near_example([slot])
            reply = send(shows, follow, shape, example)
            result.asked += 1
            result.near += 1
            if not isinstance(reply, dict) and talk["thread"].begun:
                # The conversation outgrew the model's window: the
                # coordinate is asked again in a new one, with the answers
                # so far, as the search asks its coordinate again.
                anew()
                reply = send(shows, None, shape, example)
                result.asked += 1
                result.near += 1
            if not isinstance(reply, dict):
                # Still unread. Where no search comes after it, the
                # coordinate is open because of the run, not the plan.
                if slot not in search_slots:
                    for row in rows:
                        if row.claim.get(f"{slot.name}_state") != READ:
                            row.claim[f"{slot.name}_state"] = EXHAUSTED
                            result.exhausted += 1
                continue
            reply = judged(slot, spread(reply, [slot]))
            for row in rows:
                row.claim.pop(f"{slot.name}_state", None)
            corrections, given = settle(slot, reply, near_window,
                                        "or_unstated", search=False)
            corrected(slot, corrections, given, near_window, "or_unstated",
                      shape, example, search=False)
            for row in rows:
                if not row.claim.get(f"{slot.name}_state"):
                    row.claim[f"{slot.name}_state"] = UNANSWERED
            result.near_read += sum(
                1 for row in rows
                if row.claim.get(f"{slot.name}_state") == READ)

        # -- the search, one coordinate after another -----------------------
        ranking_end = {"end": False}
        listed_first = {"done": False}
        for slot in search_slots:
            if all(row.claim.get(f"{slot.name}_state") == READ
                   for row in rows) or shut(slot):
                continue
            sentence = probes.get(slot.name)
            ranked = self.rank(document_id, [sentence],
                               set(gathered.seen)) \
                if sentence and self.rank is not None else []
            listed = []
            if not listed_first["done"]:
                listed = [s for s in first or ()
                          if (s.owner_kind, s.owner_id)
                          not in gathered.listed()]
                listed_first["done"] = True
            taken = {(s.owner_kind, s.owner_id) for s in listed}
            listed += shown_hits([s for s in ranked
                                  if (s.owner_kind, s.owner_id) not in taken
                                  and (s.owner_kind, s.owner_id)
                                  not in gathered.listed()])
            result.hits += gathered.list_hits(
                [((hit.owner_kind, hit.owner_id), lookup.title_of(hit),
                  first_line(hit)) for hit in listed])
            # Without a list the model searches itself at once.
            gets = FIRST_GETS if listed else GETS
            example = comb_example([slot])
            shows = {COORDINATES: coordinate_of(slot, unstated=False),
                     **gathered.since(talk["mark"])}
            follow = dict(shows)
            reply = send(shows, follow, comb_response_format([slot], gets),
                         example)
            result.asked += 1
            if not isinstance(reply, dict) and talk["thread"].begun:
                anew()
                reply = send({COORDINATES: coordinate_of(slot,
                                                         unstated=False),
                              **gathered.context()}, None,
                             comb_response_format([slot], gets), example)
                result.asked += 1
            if not isinstance(reply, dict):
                # Still open with the plan not searched: a finding about the
                # run.
                for row in rows:
                    if row.claim.get(f"{slot.name}_state") != READ:
                        row.claim[f"{slot.name}_state"] = EXHAUSTED
                        result.exhausted += 1
                continue
            # What the search lists on from when a round asks for nothing
            # new and leaves the coordinate unfound (owner decision
            # 2026-11-06: the search runs empty): the ranking of its
            # sentence, or the plan in its order where there is none.
            ranking = ranked or [s for s in order
                                 if (s.owner_kind, s.owner_id)
                                 not in {origin, parent}]
            ranking_end["end"] = False
            label = rows[0].label

            def ask_more(slot=slot):
                follow = {**gathered.since(talk["mark"])}
                told = fresh_turned()
                if told:
                    follow[CORRECTIONS] = told
                if not follow:
                    return None
                return as_rows(spread(send({}, follow, comb_response_format(
                    [slot]), comb_example([slot])), [slot]), label)

            def next_passages(reply, slot=slot, ranking=ranking) -> bool:
                # A find the check turns is no find: the search goes on
                # (owner decision 2026-11-07).
                entry = entry_of(reply, label)
                kept = judged(slot, {key: value for key, value in
                                     entry.items() if key != "row"})
                if found(kept.get(slot.name)):
                    return False
                page = shown_hits([s for s in ranking
                                   if (s.owner_kind, s.owner_id)
                                   not in gathered.listed()])
                if not page:
                    ranking_end["end"] = True
                    return False
                result.hits += gathered.list_hits(
                    [((s.owner_kind, s.owner_id), lookup.title_of(s),
                      first_line(s)) for s in page])
                result.listed += 1
                return True

            rowed = as_rows(spread(reply, [slot]), label)
            rowed, more = gather(ask_more, rowed, gathered, order, passages,
                                 budget, then=next_passages)
            result.asked += more
            entry = {key: value for key, value in entry_of(
                rowed, label).items() if key != "row"}
            unfound = entry.get(slot.name)
            entry = judged(slot, entry)
            for row in rows:
                row.claim.pop(f"{slot.name}_state", None)
            corrections, given = settle(slot, entry, ("retrieval", 1),
                                        NOT_IN_QUOTE, search=True)
            corrected(slot, corrections, given, ("retrieval", 1),
                      NOT_IN_QUOTE, comb_response_format([slot]),
                      comb_example([slot]), search=True)
            empty = ranking_end["end"] and not gathered.unfit
            for row in rows:
                if row.claim.get(f"{slot.name}_state"):
                    continue
                if row.label in corrections:
                    row.claim[f"{slot.name}_state"] = UNANSWERED
                elif empty:
                    row.claim[f"{slot.name}_state"] = SAID_UNSTATED
                    noticed = unfound.get("value_raw") \
                        if isinstance(unfound, dict) else None
                    if isinstance(noticed, str) and noticed.strip():
                        row.claim.setdefault(f"{slot.name}_seen",
                                             noticed.strip())
                else:
                    row.claim[f"{slot.name}_state"] = EXHAUSTED
                    result.exhausted += 1
            if gathered.unfit:
                anew()
                gathered.unfit = False

        # A coordinate the conversation never reached keeps what the reading
        # left; one it asked and nothing answered is unanswered.
        for row in rows:
            for slot in wanted:
                if not row.claim.get(f"{slot.name}_state"):
                    row.claim[f"{slot.name}_state"] = UNANSWERED
        result.made = rows[1:]
        result.rows = len(rows)
        result.fetched = len(gathered.sources)
        result.searched = sum(1 for listed in gathered.hits
                              if "pattern" in listed or "similar" in listed)
        result.missed = len(gathered.missed)
        result.filled = sum(1 for row in rows for slot in wanted
                            if row.claim.get(f"{slot.name}_state") == READ)
        self._traced(document_id, result)
        return result

    @staticmethod
    def _another(rows: list, slots: list) -> Row:
        """A row of its own for a further name an answer gives (owner
        decision 2026-11-07): a copy of the value's row with the coordinates
        that may name several things open again, appended to *rows*."""
        first = rows[0]
        clone = Row(label=row_label(len(rows)), item_index=first.item_index,
                    claim=copy.deepcopy(first.claim))
        for slot in slots:
            if several(slot):
                for suffix in COORDINATE_KEYS:
                    clone.claim.pop(f"{slot.name}{suffix}", None)
        rows.append(clone)
        return clone

    def _traced(self, document_id: int, result: Combed) -> None:
        if self.trace is not None:
            self.trace("comb", document_id, parameter=result.parameter,
                       kind=result.owner[0], owner=result.owner[1],
                       rows=result.rows, open=result.open,
                       filled=result.filled, asked=result.asked,
                       near=result.near, near_read=result.near_read,
                       hits=result.hits, fetched=result.fetched,
                       searched=result.searched, missed=result.missed,
                       corrected=result.corrected,
                       exhausted=result.exhausted, listed=result.listed,
                       **({"anew": result.anew} if result.anew else {}),
                       **({"table_rows": result.table_rows}
                          if result.table_rows else {}),
                       **({"judged": result.judged, "turned": result.turned}
                          if result.judged else {}))
