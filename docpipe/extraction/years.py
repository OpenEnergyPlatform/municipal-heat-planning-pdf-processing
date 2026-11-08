"""
years.py: A plan's own years, asked once per plan: the year it takes its own
state in and the year of its target (owner decision 2026-11-06).

A value whose passage names the plan's state by the plan's word ("Basisjahr",
"Ist-Zustand", "Zieljahr") and prints no year takes one of these years
(`pipeline.named_year`). They came from the survey's pairs of single pages,
and a profile sheet's pair "Bestand 2040" put 2030 to 2045 among the base
years. One request per plan now asks for them, each with a quote that prints
it; the pairs of single pages no longer count.

The request lists the passages the survey found a pair of either state in,
else the plan's first passages, and has the combing's tools
(`reading.Gathered`): it reads what it asks for, and a round that asks for
nothing new while a state has no year gets the next passages of the plan,
until every passage was listed. Each year is checked as any coordinate is:
its quote stands in what the request showed, is long enough, and prints the
year; what fails is told once, by its state.

Author: Felix Vossel
"""
from __future__ import annotations

from functools import partial
from typing import Callable, Optional

from . import fields, lookup
from .pipeline import YEAR_STATES, answer_in_quote, named_years, year_in_range
from .reading import Gathered, first_line, gather, more_schema, shown_hits
from .thread import CORRECTIONS, Thread
from .verify import MIN_QUOTE_CHARS, quote_in
from .wording import say

YEARS_PROMPT_ID = "extraction/years"
# The fields of the messages that follow an answer (owner decisions
# 2026-11-07): the rounds are one conversation, each later one bringing what
# is new since (`reading.Gathered.since`) and what was wrong.
FOLLOWS = ("more", "hits", "not_found", CORRECTIONS)

# What the example of the request asks of the rest of the plan, as the
# combing's example does.
MORE_EXAMPLE = [{"get": "hit", "id": "H2"}]


def response_format() -> dict:
    """The years of each state, each a year and the quote that prints it,
    an empty list where the plan names none, and what the reply asks of the
    rest of the plan."""
    year = {"type": "object",
            "properties": {"value": {"type": "integer"},
                           "quote": {"type": "string"}},
            "required": ["value", "quote"], "additionalProperties": False}
    properties = {key: {"type": "array", "items": year}
                  for key in YEAR_STATES.values()}
    properties["more"] = more_schema()
    schema = {"type": "object", "properties": properties,
              "required": list(YEAR_STATES.values()),
              "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "years_reply", "schema": schema}}


def example() -> dict:
    """The reply as the prompt's example shows it: a year of each state with
    its quote, and an ask for more, in the order of `response_format`. A
    year is its placeholder, never a year the model could copy (owner
    decision 2026-11-07: "mach das Beispiel mit YYYY")."""
    return {**{key: [{"value": fields.YEAR, "quote": "..."}]
               for key in YEAR_STATES.values()},
            "more": [dict(ask) for ask in MORE_EXAMPLE]}


def found_all(reply) -> bool:
    """Does *reply* name a year of every state?"""
    return isinstance(reply, dict) and all(
        isinstance(reply.get(key), list) and reply[key]
        for key in YEAR_STATES.values())


class PlanYears:
    """(document_id, passages, pairs, budget) -> the plan's base and target
    years as `pipeline.named_years` gives them ({"state", "axis", "year",
    "quote", "source", "index"}), [] where none holds.

    *ask(payload, document_id, thread, follow)* is one message of a
    conversation (`thread.Thread`): the first shows *payload*, a later one
    carries *follow*, what is new since the answer it follows (`FOLLOWS`,
    owner decisions 2026-11-07); the reply as a dict, CUT, or None.
    *frame_slots* are the coordinates the survey reads per passage, one of
    them the year; *states* what the profile says makes a pair of the survey
    that state (`runner.year_states_of`), which only says where the request
    starts to look. *rank(document_id, probes, exclude)* is the plan best
    first for a sentence ("similar"), None where the run ranks nothing.
    """

    def __init__(self, ask: Callable, frame_slots: list,
                 states: Optional[dict], *, rank: Optional[Callable] = None,
                 trace=None):
        self.ask = ask
        self.frame_slots = list(frame_slots)
        self.slot = next(slot for slot in frame_slots
                         if slot.kind == fields.NUMBER)
        self.states = states or {}
        self.rank = rank
        self.trace = trace

    def first(self, order: list, passages: dict, pairs: list) -> list:
        """The passages the survey found a pair of either state in, in the
        plan's order; the plan's first passages where it found none."""
        cited = {tuple(entry["source"]) for entry in named_years(
            pairs, self.frame_slots, self.states)}
        listed = [p for p in order if (p.owner_kind, p.owner_id) in cited]
        return shown_hits(listed or order)

    def checked(self, reply, evidence: list) -> tuple:
        """([named year], [correction]) of a reply: each year whose quote
        stands in what the request showed, is long enough and prints it; one
        correction per year that does not, by its state."""
        out, wrong, seen = [], [], set()
        for state, key in YEAR_STATES.items():
            for entry in (reply or {}).get(key) or ():
                if not isinstance(entry, dict):
                    continue
                value, quote = entry.get("value"), entry.get("quote")
                why, source = None, None
                if (not isinstance(value, int) or isinstance(value, bool)
                        or not year_in_range(value)):
                    why = say("frame_not_a_year", slot=self.slot.name,
                              given=value)
                elif not isinstance(quote, str) \
                        or len(quote.strip()) < MIN_QUOTE_CHARS:
                    why = say("quote_too_short", minimum=MIN_QUOTE_CHARS)
                else:
                    source = next((s for s in evidence
                                   if quote_in(s.text or "", quote)), None)
                    if source is None:
                        why = say("quote_not_shown")
                    elif not answer_in_quote(self.slot, value, None, quote):
                        why = say("year_not_in_quote", given=value,
                                  quote=quote.strip()[:80])
                if why is not None:
                    wrong.append({"state": key, "value": value,
                                  "quote": quote, "what": why})
                    continue
                if (state, value) in seen:
                    continue
                seen.add((state, value))
                out.append({"state": state, "axis": self.slot.name,
                            "year": value, "quote": quote.strip(),
                            "source": [source.owner_kind, source.owner_id],
                            "index": len(out)})
        return out, wrong

    def __call__(self, document_id: int, passages: dict, pairs: list,
                 budget: Optional[int] = None) -> list:
        order = list(passages.values())
        if not order:
            return []
        listed = self.first(order, passages, pairs)
        start = (listed[0].owner_kind, listed[0].owner_id)
        gathered = Gathered(seen=set(), cursor={"next": start,
                                                "previous": start},
                            rank=(partial(self.rank, document_id)
                                  if self.rank is not None else None))
        hits = gathered.list_hits([((s.owner_kind, s.owner_id),
                                    lookup.title_of(s), first_line(s))
                                   for s in listed])
        asked = 0
        thread = Thread()
        # What the conversation has shown of the gathering.
        shown = {"mark": gathered.mark()}

        def ask(corrections: Optional[list] = None):
            # The first message shows the first hits; each later one follows
            # the answer before it with what is new since and what was
            # wrong (owner decisions 2026-11-07).
            nonlocal asked
            if not thread.begun:
                payload, follow = gathered.context(), None
            else:
                payload = None
                follow = {**gathered.since(shown["mark"]),
                          **({CORRECTIONS: corrections}
                             if corrections else {})}
                if not follow:
                    return None
            asked += 1
            reply = self.ask(payload, document_id, thread, follow)
            if isinstance(reply, dict):
                shown["mark"] = gathered.mark()
            return reply

        def next_passages(reply) -> bool:
            nonlocal hits
            if found_all(reply):
                return False
            seen = gathered.listed()
            page = shown_hits([s for s in order
                               if (s.owner_kind, s.owner_id) not in seen])
            if not page:
                return False
            hits += gathered.list_hits([((s.owner_kind, s.owner_id),
                                         lookup.title_of(s), first_line(s))
                                        for s in page])
            return True

        reply = ask()
        years: list = []
        refused = 0
        if isinstance(reply, dict):
            reply, _more = gather(ask, reply, gathered, order, passages,
                                  budget, then=next_passages)
            evidence = gathered.evidence(passages)
            years, wrong = self.checked(reply, evidence)
            refused = len(wrong)
            if wrong:
                again = ask(wrong)
                if isinstance(again, dict):
                    more, _ = self.checked(again, gathered.evidence(passages))
                    held = {(y["state"], y["year"]) for y in years}
                    years += [y for y in more
                              if (y["state"], y["year"]) not in held]
                    for index, year in enumerate(years):
                        year["index"] = index
        if self.trace is not None:
            self.trace("years", document_id,
                       base=[y["year"] for y in years if y["state"] == "base"],
                       target=[y["year"] for y in years
                               if y["state"] == "target"],
                       asked=asked, hits=hits,
                       fetched=len(gathered.sources), refused=refused)
        return years
