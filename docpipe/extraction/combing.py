"""
combing.py: The coordinates the reading left open, looked for in the rest of
the plan. Step 4 of the rebuilt harvest (owner decisions 2026-11-04).

The reading asks a value's coordinates in its own passage and the text
around it, and may fetch more of the plan itself. What is still open after it
(a coordinate the passage does not state, one whose answer did not hold, one
no reply answered) is looked for here, per passage and parameter: one search
with the passage's context (owner decision 2026-10-22: its title, what its
rows have read in the plan's words, what is asked). The best sections, tables
and figures of that search are shown as a list of titles and first lines, and
the model fetches what it wants to read with the reading's own tools: a hit
by its id, the next or the previous section, a table or figure by its
placeholder, a pattern. It answers each open coordinate of each row with its
quote, or that the plan does not state it.

Nothing is checked here. Every answer goes through `merge_field`, and what it
refuses is asked once more with the reason. A coordinate this request leaves
without an answer ends `unanswered`; one whose request no longer fits the
model's window ends `exhausted`; `unstated` is now a finding about the plan.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Callable, Optional

from . import lookup
from .fields import EXHAUSTED, READ, SAID_UNSTATED, UNANSWERED, UNBACKED
from .pipeline import Row, mark_unanswered, merge_field, row_label
from .reading import (Gathered, answer_of, answer_schema, around_of,
                      coordinate_shown, first_line, gather, more_schema,
                      slots_of, years_of)
from .wording import say

COMB_PROMPT_ID = "extraction/comb"

# What the reading leaves for this step.
OPEN = (SAID_UNSTATED, UNBACKED, UNANSWERED)

# The hits of one search the request shows, per kind (owner decision
# 2026-11-04: the best 15 sections, 20 tables and 20 figures).
SHOWN = {"section": 15, "table": 20, "figure": 20}


def open_of(claim: dict, slots: list) -> list:
    """The coordinates of a value still open after its reading."""
    return [slot.name for slot in slots
            if claim.get(f"{slot.name}_state") in OPEN]


def shown_hits(ranked: list) -> list:
    """The best of each kind of a ranked search, in its order (`SHOWN`)."""
    left = dict(SHOWN)
    out = []
    for source in ranked:
        if left.get(source.owner_kind, 0) > 0:
            left[source.owner_kind] -= 1
            out.append(source)
    return out


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


@dataclass
class Combed:
    """What combing the open coordinates of one passage came to."""
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


class Comber:
    """(document_id, reads, passages, pairs, budget) -> [Combed], one per
    passage and parameter whose read values have an open coordinate.

    *ask(payload, shape, document_id, source)* is one request: the reply as a
    dict, CUT, or None. *rank(document_id, probes, exclude)* is the plan's
    passages best first for the search sentences *probes*
    (`runner.make_more_sources`), *probes(rows, asked, owner_of, label)* the
    sentence of a passage (`runner.context_probes`), *known(claim, asked)*
    what a row has read in the plan's words (`runner.row_context`).
    """

    def __init__(self, spec, ask: Callable, rank: Callable,
                 probes: Callable, known: Callable, *,
                 bases: Optional[Callable] = None, pool=None, trace=None):
        self.spec = spec
        self.ask = ask
        self.rank = rank
        self.probes = probes
        self.known = known
        self.bases = bases or (lambda pairs: [])
        self.pool = pool
        self.trace = trace

    def __call__(self, document_id: int, reads: list, passages: dict,
                 pairs: list, budget: Optional[int] = None) -> list:
        groups: dict = collections.OrderedDict()
        for read in reads:
            source = read.batch.items[0].source
            parameter = read.batch.parameter
            slots = slots_of(self.spec, parameter)
            for claim in read.claims:
                if open_of(claim, slots):
                    key = (parameter.uri, source.owner_kind, source.owner_id)
                    groups.setdefault(key, (parameter, source, slots,
                                            []))[3].append(claim)
        jobs = list(groups.values())

        def one(job):
            parameter, source, slots, claims = job
            return self.comb(document_id, parameter, source, slots, claims,
                             passages, pairs, budget)
        if self.pool is None:
            return [one(job) for job in jobs]
        return list(self.pool.map(one, jobs))

    def comb(self, document_id: int, parameter, source, slots: list,
             claims: list, passages: dict, pairs: list,
             budget: Optional[int] = None) -> Combed:
        """The open coordinates of *claims*, values of *parameter* read in
        *source*, answered in place."""
        rows = [Row(label=row_label(i), item_index=0, claim=claim)
                for i, claim in enumerate(claims)]
        opened = {row.label: open_of(row.claim, slots) for row in rows}
        asked = [slot for slot in slots
                 if any(slot.name in names for names in opened.values())]
        names = [slot.name for slot in asked]
        origin = (source.owner_kind, source.owner_id)
        result = Combed(parameter.uri, origin, len(rows),
                        sum(len(names) for names in opened.values()))
        around = around_of(source, passages, budget)
        parent = (around.owner_kind, around.owner_id) \
            if around is not None else origin
        probes = self.probes(rows, names, {row.label: source for row in rows},
                             parameter.label)
        ranked = self.rank(document_id, probes, {origin, parent}) \
            if probes else []
        gathered = Gathered(seen={origin, parent},
                            cursor={"next": origin, "previous": parent})
        result.hits = gathered.list_hits(
            [((hit.owner_kind, hit.owner_id), lookup.title_of(hit),
              first_line(hit)) for hit in shown_hits(ranked)],
            query=" | ".join(probes))
        bases = self.bases(pairs)
        base = {
            "passage": {"kind": source.owner_kind,
                        "title": lookup.title_of(source),
                        "section": (source.provenance or {}).get(
                            "section_title")},
            "parameter": {"key": parameter.uri, "label": parameter.label,
                          "definition": parameter.description},
            "rows": [{"row": row.label, "value": row.claim.get("value"),
                      "unit": row.claim.get("unit"),
                      "quote": row.claim.get("quote"),
                      "known": self.known(row.claim, names),
                      "open": opened[row.label]} for row in rows],
            "coordinates": {slot.name: coordinate_shown(slot)
                            for slot in asked},
            **years_of(bases, asked)}
        shape = comb_response_format(asked, [row.label for row in rows])

        def ask(corrections: Optional[list] = None):
            payload = {**base, **gathered.context()}
            if corrections:
                payload["corrections"] = corrections
            return self.ask(payload, shape, document_id, source)

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
        evidence = [source] + ([around] if around is not None else []) \
            + gathered.sources
        # This request answers the open coordinates afresh: what it leaves
        # without an answer is unanswered, not what the reading said.
        for row in rows:
            for name in opened[row.label]:
                row.claim.pop(f"{name}_state", None)
        failed = self._merged(rows, reply, asked, opened, evidence, bases)
        corrections = self._corrections(rows, failed, opened)
        if corrections:
            result.corrected = len(corrections)
            again = ask(corrections)
            result.asked += 1
            if isinstance(again, dict):
                self._merged(rows, again, asked, opened, evidence, bases)
        mark_unanswered(rows, asked)
        result.filled = sum(1 for row in rows for name in opened[row.label]
                            if row.claim.get(f"{name}_state") == READ)
        self._traced(document_id, result)
        return result

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
                       exhausted=result.exhausted)
