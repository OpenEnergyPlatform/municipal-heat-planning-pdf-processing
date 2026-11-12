"""
thread.py: Each request with exactly the words of its own task (owner
decisions 2026-11-07).

A prompt file holds what every request of its kind is told and parts only
some are told, each opened by a marker line and running to the next one:

- "<!-- with: <key> ... -->": what a field means that only some requests
  carry, such as the headings up to a value or the plan's settings; part of
  the system prompt of a request whose message carries one of these fields
  (`Parts.system`);
- "<!-- follow-up: <key> ... -->": the words of a message that follows an
  answer in the compute step's conversation and carries one of these
  fields, such as what a search fetched; never part of a system prompt
  (`Parts.follow_up`).

No request is told what another one may bring (owner decision 2026-11-07:
"Jede Anfrage sollte genau die Prompt bekommen, die beschreibt, was sie tun
soll").

Where a rule chooses how a request asks, the words of each choice stand
side by side, and a request is told those of the choice its rule has in its
step (owner decision 2026-11-12: a second wording of a sentence, and the
rule chooses which is sent):

    <!-- way: answer_with=address -->
    ... with the address of its line ...
    <!-- way: answer_with=quote -->
    ... with the words of its line, character for character ...
    <!-- /way -->

Each marker stands on a line of its own; a group holds one way for every
choice of its rule and is closed by "<!-- /way -->" (`chosen`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Iterable, Optional

WITH, FOLLOW_UP = "with", "follow-up"
# A part's marker: its kind and the names after it, on a line of its own.
MARK = re.compile(r"^<!-- (with|follow-up): ([A-Za-z_][A-Za-z_ ]*?)"
                  r" *-->[ \t]*$", re.MULTILINE)
# A way's marker, "<!-- way: rule=choice -->", or the close of a group of
# ways, "<!-- /way -->", each a line of its own with its line break.
WAY = re.compile(r"^<!-- (?:way: ([A-Za-z_]\w*)=([\w-]+)|(/way)) -->"
                 r"[ \t]*(?:\n|\Z)", re.MULTILINE)
# The reply a part shows (`runner.system_text`).
EXAMPLE = "{{example}}"


def ways_of(text: str, where: str = "") -> list:
    """[(start, end, rule, {choice: words})] of the groups of ways in
    *text*, in its order, *start* and *end* spanning a group from its first
    marker to the line break of its close. LookupError where a group is not
    closed, a close has no group, or a group names two rules or one choice
    twice."""
    groups: list = []
    group: Optional[dict] = None
    for mark in WAY.finditer(text):
        if group is not None:
            group["ways"][group["choice"]] = text[group["from"]:mark.start()]
        if mark.group(3) is not None:
            if group is None:
                raise LookupError(f"{where}: a <!-- /way --> closes no way")
            groups.append((group["start"], mark.end(), group["rule"],
                           group["ways"]))
            group = None
            continue
        rule, choice = mark.group(1), mark.group(2)
        if group is None:
            group = {"start": mark.start(), "rule": rule, "ways": {}}
        elif rule != group["rule"]:
            raise LookupError(f"{where}: one group of ways names the rules "
                              f"{group['rule']!r} and {rule!r}")
        if choice in group["ways"]:
            raise LookupError(f"{where}: two ways for {rule}={choice}")
        group["choice"], group["from"] = choice, mark.end()
    if group is not None:
        raise LookupError(f"{where}: the ways of {group['rule']!r} are not "
                          f"closed by <!-- /way -->")
    return groups


def _with_ways(text: str, pick, where: str) -> str:
    """*text* with each group of ways replaced by the words *pick(rule,
    ways)* says."""
    groups = ways_of(text, where)
    if not groups:
        return text
    out, at = [], 0
    for start, end, rule, ways in groups:
        out += [text[at:start], pick(rule, ways)]
        at = end
    return "".join(out + [text[at:]])


def chosen(text: str, where: str = "") -> str:
    """*text* with each group of ways replaced by the words of the way its
    rule has now, read in the step of the request that is asked
    (`rules.get`). Text without ways is returned as it is."""
    from .. import rules

    def pick(rule: str, ways: dict) -> str:
        value = rules.get(rule)
        if value not in ways:
            raise LookupError(f"{where}: no way for {rule}={value!r}")
        return ways[value]
    return _with_ways(text, pick, where)


def widest(text: str, where: str = "") -> str:
    """*text* with each group of ways replaced by its longest way, in
    words: the most a request of it can be told, whatever its rule says."""
    return _with_ways(
        text, lambda rule, ways: max(ways.values(),
                                     key=lambda words: len(words.split())),
        where)


def check_ways(text: str, where: str = "",
               known: Optional[dict] = None) -> None:
    """LookupError where a group of ways in *text* names a rule that is
    none of *known* (the rules of the ambient profile where not given) or
    has no choices, or does not hold exactly one way for each choice of its
    rule: a request would be sent words its rule never chooses, or none."""
    groups = ways_of(text, where)
    if not groups:
        return
    if known is None:
        from .. import rules
        from ..profile import active_profile
        known = rules.registry(active_profile())
    for _start, _end, name, ways in groups:
        rule = known.get(name)
        if rule is None or not rule.choices:
            raise LookupError(f"{where}: ways for {name!r}, which is no "
                              f"rule with choices")
        if set(ways) != set(rule.choices):
            raise LookupError(
                f"{where}: the ways of {name!r} are {sorted(ways)}, and "
                f"its choices are {sorted(rule.choices)}")


@dataclass(frozen=True)
class Part:
    """One marked part of a prompt file: its kind, the fields it is about,
    and its words."""
    kind: str
    keys: tuple
    text: str


@dataclass(frozen=True)
class Parts:
    """A prompt file cut at its markers (`cut`): what every request of its
    kind is told (*common*) and its parts in the order of the file."""
    prompt: object
    common: str
    parts: tuple

    def of(self, kind: str) -> list:
        return [part for part in self.parts if part.kind == kind]

    def system(self, carried: Iterable = ()):
        """The system prompt of a request whose message carries the fields
        *carried*: what every request is told, then the part of each field
        it carries, in the order of the file. A field no part names is told
        nothing beyond what every request is told. Of each group of ways,
        the way its rule has in the request's step (`chosen`)."""
        carried = set(carried)
        where = self.prompt.id
        pieces = [chosen(self.common, where).strip()] + [
            chosen(part.text, where).strip() for part in self.of(WITH)
            if carried & set(part.keys)]
        return replace(self.prompt,
                       text="\n\n".join(p for p in pieces if p) + "\n")

    def words(self, carried: Iterable) -> str:
        """The words of a follow-up that carries the fields *carried*: the
        follow-up part of each, in the order of the file, each part once.
        LookupError where a field has none: the model would get a field
        nobody told it the meaning of."""
        carried = list(carried)
        parts = [part for part in self.of(FOLLOW_UP)
                 if set(carried) & set(part.keys)]
        told = {key for part in parts for key in part.keys}
        missing = [key for key in carried if key not in told]
        if missing:
            raise LookupError(f"{self.prompt.id}: no follow-up part for "
                              f"{missing}")
        return "\n\n".join(chosen(part.text, self.prompt.id).strip()
                           for part in parts)

    def follow_up(self, follow: dict, example: Optional[dict] = None) -> str:
        """A follow-up message: its words (`words`), then the fields that
        carry something, as JSON; a field whose value is None is told by
        its words alone. *example* is the reply of the request the message
        asks, written in where the words have the place for one; words with
        that place and no example are an error before anything is sent."""
        if not follow:
            raise ValueError(f"{self.prompt.id}: a follow-up carries at "
                             f"least one field")
        words = self.words(follow)
        words = shown_with(words, example if EXAMPLE in words else None,
                           self.prompt.id)
        data = {key: value for key, value in follow.items()
                if value is not None}
        if not data:
            return words
        return words + "\n\n" + json.dumps(data, ensure_ascii=False,
                                            indent=2)


def shown_with(text: str, example: Optional[dict], where: str) -> str:
    """*text* with the reply it shows written in where it has the place for
    one; a place without an example, or an example without a place, is an
    error before anything is sent."""
    if EXAMPLE not in text:
        if example is not None:
            raise KeyError(f"{where}: an example for words that show none")
        return text
    if example is None:
        raise KeyError(f"{where}: words that show a reply and no example")
    return text.replace(EXAMPLE, json.dumps(example, ensure_ascii=False,
                                            separators=(",", ":")))


def cut(prompt, follows: Iterable = ()) -> Parts:
    """*prompt* cut at its markers. *follows* are the fields the code sends
    follow-ups with, each of which needs a follow-up part. A part marked
    twice, a follow-up field without its words, or a group of ways that is
    not one way for each choice of its rule (`check_ways`) raises
    LookupError, which the run raises at its start."""
    text = prompt.text
    marks = list(MARK.finditer(text))
    common = text[:marks[0].start()] if marks else text
    check_ways(common, prompt.id)
    parts: list = []
    seen: set = set()
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) \
            else len(text)
        kind, keys = mark.group(1), tuple(mark.group(2).split())
        for key in keys:
            if (kind, key) in seen:
                raise LookupError(f"{prompt.id}: two {kind} parts for "
                                  f"{key!r}")
            seen.add((kind, key))
        check_ways(text[mark.end():end],
                   f"{prompt.id} ({kind}: {' '.join(keys)})")
        parts.append(Part(kind, keys, text[mark.end():end]))
    out = Parts(prompt, common, tuple(parts))
    for key in follows:
        out.words([key])
    return out
