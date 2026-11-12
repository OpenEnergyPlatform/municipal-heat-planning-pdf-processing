"""
addressed.py: One document read in pieces of numbered lines, one question per
request, every answer an address (owner decisions 2026-11-08 evening, both
profiles).

Every request carries its instruction, the smallest part of the plan that
answers its question, and one question; every answer is an address, a
number or a few words, and code looks up what an address names
(`units.py`). Nothing is a conversation: an answer that did not hold is
asked again as a request of its own, with what did not hold (`follow`), as
often as the flow says, once by default (`flow.Numbers.follow_ups`).

The steps of a document (`Reader`):

1. Its passages as numbered lines and pieces of at most eight
   (`units.Chunk`); a figure transcribed once per run into its caption and
   its numbers and kept under the harvest (`Transcripts`), its image sent
   to no other request. A field of numbers reads a figure in the pieces of
   its numbers, any other field in the piece of its caption
   (`units.pieces_for`).
2. What the plan settles for all its values and its own years, where the
   spec asks them (`Spec.plan_fields`). Where the spec keeps a list of
   works (`Spec.works`), every piece is asked once which of its lines
   speak of another work and which line shows the rest are this
   publication's own (`work`, owner decisions 2026-11-09): a value takes
   the work of the line it stands in only from such a line, else asks its
   own (`work_coordinate`).
3. The fields a document has once (`Parameter.once_per_document`): the
   title page and the pieces a search finds best for a sentence written
   for the field, the run's budget of them, as many a request as the flow
   says, every find kept (`docfield`); a field with a list the budget times
   the flow's factor (`flow.Numbers`).
4. Every other field in every piece, the pieces best first for the
   field's sentences (`find`): each value an address and its words, and
   where the field has a list, its entry (owner decision 2026-11-09).
5. Each coordinate of each value on its own (`coord`): the value's line
   with the head of its table or the sentences beside it, the headings up
   to it, the title page and the plan's settings; the answer an address and
   words, or 0. An entry of a list is asked once per wording (`list`), a
   name of the document's list of scenarios or works once per name
   (`names`), 0 where the words name no such thing. A 0 is asked again
   with the pieces before and after the value's, then with the pieces a
   search finds best for a sentence of how the plan would print the answer
   (HyDE, `phrase`): the run's budget of them by kind, five a request, the
   model fetching more itself (`search`); what only the value's own passage
   can say is not searched, and no work is. A find from another passage is
   asked whether it speaks about the value (`check`). A year still open is
   asked last with the plan's base and target years.
6. A value stated for a group of scenarios takes the members the document
   names, one row each, where the field takes groups
   (`Parameter.takes_group`).

The two checks are unchanged: a coordinate's quote is the line its address
names, which stands in what the request showed, and its answer stands in
that line (`pipeline.merge_field`). A value is folded as before.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import contextlib
import contextvars
import copy
import dataclasses
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import regex

from .. import rules
from . import archive, fields, lookup
from . import flow as flow_map
from .fields import (EXHAUSTED, NUMBER, OUT_OF_SLICE, READ, SAID_UNSTATED,
                     UNBACKED)
from .pipeline import (Batch, Row, Source, WorkItem, mark_unanswered,
                       merge_field, row_label)
from .reading import (CUT, GETS, NO_ANSWER, Read, groups_of,
                      in_group_order, link_ranges, slots_of, span_rows)
from .units import (Chunk, Cut, Line, cut_pieces, letter_headings,
                    letter_settings, letter_title_page, letters_others,
                    Passage, Shown, address_of, chunks_of, own_lines,
                    passage_lines, passage_of, pieces_for, short_quote,
                    title_page_of)
from .verify import canonical_number, flat, min_quote_chars, numbers_in
from .spec import group_taken
from .wording import say

log = logging.getLogger(__name__)

# The requests and their prompts, one task each.
KINDS = ("transcribe", "find", "docfield", "coord", "list", "names",
         "search", "check", "follow", "work", "phrase")
PROMPT_IDS = {kind: f"extraction/{kind}" for kind in KINDS}
# Requests a profile may leave unwritten: the check of a find from another
# passage, the names request and the work request of a run that builds no
# list of names or works (`runner.names_asked`), and the sentence a search
# goes with, without which it goes with the field's.
OPTIONAL = ("check", "names", "work", "phrase")

# Why a find or a coordinate's answer does not hold beyond the two checks of
# the harvest: its address names no line the request showed, or its words
# do not stand in the line it names (`schema.DROP_REASONS`).
NOT_AN_ADDRESS = "not_an_address"
WORDS_NOT_IN_LINE = "words_not_in_line"

# What bounds the reading are numbers of the flow (`flow.Numbers`, owner
# decisions 2026-11-08 and 2026-11-09), which a run reads from its profile's
# file (`runner.take_flow`) and a reading made without one takes from the
# default profile's (`flow.default`): the pieces a search shows, first the
# best of each kind up to its share, then the best of the rest, and how many
# a request shows; the entries up to which a list is shown with what each
# means; the headings shown up to a value's place; the lines of a piece and
# of the title page; how often an answer that did not hold is asked again.

# A name not on the document's list yet.
NEW = "new"


@dataclass
class Asking:
    """What a box of the flow asks with (`engine.Engine`): its id, which
    every request it sends carries in the trace (`box`); the id of the box
    that asks whether a find of another passage speaks about the value
    (`about`), None where none follows the question; *refused(Found)* ->
    (reason, sentence) of the first own check that refuses a find, None
    where every check lets it be; how often an answer that did not hold is
    asked again, None for the flow's number. *about_step()* is the context
    the box that checks a find of another passage reads its own values in
    (`engine.Engine.step`), None where it reads the asking box's."""
    box: Optional[str] = None
    about: Optional[str] = None
    refused: Optional[Callable] = None
    follow_ups: Optional[int] = None
    about_step: Optional[Callable] = None


# The box asking now, in this thread and the jobs it runs side by side
# (`runner.run_each` hands its context on).
ASKING: contextvars.ContextVar = contextvars.ContextVar("asking",
                                                        default=None)


@contextlib.contextmanager
def asking(what: Asking):
    token = ASKING.set(what)
    try:
        yield what
    finally:
        ASKING.reset(token)


def asking_box() -> Optional[str]:
    """The id of the box asking now, None outside a box."""
    what = ASKING.get()
    return what.box if what is not None else None
# The entries of a list of works and of scenarios beside the names.
THIS_PUBLICATION = "work:this_publication"
ANOTHER_WORK = "out:another_work"
SEVERAL = "out:several"
# A year a text names in words or in a span (rule `year_words`): four
# digits standing alone, not part of a longer number.
_YEAR = re.compile(r"(?<![\d.,])(\d{4})(?![\d]|[.,]\d)")


def years_in(text: str) -> list:
    """The years *text* names, as their four digits, in order."""
    least, most = rules.get("year_words")
    return [one for one in _YEAR.findall(text or "")
            if least <= int(one) <= most]


def span():
    """What makes a span of years between two of them (rules `span_words`,
    `span_dashes`)."""
    def made():
        words = "|".join(re.escape(w) for w in rules.get("span_words"))
        dashes = re.escape(rules.get("span_dashes"))
        parts = ([rf"\b({words})\b"] if words else []) \
            + ([rf"[{dashes}]"] if dashes else [])
        return re.compile("|".join(parts) or r"(?!)", re.I)
    return rules.derived("addressed.span", made)


def _question():
    """A search sentence that is a question, which a search takes and the
    run counts (owner decision 2026-11-08: "So pingelig wäre ich da
    nicht"): it ends in a question mark or begins with one of the rule
    `question_words`."""
    def made():
        words = "|".join(re.escape(w) for w in rules.get("question_words"))
        parts = [r"\?\s*$"] + ([rf"^\s*({words})\b"] if words else [])
        return re.compile("|".join(parts), re.I)
    return rules.derived("addressed.question", made)


def told(why: str, entry) -> str:
    """Why a find or an answer did not hold, in the profile's words, with
    the address and the words it gave."""
    entry = entry if isinstance(entry, dict) else {}
    return say(why, at=entry.get("at"), words=entry.get("words"))


def refusals(refused: list) -> list:
    """What a follow-up tells of the finds that did not hold: each as it
    was given, and why in the profile's words."""
    out = []
    for entry, why in refused:
        if "told" in entry:
            # An own check of the flow: asked again with its sentence.
            out.append({**{k: v for k, v in entry.items() if k != "told"},
                        "why": entry["told"]})
            continue
        text = say(why, given=entry.get("entry")) if why == "not_an_option" \
            else told(why, entry)
        out.append({**entry, "why": text})
    return out


def joined(held: list, more: list) -> list:
    """*held* and those finds of *more* that are not among them: what the
    rule `same_find_by` names (a line, its cell, its words) once."""
    by = rules.get("same_find_by")

    def key(got) -> tuple:
        return tuple(part for name, part in (
            ("line", id(got.lines[0][0])), ("cell", got.cell),
            ("words", flat(got.words).casefold())) if name in by)
    taken = {key(got) for got in held}
    return held + [got for got in more if key(got) not in taken]


def work_read(claim: dict) -> Optional[dict]:
    """How a value read its work, its `work` fields, None where it read
    none."""
    if claim.get("work_state") != READ:
        return None
    return {key: copy.deepcopy(value) for key, value in claim.items()
            if key == "work" or key.startswith("work_")}


# A number as the words of a find print it, with its sign.
_FIRST_NUMBER = re.compile(r"[-−–]?\d(?:[\d.,]*\d)?")


def number_of(words: str) -> Optional[str]:
    """The number the words of a find print, with its sign (owner decision
    2026-11-01), in `canonical_number`'s spelling: the words themselves
    where they are a number, else the one number they print ("750.940
    kWh", "ca. 8,8 GWh"); None where they print none or more than one
    ("800 / 750", "2019 bis 2021"). A signed number and its magnitude are
    one number ("-1.155"). Where the rule `sign_belongs` is off the sign
    stays outside the number: its magnitude."""
    one = _number_of(words)
    if one and one.startswith("-") and rules.get("sign_belongs") != "on":
        return one[1:]
    return one


def _number_of(words: str) -> Optional[str]:
    whole = canonical_number(words)
    if whole is not None:
        return whole
    found = numbers_in(words or "")
    found = {n for n in found if "-" + n not in found}
    if len(found) == 1:
        return next(iter(found))
    if found and not rules.get("first_number_only"):
        # The first number the words print, in reading order.
        for found_at in _FIRST_NUMBER.finditer(words or ""):
            one = canonical_number(found_at.group(0))
            if one is not None:
                return one
    return None


def is_question(sentence: str) -> bool:
    """Is a search sentence a question rather than a sentence of the
    plan?"""
    return bool(_question().search(sentence or ""))


# -- grammars ----------------------------------------------------------------

def _format(name: str, schema: dict) -> dict:
    return {"type": "json_schema",
            "json_schema": {"name": name, "schema": schema}}


def address_key() -> str:
    """How an answer names its line: "at", the number of the line, or
    "quote", the words of the line (rule `answer_with`)."""
    return "quote" if rules.get("answer_with") == "quote" else "at"


def _found() -> dict:
    key = address_key()
    return {"type": "object",
            "properties": {key: {"type": "string"},
                           "words": {"type": "string"}},
            "required": [key, "words"], "additionalProperties": False}

# What a search may fetch itself (owner decision 2026-11-07, kept by the
# plan of 2026-11-09): the piece before or after a shown one, a table or
# figure by its placeholder, the pieces a pattern stands in, the pieces
# best for a sentence of its own. The kinds stand in `reading.GETS`, the one
# list; the rule `fetches` allows some of them.


def fetches() -> list:
    """What a reply may fetch itself (rule `fetches`), in the order of
    `GETS`."""
    allowed = rules.get("fetches")
    return [get for get in GETS if get in allowed]


def more_schema() -> dict:
    return {"type": "array", "items": {
        "type": "object",
        "properties": {"get": {"enum": fetches()},
                       "at": {"type": "string"},
                       "id": {"type": "string"},
                       "pattern": {"type": "string"},
                       "text": {"type": "string"}},
        "required": ["get"], "additionalProperties": False}}


# A find of a field with a list: the number of its entry beside its address
# and words (owner decision 2026-11-09).
def _entry_found() -> dict:
    key = address_key()
    return {"type": "object",
            "properties": {"entry": {"type": "integer"},
                           key: {"type": "string"},
                           "words": {"type": "string"}},
            "required": ["entry", key, "words"],
            "additionalProperties": False}


def found_format(closed: bool = False) -> dict:
    """The finds of a request: each an address and the words of the value,
    and where the field has a list the number of its entry (*closed*); an
    empty list where nothing shown holds one."""
    return _format("found_reply", {
        "type": "object",
        "properties": {"found": {"type": "array", "items":
                                 _entry_found() if closed
                                 else _found()}},
        "required": ["found"], "additionalProperties": False})


def work_format() -> dict:
    """The answer of a piece's work request: the lines of other works, each
    an address and the name as a line prints it, and the line that shows
    the rest are this publication's own (`own`), 0 where none does."""
    key = address_key()
    return _format("work_reply", {
        "type": "object",
        "properties": {"found": {"type": "array", "items": _found()},
                       "own": {"type": "object",
                               "properties": {
                                   key: {"type": ["string", "integer"]},
                                   "words": {"type": "string"}},
                               "required": [key],
                               "additionalProperties": False}},
        "required": ["found", "own"], "additionalProperties": False})


def work_choice_format() -> dict:
    """The work of one value, asked as an entry of the document's list of
    works: its number, 0 for none, and the line that shows it."""
    return _format("work_choice_reply", {
        "type": "object",
        "properties": {"entry": {"type": "integer"},
                       address_key(): {"type": ["string", "integer"]},
                       "words": {"type": "string"}},
        "required": ["entry"], "additionalProperties": False})


def phrase_format() -> dict:
    """A sentence as the plan would print what a search looks for."""
    return _format("phrase_reply", {
        "type": "object", "properties": {"phrase": {"type": "string"}},
        "required": ["phrase"], "additionalProperties": False})


def coord_format(several: bool, more: bool = False) -> dict:
    """A coordinate's answer: an address and its words, or 0 (owner
    decision 2026-11-09: the sentence a search goes with is a request of
    its own, `phrase`); one that may name several entries lists its
    finds."""
    if several:
        properties = {"found": {"type": "array", "items": _found()}}
        required = ["found"]
    else:
        properties = {address_key(): {"type": ["string", "integer"]},
                      "words": {"type": "string"}}
        required = [address_key()]
    if more:
        properties["more"] = more_schema()
    return _format("coordinate_reply", {
        "type": "object", "properties": properties, "required": required,
        "additionalProperties": False})


def entry_format(several: bool = False, new: bool = False) -> dict:
    """The number of a list's entry, 0 for none; a list of them where
    several may be meant; "new" for a name not on the document's list."""
    one: dict = {"type": "integer"}
    if new:
        one = {"anyOf": [{"type": "integer"}, {"enum": [NEW]}]}
    entry = {"type": "array", "items": one} if several else one
    return _format("entry_reply", {
        "type": "object", "properties": {"entry": entry},
        "required": ["entry"], "additionalProperties": False})


def year_format() -> dict:
    """The last question of a year: the line that names the plan's state,
    its words and the entry of the plan's years it means, 0 for none."""
    return _format("plan_year_reply", {
        "type": "object",
        "properties": {address_key(): {"type": ["string", "integer"]},
                       "words": {"type": "string"},
                       "entry": {"type": "integer"}},
        "required": ["entry"], "additionalProperties": False})


def lines_format() -> dict:
    """A figure transcribed: its caption (title, axes, legend) and its
    numbers, each a line (owner decision 2026-11-09)."""
    lines = {"type": "array", "items": {"type": "string"}}
    return _format("lines_reply", {
        "type": "object",
        "properties": {"caption": lines, "numbers": lines},
        "required": ["caption", "numbers"], "additionalProperties": False})


def about_format() -> dict:
    return _format("check_reply", {
        "type": "object", "properties": {"about": {"enum": ["yes", "no"]}},
        "required": ["about"], "additionalProperties": False})



# -- what a request shows ----------------------------------------------------

def field_shown(parameter, full: Optional[bool] = None) -> dict:
    """A field as a request shows it: its name and what a value of it is,
    in short where the spec writes that (`brief`) or whole as the rule
    `field_text` says (*full* says it for the caller)."""
    if full is None:
        full = rules.get("field_text") == "whole"
    means = parameter.description if full \
        else (getattr(parameter, "brief", None) or parameter.description)
    return {"name": parameter.label, "means": means}


def block_payload(passage: Optional[Passage], shown: Shown,
                  letter: str = "") -> dict:
    """A block of lines as a request shows it: its passage's kind, page and
    title, and the lines with their addresses."""
    out: dict = {}
    if passage is not None:
        out["kind"] = passage.kind
        if passage.page is not None and rules.get("show_passage_page"):
            out["page"] = passage.page
        if passage.kind != "section" and passage.title \
                and rules.get("show_passage_title"):
            out["title"] = passage.title
    out["lines"] = shown.rendered(letter)
    return out


def first_address(shown: Shown, cells: bool, letter: str = "") -> str:
    """An address for a request's example: the first of its own lines that
    is no title or head, with *cells* a cell of it where it has cells."""
    block = shown.blocks.get(letter) \
        or next(iter(shown.blocks.values()), None)
    if block is None or not block.entries:
        return "1"
    entries = [e for e in block.entries
               if e[1].role in ("body", "text", "figure", "number",
                                "foot")] \
        or block.entries
    number, line, _ = entries[0]
    wanted = rules.get("example_cell")
    cell = f".{min(wanted, len(line.cells))}" \
        if cells and line.cells and len(line.cells) > 1 else ""
    return f"{block.letter}{number}{cell}"


def shown_example(example):
    """The reply a request shows as its example, as the rules say
    (`show_example`: none at all, `show_empty_example`: of the two a request
    that finds values shows, only the one with a find); None stays None,
    and no example at all is the empty tuple."""
    if example is None:
        return None
    if not rules.get("show_example"):
        return ()
    if isinstance(example, (tuple, list)) and len(example) > 1 \
            and not rules.get("show_empty_example"):
        return (example[0],)
    return example


def point(shown: Shown, cells: bool = False, letter: str = "",
          at: Optional[str] = None) -> dict:
    """What an example answer names its line with: the address of the
    request's first line of its own (or *at*), or, where the rule
    `answer_with` has the answer quote, the words of that line."""
    at = first_address(shown, cells, letter) if at is None else at
    if address_key() == "at":
        return {"at": at}
    address = address_of(at)
    found = shown.find(address) if address is not None else None
    return {"quote": found[0].text if found is not None else ""}


def find_example(shown: Shown, closed: bool = False,
                 letter: str = "") -> tuple:
    """The two replies a request that finds values shows (owner decision
    2026-11-09: "immer ein Positiv und ein Negativbeispiel"): one find at
    the request's own first line, and where the field has a list with the
    number of its entry; and the empty one, where no shown line prints a
    value."""
    one = {**point(shown, True, letter), "words": fields.said()}
    if closed:
        one = {"entry": 1, **one}
    return {"found": [one]}, {"found": []}


@dataclass
class Found:
    """What an answer's address names: the lines, their passage, the cell
    and the words, or the reason it names nothing."""
    lines: list = field(default_factory=list)        # [(Line, Source)]
    passage: Optional[Passage] = None
    cell: Optional[int] = None
    words: str = ""
    letter: str = ""
    why: Optional[str] = None
    # The lines its quote is: the named ones, and where they are too short
    # to name a place, the shown lines around them (`Shown.around`).
    quoted: list = field(default_factory=list)
    # The number of the entry of the request's list a find names, where the
    # field has a list (owner decision 2026-11-09), 0 for none.
    entry: Optional[int] = None
    # The entry it named is none of the list's and the rule `outside_list`
    # keeps its wording (entry 0).
    outside: bool = False

    @property
    def quote(self) -> str:
        return " ".join(line.text for line, _ in self.quoted or self.lines)

    @property
    def source(self) -> Optional[Source]:
        return self.lines[0][1] if self.lines else None


def second_ways(ways: list) -> dict:
    """The note a request carries that went through the second way of the
    rules *ways* (owner decision 2026-11-11): their names, so that
    a run shows what it used. Nothing where it went through none."""
    return {"second_way": ",".join(ways)} if ways else {}


def said_none(reply) -> bool:
    """Does the answer of a names request name 0, none of its list?"""
    given = reply.get("entry") if isinstance(reply, dict) else None
    return any(not isinstance(pick, bool) and str(pick).strip() == "0"
               for pick in (given if isinstance(given, list) else [given]))


# A find's entry that is no number of its request's list (`not_an_option`,
# owner decision 2026-09-11).
NOT_AN_OPTION = "not_an_option"


def listing(options, meanings: int, two_step: bool = True) -> tuple:
    """(lines, choices, grouped) of a list as a request shows it (owner
    decisions 2026-11-08): a list longer than *meanings* entries
    (`flow.Numbers.list_meanings`) whose entries name groups is shown by
    its groups, each a choice; a shorter one with what each entry means, a
    longer one by its names. *choices* are what a number picks, labels or
    group names. The rule `two_step_list` says whether a long list of groups
    is asked in two steps, *two_step* that this list is the first of them:
    the entries of the groups chosen are never shown as groups."""
    options = list(options)
    groups: list = []
    for option in options:
        group = getattr(option, "group", "") or ""
        if group and group not in groups:
            groups.append(group)
    if len(options) > meanings and len(groups) > 1 \
            and two_step and rules.get("two_step_list"):
        return ([f"{i} {group}" for i, group in enumerate(groups, start=1)],
                groups, True)
    lines = []
    for i, option in enumerate(options, start=1):
        text = f"{i} {option.label}"
        if option.definition and len(options) <= meanings:
            text += f" (means: {option.definition})"
        lines.append(text)
    return lines, [option.label for option in options], False


def picked_entry(entry, size: int) -> Optional[int]:
    """The number a find names of a list of *size*, 0 for none; None where
    it names no number of the list."""
    if isinstance(entry, bool):
        return None
    try:
        number = int(str(entry).strip())
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= size else None


def share_of(chunk: Chunk) -> str:
    """The kind of passage a piece counts under in a search's shares: a
    table, a figure, else text ("section")."""
    kind = chunk.passage.kind
    return kind if kind in ("table", "figure") else "section"


def shares_problem(shares: dict) -> Optional[str]:
    """Why *shares* (the shares of tables, figures and text of a search)
    cannot be scaled, None where they can: for the check of the values of
    the flow. Three shares of 0 are honoured by `budgeted` (no kind first),
    never counted as 1."""
    if shares and not any(max(0, int(n)) for n in shares.values()):
        return ("the three shares of a search are 0, so that no kind of "
                "chunk is taken first; give one of them a share or accept "
                "the order of the ranking")
    return None


def budgeted(ranked: list, budget: int, shares: dict) -> list:
    """The pieces a search shows of *ranked*, best first (owner decisions
    2026-11-09: 50 pieces, 20 of tables, 15 of figures, 15 of text, filled
    up): the best of each kind of passage up to its share, the shares
    scaled to *budget*, then the best of the rest up to *budget*; in the
    order of *ranked*."""
    budget = max(0, int(budget))
    # Three shares of 0 take no kind first: the pieces are the best of all,
    # in order (they never count as 1 each).
    total = sum(max(0, int(n)) for n in shares.values())
    room = {kind: (max(0, int(n)) * budget // total if total else 0)
            for kind, n in shares.items()}
    picked: set = set()
    for chunk in ranked:
        kind = share_of(chunk)
        if room.get(kind, 0) > 0:
            room[kind] -= 1
            picked.add(chunk.key)
    for chunk in ranked:
        if len(picked) >= budget:
            break
        picked.add(chunk.key)
    return [chunk for chunk in ranked if chunk.key in picked]


def _fold(text: str) -> str:
    """*text* as the check that words stand in a line compares it: its
    spaces flattened, and its case folded unless the rule `match_case`
    says it counts."""
    text = flat(text)
    return text if rules.get("match_case") else text.casefold()


def quoted_address(shown: Shown, quote: str) -> Optional[str]:
    """The address of the shown lines that hold *quote*, characters that
    count as the same compared as the same (rule `same_characters`): the
    lines of the request's own passage first, one line or a stretch of
    consecutive ones; None where no shown line holds it."""
    wanted = _fold(quote)
    if not wanted:
        return None
    for letter in sorted(shown.blocks, key=lambda one: one != ""):
        entries = shown.blocks[letter].entries
        folded = [_fold(line.text) for _, line, _ in entries]
        text = " ".join(folded)
        at = text.find(wanted)
        if at < 0:
            continue
        end, start, first, last = at + len(wanted), 0, None, None
        for i, part in enumerate(folded):
            if first is None and start + len(part) > at:
                first = i
            if start < end:
                last = i
            start += len(part) + 1
        if first is None or last is None:
            continue
        one, other = entries[first][0], entries[last][0]
        return f"{letter}{one}" if one == other else f"{letter}{one}-{other}"
    return None


def has_address(reply) -> bool:
    """Does the answer name a line: an address, or, where the rule
    `answer_with` has it quote, a quote?"""
    if not isinstance(reply, dict):
        return False
    quote = reply.get("quote")
    return address_of(reply.get("at")) is not None or (
        rules.get("answer_with") == "quote" and isinstance(quote, str)
        and bool(quote.strip()))


def resolve(shown: Shown, entry, passages: dict) -> Found:
    """The lines an answer's address names in what *shown* showed, its
    words checked against them: `NOT_AN_ADDRESS` where it names no shown
    line or cell, `WORDS_NOT_IN_LINE` where its words do not stand in what
    it names. Words left empty are the cell's, or the lines' of a stretch;
    a single line without a cell needs words."""
    at = entry.get("at") if isinstance(entry, dict) else None
    words = entry.get("words") if isinstance(entry, dict) else None
    words = words.strip() if isinstance(words, str) else ""
    if isinstance(entry, dict) and rules.get("answer_with") == "quote":
        # The answer names its line by its words: the code finds the line
        # among the shown ones (rule `answer_with`).
        quote = entry.get("quote")
        if isinstance(quote, str) and quote.strip():
            at = quoted_address(shown, quote)
            if at is None:
                return Found(words=words, why="quote_not_in_source")
    address = address_of(at)
    if address is None:
        return Found(words=words, why=NOT_AN_ADDRESS)
    lines = shown.stretch(address)
    if not lines:
        return Found(words=words, why=NOT_AN_ADDRESS)
    line, source = lines[0]
    passage = passages.get((source.owner_kind, source.owner_id))
    cell = address.cell
    if cell is not None and (not line.cells or not 0 < cell <= len(line.cells)):
        return Found(words=words, why=NOT_AN_ADDRESS)
    text = " ".join(one.text for one, _ in lines)
    found = Found(lines, passage, cell, words, address.letter,
                  quoted=shown.around(address, min_quote_chars()))
    if not words:
        if cell is not None:
            found.words = line.cells[cell - 1]
        elif address.last is not None:
            found.words = text
        else:
            found.why = WORDS_NOT_IN_LINE
            return found
    # Empty words are always refused; words that do not stand in the lines
    # only where the rule `check_answer_in_quote` is on.
    if not found.words or (rules.get("check_answer_in_quote")
                           and _fold(found.words) not in _fold(text)):
        found.why = WORDS_NOT_IN_LINE
        return found
    if line.cells and rules.get("move_to_cell"):
        # The cell the words stand in, where the address names another one
        # and only one cell holds them.
        holding = [i for i, one in enumerate(line.cells, start=1)
                   if _fold(found.words) in _fold(one)]
        if (cell is None or cell not in holding) and len(holding) == 1:
            found.cell = holding[0]
    return found


# -- the plan's figures, transcribed once ------------------------------------

class Transcripts:
    """figure -> its caption and its numbers, transcribed once per run and
    kept under the harvest (`transcripts/<document>.json`): a figure whose
    image and prompt are those of the kept transcription is not asked again
    (owner decision 2026-11-08, e); one kept in another form is (owner
    decision 2026-11-09: caption and numbers apart).

    *ask(source, document_id)* is the transcription request, the reply as
    a dict or None; *fingerprint* says which prompt and model wrote it (a
    text, or a function that tells it where it is read, in the step that
    transcribes, whose model it names), *image_key(source)* which image
    (None where the figure has none: then nothing is asked and its
    description stands for it)."""

    def __init__(self, ask: Optional[Callable], store: Optional[Path],
                 fingerprint, image_key: Callable):
        self.ask = ask
        self.store = Path(store) if store else None
        self._fingerprint = fingerprint
        self.image_key = image_key
        self._lock = threading.Lock()

    @property
    def fingerprint(self) -> str:
        made = self._fingerprint
        return made() if callable(made) else made

    def _path(self, document_id: int) -> Optional[Path]:
        return self.store / f"{document_id}.json" if self.store else None

    def _load(self, document_id: int) -> dict:
        path = self._path(document_id)
        if path is None or not path.is_file():
            return {}
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def __call__(self, document_id: int, figures: list,
                 each: Optional[Callable] = None) -> tuple:
        """({figure id: {"caption": [lines], "numbers": [lines]}}, asked)
        of *figures*: the kept ones read, the others asked (*each(jobs,
        run)* runs them side by side) and kept."""
        kept = self._load(document_id)
        out: dict = {}
        wanted = []
        for source in figures:
            key = self.image_key(source)
            if key is None:
                continue
            entry = kept.get(str(source.owner_id)) or {}
            if entry.get("image") == key \
                    and entry.get("prompt") == self.fingerprint \
                    and isinstance(entry.get("caption"), list) \
                    and isinstance(entry.get("numbers"), list):
                out[source.owner_id] = {"caption": list(entry["caption"]),
                                        "numbers": list(entry["numbers"])}
            elif self.ask is not None:
                wanted.append((source, key))

        def lines_of(reply, name: str) -> Optional[list]:
            lines = reply.get(name) if isinstance(reply, dict) else None
            if not isinstance(lines, list):
                return None
            return [str(line).strip() for line in lines if str(line).strip()]

        def one(job):
            source, key = job
            reply = self.ask(source, document_id)
            caption, numbers = lines_of(reply, "caption"), \
                lines_of(reply, "numbers")
            if caption is None or numbers is None:
                return source, key, None
            return source, key, {"caption": caption, "numbers": numbers}
        done = (each(wanted, one) if each is not None
                else [one(job) for job in wanted])
        changed = False
        for source, key, lines in done:
            if not lines or not (lines["caption"] or lines["numbers"]):
                continue
            out[source.owner_id] = lines
            kept[str(source.owner_id)] = {"image": key, **lines,
                                          "prompt": self.fingerprint}
            changed = True
        path = self._path(document_id)
        if changed and path is not None:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                archive.keep(path)
                path.write_text(json.dumps(kept, ensure_ascii=False,
                                           indent=1), encoding="utf-8")
        return out, len(wanted)


def image_key(path: Optional[str]) -> Optional[str]:
    """What names an image for its kept transcription: its bytes' hash."""
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


# -- the document ------------------------------------------------------------

@dataclass
class Entry:
    """One entry of a document's list of names: what it is called in
    requests and in the graph, the work it belongs to, the line it was
    first read at, and how the value it was first read for read its work
    (its `work*` fields), which a later name of the entry whose own work
    stayed open takes (owner decision 2026-11-09)."""
    label: str
    name: str
    work: int = 0
    quote: str = ""
    work_read: Optional[dict] = None


@dataclass
class PieceWork:
    """What a piece's work request answered (owner decisions 2026-11-09):
    the finds of other works, each (the (passage, line) pairs it covers or
    None for the whole piece, the number of its entry of the document's
    list of works, the find), the line that shows the rest of the piece is
    this publication's own (None where none does), and what the request
    showed, which a work read from it is checked against."""
    finds: list = field(default_factory=list)
    own: Optional["Found"] = None
    evidence: list = field(default_factory=list)


class Names:
    """A document's list of scenarios or works, built piece by piece: a
    name is asked against the list so far and is an entry or a new one
    (`names`, owner decisions 2026-11-08: two equal names of two studies
    are two entries; nothing is merged by its spelling)."""

    def __init__(self, kind: str, first: Optional[Entry] = None):
        self.kind = kind
        self.entries: list = [first] if first else []
        self.lock = threading.Lock()
        self.asked: dict = {}

    def add(self, name: str, work: int = 0, quote: str = "",
            work_read: Optional[dict] = None) -> int:
        """The number of a new entry for *name*, or of the entry a request
        beside this one added for the same name of the same work; a label
        another entry has already is told apart by its work."""
        name = name.strip()
        two = rules.get("same_name_two_entries")
        with self.lock:
            for i, entry in enumerate(self.entries, start=1):
                if entry.name == name and (entry.work == work or not two):
                    return i
            label = name
            if two and any(e.label == label for e in self.entries):
                label = f"{name} ({work})"
            self.entries.append(Entry(label, name, work, quote, work_read))
            return len(self.entries)

    def shown(self, works: Optional["Names"] = None) -> list:
        """[(number, text)] of the list as a request shows it, each under
        its work where the entries have works, ordered by work."""
        with self.lock:
            entries = list(enumerate(self.entries, start=1))
        if works is not None and rules.get("names_list_order") == "by_work":
            entries.sort(key=lambda pair: (pair[1].work, pair[0]))
        out = []
        for number, entry in entries:
            if works is not None and 0 < entry.work <= len(works.entries):
                out.append((number, f"{works.entries[entry.work - 1].label}"
                                    f": {entry.name}"))
            else:
                out.append((number, entry.label))
        return out


class Plan:
    """One document as numbered lines and pieces, and what its requests
    share while it is read: its title page, its settings, its years, the
    entries its wordings were read as, and its lists of names."""

    def __init__(self, document_id: int, sources: list, transcripts: dict,
                 chunk_units: Optional[int] = None, *, numbers=None,
                 cut: Optional[Cut] = None,
                 cutting: Optional[Callable] = None):
        # How many lines a piece and the title page hold and how many
        # headings are shown up to a place are the flow's (`flow.Numbers`);
        # *chunk_units* says another size of the pieces, *cut* how the
        # flow's split box cuts them (`units.Cut`); *cutting()* is the
        # context the pieces are cut in (the split box's own values,
        # `engine.Engine.step`).
        self.numbers = numbers or flow_map.default()
        if cut is None:
            cut = Cut(lines=flow_map.number(self.numbers, "piece_lines")
                      if chunk_units is None else chunk_units,
                      headings=flow_map.number(self.numbers, "headings"))
        elif chunk_units is not None:
            cut = dataclasses.replace(cut, lines=chunk_units)
        self.cut = cut
        self.document_id = document_id
        self.sources = list(sources)
        self.by_owner = {(s.owner_kind, s.owner_id): s for s in sources}
        self.passages: dict = {}
        self.chunks: list = []
        cutting = cutting or contextlib.nullcontext
        with cutting():
            for source in sources:
                passage = passage_of(source,
                                     transcripts.get(source.owner_id)
                                     if source.owner_kind == "figure"
                                     else None)
                if not passage.lines:
                    continue
                self.passages[passage.owner] = passage
        # The pieces as the split box cuts them: each a piece of one
        # passage (`Chunk`); a piece over several passages is a group of
        # them (`groups`), asked together.
        with cutting():
            self.chunks, self.groups = cut_pieces(
                list(self.passages.values()), cut)
        self.group_of = {chunk.key: group for group in self.groups
                         for chunk in group}
        self.by_key = {chunk.key: chunk for chunk in self.chunks}
        self.position = {chunk.key: i for i, chunk in enumerate(self.chunks)}
        # The pieces a field of numbers reads, and those any other field
        # reads (`units.pieces_for`), each with the place of its pieces.
        self.views = {numbers: pieces_for(self.chunks, numbers)
                      for numbers in (True, False)}
        self.places = {numbers: {chunk.key: i for i, chunk in
                                 enumerate(view)}
                       for numbers, view in self.views.items()}
        self.title_page = title_page_of(
            list(self.passages.values()),
            flow_map.number(self.numbers, "title_page_lines"))
        self.settings: list = []          # [(Line, Source)]
        self.bases: list = []             # `pipeline.named_years` entries
        self.lists: dict = {}
        self.names: dict = {}             # kind -> Names
        self.works_of: dict = {}          # piece key -> PieceWork
        self.lock = threading.Lock()
        self._locks: dict = {}
        self._headings: dict = {}
        self._first: set = set()

    @staticmethod
    def part(numbers: bool) -> bool:
        """Does a field read a figure in the pieces of its numbers? A
        field of numbers does, any other field reads its caption, as the
        rule `figure_part` says (by the kind of field, or always one)."""
        return {"caption": False, "numbers": True}.get(
            rules.get("figure_part"), bool(numbers))

    def pieces(self, numbers: bool) -> list:
        """The pieces a field reads, of numbers or not (`pieces_for`)."""
        return self.views[self.part(numbers)]

    def places_of(self, numbers: bool) -> dict:
        """{piece key: its place} among `pieces`."""
        return self.places[self.part(numbers)]

    def first_request(self) -> bool:
        """Is this the first request the step that runs makes in this
        document? Told once per step (rule `show_title_page`, "first")."""
        step = rules.STEP.get()
        key = step.ident if step is not None else ""
        with self.lock:
            if key in self._first:
                return False
            self._first.add(key)
            return True

    def key_lock(self, key) -> threading.Lock:
        with self.lock:
            return self._locks.setdefault(key, threading.Lock())

    def headings(self, owner: tuple) -> list:
        """[(Line, Source)] of the titles of the sections up to a passage,
        its own last (`lookup.sections_up_to`)."""
        # As many as the step that runs says (`headings`), else as the
        # split box cut the document with.
        own, value = rules.stepped_value("headings")
        count = int(value) if own else self.cut.headings
        with self.lock:
            if (owner, count) in self._headings:
                return self._headings[(owner, count)]
        got: list = []
        for section in lookup.sections_up_to(self.sources, tuple(owner),
                                             count):
            title = lookup.title_of(section)
            if title:
                got.append((Line(len(got) + 1, title, (), "heading"),
                            Source(section.owner_kind, section.owner_id,
                                   title, section.provenance)))
        with self.lock:
            self._headings[(owner, count)] = got
        return got

    def chunk_of(self, owner: tuple, number: int,
                 numbers: Optional[bool] = None) -> Optional[Chunk]:
        """The piece of a passage that holds its line *number*, of those a
        field of numbers or another field reads where *numbers* says which;
        a line every piece shows is the first piece's."""
        chunks = self.chunks if numbers is None else self.pieces(numbers)
        pieces = [c for c in chunks if c.owner == tuple(owner)]
        return next((c for c in pieces if number in c.numbers),
                    pieces[0] if pieces else None)

    def beside(self, chunk: Chunk, numbers: bool = False) -> list:
        """The pieces right before and after *chunk* among those a field of
        numbers or another field reads, as many on each side as the rule
        `beside_pieces` says."""
        view = self.pieces(numbers)
        at = self.places_of(numbers).get(chunk.key)
        if at is None:
            return []
        near = rules.get("beside_pieces")
        around = [at + d for d in range(-near, 0)] \
            + [at + d for d in range(1, near + 1)]
        return [view[i] for i in around if 0 <= i < len(view)]


def title_page_shown(plan: Plan) -> bool:
    """Does the request that is built now show the title page (rule
    `show_title_page`)? "first" shows it in the first request the step
    makes in the document only."""
    mode = rules.get("show_title_page")
    if mode == "never":
        return False
    return plan.first_request() if mode == "first" else True


def blocks_in_order(parts: dict) -> dict:
    """*parts* (block name -> payload) as the rule `shown_block_order`
    orders them; those it does not name come last in the usual order."""
    order = list(rules.get("shown_block_order"))
    usual = ["passage", "headings", "title_page", "settings"]
    names = [n for n in order if n in parts] \
        + [n for n in usual if n not in order and n in parts]
    return {name: parts[name] for name in names}


def show_value(plan: Plan, claim: dict, headings: Optional[bool] = None,
               plain: bool = False) -> tuple:
    """(Shown, payload) of what every request about a value's coordinates
    shows: its line with its table's title and head, or the sentences
    before and after it; the headings up to it, the title page and the
    plan's settings, as the step that asks says (rules `show_headings`,
    `show_title_page`, `show_settled`); the value as its words and its
    address. *headings* False shows none whatever the rules say, *plain*
    asks only for the lines of the place: the title page and the settings
    stand in what a quote may cite, as the rules `show_*` do not touch
    them."""
    at = claim.get("at") or {}
    owner = tuple(at.get("owner") or ())
    passage = plan.passages.get(owner)
    shown = Shown()
    if passage is None:
        return shown, {}
    first = int(at.get("line") or 1)
    last = int(at.get("last") or first)
    around = rules.get("lines_around")
    rows = rules.get("rows_around")
    numbers = (list(range(max(1, first - rows), last + 1 + rows))
               if passage.kind == "table"
               else list(range(max(1, first - around), last + 1 + around)))
    shown.add("", "passage", passage_lines(passage, numbers))
    if plain:
        heads = []
        title_page, settings = plan.title_page, plan.settings
    else:
        heads = plan.headings(owner) if headings is not False \
            and rules.get("show_headings") else []
        title_page = plan.title_page if title_page_shown(plan) else []
        settings = plan.settings if rules.get("show_settled") else []
    shown.add(letter_headings(), "headings", heads, renumber=True)
    shown.add(letter_title_page(), "title_page", title_page, renumber=True)
    shown.add(letter_settings(), "settings", settings, renumber=True)
    value_at = f"{first}" + (f".{at['cell']}" if at.get("cell") else "") \
        + (f"-{last}" if last != first else "")
    words = claim.get("value_raw") or claim.get("value")
    parts = {} if plain else {"passage": block_payload(passage, shown)}
    if heads:
        parts["headings"] = shown.rendered(letter_headings())
    if title_page and not plain:
        parts["title_page"] = shown.rendered(letter_title_page())
    if settings and not plain:
        parts["settings"] = shown.rendered(letter_settings())
    payload = {"value": {"words": words, "at": value_at},
               **(parts if plain else blocks_in_order(parts))}
    return shown, payload


# -- the requests ------------------------------------------------------------

@dataclass
class Asks:
    """The requests of the harvest, each (payload, document_id, *, shape,
    example, **noted) -> the reply as a dict, CUT or None; a request that
    finds values shows two replies, *example* a pair (`find_example`).
    *follow* is a request asked again with what did not hold: (kind,
    payload, document_id, *, shape, example, **noted). *check*, *names*,
    *work* and *phrase* are None where the profile writes no prompt for them
    (`OPTIONAL`)."""
    find: Callable
    docfield: Callable
    coord: Callable
    list: Callable
    search: Callable
    follow: Callable
    names: Optional[Callable] = None
    check: Optional[Callable] = None
    work: Optional[Callable] = None
    phrase: Optional[Callable] = None


@dataclass
class Counts:
    """What the requests of a document came to, for the trace and the
    statistics: requests per kind, refusals per reason, and the search
    sentences that were questions."""
    asked: collections.Counter = field(default_factory=collections.Counter)
    failed: collections.Counter = field(default_factory=collections.Counter)
    questions: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def ask(self, kind: str, n: int = 1) -> None:
        with self.lock:
            self.asked[kind] += n

    def fail(self, why: str, n: int = 1) -> None:
        with self.lock:
            self.failed[why] += n

    def question(self) -> None:
        with self.lock:
            self.questions += 1


class Reader:
    """The reading of a document (`Plan`): what it settles and its years
    (`settled`), its fields asked once (`docfield`), every other field in
    its pieces (`find`) and each value's coordinates (`coordinates`).

    *spec* is the document's spec, *asks* its requests (`Asks`).
    *order(document_id, sentences, chunks)* is every piece best first for
    search sentences (the reranker over all pieces), *search_order* the
    same from the passages the vector search finds best, their pieces
    reranked first (`make_order`). *probes(parameter, document_id)* is a
    field's search sentences, *known(claim, asked)* what a value has read
    in the plan's words (`runner.row_context`), *span_marks* what a value
    stated for a span of years takes on each of its rows. *plan_fields*
    are what the profile asks once of a plan ("settings", "base_year",
    "target_year"; each {"name", "means", "sentence"}), *works* the field
    whose finds name other works and the fields each of them is asked
    ({"name", "means", "fields": {uri: question}}), None where the profile
    keeps no list of works. *frame_slots* date a value by the plan's years.
    *each(jobs, run)* runs jobs side by side. *rerank(document_id,
    sentences, chunks)* orders the pieces a search shows; *budget* is how
    many pieces a search shows, *shares* how many of them each kind of
    passage gets first ("table", "figure", "section"), *per_request* how
    many a request shows (owner decisions 2026-11-09: 50, 20/15/15, 5).
    *context(document_id)* is what the document says of itself (its title,
    its municipality), which a search sentence is written with. *numbers*
    are the numbers of the flow the reading is bounded by (`flow.Numbers`,
    the default profile's where none are given): they say *budget*, *shares*
    and *per_request* where those are not given, how many times the budget
    a field with a list reads, up to how many entries a list is shown with
    what each means and how often an answer that did not hold is asked
    again.
    """

    def __init__(self, spec, asks: Asks, order: Callable, *,
                 search_order: Optional[Callable] = None,
                 rerank: Optional[Callable] = None,
                 probes: Optional[Callable] = None,
                 known: Optional[Callable] = None,
                 span_marks: Optional[dict] = None,
                 plan_fields: Optional[dict] = None,
                 works: Optional[dict] = None,
                 frame_slots: Optional[list] = None,
                 each: Optional[Callable] = None, trace=None,
                 budget: Optional[int] = None,
                 shares: Optional[dict] = None,
                 per_request: Optional[int] = None,
                 context: Optional[Callable] = None, numbers=None,
                 flow: Optional[list] = None):
        self.spec = spec
        self.asks = asks
        self.order = order
        self.search_order = search_order or order
        self.rerank = rerank or (lambda document_id, sentences, chunks:
                                 list(chunks))
        self.probes = probes or (lambda parameter, document_id: [])
        self.known = known or (lambda claim, asked: {})
        # The conversations of the values of a document, by value
        # (`_talk`, the rule `conversation`).
        self._talks: dict = {}
        self._talk_lock = threading.Lock()
        # None: the rule `span_marks` as the step that runs reads it.
        self._span_marks = span_marks
        self.plan_fields = dict(plan_fields or {})
        self.works_field = works
        self.frame_slots = list(frame_slots or ())
        self.each = each or (lambda jobs, run: [run(job) for job in jobs])
        self.trace = trace
        self.numbers = numbers or flow_map.default()
        # What the run was given for the search instead of its numbers; the
        # numbers themselves are read at use, where a step may set its own.
        self._budget, self._per_request = budget, per_request
        self._shares = None if shares is None else dict(shares)
        self.context = context or (lambda document_id: {})
        # The drawing of the flow the document is read by (`engine.Engine`),
        # the default profile's where none is given.
        self.flow = flow
        self._engine = None
        self._engine_lock = threading.Lock()

    @property
    def span_marks(self) -> dict:
        """What a value stated for a span of years marks its rows with
        (rule `span_marks`), as the step that runs reads it."""
        return dict(rules.get("span_marks") or {}
                    if self._span_marks is None else self._span_marks)

    @property
    def budget(self) -> int:
        """The chunks a search shows (`search_pieces`), as the step that
        runs reads it; every chunk where the rule `search_to_end` is on."""
        if rules.get("search_to_end"):
            from .runner import REST_TO_END
            return REST_TO_END
        own, value = rules.stepped_value("search_pieces")
        return max(1, int(value if own else self._budget
                          if self._budget is not None
                          else flow_map.number(self.numbers,
                                               "search_pieces")))

    @property
    def shares(self) -> dict:
        """{kind of passage: its share of a search's chunks}, as the step
        that runs reads them."""
        out = {}
        for kind, name in (("table", "search_tables"),
                           ("figure", "search_figures"),
                           ("section", "search_text")):
            own, value = rules.stepped_value(name)
            out[kind] = int(value) if own else (
                self._shares[kind] if self._shares is not None
                else flow_map.number(self.numbers, name))
        return out

    @property
    def per_request(self) -> int:
        """The chunks of a search one request shows (`search_per_request`),
        as the step that runs reads it."""
        own, value = rules.stepped_value("search_per_request")
        return max(1, int(value if own else self._per_request
                          if self._per_request is not None
                          else flow_map.number(self.numbers,
                                               "search_per_request")))

    @property
    def engine(self):
        """The engine that does what the drawing says with this reading."""
        with self._engine_lock:
            if self._engine is None:
                from .engine import Engine
                self._engine = Engine(self, self.flow)
            return self._engine

    def follow_ups(self) -> int:
        """How often an answer that did not hold is asked again: the box
        asking's own number, else the flow's."""
        what = ASKING.get()
        if what is not None and what.follow_ups is not None:
            return what.follow_ups
        return flow_map.number(self.numbers, "follow_ups")

    def _traced(self, event: str, document_id: int, /,
                **values) -> None:
        if self.trace is not None:
            self.trace(event, document_id, **values)

    def _talk(self, kind: str, noted: dict, document_id: int):
        """The conversation of the value a coordinate request is about
        ([] when it has begun), None where the rule `conversation` has
        none or the request is no coordinate's."""
        if kind not in ("coord", "search") \
                or rules.get("conversation") != "per_value" \
                or not noted.get("value") or not noted.get("coordinate"):
            return None
        key = (document_id, noted.get("parameter"), noted["value"])
        with self._talk_lock:
            if len(self._talks) > 20000:
                self._talks.clear()
            return self._talks.setdefault(key, [])

    @staticmethod
    def _ways(kind: str, noted: dict, talk) -> dict:
        """*noted* with the rules whose second way this request goes
        through (`second_ways`)."""
        ways = [w for w in (noted.get("second_way") or "").split(",") if w]
        if kind in ("find", "docfield", "coord", "search", "work") \
                and rules.get("answer_with") == "quote":
            ways.append("answer_with")
        if talk:
            ways.append("conversation")
        return {**noted, **second_ways(sorted(set(ways)))}

    def _ask(self, kind: str, payload: dict, document_id: int, shape: dict,
             example: dict, counts: Counts, /, **noted):
        counts.ask(kind)
        talk = self._talk(kind, noted, document_id)
        noted = self._ways(kind, noted, talk)
        sent = payload
        if talk:
            # The questions about the value so far and what they were
            # answered go before this one, each a message of its own (the
            # runner's `make_asks`).
            payload = {**payload, "conversation": list(talk)}
        reply = getattr(self.asks, kind)(payload, document_id, shape=shape,
                                         example=shown_example(example),
                                         **noted)
        if talk is not None and isinstance(reply, dict):
            with self._talk_lock:
                talk.append({"asked": noted["coordinate"], "sent": sent,
                             "answer": reply})
        return reply

    def _follow(self, kind: str, payload: dict, document_id: int,
                shape: dict, example: dict, answer, what: list,
                counts: Counts, /, **noted):
        """The request asked again, as a request of its own: what it
        showed, the answer that did not hold and why (owner decision
        2026-11-08: "Rückfragen sind eigene Anfragen"). Its callers ask it
        as often as the flow says (`flow.Numbers.follow_ups`), each time
        with the answer before it."""
        counts.ask("follow")
        talk = self._talk(kind, noted, document_id)
        noted = self._ways(kind, noted, talk)
        payload = {**payload, "answer": answer, "what": what}
        sent = payload
        if talk:
            # The follow-up hangs on the conversation of its value.
            payload = {**payload, "conversation": list(talk)}
        reply = self.asks.follow(kind, payload, document_id, shape=shape,
                                 example=shown_example(example), **noted)
        if talk is not None and isinstance(reply, dict):
            with self._talk_lock:
                talk.append({"asked": noted["coordinate"], "follow_up": what,
                             "sent": sent, "answer": reply})
        return reply

    def lists_of(self, plan: Plan) -> None:
        """The lists of names a document builds while it is read: its
        scenarios (a field or coordinate the spec merges) and its works
        (where the profile keeps them), the publication itself the first
        work."""
        kinds = set()
        for parameter in self.spec.parameters:
            if getattr(parameter, "merged", None):
                kinds.add(parameter.merged)
            for axis in parameter.axes.values():
                if getattr(axis, "merged", None):
                    kinds.add(axis.merged)
        for kind in kinds:
            plan.names.setdefault(kind, Names(kind))
        if self.works_field is not None:
            title = plan.title_page[0][0].text if plan.title_page else ""
            plain = rules.get("publication_description") == "plain"
            plan.names.setdefault("work", Names("work", Entry(
                "this publication", "this publication" + (
                    f": {title}" if title and not plain else ""), 0, title)
                if rules.get("this_publication_first") else None))

    # -- the document ------------------------------------------------------------

    def __call__(self, plan: Plan, parameters: list, chunks=None,
                 counts: Optional[Counts] = None,
                 order_of: Optional[dict] = None) -> list:
        """[Read] of *parameters* in *plan*, read as the drawing of the flow
        says (`engine.Engine.read`): one per field and passage it was read
        in. *chunks* are the pieces read: all where None, else a list, or
        {uri: list or None} per field; *order_of* {uri: [piece key]} the
        order each field reads them in."""
        return self.engine.read(plan, parameters, chunks, counts, order_of)

    # -- finding -----------------------------------------------------------------

    def find(self, plan: Plan, parameter, chunk: Chunk,
             counts: Counts) -> dict:
        """The values of *parameter* in one piece (`find`): {"claims",
        "asked", "failed", "lost"}, *lost* [why] of every part that came to
        nothing. A piece whose answer did not fit its room is asked in
        halves of its own lines, each with the lines every piece of its
        passage shows, until a single line is a hole of its own (owner
        decision 2026-09-12: a request is split, never its answer
        rescued)."""
        out = {"claims": [], "asked": 0, "failed": collections.Counter(),
               "lost": []}
        # A piece of several passages (`Plan.groups`) is asked as one, each
        # passage under its letter; it is halved by its passages first.
        pending = [(list(chunk) if isinstance(chunk, (list, tuple))
                    else [chunk], 0)]
        while pending:
            piece, depth = pending.pop(0)
            got = self._find_once(plan, parameter,
                                  piece[0] if len(piece) == 1 else piece,
                                  counts)
            out["asked"] += got["asked"]
            out["claims"] += got["claims"]
            out["failed"].update(got["failed"])
            if got["lost"] == CUT:
                halves = self.halves(piece, depth)
                if halves:
                    pending[:0] = [(half, depth + 1) for half in halves]
                    continue
            if got["lost"]:
                out["lost"].append(got["lost"])
        return out

    @staticmethod
    def halves(piece: list, depth: int) -> Optional[list]:
        """The two halves a request whose answer did not fit its room is
        asked in instead (owner decision 2026-09-12: a request is split,
        never its answer rescued), None where it stays a hole: the rules
        `split_cut_off` (on), `split_by` (first by passages, then by lines,
        or by lines only) and `split_most` (how often one request is
        split, 0 until a single line is left)."""
        if not rules.get("split_cut_off"):
            return None
        most = rules.get("split_most")
        if most and depth >= most:
            return None
        if len(piece) > 1 and rules.get("split_by") == "chunks_then_lines":
            half = len(piece) // 2
            return [piece[:half], piece[half:]]
        if not any(len(one.numbers) > 1 for one in piece):
            return None
        first, second = [], []
        for one in piece:
            half = len(one.numbers) // 2
            if len(one.numbers) > 1:
                first.append(Chunk(one.passage, one.index,
                                   one.numbers[:half], one.carried))
                second.append(Chunk(one.passage, one.index,
                                    one.numbers[half:], one.carried))
            else:
                first.append(one)
        return [first, second] if second else None

    def _find_once(self, plan: Plan, parameter, chunk: Chunk,
                   counts: Counts) -> dict:
        """The values of *parameter* in one piece, asked once: {"claims",
        "asked", "failed", "lost"}. What does not hold is asked again with
        its reason (`follow`, as often as the flow says), then left."""
        shown = Shown()
        members = list(chunk) if isinstance(chunk, (list, tuple)) else None
        first = members[0] if members else chunk
        heads = plan.headings(first.owner) \
            if rules.get("show_headings") else []
        shown.add(letter_headings(), "headings", heads, renumber=True)
        title = plan.title_page if title_page_shown(plan) else []
        shown.add(letter_title_page(), "title_page", title, renumber=True)
        listed = self.listed(parameter)
        if members is None:
            shown.add("", "passage", own_lines(chunk))
            shown_lines = {"passage": block_payload(chunk.passage, shown)}
            at = ""
        else:
            # A piece of several passages: each under a letter of its own,
            # as the pieces of a search (owner decisions 2026-11-10).
            letters: list = []
            for member in members:
                letter = shown.letter_for(member.owner)
                shown.add(letter, letter, own_lines(member))
                if letter not in letters:
                    letters.append(letter)
            shown_lines = {"passages": {
                letter: block_payload(plan.passages.get(
                    (shown.blocks[letter].entries[0][2].owner_kind,
                     shown.blocks[letter].entries[0][2].owner_id)),
                    shown, letter) for letter in letters}}
            at = letters[0]
        payload = {"field": field_shown(parameter),
                   **({"list": listed[0]} if listed else {}),
                   **({"headings": shown.rendered(letter_headings())}
                      if heads else {}),
                   **({"title_page": shown.rendered(letter_title_page())}
                      if title else {}),
                   **shown_lines}
        example = find_example(shown, listed is not None, at)
        shape = found_format(listed is not None)
        noted = {"parameter": parameter.uri, "kind": first.passage.kind,
                 "owner": first.passage.source.owner_id, "chunk": first.index,
                 **({"chunks": len(members)} if members else {})}
        out = {"claims": [], "asked": 1, "failed": collections.Counter(),
               "lost": None}
        reply = self._ask("find", payload, plan.document_id, shape,
                          example, counts, **noted)
        if not isinstance(reply, dict):
            out["lost"] = CUT if reply == CUT else NO_ANSWER
            return out
        held, refused = self._finds(plan, shown, reply, listed,
                                    parameter.is_numeric)
        out["failed"].update(why for _, why in refused)
        for _, why in refused:
            counts.fail(why)
        for _ in range(self.follow_ups()):
            if not refused:
                break
            reply = self._follow(
                "find", payload, plan.document_id, shape, example,
                reply, refusals(refused), counts, **noted)
            out["asked"] += 1
            if not isinstance(reply, dict):
                break
            more, refused = self._finds(plan, shown, reply, listed,
                                        parameter.is_numeric)
            held = joined(held, more)
        for got in held:
            claim = self.claim(plan, parameter, got, counts)
            if claim is not None:
                out["claims"].append(claim)
        return out

    def list_of(self, options, two_step: bool = True) -> tuple:
        """A list as every request of this reading shows it (`listing`):
        with what each entry means up to the flow's number of entries
        (`flow.Numbers.list_meanings`). Every place that shows a list or
        reads a number of one goes through here, so that a number is read
        against the list it was given for."""
        return listing(options,
                       flow_map.number(self.numbers, "list_meanings"),
                       two_step)

    def listed(self, parameter) -> Optional[tuple]:
        """The list a field's finds name their entry in (`list_of`), None
        for a field without one (owner decision 2026-11-09: a field with a
        list is asked with it, the answer the number of its entry)."""
        if parameter.value_type != "category":
            return None
        options = fields.value_choice(parameter).options
        return self.list_of(options) if options else None

    @staticmethod
    def _finds(plan: Plan, shown: Shown, reply, listed=None,
               numeric: bool = False) -> tuple:
        """([Found] that hold, [(entry, why)] that do not) of a reply: a
        number's words name exactly one number, and a find of a field with
        a list names a number of it (`not_an_option`)."""
        held, refused = [], []
        for entry in reply.get("found") or ():
            if not isinstance(entry, dict):
                continue
            got = resolve(shown, entry, plan.passages)
            if got.why is None and numeric \
                    and rules.get("words_need_number") \
                    and number_of(got.words) is None:
                got.why = WORDS_NOT_IN_LINE
            if got.why is None and got.passage is None:
                got.why = NOT_AN_ADDRESS
            if got.why is None and listed is not None:
                got.entry = picked_entry(entry.get("entry"), len(listed[1]))
                if got.entry is None:
                    if rules.get("outside_list") == "keep":
                        got.entry, got.outside = 0, True
                    else:
                        got.why = NOT_AN_OPTION
            checked = own_check(got) if got.why is None else None
            if checked is not None:
                got.why = checked[0]
            if got.why is None:
                held.append(got)
            else:
                given = {key: entry.get(key) for key in
                         ("entry", "at", "quote", "words") if key in entry}
                if checked is not None:
                    given["told"] = checked[1]
                refused.append((given, got.why))
        return held, refused

    def claim(self, plan: Plan, parameter, got: Found,
              counts: Counts) -> Optional[dict]:
        """The claim of a value found: its number or words, the line as its
        quote, its address, the head of its column, and for a figure that a
        model read it off a picture (`drawn`, trust level C). A value of a
        list is the entry its find named, the entry of a group named asked
        among the group's (`list`); one found without its entry is asked
        it."""
        passage = got.passage
        if passage is None:
            return None
        numbers = [line.number for line, _ in got.lines]
        claim: dict = {"source": "Q1"}
        if parameter.is_numeric:
            try:
                value = float(number_of(got.words))
            except (TypeError, ValueError):
                return None
            claim["value"] = int(value) if value.is_integer() else value
            claim["value_raw"] = got.words
        elif parameter.value_type == "category":
            slot = fields.value_choice(parameter)
            entry = ""
            if slot.options and got.entry is not None:
                _lines, choices, grouped = self.list_of(slot.options)
                if got.entry and grouped:
                    entry = self.entry(plan, parameter.uri, "value", slot,
                                       got.words, got, counts,
                                       group=choices[got.entry - 1])
                elif got.entry:
                    entry = choices[got.entry - 1]
            elif slot.options:
                entry = self.entry(plan, parameter.uri, "value", slot,
                                   got.words, got, counts)
            claim["value"] = entry or ""
            claim["value_raw"] = got.words
            if got.outside:
                # An entry outside the list, its wording kept (rule
                # `outside_list`): the wording is the note, as everywhere
                # an answer is none of a closed list's.
                claim[f"{slot.name}_seen"] = got.words
                self._traced("second_way", plan.document_id,
                             rule="outside_list", parameter=parameter.uri)
        else:
            claim["value"] = got.words
        claim["quote"] = short_quote(passage, numbers, min_quote_chars())
        claim["at"] = {"owner": list(passage.owner), "line": numbers[0],
                       **({"cell": got.cell} if got.cell else {}),
                       **({"last": numbers[-1]} if len(numbers) > 1 else {})}
        if got.cell and passage.kind == "table":
            head = passage.head_of(got.cell)
            if head:
                claim["head"] = head
        if passage.drawn:
            claim["drawn"] = True
        return claim

    # -- what a document has once ------------------------------------------------

    def shown_order(self, plan: Plan, sentences: list, pieces: list,
                    budget: Optional[int] = None,
                    shares: Optional[dict] = None) -> list:
        """The pieces a search for *sentences* shows, in the order it shows
        them (owner decisions 2026-11-09): of the pieces of the passages
        the vector search finds best, the *budget* best by kind
        (`budgeted`), ordered once by the reranker with the same
        sentences."""
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        ranked = self.search_order(plan.document_id, sentences, pieces)
        picked = budgeted(ranked, budget or self.budget,
                          self.shares if shares is None else shares)
        if not sentences or not rules.get("rerank") \
                or len(picked) < rules.get("rerank_least_pieces"):
            return picked
        return self.rerank(plan.document_id, sentences, picked)

    def rerank_left(self, plan: Plan, sentences: list, pieces: list) -> list:
        """*pieces* ordered by the reranker with *sentences* again, for
        the rule `rerank_when` (each round), where the rule `rerank` is on
        and there are enough of them."""
        if not rules.get("rerank") \
                or len(pieces) < rules.get("rerank_least_pieces"):
            return pieces
        return self.rerank(plan.document_id, sentences, pieces)

    def ask_window(self, plan: Plan, field_: dict, batch: list,
                   counts: Counts, uri: str, *, numbers: bool = False,
                   listed=None, title_page: bool = False) -> tuple:
        """([Found] that hold, lost) of one request of a field asked over
        pieces of the document (`docfield`, owner decision 2026-11-08):
        the title page where *title_page*, the pieces *batch* each under a
        letter of its own; what does not hold is asked again with its
        reason (as often as the flow says). *listed* is the field's list
        (`listing`), whose entry a find names. *lost* is CUT or NO_ANSWER
        where the request came to nothing, else None. A request whose
        answer did not fit its room is asked in halves as a request about
        a piece is (`halves`, owner decision 2026-09-12)."""
        mode = rules.get("show_title_page")
        title_page = {"always": True, "never": False}.get(mode, title_page)
        held_all: list = []
        lost_all = None
        pending = [(list(batch), 0)]
        while pending:
            piece, depth = pending.pop(0)
            held, lost = self._window_once(
                plan, field_, piece, counts, uri, numbers=numbers,
                listed=listed, title_page=title_page)
            if lost == CUT:
                halves = self.halves(piece, depth)
                if halves:
                    pending[:0] = [(half, depth + 1) for half in halves]
                    continue
            if lost:
                lost_all = lost_all or lost
            held_all = joined(held_all, held)
        return held_all, lost_all

    def _window_once(self, plan: Plan, field_: dict, batch: list,
                     counts: Counts, uri: str, *, numbers: bool = False,
                     listed=None, title_page: bool = False) -> tuple:
        """([Found] that hold, lost) of one request of a window, asked
        once (`ask_window`)."""
        shape = found_format(listed is not None)
        shown = Shown()
        if title_page:
            shown.add(letter_title_page(), "title_page", plan.title_page,
                      renumber=True)
        letters: list = []
        for chunk in batch:
            letter = shown.letter_for(chunk.owner)
            shown.add(letter, letter, own_lines(chunk))
            if letter not in letters:
                letters.append(letter)
        blocks = {letter: block_payload(
            plan.passages.get((shown.blocks[letter].entries[0][2]
                               .owner_kind,
                               shown.blocks[letter].entries[0][2]
                               .owner_id)), shown, letter)
            for letter in letters}
        payload = {"field": field_,
                   **({"list": listed[0]} if listed else {}),
                   **({"title_page": shown.rendered(letter_title_page())}
                      if letter_title_page() in shown.blocks else {}),
                   **({"passages": blocks} if blocks else {})}
        example = find_example(
            shown, listed is not None,
            letter_title_page() if letter_title_page() in shown.blocks
            else (letters[0] if letters else ""))
        reply = self._ask("docfield", payload, plan.document_id, shape,
                          example, counts, parameter=uri,
                          chunks=len(batch))
        if not isinstance(reply, dict):
            return [], (CUT if reply == CUT else NO_ANSWER)
        held, refused = self._finds(plan, shown, reply, listed, numbers)
        for _, why in refused:
            counts.fail(why)
        for _ in range(self.follow_ups()):
            if not refused:
                break
            reply = self._follow(
                "docfield", payload, plan.document_id, shape, example,
                reply, refusals(refused), counts, parameter=uri)
            if not isinstance(reply, dict):
                break
            more, refused = self._finds(plan, shown, reply, listed,
                                        numbers)
            held = joined(held, more)
        return held, None

    def settled(self, plan: Plan, counts: Counts) -> None:
        """What the plan settles for all its values and its own years, as
        the drawing of the flow asks them (`engine.Engine.prepare`)."""
        engine = self.engine
        from .engine import Doc, Scope
        scope = Scope(None, True, doc=Doc(plan, counts, []), plan=plan)
        for frame in engine.settled_frames:
            if not frame.get("off"):
                engine.run_node(frame, scope)

    # -- lists ---------------------------------------------------------------------

    def entry(self, plan: Plan, uri: str, name: str, slot, words: str,
              got: Optional[Found], counts: Counts, several: bool = False,
              group: Optional[str] = None):
        """The entry of *slot*'s list a wording means, asked once per
        document, field, coordinate, wording and group (`list`, owner
        decision 2026-11-08): its label, a list of labels where several may
        be meant, "" where none fits (0). With *group* (a find named it,
        owner decision 2026-11-09) the entries of that group are asked."""
        key = ("list", uri, name, flat(words).casefold(), group or "")
        if not rules.get("entry_once_per_wording"):
            # Once for every place the wording stands in (rule
            # `entry_once_per_wording`), not once for the wording.
            source = got.source if got is not None else None
            key += ((source.owner_kind, source.owner_id,
                     got.lines[0][0].number, got.cell) if source is not None
                    else len(plan.lists),)
        with plan.key_lock(key):
            if key not in plan.lists:
                plan.lists[key] = self._entry(plan, uri, name, slot, words,
                                              got, counts, several, group)
            return copy.copy(plan.lists[key])

    @staticmethod
    def earlier_entries(plan: Plan, uri: str, name: str,
                        group: Optional[str]) -> list:
        """[{"words", "entry"}] the document's list of this coordinate has
        already settled for other wordings, for the rule
        `list_shows_earlier`."""
        out = []
        for key, entry in list(plan.lists.items()):
            if key[:3] == ("list", uri, name) and key[4] == (group or "") \
                    and entry:
                out.append({"words": key[3], "entry": entry})
        return out

    def _entry(self, plan: Plan, uri: str, name: str, slot, words: str,
               got: Optional[Found], counts: Counts, several: bool,
               group: Optional[str] = None):
        """The list as it is: each entry by its name and what it means,
        never by how this document named it before (owner decision
        2026-11-09: what an earlier answer wrote beside an entry steered
        every later one)."""
        options = list(slot.options)
        if not options:
            return [words] if several else words
        shown_line: dict = {}
        if got is not None and got.lines:
            shown_line["lines"] = [line.text for line, _ in got.lines]
            if got.passage is not None and got.passage.kind == "table":
                shown_line["table"] = got.passage.title
        noted = {"parameter": uri, "coordinate": name}
        chosen = options
        if group is not None:
            chosen = [o for o in options
                      if (getattr(o, "group", "") or "") == group]
            if not chosen:
                # The group the find named has no entry: the whole list, or
                # none (rule `group_without_entries`).
                if rules.get("group_without_entries") == "none":
                    return [] if several else ""
                chosen = options
        else:
            lines, choices, grouped = self.list_of(options)
            if grouped:
                # A long list in two steps: its groups, then the entries of
                # the group chosen (the first group named, or every one the
                # rule `group_picks_taken` says), with what each means.
                every = rules.get("group_picks_taken") == "all"
                payload = {"words": words,
                           "question": slot.question or name,
                           **shown_line, **settings_of(plan), "list": lines}
                reply = self._ask("list", payload, plan.document_id,
                                  entry_format(several=every),
                                  {"entry": [1] if every else 1}, counts,
                                  **noted, step="group")
                picks = self._picks(reply, len(choices), every) or []
                if picks:
                    named = {choices[i - 1] for i in
                             (picks if every else picks[:1])}
                    chosen = [o for o in options
                              if (getattr(o, "group", "") or "") in named]
        # What is chosen among now are entries, never the groups again.
        listed, labels, _grouped = self.list_of(chosen, two_step=False)
        payload = {"words": words, "question": slot.question or name,
                   **shown_line, **settings_of(plan), "list": listed}
        ways = [] if rules.get("entry_once_per_wording") \
            else ["entry_once_per_wording"]
        if rules.get("list_shows_earlier"):
            earlier = self.earlier_entries(plan, uri, name, group)
            if earlier:
                payload["earlier"] = earlier
                ways.append("list_shows_earlier")
        noted = {**noted, **second_ways(ways)}
        example = {"entry": [1]} if several else {"entry": 1}
        shape = entry_format(several)
        reply = self._ask("list", payload, plan.document_id, shape, example,
                          counts, **noted)
        picks = self._picks(reply, len(labels), several)
        if picks is None:
            counts.fail(NOT_AN_OPTION)
        for _ in range(self.follow_ups()):
            if picks is not None:
                break
            given = reply.get("entry") if isinstance(reply, dict) else None
            reply = self._follow("list", payload, plan.document_id, shape,
                                 example, reply,
                                 [say(NOT_AN_OPTION, given=given)],
                                 counts, **noted)
            picks = self._picks(reply, len(labels), several)
        picked = [labels[i - 1] for i in picks or []]
        if several:
            return picked
        return picked[0] if picked else ""

    @staticmethod
    def _picks(reply, size: int, several: bool) -> Optional[list]:
        """The numbers an answer names, 0 dropped; None where one is no
        number of the list (`not_an_option`)."""
        if not isinstance(reply, dict):
            return []
        given = reply.get("entry")
        picks = given if isinstance(given, list) else [given]
        out: list = []
        for pick in picks:
            if isinstance(pick, bool):
                return None
            try:
                pick = int(str(pick).strip())
            except (TypeError, ValueError):
                return None
            if pick < 0 or pick > size:
                return None
            if pick and pick not in out:
                out.append(pick)
        return out if several else out[:1]

    # -- names of the document --------------------------------------------------

    def name_of(self, plan: Plan, kind: str, words: str,
                got: Optional[Found], counts: Counts, work: int = 0,
                besides: tuple = (), group: bool = False,
                uri: str = "", work_read: Optional[dict] = None):
        """The entries of the document's list of *kind* a name means
        (`names`): [(label, number)], a new entry where the name is not on
        the list yet, ("out", label) for an entry *besides* the names
        ((label, means)); with *group* the words may name several entries;
        [] where they name no such thing (0, owner decision 2026-11-09);
        None where no answer came. Each name is asked once per document and
        work. A new entry keeps *work_read*, how the value it is read for
        read its work."""
        names = plan.names[kind]
        if self.asks.names is None:
            return []
        works = plan.names.get("work") if kind != "work" else None
        key = (kind, flat(words).casefold(), work, group)
        with plan.key_lock(("names",) + key):
            with names.lock:
                if key in names.asked:
                    return list(names.asked[key])
            meant = rules.get("names_meanings")
            listed = [f"{i} {label} (means: {means})" if meant
                      else f"{i} {label}"
                      for i, (label, means) in enumerate(besides, start=1)]
            offset = len(listed)
            numbers = {}
            for number, text in names.shown(works):
                numbers[offset + len(numbers) + 1] = number
                listed.append(f"{offset + len(numbers)} {text}")
            payload = {"name": words,
                       **({"lines": [line.text for line, _ in got.lines]}
                          if got is not None and got.lines else {}),
                       **({"work": works.entries[work - 1].label}
                          if works is not None
                          and 0 < work <= len(works.entries) else {}),
                       "list": listed}
            shape = entry_format(several=group, new=True)
            example = {"entry": [1]} if group else {"entry": 1}
            noted = {"kind": kind, "names": len(listed),
                     **({"parameter": uri} if uri else {})}
            reply = self._ask("names", payload, plan.document_id, shape,
                              example, counts, **noted)
            if not isinstance(reply, dict):
                return None
            picks = self._name_picks(reply, len(listed))
            if picks is None:
                counts.fail("name_not_listed")
                if said_none(reply) and not rules.get("name_may_be_none"):
                    noted = {**noted, **second_ways(["name_may_be_none"])}
            for _ in range(self.follow_ups()):
                if picks is not None:
                    break
                reply = self._follow("names", payload, plan.document_id,
                                     shape, example, reply,
                                     [say("name_not_listed",
                                          given=reply.get("entry"))],
                                     counts, **noted)
                if not isinstance(reply, dict):
                    break
                picks = self._name_picks(reply, len(listed))
            if picks is None:
                return None
            out = []
            for pick in picks:
                if pick == NEW:
                    number = names.add(words, work,
                                       got.quote if got is not None else "",
                                       work_read)
                    out.append((names.entries[number - 1].label, number))
                elif pick <= offset:
                    out.append(("out", besides[pick - 1][0]))
                else:
                    number = numbers[pick]
                    out.append((names.entries[number - 1].label, number))
            if not group:
                out = out[:1]
            with names.lock:
                names.asked[key] = list(out)
            return out

    @staticmethod
    def _name_picks(reply, size: int) -> Optional[list]:
        if not isinstance(reply, dict):
            return []
        given = reply.get("entry")
        picks = given if isinstance(given, list) else [given]
        out: list = []
        for pick in picks:
            if isinstance(pick, str) and pick.strip().lower() == NEW:
                if NEW not in out:
                    out.append(NEW)
                continue
            if isinstance(pick, bool):
                return None
            try:
                pick = int(str(pick).strip())
            except (TypeError, ValueError):
                return None
            if pick < 0 or pick > size:
                return None
            if not pick and not rules.get("name_may_be_none"):
                # 0 is an answer outside the list where the rule
                # `name_may_be_none` is off.
                return None
            if pick and pick not in out:
                out.append(pick)
        return out

    # -- coordinates ---------------------------------------------------------------

    def coordinate(self, plan: Plan, read: Read, row: Row, group, slot,
                   counts: Counts, clone: Callable) -> list:
        """One coordinate of one value as the drawing's frame of
        coordinates asks it (`engine.Engine.coordinate`): [the rows made
        beside it]."""
        return self.engine.coordinate(plan, read, row, group, slot, counts,
                                      clone)

    def coord_payload(self, plan: Plan, read: Read, row: Row,
                      slot) -> tuple:
        """(Shown, payload, noted) of what every request about one
        coordinate of a value shows: the value's place (`show_value`), the
        field, the question and what the value has read (`known`); the
        payload None where the value has no place."""
        parameter = read.batch.parameter
        shown, payload = show_value(plan, row.claim)
        noted = {"parameter": parameter.uri, "coordinate": slot.name,
                 "owner": ((row.claim.get("at") or {}).get("owner")
                           or [None, None])[1], "value": row.label}
        if not shown.blocks:
            return shown, None, noted
        known = self.known(row.claim, [slot.name]) \
            if rules.get("show_known") else {}
        payload = {**payload, "field": field_shown(parameter),
                   "question": slot.question or slot.name,
                   **({"known": known} if known else {})}
        return shown, payload, noted

    def ask_own_place(self, plan: Plan, read: Read, row: Row, slot,
                      counts: Counts, clone: Callable) -> tuple:
        """(answered, rows made, payload, noted) of a coordinate asked at its
        value's own place (`coord`): its line with the head of its table or
        the sentences beside it, the headings up to it, the title page and
        the plan's settings; the answer an address and words, or 0. What
        does not hold is asked again with its reason, then stays
        `unbacked`. Not answered where the value has no place or no answer
        came."""
        shown, payload, noted = self.coord_payload(plan, read, row, slot)
        if payload is None:
            return False, [], None, noted
        several = self.several(slot)
        example = self.coord_example(shown, several)
        reply = self._ask("coord", payload, plan.document_id,
                          coord_format(several), example, counts, **noted)
        if not isinstance(reply, dict):
            # No answer for this value: `unanswered` (`mark_unanswered`).
            return False, [], payload, noted
        made, _held = self.take(plan, read, row, slot, shown, reply, payload,
                                "coord", example, counts, clone, ("own", 1),
                                noted)
        return True, made, payload, noted

    @staticmethod
    def several(slot) -> bool:
        return bool(getattr(slot, "several", False)
                    or getattr(slot, "merged", None))

    @staticmethod
    def coord_example(shown: Shown, several: bool) -> dict:
        at = point(shown, False)
        if several:
            return {"found": [{**at, "words": fields.said()}]}
        return {**at, "words": fields.said()}

    @staticmethod
    def coord_finds(reply) -> list:
        if not isinstance(reply, dict):
            return []
        if isinstance(reply.get("found"), list):
            return [e for e in reply["found"] if isinstance(e, dict)]
        if has_address(reply):
            return [{**({"at": reply["at"]} if "at" in reply else {}),
                     **({"quote": reply["quote"]} if "quote" in reply
                        else {}), "words": reply.get("words")}]
        return []

    def take(self, plan: Plan, read: Read, row: Row, slot, shown: Shown,
             reply: dict, payload: dict, kind: str, example: dict,
             counts: Counts, clone: Callable, window: tuple,
             noted: dict) -> tuple:
        """(rows made, held) of a coordinate's answer: its finds each read
        onto the row, one row per entry where several are named, and
        checked (`merge_field`); what does not hold is asked again with its
        reason (`follow`, as often as the flow says), then stays
        `unbacked`."""
        finds = self.coord_finds(reply)
        if not finds:
            return [], False
        made, held, failed = self.settle(plan, read, row, slot, shown, finds,
                                         counts, clone, window)
        if failed and not held:
            for _ in range(self.follow_ups()):
                reply = self._follow(kind, payload, plan.document_id,
                                     coord_format(self.several(slot),
                                                  more=kind == "search"),
                                     example, reply, failed, counts, **noted)
                finds = self.coord_finds(reply)
                if not finds:
                    break
                more, held, failed = self.settle(plan, read, row, slot,
                                                 shown, finds, counts, clone,
                                                 window)
                made += more
                if held or not failed:
                    break
            if not held and rules.get("after_follow_ups") == "unbacked":
                row.claim[f"{slot.name}_state"] = UNBACKED
        return made, held

    def settle(self, plan: Plan, read: Read, row: Row, slot, shown: Shown,
               finds: list, counts: Counts, clone: Callable,
               window: tuple) -> tuple:
        """(rows made, held, [what failed]) of a coordinate's finds read
        onto *row*: each entry they name is a row of its own."""
        parameter = read.batch.parameter
        evidence = shown.evidence()
        answers: list = []
        failed: list = []
        for entry in finds:
            got = resolve(shown, entry, plan.passages)
            if got.why is not None:
                counts.fail(got.why)
                failed.append({"at": entry.get("at"),
                               "words": entry.get("words"),
                               "why": told(got.why, entry)})
                continue
            checked = own_check(got)
            if checked is not None:
                counts.fail(checked[0])
                failed.append({"at": entry.get("at"),
                               "words": entry.get("words"),
                               "why": checked[1]})
                continue
            answers += self.answers(plan, parameter, row, slot, got, counts)
        if not answers:
            return [], False, failed
        rows = [row] + [clone(row) for _ in answers[1:]]
        made = rows[1:]
        held = False
        for one, (answer, means) in zip(rows, answers):
            one.claim.pop(f"{slot.name}_state", None)
            got = merge_field([one], evidence, slot,
                              {"answers": {one.label: answer}},
                              window=window, bases=plan.bases)
            if one.claim.get(f"{slot.name}_state") == READ:
                held = True
                if means is not None:
                    one.claim[f"{slot.name}_means"] = list(means)
                made += span_rows(one, slot, answer.get("until"),
                                  self.span_marks, clone)
            for failure in got["failed"]:
                counts.fail(failure.get("why") or UNBACKED)
                failed.append({"words": failure.get("raw")
                               or failure.get("given"),
                               "why": failure.get("reason")})
        return made, held, failed

    def answers(self, plan: Plan, parameter, row: Row, slot, got: Found,
                counts: Counts) -> list:
        """[(answer for `merge_field`, names it means or None)] of one find
        of a coordinate: a year from its words, an entry of its list, a name
        of the document's list, or the words themselves."""
        quote, words = got.quote, got.words
        base = {"value_raw": words, "quote": quote}
        if slot.kind == NUMBER:
            years = [int(y) for y in years_in(words)]
            if not years:
                return [(self.plan_year(plan, parameter, slot, got, counts),
                         None)]
            answer = {"value": years[0], **base}
            if len(years) > 1 and rules.get("years_in_words") == "span_ends" \
                    and span().search(words) and years[-1] > years[0]:
                answer["until"] = years[-1]
            return [(answer, None)]
        merged = getattr(slot, "merged", None)
        if merged and merged in plan.names:
            besides = tuple((o.label, o.definition) for o in slot.options)
            group = group_taken(parameter)
            picked = self.name_of(plan, merged, words, got, counts,
                                  work=self.work_of(plan, row),
                                  besides=besides, group=group,
                                  uri=parameter.uri)
            if picked is None:
                return [({"value": words, **base}, None)]
            if not picked:
                # The words name no such thing (0): read as they stand,
                # meaning no entry (owner decision 2026-11-09).
                return [({"value": words, **base}, [])]
            outs = [label for kind, label in picked if kind == "out"]
            names = [label for label, _n in picked if label != "out"]
            several = next((o.label for o in slot.options
                            if o.uri == SEVERAL), None)
            if outs and not names:
                return [({"value": outs[0], **base}, [])]
            if len(names) == 1:
                return [({"value": words, **base}, names)]
            # The words of a group of scenarios: one row per member, each
            # holding the words under the entry of several (owner decision
            # 2026-11-08, i).
            if several is None:
                return [({"value": words, **base}, [name]) for name in names]
            return [({"value": several, **base}, [name]) for name in names]
        if slot.is_closed:
            many = bool(getattr(slot, "several", False))
            picked = self.entry(plan, parameter.uri, slot.name, slot, words,
                                got, counts, several=many)
            labels = [label for label in (picked if isinstance(picked, list)
                                          else [picked]) if label] or [""]
            return [({"value": label, **base}, None) for label in labels]
        return [({"value": words, "quote": quote}, None)]

    @staticmethod
    def work_of(plan: Plan, row: Row) -> int:
        """The number of the work a value was read for in the document's
        list of works, 0 where none."""
        means = row.claim.get("work_means")
        works = plan.names.get("work")
        if not means or works is None:
            return 0
        return next((i for i, e in enumerate(works.entries, start=1)
                     if e.label == means[0]), 0)

    def quantity(self, plan: Plan, parameter, row: Row, slot,
                 counts: Counts) -> None:
        """What a number is, by the words it was read with: its own
        designation, the head of its column and its unit go to the list
        (`list`), and the line that holds the designation, else the value's
        own, is its quote (owner decision 2026-11-08: "quantity geht mit den
        Worten von what, Kopf und Einheit direkt in die Listenfrage")."""
        claim = row.claim
        what = claim.get("what_raw") or claim.get("what") \
            if claim.get("what_state") == READ else None
        parts = {"what": what, "head": claim.get("head"),
                 "unit": claim.get("unit_raw") or claim.get("unit")}
        said = [parts[name] for name in rules.get("quantity_words")
                if name in parts]
        words = rules.get("quantity_joiner").join(str(s) for s in said if s) \
            or str(claim.get("value_raw") or claim.get("value"))
        shown, _payload = show_value(plan, claim, plain=True)
        own = shown.blocks.get("")
        if what:
            quote = claim.get("what_quote") or claim.get("quote")
            wording = what
            source = Source(*(claim.get("what_source") or ["section", 0]),
                            quote)
        else:
            quote = claim.get("quote")
            wording = claim.get("head") or claim.get("value_raw") \
                or str(claim.get("value"))
            source = own.entries[0][2] if own else Source("section", 0, quote)
        got = Found(lines=own.lines if own else [], words=words,
                    passage=plan.passages.get(tuple((claim.get("at") or {})
                                                    .get("owner") or ())))
        label = self.entry(plan, parameter.uri, slot.name, slot, words, got,
                           counts)
        answer = {"value": label or "", "value_raw": wording, "quote": quote}
        merge_field([row], shown.evidence() + [Source(
            source.owner_kind, source.owner_id, quote or "")], slot,
            {"answers": {row.label: answer}}, window=("own", 1))

    def plan_year(self, plan: Plan, parameter, slot, got: Found,
                  counts: Counts) -> dict:
        """The year a find names by the plan's word for its state
        ("Basisjahr", "Zieljahr"), asked among the plan's base and target
        years (`list`, owner decision 2026-11-07): the answer for
        `merge_field`, which reads it where the words stand in the line and
        the year is one of the plan's (`pipeline.named_year`)."""
        listed = [b for b in plan.bases if b.get("axis") == slot.name]
        empty = {"value": "", "value_raw": got.words, "quote": got.quote}
        if not listed:
            return empty
        payload = {"words": got.words,
                   "lines": [line.text for line, _ in got.lines],
                   "question": slot.question or slot.name,
                   "list": years_listed(listed)}
        reply = self._ask("list", payload, plan.document_id, entry_format(),
                          {"entry": 1}, counts, parameter=parameter.uri,
                          coordinate=slot.name, step="plan_years")
        picks = self._picks(reply, len(listed), False) or []
        if not picks:
            return empty
        return {"value": listed[picks[0] - 1]["year"],
                "value_raw": got.words, "quote": got.quote}

    def last_year(self, plan: Plan, parameter, row: Row, slot,
                  counts: Counts, noted: dict) -> None:
        """A year nothing found, asked last with the plan's base and target
        years (owner decision 2026-11-07): the line of the value's place
        that names the plan's word for its state, and the year of the list
        it means; read where the words stand in that line and the year is
        one of the plan's (`pipeline.named_year`)."""
        listed = [b for b in plan.bases if b.get("axis") == slot.name]
        shown, payload = show_value(plan, row.claim)
        payload = {**payload, "question": slot.question or slot.name,
                   "list": years_listed(listed)}
        example = {**point(shown, False), "words": fields.said(),
                   "entry": 1}
        reply = self._ask("list", payload, plan.document_id, year_format(),
                          example, counts, **{**noted, "step": "plan_years"})
        if not isinstance(reply, dict):
            return
        picks = self._picks(reply, len(listed), False) or []
        got = resolve(shown, reply, plan.passages)
        if not picks or got.why is not None:
            return
        state = row.claim.get(f"{slot.name}_state")
        row.claim.pop(f"{slot.name}_state", None)
        merge_field([row], shown.evidence(), slot, {"answers": {row.label: {
            "value": listed[picks[0] - 1]["year"], "value_raw": got.words,
            "quote": got.quote}}}, window=("plan_years", 1),
            bases=plan.bases)
        if row.claim.get(f"{slot.name}_state") != READ and state:
            row.claim[f"{slot.name}_state"] = state

    # -- search --------------------------------------------------------------------

    def search_sentence(self, plan: Plan, read: Read, row: Row, slot,
                        counts: Counts, before: Optional[list] = None) -> str:
        """The sentence a search goes with (`sentence`); a question where
        the rule `question_as_sentence` takes none is the field's own
        sentence instead, and a question taken is counted. *before* are the
        sentences of the rounds before, shown where a new one is asked
        (`phrase` with `before`). The rule `search_with` may take the
        field's question or the coordinate's name instead, with no request
        for a sentence."""
        how = rules.get("search_with")
        if how == "question":
            return slot.question or slot.name
        if how == "name":
            return slot.name
        sentence = self.sentence(plan, read, row, slot, counts, before)
        if is_question(sentence) and not rules.get("question_as_sentence"):
            sentence = self.field_sentence(plan, read, slot)
        if is_question(sentence):
            counts.question()
            log.info("   search of %s/%s in document %s with a question: %s",
                     read.batch.parameter.uri, slot.name, plan.document_id,
                     sentence)
        return sentence

    def field_sentence(self, plan: Plan, read: Read, slot) -> str:
        """What a search goes with where no sentence was written for it
        (rule `search_fallback`): the field's own search sentence, else its
        question or name; or its question, or its name, or none."""
        return self.fallback(plan, read.batch.parameter, slot)

    def fallback(self, plan: Plan, parameter, slot) -> str:
        how = rules.get("search_fallback")
        if how == "none":
            return ""
        if how == "name":
            return slot.name
        if how == "question":
            return slot.question or slot.name
        return next(iter(self.probes(parameter, plan.document_id) or ()),
                    "") or slot.question or slot.name

    def sentence(self, plan: Plan, read: Read, row: Row, slot,
                 counts: Counts, before: Optional[list] = None) -> str:
        """The sentence a search for one coordinate goes with: as the plan
        would print the answer for this value (HyDE), written by a request
        of its own once per document, field, coordinate and wording of the
        value (`phrase`, owner decision 2026-11-09); the field's own
        sentence where none was written."""
        parameter = read.batch.parameter
        words = str(row.claim.get("value_raw") or row.claim.get("value")
                    or "")
        key = ("phrase", parameter.uri, slot.name, flat(words).casefold(),
               tuple(before or ()))
        if not before:
            key = key[:4]
        with plan.key_lock(key):
            if key not in plan.lists:
                plan.lists[key] = self._sentence(plan, parameter, slot, row,
                                                 words, counts, before)
            sentence = plan.lists[key]
        if sentence:
            return sentence
        return self.fallback(plan, parameter, slot)

    def _sentence(self, plan: Plan, parameter, slot, row: Row, words: str,
                  counts: Counts, before: Optional[list] = None) -> str:
        if self.asks.phrase is None:
            return ""
        at = row.claim.get("at") or {}
        owner = tuple(at.get("owner") or ())
        shown, _payload = show_value(plan, row.claim, plain=True)
        own = shown.blocks.get("")
        lines = [line.text for line, _ in own.lines] if own else []
        context = {key: value for key, value
                   in (self.context(plan.document_id) or {}).items()
                   if isinstance(value, str) and value.strip()}
        if not context and plan.title_page \
                and rules.get("document_name_fallback"):
            context = {"name": plan.title_page[0][0].text}
        heads = [line.text for line, _ in plan.headings(owner)] \
            if owner and rules.get("show_headings") else []
        shows = rules.get("phrase_shows")
        payload = {
            **({"label": parameter.label} if "label" in shows else {}),
            **({"description": parameter.description}
               if "description" in shows else {}),
            **({"document": context} if context and "document" in shows
               else {}),
            **({"question": slot.question or slot.name}
               if "question" in shows else {}),
            **({"value": {"words": words, "lines": lines}}
               if "value" in shows else {}),
            **({"headings": heads} if heads and "headings" in shows else {}),
            **({"before": list(before)} if before and "before" in shows
               else {})}
        reply = self._ask("phrase", payload, plan.document_id,
                          phrase_format(), None, counts,
                          parameter=parameter.uri, coordinate=slot.name)
        phrase = reply.get("phrase") if isinstance(reply, dict) else ""
        return phrase.strip() if isinstance(phrase, str) else ""

    def search_round(self, plan: Plan, read: Read, row: Row, slot,
                     payload: dict, batch: list, counts: Counts,
                     clone: Callable, window: tuple, noted: dict) -> tuple:
        """(rows made, held, what it asks to fetch) of one request of a
        search: the value's place and the pieces *batch* under letters of
        their own."""
        shown, base = show_value(
            plan, row.claim, headings=False if slot.name == "work" else None)
        letters: list = []
        for chunk in batch:
            letter = shown.letter_for(chunk.owner)
            shown.add(letter, letter, own_lines(chunk))
            if letter not in letters:
                letters.append(letter)
        blocks = {letter: block_payload(plan.passages.get(
            (shown.blocks[letter].entries[0][2].owner_kind,
             shown.blocks[letter].entries[0][2].owner_id)), shown, letter)
            for letter in letters}
        several = self.several(slot)
        # What the value's place shows is what this step says (its own
        # values of the rules `show_*`), not what the step before it showed.
        known = self.known(row.claim, [slot.name]) \
            if rules.get("show_known") else {}
        ask_payload = {**base, "field": field_shown(read.batch.parameter),
                       "question": slot.question or slot.name,
                       **({"known": known} if known else {}),
                       "passages": blocks}
        example = self.coord_example(shown, several)
        reply = self._ask("search", ask_payload, plan.document_id,
                          coord_format(several, more=True), example, counts,
                          **noted, chunks=len(batch))
        if not isinstance(reply, dict):
            return [], False, []
        own = tuple((row.claim.get("at") or {}).get("owner") or ())
        kept = []
        for entry in self.coord_finds(reply):
            got = resolve(shown, entry, plan.passages)
            if got.why is None and got.letter in letters_others() \
                    and got.source is not None \
                    and (rules.get("about_other") == "any"
                         or (got.source.owner_kind, got.source.owner_id)
                         != own) \
                    and self.asks.check is not None \
                    and about_box() is not None \
                    and not self.about(plan, row, slot, got, counts, noted):
                continue
            kept.append(entry)
        more = reply.get("more") if isinstance(reply.get("more"), list) \
            else []
        if not kept:
            return [], False, more
        # The first find alone is the answer where the rule says so: the
        # list of finds a reply may still carry is not read besides it.
        answer = {**reply, "found": kept} \
            if several or rules.get("search_finds_taken") == "all" \
            else {**{key: value for key, value in reply.items()
                     if key != "found"}, **kept[0]}
        made, held = self.take(plan, read, row, slot, shown, answer,
                                  ask_payload, "search", example, counts,
                                  clone, window, noted)
        return made, held, [] if held else more

    def about(self, plan: Plan, row: Row, slot, got: Found, counts: Counts,
              noted: dict) -> bool:
        """Does the place a find of another passage stands in speak about
        this value (`check`, owner decision 2026-11-07)? The box that
        checks reads its own values (`about_shows`, `about_no_reply`)."""
        what = ASKING.get()
        step = what.about_step() if what is not None \
            and what.about_step is not None else contextlib.nullcontext()
        with step:
            shows = rules.get("about_shows")
            shown, payload = show_value(plan, row.claim, plain=True)
            owner = tuple(((row.claim.get("at") or {}).get("owner")) or ())
            heads = [line.text for line, _ in plan.headings(owner)] \
                if owner and "headings" in shows \
                and rules.get("show_headings") else []
            ask_payload = {
                **({"value": payload.get("value")} if "value" in shows
                   else {}),
                **({"passage": block_payload(plan.passages.get(owner), shown)
                    if owner in plan.passages else None}
                   if "passage" in shows else {}),
                **({"headings": heads} if heads else {}),
                **({"question": slot.question or slot.name}
                   if "question" in shows else {}),
                **({"answer": got.words} if "answer" in shows else {}),
                **({"place": [line.text for line, _ in got.lines]}
                   if "place" in shows else {})}
            with asking(Asking(about_box(), None, None,
                               what.follow_ups if what is not None
                               else None)):
                reply = self._ask("check", ask_payload, plan.document_id,
                                  about_format(), {"about": "yes"}, counts,
                                  **noted)
            if not isinstance(reply, dict):
                return rules.get("about_no_reply") == "keep"
            return reply.get("about") == "yes"

    def fetch(self, plan: Plan, more, batch: list, seen: set,
              numbers: bool = False) -> list:
        """The pieces a reply asks for itself (`more`), those not shown
        yet, of the pieces its field reads: the piece before or after a
        shown one, a table or figure by its placeholder, the pieces a
        pattern stands in, the pieces best for a sentence of its own."""
        pieces = plan.pieces(numbers)
        places = plan.places_of(numbers)
        out: list = []
        for ask in more if isinstance(more, list) else ():
            if not isinstance(ask, dict) or not batch:
                continue
            get = ask.get("get")
            if get not in fetches():
                continue
            if get in ("next", "previous"):
                anchor = batch[-1] if get == "next" else batch[0]
                at = places.get(anchor.key)
                if at is not None:
                    i = at + (1 if get == "next" else -1)
                    if 0 <= i < len(pieces):
                        out.append(pieces[i])
            elif get == "item":
                found = lookup.item(plan.sources, ask.get("id") or "")
                if found is not None:
                    out += [c for c in pieces
                            if c.owner == (found.owner_kind,
                                           found.owner_id)][:1]
            elif get == "search":
                try:
                    wanted = regex.compile(ask.get("pattern") or "",
                                           regex.I)
                except (regex.error, TypeError, ValueError):
                    continue
                if wanted.pattern:
                    out += self.matching(wanted, pieces, seen)
            elif get == "similar":
                text = ask.get("text") or ""
                if text.strip():
                    out += [c for c in self.search_order(
                        plan.document_id, [text], pieces)
                        if c.key not in seen][:self.per_request]
        return [c for c in dict.fromkeys(out) if c.key not in seen]

    def matching(self, wanted, pieces: list, seen: set) -> list:
        """The pieces a pattern the model wrote stands in, not shown yet,
        as many as a request shows. The pattern runs for the rule
        `pattern_timeout_s` seconds at most over all the pieces; one that
        does not finish stands in none (it is a pattern of the model's,
        which can backtrack without end)."""
        limit = float(rules.get("pattern_timeout_s"))
        deadline = time.monotonic() + limit
        found: list = []
        try:
            for piece in pieces:
                if piece.key in seen:
                    continue
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError
                if wanted.search(piece.text(), timeout=left):
                    found.append(piece)
        except TimeoutError:
            log.warning("a pattern of the model did not finish within %s s: "
                        "%s", limit, wanted.pattern)
            return []
        return found[:self.per_request]

    # -- names -----------------------------------------------------------------------

    def named_value(self, plan: Plan, parameter, row: Row,
                    counts: Counts) -> None:
        """A value that is the name the document gives a thing (a
        scenario): the entry of the document's list it is, a new one where
        it is not on it yet, under `value_means` (owner decisions
        2026-11-08: the list is built piece by piece)."""
        claim = row.claim
        if not isinstance(claim.get("value"), str) or not claim["value"]:
            return
        at = claim.get("at") or {}
        passage = plan.passages.get(tuple(at.get("owner") or ()))
        number = int(at.get("line") or 1)
        lines = [(passage.line(number), passage.source)] \
            if passage is not None and passage.line(number) else []
        got = Found(lines=lines, passage=passage, words=claim["value"])
        picked = self.name_of(plan, parameter.merged, claim["value"], got,
                              counts, work=self.work_of(plan, row),
                              uri=parameter.uri, work_read=work_read(claim))
        if picked is None or (picked and picked[0][0] == "out"):
            return
        # A name the request says names no such thing is no entry: the value
        # stays as read and the graph makes no scenario of it (owner
        # decision 2026-11-09: "Nichts falsches im Graphen aber wir wollen
        # auch viele Werte").
        claim["value_means"] = [label for label, _number in picked[:1]]
        if picked and claim.get("work_state") != READ:
            # The entry decides last: a name of an entry whose own work
            # stayed open takes the work the entry was read with (owner
            # decision 2026-11-09).
            entry = plan.names[parameter.merged].entries[picked[0][1] - 1]
            if entry.work_read:
                claim.update({**entry.work_read, "work_window": ["entry", 1]})

    def works(self, plan: Plan, chunks: list, counts: Counts) -> list:
        """The works the document presents, compares or cites beside itself
        (owner decisions 2026-11-08, h, and 2026-11-09): every piece asked
        once which of its lines speak of another work and which line shows
        the rest are this publication's own (`work_piece`), kept for the
        values found in it (`Plan.works_of`, `inherit_work`); each name of
        a work asked against the document's list of works, piece by piece in
        the plan's order, and each new work asked at its line for what the
        profile asks of a work (its title, its organisation, its year, its
        short name), side by side: values of that work, never of this
        publication, which the graph does not take. [Read] of those
        values."""
        if self.asks.work is None:
            return []
        field_ = self.works_field or {}
        shown_field = {"name": field_.get("name", "work"),
                       "means": field_.get("means", "")}
        chunks = list(chunks)
        asked = self.each(chunks, lambda chunk: self.work_piece(
            plan, shown_field, chunk, counts))
        works = plan.names["work"]
        new: list = []
        for chunk, got in zip(chunks, asked):
            if got is None:
                continue
            shown, payload, held, own = got
            finds = []
            for one in held:
                before = len(works.entries)
                picked = self.name_of(plan, "work", one.words, one, counts)
                if not picked:
                    continue
                number = picked[0][1]
                if number > before:
                    new.append((number, one, shown, payload))
                finds.append((self.covered(chunk, one), number, one))
            plan.works_of[chunk.key] = PieceWork(finds, own,
                                                 shown.evidence())
        jobs = [(number, one, shown, payload, uri, question)
                for number, one, shown, payload in new
                for uri, question in (field_.get("fields") or {}).items()
                if self.spec.by_uri.get(uri) is not None]
        made = self.each(jobs, lambda job: self.work_value(
            plan, self.spec.by_uri[job[4]], job[5], job[1],
            works.entries[job[0] - 1].label, counts, job[2], job[3]))
        reads: dict = {}
        for job, got in zip(jobs, made):
            if got is None:
                continue
            claim, source = got
            parameter = self.spec.by_uri[job[4]]
            key = (parameter.uri, source.owner_kind, source.owner_id,
                   source.text if claim.get("at") is None else None)
            read = reads.get(key)
            if read is None:
                read = reads[key] = Read(Batch(
                    plan.document_id, parameter,
                    [WorkItem(plan.document_id, parameter, source)],
                    spec=self.spec), [])
            read.claims.append(claim)
        self._traced("works", plan.document_id,
                     works=len(works.entries), new=len(new))
        return list(reads.values())

    def work_piece(self, plan: Plan, shown_field: dict, chunk: Chunk,
                   counts: Counts) -> Optional[tuple]:
        """(shown, payload, [Found] of other works, the line of this
        publication's own or None) of one piece's work request (`work`):
        the piece with the headings up to it and the title page; what does
        not hold is asked again with its reason (as often as the flow
        says). None where no answer came."""
        shown = Shown()
        heads = plan.headings(chunk.owner) \
            if rules.get("show_headings") else []
        title = plan.title_page if title_page_shown(plan) else []
        shown.add(letter_headings(), "headings", heads, renumber=True)
        shown.add(letter_title_page(), "title_page", title, renumber=True)
        shown.add("", "passage", own_lines(chunk))
        payload = {"field": shown_field,
                   **({"headings": shown.rendered(letter_headings())}
                      if heads else {}),
                   **({"title_page": shown.rendered(letter_title_page())}
                      if title else {}),
                   "passage": block_payload(chunk.passage, shown)}
        other, _ = find_example(shown)
        own_at = f"{letter_headings()}{len(heads)}" if heads \
            else first_address(shown, False)
        example = ({**other, "own": {address_key(): 0, "words": ""}},
                   {"found": [], "own": {**point(shown, False, at=own_at),
                                         "words": fields.said()}})
        noted = {"parameter": "work", "kind": chunk.passage.kind,
                 "owner": chunk.passage.source.owner_id, "chunk": chunk.index}
        reply = self._ask("work", payload, plan.document_id, work_format(),
                          example, counts, **noted)
        if not isinstance(reply, dict):
            return None
        held, refused = self._finds(plan, shown, reply)
        own, why = self.own_line(plan, shown, chunk, reply.get("own"))
        if why is not None:
            refused.append((reply.get("own"), why))
        for _, reason in refused:
            counts.fail(reason)
        for _ in range(self.follow_ups()):
            if not refused:
                break
            reply = self._follow("work", payload, plan.document_id,
                                 work_format(), example, reply,
                                 refusals(refused), counts, **noted)
            if not isinstance(reply, dict):
                break
            more, refused = self._finds(plan, shown, reply)
            held = joined(held, more)
            if own is None:
                own, why = self.own_line(plan, shown, chunk,
                                         reply.get("own"))
                if why is not None:
                    refused.append((reply.get("own"), why))
        return shown, payload, held, own

    @staticmethod
    def own_line(plan: Plan, shown: Shown, chunk: Chunk, raw) -> tuple:
        """(Found or None, why or None) of the line a piece's work request
        names as showing the rest of the piece is this publication's own:
        it counts where it stands among the piece's lines or headings, or
        on the title page in the piece itself; 0 names none."""
        if not has_address(raw):
            return None, None
        got = resolve(shown, raw, plan.passages)
        if got.why is not None:
            return None, got.why
        source = got.source
        if got.letter in ("", letter_headings()) or (
                got.letter == letter_title_page() and source is not None
                and (source.owner_kind, source.owner_id) == chunk.owner):
            return got, None
        return None, None

    @staticmethod
    def covered(chunk: Chunk, found: Found) -> Optional[set]:
        """The (passage, line) places a find of a piece's work request
        speaks for: the whole piece (None) where it stands in a heading or
        in what every piece of its passage shows (a table's title and head,
        a figure's caption), else its own lines."""
        if rules.get("work_find_covers_piece"):
            if found.letter == letter_headings():
                return None
            if found.letter == "" and found.lines and all(
                    line.number in chunk.passage.fixed
                    for line, _ in found.lines):
                return None
        return {((source.owner_kind, source.owner_id), line.number)
                for line, source in found.lines}

    def work_value(self, plan: Plan, parameter, question: str, one: Found,
                   label: str, counts: Counts, shown: Shown,
                   payload: dict) -> Optional[tuple]:
        """One detail of a work, asked with the piece that names it (`coord`):
        (the claim of a value of *parameter* whose work is that work, with
        the line as its quote, the passage it is checked against); None
        where no line gives it. A heading is quoted as it is shown, and
        checked against itself."""
        ask_payload = {**payload, "work": label,
                       "field": field_shown(parameter), "question": question}
        example = {**point(shown, False), "words": fields.said()}
        reply = self._ask("coord", ask_payload, plan.document_id,
                          coord_format(False), example, counts,
                          parameter=parameter.uri, coordinate="work")
        finds = self.coord_finds(reply)
        if not finds:
            return None
        got = resolve(shown, finds[0], plan.passages)
        if got.why is not None or got.passage is None:
            return None
        if got.letter == letter_headings():
            claim = {"source": "Q1", "value": got.words, "quote": got.quote}
            source = got.source
        else:
            claim = self.claim(plan, parameter, got, counts)
            source = got.passage.source
        work = next((s for s in fields.axis_slots(parameter)
                     if s.name == "work"), None)
        if claim is None or work is None:
            return (claim, source) if claim is not None else None
        option = next((o.label for o in work.options
                       if o.uri == ANOTHER_WORK), ANOTHER_WORK)
        named = one.words if flat(one.words).casefold() \
            in flat(one.quote).casefold() else label
        claim.update({"work": option, "work_state": READ,
                      "work_raw": named, "work_quote": one.quote,
                      "work_source": [one.source.owner_kind,
                                      one.source.owner_id],
                      "work_window": ["piece", 1], "work_means": [label]})
        return claim, source

    def work_coordinate(self, plan: Plan, read: Read, row: Row, slot,
                        counts: Counts) -> None:
        """The work of one value (owner decisions 2026-11-09): the work of
        the line it stands in where its piece's work request named one
        (`inherit_work`), else asked as an entry of the document's list of
        works with the value's line, the headings and the title page, the
        answer the entry and the line that shows it; 0 leaves it
        `unstated`, and it is never searched. What does not hold is asked
        again with its reason (as often as the flow says), then stays
        `unbacked`."""
        if self.inherit_work(plan, row, slot):
            return
        parameter = read.batch.parameter
        works = plan.names["work"]
        shown, payload = show_value(plan, row.claim)
        if not shown.blocks:
            return
        listed = [f"{number} {text}" for number, text in works.shown()]
        payload = {**payload, "field": field_shown(parameter),
                   "question": slot.question or slot.name, "list": listed}
        example = {"entry": 1, **point(shown, False),
                   "words": fields.said()}
        noted = {"parameter": parameter.uri, "coordinate": slot.name,
                 "owner": ((row.claim.get("at") or {}).get("owner")
                           or [None, None])[1], "value": row.label}
        reply = self._ask("coord", payload, plan.document_id,
                          work_choice_format(), example, counts, **noted)
        if not isinstance(reply, dict):
            return
        failed = self.read_work(plan, row, slot, shown, reply)
        if failed:
            for _ in range(self.follow_ups()):
                reply = self._follow("coord", payload, plan.document_id,
                                     work_choice_format(), example, reply,
                                     failed, counts, **noted)
                if not isinstance(reply, dict):
                    break
                failed = self.read_work(plan, row, slot, shown, reply)
                if not failed:
                    break
            if failed:
                row.claim[f"{slot.name}_state"] = UNBACKED

    def read_work(self, plan: Plan, row: Row, slot, shown: Shown,
                  reply: dict) -> list:
        """[what did not hold] of an answer to a value's work, [] where it
        read the work or said none (0, `unstated`)."""
        works = plan.names["work"]
        pick = picked_entry(reply.get("entry"), len(works.entries))
        if pick is None:
            return [say(NOT_AN_OPTION, given=reply.get("entry"))]
        if pick == 0 or not has_address(reply):
            row.claim[f"{slot.name}_state"] = SAID_UNSTATED
            return []
        got = resolve(shown, reply, plan.passages)
        if got.why is not None:
            return [{"at": reply.get("at"), "words": reply.get("words"),
                     "why": told(got.why, reply)}]
        return self.take_work(row, slot, pick, got, shown.evidence(),
                              ("own", 1), works)

    @staticmethod
    def take_work(row: Row, slot, number: int, got: Found, evidence: list,
                  window: tuple, works: "Names") -> list:
        """The work *number* of the document's list read onto a value with
        the line *got* names as its quote (`merge_field`): [] where it holds,
        [what did not hold] else."""
        first = number == 1 and rules.get("this_publication_first")
        uri = THIS_PUBLICATION if first else ANOTHER_WORK
        option = next((o.label for o in slot.options if o.uri == uri), uri)
        row.claim.pop(f"{slot.name}_state", None)
        result = merge_field([row], evidence, slot, {"answers": {row.label: {
            "value": option, "value_raw": got.words, "quote": got.quote}}},
            window=window)
        if row.claim.get(f"{slot.name}_state") == READ:
            row.claim[f"{slot.name}_means"] = [works.entries[number - 1].label]
            return []
        row.claim.pop(f"{slot.name}_state", None)
        return [{"words": failure.get("raw") or failure.get("given"),
                 "why": failure.get("reason")}
                for failure in result["failed"]] or [{"why": UNBACKED}]

    def inherit_work(self, plan: Plan, row: Row, slot) -> bool:
        """Does the value take the work of the line it stands in (owner
        decisions 2026-11-09: nothing without a line)? The work its piece's
        work request named for that line, read with that find as its
        quote: a find of the line itself before one of the whole piece,
        the line of this publication's own after both; a line two works
        are named for, or none, is the value's own to ask."""
        got = self.piece_work(plan, row.claim)
        if got is None:
            return bool(rules.get("work_without_line")
                        and self.work_by_piece(plan, row, slot))
        number, found, evidence = got
        works = plan.names["work"]
        if not 0 < number <= len(works.entries):
            return False
        return not self.take_work(row, slot, number, found, evidence,
                                  ("piece", 1), works)

    def work_by_piece(self, plan: Plan, row: Row, slot) -> bool:
        """Does the value take the work its piece names, or this
        publication where it names none, with no line that names it (rule
        `work_without_line`)? The value's own line is its quote. A piece
        that names two works leaves the value to ask."""
        claim = row.claim
        at = claim.get("at") or {}
        owner = tuple(at.get("owner") or ())
        line = int(at.get("line") or 0)
        works = plan.names["work"]
        if len(owner) != 2 or line <= 0:
            return False
        chunk = plan.chunk_of(owner, line, False)
        info = plan.works_of.get(chunk.key) if chunk is not None else None
        named = {number for _, number, _ in info.finds} if info else set()
        if len(named) == 1:
            number = next(iter(named))
        elif not named and rules.get("this_publication_first"):
            number = 1
        else:
            return False
        if not 0 < number <= len(works.entries):
            return False
        shown, _payload = show_value(plan, claim)
        words = str(claim.get("value_raw") or claim.get("value") or "")
        place = f"{line}.{at['cell']}" if at.get("cell") else str(line)
        got = resolve(shown, {"at": place, "words": words}, plan.passages)
        if got.why is not None:
            return False
        if self.take_work(row, slot, number, got, shown.evidence(),
                          ("piece", 1), works):
            return False
        self._traced("second_way", plan.document_id,
                     rule="work_without_line", work=number)
        return True

    @staticmethod
    def piece_work(plan: Plan, claim: dict) -> Optional[tuple]:
        """(number of the work, the find, what its request showed) a
        value's piece names for the line it stands in, None where it names
        none or two."""
        at = claim.get("at") or {}
        owner = tuple(at.get("owner") or ())
        line = int(at.get("line") or 0)
        if len(owner) != 2 or line <= 0:
            return None
        chunk = plan.chunk_of(owner, line, False)
        info = plan.works_of.get(chunk.key) if chunk is not None else None
        if info is None:
            return None
        place = (owner, line)
        own_lines_ = [(number, found) for cover, number, found in info.finds
                      if cover is not None and place in cover]
        whole = [(number, found) for cover, number, found in info.finds
                 if cover is None]
        for named in (own_lines_, whole):
            numbers = {number for number, _ in named}
            if len(numbers) == 1:
                return named[0][0], named[0][1], info.evidence
            if numbers:
                return None
        if info.own is not None:
            return 1, info.own, info.evidence
        return None


def about_box() -> Optional[str]:
    """The id of the box that asks of a find from another passage whether
    it speaks about the value, None where the question asking now has
    none after it."""
    what = ASKING.get()
    return what.about if what is not None else None


def own_check(got: Found) -> Optional[tuple]:
    """(reason, sentence) of the own check of the box asking now that
    refuses *got*, None where none does (owner decision 2026-11-10: an own
    check only refuses; its reason is check:<name>)."""
    what = ASKING.get()
    if what is None or what.refused is None:
        return None
    return what.refused(got)


def years_listed(listed: list) -> list:
    """The plan's years as a request lists them, each with the state it is
    the year of and, where the rule `year_list_quote` says so, the line that
    says it."""
    quote = rules.get("year_list_quote")
    return [f"{i} {b['year']} ({b['state']}: {b['quote']})" if quote
            else f"{i} {b['year']} ({b['state']})"
            for i, b in enumerate(listed, start=1)]


def settings_of(plan: Plan) -> dict:
    """{"settings": lines} of what the plan settles for all its values,
    shown beside a list's entries, {} where it settles nothing: they hold
    for every value, also where the entry of a wording depends on them
    (emissions given in CO2 equivalents)."""
    if not plan.settings or not rules.get("show_settled"):
        return {}
    return {"settings": [line.text for line, _ in plan.settings]}


def field_shown_of(field_: dict) -> dict:
    """A field the profile asks of a plan as a request shows it."""
    return {"name": field_.get("name", ""), "means": field_.get("means", "")}


# -- the order of the pieces ---------------------------------------------------

@dataclass
class ChunkDoc:
    """A piece as the reranker reads it."""
    owner_kind: str
    owner_id: tuple
    text: str
    image_path: Optional[str] = None


def make_order(reranker: Optional[Callable], rank: Optional[Callable]
               ) -> tuple:
    """(order, search_order, rerank), each (document_id, sentences, chunks)
    -> the pieces best first. *order* has the reranker score every piece
    with every sentence, keeping each piece's best (owner decisions
    2026-11-08: all pieces, best first); *search_order* takes the passages
    the vector search finds best (*rank*, with its reranker over passages,
    100 of each kind) and gives their pieces in that order, the rest of the
    plan after them; *rerank* orders the pieces a search shows with the
    same sentences (owner decisions 2026-11-09: "der Reranker ordnet diese
    höchstens 50 Stücke einmal mit demselben Satz"). Without a reranker the
    pieces keep their passages' order; without either, the plan's. A
    reranker or a search that fails raises: what is handed in asks again
    until it answers (`runner.persistently`, owner decision 2026-11-09:
    nothing is read in another order instead), and one the server refuses
    as often as the flow's `replies` says fails its document, which stays
    unfinished."""
    local = threading.local()

    def rerank(document_id: int, sentences: list, chunks: list) -> list:
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        if reranker is None or not sentences \
                or len(chunks) < rules.get("rerank_least_pieces"):
            return list(chunks)
        if getattr(local, "reranker", None) is None:
            local.reranker = reranker()
        if local.reranker is None:
            return list(chunks)
        docs = [ChunkDoc(c.passage.kind, c.key, c.text()) for c in chunks]
        by = {doc.owner_id: c for doc, c in zip(docs, chunks)}
        return [by[doc.owner_id] for doc in local.reranker.order(
            document_id, sentences, docs)]

    def search_order(document_id: int, sentences: list,
                     chunks: list) -> list:
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        if rank is None or not sentences or not chunks:
            return list(chunks)
        by_owner: dict = collections.defaultdict(list)
        for chunk in chunks:
            by_owner[chunk.owner].append(chunk)
        out: list = []
        taken: set = set()
        for source in rank(document_id, sentences, set()):
            for chunk in by_owner.get((source.owner_kind,
                                       source.owner_id), ()):
                if chunk.key not in taken:
                    taken.add(chunk.key)
                    out.append(chunk)
        return out + [c for c in chunks if c.key not in taken]

    def order(document_id: int, sentences: list, chunks: list) -> list:
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        if not sentences or not chunks:
            return list(chunks)
        if reranker is not None:
            return rerank(document_id, sentences, chunks)
        return search_order(document_id, sentences, chunks)
    return order, search_order, rerank

def order_key(parameters: list, chunk_units: int, written: str = "") -> str:
    """The key an order of the pieces is kept under: the fields it ranked,
    each with the words its search sentences are written from, what writes
    them (*written*) and the size of the pieces."""
    raw = json.dumps([[p.uri, p.label, p.description] for p in parameters]
                     + [chunk_units, written], ensure_ascii=False,
                     sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class Orders:
    """(plan, parameters, chunk_units, scope, chunks) -> {field uri:
    [piece key]}: the pieces each field reads (`Plan.pieces`) best first
    for its sentences, kept under the harvest
    (`survey/<document>[.<scope>].json`) with the passages each field was
    read in, which the passes over a stored harvest read
    (`surveyed.surveyed_owners`)."""

    def __init__(self, order: Callable, probes: Callable,
                 store: Optional[Path], trace=None, written: str = ""):
        self.order = order
        self.probes = probes
        self.store = Path(store) if store else None
        self.trace = trace
        self.written = written

    def __call__(self, plan: Plan, parameters: list, chunk_units: int,
                 scope: str = "", chunks: Optional[list] = None) -> dict:
        chunks = list(plan.chunks if chunks is None else chunks)
        read_by = {numbers: set(plan.pieces(numbers))
                   for numbers in (True, False)}
        pieces = {p.uri: [c for c in chunks if c in read_by[p.is_numeric]]
                  for p in parameters}
        key = order_key(parameters, chunk_units, self.written)
        path = None
        if self.store is not None:
            name = f"{plan.document_id}.{scope}" if scope \
                else str(plan.document_id)
            path = self.store / f"{name}.json"
            kept = None
            if path.is_file():
                try:
                    kept = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    kept = None
            if kept and kept.get("key") == key \
                    and rules.get("reuse_stored_order"):
                order = kept.get("order") or {}
                if set(order) == set(pieces) and all(
                        {tuple(k) for k in keys}
                        == {tuple(c.key) for c in pieces[uri]}
                        for uri, keys in order.items()):
                    return {uri: [tuple(k) for k in keys]
                            for uri, keys in order.items()}
        out: dict = {}
        for parameter in parameters:
            sentences = list(self.probes(parameter, plan.document_id) or ()) \
                or [parameter.label]
            out[parameter.uri] = [c.key for c in self.order(
                plan.document_id, sentences, pieces[parameter.uri])]
        if self.trace is not None:
            self.trace("order", plan.document_id, scope=scope or None,
                       passages=len({c.owner for c in chunks}),
                       parameters=len(parameters),
                       first={uri: [list(k) for k in keys[:5]]
                              for uri, keys in out.items()})
        if path is not None:
            owners = list(dict.fromkeys(c.owner for c in chunks))
            path.parent.mkdir(parents=True, exist_ok=True)
            archive.keep(path)
            path.write_text(json.dumps(
                {"key": key, "complete": True,
                 "answers": [{"owner": list(o),
                              "parameters": [p.uri for p in parameters]}
                             for o in owners],
                 "order": {uri: [list(k) for k in keys]
                           for uri, keys in out.items()}},
                ensure_ascii=False, default=str), encoding="utf-8")
        return out
