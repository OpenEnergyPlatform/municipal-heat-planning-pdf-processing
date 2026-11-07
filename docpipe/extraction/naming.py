"""
naming.py: Which of a document's names mean the same thing, asked once the
document is read (owner decisions 2026-11-06).

A coordinate the spec marks `merged`, and a free-text value so marked, are
read as the document prints them: the scenario of a number is "the Zero
Carbon scenario" in one sentence and "LCEO Zero Carbon" in a table. Once a
document is folded, the names read for a kind of thing, the word `merged`
names ("scenario"), are put together in two steps (owner decision
2026-11-06, after a probe that asked every name against all 240 names of a
publication: answers mostly right, cost growing with the square of the
names).

First the candidates, from two sources. One request shows every name under
a number (N1, N2, …) with the quote it was read with and asks for the
groups of names that may name the same thing, generously, a name with no
partner left out (`groups_payload`); one that does not fit is asked for
each half of the names. And every name is embedded with the text around it
where it was first read, `EMBED_CONTEXT_CHARS` before and after it
(`context_of`): its `NEIGHBOURS` nearest names are its candidates too, and
so is every name that has it among its nearest (`candidates`).

Then every name is asked on its own against its candidates (owner decision
2026-11-06: "Je Name gegen seine Gruppe"): the request shows the one name
with the places it was read at, its quote and 500 characters before and
after it in the passage it stands in (`CONTEXT_CHARS`), stretches of one
passage that overlap shown once, and beside it its candidates under their
numbers with their quotes. The model answers with numbers, never copying a
name: every name of the same thing, its own included, or, where the name
stands for several things ("the EC LTS scenarios"), the names of each of
them without its own. Two names are one thing only where each gives the
other, and a thing is called by its first name; a name of several things
stands for each of them (`meanings`). A name with no candidate asks nothing
and means itself. Each row keeps the name it was read as and gets the names
of what it means under `<coordinate>_means`, `value_means` for its own
value, and the graph writes the row to each of them.

Nothing is checked beyond the list: a reply without its key, or with a
number the request did not show, is asked once more with its reason
(`key_missing`, `name_not_listed`); a name answered in neither means itself,
and a request over all names answered in neither gives no groups. The
answer quotes nothing, since each name keeps the quote it was read with
(owner decision 2026-11-06). A request about one name that does not fit its
room is asked against each half of its candidates, and what the halves name
is the name's answer.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from . import fields
from .graphkit import NOT_IN_GRAPH
from .thread import CORRECTIONS, Thread
from .verify import flat
from .wording import say

NAMING_PROMPT_ID = "extraction/naming"
GROUPS_PROMPT_ID = "extraction/naming_groups"
# The naming's prompts: the request over all names for the candidates, and
# the request about one name.
NAMING_PROMPT_IDS = (GROUPS_PROMPT_ID, NAMING_PROMPT_ID)
# The field of the message that follows a wrong answer (owner decisions
# 2026-11-07).
FOLLOWS = (CORRECTIONS,)
# Characters of a passage shown before and after a quote (owner decision
# 2026-11-06).
CONTEXT_CHARS = 500
# Characters before and after a name embedded with it, and how many nearest
# names are its candidates (owner decisions 2026-11-06).
EMBED_CONTEXT_CHARS = 100
NEIGHBOURS = 15
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
    # An out: entry, such as the "status quo" a coordinate of names takes
    # beside them (owner decision 2026-11-07), names nothing.
    if not isinstance(name, str) or not name.strip() \
            or name.startswith(NOT_IN_GRAPH):
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


def context_of(name: str, places: list, passages: dict) -> str:
    """What is embedded of *name* (owner decision 2026-11-06): the name, and
    the text around it where it was first read (*places*, [(owner,
    quote)]), `EMBED_CONTEXT_CHARS` before and after it; around its quote
    where the quote does not print the name."""
    owner, quote = places[0] if places else (None, "")
    _which, text, start, end = located(passages.get(owner), quote or name)
    inside = _span(text[start:end], name)
    if inside is not None:
        start, end = start + inside[0], start + inside[1]
    around = text[max(0, start - EMBED_CONTEXT_CHARS):end + EMBED_CONTEXT_CHARS]
    return f"{name}\n{around}"


def neighbours(vectors: list, many: int) -> list:
    """[[the indices of the *many* vectors nearest to each, nearest first]]
    of *vectors*, by the cosine of their angle; no vector is its own."""
    import numpy as np
    matrix = np.asarray(vectors, dtype=float)
    if matrix.ndim != 2 or len(matrix) < 2:
        return [[] for _ in range(len(matrix))]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.where(norms == 0, 1.0, norms)
    similar = matrix @ matrix.T
    np.fill_diagonal(similar, -np.inf)
    return [[int(at) for at in np.argsort(-row, kind="stable")[:many]
             if np.isfinite(row[at])] for row in similar]


def candidates(order: list, groups: list, near: dict) -> dict:
    """{name: [the names it is asked against, in the order of *order*]}
    (owner decision 2026-11-06: both sources): the other names of each
    group of the request over all names it stands in (*groups*, [[names]]),
    its nearest names by embedding (*near*, {name: [names]}), and every
    name that has it among its nearest."""
    beside: dict = {name: set() for name in order}
    for group in groups:
        members = [name for name in group if name in beside]
        for name in members:
            beside[name].update(one for one in members if one != name)
    for name, others in near.items():
        for other in others:
            if name in beside and other in beside and other != name:
                beside[name].add(other)
                beside[other].add(name)
    return {name: [one for one in order if one in beside[name]]
            for name in order}


GROUPS = "groups"


def groups_payload(kind: str, numbers: dict, quotes: dict) -> dict:
    """The request over all names: what they name, and every name under
    its number (*numbers*, `numbered`) with the quote it was read with
    (*quotes*). What was wrong with its answer follows that answer
    (`FOLLOWS`, owner decisions 2026-11-07)."""
    return {"kind": kind,
            "names": {number: {"name": one, "quote": quotes.get(one, "")}
                      for one, number in numbers.items()}}


def groups_format(numbers: list) -> dict:
    """The groups of names that may name the same thing, under `GROUPS`:
    each a list of two or more of *numbers*."""
    schema = {"type": "object",
              "properties": {GROUPS: {
                  "type": "array",
                  "items": {"type": "array", "minItems": 2,
                            "items": {"type": "string",
                                      "enum": list(numbers)}}}},
              "required": [GROUPS], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "naming_groups_reply", "schema": schema}}


def groups_example(numbers: dict) -> dict:
    """The reply the prompt shows for the request over all names: one group
    of its first two names (owner decision 2026-11-06: every request's
    example is its own reply). A group the model copies from it is a
    candidate, which the request about each name decides."""
    return {GROUPS: [list(numbers.values())[:2]]}


def groups_of(reply, numbers: dict) -> tuple:
    """([[names]], None) of a reply to the request over all names whose
    groups name only numbers it showed, each group of two names or more;
    (None, what was wrong) of any other: a reply without `GROUPS`
    (`key_missing`), or one whose groups are no lists of shown numbers
    (`name_not_listed`)."""
    name_of = {number: one for one, number in numbers.items()}
    if not isinstance(reply, dict) or GROUPS not in reply:
        return None, {"what": say("key_missing", key=GROUPS)}
    given = reply[GROUPS]
    if isinstance(given, list) and all(
            isinstance(group, list) and all(
                isinstance(one, str) and one in name_of for one in group)
            for group in given):
        groups = [list(dict.fromkeys(name_of[one] for one in group))
                  for group in given]
        return [group for group in groups if len(group) > 1], None
    return None, {"value": given, "what": say(
        "groups_not_listed", name=GROUPS,
        given=json.dumps(given, ensure_ascii=False))}


MEANT = "means"


def payload(kind: str, name: str, places: list, numbers: dict,
            quotes: dict) -> dict:
    """One request: what the names name, the name asked under its number
    (*numbers*, `numbered`) with the texts of the places it was read at
    (*places*), and every name under its number with the quote it was read
    with (*quotes*). What was wrong with its answer follows that answer
    (`FOLLOWS`, owner decisions 2026-11-07)."""
    return {"kind": kind,
            "name": {"number": numbers[name], "name": name,
                     "places": list(places)},
            "names": {number: {"name": one, "quote": quotes.get(one, "")}
                      for one, number in numbers.items()}}


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
    from *answers* ({name: [names it gave]}, owner decision 2026-11-06): an
    answer that holds the name itself gives the other names of its thing,
    and so does an answer of one other name; two names are one thing only
    where each gives the other, and a thing is called by its first name in
    *order*. An answer of several names without the name itself stands for
    each of their things. An answer with no name of *order* means the name
    itself."""
    index = {name: at for at, name in enumerate(order)}
    meant = {name: [one for one in dict.fromkeys(answers.get(name) or ())
                    if one in index] or [name] for name in order}

    def same(name: str) -> set:
        given = meant[name]
        if name in given:
            return set(given) - {name}
        return set(given) if len(given) == 1 else set()
    sames = {name: same(name) for name in order}
    parent = {name: name for name in order}

    def root(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name
    for name in order:
        for other in sames[name]:
            if name in sames[other]:
                one, two = root(name), root(other)
                if one != two:
                    first, later = sorted((one, two), key=index.get)
                    parent[later] = first
    several = {name: meant[name] if name not in meant[name]
               and len(meant[name]) > 1 else [] for name in order}

    def things(name: str, seen: frozenset) -> list:
        if not several[name]:
            return [root(name)]
        out: list = []
        for one in several[name]:
            if one in seen:
                continue
            for thing in things(one, seen | {name}):
                if thing not in out:
                    out.append(thing)
        return out or [root(name)]
    return {name: things(name, frozenset()) for name in order}


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

    *ask(payload, shape, document_id, kind, example, thread, follow)* is the
    request about one name, *ask_groups* with the same arguments the
    request over all names (`groups_payload`), each a message of a
    conversation (`thread.Thread`): the first shows *payload*, a later one
    what was wrong with the answer it follows (*follow*, owner decisions
    2026-11-07); the reply as a dict, CUT, or None, *example* the reply its
    prompt shows. *embed(texts)* is a vector per text
    (`context_of`). Without *ask_groups*, or without *embed*, that source
    gives no candidates. *passages* is {(owner kind, owner id): Source} of
    the document in the order of the plan. The requests about the names of
    one kind run in *pool* where one is given.
    """

    def __init__(self, spec, ask: Callable, trace: Optional[Callable] = None,
                 pool=None, ask_groups: Optional[Callable] = None,
                 embed: Optional[Callable] = None):
        self.slots = merged_slots(spec)
        self.ask = ask
        self.ask_groups = ask_groups
        self.embed = embed
        self.trace = trace
        self.pool = pool

    def __call__(self, document_id: int, rows: list, passages: dict) -> dict:
        meant: dict = {}
        for kind, names in names_of(rows, self.slots).items():
            order = list(names)
            noted: dict = {}
            answers = self.answered(document_id, kind, order, names, passages,
                                    noted)
            meant[kind] = meanings(order, answers)
            if self.trace is not None:
                things = {thing for each in meant[kind].values()
                          for thing in each}
                self.trace("naming", document_id, kind=kind, names=len(order),
                           things=len(things),
                           several=sum(1 for each in meant[kind].values()
                                       if len(each) > 1), **noted)
        mark(rows, self.slots, meant)
        return meant

    def answered(self, document_id: int, kind: str, order: list,
                 names: dict, passages: dict,
                 noted: Optional[dict] = None) -> dict:
        """{name: [names it gave]} of the names *order*: one request per name
        against its candidates (`candidates`, owner decision 2026-11-06); a
        name with none, or that no reply answered, is left out and means
        itself (`meanings`). *noted* gets how many `groups` the request over
        all names gave and how many names were `asked`."""
        noted = {} if noted is None else noted
        if len(order) < 2:
            return {}
        shown, at = places_of({name: names[name] for name in order}, passages)
        quotes = {name: next((quote for _owner, quote in names[name] if quote),
                             name) for name in order}
        grouped = self._grouped(document_id, kind, order, quotes)
        near = self._near(order, names, passages)
        against = candidates(order, grouped, near)
        noted.update(groups=len(grouped),
                     asked=sum(1 for name in order if against[name]))

        def one(name: str):
            if not against[name]:
                return name, None
            places = [shown[place] for place in at.get(name, [])]
            among = [other for other in order
                     if other == name or other in against[name]]
            return name, self._means(document_id, kind, name, among, places,
                                     quotes)
        if self.pool is None:
            got = [one(name) for name in order]
        else:
            got = list(self.pool.map(one, order))
        return {name: means for name, means in got if means}

    def _grouped(self, document_id: int, kind: str, among: list,
                 quotes: dict) -> list:
        """[[names]] the request over the names *among* puts together: one
        request, and one more where the reply was wrong; none where neither
        answered. A request that does not fit is asked for each half of the
        names, and a group across the halves is left to the embedding."""
        if self.ask_groups is None or len(among) < 2:
            return []
        numbers = numbered(among)
        shape = groups_format(list(numbers.values()))
        example = groups_example(numbers)
        thread, follow = Thread(), None
        for _ in range(2):
            reply = self.ask_groups(groups_payload(kind, numbers, quotes),
                                    shape, document_id, kind, example,
                                    thread, follow)
            if reply == CUT:
                half = len(among) // 2
                if half < 2:
                    if self.trace is not None:
                        self.trace("naming", document_id, kind=kind,
                                   names=len(among), why=CUT)
                    return []
                return (self._grouped(document_id, kind, among[:half], quotes)
                        + self._grouped(document_id, kind, among[half:],
                                        quotes))
            if not isinstance(reply, dict):
                return []
            groups, wrong = groups_of(reply, numbers)
            if groups is not None:
                return groups
            follow = {CORRECTIONS: wrong}
        return []

    def _near(self, order: list, names: dict, passages: dict) -> dict:
        """{name: [its `NEIGHBOURS` nearest names]} by the embedding of each
        name with the text around it (`context_of`); none without *embed*."""
        if self.embed is None or len(order) < 2:
            return {}
        vectors = self.embed([context_of(name, names[name], passages)
                              for name in order])
        return {name: [order[at] for at in nearest]
                for name, nearest in zip(order, neighbours(vectors,
                                                           NEIGHBOURS))}

    def _means(self, document_id: int, kind: str, name: str, among: list,
               places: list, quotes: dict) -> Optional[list]:
        """[the names *name* gave] of the names *among*, it among them: one
        request, and one more where the reply was wrong; None where neither
        answered. A request that does not fit is asked against each half of
        the other names, and the halves' answers are joined (`_halves`)."""
        numbers = numbered(among)
        shape = response_format(list(numbers.values()))
        example = example_of(numbers, name)
        thread, follow = Thread(), None
        for _ in range(2):
            reply = self.ask(payload(kind, name, places, numbers, quotes),
                             shape, document_id, kind, example, thread,
                             follow)
            if reply == CUT:
                return self._halves(document_id, kind, name, among, places,
                                    quotes)
            if not isinstance(reply, dict):
                return None
            means, wrong = means_of(reply, numbers)
            if means is not None:
                return means
            follow = {CORRECTIONS: wrong}
        return None

    def _halves(self, document_id: int, kind: str, name: str, among: list,
                places: list, quotes: dict) -> Optional[list]:
        """The answers about *name* against each half of the other names,
        joined into one answer as a request over all of them would have
        given it: a half that gives the name alone has nothing of its thing
        and adds nothing. None where no half answered."""
        others = [one for one in among if one != name]
        if len(others) < 2:
            if self.trace is not None:
                self.trace("naming", document_id, kind=kind, names=len(among),
                           why=CUT)
            return None
        half = len(others) // 2
        joined: list = []
        answered = False
        for part in (others[:half], others[half:]):
            got = self._means(document_id, kind, name, [name] + part, places,
                              quotes)
            if not got:
                continue
            answered = True
            if got != [name]:
                joined.extend(one for one in got if one not in joined)
        if not answered:
            return None
        return joined or [name]
