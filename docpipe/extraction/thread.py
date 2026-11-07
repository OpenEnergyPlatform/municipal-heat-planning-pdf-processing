"""
thread.py: Each request with exactly the words of its own task, and what
asks again about an answer in the same conversation (owner decisions
2026-11-07).

A prompt file holds what every request of its kind is told and parts only
some are told, each opened by a marker line and running to the next one:

- "<!-- group: <name> -->": the words of one group of the spec's
  coordinates, the message that asks that group;
- "<!-- with: <key> ... -->": what a field means that only some requests
  carry, such as the table right before a passage; part of the system
  prompt of a conversation whose first message carries one of these fields;
- "<!-- follow-up: <key> ... -->": the words of a message that follows an
  answer and carries one of these fields, such as a correction or what a
  search fetched; never part of a system prompt.

What asks again about an answer goes after it in the same conversation
(`Thread`): a correction, the next value of a passage, the next group of a
value, the second reading of a value beside its passage, the next round of
a search. Its message brings only what is new, in the words of the parts
its fields need: the model sees what it answered, and no request is told
what another one may bring (owner decisions 2026-11-07: "Jede Anfrage
sollte genau die Prompt bekommen, die beschreibt, was sie tun soll", and the
model should see its last answer "anstatt das da endlos Kontext
reingeballert wird"). A call still sends the whole conversation; a server
that keeps what it has read reads its beginning once.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

GROUP, WITH, FOLLOW_UP = "group", "with", "follow-up"
# What a follow-up carries that tells the model what was wrong with the
# answer it follows.
CORRECTIONS = "corrections"
# A part's marker: its kind and the names after it, on a line of its own.
MARK = re.compile(r"^<!-- (group|with|follow-up): ([A-Za-z_][A-Za-z_ ]*?)"
                  r" *-->[ \t]*$", re.MULTILINE)
# The reply a part shows (`runner.system_text`).
EXAMPLE = "{{example}}"


@dataclass(frozen=True)
class Part:
    """One marked part of a prompt file: its kind, the group or the fields
    it is about, and its words."""
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

    @property
    def groups(self) -> tuple:
        return tuple(part.keys[0] for part in self.of(GROUP))

    def system(self, carried: Iterable = ()):
        """The system prompt of a conversation whose first message carries
        the fields *carried*: what every request is told, then the part of
        each field it carries, in the order of the file. A field no part
        names is told nothing beyond what every request is told."""
        carried = set(carried)
        pieces = [self.common.strip()] + [
            part.text.strip() for part in self.of(WITH)
            if carried & set(part.keys)]
        return replace(self.prompt,
                       text="\n\n".join(p for p in pieces if p) + "\n")

    def group(self, name: str, example: Optional[dict] = None) -> str:
        """The words of the message that asks the group *name*, with the
        reply it asks for where they show one (*example*); "" where the
        prompt has no group parts, whose every request is told the same.
        LookupError where it has group parts and none for that group."""
        if not self.groups:
            return ""
        for part in self.of(GROUP):
            if part.keys[0] == name:
                return shown_with(part.text.strip(), example,
                                  self.prompt.id)
        raise LookupError(f"{self.prompt.id}: no part for the group "
                          f"{name!r}")

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
        return "\n\n".join(part.text.strip() for part in parts)

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


def cut(prompt, groups: Optional[Iterable] = None,
        follows: Iterable = ()) -> Parts:
    """*prompt* cut at its markers. With *groups*, a prompt that has group
    parts has one for each of them and none for another group; *follows*
    are the fields the code sends follow-ups with, each of which needs a
    follow-up part. A part marked twice, a group without its part or a part
    without its group, or a follow-up field without its words raises
    LookupError, which the run raises at its start
    (`runner.surveyed_flow`)."""
    text = prompt.text
    marks = list(MARK.finditer(text))
    common = text[:marks[0].start()] if marks else text
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
        if kind == GROUP and len(keys) != 1:
            raise LookupError(f"{prompt.id}: a group part names one group, "
                              f"not {list(keys)}")
        parts.append(Part(kind, keys, text[mark.end():end]))
    out = Parts(prompt, common, tuple(parts))
    if groups is not None and out.groups:
        names = [getattr(group, "name", group) for group in groups]
        missing = [name for name in names if name not in out.groups]
        extra = sorted(set(out.groups) - set(names))
        if missing or extra:
            raise LookupError(
                f"{prompt.id}: the spec's groups and the prompt's parts "
                f"differ: no part for {missing}, a part for no group "
                f"{extra}")
    for key in follows:
        out.words([key])
    return out


@dataclass
class Thread:
    """One conversation with the model: the system prompt it began with,
    every message sent and the answer that stands last
    (`runner.ask_in_grammar` keeps it), and what its first message carried.
    """
    system: Optional[str] = None
    messages: list = field(default_factory=list)
    first: dict = field(default_factory=dict)

    @property
    def begun(self) -> bool:
        return bool(self.messages)

    def then(self, content) -> list:
        """The conversation with *content* as the next message: a follow-up
        after the answer that stands."""
        if not self.begun:
            raise ValueError("a follow-up needs an answer to follow")
        return [*self.messages, {"role": "user", "content": content}]

    def branch(self) -> "Thread":
        """A conversation that goes on from here without changing this one:
        a second row a reply made of one value asks on in its own."""
        return Thread(self.system, list(self.messages), dict(self.first))
