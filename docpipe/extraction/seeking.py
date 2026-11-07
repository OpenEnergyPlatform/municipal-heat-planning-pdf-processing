"""
seeking.py: A parameter the survey named no passage for, and whose walk down
the ranked list found no value, searched for by the model itself (owner
decision 2026-11-07, „genau wie Nachsuche: Erst Retrieval dann Agentisch“).

The walk reads the passages a search ranks for the parameter, one a round
(`surveyed.sought_walk`). Where its list ends without a value the check
takes, one conversation with the combing's tools (`reading.Gathered`) looks
for the passages that state one: it searches by pattern or by a sentence of
its own ("similar"), fetches hits, sections, tables and figures, and names
the passages it found by their ids. The passages the walk read are not
listed again, and the conversation ends where a round asks for nothing new.
Each passage it names is then read like any other (`reading.Reader`), so a
value it found is held to the same checks; naming a passage reads nothing by
itself. An id it names that no hit and no fetched passage of the
conversation has is told once.

Author: Felix Vossel
"""
from __future__ import annotations

from functools import partial
from typing import Callable, Optional

from . import lookup
from .reading import Gathered, gather, more_schema, parameter_shown
from .thread import CORRECTIONS, Thread
from .wording import say

SEEK_PROMPT_ID = "extraction/seek"
# The fields of the messages that follow an answer (owner decisions
# 2026-11-07): what the search fetched, the next hits, what could not be
# fetched, and what was wrong.
FOLLOWS = ("more", "hits", "not_found", CORRECTIONS)

# What the example of the request answers and asks of the rest of the plan.
PLACES_EXAMPLE = [{"id": "H2"}]
MORE_EXAMPLE = [{"get": "search", "pattern": "..."}]


def response_format() -> dict:
    """The passages found, each by the id the conversation showed it under,
    an empty list where none, and what the reply asks of the rest of the
    plan."""
    place = {"type": "object", "properties": {"id": {"type": "string"}},
             "required": ["id"], "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"places": {"type": "array", "items": place},
                             "more": more_schema()},
              "required": ["places"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "seek_reply", "schema": schema}}


def example() -> dict:
    """The reply as the prompt's example shows it, in the order of
    `response_format`."""
    return {"places": [dict(one) for one in PLACES_EXAMPLE],
            "more": [dict(ask) for ask in MORE_EXAMPLE]}


def owner_of(gathered: Gathered, ref) -> Optional[tuple]:
    """The passage an id of the conversation names: a hit ("H…") or a
    passage it fetched ("M…"); None for any other."""
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    hit = gathered.by_hit.get(ref)
    if hit is not None:
        return tuple(hit[0])
    for source, entry in zip(gathered.sources, gathered.shown):
        if entry.get("id") == ref:
            return (source.owner_kind, source.owner_id)
    return None


class FreeSearch:
    """(document_id, parameter, passages, walked, budget) -> [Source], the
    passages the model found for *parameter*, in the order it named them.

    *ask(payload, document_id, thread, follow)* is one message of a
    conversation (`thread.Thread`): the first shows *payload*, a later one
    carries *follow*, what is new since the answer it follows (`FOLLOWS`);
    the reply as a dict, CUT, or None. *rank(document_id, probes, exclude)*
    is the plan best first for a sentence ("similar"), None where the run
    ranks nothing.
    """

    def __init__(self, ask: Callable, *, rank: Optional[Callable] = None,
                 trace=None):
        self.ask = ask
        self.rank = rank
        self.trace = trace

    def __call__(self, document_id: int, parameter, passages: dict,
                 walked: list, budget: Optional[int] = None) -> list:
        order = list(passages.values())
        if not order:
            return []
        start = (order[0].owner_kind, order[0].owner_id)
        read = {tuple(owner) for owner in walked}
        gathered = Gathered(seen=set(read), cursor={"next": start,
                                                    "previous": start},
                            rank=(partial(self.rank, document_id)
                                  if self.rank is not None else None))
        payload = {"parameter": parameter_shown(parameter, full=True),
                   "walked": [{"kind": source.owner_kind,
                               "title": lookup.title_of(source)}
                              for source in order
                              if (source.owner_kind, source.owner_id)
                              in read]}
        asked = 0
        thread = Thread()
        shown = {"mark": gathered.mark()}

        def ask(corrections: Optional[list] = None):
            nonlocal asked
            if not thread.begun:
                first, follow = payload, None
            else:
                first = None
                follow = {**gathered.since(shown["mark"]),
                          **({CORRECTIONS: corrections}
                             if corrections else {})}
                if not follow:
                    return None
            asked += 1
            reply = self.ask(first, document_id, thread, follow)
            if isinstance(reply, dict):
                shown["mark"] = gathered.mark()
            return reply

        reply = ask()
        found: list = []
        unknown = 0
        if isinstance(reply, dict):
            reply, _more = gather(ask, reply, gathered, order, passages,
                                  budget)

            def placed(reply) -> tuple:
                owners, wrong = [], []
                for one in (reply or {}).get("places") or ():
                    ref = one.get("id") if isinstance(one, dict) else None
                    owner = owner_of(gathered, ref)
                    if owner is None or owner not in passages:
                        wrong.append({"id": ref, "what": say(
                            "place_unknown", id=ref)})
                    elif owner not in owners:
                        owners.append(owner)
                return owners, wrong
            owners, wrong = placed(reply)
            unknown = len(wrong)
            if wrong:
                again = ask(wrong)
                if isinstance(again, dict):
                    more, _ = placed(again)
                    owners += [owner for owner in more if owner not in owners]
            found = [passages[owner] for owner in owners]
        if self.trace is not None:
            self.trace("seek_free", document_id, parameter=parameter.uri,
                       walked=len(read), asked=asked, found=len(found),
                       fetched=len(gathered.sources), unknown=unknown)
        return found
