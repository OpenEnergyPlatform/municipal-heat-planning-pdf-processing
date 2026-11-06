"""
combing.py: The coordinates the reading left open, looked for in the rest of
the plan. Step 4 of the rebuilt harvest (owner decisions 2026-11-04).

The reading asks a value's coordinates in its own passage and the text
around it, and may fetch more of the plan itself. What is still open after it
(a coordinate the passage does not state, one whose answer did not hold, one
no reply answered) is looked for here, per value and group of the spec that
still has an open coordinate (owner decisions 2026-11-04 and 2026-11-05:
every request one task and one value), the group's words for where a plan
prints it shown. The search ranks the plan with the sentences the reading
wrote to the coordinates it found unstated, as the plan would print them
(owner decision 2026-11-05: HyDE, `Read.probes`), those of the coordinates
asked here; the best sections, tables and figures of that ranking are shown
as a list of titles and first lines. Where no coordinate asked has a
sentence, one whose answer did not hold or that no reply answered, the
request shows no list and the model searches itself (owner decision
2026-11-05), with the reading's own tools: a hit by its id, the next or the
previous section, a table or figure by its placeholder, a pattern, a
sentence of its own ("similar"). It answers each open coordinate it finds
with its quote and leaves out what it does not find: the combing offers no
"not stated" (owner decision 2026-11-06, after a probe in which the model
ended its search with it at once), and one the model writes all the same
is no answer (`found`).

A round that asks for nothing new while a coordinate is still unfound gets
the next passages of the ranking, as many of each kind as the first list,
or of the plan in its order where there is no ranking, until every passage
of the plan was listed (owner decision 2026-11-06: the search runs empty).
Only then is a coordinate no reply found `unstated`, a finding about the
plan; one whose request no longer fits the model's window before that ends
`exhausted`, a finding about the run.

Nothing is checked here. Every answer goes through `merge_field`, and what it
refuses is asked once more with the reason. Its quote may stand in whatever
the request showed of the plan (owner decision 2026-11-05): a passage the
model fetched, a hit's line or title, the title or heading of a passage, the
value's passage and its section, a wording the value has read. The
coordinate then cites the passage that piece was shown with. A coordinate
the reply names in another form than asked is asked for once more in the
form asked, and ends `unanswered` where that reply does not give it.

A pass over a stored harvest combs with the same requests
(`Comber.comb_groups`): the coordinates it names (*coordinates*) whatever
their state, one request per value and group, the value's own passage and
its section
shown first (*own*), since the reading that asked them there ran under an
older question, the years of the stored rows
(*bases*), and the passages a harvest before read the coordinate in listed
(*first*). A stored row carries no sentence, so the model searches the rest
of the plan itself.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import copy
from dataclasses import dataclass, field
from functools import partial
from typing import Callable, Optional

from . import lookup
from .fields import (EXHAUSTED, READ, SAID_UNSTATED, UNANSWERED, UNBACKED,
                     UNSTATED)
from .pipeline import Row, merge_field, row_label
from .reading import (SHOWN, Gathered, answer_of, answer_schema,
                      answers_each, around_of, coordinate_shown, entry_example,
                      first_line, gather, groups_of, heading_of, known_shown,
                      more_schema, several, shown_as, shown_hits, slots_of,
                      source_of, unanswered_what, years_of)
from .wording import say

COMB_PROMPT_ID = "extraction/comb"

# What a combing request tells of a quote that stands in nothing it showed,
# in the names of what it shows: "more", "hits", "passage", "row" (owner
# decision 2026-11-06).
NOT_SHOWN = "quote_not_shown"

# What the reading leaves for this step.
OPEN = (SAID_UNSTATED, UNBACKED, UNANSWERED)

# The hits of one search the request shows, per kind, are `reading.SHOWN`
# (owner decision 2026-11-04: the best 15 sections, 20 tables and 20
# figures), cut by `reading.shown_hits`; both are named here as before.
__all__ = ["COMB_PROMPT_ID", "OPEN", "SHOWN", "Comber", "Combed",
           "as_rows", "comb_example", "comb_response_format", "finds",
           "found", "open_of", "shown_corrections", "shown_hits"]

# What the example of a combing request asks of the rest of the plan, as the
# prompts' examples always showed it.
MORE_EXAMPLE = [{"get": "hit", "id": "H2"}]


def open_of(claim: dict, slots: list) -> list:
    """The coordinates of a value still open after its reading."""
    return [slot.name for slot in slots
            if claim.get(f"{slot.name}_state") in OPEN]


def comb_response_format(slots: list) -> dict:
    """The coordinates asked of the one row a request shows that the reply
    found, at the top of the reply with no wrapper and no row label (owner
    decision 2026-11-06), none required and none UNSTATED, and what the
    reply asks of the rest of the plan."""
    properties = {slot.name: answer_schema(slot, unstated=False)
                  for slot in slots}
    properties["more"] = more_schema()
    schema = {"type": "object", "properties": properties,
              "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "comb_reply", "schema": schema}}


def found(answer) -> bool:
    """Does *answer*, a reply's entry for one coordinate, name something: an
    answer that is not UNSTATED, alone or in a list? An entry the reply left
    out, one without a value, and UNSTATED name nothing: the combing does
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
    """*reply* (`as_rows`) as the combing reads it: each row's entries that
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
    """The reply of a combing request as its example shows it: exactly the
    coordinates this request asks, in its order, each read
    (`reading.entry_example`), then what it asks of the rest of the plan,
    as `comb_response_format` has them (owner decision 2026-11-06)."""
    return {**{slot.name: entry_example(slot) for slot in slots},
            "more": [dict(ask) for ask in MORE_EXAMPLE]}


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


def shown_corrections(corrections: list, label: str) -> Optional[dict]:
    """What a request asked again is told of its one row: the coordinates
    under "what", and where a correction names it the name and quote it was
    given; None where nothing was wrong with that row."""
    for correction in corrections or ():
        if correction.get("row") == label:
            return {key: value for key, value in correction.items()
                    if key != "row"}
    return None


def named_rows(corrections: list, given: dict, slots: list) -> list:
    """*corrections* ([{row, what}]) of rows a reply made of one value
    (`reading.answers_each`): a row asked again for one coordinate that
    named several things names the name it was given and its quote
    (*given*: {row: its reply entry}), so the request asks for that one."""
    by_name = {slot.name: slot for slot in slots if several(slot)}
    out = []
    for correction in corrections:
        entry = given.get(correction.get("row")) or {}
        names = [name for name in correction.get("what") or {}
                 if name in by_name and isinstance(entry.get(name), dict)]
        if len(names) == 1:
            answer = entry[names[0]]
            correction = {"row": correction["row"],
                          **{key: answer[key] for key in ("value", "quote")
                             if answer.get(key) not in (None, "")},
                          "what": correction["what"]}
        out.append(correction)
    return out


@dataclass
class Combed:
    """What combing the open coordinates of one value came to."""
    parameter: str
    owner: tuple
    rows: int
    open: int                     # coordinates open before
    filled: int = 0               # read by this step
    asked: int = 0
    hits: int = 0                 # hits of the search shown
    fetched: int = 0
    searched: int = 0
    missed: int = 0
    corrected: int = 0
    exhausted: int = 0
    listed: int = 0               # lists of the next passages the run added
    group: Optional[str] = None   # the group of the spec asked
    # rows made beside the value, one per further name it was stated for
    made: list = field(default_factory=list)


class Comber:
    """(document_id, reads, passages, pairs, budget) -> [Combed], one per
    read value and group of the spec with an open coordinate.

    *ask(payload, shape, document_id, source, group, example)* is one
    request: the reply as a dict, CUT, or None, *group* the name of the group
    of the spec it asks, for its trace, *example* the reply its prompt shows
    (`comb_example`). *rank(document_id, probes, exclude)* is the plan's
    passages best first for the search sentences *probes*
    (`runner.make_more_sources`): the reading's sentences, and the model's
    own under "similar". *known(claim, asked)* is what a row has read in the
    plan's words (`runner.row_context`).
    """

    def __init__(self, spec, ask: Callable, rank: Optional[Callable],
                 known: Callable, *, bases: Optional[Callable] = None,
                 pool=None, trace=None):
        self.spec = spec
        self.ask = ask
        self.rank = rank
        self.known = known
        self.bases = bases or (lambda pairs: [])
        self.pool = pool
        self.trace = trace

    def __call__(self, document_id: int, reads: list, passages: dict,
                 pairs: list, budget: Optional[int] = None) -> list:
        """One Combed per read value and group of the spec with a
        coordinate still open on it (owner decisions 2026-11-04 and
        2026-11-05: one value per request)."""
        jobs: list = []
        for read in reads:
            parameter = read.batch.parameter
            slots = slots_of(self.spec, parameter)
            for index, claim in enumerate(read.claims):
                # The passage the value is read from, which may be one its
                # round fetched (`reading.source_of`), and the sentences its
                # reading wrote to what it found unstated.
                source = source_of(read.batch, claim)
                probes = read.probes[index] \
                    if index < len(read.probes) else {}
                for group, group_slots in groups_of(self.spec, slots):
                    if open_of(claim, group_slots):
                        jobs.append((read, parameter, source, group,
                                     group_slots, claim, probes))

        def one(job):
            _read, parameter, source, group, group_slots, claim, probes = job
            return self.comb(document_id, parameter, source, group_slots,
                             [claim], passages, pairs, budget, group=group,
                             probes=probes, split=True)
        if self.pool is None:
            combed = [one(job) for job in jobs]
        else:
            combed = list(self.pool.map(one, jobs))
        # A value combed for several names is one row per name (owner
        # decision 2026-11-06): the rows made join their value's reading.
        for job, result in zip(jobs, combed):
            read, probes = job[0], job[-1]
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
        """`comb` once per value of *claims* and group of the spec that has
        something to ask of it: with *coordinates* the group's share of
        them, else a coordinate open on the value. [Combed], one per value
        and group asked."""
        out = []
        for claim in claims:
            for group, group_slots in groups_of(self.spec, slots):
                names = {slot.name for slot in group_slots}
                if coordinates is not None:
                    asked = [name for name in coordinates if name in names]
                    if not asked:
                        continue
                else:
                    asked = None
                    if not open_of(claim, group_slots):
                        continue
                out.append(self.comb(document_id, parameter, source,
                                     group_slots, [claim], passages, pairs,
                                     budget, coordinates=asked, own=own,
                                     bases=bases, first=first, group=group))
        return out

    def comb(self, document_id: int, parameter, source, slots: list,
             claims: list, passages: dict, pairs: list,
             budget: Optional[int] = None, *,
             coordinates: Optional[list] = None, own: bool = False,
             bases: Optional[tuple] = None,
             first: Optional[list] = None, group=None,
             probes: Optional[dict] = None, split: bool = False) -> Combed:
        """The open coordinates of *claims*, values of *parameter* read in
        *source*, answered in place; with *coordinates* those of every row,
        open or not. *own* shows *source* and its section before the first
        request, *bases* are the years a row may name by a word (instead of
        those of *pairs*), *first* passages listed before the search's
        hits, *group* the group of the spec *slots* belong to, whose words
        for where a plan prints them the request shows, *probes* the
        sentences the reading wrote to coordinates it found unstated
        ({coordinate: sentence}), which the search ranks with. A round that
        asks for nothing new while a coordinate is unfound lists the next
        passages of that ranking, or of the plan in its order, until every
        passage was listed; a coordinate still unfound then is unstated,
        one whose request no longer fit before is exhausted. With
        *split*, a value the reply states for several names of a coordinate
        that may name several (`reading.several`) is one row per name
        (`reading.answers_each`, owner decision 2026-11-06), each a copy of
        the value's row in `Combed.made` and asked again on its own; without
        it, as in a pass over a stored harvest that re-reads each stored row
        in place, the first name.

        Each request shows one row (owner decision 2026-11-06): *claims* is
        one value's claim, and a row made for a further name is asked again
        on its own. The reply carries that row's answers at its top, with no
        row label (`comb_response_format`, `as_rows`)."""
        if len(claims) != 1:
            raise ValueError(f"a combing request shows one row, not "
                             f"{len(claims)}")
        rows = [Row(label=row_label(0), item_index=0, claim=claims[0])]
        if coordinates is not None:
            have = {slot.name for slot in slots}
            opened = {row.label: [name for name in coordinates
                                  if name in have] for row in rows}
        else:
            opened = {row.label: open_of(row.claim, slots) for row in rows}
        asked = [slot for slot in slots
                 if any(slot.name in names for names in opened.values())]
        names = [slot.name for slot in asked]
        origin = (source.owner_kind, source.owner_id)
        result = Combed(parameter.uri, origin, len(rows),
                        sum(len(names) for names in opened.values()),
                        group=group.name if group is not None else None)
        around = around_of(source, passages, budget)
        parent = (around.owner_kind, around.owner_id) \
            if around is not None else origin
        # The sentences of the coordinates asked here (owner decision
        # 2026-11-05: HyDE); without one no list is ranked and the model
        # searches itself.
        sentences = list(dict.fromkeys(
            (probes or {})[name] for name in names
            if (probes or {}).get(name)))
        ranked = self.rank(document_id, sentences, {origin, parent}) \
            if sentences else []
        gathered = Gathered(seen={origin, parent},
                            cursor={"next": origin, "previous": parent},
                            rank=(partial(self.rank, document_id)
                                  if self.rank is not None else None))
        if own:
            # Shown, not listed: the request reads the passage it asks for
            # again, and its section with it.
            gathered.seen -= {origin, parent}
            for shown in [source] + ([around] if around is not None else []):
                gathered._show(shown, (shown.text or "")[:budget or None])
        listed = [s for s in first or ()
                  if (s.owner_kind, s.owner_id) not in gathered.seen]
        taken = {(s.owner_kind, s.owner_id) for s in listed}
        listed += shown_hits([s for s in ranked
                              if (s.owner_kind, s.owner_id) not in taken])
        result.hits = gathered.list_hits(
            [((hit.owner_kind, hit.owner_id), lookup.title_of(hit),
              first_line(hit)) for hit in listed],
            **({"query": " | ".join(sentences)} if sentences else {}))
        bases = list(bases) if bases is not None else self.bases(pairs)
        knowns = {row.label: self.known(row.claim, names) for row in rows}

        def row_shown(row: Row) -> dict:
            return {"value": row.claim.get("value"),
                    "unit": row.claim.get("unit"),
                    "quote": row.claim.get("quote"),
                    "known": knowns[row.label],
                    "open": opened[row.label]}
        base = {
            "passage": {"kind": source.owner_kind,
                        "title": lookup.title_of(source),
                        "section": (source.provenance or {}).get(
                            "section_title")},
            "parameter": {"key": parameter.uri, "label": parameter.label,
                          "definition": parameter.description},
            "coordinates": {slot.name: coordinate_shown(slot, unstated=False)
                            for slot in asked},
            **({"where": group.where} if group is not None else {}),
            **years_of(bases, asked)}
        shape = comb_response_format(asked)
        example = comb_example(asked)

        def ask(corrections: Optional[list] = None,
                row: Optional[Row] = None):
            # One row per request: the value's own, or one asked again.
            row = row or rows[0]
            payload = {**base, "row": row_shown(row), **gathered.context()}
            told = shown_corrections(corrections, row.label)
            if told:
                payload["corrections"] = told
            return as_rows(self.ask(payload, shape, document_id, source,
                                    group=group.name if group is not None
                                    else None, example=example), row.label)

        reply = ask()
        result.asked = 1
        if not isinstance(reply, dict):
            # Still open with the plan not combed: a finding about the run.
            for row in rows:
                for name in opened[row.label]:
                    row.claim[f"{name}_state"] = EXHAUSTED
                    result.exhausted += 1
            self._traced(document_id, result)
            return result
        # What the search lists on from when a round asks for nothing new and
        # leaves a coordinate unfound (owner decision 2026-11-06: the search
        # runs empty): the ranking of the sentences, or the plan in its order
        # where there is none, as many of each kind as the first list.
        ranking = ranked or [s for s in passages.values()
                             if (s.owner_kind, s.owner_id) not in
                             {origin, parent}]
        about = {"query": " | ".join(sentences)} if ranked else {}
        listing = {"end": False}

        def next_passages(reply) -> bool:
            entry = entry_of(reply, rows[0].label)
            if all(found(entry.get(name)) for name in opened[rows[0].label]):
                return False
            listed = gathered.listed()
            page = shown_hits([s for s in ranking
                               if (s.owner_kind, s.owner_id) not in listed])
            if not page:
                listing["end"] = True
                return False
            result.hits += gathered.list_hits(
                [((s.owner_kind, s.owner_id), lookup.title_of(s),
                  first_line(s)) for s in page], **about)
            result.listed += 1
            return True

        reply, more = gather(ask, reply, gathered, list(passages.values()),
                             passages, budget, then=next_passages)
        result.asked += more
        result.fetched = len(gathered.sources)
        result.searched = sum(1 for listed in gathered.hits
                              if "pattern" in listed or "similar" in listed)
        result.missed = len(gathered.missed)
        # What the reply said of a coordinate it did not find, kept as the
        # wording the model saw where it gave one (`pipeline.merge_field`).
        unfound = entry_of(reply, rows[0].label)
        reply = finds(reply, asked)
        # Whatever the request showed of the plan may be quoted (owner
        # decision 2026-11-05), each piece under the passage it was shown
        # with: the value's passage and its section, their heading and
        # title, what the model fetched, the hits' lines and titles, and the
        # wordings the value has read.
        evidence = [source] + ([around] if around is not None else []) \
            + heading_of(source) + shown_as(source, lookup.title_of(source)) \
            + gathered.evidence(passages) + [
                one for row in rows
                for one in known_shown(row.claim, knowns[row.label],
                                       passages)]
        # This request answers the open coordinates afresh: what it leaves
        # without an answer is unanswered, not what the reading said.
        for row in rows:
            for name in opened[row.label]:
                row.claim.pop(f"{name}_state", None)

        reply, made = self._each(rows, reply, asked, opened, knowns, split)
        result.made = made
        failed = self._merged(rows, reply, asked, opened, evidence,
                              bases)
        corrections = self._corrections(rows, failed, opened, reply)
        if corrections and made:
            # One request per row asked again, showing that row only and
            # naming the name it was given.
            given = {entry.get("row"): entry for entry in reply["rows"]
                     if isinstance(entry, dict)}
            by_label = {row.label: row for row in rows}
            result.corrected = len(corrections)
            for correction in named_rows(corrections, given, asked):
                again = ask([correction], by_label[correction["row"]])
                result.asked += 1
                if isinstance(again, dict):
                    again, _ = self._each(rows, finds(again, asked), asked,
                                          opened, knowns, False)
                    self._merged(rows, again, asked, opened, evidence,
                                 bases)
        elif corrections:
            result.corrected = len(corrections)
            again = ask(corrections)
            result.asked += 1
            if isinstance(again, dict):
                again, _ = self._each(rows, finds(again, asked), asked,
                                      opened, knowns, False)
                self._merged(rows, again, asked, opened, evidence,
                             bases)
        self._ended(rows, opened, corrections, unfound,
                    listing["end"] and not gathered.unfit, result)
        result.filled = sum(1 for row in rows for name in opened[row.label]
                            if row.claim.get(f"{name}_state") == READ)
        self._traced(document_id, result)
        return result

    @staticmethod
    def _ended(rows: list, opened: dict, corrections: list, unfound: dict,
               empty: bool, result: Combed) -> None:
        """Every coordinate still without a state when the search ended: one
        asked again for its form, unanswered; any other unstated where the
        search listed every passage of the plan (*empty*), exhausted where
        a request no longer fit before (owner decision 2026-11-06). An
        unstated one keeps the wording the reply gave it (*unfound*, its
        entry before `finds`) as what the model saw."""
        again = {(correction["row"], name) for correction in corrections
                 for name in correction.get("what") or {}}
        for row in rows:
            for name in opened[row.label]:
                if row.claim.get(f"{name}_state"):
                    continue
                if (row.label, name) in again:
                    row.claim[f"{name}_state"] = UNANSWERED
                elif empty:
                    row.claim[f"{name}_state"] = SAID_UNSTATED
                    given = unfound.get(name)
                    noticed = given.get("value_raw") \
                        if isinstance(given, dict) else None
                    if isinstance(noticed, str) and noticed.strip():
                        row.claim.setdefault(f"{name}_seen", noticed.strip())
                else:
                    row.claim[f"{name}_state"] = EXHAUSTED
                    result.exhausted += 1

    @staticmethod
    def _each(rows: list, reply: dict, slots: list, opened: dict,
              knowns: dict, split: bool) -> tuple:
        """(*reply* with each row entry that names several things for a
        coordinate as one entry per name (`reading.answers_each`), [the rows
        made for them]): every further name on a copy of its row, appended
        to *rows*. Without *split*, the first name alone."""
        by_label = {row.label: row for row in rows}
        entries, made = [], []
        for entry in reply.get("rows") or ():
            label = entry.get("row") if isinstance(entry, dict) else None
            if label not in by_label:
                entries.append(entry)
                continue
            each = answers_each(entry, slots)
            entries.append(each[0])
            for one in (each[1:] if split else ()):
                row = by_label[label]
                copy_label = row_label(len(rows))
                clone = Row(label=copy_label, item_index=row.item_index,
                            claim=copy.deepcopy(row.claim))
                rows.append(clone)
                made.append(clone)
                opened[copy_label] = list(opened[label])
                knowns[copy_label] = knowns[label]
                entries.append({**one, "row": copy_label})
        return {**reply, "rows": entries}, made

    @staticmethod
    def _merged(rows: list, reply: dict, slots: list, opened: dict,
                evidence: list, bases: list) -> list:
        """The reply's answers onto the coordinates still open on each row;
        [(coordinate, failure)] of what the check refused."""
        entries: dict = {}
        for entry in reply.get("rows") or ():
            label = entry.get("row") if isinstance(entry, dict) else None
            if label in opened and label not in entries:
                entries[label] = entry
        failed = []
        for slot in slots:
            answers = {label: answer_of(entry[slot.name])
                       for label, entry in entries.items()
                       if slot.name in opened[label]
                       and isinstance(entry.get(slot.name), dict)}
            if not answers:
                continue
            got = merge_field(rows, evidence, slot, {"answers": answers},
                              window=("retrieval", 1), bases=bases,
                              not_shown=NOT_SHOWN)
            failed.extend((slot.name, failure) for failure in got["failed"])
        return failed

    @staticmethod
    def _corrections(rows: list, failed: list, opened: dict,
                     reply: dict) -> list:
        """[{row, what: {coordinate: reason}}] of the rows the check refused
        an answer of or *reply* (`finds`) named something on in another form
        than asked (`reading.unanswered_what`). A coordinate the reply left
        out is not asked for: the combing found nothing there (owner
        decision 2026-11-06)."""
        given = {entry.get("row"): entry for entry in reply.get("rows") or ()
                 if isinstance(entry, dict)}
        what: dict = collections.defaultdict(dict)
        for row in rows:
            entry = given.get(row.label) or {}
            for name in opened[row.label]:
                if not row.claim.get(f"{name}_state") and name in entry:
                    what[row.label][name] = unanswered_what(entry, name)
        for name, failure in failed:
            if failure.get("row") in opened:
                what[failure["row"]][name] = failure.get("reason")
        return [{"row": row.label, "what": what[row.label]}
                for row in rows if what.get(row.label)]

    def _traced(self, document_id: int, result: Combed) -> None:
        if self.trace is not None:
            self.trace("comb", document_id, parameter=result.parameter,
                       kind=result.owner[0], owner=result.owner[1],
                       rows=result.rows, open=result.open,
                       filled=result.filled, asked=result.asked,
                       hits=result.hits, fetched=result.fetched,
                       searched=result.searched, missed=result.missed,
                       corrected=result.corrected,
                       exhausted=result.exhausted, listed=result.listed,
                       group=result.group)
