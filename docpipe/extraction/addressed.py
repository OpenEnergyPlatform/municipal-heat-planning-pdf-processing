"""
addressed.py: One document read in pieces of numbered lines, one question per
request, every answer an address (owner decisions 2026-11-08 evening, both
profiles).

Every request carries its instruction, the smallest part of the plan that
answers its question, and one question; every answer is an address, a
number or a few words, and code looks up what an address names
(`units.py`). Nothing is a conversation: an answer that did not hold is
asked once more as a request of its own, with what did not hold (`follow`).

The steps of a document (`Reader`):

1. Its passages as numbered lines and pieces of at most eight
   (`units.Chunk`); a figure transcribed into lines once per run and kept
   under the harvest (`Transcripts`), its image sent to no other request.
2. What the plan settles for all its values and its own years, where the
   profile asks them (`PLAN_FIELDS`), and the fields a document has once
   (`Parameter.once_per_document`): the title page and the five pieces a
   search finds best for a sentence written for the field, then the next
   five, until an answer holds or every piece was shown (`docfield`).
3. Every other field in every piece, the pieces best first for the
   field's sentences (`find`): each value an address and its words.
4. Each coordinate of each value on its own (`coord`): the value's line
   with the head of its table or the sentences beside it, the headings up
   to it, the title page and the plan's settings; the answer an address and
   words, or 0 with a sentence of how the plan would print what is missing
   (HyDE). An entry of a list is asked once per wording (`list`), a name of
   the document's list of scenarios or works once per name (`names`). A 0
   is asked again with the pieces before and after the value's, then with
   the pieces a search with that sentence finds best, five at a time
   (`search`); what only the value's own passage can say is not searched.
   A find from another passage is asked whether it speaks about the value
   (`check`). A year still open is asked last with the plan's base and
   target years.
5. A value stated for a group of scenarios takes the members the document
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
from .fields import (EXHAUSTED, NUMBER, OUT_OF_SLICE, READ, SAID_UNSTATED,
                     UNBACKED)
from .pipeline import (Batch, Row, Source, WorkItem, mark_unanswered,
                       merge_field, row_label)
from .reading import (CUT, NO_ANSWER, Read, groups_of, in_group_order,
                      link_ranges, slots_of, span_rows)
from .units import (HEADINGS, OTHERS, SETTINGS, TITLE_PAGE, Chunk, Line,
                    Passage, Shown, address_of, chunks_of, own_lines,
                    passage_lines, passage_of, short_quote, title_page_of)
from .verify import MIN_QUOTE_CHARS, canonical_number, flat, numbers_in
from .wording import say

log = logging.getLogger(__name__)

# The requests and their prompts, one task each.
KINDS = ("transcribe", "find", "docfield", "coord", "list", "names",
         "search", "check", "follow")
PROMPT_IDS = {kind: f"extraction/{kind}" for kind in KINDS}
# Requests a profile may leave unwritten: the check of a find from another
# passage, and the names request of a run that builds no list of names
# (`runner.names_asked`).
OPTIONAL = ("check", "names")

# Why a find or a coordinate's answer does not hold beyond the two checks of
# the harvest: its address names no line the request showed, or its words
# do not stand in the line it names (`schema.DROP_REASONS`).
NOT_AN_ADDRESS = "not_an_address"
WORDS_NOT_IN_LINE = "words_not_in_line"

# Pieces a document field's request shows besides the title page, and a
# search's request (owner decisions 2026-11-08).
DOCFIELD_CHUNKS = 5
SEARCH_CHUNKS = 5
# Passages of a search whose pieces the reranker orders before the rest.
SEARCH_PASSAGES = 10
# Entries of a list shown with what each means; a longer list shows its
# names only, and one whose entries name groups is asked group first.
LIST_WITH_MEANS = 24
# Headings shown up to a value's place, its own last.
SECTION_TITLES = 10

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


def found_format() -> dict:
    """The finds of a request: each an address and the words of the value,
    an empty list where nothing shown holds one."""
    return _format("found_reply", {
        "type": "object",
        "properties": {"found": {"type": "array", "items": _FOUND}},
        "required": ["found"], "additionalProperties": False})


def coord_format(several: bool, more: bool = False) -> dict:
    """A coordinate's answer: an address and its words, or 0 and the
    sentence of how the plan would print it (`hyde`); one that may name
    several entries lists its finds."""
    if several:
        properties = {"found": {"type": "array", "items": _FOUND},
                      "hyde": {"type": "string"}}
        required = ["found"]
    else:
        properties = {"at": {"type": ["string", "integer"]},
                      "words": {"type": "string"},
                      "hyde": {"type": "string"}}
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
    return _format("lines_reply", {
        "type": "object",
        "properties": {"lines": {"type": "array",
                                 "items": {"type": "string"}}},
        "required": ["lines"], "additionalProperties": False})


def about_format() -> dict:
    return _format("check_reply", {
        "type": "object", "properties": {"about": {"enum": ["yes", "no"]}},
        "required": ["about"], "additionalProperties": False})


def nothing_found(reply) -> bool:
    """Does a coordinate's answer say nothing shown states it?"""
    if not isinstance(reply, dict):
        return False
    if isinstance(reply.get("found"), list):
        return not reply["found"]
    return address_of(reply.get("at")) is None


def hyde_missing(reply) -> Optional[str]:
    """"hyde" where a coordinate's answer says nothing shown states it and
    gives no sentence and fetches nothing: such a reply is asked again
    (owner decision 2026-11-08, test 6); None where it holds."""
    if not isinstance(reply, dict) or not nothing_found(reply) \
            or reply.get("more"):
        return None
    hyde = reply.get("hyde")
    return None if isinstance(hyde, str) and hyde.strip() else "hyde"


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


def first_address(shown: Shown, table: bool, letter: str = "") -> str:
    """An address for a request's example: the first of its own lines that
    is no title or head, a cell of it in a table."""
    block = shown.blocks.get(letter) \
        or next(iter(shown.blocks.values()), None)
    if block is None or not block.entries:
        return "1"
    entries = [e for e in block.entries
               if e[1].role in ("body", "text", "figure", "foot")] \
        or block.entries
    number, line, _ = entries[0]
    cell = ".2" if table and line.cells and len(line.cells) > 1 else ""
    return f"{block.letter}{number}{cell}"


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

    @property
    def quote(self) -> str:
        return " ".join(line.text for line, _ in self.quoted or self.lines)

    @property
    def source(self) -> Optional[Source]:
        return self.lines[0][1] if self.lines else None


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
    """figure -> its lines, transcribed once per run and kept under the
    harvest (`transcripts/<document>.json`): a figure whose image and prompt
    are those of the kept transcription is not asked again (owner decision
    2026-11-08, e).

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
        """({figure id: [lines]}, asked) of *figures*: the kept ones read,
        the others asked (*each(jobs, run)* runs them side by side) and
        kept."""
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
                    and isinstance(entry.get("lines"), list):
                out[source.owner_id] = list(entry["lines"])
            elif self.ask is not None:
                wanted.append((source, key))

        def one(job):
            source, key = job
            reply = self.ask(source, document_id)
            lines = reply.get("lines") if isinstance(reply, dict) else None
            if not isinstance(lines, list):
                return source, key, None
            return source, key, [str(line).strip() for line in lines
                                 if str(line).strip()]
        done = (each(wanted, one) if each is not None
                else [one(job) for job in wanted])
        changed = False
        for source, key, lines in done:
            if not lines:
                continue
            out[source.owner_id] = lines
            kept[str(source.owner_id)] = {"image": key, "lines": lines,
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
    requests and in the graph, the work it belongs to, and the line it was
    first read at."""
    label: str
    name: str
    work: int = 0
    quote: str = ""


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

    def add(self, name: str, work: int = 0, quote: str = "") -> int:
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
            self.entries.append(Entry(label, name, work, quote))
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
                 chunk_units: int):
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
        self.title_page = title_page_of(list(self.passages.values()))
        self.settings: list = []          # [(Line, Source)]
        self.bases: list = []             # `pipeline.named_years` entries
        self.lists: dict = {}
        self.names: dict = {}             # kind -> Names
        self.lock = threading.Lock()
        self._locks: dict = {}
        self._headings: dict = {}

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
                                             SECTION_TITLES):
            title = lookup.title_of(section)
            if title:
                got.append((Line(len(got) + 1, title, (), "heading"),
                            Source(section.owner_kind, section.owner_id,
                                   title, section.provenance)))
        with self.lock:
            self._headings[owner] = got
        return got

    def chunk_of(self, owner: tuple, number: int) -> Optional[Chunk]:
        """The piece of a passage that holds its line *number*."""
        pieces = [c for c in self.chunks if c.owner == tuple(owner)]
        return next((c for c in pieces if number in c.numbers),
                    pieces[0] if pieces else None)

    def beside(self, chunk: Chunk) -> list:
        """The pieces right before and after *chunk* in the plan's order."""
        at = self.position.get(chunk.key)
        if at is None:
            return []
        return [self.chunks[i] for i in (at - 1, at + 1)
                if 0 <= i < len(self.chunks)]


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
    example, **noted) -> the reply as a dict, CUT or None. *follow* is a
    request asked once more with what did not hold: (kind, payload,
    document_id, *, shape, example, **noted). *check* and *names* are None
    where the profile writes no prompt for them (`OPTIONAL`)."""
    find: Callable
    docfield: Callable
    coord: Callable
    list: Callable
    search: Callable
    follow: Callable
    names: Optional[Callable] = None
    check: Optional[Callable] = None


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
    *each(jobs, run)* runs jobs side by side; *budget* is how many lists of
    a search one coordinate walks before it is `exhausted`.
    """

    def __init__(self, spec, asks: Asks, order: Callable, *,
                 search_order: Optional[Callable] = None,
                 probes: Optional[Callable] = None,
                 known: Optional[Callable] = None,
                 span_marks: Optional[dict] = None,
                 plan_fields: Optional[dict] = None,
                 works: Optional[dict] = None,
                 frame_slots: Optional[list] = None,
                 each: Optional[Callable] = None, trace=None,
                 budget: int = 12):
        self.spec = spec
        self.asks = asks
        self.order = order
        self.search_order = search_order or order
        self.probes = probes or (lambda parameter, document_id: [])
        self.known = known or (lambda claim, asked: {})
        self.span_marks = dict(span_marks or {})
        self.plan_fields = dict(plan_fields or {})
        self.works_field = works
        self.frame_slots = list(frame_slots or ())
        self.each = each or (lambda jobs, run: [run(job) for job in jobs])
        self.trace = trace
        self.budget = max(1, int(budget))

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
        """The request asked once more, as a request of its own: what it
        showed, the answer that did not hold and why (owner decision
        2026-11-08: "Rückfragen sind eigene Anfragen")."""
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
            reads.extend(self.works(plan, list(plan.chunks), counts))
        once = [p for p in parameters
                if getattr(p, "once_per_document", False)]
        for parameter in once:
            reads.extend(self.docfield(plan, parameter, counts))
        located = [p for p in parameters if p not in once]
        jobs = []
        for parameter in located:
            chosen = pieces_of(parameter.uri)
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
        "asked", "failed", "lost"}. What does not hold is asked once more
        with its reason (`follow`), then left."""
        shown = Shown()
        heads = plan.headings(chunk.owner)
        shown.add(HEADINGS, "headings", heads, renumber=True)
        shown.add("", "passage", own_lines(chunk))
        payload = {"field": field_shown(parameter),
                   **({"headings": shown.rendered(HEADINGS)}
                      if heads else {}),
                   "passage": block_payload(chunk.passage, shown)}
        example = {"found": [{"at": first_address(
            shown, chunk.passage.kind == "table"), "words": fields.SAID}]}
        noted = {"parameter": parameter.uri, "kind": chunk.passage.kind,
                 "owner": chunk.passage.source.owner_id, "chunk": chunk.index}
        out = {"claims": [], "asked": 1, "failed": collections.Counter(),
               "lost": None}
        reply = self._ask("find", payload, plan.document_id, found_format(),
                          example, counts, **noted)
        if not isinstance(reply, dict):
            out["lost"] = CUT if reply == CUT else NO_ANSWER
            return out
        held, refused = self._finds(plan, parameter, shown, reply)
        if refused:
            out["failed"].update(why for _, why in refused)
            for _, why in refused:
                counts.fail(why)
            again = self._follow(
                "find", payload, plan.document_id, found_format(), example,
                reply, [{**entry, "why": told(why, entry)}
                        for entry, why in refused],
                counts, **noted)
            out["asked"] += 1
            if isinstance(again, dict):
                more, _ = self._finds(plan, parameter, shown, again)
                taken = {(id(g.lines[0][0]), g.cell, g.words) for g in held}
                held += [g for g in more if (id(g.lines[0][0]), g.cell,
                                             g.words) not in taken]
        for got in held:
            claim = self.claim(plan, parameter, got, counts)
            if claim is not None:
                out["claims"].append(claim)
        return out

    def _finds(self, plan: Plan, parameter, shown: Shown, reply) -> tuple:
        """([Found] that hold, [(entry, why)] that do not) of a reply: a
        number's words name exactly one number."""
        held, refused = [], []
        for entry in reply.get("found") or ():
            if not isinstance(entry, dict):
                continue
            got = resolve(shown, entry, plan.passages)
            if got.why is None and parameter.is_numeric \
                    and number_of(got.words) is None:
                got.why = WORDS_NOT_IN_LINE
            if got.why is None and got.passage is None:
                got.why = NOT_AN_ADDRESS
            if got.why is None:
                held.append(got)
            else:
                refused.append(({"at": entry.get("at"),
                                 "words": entry.get("words")}, got.why))
        return held, refused

    def claim(self, plan: Plan, parameter, got: Found,
              counts: Counts) -> Optional[dict]:
        """The claim of a value found: its number or words, the line as its
        quote, its address, the head of its column, and for a figure that a
        model read it off a picture (`drawn`, trust level C). A value of a
        list is asked its entry (`list`)."""
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
            entry = self.entry(plan, parameter.uri, "value", slot,
                               got.words, got, counts) \
                if slot.options else ""
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

    def ask_once(self, plan: Plan, field_: dict, sentences: list,
                 counts: Counts, uri: str) -> tuple:
        """([Found], lost) of a field asked once of the document
        (`docfield`): the title page and the `DOCFIELD_CHUNKS` pieces a
        search finds best for *sentences*, then the next ones, until an
        answer holds or every piece was shown. *lost* is CUT or NO_ANSWER
        where a request came to nothing, else None."""
        ranked = self.search_order(plan.document_id, list(sentences),
                                   plan.chunks)
        first = True
        for start in range(0, max(len(ranked), 1), DOCFIELD_CHUNKS):
            batch = ranked[start:start + DOCFIELD_CHUNKS]
            if not batch and not first:
                break
            shown = Shown()
            if first:
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
                       **({"title_page": shown.rendered(TITLE_PAGE)}
                          if TITLE_PAGE in shown.blocks else {}),
                       **({"passages": blocks} if blocks else {})}
            example = {"found": [{"at": first_address(
                shown, False, TITLE_PAGE if first and plan.title_page
                else (letters[0] if letters else "")),
                "words": fields.SAID}]}
            first = False
            reply = self._ask("docfield", payload, plan.document_id,
                              found_format(), example, counts,
                              parameter=uri, chunks=len(batch))
            if not isinstance(reply, dict):
                return [], CUT if reply == CUT else NO_ANSWER
            entries = [e for e in reply.get("found") or ()
                       if isinstance(e, dict)]
            got = [resolve(shown, e, plan.passages) for e in entries]
            held = [g for g in got if g.why is None]
            refused = [(e, g.why) for e, g in zip(entries, got) if g.why]
            if refused:
                for _, why in refused:
                    counts.fail(why)
                again = self._follow(
                    "docfield", payload, plan.document_id, found_format(),
                    example, reply,
                    [{"at": e.get("at"), "words": e.get("words"),
                      "why": told(why, e)} for e, why in refused], counts,
                    parameter=uri)
                if isinstance(again, dict):
                    held += [g for g in (resolve(shown, e, plan.passages)
                                         for e in again.get("found") or ()
                                         if isinstance(e, dict))
                             if g.why is None]
            if held:
                return held, None
        return [], None

    def docfield(self, plan: Plan, parameter, counts: Counts) -> list:
        """[Read] of a field the document has once (owner decision
        2026-11-08: asked once per document, never per piece), one per
        passage a value of it was read in, each value asked its
        coordinates; a field nothing came of is a Read without values,
        unread with its reason where a request came to nothing."""
        sentences = list(self.probes(parameter, plan.document_id) or ()) \
            or [parameter.label]
        found, lost = self.ask_once(plan, field_shown(parameter, full=True),
                                    sentences, counts, parameter.uri)
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
                                      or field_["name"]], counts, "settings")
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
                                     f"{state}_year")
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
              got: Optional[Found], counts: Counts, several: bool = False):
        """The entry of *slot*'s list a wording means, asked once per
        document, field, coordinate and wording (`list`, owner decision
        2026-11-08): its label, a list of labels where several may be
        meant, "" where none fits (0)."""
        key = ("list", uri, name, flat(words).casefold())
        with plan.key_lock(key):
            if key not in plan.lists:
                plan.lists[key] = self._entry(plan, uri, name, slot, words,
                                              got, counts, several)
            return copy.copy(plan.lists[key])

    def _entry(self, plan: Plan, uri: str, name: str, slot, words: str,
               got: Optional[Found], counts: Counts, several: bool):
        options = [(o.label, o.definition, getattr(o, "group", "") or "")
                   for o in slot.options]
        if not options:
            return [words] if several else words
        shown_line: dict = {}
        if got is not None and got.lines:
            shown_line["lines"] = [line.text for line, _ in got.lines]
            if got.passage is not None and got.passage.kind == "table":
                shown_line["table"] = got.passage.title
        groups: list = []
        for _label, _means, group in options:
            if group and group not in groups:
                groups.append(group)
        chosen = options
        noted = {"parameter": uri, "coordinate": name}
        if len(options) > LIST_WITH_MEANS and len(groups) > 1:
            # A long list in two steps: its groups, then the entries of the
            # group chosen, with what each means.
            payload = {"words": words, "question": slot.question or name,
                       **shown_line, **settings_of(plan),
                       "list": [f"{i} {g}" for i, g in enumerate(groups, 1)]}
            reply = self._ask("list", payload, plan.document_id,
                              entry_format(), {"entry": 1}, counts,
                              **noted, step="group")
            picks = self._picks(reply, len(groups), False) or []
            if picks:
                chosen = [o for o in options if o[2] == groups[picks[0] - 1]]
        listed = []
        for i, (label, means, _group) in enumerate(chosen, start=1):
            text = f"{i} {label}"
            if means and len(chosen) <= LIST_WITH_MEANS:
                text += f" (means: {means})"
            with plan.lock:
                said = list(plan.lists.get(("said", uri, name, label), ()))
            if said:
                text += f" (in this document: {', '.join(said[:3])})"
            listed.append(text)
        payload = {"words": words, "question": slot.question or name,
                   **shown_line, **settings_of(plan), "list": listed}
        example = {"entry": [1]} if several else {"entry": 1}
        shape = entry_format(several)
        reply = self._ask("list", payload, plan.document_id, shape, example,
                          counts, **noted)
        picks = self._picks(reply, len(chosen), several)
        if picks is None:
            counts.fail("not_an_option")
            given = reply.get("entry") if isinstance(reply, dict) else None
            again = self._follow("list", payload, plan.document_id, shape,
                                 example, reply,
                                 [say("not_an_option", given=given)],
                                 counts, **noted)
            picks = self._picks(again, len(chosen), several) or []
        labels = [chosen[i - 1][0] for i in picks]
        with plan.lock:
            for label in labels:
                said = plan.lists.setdefault(("said", uri, name, label), [])
                if words not in said:
                    said.append(words)
        if several:
            return labels
        return labels[0] if labels else ""

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
                uri: str = "") -> list:
        """The entries of the document's list of *kind* a name means
        (`names`): [(label, number)], a new entry where the name is not on
        the list yet, ("out", label) for an entry *besides* the names
        ((label, means)); with *group* the words may name several entries.
        Each name is asked once per document and work."""
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
            picks = self._name_picks(reply, len(listed))
            if picks is None:
                counts.fail("name_not_listed")
                given = reply.get("entry") if isinstance(reply, dict) \
                    else None
                again = self._follow("names", payload, plan.document_id,
                                     shape, example, reply,
                                     [say("name_not_listed", given=given)],
                                     counts, **noted)
                picks = self._name_picks(again, len(listed)) or []
            out = []
            for pick in picks:
                if pick == NEW:
                    number = names.add(words, work,
                                       got.quote if got is not None else "")
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
        the plan would print it; a year still open the plan's years."""
        parameter = read.batch.parameter
        if slot.name == "quantity" and slot.is_closed:
            self.quantity(plan, parameter, row, slot, counts)
            return []
        shown, payload = show_value(plan, row.claim,
                                    headings=slot.name != "work")
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
        made, held, hyde = self.take(plan, read, row, slot, shown, reply,
                                     payload, "coord", example, counts,
                                     clone, ("own", 1), noted)
        if held:
            return made
        own = slot.name in tuple(getattr(group, "own_passage", ()) or ()) \
            + tuple(getattr(group, "own_value", ()) or ())
        if row.claim.get(f"{slot.name}_state") == UNBACKED:
            pass
        elif not own:
            made += self.search(plan, read, row, slot, payload, hyde,
                                counts, clone, noted)
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
        """(rows made, held, hyde) of a coordinate's answer: its finds each
        read onto the row, one row per entry where several are named, and
        checked (`merge_field`); what does not hold is asked once more with
        its reason (`follow`), then stays `unbacked`. *hyde* is the
        answer's sentence where it found nothing."""
        finds = self.coord_finds(reply)
        hyde = reply.get("hyde") if isinstance(reply.get("hyde"), str) \
            else ""
        if not finds:
            return [], False, hyde
        made, held, failed = self.settle(plan, read, row, slot, shown, finds,
                                         counts, clone, window)
        if failed and not held:
            again = self._follow(kind, payload, plan.document_id,
                                 coord_format(self.several(slot),
                                              more=kind == "search"),
                                 example, reply, failed, counts, **noted)
            finds = self.coord_finds(again)
            if finds:
                more, held, _ = self.settle(plan, read, row, slot, shown,
                                            finds, counts, clone, window)
                made += more
            elif isinstance(again, dict) and isinstance(again.get("hyde"),
                                                        str):
                hyde = again["hyde"]
            if not held:
                row.claim[f"{slot.name}_state"] = UNBACKED
        return made, held, hyde

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
        if slot.name == "work" and "work" in plan.names:
            picked = self.name_of(plan, "work", words, got, counts,
                                  uri=parameter.uri)
            if not picked:
                return [({"value": "", **base}, None)]
            label, number = picked[0]
            uri = THIS_PUBLICATION if number == 1 else ANOTHER_WORK
            option = next((o.label for o in slot.options if o.uri == uri),
                          uri)
            return [({"value": option, **base}, [label])]
        merged = getattr(slot, "merged", None)
        if merged and merged in plan.names:
            besides = tuple((o.label, o.definition) for o in slot.options)
            group = bool(getattr(parameter, "takes_group", True))
            picked = self.name_of(plan, merged, words, got, counts,
                                  work=self.work_of(plan, row),
                                  besides=besides, group=group,
                                  uri=parameter.uri)
            if not picked:
                return [({"value": words, **base}, None)]
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
               hyde: str, counts: Counts, clone: Callable,
               noted: dict) -> list:
        """A coordinate its value's own place does not state (owner
        decisions 2026-11-08): the pieces right before and after the
        value's, then the pieces a search finds best for the answer's
        sentence of how the plan would print it (HyDE; the field's own
        sentence where it wrote none), `SEARCH_CHUNKS` at a time, until a
        find holds, one does not hold after its follow-up (`unbacked`),
        the ranking ends (`unstated`) or the budget does (`exhausted`). What
        a request asks to fetch itself (`more`) is shown in the next. [the
        rows made]."""
        at = row.claim.get("at") or {}
        chunk = plan.chunk_of(tuple(at.get("owner") or ()),
                              int(at.get("line") or 1))
        seen = {chunk.key} if chunk is not None else set()
        sentence = hyde.strip() if hyde and hyde.strip() else ""
        if not sentence:
            sentence = next(iter(self.probes(read.batch.parameter,
                                             plan.document_id) or ()), "") \
                or slot.question or slot.name
        if is_question(sentence):
            counts.question()
            log.info("   search of %s/%s in document %s with a question: %s",
                     read.batch.parameter.uri, slot.name, plan.document_id,
                     sentence)
        batch = plan.beside(chunk) if chunk is not None else []
        window = ("near", 1)
        ranking: Optional[list] = None
        rounds = 0
        fetched: list = []
        while True:
            batch = [c for c in fetched + batch if c.key not in seen]
            fetched = []
            if not batch:
                if ranking is None:
                    ranking = self.search_order(plan.document_id, [sentence],
                                                plan.chunks)
                    window = ("found", 1)
                left = [c for c in ranking if c.key not in seen]
                if not left:
                    row.claim[f"{slot.name}_state"] = SAID_UNSTATED
                    return []
                if rounds >= self.budget:
                    row.claim[f"{slot.name}_state"] = EXHAUSTED
                    return []
                batch = left[:SEARCH_CHUNKS]
            seen.update(c.key for c in batch)
            rounds += 1
            made, held, more = self.search_round(plan, read, row, slot,
                                                 payload, batch, counts,
                                                 clone, window, noted)
            if held or row.claim.get(f"{slot.name}_state") == UNBACKED:
                return made
            fetched = self.fetch(plan, more, batch, seen)
            batch = []

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
        made, held, _ = self.take(plan, read, row, slot, shown, answer,
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

    def fetch(self, plan: Plan, more, batch: list, seen: set) -> list:
        """The pieces a reply asks for itself (`more`), those not shown
        yet: the piece before or after a shown one, a table or figure by
        its placeholder, the pieces a pattern stands in, the pieces best
        for a sentence of its own."""
        out: list = []
        for ask in more if isinstance(more, list) else ():
            if not isinstance(ask, dict) or not batch:
                continue
            get = ask.get("get")
            if get in ("next", "previous"):
                anchor = batch[-1] if get == "next" else batch[0]
                at = plan.position.get(anchor.key)
                if at is not None:
                    i = at + (1 if get == "next" else -1)
                    if 0 <= i < len(plan.chunks):
                        out.append(plan.chunks[i])
            elif get == "item":
                found = lookup.item(plan.sources, ask.get("id") or "")
                if found is not None:
                    out += [c for c in plan.chunks
                            if c.owner == (found.owner_kind,
                                           found.owner_id)][:1]
            elif get == "search":
                try:
                    wanted = re.compile(ask.get("pattern") or "", re.I)
                except re.error:
                    continue
                if wanted.pattern:
                    out += [c for c in plan.chunks
                            if c.key not in seen
                            and wanted.search(c.text())][:SEARCH_CHUNKS]
            elif get == "similar":
                text = ask.get("text") or ""
                if text.strip():
                    out += [c for c in self.search_order(
                        plan.document_id, [text], plan.chunks)
                        if c.key not in seen][:SEARCH_CHUNKS]
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
                              uri=parameter.uri)
        if picked and picked[0][0] != "out":
            claim["value_means"] = [picked[0][0]]

    def works(self, plan: Plan, chunks: list, counts: Counts) -> list:
        """The works the document presents, compares or cites beside itself
        (owner decision 2026-11-08, h): found piece by piece (the profile's
        `WORKS` field), each asked against the document's list of works,
        and each new one asked at its line for what the profile asks of a
        work (its title, its organisation, its year, its short name):
        values of that work, never of this publication, which the graph
        does not take. [Read] of those values."""
        field_ = self.works_field or {}
        shown_field = {"name": field_.get("name", "work"),
                       "means": field_.get("means", "")}
        finds = self.each(list(chunks), lambda chunk: self.work_finds(
            plan, shown_field, chunk, counts))
        new: list = []
        for found in finds:
            for one in found:
                before = len(plan.names["work"].entries)
                picked = self.name_of(plan, "work", one.words, one, counts)
                if picked and picked[0][1] > before:
                    new.append((picked[0][1], one))
        reads: dict = {}
        for number, one in new:
            label = plan.names["work"].entries[number - 1].label
            for uri, question in (field_.get("fields") or {}).items():
                parameter = self.spec.by_uri.get(uri)
                if parameter is None:
                    continue
                claim = self.work_value(plan, parameter, question, one,
                                        label, counts)
                if claim is None:
                    continue
                owner = one.passage.owner
                read = reads.get((uri, owner))
                if read is None:
                    read = reads[(uri, owner)] = Read(Batch(
                        plan.document_id, parameter,
                        [WorkItem(plan.document_id, parameter,
                                  one.passage.source)], spec=self.spec), [])
                read.claims.append(claim)
        self._traced("works", plan.document_id,
                     works=len(plan.names["work"].entries), new=len(new))
        return list(reads.values())

    def work_finds(self, plan: Plan, shown_field: dict, chunk: Chunk,
                   counts: Counts) -> list:
        """[Found] of the names of other works in one piece (`find`)."""
        shown = Shown()
        shown.add("", "passage", own_lines(chunk))
        payload = {"field": shown_field,
                   "passage": block_payload(chunk.passage, shown)}
        example = {"found": [{"at": first_address(
            shown, chunk.passage.kind == "table"), "words": fields.SAID}]}
        reply = self._ask("find", payload, plan.document_id, found_format(),
                          example, counts, parameter="work",
                          kind=chunk.passage.kind,
                          owner=chunk.passage.source.owner_id,
                          chunk=chunk.index)
        if not isinstance(reply, dict):
            return []
        out = []
        for entry in reply.get("found") or ():
            got = resolve(shown, entry, plan.passages) \
                if isinstance(entry, dict) else None
            if got is not None and got.why is None and got.passage:
                out.append(got)
        return out

    def work_value(self, plan: Plan, parameter, question: str, one: Found,
                   label: str, counts: Counts) -> Optional[dict]:
        """One detail of a work, asked at its line (`coord`): the claim of
        a value of *parameter* whose work is that work, with the line as its
        quote; None where the line does not give it."""
        passage = one.passage
        numbers = [line.number for line, _ in one.lines]
        shown = Shown()
        shown.add("", "passage", passage_lines(passage, numbers))
        payload = {"work": label, "field": field_shown(parameter),
                   "question": question,
                   "passage": block_payload(passage, shown)}
        example = {"at": first_address(shown, passage.kind == "table"),
                   "words": fields.SAID}
        reply = self._ask("coord", payload, plan.document_id,
                          coord_format(False), example, counts,
                          parameter=parameter.uri, coordinate="work")
        finds = self.coord_finds(reply)
        if not finds:
            return None
        got = resolve(shown, finds[0], plan.passages)
        if got.why is not None:
            return None
        claim = self.claim(plan, parameter, got, counts)
        work = next((s for s in fields.axis_slots(parameter)
                     if s.name == "work"), None)
        if claim is None or work is None:
            return claim
        option = next((o.label for o in work.options
                       if o.uri == ANOTHER_WORK), ANOTHER_WORK)
        claim.update({"work": option, "work_state": READ,
                      "work_raw": got.words if flat(got.words).casefold()
                      in flat(claim["quote"]).casefold() else label,
                      "work_quote": claim["quote"],
                      "work_source": list(passage.owner),
                      "work_window": ["own", 1], "work_means": [label]})
        if flat(claim["work_raw"]).casefold() \
                not in flat(claim["quote"]).casefold():
            claim["work_raw"] = got.words
        return claim


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
    """(order, search_order), each (document_id, sentences, chunks) -> the
    pieces best first. *order* has the reranker score every piece with
    every sentence, keeping each piece's best (owner decisions 2026-11-08:
    all pieces, best first); *search_order* takes the passages the vector
    search finds best (*rank*, with its reranker over passages), has the
    reranker order the pieces of the first `SEARCH_PASSAGES` and puts the
    rest after them in the plan's order (owner decision 2026-11-08: "Treffer
    werden in ihre Stücke zerlegt und vom Reranker mit demselben Satz
    geordnet"). Without a reranker the pieces keep their passages' order;
    without either, the plan's."""
    local = threading.local()

    def reranked(document_id: int, sentences: list, chunks: list) -> list:
        if reranker is None or not chunks:
            return list(chunks)
        if getattr(local, "reranker", None) is None:
            local.reranker = reranker()
        if local.reranker is None:
            return list(chunks)
        docs = [ChunkDoc(c.passage.kind, c.key, c.text()) for c in chunks]
        by = {doc.owner_id: c for doc, c in zip(docs, chunks)}
        try:
            return [by[doc.owner_id] for doc in local.reranker.order(
                document_id, sentences, docs)]
        except Exception as exc:       # the order only
            log.warning("   order of the pieces of %s failed, read in the "
                        "plan's order: %s", document_id, exc)
            return list(chunks)

    def passages_first(document_id: int, sentences: list,
                       chunks: list) -> tuple:
        if rank is None:
            return [], list(chunks)
        try:
            passages = rank(document_id, sentences, set())
        except Exception as exc:
            log.warning("   search of %s failed: %s", document_id, exc)
            return [], list(chunks)
        first: list = []
        for source in passages[:SEARCH_PASSAGES]:
            owner = (source.owner_kind, source.owner_id)
            first += [c for c in chunks if c.owner == owner]
        later: list = []
        for source in passages[SEARCH_PASSAGES:]:
            owner = (source.owner_kind, source.owner_id)
            later += [c for c in chunks if c.owner == owner]
        taken = set(first) | set(later)
        return first, later + [c for c in chunks if c not in taken]

    def order(document_id: int, sentences: list, chunks: list) -> list:
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        if not sentences or not chunks:
            return list(chunks)
        if reranker is not None:
            return reranked(document_id, sentences, chunks)
        first, rest = passages_first(document_id, sentences, chunks)
        return first + rest

    def search_order(document_id: int, sentences: list,
                     chunks: list) -> list:
        sentences = [s for s in sentences if isinstance(s, str) and s.strip()]
        if not sentences or not chunks:
            return list(chunks)
        first, rest = passages_first(document_id, sentences, chunks)
        if not first:
            return reranked(document_id, sentences, chunks)
        return reranked(document_id, sentences, first) + rest
    return order, search_order


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
    [piece key]}: the pieces of each field best first for its sentences,
    kept under the harvest (`survey/<document>[.<scope>].json`) with the
    passages each field was read in, which the passes over a stored harvest
    read (`surveyed.surveyed_owners`)."""

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
                wanted = {tuple(c.key) for c in chunks}
                if set(order) == {p.uri for p in parameters} and all(
                        {tuple(k) for k in keys} == wanted
                        for keys in order.values()):
                    return {uri: [tuple(k) for k in keys]
                            for uri, keys in order.items()}
        out: dict = {}
        for parameter in parameters:
            sentences = list(self.probes(parameter, plan.document_id) or ()) \
                or [parameter.label]
            out[parameter.uri] = [c.key for c in self.order(
                plan.document_id, sentences, chunks)]
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
