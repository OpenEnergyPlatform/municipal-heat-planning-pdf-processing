"""
places.py: Where a document says something to each axis, read once per
document before its coordinates are searched.

The search for a coordinate the value's own passage does not answer used to
read the whole plan for it, window after window: the embedding ranking first,
then every remaining passage in order. Most passages say nothing to most
axes, and the rest stage of one AR6 document took two hours for nineteen
coordinates.

Here the model reads every passage of the document once, side by side, and
names for each one the parameters whose numbers stand in it and the axes it
answers, with a verbatim quote. It reads no value. The search then shows a
coordinate only the places of its axis, nearest to the row first. A place
whose quote does not stand in its passage, or is too short to name a place,
is not taken: the two halves of the one check every reading passes, minus the
answer, because there is none.

A map is complete when every window of the document came back readable. Only
a complete map stands for the document (owner decision 2026-10-22: an axis
still open after all its places is unstated, the map having read the whole
plan). An incomplete one is not used, and the search reads as before.

The map is kept per document (`places/<document>.json`) under a key over the
prompt, the questions and the model, so a pass over a stored harvest reads it
again instead of asking for it again.

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

from . import archive, fields
from .verify import MIN_QUOTE_CHARS, quote_in

log = logging.getLogger(__name__)

PLACES_PROMPT_ID = "extraction/places"

# What a window's request came to besides a reply: too long to be sent, or
# an answer that did not fit its token limit. Both are split, not rescued.
CUT = "cut_off"


@dataclass
class Map:
    """The places of one document: which passages answer which axis."""
    complete: bool
    by_axis: dict = field(default_factory=dict)    # axis -> {(kind, id)}
    by_parameter: dict = field(default_factory=dict)

    def keys_of(self, axes) -> Optional[set]:
        """The passages that answer any of *axes*, or None when the map does
        not stand for the document or does not know one of them."""
        if not self.complete or any(axis not in self.by_axis
                                    for axis in axes):
            return None
        return set().union(*(self.by_axis[axis] for axis in axes))


def questions(spec) -> tuple:
    """({axis: question}, {parameter: label}) the map is asked with: every
    axis the spec asks with a question, the first wording of each, and the
    unit. The unit off the map searched the whole plan: in the test of
    2026-10-23, 26,499 of about 35,000 requests read 71 units."""
    asked = [(name, axis.question) for parameter in spec.parameters
             for name, axis in parameter.axes.items() if not axis.derive]
    unit = fields.unit_slot(spec)
    if unit is not None:
        asked.append((unit.name, unit.question))
    axes: dict = {}
    for name, question in asked:
        if question and name not in axes:
            axes[name] = question.split("?")[0].strip() + "?"
    named = {parameter.uri: parameter.label for parameter in spec.parameters}
    return axes, named


def key_of(prompt_text: str, axes: dict, parameters: dict,
           model: str) -> str:
    raw = json.dumps([prompt_text, axes, parameters, model],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def payload(window: list, axes: dict, parameters: dict) -> dict:
    return {"sources": [{"id": f"P{i + 1}", "text": source.text or ""}
                        for i, source in enumerate(window)],
            "parameters": parameters, "axes": axes}


def response_format(window: list, axes: dict, parameters: dict) -> dict:
    """The reply as a server grammar: a list of places, each one passage of
    the window, parameters and axes from their lists, and a quote."""
    hit = {"type": "object",
           "properties": {
               "passage": {"enum": [f"P{i + 1}" for i in range(len(window))]},
               "parameters": {"type": "array",
                              "items": {"enum": sorted(parameters)}},
               "axes": {"type": "array", "items": {"enum": sorted(axes)}},
               "quote": {"type": "string"}},
           "required": ["passage", "axes", "quote"],
           "additionalProperties": False}
    schema = {"type": "object",
              "properties": {"hits": {"type": "array", "items": hit}},
              "required": ["hits"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "places_reply", "schema": schema}}


def read_hits(reply: dict, window: list, axes: dict,
              parameters: dict) -> tuple:
    """([(source, axes, parameters, quote)], places not taken) of one reply.

    A place is taken when its quote stands in its own passage and is long
    enough to name a place there. Nothing else is checked.
    """
    taken, dropped = [], 0
    for hit in (reply or {}).get("hits") or []:
        if not isinstance(hit, dict):
            dropped += 1
            continue
        label = str(hit.get("passage") or "")
        index = int(label[1:]) - 1 if label[1:].isdigit() else -1
        quote = hit.get("quote")
        if not 0 <= index < len(window) or not isinstance(quote, str):
            dropped += 1
            continue
        source = window[index]
        if (len(quote.strip()) < MIN_QUOTE_CHARS
                or not quote_in(source.text or "", quote)):
            dropped += 1
            continue
        named_axes = [a for a in hit.get("axes") or () if a in axes]
        named = [p for p in hit.get("parameters") or () if p in parameters]
        if named_axes or named:
            taken.append((source, named_axes, named, quote))
    return taken, dropped


def section_of(source):
    return (source.provenance or {}).get("section_number")


def windows_of(sources: list, fits: Callable) -> list:
    """The passages in document order, one section with its tables and
    figures to a request, split where *fits* says the section is too long. A
    passage that does not fit alone goes alone, and its request says so
    (`ask` returns CUT when the prompt leaves no room). Packed to fit, about
    73 passages went to one request and the map named the passage of 38 % of
    the coordinates read afterwards (test of 2026-10-23)."""
    out, current = [], []
    for source in sources:
        if current and (section_of(source) != section_of(current[0])
                        or not fits(current + [source])):
            out.append(current)
            current = []
        current.append(source)
    if current:
        out.append(current)
    return out


class Places:
    """(document_id, axes) -> the passages that answer them, or None.

    *ask(window, document_id)* is one request: the reply as a dict, CUT, or
    None when it could not be read. *passages_of(document_id)* is every
    passage of the document in its order. *pool* runs a document's
    requests side by side (None: one after another). *store* is where maps
    are kept.
    """

    def __init__(self, ask: Callable, passages_of: Callable, fits: Callable,
                 axes: dict, parameters: dict, key: str, *,
                 store: Optional[Path] = None, pool=None, trace=None):
        self.ask = ask
        self.passages_of = passages_of
        self.fits = fits
        self.axes = axes
        self.parameters = parameters
        self.key = key
        self.store = Path(store) if store else None
        self.pool = pool
        self.trace = trace
        self._maps: dict = {}
        self._locks: dict = {}
        self._guard = threading.Lock()

    def __call__(self, document_id: int, axes) -> Optional[list]:
        """The passages that answer any of *axes*, in document order, or
        None. Only the keys are kept per document; the passages are read
        again, from the run's shared store."""
        keys = self.map_for(document_id).keys_of(list(axes))
        if keys is None:
            return None
        return [s for s in self.passages_of(document_id)
                if (s.owner_kind, s.owner_id) in keys]

    def map_for(self, document_id: int) -> Map:
        with self._guard:
            lock = self._locks.setdefault(document_id, threading.Lock())
        with lock:
            found = self._maps.get(document_id)
            if found is None:
                found = self._load(document_id) or self._build(document_id)
                self._maps[document_id] = found
            return found

    def _path(self, document_id: int) -> Optional[Path]:
        return self.store / f"{document_id}.json" if self.store else None

    def _load(self, document_id: int) -> Optional[Map]:
        path = self._path(document_id)
        if path is None or not path.is_file():
            return None
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if kept.get("key") != self.key or not kept.get("complete"):
            return None
        sources = self.passages_of(document_id)
        at = {(s.owner_kind, s.owner_id) for s in sources}
        if {tuple(p["owner"]) for p in kept.get("places", ())} - at:
            return None                 # the document changed since
        built = Map(True, {a: set() for a in self.axes},
                    {p: set() for p in self.parameters})
        for place in kept.get("places", ()):
            owner = tuple(place["owner"])
            for axis in place.get("axes", ()):
                built.by_axis.setdefault(axis, set()).add(owner)
            for parameter in place.get("parameters", ()):
                built.by_parameter.setdefault(parameter, set()).add(owner)
        return built

    def _ask_window(self, window: list, document_id: int) -> tuple:
        """(places, dropped, complete) of one window, halved while its
        reply does not fit."""
        reply = self.ask(window, document_id)
        if reply == CUT and len(window) > 1:
            cut = len(window) // 2
            a = self._ask_window(window[:cut], document_id)
            b = self._ask_window(window[cut:], document_id)
            return a[0] + b[0], a[1] + b[1], a[2] and b[2]
        if not isinstance(reply, dict):
            return [], 0, False
        taken, dropped = read_hits(reply, window, self.axes, self.parameters)
        return taken, dropped, True

    def _build(self, document_id: int) -> Map:
        sources = self.passages_of(document_id)
        windows = windows_of(sources, self.fits)
        if self.pool is None:
            results = [self._ask_window(w, document_id) for w in windows]
        else:
            futures = [self.pool.submit(self._ask_window, w, document_id)
                       for w in windows]
            results = [f.result() for f in futures]
        built = Map(all(r[2] for r in results),
                    {a: set() for a in self.axes},
                    {p: set() for p in self.parameters})
        places, dropped = [], 0
        for taken, lost, _done in results:
            dropped += lost
            for source, axes, parameters, quote in taken:
                owner = (source.owner_kind, source.owner_id)
                for axis in axes:
                    built.by_axis[axis].add(owner)
                for parameter in parameters:
                    built.by_parameter[parameter].add(owner)
                places.append({"owner": list(owner), "axes": axes,
                               "parameters": parameters, "quote": quote})
        failed = sum(1 for r in results if not r[2])
        log.info("   places %s: %d passage(s) in %d request(s), %d place(s) "
                 "taken, %d not taken, %d request(s) unread%s", document_id,
                 len(sources), len(windows), len(places), dropped, failed,
                 "" if built.complete else " -- the map is not used")
        if self.trace is not None:
            self.trace("places", document_id, passages=len(sources),
                       windows=len(windows), places=len(places),
                       dropped=dropped, unread=failed,
                       complete=built.complete,
                       by_axis={a: len(k) for a, k in built.by_axis.items()},
                       by_parameter={p: len(k) for p, k
                                     in built.by_parameter.items()})
        path = self._path(document_id)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            archive.keep(path)
            path.write_text(json.dumps(
                {"key": self.key, "complete": built.complete,
                 "places": places}, ensure_ascii=False), encoding="utf-8")
        return built


def nearest_first(pool: list, rows_at: list) -> list:
    """*pool* ordered by its distance to the rows' own sections, the
    document's order among equals. *rows_at* are section numbers."""
    rows_at = [n for n in rows_at if isinstance(n, int)]

    def distance(item) -> tuple:
        index, source = item
        number = (source.provenance or {}).get("section_number")
        if not rows_at or not isinstance(number, int):
            return (0, index)
        return (min(abs(number - at) for at in rows_at), index)

    return [source for _i, source in sorted(enumerate(pool), key=distance)]
