"""
settings.py: What a plan settles for all its values, asked once per plan:
its settings, each in the plan's own words and with its quote (owner
decisions 2026-11-07, „Ja, je Plan (Empfohlen)“, both profiles).

A plan says once what holds for all its numbers: "Das Basisjahr ist das Jahr
2022.", that "CO2-Emissionen" include the CO2 equivalents, the unit of the
consumptions in a table. Asked of every value on its own, such a sentence
pages away was not shown, and the coordinate stayed open. One request per
plan now reads them, free settings in the plan's words, each {about, value,
quote}, without a list and without saying which coordinate one belongs to:
that is the reading's to decide, by meaning, where it is shown the settings
beside a value (`reading.text_payload`, `combing.Comber`), and an answer may
quote one.

The request lists the plan's passages in its order, a page of each kind at a
time, and has the combing's tools (`reading.Gathered`): it reads what it asks
for, and a round that asks for nothing new gets the next passages of the
plan, until every passage was listed. Each setting is checked as any answer
is: its quote stands in what the request showed, is long enough, and holds
what it is about and what it settles; what fails is told once.

Author: Felix Vossel
"""
from __future__ import annotations

from functools import partial
from typing import Callable, Optional

from . import lookup
from .reading import Gathered, first_line, gather, more_schema, shown_hits
from .thread import CORRECTIONS, Thread
from .verify import MIN_QUOTE_CHARS, flat, quote_in
from .wording import say

SETTINGS_PROMPT_ID = "extraction/settings"
# The fields of the messages that follow an answer (owner decisions
# 2026-11-07): the rounds are one conversation, each later one bringing what
# is new since (`reading.Gathered.since`) and what was wrong.
FOLLOWS = ("more", "hits", "not_found", CORRECTIONS)
# What a setting names, as the reply gives it: what it is about, what it
# settles for it, and the place that prints it.
KEYS = ("about", "value", "quote")

# What the example of the request asks of the rest of the plan, as the
# combing's example does.
MORE_EXAMPLE = [{"get": "hit", "id": "H2"}]


def response_format() -> dict:
    """The plan's settings, each what it is about, what it settles and its
    quote, an empty list where the plan settles nothing for all its values,
    and what the reply asks of the rest of the plan."""
    setting = {"type": "object",
               "properties": {key: {"type": "string"} for key in KEYS},
               "required": list(KEYS), "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"settings": {"type": "array", "items": setting},
                             "more": more_schema()},
              "required": ["settings"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "settings_reply", "schema": schema}}


def example() -> dict:
    """The reply as the prompt's example shows it: one setting with its
    quote, and an ask for more, in the order of `response_format`."""
    return {"settings": [{key: "..." for key in KEYS}],
            "more": [dict(ask) for ask in MORE_EXAMPLE]}


class PlanSettings:
    """(document_id, passages, budget) -> the plan's settings, each
    {"about", "value", "quote", "source"}, [] where none holds.

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

    @staticmethod
    def checked(reply, evidence: list) -> tuple:
        """([setting], [correction]) of a reply: each setting whose quote
        stands in what the request showed, is long enough and holds what it
        is about and what it settles; one correction per setting that does
        not."""
        out, wrong, seen = [], [], set()
        for entry in (reply or {}).get("settings") or ():
            if not isinstance(entry, dict):
                continue
            given = {key: entry.get(key) for key in KEYS}
            if not all(isinstance(value, str) and value.strip()
                       for value in given.values()):
                wrong.append({**given, "what": say(
                    "key_missing", key=", ".join(KEYS))})
                continue
            quote = given["quote"]
            source = None
            if len(quote.strip()) < MIN_QUOTE_CHARS:
                why = say("quote_too_short", minimum=MIN_QUOTE_CHARS)
            else:
                source = next((s for s in evidence
                               if quote_in(s.text or "", quote)), None)
                why = None if source is not None else say("quote_not_shown")
            if why is None:
                said = flat(quote).casefold()
                lacking = [given[key] for key in ("about", "value")
                           if flat(given[key]).casefold() not in said]
                if lacking:
                    why = say("answer_not_in_quote_text", answer=lacking[0])
            if why is not None:
                wrong.append({**given, "what": why})
                continue
            key = (flat(given["about"]).casefold(),
                   flat(given["value"]).casefold())
            if key in seen:
                continue
            seen.add(key)
            out.append({"about": given["about"].strip(),
                        "value": given["value"].strip(),
                        "quote": quote.strip(),
                        "source": [source.owner_kind, source.owner_id]})
        return out, wrong

    def __call__(self, document_id: int, passages: dict,
                 budget: Optional[int] = None) -> list:
        order = list(passages.values())
        if not order:
            return []
        start = (order[0].owner_kind, order[0].owner_id)
        gathered = Gathered(seen=set(), cursor={"next": start,
                                                "previous": start},
                            rank=(partial(self.rank, document_id)
                                  if self.rank is not None else None))
        hits = gathered.list_hits([((s.owner_kind, s.owner_id),
                                    lookup.title_of(s), first_line(s))
                                   for s in shown_hits(order)])
        asked = 0
        thread = Thread()
        # What the conversation has shown of the gathering.
        shown = {"mark": gathered.mark()}

        def ask(corrections: Optional[list] = None):
            # The first message shows the first passages of the plan; each
            # later one follows the answer before it with what is new since
            # and what was wrong (owner decisions 2026-11-07).
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

        def next_passages(_reply) -> bool:
            # Every passage of the plan is listed before the settings stand.
            nonlocal hits
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
        settings: list = []
        refused = 0
        if isinstance(reply, dict):
            reply, _more = gather(ask, reply, gathered, order, passages,
                                  budget, then=next_passages)
            settings, wrong = self.checked(reply, gathered.evidence(passages))
            refused = len(wrong)
            if wrong:
                again = ask(wrong)
                if isinstance(again, dict):
                    more, _ = self.checked(again,
                                           gathered.evidence(passages))
                    held = {(s["about"], s["value"]) for s in settings}
                    settings += [s for s in more
                                 if (s["about"], s["value"]) not in held]
        if self.trace is not None:
            self.trace("settings", document_id, settings=len(settings),
                       asked=asked, hits=hits,
                       fetched=len(gathered.sources), refused=refused)
        return settings
