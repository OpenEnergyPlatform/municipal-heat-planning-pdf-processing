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
import copy
import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import archive, fields, lookup
from . import flow as flow_map
from .fields import (EXHAUSTED, NUMBER, OUT_OF_SLICE, READ, SAID_UNSTATED,
                     UNBACKED)
from .pipeline import (Batch, Row, Source, WorkItem, mark_unanswered,
                       merge_field, row_label)
from .reading import (CUT, NO_ANSWER, Read, groups_of, in_group_order,
                      link_ranges, slots_of, span_rows)
from .units import (HEADINGS, OTHERS, SETTINGS, TITLE_PAGE, Chunk, Line,
                    Passage, Shown, address_of, chunks_of, own_lines,
                    passage_lines, passage_of, pieces_for, short_quote,
                    title_page_of)
from .verify import MIN_QUOTE_CHARS, canonical_number, flat, numbers_in
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
# The entries of a list of works and of scenarios beside the names.
THIS_PUBLICATION = "work:this_publication"
ANOTHER_WORK = "out:another_work"
SEVERAL = "out:several"
YEAR = re.compile(r"(?<![\d.,])(1[89]\d\d|20\d\d|21\d\d)(?![\d]|[.,]\d)")
SPAN = re.compile(r"\b(bis|to|until|through)\b|[-–]", re.I)
# A search sentence that is a question, which a search takes and the run
# counts (owner decision 2026-11-08: "So pingelig wäre ich da nicht").
QUESTION = re.compile(r"\?\s*$|^\s*(wer|was|wann|wo|wie|welche[rsmn]?|warum|"
                      r"wieso|who|what|when|where|which|how|why)\b", re.I)


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
        text = say(why, given=entry.get("entry")) if why == "not_an_option" \
            else told(why, entry)
        out.append({**entry, "why": text})
    return out


def joined(held: list, more: list) -> list:
    """*held* and those finds of *more* that are not among them: a line,
    its cell and its words once."""
    def key(got) -> tuple:
        return (id(got.lines[0][0]), got.cell, flat(got.words).casefold())
    taken = {key(got) for got in held}
    return held + [got for got in more if key(got) not in taken]


def work_read(claim: dict) -> Optional[dict]:
    """How a value read its work, its `work` fields, None where it read
    none."""
    if claim.get("work_state") != READ:
        return None
    return {key: copy.deepcopy(value) for key, value in claim.items()
            if key == "work" or key.startswith("work_")}


def number_of(words: str) -> Optional[str]:
    """The number the words of a find print, with its sign (owner decision
    2026-11-01), in `canonical_number`'s spelling: the words themselves
    where they are a number, else the one number they print ("750.940
    kWh", "ca. 8,8 GWh"); None where they print none or more than one
    ("800 / 750", "2019 bis 2021"). A signed number and its magnitude are
    one number ("-1.155")."""
    whole = canonical_number(words)
    if whole is not None:
        return whole
    found = numbers_in(words or "")
    found = {n for n in found if "-" + n not in found}
    return next(iter(found)) if len(found) == 1 else None


def is_question(sentence: str) -> bool:
    """Is a search sentence a question rather than a sentence of the
    plan?"""
    return bool(QUESTION.search(sentence or ""))


# -- grammars ----------------------------------------------------------------

def _format(name: str, schema: dict) -> dict:
    return {"type": "json_schema",
            "json_schema": {"name": name, "schema": schema}}


_FOUND = {"type": "object",
          "properties": {"at": {"type": "string"},
                         "words": {"type": "string"}},
          "required": ["at", "words"], "additionalProperties": False}

# What a search may fetch itself (owner decision 2026-11-07, kept by the
# plan of 2026-11-09): the piece before or after a shown one, a table or
# figure by its placeholder, the pieces a pattern stands in, the pieces
# best for a sentence of its own.
GETS = ("next", "previous", "item", "search", "similar")


def more_schema() -> dict:
    return {"type": "array", "items": {
        "type": "object",
        "properties": {"get": {"enum": list(GETS)},
                       "at": {"type": "string"},
                       "id": {"type": "string"},
                       "pattern": {"type": "string"},
                       "text": {"type": "string"}},
        "required": ["get"], "additionalProperties": False}}


# A find of a field with a list: the number of its entry beside its address
# and words (owner decision 2026-11-09).
_ENTRY_FOUND = {"type": "object",
                "properties": {"entry": {"type": "integer"},
                               "at": {"type": "string"},
                               "words": {"type": "string"}},
                "required": ["entry", "at", "words"],
                "additionalProperties": False}


def found_format(closed: bool = False) -> dict:
    """The finds of a request: each an address and the words of the value,
    and where the field has a list the number of its entry (*closed*); an
    empty list where nothing shown holds one."""
    return _format("found_reply", {
        "type": "object",
        "properties": {"found": {"type": "array", "items":
                                 _ENTRY_FOUND if closed else _FOUND}},
        "required": ["found"], "additionalProperties": False})


def work_format() -> dict:
    """The answer of a piece's work request: the lines of other works, each
    an address and the name as a line prints it, and the line that shows
    the rest are this publication's own (`own`), 0 where none does."""
    return _format("work_reply", {
        "type": "object",
        "properties": {"found": {"type": "array", "items": _FOUND},
                       "own": {"type": "object",
                               "properties": {
                                   "at": {"type": ["string", "integer"]},
                                   "words": {"type": "string"}},
                               "required": ["at"],
                               "additionalProperties": False}},
        "required": ["found", "own"], "additionalProperties": False})


def work_choice_format() -> dict:
    """The work of one value, asked as an entry of the document's list of
    works: its number, 0 for none, and the line that shows it."""
    return _format("work_choice_reply", {
        "type": "object",
        "properties": {"entry": {"type": "integer"},
                       "at": {"type": ["string", "integer"]},
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
        properties = {"found": {"type": "array", "items": _FOUND}}
        required = ["found"]
    else:
        properties = {"at": {"type": ["string", "integer"]},
                      "words": {"type": "string"}}
        required = ["at"]
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
        "properties": {"at": {"type": ["string", "integer"]},
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

def field_shown(parameter, full: bool = False) -> dict:
    """A field as a request shows it: its name and what a value of it is,
    in short where the spec writes that (`brief`)."""
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
        if passage.page is not None:
            out["page"] = passage.page
        if passage.kind != "section" and passage.title:
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
    cell = ".2" if cells and line.cells and len(line.cells) > 1 else ""
    return f"{block.letter}{number}{cell}"


def find_example(shown: Shown, closed: bool = False,
                 letter: str = "") -> tuple:
    """The two replies a request that finds values shows (owner decision
    2026-11-09: "immer ein Positiv und ein Negativbeispiel"): one find at
    the request's own first line, and where the field has a list with the
    number of its entry; and the empty one, where no shown line prints a
    value."""
    one = {"at": first_address(shown, True, letter), "words": fields.SAID}
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

    @property
    def quote(self) -> str:
        return " ".join(line.text for line, _ in self.quoted or self.lines)

    @property
    def source(self) -> Optional[Source]:
        return self.lines[0][1] if self.lines else None


# A find's entry that is no number of its request's list (`not_an_option`,
# owner decision 2026-09-11).
NOT_AN_OPTION = "not_an_option"


def listing(options, meanings: int) -> tuple:
    """(lines, choices, grouped) of a list as a request shows it (owner
    decisions 2026-11-08): a list longer than *meanings* entries
    (`flow.Numbers.list_meanings`) whose entries name groups is shown by
    its groups, each a choice; a shorter one with what each entry means, a
    longer one by its names. *choices* are what a number picks, labels or
    group names."""
    options = list(options)
    groups: list = []
    for option in options:
        group = getattr(option, "group", "") or ""
        if group and group not in groups:
            groups.append(group)
    if len(options) > meanings and len(groups) > 1:
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


def budgeted(ranked: list, budget: int, shares: dict) -> list:
    """The pieces a search shows of *ranked*, best first (owner decisions
    2026-11-09: 50 pieces, 20 of tables, 15 of figures, 15 of text, filled
    up): the best of each kind of passage up to its share, the shares
    scaled to *budget*, then the best of the rest up to *budget*; in the
    order of *ranked*."""
    budget = max(0, int(budget))
    total = sum(max(0, int(n)) for n in shares.values()) or 1
    room = {kind: max(0, int(n)) * budget // total
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


def resolve(shown: Shown, entry, passages: dict) -> Found:
    """The lines an answer's address names in what *shown* showed, its
    words checked against them: `NOT_AN_ADDRESS` where it names no shown
    line or cell, `WORDS_NOT_IN_LINE` where its words do not stand in what
    it names. Words left empty are the cell's, or the lines' of a stretch;
    a single line without a cell needs words."""
    at = entry.get("at") if isinstance(entry, dict) else None
    words = entry.get("words") if isinstance(entry, dict) else None
    words = words.strip() if isinstance(words, str) else ""
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
                  quoted=shown.around(address, MIN_QUOTE_CHARS))
    if not words:
        if cell is not None:
            found.words = line.cells[cell - 1]
        elif address.last is not None:
            found.words = text
        else:
            found.why = WORDS_NOT_IN_LINE
            return found
    if not found.words or \
            flat(found.words).casefold() not in flat(text).casefold():
        found.why = WORDS_NOT_IN_LINE
        return found
    if line.cells:
        # The cell the words stand in, where the address names another one
        # and only one cell holds them.
        holding = [i for i, one in enumerate(line.cells, start=1)
                   if flat(found.words).casefold() in flat(one).casefold()]
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
    a dict or None; *fingerprint* says which prompt and model wrote it,
    *image_key(source)* which image (None where the figure has none: then
    nothing is asked and its description stands for it)."""

    def __init__(self, ask: Optional[Callable], store: Optional[Path],
                 fingerprint: str, image_key: Callable):
        self.ask = ask
        self.store = Path(store) if store else None
        self.fingerprint = fingerprint
        self.image_key = image_key
        self._lock = threading.Lock()

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
        with self.lock:
            for i, entry in enumerate(self.entries, start=1):
                if entry.name == name and entry.work == work:
                    return i
            label = name
            if any(e.label == label for e in self.entries):
                label = f"{name} ({work})"
            self.entries.append(Entry(label, name, work, quote, work_read))
            return len(self.entries)

    def shown(self, works: Optional["Names"] = None) -> list:
        """[(number, text)] of the list as a request shows it, each under
        its work where the entries have works, ordered by work."""
        with self.lock:
            entries = list(enumerate(self.entries, start=1))
        if works is not None:
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
                 chunk_units: Optional[int] = None, *, numbers=None):
        # How many lines a piece and the title page hold and how many
        # headings are shown up to a place are the flow's (`flow.Numbers`);
        # *chunk_units* says another size of the pieces.
        self.numbers = numbers or flow_map.default()
        if chunk_units is None:
            chunk_units = self.numbers.piece_lines
        self.document_id = document_id
        self.sources = list(sources)
        self.by_owner = {(s.owner_kind, s.owner_id): s for s in sources}
        self.passages: dict = {}
        self.chunks: list = []
        for source in sources:
            passage = passage_of(source, transcripts.get(source.owner_id)
                                 if source.owner_kind == "figure" else None)
            if not passage.lines:
                continue
            self.passages[passage.owner] = passage
            self.chunks.extend(chunks_of(passage, chunk_units))
        self.by_key = {chunk.key: chunk for chunk in self.chunks}
        self.position = {chunk.key: i for i, chunk in enumerate(self.chunks)}
        # The pieces a field of numbers reads, and those any other field
        # reads (`units.pieces_for`), each with the place of its pieces.
        self.views = {numbers: pieces_for(self.chunks, numbers)
                      for numbers in (True, False)}
        self.places = {numbers: {chunk.key: i for i, chunk in
                                 enumerate(view)}
                       for numbers, view in self.views.items()}
        self.title_page = title_page_of(list(self.passages.values()),
                                        self.numbers.title_page_lines)
        self.settings: list = []          # [(Line, Source)]
        self.bases: list = []             # `pipeline.named_years` entries
        self.lists: dict = {}
        self.names: dict = {}             # kind -> Names
        self.works_of: dict = {}          # piece key -> PieceWork
        self.lock = threading.Lock()
        self._locks: dict = {}
        self._headings: dict = {}

    def pieces(self, numbers: bool) -> list:
        """The pieces a field reads, of numbers or not (`pieces_for`)."""
        return self.views[bool(numbers)]

    def key_lock(self, key) -> threading.Lock:
        with self.lock:
            return self._locks.setdefault(key, threading.Lock())

    def headings(self, owner: tuple) -> list:
        """[(Line, Source)] of the titles of the sections up to a passage,
        its own last (`lookup.sections_up_to`)."""
        with self.lock:
            if owner in self._headings:
                return self._headings[owner]
        got: list = []
        for section in lookup.sections_up_to(self.sources, tuple(owner),
                                             self.numbers.headings):
            title = lookup.title_of(section)
            if title:
                got.append((Line(len(got) + 1, title, (), "heading"),
                            Source(section.owner_kind, section.owner_id,
                                   title, section.provenance)))
        with self.lock:
            self._headings[owner] = got
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
        numbers or another field reads."""
        view = self.pieces(numbers)
        at = self.places[bool(numbers)].get(chunk.key)
        if at is None:
            return []
        return [view[i] for i in (at - 1, at + 1) if 0 <= i < len(view)]


def show_value(plan: Plan, claim: dict, headings: bool = True) -> tuple:
    """(Shown, payload) of what every request about a value's coordinates
    shows: its line with its table's title and head, or the sentences
    before and after it; the headings up to it, the title page and the
    plan's settings; the value as its words and its address."""
    at = claim.get("at") or {}
    owner = tuple(at.get("owner") or ())
    passage = plan.passages.get(owner)
    shown = Shown()
    if passage is None:
        return shown, {}
    first = int(at.get("line") or 1)
    last = int(at.get("last") or first)
    numbers = (list(range(first, last + 1)) if passage.kind == "table"
               else list(range(max(1, first - 1), last + 2)))
    shown.add("", "passage", passage_lines(passage, numbers))
    heads = plan.headings(owner) if headings else []
    shown.add(HEADINGS, "headings", heads, renumber=True)
    shown.add(TITLE_PAGE, "title_page", plan.title_page, renumber=True)
    shown.add(SETTINGS, "settings", plan.settings, renumber=True)
    value_at = f"{first}" + (f".{at['cell']}" if at.get("cell") else "") \
        + (f"-{last}" if last != first else "")
    words = claim.get("value_raw") or claim.get("value")
    payload = {"value": {"words": words, "at": value_at},
               "passage": block_payload(passage, shown),
               **({"headings": shown.rendered(HEADINGS)} if heads else {}),
               **({"title_page": shown.rendered(TITLE_PAGE)}
                  if plan.title_page else {}),
               **({"settings": shown.rendered(SETTINGS)}
                  if plan.settings else {})}
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
                 context: Optional[Callable] = None, numbers=None):
        self.spec = spec
        self.asks = asks
        self.order = order
        self.search_order = search_order or order
        self.rerank = rerank or (lambda document_id, sentences, chunks:
                                 list(chunks))
        self.probes = probes or (lambda parameter, document_id: [])
        self.known = known or (lambda claim, asked: {})
        self.span_marks = dict(span_marks or {})
        self.plan_fields = dict(plan_fields or {})
        self.works_field = works
        self.frame_slots = list(frame_slots or ())
        self.each = each or (lambda jobs, run: [run(job) for job in jobs])
        self.trace = trace
        self.numbers = numbers or flow_map.default()
        self.budget = max(1, int(self.numbers.search_pieces
                                 if budget is None else budget))
        self.shares = dict(self.numbers.shares() if shares is None
                           else shares)
        self.per_request = max(1, int(self.numbers.search_per_request
                                      if per_request is None
                                      else per_request))
        self.context = context or (lambda document_id: {})

    def _traced(self, event: str, document_id: int, /,
                **values) -> None:
        if self.trace is not None:
            self.trace(event, document_id, **values)

    def _ask(self, kind: str, payload: dict, document_id: int, shape: dict,
             example: dict, counts: Counts, /, **noted):
        counts.ask(kind)
        return getattr(self.asks, kind)(payload, document_id, shape=shape,
                                        example=example, **noted)

    def _follow(self, kind: str, payload: dict, document_id: int,
                shape: dict, example: dict, answer, what: list,
                counts: Counts, /, **noted):
        """The request asked again, as a request of its own: what it
        showed, the answer that did not hold and why (owner decision
        2026-11-08: "Rückfragen sind eigene Anfragen"). Its callers ask it
        as often as the flow says (`flow.Numbers.follow_ups`), each time
        with the answer before it."""
        counts.ask("follow")
        return self.asks.follow(kind, {**payload, "answer": answer,
                                       "what": what}, document_id,
                                shape=shape, example=example, **noted)

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
            plan.names.setdefault("work", Names("work", Entry(
                "this publication", "this publication" + (
                    f": {title}" if title else ""), 0, title)))

    # -- the document ------------------------------------------------------------

    def __call__(self, plan: Plan, parameters: list, chunks=None,
                 counts: Optional[Counts] = None,
                 order_of: Optional[dict] = None) -> list:
        """[Read] of *parameters* in *plan*: one per field and passage it
        was read in. *chunks* are the pieces read: all where None, else a
        list, or {uri: list or None} per field; *order_of* {uri: [piece
        key]} the order each field reads them in."""
        counts = counts or Counts()
        self.lists_of(plan)

        def pieces_of(uri: str) -> list:
            got = chunks.get(uri) if isinstance(chunks, dict) else chunks
            return list(plan.chunks) if got is None else list(got)
        reads: list = []
        if self.works_field is not None and "work" in plan.names \
                and (chunks is None or isinstance(chunks, dict)
                     and any(v is None for v in chunks.values())):
            reads.extend(self.works(plan, plan.pieces(False), counts))
        once = [p for p in parameters
                if getattr(p, "once_per_document", False)]
        for parameter in once:
            reads.extend(self.docfield(plan, parameter, counts))
        located = [p for p in parameters if p not in once]
        jobs = []
        for parameter in located:
            view = set(plan.pieces(parameter.is_numeric))
            chosen = [c for c in pieces_of(parameter.uri) if c in view]
            held = set(chosen)
            ranked = (order_of or {}).get(parameter.uri) or []
            pieces = [plan.by_key[tuple(key)] for key in ranked
                      if tuple(key) in plan.by_key
                      and plan.by_key[tuple(key)] in held]
            taken = set(pieces)
            pieces += [c for c in chosen if c not in taken]
            jobs.extend((parameter, chunk) for chunk in pieces)
        finds = self.each(jobs, lambda job: self.find(plan, *job, counts))
        by_read: dict = {}
        for (parameter, chunk), got in zip(jobs, finds):
            key = (parameter.uri, chunk.owner)
            read = by_read.get(key)
            if read is None:
                read = by_read[key] = Read(Batch(
                    plan.document_id, parameter,
                    [WorkItem(plan.document_id, parameter,
                              chunk.passage.source)], spec=self.spec), [])
            read.asked += got["asked"]
            read.claims.extend(got["claims"])
            read.lost.extend(got["lost"])
            for why, n in got["failed"].items():
                read.failed[why] = read.failed.get(why, 0) + n
        # The values whose names build a list of the document first (a
        # scenario's own name), then every other value.
        located_reads = list(by_read.values())
        for first in (True, False):
            group = [r for r in located_reads
                     if bool(getattr(r.batch.parameter, "merged", None))
                     == first]
            self.coordinates_of(plan, group, counts)
        for read in located_reads:
            if not read.claims and read.lost:
                read.unread = True
                read.why = read.lost[0]
                read.lost = []
            self._traced("read", plan.document_id,
                         parameter=read.batch.parameter.uri,
                         kind=read.batch.items[0].source.owner_kind,
                         owner=read.batch.items[0].source.owner_id,
                         values=len(read.claims), asked=read.asked,
                         failed=dict(read.failed),
                         unanswered=read.unanswered,
                         **({"unread": True, "why": read.why}
                            if read.unread else {}))
        return reads + located_reads

    def coordinates_of(self, plan: Plan, reads: list,
                       counts: Counts) -> None:
        """Every value of *reads* asked its coordinates, side by side;
        each Read's claims become the rows they came to."""
        values = [(read, Row(row_label(i), 0, claim))
                  for read in reads for i, claim in enumerate(read.claims)]
        done = self.each(values, lambda job: self.coordinates(
            plan, job[0], job[1], counts))
        per_read: dict = collections.defaultdict(list)
        for (read, _row), rows in zip(values, done):
            per_read[id(read)].extend(rows)
        for read in reads:
            rows = per_read.get(id(read), [])
            slots = slots_of(self.spec, read.batch.parameter)
            link_ranges(rows, slots)
            read.unanswered = mark_unanswered(rows, slots)
            read.claims = [row.claim for row in rows]

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
        pending = [chunk]
        while pending:
            piece = pending.pop(0)
            got = self._find_once(plan, parameter, piece, counts)
            out["asked"] += got["asked"]
            out["claims"] += got["claims"]
            out["failed"].update(got["failed"])
            if got["lost"] == CUT and len(piece.numbers) > 1:
                half = len(piece.numbers) // 2
                pending[:0] = [Chunk(piece.passage, piece.index,
                                     piece.numbers[:half]),
                               Chunk(piece.passage, piece.index,
                                     piece.numbers[half:])]
                continue
            if got["lost"]:
                out["lost"].append(got["lost"])
        return out

    def _find_once(self, plan: Plan, parameter, chunk: Chunk,
                   counts: Counts) -> dict:
        """The values of *parameter* in one piece, asked once: {"claims",
        "asked", "failed", "lost"}. What does not hold is asked again with
        its reason (`follow`, as often as the flow says), then left."""
        shown = Shown()
        heads = plan.headings(chunk.owner)
        shown.add(HEADINGS, "headings", heads, renumber=True)
        shown.add("", "passage", own_lines(chunk))
        listed = self.listed(parameter)
        payload = {"field": field_shown(parameter),
                   **({"list": listed[0]} if listed else {}),
                   **({"headings": shown.rendered(HEADINGS)}
                      if heads else {}),
                   "passage": block_payload(chunk.passage, shown)}
        example = find_example(shown, listed is not None)
        shape = found_format(listed is not None)
        noted = {"parameter": parameter.uri, "kind": chunk.passage.kind,
                 "owner": chunk.passage.source.owner_id, "chunk": chunk.index}
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
        for _ in range(self.numbers.follow_ups):
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

    def list_of(self, options) -> tuple:
        """A list as every request of this reading shows it (`listing`):
        with what each entry means up to the flow's number of entries
        (`flow.Numbers.list_meanings`). Every place that shows a list or
        reads a number of one goes through here, so that a number is read
        against the list it was given for."""
        return listing(options, self.numbers.list_meanings)

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
                    and number_of(got.words) is None:
                got.why = WORDS_NOT_IN_LINE
            if got.why is None and got.passage is None:
                got.why = NOT_AN_ADDRESS
            if got.why is None and listed is not None:
                got.entry = picked_entry(entry.get("entry"), len(listed[1]))
                if got.entry is None:
                    got.why = NOT_AN_OPTION
            if got.why is None:
                held.append(got)
            else:
                refused.append(({key: entry.get(key) for key in
                                 ("entry", "at", "words") if key in entry},
                                got.why))
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
        else:
            claim["value"] = got.words
        claim["quote"] = short_quote(passage, numbers, MIN_QUOTE_CHARS)
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
                    budget: Optional[int] = None) -> list:
        """The pieces a search for *sentences* shows, in the order it shows
        them (owner decisions 2026-11-09): of the pieces of the passages
        the vector search finds best, the *budget* best by kind
        (`budgeted`), ordered once by the reranker with the same
        sentences."""
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        ranked = self.search_order(plan.document_id, sentences, pieces)
        picked = budgeted(ranked, budget or self.budget, self.shares)
        if not sentences or len(picked) < 2:
            return picked
        return self.rerank(plan.document_id, sentences, picked)

    def ask_once(self, plan: Plan, field_: dict, sentences: list,
                 counts: Counts, uri: str, *, numbers: bool = False,
                 budget: Optional[int] = None, listed=None,
                 until_held: bool = False) -> tuple:
        """([Found], lost) of a field asked once of the document
        (`docfield`): the title page, then the pieces a search finds best
        for *sentences* (`shown_order`, *budget* of them), `per_request` a
        request, every find that holds kept; with *until_held* those of the
        first request that finds one, the rest of the plan after the budget
        (what the plan settles, `settled`). *listed* is the field's list
        (`listing`), whose entry a find names. *lost* is CUT or NO_ANSWER
        where a request came to nothing and nothing was found, else
        None."""
        pieces = plan.pieces(numbers)
        order = self.shown_order(plan, list(sentences), pieces, budget)
        if until_held:
            taken = set(order)
            order += [c for c in self.search_order(
                plan.document_id, list(sentences), pieces) if c not in taken]
        shape = found_format(listed is not None)
        found: list = []
        lost = None
        for start in range(0, max(len(order), 1), self.per_request):
            batch = order[start:start + self.per_request]
            if not batch and start:
                break
            shown = Shown()
            if not start:
                shown.add(TITLE_PAGE, "title_page", plan.title_page,
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
                       **({"title_page": shown.rendered(TITLE_PAGE)}
                          if TITLE_PAGE in shown.blocks else {}),
                       **({"passages": blocks} if blocks else {})}
            example = find_example(
                shown, listed is not None,
                TITLE_PAGE if TITLE_PAGE in shown.blocks
                else (letters[0] if letters else ""))
            reply = self._ask("docfield", payload, plan.document_id, shape,
                              example, counts, parameter=uri,
                              chunks=len(batch))
            if not isinstance(reply, dict):
                lost = lost or (CUT if reply == CUT else NO_ANSWER)
                continue
            held, refused = self._finds(plan, shown, reply, listed, numbers)
            for _, why in refused:
                counts.fail(why)
            for _ in range(self.numbers.follow_ups):
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
            found = joined(found, held)
            if until_held and found:
                return found, None
        return found, (lost if not found else None)

    def docfield(self, plan: Plan, parameter, counts: Counts) -> list:
        """[Read] of a field the document has once (owner decision
        2026-11-08: asked once per document, never per piece), one per
        passage a value of it was read in, each value asked its
        coordinates; a field nothing came of is a Read without values,
        unread with its reason where a request came to nothing."""
        sentences = list(self.probes(parameter, plan.document_id) or ()) \
            or [parameter.label]
        listed = self.listed(parameter)
        # A field with a list reads the budget times the flow's factor,
        # twice by default (owner decision 2026-11-09: "dann aber doppeltes
        # Budget bei Chunks").
        factor = self.numbers.listed_field_factor if listed else 1
        found, lost = self.ask_once(
            plan, field_shown(parameter, full=True), sentences, counts,
            parameter.uri, numbers=parameter.is_numeric,
            budget=self.budget * factor, listed=listed)
        reads: dict = {}
        for got in found:
            source = got.source
            owner = (source.owner_kind, source.owner_id)
            got.passage = got.passage or plan.passages.get(owner)
            claim = self.claim(plan, parameter, got, counts)
            if claim is None:
                continue
            read = reads.get(owner)
            if read is None:
                read = reads[owner] = Read(Batch(
                    plan.document_id, parameter,
                    [WorkItem(plan.document_id, parameter,
                              got.passage.source)], spec=self.spec), [])
            read.claims.append(claim)
        out = list(reads.values())
        self.coordinates_of(plan, out, counts)
        if not out and lost:
            source = plan.sources[0] if plan.sources \
                else Source("section", 0, "")
            out.append(Read(Batch(plan.document_id, parameter,
                                  [WorkItem(plan.document_id, parameter,
                                            source)], spec=self.spec), [],
                            unread=True, why=lost))
        self._traced("docfield", plan.document_id, parameter=parameter.uri,
                     values=sum(len(r.claims) for r in out),
                     **({"why": lost} if lost else {}))
        return out

    def settled(self, plan: Plan, counts: Counts) -> None:
        """What the plan settles for all its values and its own years, each
        asked once in the form of a document's field (owner decision
        2026-11-08): the settings' lines are shown under `F` with every
        value's coordinates, the years are the plan's base and target years
        (`pipeline.named_years`)."""
        field_ = self.plan_fields.get("settings")
        if field_:
            found, _ = self.ask_once(plan, field_shown_of(field_),
                                     [field_.get("sentence")
                                      or field_["name"]], counts, "settings",
                                     until_held=True)
            lines: list = []
            for got in found:
                for line, source in got.lines:
                    if all(line is not one for one, _ in lines):
                        lines.append((line, source))
            plan.settings = lines
        year = next((slot for slot in self.frame_slots
                     if slot.kind == NUMBER), None)
        for state in ("base", "target"):
            field_ = self.plan_fields.get(f"{state}_year")
            if not field_ or year is None:
                continue
            found, _ = self.ask_once(plan, field_shown_of(field_),
                                     [field_.get("sentence")
                                      or field_["name"]], counts,
                                     f"{state}_year", until_held=True)
            for got in found:
                for number in YEAR.findall(got.words):
                    value = int(number)
                    if any(b["state"] == state and b["year"] == value
                           for b in plan.bases):
                        continue
                    plan.bases.append({
                        "state": state, "axis": year.name, "year": value,
                        "quote": got.quote,
                        "source": [got.source.owner_kind,
                                   got.source.owner_id],
                        "index": len(plan.bases)})
        self._traced("settled", plan.document_id,
                     settings=len(plan.settings),
                     base=[b["year"] for b in plan.bases
                           if b["state"] == "base"],
                     target=[b["year"] for b in plan.bases
                             if b["state"] == "target"])

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
        with plan.key_lock(key):
            if key not in plan.lists:
                plan.lists[key] = self._entry(plan, uri, name, slot, words,
                                              got, counts, several, group)
            return copy.copy(plan.lists[key])

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
                      if (getattr(o, "group", "") or "") == group] or options
        else:
            lines, choices, grouped = self.list_of(options)
            if grouped:
                # A long list in two steps: its groups, then the entries of
                # the group chosen, with what each means.
                payload = {"words": words,
                           "question": slot.question or name,
                           **shown_line, **settings_of(plan), "list": lines}
                reply = self._ask("list", payload, plan.document_id,
                                  entry_format(), {"entry": 1}, counts,
                                  **noted, step="group")
                picks = self._picks(reply, len(choices), False) or []
                if picks:
                    chosen = [o for o in options
                              if (getattr(o, "group", "") or "")
                              == choices[picks[0] - 1]]
        listed, labels, _grouped = self.list_of(chosen)
        payload = {"words": words, "question": slot.question or name,
                   **shown_line, **settings_of(plan), "list": listed}
        example = {"entry": [1]} if several else {"entry": 1}
        shape = entry_format(several)
        reply = self._ask("list", payload, plan.document_id, shape, example,
                          counts, **noted)
        picks = self._picks(reply, len(labels), several)
        if picks is None:
            counts.fail(NOT_AN_OPTION)
        for _ in range(self.numbers.follow_ups):
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
            listed = [f"{i} {label} (means: {means})"
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
            for _ in range(self.numbers.follow_ups):
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
            if pick and pick not in out:
                out.append(pick)
        return out

    # -- coordinates ---------------------------------------------------------------

    def coordinates(self, plan: Plan, read: Read, row: Row,
                    counts: Counts) -> list:
        """[*row* and the rows made beside it], each coordinate of the
        spec asked on its own in the order of the groups (owner decision
        2026-11-07); a coordinate that reads the value as no value of its
        field (`fields.kept`) closes those after it (`out_of_slice`). A
        value that is a name of the document's list is that entry
        (`named_value`)."""
        parameter = read.batch.parameter
        slots = slots_of(self.spec, parameter)
        rows = [row]
        before: list = []
        made = {"n": 0}

        def clone(one: Row) -> Row:
            made["n"] += 1
            return Row(f"{one.label}.{made['n']}", one.item_index,
                       copy.deepcopy(one.claim))
        for group, group_slots in groups_of(self.spec, slots):
            for slot in in_group_order(group, group_slots):
                for one in list(rows):
                    if fields.closed(before, one.claim):
                        one.claim.setdefault(f"{slot.name}_state",
                                             OUT_OF_SLICE)
                        continue
                    if one.claim.get(f"{slot.name}_state") == READ:
                        continue
                    rows += self.coordinate(plan, read, one, group, slot,
                                            counts, clone)
                before.append(slot)
        merged = getattr(parameter, "merged", None)
        if merged and merged in plan.names:
            for one in rows:
                self.named_value(plan, parameter, one, counts)
        return rows

    def coordinate(self, plan: Plan, read: Read, row: Row, group, slot,
                   counts: Counts, clone: Callable) -> list:
        """One coordinate of one value (`coord`), [the rows made beside
        it]: its own place first; a 0 then, unless only its own passage can
        say it, the pieces beside it and a search with the sentence of how
        the plan would print it (`phrase`); a year still open the plan's
        years. The work of a value is the work of the line it stands in,
        else asked as an entry of the document's list of works, and never
        searched (`work_coordinate`, owner decisions 2026-11-09)."""
        parameter = read.batch.parameter
        if slot.name == "quantity" and slot.is_closed:
            self.quantity(plan, parameter, row, slot, counts)
            return []
        if slot.name == "work" and "work" in plan.names:
            self.work_coordinate(plan, read, row, slot, counts)
            return []
        shown, payload = show_value(plan, row.claim)
        if not shown.blocks:
            return []
        known = self.known(row.claim, [slot.name])
        payload = {**payload, "field": field_shown(parameter),
                   "question": slot.question or slot.name,
                   **({"known": known} if known else {})}
        several = self.several(slot)
        example = self.coord_example(shown, several)
        noted = {"parameter": parameter.uri, "coordinate": slot.name,
                 "owner": ((row.claim.get("at") or {}).get("owner")
                           or [None, None])[1], "value": row.label}
        reply = self._ask("coord", payload, plan.document_id,
                          coord_format(several), example, counts, **noted)
        if not isinstance(reply, dict):
            # No answer for this value: `unanswered` (`mark_unanswered`).
            return []
        made, held = self.take(plan, read, row, slot, shown, reply, payload,
                               "coord", example, counts, clone, ("own", 1),
                               noted)
        if held:
            return made
        own = slot.name in tuple(getattr(group, "own_passage", ()) or ()) \
            + tuple(getattr(group, "own_value", ()) or ())
        if row.claim.get(f"{slot.name}_state") == UNBACKED:
            pass
        elif not own:
            made += self.search(plan, read, row, slot, payload, counts,
                                clone, noted)
        else:
            row.claim[f"{slot.name}_state"] = SAID_UNSTATED
        if slot.kind == NUMBER and row.claim.get(f"{slot.name}_state") \
                != READ and any(b.get("axis") == slot.name
                                for b in plan.bases):
            self.last_year(plan, parameter, row, slot, counts, noted)
        return made

    @staticmethod
    def several(slot) -> bool:
        return bool(getattr(slot, "several", False)
                    or getattr(slot, "merged", None))

    @staticmethod
    def coord_example(shown: Shown, several: bool) -> dict:
        at = first_address(shown, False)
        if several:
            return {"found": [{"at": at, "words": fields.SAID}]}
        return {"at": at, "words": fields.SAID}

    @staticmethod
    def coord_finds(reply) -> list:
        if not isinstance(reply, dict):
            return []
        if isinstance(reply.get("found"), list):
            return [e for e in reply["found"] if isinstance(e, dict)]
        if address_of(reply.get("at")) is not None:
            return [{"at": reply.get("at"), "words": reply.get("words")}]
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
            for _ in range(self.numbers.follow_ups):
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
            if not held:
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
            years = [int(y) for y in YEAR.findall(words)]
            if not years:
                return [(self.plan_year(plan, parameter, slot, got, counts),
                         None)]
            answer = {"value": years[0], **base}
            if len(years) > 1 and SPAN.search(words) and years[-1] > years[0]:
                answer["until"] = years[-1]
            return [(answer, None)]
        merged = getattr(slot, "merged", None)
        if merged and merged in plan.names:
            besides = tuple((o.label, o.definition) for o in slot.options)
            group = bool(getattr(parameter, "takes_group", True))
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
        said = [what, claim.get("head"),
                claim.get("unit_raw") or claim.get("unit")]
        words = " / ".join(str(s) for s in said if s) \
            or str(claim.get("value_raw") or claim.get("value"))
        shown, _payload = show_value(plan, claim, headings=False)
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
                   "list": [f"{i} {b['year']} ({b['state']}: {b['quote']})"
                            for i, b in enumerate(listed, start=1)]}
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
                   "list": [f"{i} {b['year']} ({b['state']}: {b['quote']})"
                            for i, b in enumerate(listed, start=1)]}
        example = {"at": first_address(shown, False), "words": fields.SAID,
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

    def search(self, plan: Plan, read: Read, row: Row, slot, payload: dict,
               counts: Counts, clone: Callable, noted: dict) -> list:
        """A coordinate its value's own place does not state (owner
        decisions 2026-11-08 and 2026-11-09): the pieces right before and
        after the value's, then the pieces a search finds best for a
        sentence of how the plan would print the answer (`sentence`), the
        run's budget of them by kind (`shown_order`), `per_request` at a
        time, the pieces a request fetches itself first in the next, until
        a find holds, one does not hold after its follow-up (`unbacked`),
        or nothing is left to show: `unstated` where every piece of the
        plan was shown, `exhausted` where the budget left some unshown.
        [the rows made]."""
        numbers = read.batch.parameter.is_numeric
        pieces = plan.pieces(numbers)
        at = row.claim.get("at") or {}
        chunk = plan.chunk_of(tuple(at.get("owner") or ()),
                              int(at.get("line") or 1), numbers)
        seen = {chunk.key} if chunk is not None else set()
        sentence = self.sentence(plan, read, row, slot, counts)
        if is_question(sentence):
            counts.question()
            log.info("   search of %s/%s in document %s with a question: %s",
                     read.batch.parameter.uri, slot.name, plan.document_id,
                     sentence)
        batch = plan.beside(chunk, numbers) if chunk is not None else []
        window = ("near", 1)
        # Which pieces a request shows, noted with it (`shows`): those
        # beside the value ("near"), those of the search's budget
        # ("found"), or those the request before fetched itself
        # ("fetched"), which count toward no budget.
        shows = "near"
        order: Optional[list] = None
        fetched: list = []
        while True:
            batch = [c for c in dict.fromkeys(fetched + batch)
                     if c.key not in seen]
            fetched = []
            if not batch:
                if order is None:
                    order = self.shown_order(plan, [sentence], pieces)
                    window = ("found", 1)
                left = [c for c in order if c.key not in seen]
                if not left:
                    rest = any(c.key not in seen for c in pieces)
                    row.claim[f"{slot.name}_state"] = \
                        EXHAUSTED if rest else SAID_UNSTATED
                    return []
                batch = left[:self.per_request]
                shows = "found"
            seen.update(c.key for c in batch)
            made, held, more = self.search_round(
                plan, read, row, slot, payload, batch, counts, clone,
                window, {**noted, "shows": shows})
            if held or row.claim.get(f"{slot.name}_state") == UNBACKED:
                return made
            fetched = self.fetch(plan, more, batch, seen, numbers)
            batch = []
            shows = "fetched"

    def sentence(self, plan: Plan, read: Read, row: Row, slot,
                 counts: Counts) -> str:
        """The sentence a search for one coordinate goes with: as the plan
        would print the answer for this value (HyDE), written by a request
        of its own once per document, field, coordinate and wording of the
        value (`phrase`, owner decision 2026-11-09); the field's own
        sentence where none was written."""
        parameter = read.batch.parameter
        words = str(row.claim.get("value_raw") or row.claim.get("value")
                    or "")
        key = ("phrase", parameter.uri, slot.name, flat(words).casefold())
        with plan.key_lock(key):
            if key not in plan.lists:
                plan.lists[key] = self._sentence(plan, parameter, slot, row,
                                                 words, counts)
            sentence = plan.lists[key]
        if sentence:
            return sentence
        return next(iter(self.probes(parameter, plan.document_id) or ()),
                    "") or slot.question or slot.name

    def _sentence(self, plan: Plan, parameter, slot, row: Row, words: str,
                  counts: Counts) -> str:
        if self.asks.phrase is None:
            return ""
        at = row.claim.get("at") or {}
        owner = tuple(at.get("owner") or ())
        shown, _payload = show_value(plan, row.claim, headings=False)
        own = shown.blocks.get("")
        lines = [line.text for line, _ in own.lines] if own else []
        context = {key: value for key, value
                   in (self.context(plan.document_id) or {}).items()
                   if isinstance(value, str) and value.strip()}
        if not context and plan.title_page:
            context = {"name": plan.title_page[0][0].text}
        heads = [line.text for line, _ in plan.headings(owner)] \
            if owner else []
        payload = {"label": parameter.label,
                   "description": parameter.description,
                   **({"document": context} if context else {}),
                   "question": slot.question or slot.name,
                   "value": {"words": words, "lines": lines},
                   **({"headings": heads} if heads else {})}
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
        shown, _ = show_value(plan, row.claim, headings=slot.name != "work")
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
        ask_payload = {**payload, "passages": blocks}
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
            if got.why is None and got.letter in OTHERS \
                    and got.source is not None \
                    and (got.source.owner_kind, got.source.owner_id) != own \
                    and self.asks.check is not None \
                    and not self.about(plan, row, slot, got, counts, noted):
                continue
            kept.append(entry)
        more = reply.get("more") if isinstance(reply.get("more"), list) \
            else []
        if not kept:
            return [], False, more
        answer = {**reply, "found": kept} if several \
            else {**reply, **kept[0]}
        made, held = self.take(plan, read, row, slot, shown, answer,
                                  ask_payload, "search", example, counts,
                                  clone, window, noted)
        return made, held, [] if held else more

    def about(self, plan: Plan, row: Row, slot, got: Found, counts: Counts,
              noted: dict) -> bool:
        """Does the place a find of another passage stands in speak about
        this value (`check`, owner decision 2026-11-07)?"""
        _shown, payload = show_value(plan, row.claim, headings=False)
        ask_payload = {"value": payload.get("value"),
                       "passage": payload.get("passage"),
                       "question": slot.question or slot.name,
                       "answer": got.words,
                       "place": [line.text for line, _ in got.lines]}
        reply = self._ask("check", ask_payload, plan.document_id,
                          about_format(), {"about": "yes"}, counts, **noted)
        return isinstance(reply, dict) and reply.get("about") == "yes"

    def fetch(self, plan: Plan, more, batch: list, seen: set,
              numbers: bool = False) -> list:
        """The pieces a reply asks for itself (`more`), those not shown
        yet, of the pieces its field reads: the piece before or after a
        shown one, a table or figure by its placeholder, the pieces a
        pattern stands in, the pieces best for a sentence of its own."""
        pieces = plan.pieces(numbers)
        places = plan.places[bool(numbers)]
        out: list = []
        for ask in more if isinstance(more, list) else ():
            if not isinstance(ask, dict) or not batch:
                continue
            get = ask.get("get")
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
                    wanted = re.compile(ask.get("pattern") or "", re.I)
                except re.error:
                    continue
                if wanted.pattern:
                    out += [c for c in pieces
                            if c.key not in seen
                            and wanted.search(c.text())][:self.per_request]
            elif get == "similar":
                text = ask.get("text") or ""
                if text.strip():
                    out += [c for c in self.search_order(
                        plan.document_id, [text], pieces)
                        if c.key not in seen][:self.per_request]
        return [c for c in dict.fromkeys(out) if c.key not in seen]

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
        lines = [(line, source) for line, source
                 in (passage_lines(passage, [number]) if passage else [])
                 if line.number == number]
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
        heads = plan.headings(chunk.owner)
        shown.add(HEADINGS, "headings", heads, renumber=True)
        shown.add(TITLE_PAGE, "title_page", plan.title_page, renumber=True)
        shown.add("", "passage", own_lines(chunk))
        payload = {"field": shown_field,
                   **({"headings": shown.rendered(HEADINGS)}
                      if heads else {}),
                   **({"title_page": shown.rendered(TITLE_PAGE)}
                      if plan.title_page else {}),
                   "passage": block_payload(chunk.passage, shown)}
        other, _ = find_example(shown)
        own_at = f"{HEADINGS}{len(heads)}" if heads \
            else first_address(shown, False)
        example = ({**other, "own": {"at": 0, "words": ""}},
                   {"found": [], "own": {"at": own_at,
                                         "words": fields.SAID}})
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
        for _ in range(self.numbers.follow_ups):
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
        if not isinstance(raw, dict) or address_of(raw.get("at")) is None:
            return None, None
        got = resolve(shown, raw, plan.passages)
        if got.why is not None:
            return None, got.why
        source = got.source
        if got.letter in ("", HEADINGS) or (
                got.letter == TITLE_PAGE and source is not None
                and (source.owner_kind, source.owner_id) == chunk.owner):
            return got, None
        return None, None

    @staticmethod
    def covered(chunk: Chunk, found: Found) -> Optional[set]:
        """The (passage, line) places a find of a piece's work request
        speaks for: the whole piece (None) where it stands in a heading or
        in what every piece of its passage shows (a table's title and head,
        a figure's caption), else its own lines."""
        if found.letter == HEADINGS:
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
        example = {"at": first_address(shown, False), "words": fields.SAID}
        reply = self._ask("coord", ask_payload, plan.document_id,
                          coord_format(False), example, counts,
                          parameter=parameter.uri, coordinate="work")
        finds = self.coord_finds(reply)
        if not finds:
            return None
        got = resolve(shown, finds[0], plan.passages)
        if got.why is not None or got.passage is None:
            return None
        if got.letter == HEADINGS:
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
        example = {"entry": 1, "at": first_address(shown, False),
                   "words": fields.SAID}
        noted = {"parameter": parameter.uri, "coordinate": slot.name,
                 "owner": ((row.claim.get("at") or {}).get("owner")
                           or [None, None])[1], "value": row.label}
        reply = self._ask("coord", payload, plan.document_id,
                          work_choice_format(), example, counts, **noted)
        if not isinstance(reply, dict):
            return
        failed = self.read_work(plan, row, slot, shown, reply)
        if failed:
            for _ in range(self.numbers.follow_ups):
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
        if pick == 0 or address_of(reply.get("at")) is None:
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
        uri = THIS_PUBLICATION if number == 1 else ANOTHER_WORK
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
            return False
        number, found, evidence = got
        works = plan.names["work"]
        if not 0 < number <= len(works.entries):
            return False
        return not self.take_work(row, slot, number, found, evidence,
                                  ("piece", 1), works)

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


def settings_of(plan: Plan) -> dict:
    """{"settings": lines} of what the plan settles for all its values,
    shown beside a list's entries, {} where it settles nothing: they hold
    for every value, also where the entry of a wording depends on them
    (emissions given in CO2 equivalents)."""
    if not plan.settings:
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
        if reranker is None or not sentences or len(chunks) < 2:
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
            if kept and kept.get("key") == key:
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
