"""
survey.py: The passages each parameter of a plan is read in, best first.

Every passage of the plan is read for every parameter (owner decisions
2026-11-08). The survey this replaces asked the model, per passage, which
parameters stand in it, and read a parameter only where it was named: on
one plan it named none for 34 of the 207 passages two runs both surveyed
where the run before had named one, and about 120 values were never asked.
What is left is the order: for each parameter the reranker ranks the whole
plan with the parameter's search sentences (its HyDE sentences,
`runner.make_seek_probes`), and its passages are read in that order, a
passage the search did not return after them in the plan's order. Nothing
is left out for its rank.

The order of a document is kept (`survey/<document>.json`) under a key over
the parameters, with the passages it ranked. An order of part of a plan (the
passages a harvest before found something in, the rest of a plan, the
parameters a spec gained) is kept beside it under its own scope
(`survey/<document>.<scope>.json`), so that neither is taken for the other;
the passes over a stored harvest read from these files what was read
(`surveyed.surveyed_owners`).

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import archive

log = logging.getLogger(__name__)


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
    budget = max(1, int(budget))
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


def key_of(parameters: list) -> str:
    """The key an order is kept under: the parameters it ranked, each with
    the words its search sentences are written from."""
    raw = json.dumps([[p.uri, p.label, p.description] for p in parameters],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Answer:
    """The parameters one passage is read for. *tuples* and *dropped* are
    what a stored survey of the flow before this one said of the passage's
    frame, read back by the passes over its harvest."""
    owner: tuple
    parameters: list
    tuples: dict = field(default_factory=dict)     # group -> [tuple]
    dropped: list = field(default_factory=list)


@dataclass
class Found:
    """The passages of one document each parameter is read in."""
    complete: bool
    answers: dict = field(default_factory=dict)    # owner -> Answer
    unanswered: list = field(default_factory=list)
    # parameter uri -> its owners best first (`Ranking`); a parameter
    # without one is read in the plan's order.
    order: dict = field(default_factory=dict)

    def passages_of(self, parameter: str) -> list:
        """The owners *parameter* is read in: best first where they were
        ranked, else in document order."""
        named = [owner for owner, answer in self.answers.items()
                 if parameter in answer.parameters]
        ranked = self.order.get(parameter)
        if not ranked:
            return named
        held = set(named)
        first = [tuple(owner) for owner in ranked if tuple(owner) in held]
        rest = [owner for owner in named if owner not in set(first)]
        return first + rest

    def tuples_at(self, owner: tuple, group: str) -> list:
        answer = self.answers.get(tuple(owner))
        return list(answer.tuples.get(group, ())) if answer else []


def merge(found: Found, answers: list) -> None:
    """Fold *answers* into the document's: the parameters of one passage
    add up, a tuple counts once."""
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


def ranked_owners(ranked: list, passages: list) -> list:
    """The owners of *passages*, those *ranked* returned first in its order,
    the rest after them in the order of *passages*: every passage once."""
    held = [(s.owner_kind, s.owner_id) for s in passages]
    wanted = set(held)
    first: list = []
    for source in ranked or ():
        owner = (source.owner_kind, source.owner_id)
        if owner in wanted and owner not in first:
            first.append(owner)
    taken = set(first)
    return first + [owner for owner in held if owner not in taken]


class Ranking:
    """document_id -> Found: every passage of the document for every
    parameter of *parameters*, each parameter's passages best first.

    *rank(document_id, sentences, exclude)* is the whole plan best first
    for search sentences (the run's search with its reranker), *probes(
    parameter, document_id)* the parameter's sentences, its label where it
    has none. *passages_of(document_id)* is every passage of the document in
    its order. *store* is where orders are kept, *scope* the name of an
    order of part of a plan beside the whole one's.
    """

    def __init__(self, rank: Optional[Callable], passages_of: Callable,
                 parameters: list, *, probes: Optional[Callable] = None,
                 store: Optional[Path] = None, scope: str = "", trace=None):
        self.rank = rank
        self.passages_of = passages_of
        self.parameters = list(parameters)
        self.probes = probes
        self.key = key_of(self.parameters)
        self.store = Path(store) if store else None
        self.scope = scope
        self.trace = trace
        self._found: dict = {}
        self._locks: dict = {}
        self._guard = threading.Lock()

    def __call__(self, document_id: int,
                 passages: Optional[list] = None) -> Found:
        """The order of *document_id*: of every passage it has, or of
        *passages* for an order of part of it."""
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
            tuple(a["owner"]), list(a.get("parameters") or ()))
            for a in kept.get("answers", ())}
        if set(answers) != at:
            return None                 # the passages changed since
        order = {uri: [tuple(o) for o in owners]
                 for uri, owners in (kept.get("order") or {}).items()}
        return Found(True, answers, [], order)

    def _ranked(self, document_id: int, parameter, passages: list) -> list:
        """The owners of *passages* best first for *parameter*; in the
        plan's order where nothing ranks them."""
        if self.rank is None:
            return ranked_owners([], passages)
        sentences = ((self.probes(parameter, document_id)
                      if self.probes else None) or [parameter.label])
        try:
            ranked = self.rank(document_id, list(sentences), set())
        except Exception as exc:    # the order only: every passage is read
            log.warning("   order of %s for %s: the search failed, read in "
                        "the plan's order: %s", parameter.uri, document_id,
                        exc)
            ranked = []
        return ranked_owners(ranked, passages)

    def _build(self, document_id: int, passages: list) -> Found:
        uris = [parameter.uri for parameter in self.parameters]
        found = Found(True)
        for source in passages:
            owner = (source.owner_kind, source.owner_id)
            if owner not in found.answers:
                found.answers[owner] = Answer(owner, list(uris))
        ranked_first: dict = {}
        for parameter in self.parameters:
            owners = self._ranked(document_id, parameter, passages)
            found.order[parameter.uri] = owners
            ranked_first[parameter.uri] = [list(o) for o in owners[:5]]
        log.info("   order %s%s: %d passage(s), each read for %d "
                 "parameter(s)", document_id,
                 f" ({self.scope})" if self.scope else "",
                 len(found.answers), len(uris))
        if self.trace is not None:
            self.trace("order", document_id, scope=self.scope or None,
                       passages=len(found.answers), parameters=len(uris),
                       first=ranked_first)
        path = self._path(document_id)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            archive.keep(path)
            path.write_text(json.dumps(
                {"key": self.key, "complete": True,
                 "answers": [{"owner": list(a.owner),
                              "parameters": a.parameters}
                             for a in found.answers.values()],
                 "order": {uri: [list(o) for o in owners]
                           for uri, owners in found.order.items()}},
                ensure_ascii=False, default=str), encoding="utf-8")
        return found
