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
sentence of its own ("similar"). It answers each open coordinate of the
value with its quote, or that the plan does not state it.

Nothing is checked here. Every answer goes through `merge_field`, and what it
refuses is asked once more with the reason. Its quote may stand in whatever
the request showed of the plan (owner decision 2026-11-05): a passage the
model fetched, a hit's line or title, the title or heading of a passage, the
value's passage and its section, a wording the value has read. The
coordinate then cites the passage that piece was shown with. A coordinate
this request leaves
without an answer ends `unanswered`; one whose request no longer fits the
model's window ends `exhausted`; `unstated` is now a finding about the plan.

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
from .fields import EXHAUSTED, READ, SAID_UNSTATED, UNANSWERED, UNBACKED
from .pipeline import Row, mark_unanswered, merge_field, row_label
from .reading import (SHOWN, Gathered, answer_of, answer_schema,
                      answers_each, around_of, coordinate_shown, first_line,
                      gather, groups_of, heading_of, known_shown, more_schema,
                      several, shown_as, shown_hits, slots_of, source_of,
                      years_of)
from .wording import say

COMB_PROMPT_ID = "extraction/comb"

# What the reading leaves for this step.
OPEN = (SAID_UNSTATED, UNBACKED, UNANSWERED)

# The hits of one search the request shows, per kind, are `reading.SHOWN`
# (owner decision 2026-11-04: the best 15 sections, 20 tables and 20
# figures), cut by `reading.shown_hits`; both are named here as before.
__all__ = ["COMB_PROMPT_ID", "OPEN", "SHOWN", "Comber", "Combed",
           "comb_response_format", "open_of", "shown_hits"]


def open_of(claim: dict, slots: list) -> list:
    """The coordinates of a value still open after its reading."""
    return [slot.name for slot in slots
            if claim.get(f"{slot.name}_state") in OPEN]


def comb_response_format(slots: list, labels: list) -> dict:
    """Each row of *labels* with every coordinate asked, and what the reply
    asks of the rest of the plan."""
    properties = {"row": {"enum": list(labels)}}
    properties.update({slot.name: answer_schema(slot) for slot in slots})
    entry = {"type": "object", "properties": properties,
             "required": ["row", *(slot.name for slot in slots)],
             "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"rows": {"type": "array", "items": entry},
                             "more": more_schema()},
              "required": ["rows"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "comb_reply", "schema": schema}}


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
    group: Optional[str] = None   # the group of the spec asked
    # rows made beside the value, one per further name it was stated for
    made: list = field(default_factory=list)


class Comber:
    """(document_id, reads, passages, pairs, budget) -> [Combed], one per
    read value and group of the spec with an open coordinate.

    *ask(payload, shape, document_id, source, group)* is one request: the
    reply as a dict, CUT, or None, *group* the name of the group of the spec
    it asks, for its trace. *rank(document_id, probes, exclude)* is the plan's
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
        ({coordinate: sentence}), which the search ranks with. With
        *split*, a value the reply states for several names of a coordinate
        that may name several (`reading.several`) is one row per name
        (`reading.answers_each`, owner decision 2026-11-06), each a copy of
        the value's row in `Combed.made` and asked again on its own; without
        it, as in a pass over a stored harvest that re-reads each stored row
        in place, the first name."""
        rows = [Row(label=row_label(i), item_index=0, claim=claim)
                for i, claim in enumerate(claims)]
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
            return {"row": row.label,
                    "value": row.claim.get("value"),
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
            "rows": [row_shown(row) for row in rows],
            "coordinates": {slot.name: coordinate_shown(slot)
                            for slot in asked},
            **({"where": group.where} if group is not None else {}),
            **years_of(bases, asked)}
        def ask(corrections: Optional[list] = None,
                shown: Optional[list] = None):
            payload = {**base, **gathered.context()}
            if shown is not None:
                payload["rows"] = shown
            if corrections:
                payload["corrections"] = corrections
            shape = comb_response_format(
                asked, [entry["row"] for entry in payload["rows"]])
            return self.ask(payload, shape, document_id, source,
                            group=group.name if group is not None else None)

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
        reply, more = gather(ask, reply, gathered, list(passages.values()),
                             passages, budget)
        result.asked += more
        result.fetched = len(gathered.sources)
        result.searched = len(gathered.hits) - (1 if result.hits else 0)
        result.missed = len(gathered.missed)
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
        corrections = self._corrections(rows, failed, opened)
        if corrections and made:
            # One request per row asked again, showing that row only and
            # naming the name it was given.
            given = {entry.get("row"): entry for entry in reply["rows"]
                     if isinstance(entry, dict)}
            by_label = {row.label: row for row in rows}
            result.corrected = len(corrections)
            for correction in named_rows(corrections, given, asked):
                again = ask([correction],
                            [row_shown(by_label[correction["row"]])])
                result.asked += 1
                if isinstance(again, dict):
                    again, _ = self._each(rows, again, asked, opened,
                                          knowns, False)
                    self._merged(rows, again, asked, opened, evidence,
                                 bases)
        elif corrections:
            result.corrected = len(corrections)
            again = ask(corrections)
            result.asked += 1
            if isinstance(again, dict):
                again, _ = self._each(rows, again, asked, opened, knowns,
                                      False)
                self._merged(rows, again, asked, opened, evidence,
                             bases)
        mark_unanswered(rows, asked)
        result.filled = sum(1 for row in rows for name in opened[row.label]
                            if row.claim.get(f"{name}_state") == READ)
        self._traced(document_id, result)
        return result

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
                              window=("retrieval", 1), bases=bases)
            failed.extend((slot.name, failure) for failure in got["failed"])
        return failed

    @staticmethod
    def _corrections(rows: list, failed: list, opened: dict) -> list:
        """[{row, what: {coordinate: reason}}] of the rows the check refused
        an answer of or the reply left a coordinate open on."""
        what: dict = collections.defaultdict(dict)
        for row in rows:
            for name in opened[row.label]:
                if not row.claim.get(f"{name}_state"):
                    what[row.label][name] = say("key_missing", key=name)
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
                       exhausted=result.exhausted, group=result.group)
