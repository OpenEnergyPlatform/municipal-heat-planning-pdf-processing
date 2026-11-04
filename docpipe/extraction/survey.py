"""
survey.py: One pass over the whole plan before any number is read.

The plan is cut into small contexts, at most one figure and at most the text
of two of its pages each, and every passage of every context is answered:
the parameters whose numbers stand in it, with a quote, or none of them.
The same request names the tuples of the groups the spec reads here (a
scenario and its year), each coordinate with its own quote. A parameter is
then read in its own passages, and a number takes its frame from its passage,
without a search (owner decision 2026-11-04).

This replaces four steps of the harvest before it: the anchors written to
search with, the frame read from the best-ranked passages, the map of places
built at the first search, and most of the search for open coordinates. On
Rendsburg in corpus_m8_100 those were 60, 31, 112 and 833 requests, and the
frame saw 12 passages and found three pairs while the rows later carried six.

Checked is what every reading is checked for: an assignment's quote stands
in its own passage and is long enough to name a place there; a tuple is held
to `runner.frame_pairs`, the frame's own check.

The survey of a document is kept (`survey/<document>.json`) under a key over
the prompt, the parameters, the groups and the model.

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
from .verify import MIN_QUOTE_CHARS, quote_in

log = logging.getLogger(__name__)

SURVEY_PROMPT_ID = "extraction/survey"

# The answer for a passage that holds no number of any parameter.
NONE = "out:none"

# What a context's request came to besides a reply: too long to be sent, or
# an answer that did not fit its token limit. Both are split, not rescued.
CUT = "cut_off"


def budget_of(passages: list, pages: Optional[int]) -> int:
    """The text of two pages of this plan, in characters: twice its mean.

    A figure's description is not counted: a context holds one figure,
    whatever its description's length.
    """
    chars = sum(len(p.text or "") for p in passages
                if p.owner_kind != "figure")
    if not pages:
        pages = max([(p.provenance or {}).get("page") or 0
                     for p in passages] or [0])
    return max(1, round(2 * chars / max(pages or 1, 1)))


def _pieces(text: str, budget: int) -> list:
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
    """The passages in document order, packed into contexts of at most one
    figure and at most *budget* characters of text.

    A passage longer than the budget is cut into pieces of the budget, each
    a context of its own, and every piece keeps its passage's owner.
    """
    out: list = []
    current: list = []
    chars, figure = 0, False
    for passage in passages:
        text = passage.text or ""
        is_figure = passage.owner_kind == "figure"
        size = 0 if is_figure else len(text)
        if size > budget:
            if current:
                out.append(current)
            current, chars, figure = [], 0, False
            out.extend([replace(passage, text=piece)]
                       for piece in _pieces(text, budget))
            continue
        if current and (chars + size > budget or (is_figure and figure)):
            out.append(current)
            current, chars, figure = [], 0, False
        current.append(passage)
        chars += size
        figure = figure or is_figure
    if current:
        out.append(current)
    return out


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
    sources = []
    for index, source in enumerate(context):
        provenance = source.provenance or {}
        entry = {"id": f"P{index + 1}", "kind": source.owner_kind,
                 "section": provenance.get("section_title"),
                 "text": source.text or ""}
        if provenance.get("page"):
            entry["page"] = provenance["page"]
        sources.append(entry)
    body = {"sources": sources, "parameters": parameters, "groups": groups}
    if corrections:
        body["corrections"] = list(corrections)
    return body


def corrections_of(answers: list, unanswered: list, context: list) -> list:
    """What was wrong with a reply over *context*, one sentence each, for
    the request that asks it again: a quote not in its passage or too short,
    a tuple not taken, a passage not answered. Empty when nothing was."""
    from .wording import say

    label = {(s.owner_kind, s.owner_id): f"P{i + 1}"
             for i, s in enumerate(context)}
    out: list = []
    for answer in answers:
        for dropped in answer.dropped:
            why = dropped.get("why")
            if why == "quote too short":
                sentence = say("quote_too_short", minimum=MIN_QUOTE_CHARS)
            elif why in ("quote not in its passage", "no quote"):
                sentence = say("quote_not_in_source")
            elif dropped.get("group") and why:
                sentence = why
            else:
                continue
            out.append(f"{label.get(answer.owner, '?')}: {sentence}")
    out.extend(say("key_missing", key=label.get(tuple(owner), "?"))
               for owner in unanswered)
    return out


def response_format(context: list, parameters: dict, slots: dict) -> dict:
    """The reply as a server grammar: one entry for EVERY passage of the
    context, its parameters from the list or NONE, a quote, and the tuples
    of each group the survey reads."""
    entry_props: dict = {
        "parameters": {"type": "array", "minItems": 1,
                       "items": {"enum": sorted(parameters) + [NONE]}},
        "quote": {"type": "string"}}
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
    entry = {"type": "object", "properties": entry_props,
             "required": ["parameters"], "additionalProperties": False}
    ids = [f"P{i + 1}" for i in range(len(context))]
    schema = {"type": "object",
              "properties": {"passages": {
                  "type": "object", "properties": {i: entry for i in ids},
                  "required": ids, "additionalProperties": False}},
              "required": ["passages"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "survey_reply", "schema": schema}}


@dataclass
class Answer:
    """What the survey says of one passage."""
    owner: tuple
    parameters: list                  # taken, in the reply's order
    quote: Optional[str] = None
    tuples: dict = field(default_factory=dict)     # group -> [tuple]
    dropped: list = field(default_factory=list)    # why something was not taken


def read_reply(reply: dict, context: list, parameters: dict, slots: dict,
               pairs_of: Callable) -> tuple:
    """([Answer], passages unanswered) of one context's reply.

    A passage's parameters are taken when their quote stands in that passage
    and is long enough to name a place there; NONE beside a parameter says
    nothing. A tuple is taken when *pairs_of* (`runner.frame_pairs`) takes
    it over the passages shown. Nothing else is checked.
    """
    answers, unanswered = [], []
    entries = (reply or {}).get("passages")
    entries = entries if isinstance(entries, dict) else {}
    for index, source in enumerate(context):
        owner = (source.owner_kind, source.owner_id)
        entry = entries.get(f"P{index + 1}")
        if not isinstance(entry, dict):
            unanswered.append(owner)
            continue
        answer = Answer(owner, [])
        named = [p for p in entry.get("parameters") or ()
                 if p in parameters]
        quote = entry.get("quote")
        if named:
            if not isinstance(quote, str) or not quote.strip():
                answer.dropped.append({"parameters": named,
                                       "why": "no quote"})
            elif len(quote.strip()) < MIN_QUOTE_CHARS:
                answer.dropped.append({"parameters": named,
                                       "why": "quote too short",
                                       "quote": quote})
            elif not quote_in(source.text or "", quote):
                answer.dropped.append({"parameters": named,
                                       "why": "quote not in its passage",
                                       "quote": quote})
            else:
                answer.parameters = named
                answer.quote = quote.strip()
        for name, group_slots in slots.items():
            rejected: list = []
            given = entry.get(name)
            taken = pairs_of({"pairs": given if isinstance(given, list)
                              else []}, group_slots, context, rejected)
            if taken:
                answer.tuples[name] = taken
            for reason in rejected:
                answer.dropped.append({"group": name,
                                       "why": reason.get("reason")})
        answers.append(answer)
    return answers, unanswered


@dataclass
class Found:
    """The survey of one document."""
    complete: bool
    answers: dict = field(default_factory=dict)    # owner -> Answer
    unanswered: list = field(default_factory=list)

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
        held.quote = held.quote or answer.quote
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
    another). *store* is where surveys are kept.
    """

    def __init__(self, ask: Callable, passages_of: Callable,
                 pages_of: Callable, parameters: dict, slots: dict,
                 pairs_of: Callable, key: str, *,
                 store: Optional[Path] = None, pool=None, trace=None):
        self.ask = ask
        self.passages_of = passages_of
        self.pages_of = pages_of
        self.parameters = parameters
        self.slots = slots
        self.pairs_of = pairs_of
        self.key = key
        self.store = Path(store) if store else None
        self.pool = pool
        self.trace = trace
        self._found: dict = {}
        self._locks: dict = {}
        self._guard = threading.Lock()

    def __call__(self, document_id: int) -> Found:
        with self._guard:
            lock = self._locks.setdefault(document_id, threading.Lock())
        with lock:
            found = self._found.get(document_id)
            if found is None:
                found = self._load(document_id) or self._build(document_id)
                self._found[document_id] = found
            return found

    def _path(self, document_id: int) -> Optional[Path]:
        return self.store / f"{document_id}.json" if self.store else None

    def _load(self, document_id: int) -> Optional[Found]:
        path = self._path(document_id)
        if path is None or not path.is_file():
            return None
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if kept.get("key") != self.key or not kept.get("complete"):
            return None
        at = {(s.owner_kind, s.owner_id)
              for s in self.passages_of(document_id)}
        answers = {tuple(a["owner"]): Answer(
            tuple(a["owner"]), list(a.get("parameters") or ()),
            a.get("quote"), dict(a.get("tuples") or {}),
            list(a.get("dropped") or ())) for a in kept.get("answers", ())}
        if set(answers) - at:
            return None                 # the document changed since
        return Found(True, answers, [])

    def _ask_context(self, context: list, document_id: int) -> tuple:
        """(answers, unanswered, complete) of one context, halved while its
        reply does not fit, asked once more for what it got wrong."""
        reply = self.ask(context, document_id, None)
        if reply == CUT and len(context) > 1:
            cut = len(context) // 2
            a = self._ask_context(context[:cut], document_id)
            b = self._ask_context(context[cut:], document_id)
            return a[0] + b[0], a[1] + b[1], a[2] and b[2]
        if not isinstance(reply, dict):
            return [], [(s.owner_kind, s.owner_id) for s in context], False
        answers, unanswered = read_reply(reply, context, self.parameters,
                                         self.slots, self.pairs_of)
        corrections = corrections_of(answers, unanswered, context)
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

    def _build(self, document_id: int) -> Found:
        passages = self.passages_of(document_id)
        budget = budget_of(passages, self.pages_of(document_id))
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
            self.trace("survey", document_id, passages=len(passages),
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
                              "parameters": a.parameters, "quote": a.quote,
                              "tuples": a.tuples, "dropped": a.dropped}
                             for a in found.answers.values()],
                 "unanswered": [list(o) for o in found.unanswered]},
                ensure_ascii=False, default=str), encoding="utf-8")
        return found
