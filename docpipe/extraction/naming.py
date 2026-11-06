"""
naming.py: Which of a document's names mean the same thing, asked once the
document is read (owner decisions 2026-11-06).

A coordinate the spec marks `merged`, and a free-text value so marked, are
read as the document prints them: the scenario of a number is "the Zero
Carbon scenario" in one sentence and "LCEO Zero Carbon" in a table. Once a
document is folded, every name read for a kind of thing, the word `merged`
names ("scenario"), is asked on its own (owner decision 2026-11-06, after
two probes in which one request over all 145 to 158 names gave every name
the same simplest answer: once the nearest other name, once itself). Each
request shows the one name with the places it was read at: its quote and
500 characters before and after it in the passage it stands in
(`CONTEXT_CHARS`), stretches of one passage that overlap shown once. Beside
it stand all the document's names, each under a number (N1, N2, …) and with
the quote it was read with, the one asked among them. The model answers
with numbers, never copying a name: the name's own number, the number of
another name of the same thing, or several where it means several things
("the EC LTS scenarios"). A name whose thing has no other name in the
request means itself, even where the model knows the thing by a name the
request does not show. Names of the same thing are one thing, called by the
name the others point to; a name of several things stands for each of them
(`meanings`). Each row keeps the name it was read as and gets the names of
what it means under `<coordinate>_means`, `value_means` for its own value,
and the graph writes the row to each of them.

Nothing is checked beyond the list: a reply without "means", or with a
number the request did not show, is asked once more with its reason
(`key_missing`, `name_not_listed`); a name answered in neither means itself.
The answer quotes nothing, since each name keeps the quote it was read with
(owner decision 2026-11-06). A request that does not fit its room is asked
against each half of the other names, and what the halves name is the
name's answer: a name that names itself beside another means the other
(`meanings`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from . import fields
from .verify import flat
from .wording import say

NAMING_PROMPT_ID = "extraction/naming"
# Characters of a passage shown before and after a quote (owner decision
# 2026-11-06).
CONTEXT_CHARS = 500
CUT = "cut_off"
VALUE = "value"
MEANS = "_means"


def merged_slots(spec) -> dict:
    """{parameter uri: {key: kind}} of what *spec* merges: `VALUE` for a
    parameter's own value, the coordinate's name for an axis, each with the
    kind of thing its names name."""
    out: dict = {}
    for parameter in spec.parameters:
        kinds = {}
        if getattr(parameter, "merged", None):
            kinds[VALUE] = parameter.merged
        for name, axis in parameter.axes.items():
            if getattr(axis, "merged", None):
                kinds[name] = axis.merged
        if kinds:
            out[parameter.uri] = kinds
    return out


def merges(spec) -> bool:
    """Does *spec* merge any names?"""
    return bool(merged_slots(spec))


def read_name(row: dict, key: str) -> Optional[tuple]:
    """(name, owner, quote) of what *row* read under *key*, its own value
    for `VALUE`, or None where it read no name there."""
    if key == VALUE:
        name, quote = row.get("value"), row.get("quote")
        provenance = row.get("provenance") or {}
        owner = (provenance.get("owner_kind"), provenance.get("owner_id"))
    else:
        if row.get(f"{key}_state") != fields.READ:
            return None
        name, quote = row.get(key), row.get(f"{key}_quote")
        source = row.get(f"{key}_source")
        owner = tuple(source) if isinstance(source, (list, tuple)) \
            and len(source) == 2 else (None, None)
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip(), owner, quote if isinstance(quote, str) else ""


def names_of(rows: list, slots: dict) -> dict:
    """{kind: {name: [(owner, quote)]}} of every name *rows* read for what
    is merged (`merged_slots`), in the order the rows read them."""
    out: dict = {}
    for row in rows:
        for key, kind in (slots.get(row.get("parameter")) or {}).items():
            read = read_name(row, key)
            if read is None:
                continue
            name, owner, quote = read
            places = out.setdefault(kind, {}).setdefault(name, [])
            if (owner, quote) not in places:
                places.append((owner, quote))
    return out


def _span(text: str, quote: str) -> Optional[tuple]:
    """(start, end) of *quote* in *text*, whatever whitespace stands
    between its words, or None."""
    if not text or not quote:
        return None
    at = text.find(quote)
    if at >= 0:
        return at, at + len(quote)
    words = [re.escape(word) for word in flat(quote).split(" ") if word]
    hit = re.search(r"\s+".join(words), text) if words else None
    return hit.span() if hit else None


def located(source, quote: str) -> tuple:
    """(which, text, start, end): the text of *source* *quote* stands in and
    where, *which* in the order they are tried: 0 the passage's own, 1 the
    heading of its section, 2 the passage brought into one shape with the
    quote (`verify.flat`) where only that shape holds it, 3 the quote alone
    where none does."""
    if source is not None:
        span = _span(source.text or "", quote)
        if span is not None:
            return (0, source.text or "", *span)
        title = (source.provenance or {}).get("section_title") or ""
        span = _span(title, quote)
        if span is not None:
            return (1, title, *span)
        same, wanted = flat(source.text or ""), flat(quote)
        at = same.find(wanted) if wanted else -1
        if at >= 0:
            return 2, same, at, at + len(wanted)
    return 3, quote, 0, len(quote)


def places_of(names: dict, passages: dict) -> tuple:
    """({place: text}, {name: [place]}) of *names* ({name: [(owner,
    quote)]}): each quote with `CONTEXT_CHARS` before and after it in the
    text it stands in, stretches of one text that overlap joined into one
    place, the places in the order of the plan."""
    order = {owner: index for index, owner in enumerate(passages)}
    spans: dict = {}
    taken: list = []
    for name, places in names.items():
        for owner, quote in places:
            which, text, start, end = located(passages.get(owner), quote)
            spans.setdefault((owner, which, text), []).append(
                (max(0, start - CONTEXT_CHARS),
                 min(len(text), end + CONTEXT_CHARS)))
            taken.append((name, owner, text, start, end))
    joined: list = []
    for (owner, _which, text), parts in sorted(
            spans.items(), key=lambda item: (order.get(item[0][0],
                                                       len(order)),
                                             item[0][1], item[0][2])):
        parts.sort()
        start, end = parts[0]
        for one, other in parts[1:]:
            if one <= end:
                end = max(end, other)
            else:
                joined.append((owner, text, start, end))
                start, end = one, other
        joined.append((owner, text, start, end))
    shown = {f"P{index + 1}": text[start:end]
             for index, (_owner, text, start, end) in enumerate(joined)}
    at: dict = {name: [] for name in names}
    for name, owner, text, start, end in taken:
        for index, (o, t, s, e) in enumerate(joined):
            if o == owner and t == text and s <= start and end <= e:
                place = f"P{index + 1}"
                if place not in at[name]:
                    at[name].append(place)
                break
    return shown, at


def numbered(order: list) -> dict:
    """{name: its number} of the names *order*: N1, N2, … in their order."""
    return {name: f"N{index + 1}" for index, name in enumerate(order)}


MEANT = "means"


def payload(kind: str, name: str, places: list, numbers: dict, quotes: dict,
            corrections: Optional[dict] = None) -> dict:
    """One request: what the names name, the name asked under its number
    (*numbers*, `numbered`) with the texts of the places it was read at
    (*places*), and every name under its number with the quote it was read
    with (*quotes*); with *corrections* the same request asked once more."""
    out = {"kind": kind,
           "name": {"number": numbers[name], "name": name,
                    "places": list(places)},
           "names": {number: {"name": one, "quote": quotes.get(one, "")}
                     for one, number in numbers.items()}}
    if corrections:
        out["corrections"] = corrections
    return out


def response_format(numbers: list) -> dict:
    """The numbers of the names the name asked means, under `MEANT`: its
    own, another's or several, each one of *numbers*."""
    schema = {"type": "object",
              "properties": {MEANT: {
                  "type": "array", "minItems": 1,
                  "items": {"type": "string", "enum": list(numbers)}}},
              "required": [MEANT], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "naming_reply", "schema": schema}}


def example_of(numbers: dict, name: str) -> dict:
    """The reply the prompt shows for the request about *name*: the name
    meaning itself, in its own number (owner decision 2026-11-06: every
    request's example is its own reply)."""
    return {MEANT: [numbers[name]]}


def means_of(reply, numbers: dict) -> tuple:
    """([names the name asked means], None) of a naming *reply*
    ({"means": [numbers]}) whose list holds only numbers the request showed,
    turned back into names; (None, what was wrong) of any other: a reply
    without "means" (`key_missing`), or one whose list is empty or names a
    number the request did not show (`name_not_listed`)."""
    name_of = {number: one for one, number in numbers.items()}
    if not isinstance(reply, dict) or MEANT not in reply:
        return None, {"what": say("key_missing", key=MEANT)}
    given = reply[MEANT]
    if isinstance(given, list) and given and all(
            isinstance(one, str) and one in name_of for one in given):
        return list(dict.fromkeys(name_of[one] for one in given)), None
    return None, {"value": given, "what": say(
        "name_not_listed", name=MEANT,
        given=json.dumps(given, ensure_ascii=False))}


def meanings(order: list, answers: dict) -> dict:
    """{name: [the names of the things it means]} of the names *order*,
    from *answers* ({name: [names it means]}): a name answered with one
    other name is a name of that one's thing, and a thing is called by the
    name of it that answered itself, else by its first; a name answered with
    several names stands for each of their things. An answer with no name of
    *order* means the name itself."""
    index = {name: at for at, name in enumerate(order)}
    meant = {name: [one for one in dict.fromkeys(answers.get(name) or ())
                    if one in index] or [name] for name in order}
    parent = {name: name for name in order}

    def root(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name
    for name in order:
        if len(meant[name]) == 1 and meant[name][0] != name:
            one, other = root(name), root(meant[name][0])
            if one != other:
                first, later = sorted((one, other), key=index.get)
                parent[later] = first
    members: dict = {}
    for name in order:
        members.setdefault(root(name), []).append(name)
    called = {top: next((name for name in group if meant[name] == [name]),
                        group[0])
              for top, group in members.items()}
    several = {top: [one for name in group if len(meant[name]) > 1
                     for one in meant[name]]
               for top, group in members.items()}

    def things(top: str, seen: frozenset) -> list:
        if not several[top]:
            return [called[top]]
        out: list = []
        for one in several[top]:
            other = root(one)
            if other == top or other in seen:
                continue
            for thing in things(other, seen | {top}):
                if thing not in out:
                    out.append(thing)
        return out or [called[top]]
    return {name: things(root(name), frozenset()) for name in order}


def mark(rows: list, slots: dict, meant: dict) -> int:
    """Each row's names under `<key>_means` (`VALUE`: `value_means`): the
    names of the things it means (*meant*, {kind: {name: [names]}}). How
    many names were marked."""
    marked = 0
    for row in rows:
        for key, kind in (slots.get(row.get("parameter")) or {}).items():
            read = read_name(row, key)
            things = (meant.get(kind) or {}).get(read[0]) if read else None
            if things:
                row[f"{key}{MEANS}"] = list(things)
                marked += 1
    return marked


class Namer:
    """(document_id, rows, passages) -> {kind: {name: [names it means]}},
    each row marked on the way (`mark`).

    *ask(payload, shape, document_id, kind, example)* is one request: the
    reply as a dict, CUT, or None, *example* the reply its prompt shows
    (`example_of`). *passages* is {(owner kind, owner id): Source} of the
    document in the order of the plan. The requests of one kind run in
    *pool* where one is given.
    """

    def __init__(self, spec, ask: Callable, trace: Optional[Callable] = None,
                 pool=None):
        self.slots = merged_slots(spec)
        self.ask = ask
        self.trace = trace
        self.pool = pool

    def __call__(self, document_id: int, rows: list, passages: dict) -> dict:
        meant: dict = {}
        for kind, names in names_of(rows, self.slots).items():
            order = list(names)
            answers = self.answered(document_id, kind, order, names, passages)
            meant[kind] = meanings(order, answers)
            if self.trace is not None:
                things = {thing for each in meant[kind].values()
                          for thing in each}
                self.trace("naming", document_id, kind=kind, names=len(order),
                           things=len(things),
                           several=sum(1 for each in meant[kind].values()
                                       if len(each) > 1))
        mark(rows, self.slots, meant)
        return meant

    def answered(self, document_id: int, kind: str, order: list,
                 names: dict, passages: dict) -> dict:
        """{name: [names it means]} of the names *order*, one request per
        name (owner decision 2026-11-06); a name no reply answered is left
        out and means itself (`meanings`)."""
        if len(order) < 2:
            return {}
        shown, at = places_of({name: names[name] for name in order}, passages)
        quotes = {name: next((quote for _owner, quote in names[name] if quote),
                             name) for name in order}

        def one(name: str):
            places = [shown[place] for place in at.get(name, [])]
            return name, self._means(document_id, kind, name, order, places,
                                     quotes)
        if self.pool is None:
            got = [one(name) for name in order]
        else:
            got = list(self.pool.map(one, order))
        return {name: means for name, means in got if means}

    def _means(self, document_id: int, kind: str, name: str, among: list,
               places: list, quotes: dict) -> Optional[list]:
        """[the names *name* means] of the names *among*, it among them: one
        request, and one more where the reply was wrong; None where neither
        answered. A request that does not fit is asked against each half of
        the other names, and the names the halves give are the answer; where
        they give *name* beside another, it means the other (`meanings`)."""
        numbers = numbered(among)
        shape = response_format(list(numbers.values()))
        example = example_of(numbers, name)
        corrections = None
        for _ in range(2):
            reply = self.ask(payload(kind, name, places, numbers, quotes,
                                     corrections),
                             shape, document_id, kind, example)
            if reply == CUT:
                return self._halves(document_id, kind, name, among, places,
                                    quotes)
            if not isinstance(reply, dict):
                return None
            means, wrong = means_of(reply, numbers)
            if means is not None:
                return means
            corrections = wrong
        return None

    def _halves(self, document_id: int, kind: str, name: str, among: list,
                places: list, quotes: dict) -> Optional[list]:
        others = [one for one in among if one != name]
        if len(others) < 2:
            if self.trace is not None:
                self.trace("naming", document_id, kind=kind, names=len(among),
                           why=CUT)
            return None
        half = len(others) // 2
        joined: list = []
        for part in (others[:half], others[half:]):
            got = self._means(document_id, kind, name, [name] + part, places,
                              quotes) or []
            joined.extend(one for one in got if one not in joined)
        return joined or None
