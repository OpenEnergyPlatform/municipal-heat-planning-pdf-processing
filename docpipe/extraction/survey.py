"""
survey.py: One pass over the whole plan before any number is read.

Every passage of the plan is a request of its own, a passage longer than the
text of one of its pages cut into pieces of a page (owner decisions
2026-11-06), and every passage is answered: the parameters whose values stand
in it, or none of them. The reply is that passage's entry alone, with no
wrapper and no id: the request shows one passage, so the model has nothing to
key its answer by (owner decision 2026-11-06). The survey only
names them, without a quote (owner decision 2026-11-06): it decides which
passages a parameter is read in, and the reading checks every value it reads
there. The same request names the tuples of the groups the spec reads here
(a scenario and its year), each coordinate with its own quote. A parameter is
then read in its own passages, and a number takes its frame from its passage,
without a search (owner decision 2026-11-04).

This replaces four steps of the harvest before it: the anchors written to
search with, the frame read from the best-ranked passages, the map of places
built at the first search, and most of the search for open coordinates. On
Rendsburg in corpus_m8_100 those were 60, 31, 112 and 833 requests, and the
frame saw 12 passages and found three pairs while the rows later carried six.

A parameter named for a passage is taken as named. A tuple is held to
`runner.frame_pairs`, the frame's own check.

The survey of a document is kept (`survey/<document>.json`) under a key over
the prompt, the parameters, the groups and the model. A survey of part of a
plan (the passages a harvest before found something in, the rest of a plan,
the parameters a spec gained) is kept beside it under its own scope
(`survey/<document>.<scope>.json`), so that neither is taken for the other.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from . import archive, fields

log = logging.getLogger(__name__)

SURVEY_PROMPT_ID = "extraction/survey"

# The answer for a passage that holds no number of any parameter.
NONE = "out:none"

# What a context's request came to besides a reply: too long to be sent, or
# an answer that did not fit its token limit. Neither is rescued; a request
# shows one passage of at most a page, so its passage stays unanswered.
CUT = "cut_off"

# The most text one survey request shows, in pages of its plan: a longer
# passage is cut into pieces of it (owner decision 2026-11-06). On paper 86 one
# page instead of two named scenario descriptions in 18 passages instead of
# 12, authors in 10 instead of 6, for 58 more requests. The reading keeps two
# pages for what it shows around a table or figure (`budget_of`).
CONTEXT_PAGES = 1


def budget_of(passages: list, pages: Optional[int], span: int = 2) -> int:
    """The text of *span* pages of this plan, in characters: *span* times
    its mean; two pages unless said otherwise.

    A figure's description is not counted: a figure is never cut, whatever
    its description's length.
    """
    chars = sum(len(p.text or "") for p in passages
                if p.owner_kind != "figure")
    if not pages:
        pages = max([(p.provenance or {}).get("page") or 0
                     for p in passages] or [0])
    return max(1, round(span * chars / max(pages or 1, 1)))


def pieces(text: str, budget: int) -> list:
    """*text* in pieces of at most *budget* characters, cut at a line end
    where one stands in the second half of the piece."""
    out, start = [], 0
    while start < len(text):
        end = min(start + budget, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + budget // 2, end)
            if cut > start:
                end = cut + 1
        if text[start:end].strip():
            out.append(text[start:end])
        start = end
    return out


def contexts_of(passages: list, budget: int) -> list:
    """The passages in document order, each a context of its own (owner
    decision 2026-11-06: one passage per request).

    A passage whose text is longer than *budget* characters is cut into
    pieces of the budget, each a context of its own, and every piece keeps
    its passage's owner. A figure is never cut: its description is not
    counted, whatever its length.
    """
    out: list = []
    for passage in passages:
        text = passage.text or ""
        if passage.owner_kind != "figure" and len(text) > budget:
            out.extend([replace(passage, text=piece)]
                       for piece in pieces(text, budget))
        else:
            out.append([passage])
    return out


def one_passage(context: list):
    """The one passage of a survey context (`contexts_of`); a context of any
    other size is a mistake of the caller, not something to answer."""
    if len(context) != 1:
        raise ValueError(f"a survey request shows one passage, not "
                         f"{len(context)}")
    return context[0]


def tuple_slots(spec) -> dict:
    """{group name: its slots} for every group the survey reads."""
    return {group.name: fields.frame_slots(spec, group.coordinates)
            for group in spec.groups_read_in("survey")}


def listed(slot) -> Optional[dict]:
    """A closed slot's list as the request shows it, without the out:
    entries and without "not stated": a tuple the passages do not print is
    left out, not answered."""
    if not slot.is_closed:
        return None
    shown = slot.answerable()
    kept = {option.label for option in slot.options
            if not str(option.uri).startswith("out:")}
    return {label: entry for label, entry in shown.items() if label in kept}


def parameters_of(spec) -> dict:
    """{uri: {label, definition}} of every parameter, as the survey shows
    them."""
    return {parameter.uri: {"label": parameter.label,
                            "definition": parameter.description}
            for parameter in spec.parameters}


def groups_shown(spec) -> dict:
    """{group name: {where, coordinates}} of the groups the survey reads,
    each coordinate with its list where it has one."""
    shown: dict = {}
    for group in spec.groups_read_in("survey"):
        slots = fields.frame_slots(spec, group.coordinates)
        shown[group.name] = {
            "where": group.where,
            "coordinates": {slot.name: (listed(slot) if slot.is_closed
                                        else slot.kind)
                            for slot in slots}}
    return shown


def key_of(prompt_text: str, parameters: dict, groups: dict,
           model: str) -> str:
    raw = json.dumps([prompt_text, parameters, groups, model],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def payload(context: list, parameters: dict, groups: dict,
            corrections: Optional[list] = None) -> dict:
    """One request: its one passage under "source", without an id, the
    parameters and the groups; with *corrections* the same request asked
    once more."""
    source = one_passage(context)
    provenance = source.provenance or {}
    shown = {"kind": source.owner_kind,
             "section": provenance.get("section_title"),
             "text": source.text or ""}
    if provenance.get("page"):
        shown["page"] = provenance["page"]
    body = {"source": shown, "parameters": parameters, "groups": groups}
    if corrections:
        body["corrections"] = list(corrections)
    return body


def corrections_of(answers: list, unanswered: list) -> list:
    """What was wrong with the reply about one passage, one sentence each,
    for the request that asks it again: a tuple not taken, or no list of
    parameters. Empty when nothing was."""
    from .wording import say

    out: list = []
    for answer in answers:
        for dropped in answer.dropped:
            why = dropped.get("why")
            if dropped.get("group") and why:
                out.append(why)
    out.extend(say("key_missing", key="parameters") for _ in unanswered)
    return out


def response_format(parameters: dict, slots: dict) -> dict:
    """The reply about one passage as a server grammar: its parameters from
    the list or NONE, and the tuples of each group the survey reads, at the
    top with no wrapper (owner decision 2026-11-06)."""
    entry_props: dict = {
        "parameters": {"type": "array", "minItems": 1,
                       "items": {"enum": sorted(parameters) + [NONE]}}}
    for name, group_slots in slots.items():
        props: dict = {}
        for slot in group_slots:
            if slot.is_closed:
                props[slot.name] = {"enum": sorted(listed(slot))}
            elif slot.kind == fields.NUMBER:
                props[slot.name] = {"type": "integer"}
            else:
                props[slot.name] = {"type": "string"}
            props[f"{slot.name}_quote"] = {"type": "string"}
            props[f"{slot.name}_raw"] = {"type": "string"}
        entry_props[name] = {"type": "array", "items": {
            "type": "object", "properties": props,
            "required": [s.name for s in group_slots]
            + [f"{s.name}_quote" for s in group_slots],
            "additionalProperties": False}}
    schema = {"type": "object", "properties": entry_props,
              "required": ["parameters"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "survey_reply", "schema": schema}}


@dataclass
class Answer:
    """What the survey says of one passage."""
    owner: tuple
    parameters: list                  # taken, in the reply's order
    tuples: dict = field(default_factory=dict)     # group -> [tuple]
    dropped: list = field(default_factory=list)    # why something was not taken


def read_reply(reply: dict, context: list, parameters: dict, slots: dict,
               pairs_of: Callable) -> tuple:
    """([Answer], passages unanswered) of the reply about a context's one
    passage: the reply is that passage's entry itself (`response_format`).

    The parameters are taken as the reply names them, those of the spec
    only; NONE beside a parameter says nothing. A reply that is no object or
    has no list under "parameters" leaves the passage unanswered. A tuple is
    taken when *pairs_of* (`runner.frame_pairs`) takes it over the passage
    shown. Nothing else is checked.
    """
    source = one_passage(context)
    owner = (source.owner_kind, source.owner_id)
    if not isinstance(reply, dict) \
            or not isinstance(reply.get("parameters"), list):
        return [], [owner]
    answer = Answer(owner, [p for p in reply["parameters"]
                            if p in parameters])
    for name, group_slots in slots.items():
        rejected: list = []
        given = reply.get(name)
        taken = pairs_of({"pairs": given if isinstance(given, list)
                          else []}, group_slots, context, rejected)
        if taken:
            answer.tuples[name] = taken
        for reason in rejected:
            answer.dropped.append({"group": name,
                                   "why": reason.get("reason")})
    return [answer], []


@dataclass
class Found:
    """The survey of one document."""
    complete: bool
    answers: dict = field(default_factory=dict)    # owner -> Answer
    unanswered: list = field(default_factory=list)
    # (parameter uri, owner kind, owner id) -> place from 1: each passage
    # the walk down a search's list read a parameter in, with its place in
    # that list, in the order read (`surveyed.sought_walk`, `walks_of`).
    walked: dict = field(default_factory=dict)

    def passages_of(self, parameter: str) -> list:
        """The owners the survey named for *parameter*, in document order."""
        return [owner for owner, answer in self.answers.items()
                if parameter in answer.parameters]

    def tuples_at(self, owner: tuple, group: str) -> list:
        answer = self.answers.get(tuple(owner))
        return list(answer.tuples.get(group, ())) if answer else []


def merge(found: Found, answers: list) -> None:
    """Fold the answers of one context into the document's: pieces of one
    passage add up, a tuple counts once."""
    for answer in answers:
        held = found.answers.get(answer.owner)
        if held is None:
            found.answers[answer.owner] = answer
            continue
        for parameter in answer.parameters:
            if parameter not in held.parameters:
                held.parameters.append(parameter)
        for name, tuples in answer.tuples.items():
            have = held.tuples.setdefault(name, [])
            for one in tuples:
                if one not in have:
                    have.append(one)
        held.dropped.extend(answer.dropped)


class Survey:
    """document_id -> Found.

    *ask(context, document_id, corrections)* is one request: the reply as a
    dict, CUT, or None when it could not be read. A reply with something not
    taken is asked once more with what was wrong (`corrections_of`), and
    what either reply backs is taken. *passages_of(document_id)* is every
    passage of the document in its order, *pages_of(document_id)* its page
    count. *pool* runs a document's requests side by side (None: one after
    another). *store* is where surveys are kept, *scope* the name of a
    survey of part of a plan beside the whole one's.
    """

    def __init__(self, ask: Callable, passages_of: Callable,
                 pages_of: Callable, parameters: dict, slots: dict,
                 pairs_of: Callable, key: str, *,
                 store: Optional[Path] = None, scope: str = "",
                 pool=None, trace=None):
        self.ask = ask
        self.passages_of = passages_of
        self.pages_of = pages_of
        self.parameters = parameters
        self.slots = slots
        self.pairs_of = pairs_of
        self.key = key
        self.store = Path(store) if store else None
        self.scope = scope
        self.pool = pool
        self.trace = trace
        self._found: dict = {}
        self._locks: dict = {}
        self._guard = threading.Lock()

    def __call__(self, document_id: int,
                 passages: Optional[list] = None) -> Found:
        """The survey of *document_id*: of every passage it has, or of
        *passages* for a survey of part of it."""
        with self._guard:
            lock = self._locks.setdefault(document_id, threading.Lock())
        with lock:
            found = self._found.get(document_id)
            if found is None:
                if passages is None:
                    passages = self.passages_of(document_id)
                found = (self._load(document_id, passages)
                         or self._build(document_id, passages))
                self._found[document_id] = found
            return found

    def _path(self, document_id: int) -> Optional[Path]:
        if self.store is None:
            return None
        name = (f"{document_id}.{self.scope}" if self.scope
                else str(document_id))
        return self.store / f"{name}.json"

    def _load(self, document_id: int, passages: list) -> Optional[Found]:
        path = self._path(document_id)
        if path is None or not path.is_file():
            return None
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if kept.get("key") != self.key or not kept.get("complete"):
            return None
        at = {(s.owner_kind, s.owner_id) for s in passages}
        answers = {tuple(a["owner"]): Answer(
            tuple(a["owner"]), list(a.get("parameters") or ()),
            dict(a.get("tuples") or {}), list(a.get("dropped") or ()))
            for a in kept.get("answers", ())}
        unanswered = [tuple(o) for o in kept.get("unanswered") or ()]
        if set(answers) | set(unanswered) != at:
            return None                 # the passages changed since
        # What it could not answer stays a hole, as it was the first time.
        return Found(True, answers, unanswered)

    def _ask_context(self, context: list, document_id: int) -> tuple:
        """(answers, unanswered, complete) of one context, its one passage
        asked once more for what the reply got wrong. A reply that did not
        fit its room leaves the passage unanswered: there is nothing left to
        split."""
        source = one_passage(context)
        reply = self.ask(context, document_id, None)
        if not isinstance(reply, dict):
            return [], [(source.owner_kind, source.owner_id)], False
        answers, unanswered = read_reply(reply, context, self.parameters,
                                         self.slots, self.pairs_of)
        corrections = corrections_of(answers, unanswered)
        if not corrections:
            return answers, unanswered, True
        again = self.ask(context, document_id, corrections)
        if not isinstance(again, dict):
            return answers, unanswered, True
        more, still = read_reply(again, context, self.parameters,
                                 self.slots, self.pairs_of)
        found = Found(True)
        merge(found, answers + more)
        return (list(found.answers.values()),
                [owner for owner in unanswered if owner in still], True)

    def _build(self, document_id: int, passages: list) -> Found:
        budget = budget_of(passages, self.pages_of(document_id),
                           CONTEXT_PAGES)
        contexts = contexts_of(passages, budget)
        if self.pool is None:
            results = [self._ask_context(c, document_id) for c in contexts]
        else:
            futures = [self.pool.submit(self._ask_context, c, document_id)
                       for c in contexts]
            results = [f.result() for f in futures]
        found = Found(all(r[2] for r in results))
        for answers, unanswered, _done in results:
            merge(found, answers)
            found.unanswered.extend(o for o in unanswered
                                    if o not in found.unanswered)
        # In document order, whatever order the contexts came back in.
        order = {(s.owner_kind, s.owner_id): i
                 for i, s in enumerate(passages)}
        found.answers = dict(sorted(found.answers.items(),
                                    key=lambda item: order.get(item[0], 0)))
        by_parameter = {p: len(found.passages_of(p)) for p in self.parameters}
        none = sum(1 for a in found.answers.values() if not a.parameters)
        dropped = sum(len(a.dropped) for a in found.answers.values())
        tuples = {name: len({json.dumps(t, sort_keys=True, default=str)
                             for a in found.answers.values()
                             for t in a.tuples.get(name, ())})
                  for name in self.slots}
        log.info("   survey %s: %d passage(s) in %d context(s) of %d chars, "
                 "%d without a parameter, %d answer(s) not taken, %d "
                 "unanswered%s", document_id, len(passages), len(contexts),
                 budget, none, dropped, len(found.unanswered),
                 "" if found.complete else " -- incomplete")
        if self.trace is not None:
            self.trace("survey", document_id, scope=self.scope or None,
                       passages=len(passages),
                       contexts=len(contexts), budget=budget, none=none,
                       dropped=dropped, unanswered=len(found.unanswered),
                       complete=found.complete, by_parameter=by_parameter,
                       tuples=tuples)
        path = self._path(document_id)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            archive.keep(path)
            path.write_text(json.dumps(
                {"key": self.key, "complete": found.complete,
                 "contexts": len(contexts), "budget": budget,
                 "answers": [{"owner": list(a.owner),
                              "parameters": a.parameters,
                              "tuples": a.tuples, "dropped": a.dropped}
                             for a in found.answers.values()],
                 "unanswered": [list(o) for o in found.unanswered]},
                ensure_ascii=False, default=str), encoding="utf-8")
        return found
