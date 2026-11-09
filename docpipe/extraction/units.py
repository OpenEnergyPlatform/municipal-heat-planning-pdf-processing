"""
units.py: A plan's passages as numbered lines, cut into pieces of at most
eight lines (owner decisions 2026-11-08 evening, both profiles).

Every request of the harvest shows lines with their numbers and the model
answers with an address, never with a copied quote: a line is `19`, a cell
of a table row `19.5` (line 19, cell 5), a stretch of lines `12-14`. What a
number names is code's to look up: the line's text is the quote, the head
of a cell's column its `head`, the passage and the page where it stands.

A section is cut first at its line ends, then at its sentence ends, a
heading a line of its own; an abbreviation ("z. B.", "S. 12", "et al.") and
an ordinal ("3. Oktober") end no sentence, and a number ("1.155 MWh") never
breaks, since a sentence ends only where a mark is followed by a space. A
table is its title lines, its head lines and its body rows, numbered in that
order from 1 (the rule under the head counts not), each body row a line
whose cells are numbered from 1; lines under the table are lines as well.
Any line that "|" divides has cells, wherever it stands: a table row, a
figure's line, a sentence (owner decision 2026-11-09). A figure is the
lines a model transcribed it into once (`transcripts`): its caption (title,
axes, legend) and its numbers, each a line of its own; else the lines of
its description.

A piece (`Chunk`) is at most `CHUNK_UNITS` lines of its passage, a table's
title and head lines shown with every piece of it under the same numbers. A
figure with numbers is one piece of its caption and pieces of its numbers,
each shown with the caption; a field whose values are no numbers reads only
the caption, a field of numbers only the pieces of numbers (`pieces_for`).
Every line of a passage keeps one number in every request that shows it.

A request shows besides its own passage other blocks of lines, each under a
letter of its own so that no two lines of a request share an address: the
title page `T`, the headings up to a place `H`, the plan's settings `F`, and
any other passage `A`, `B`, ... (`Shown`).

Author: Felix Vossel
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Optional

from .pipeline import Source
from .verify import flat

# Lines of a piece (owner decision 2026-11-08, f: 8, and 12 measured only
# where a probe loses values against the runs before).
CHUNK_UNITS = 8
# Lines of the plan's first page a request shows as its title page.
TITLE_PAGE_LINES = 12

# The letters of the blocks a request shows beside its own passage.
TITLE_PAGE = "T"
HEADINGS = "H"
SETTINGS = "F"
RESERVED = (TITLE_PAGE, HEADINGS, SETTINGS)
OTHERS = tuple(letter for letter in "ABCDEGIJKLMNOPQRSUVWXYZ"
               if letter not in RESERVED)
# The role of a line that is one number a figure shows.
NUMBER_LINE = "number"

# Abbreviations whose point ends no sentence, both languages, written as
# the plan prints them; matched at the end of the text before a break.
ABBREVIATIONS = (
    "z. B.", "z.B.", "u. a.", "u.a.", "d. h.", "d.h.", "i. d. R.", "o. ä.",
    "ca.", "Abb.", "Tab.", "Nr.", "Nrn.", "bzw.", "vgl.", "S.", "Kap.",
    "Abs.", "Anh.", "Bd.", "Hrsg.", "ggf.", "evtl.", "inkl.", "zzgl.",
    "exkl.", "bspw.", "usw.", "etc.", "Mio.", "Mrd.", "Tsd.", "rd.", "max.",
    "min.", "Dr.", "Prof.", "Dipl.", "Ing.", "St.", "Str.", "jährl.", "gem.",
    "lt.", "e.g.", "i.e.", "e. g.", "i. e.", "Fig.", "Figs.", "et al.",
    "approx.", "cf.", "vs.", "No.", "Nos.", "Eq.", "Sec.", "Ch.", "pp.",
    "p.", "Vol.", "Ref.", "resp.", "incl.", "Jan.", "Feb.", "Mar.", "Apr.",
    "Aug.", "Sep.", "Sept.", "Oct.", "Okt.", "Nov.", "Dec.", "Dez.")
_ABBREVIATION_ENDS = tuple(sorted({flat(a) for a in ABBREVIATIONS},
                                  key=len, reverse=True))
# A mark that ends a sentence with what closes it, a space, and what may
# begin the next one.
_SENTENCE_END = re.compile(r"(?<=[.!?])([\"'”“»)\]]*)\s+(?=[\"'„“«(\[•▪●◦\-–]?"
                           r"[A-ZÄÖÜ0-9])")
# A list item a transcription runs into the text before it.
_BULLET = re.compile(r"\s+(?=[•▪●◦]\s)")
# An ordinal or a numbered heading before a point: "3." "12." ends nothing.
_ORDINAL = re.compile(r"(?:^|\s)\d{1,3}\.$")
# A line of a Markdown table and the rule under its head.
_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RULE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
# An address as a model writes it: an optional block letter, a line, an
# optional cell, an optional last line of a stretch.
_ADDRESS = re.compile(r"^\s*([A-Z])?\s*(\d+)(?:\.(\d+))?"
                      r"(?:\s*[-–]\s*([A-Z])?\s*(\d+))?\s*$")


def ends_abbreviated(text: str, after: str = "") -> bool:
    """Does *text* end with an abbreviation or an ordinal, whose point ends
    no sentence? *after* is what follows the break, which completes an
    abbreviation of two parts ("z." and "B.")."""
    tail = flat(text)
    if _ORDINAL.search(tail):
        return True
    word = flat(after).split(" ", 1)[0] if after else ""
    for abbreviation in _ABBREVIATION_ENDS:
        whole = tail
        if word and " " in abbreviation \
                and abbreviation.rsplit(" ", 1)[1] == word:
            # The break stands inside it: its first part ends *text*.
            whole = f"{tail} {word}"
        if whole.endswith(abbreviation):
            before = whole[:-len(abbreviation)]
            if not before or not before[-1].isalnum():
                return True
    return False


def sentences_of(text: str) -> list:
    """*text* cut at its line ends, then at its sentence ends and before a
    list item it runs on into: every piece a line, none empty."""
    out: list = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        for item in _BULLET.split(line.strip()):
            start = 0
            for match in _SENTENCE_END.finditer(item):
                if ends_abbreviated(item[start:match.start()],
                                    item[match.end():match.end() + 12]):
                    continue
                end = match.start() + len(match.group(1))
                piece = item[start:end].strip()
                if piece:
                    out.append(piece)
                start = match.end()
            piece = item[start:].strip()
            if piece:
                out.append(piece)
    return out


def cells_of(line: str) -> tuple:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def line_cells(text: str) -> tuple:
    """The cells of a line that "|" divides, wherever it stands (owner
    decision 2026-11-09: "26 JRC GECO 1.5C | Other | 11 (read off)" is
    addressed as 26.1 to 26.3 like a table row); () for a line of fewer
    than two."""
    if "|" not in (text or ""):
        return ()
    cells = cells_of(text)
    return cells if len(cells) > 1 else ()


@dataclass(frozen=True)
class Line:
    """One numbered line of a passage: a sentence, a heading, a table's
    title, head or body row, a line under a table, a line of a figure's
    caption or one of its numbers."""
    number: int
    text: str
    cells: tuple = ()
    # "text", "title", "head", "body", "foot", "figure", "number"
    role: str = "text"


@dataclass
class Passage:
    """A passage as numbered lines. *source* is what a value read from it
    is checked against: the passage itself, a figure as its transcription.
    *fixed* are the lines every piece of it shows (a table's title and
    head, a figure's title)."""
    source: Source
    lines: list
    fixed: tuple = ()
    drawn: bool = False

    @property
    def owner(self) -> tuple:
        return (self.source.owner_kind, self.source.owner_id)

    @property
    def kind(self) -> str:
        return self.source.owner_kind

    @property
    def page(self) -> Optional[int]:
        page = (self.source.provenance or {}).get("page")
        return page if isinstance(page, int) else None

    @property
    def has_numbers(self) -> bool:
        """Is this a figure transcribed with its numbers, each a line?"""
        return any(line.role == NUMBER_LINE for line in self.lines)

    @property
    def title(self) -> str:
        """The table's or figure's title line, the section's heading."""
        if self.fixed:
            return self.line(self.fixed[0]).text
        return (self.source.provenance or {}).get("section_title") or ""

    def line(self, number: int) -> Optional[Line]:
        if 1 <= number <= len(self.lines):
            return self.lines[number - 1]
        return None

    def head_of(self, cell: int) -> Optional[str]:
        """The words over *cell* of a body row, top first, each once, from
        the head lines with as many cells as the rows: None where none."""
        widths = {len(line.cells) for line in self.lines
                  if line.role == "body"}
        words: list = []
        for line in self.lines:
            if line.role != "head" or len(line.cells) not in widths:
                continue
            if 0 < cell <= len(line.cells) and line.cells[cell - 1] \
                    and line.cells[cell - 1] not in words:
                words.append(line.cells[cell - 1])
        return " / ".join(words) or None


def table_lines(text: str) -> Optional[tuple]:
    """([Line], fixed) of a table's text, None where it holds no Markdown
    table with a rule under its head."""
    raw = [line for line in (text or "").splitlines() if line.strip()]
    at = next((i for i, line in enumerate(raw)
               if _RULE.match(line) and "-" in line and i > 0
               and _ROW.match(raw[i - 1])), None)
    if at is None:
        return None
    lines: list = []
    fixed: list = []
    head_start = at
    while head_start > 0 and _ROW.match(raw[head_start - 1]):
        head_start -= 1
    for line in raw[:head_start]:
        for sentence in sentences_of(line):
            lines.append(Line(len(lines) + 1, sentence, line_cells(sentence),
                              "title"))
            fixed.append(len(lines))
    for line in raw[head_start:at]:
        lines.append(Line(len(lines) + 1, line.strip(), cells_of(line),
                          "head"))
        fixed.append(len(lines))
    after = False
    for line in raw[at + 1:]:
        if _ROW.match(line) and not after:
            if _RULE.match(line):
                continue
            lines.append(Line(len(lines) + 1, line.strip(), cells_of(line),
                              "body"))
            continue
        after = True
        for sentence in sentences_of(line):
            lines.append(Line(len(lines) + 1, sentence, line_cells(sentence),
                              "foot"))
    if not any(line.role == "body" for line in lines):
        return None
    return lines, tuple(fixed)


def figure_lines(transcript) -> tuple:
    """([caption lines], [number lines]) of a figure's transcription
    (`addressed.Transcripts`, owner decision 2026-11-09): its title, axes
    and legend, and each number it shows; a transcription that is one list
    is all caption."""
    if isinstance(transcript, dict):
        caption = transcript.get("caption")
        numbers = transcript.get("numbers")
    else:
        caption, numbers = transcript, ()

    def clean(texts) -> list:
        return [text.strip() for text in (texts or ())
                if isinstance(text, str) and text.strip()]
    return clean(caption), clean(numbers)


def passage_of(source: Source, transcript=None) -> Passage:
    """*source* as numbered lines: a table's title, head and rows, a
    figure's transcribed lines (*transcript*, `figure_lines`: its caption,
    its title first, then its numbers), else its sentences. The caption of
    a figure with numbers is shown with every piece of it, as a table's
    title and head are."""
    if source.owner_kind == "table":
        got = table_lines(source.text)
        if got is not None:
            return Passage(source, got[0], got[1])
    if source.owner_kind == "figure":
        caption, numbers = figure_lines(transcript)
        if caption or numbers:
            lines = [Line(i, text, line_cells(text), "figure")
                     for i, text in enumerate(caption, start=1)]
            lines += [Line(len(caption) + i, text, line_cells(text),
                           NUMBER_LINE)
                      for i, text in enumerate(numbers, start=1)]
            if numbers:
                fixed = tuple(range(1, len(caption) + 1))
            else:
                fixed = (1,) if caption else ()
            # What a value read from it stands in: its transcription.
            seen = replace(source, text="\n".join(caption + numbers),
                           body=None)
            return Passage(seen, lines, fixed, drawn=True)
        lines = [Line(i, text, line_cells(text), "figure") for i, text
                 in enumerate(sentences_of(source.text), start=1)]
        return Passage(source, lines, (1,) if lines else (), drawn=True)
    lines = [Line(i, text, line_cells(text)) for i, text
             in enumerate(sentences_of(source.text), start=1)]
    return Passage(source, lines)


class Chunk:
    """A piece of a passage: its own lines (*numbers*), shown with the
    lines every piece of the passage shows. Two pieces are the same piece
    where their passage and place are the same (`key`)."""

    def __init__(self, passage: Passage, index: int, numbers: tuple):
        self.passage = passage
        self.index = index
        self.numbers = tuple(numbers)

    def __repr__(self) -> str:
        return f"Chunk({self.key}, {self.numbers})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Chunk) and other.key == self.key

    def __hash__(self) -> int:
        return hash(self.key)

    @property
    def owner(self) -> tuple:
        return self.passage.owner

    @property
    def key(self) -> tuple:
        """What names the piece in a document: its passage and place."""
        return (*self.passage.owner, self.index)

    @property
    def shown(self) -> tuple:
        """Every line number the piece shows, in order."""
        return tuple(sorted(set(self.passage.fixed) | set(self.numbers)))

    def lines(self) -> list:
        return [self.passage.line(n) for n in self.shown]

    def text(self) -> str:
        """Its lines as the reranker reads them, without numbers."""
        return "\n".join(line.text for line in self.lines())

    @property
    def of_numbers(self) -> bool:
        """Is this a piece of a figure's numbers?"""
        return bool(self.numbers) and self.passage.has_numbers

    @property
    def of_caption(self) -> bool:
        """Is this the piece of a figure's caption alone, beside the pieces
        of its numbers?"""
        return not self.numbers and self.passage.has_numbers


def chunks_of(passage: Passage, size: int = CHUNK_UNITS) -> list:
    """The pieces of *passage*: its lines but the fixed ones, *size* at a
    time, in order; a passage of fixed lines only is one piece. A figure
    with numbers is first the piece of its caption, then the pieces of its
    numbers, each shown with the caption."""
    size = max(1, int(size))
    own = [line.number for line in passage.lines
           if line.number not in passage.fixed]
    if not own:
        return [Chunk(passage, 0, ())] if passage.lines else []
    first = 1 if passage.has_numbers and passage.fixed else 0
    pieces = [Chunk(passage, first + i, tuple(own[start:start + size]))
              for i, start in enumerate(range(0, len(own), size))]
    return ([Chunk(passage, 0, ())] if first else []) + pieces


def pieces_for(chunks: list, numbers: bool) -> list:
    """The pieces a field reads, in their order (owner decision 2026-11-09):
    a field whose values are numbers reads a figure in the pieces of its
    numbers, each shown with the caption; any other field reads it in the
    piece of its caption alone (title, axes, legend), whose names its
    numbers only repeat."""
    if numbers:
        return [chunk for chunk in chunks if not chunk.of_caption]
    return [chunk for chunk in chunks if not chunk.of_numbers]


def neighbours(chunks: list, chunk: Chunk) -> list:
    """The pieces right before and after *chunk* among a document's
    *chunks* in reading order, the one before first."""
    at = next((i for i, one in enumerate(chunks) if one.key == chunk.key),
              None)
    if at is None:
        return []
    return [chunks[i] for i in (at - 1, at + 1) if 0 <= i < len(chunks)]


def rendered(line: Line, letter: str = "") -> str:
    """A line as a request shows it: its address, a space, its text."""
    return f"{letter}{line.number} {line.text}"


@dataclass(frozen=True)
class Address:
    """What a model's address names: a block's letter ("" for the
    request's own passage), a line, a cell, and the last line of a
    stretch."""
    letter: str
    line: int
    cell: Optional[int] = None
    last: Optional[int] = None


def address_of(raw) -> Optional[Address]:
    """*raw* ("19.5", "T3", "12-14", 19) as an Address, None where it is
    none. 0 is no address: the answer that nothing shown says it."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Address("", raw) if raw > 0 else None
    if not isinstance(raw, str):
        return None
    match = _ADDRESS.match(raw)
    if not match:
        return None
    letter, line, cell, other, last = match.groups()
    if other and other != (letter or ""):
        return None
    line = int(line)
    if line <= 0:
        return None
    last = int(last) if last else None
    if last is not None and (last < line or cell):
        return None
    return Address(letter or "", line, int(cell) if cell else None, last)


@dataclass
class Block:
    """Lines a request shows under one letter: each the number it is shown
    under, the line of its passage and the passage a quote of it cites."""
    letter: str
    label: str
    entries: list         # [(shown number, Line, Source)]

    @property
    def lines(self) -> list:
        return [(line, source) for _, line, source in self.entries]

    def rendered(self) -> list:
        return [f"{self.letter}{number} {line.text}"
                for number, line, _ in self.entries]


@dataclass
class Shown:
    """Everything a request shows as lines, by letter: its own passage
    under "" and every other block under a letter of its own, so that each
    address names one line. A block of lines from several passages (the
    title page, the headings, the settings) is shown numbered from 1; a
    passage under its own numbers."""
    blocks: dict = field(default_factory=dict)

    def add(self, letter: str, label: str, lines: list,
            renumber: bool = False) -> None:
        if not lines:
            return
        held = self.blocks.get(letter)
        entries = list(held.entries) if held else []
        have = {(line.number, source.owner_kind, source.owner_id)
                for _, line, source in entries}
        for line, source in lines:
            if not renumber and (line.number, source.owner_kind,
                                 source.owner_id) in have:
                continue
            number = len(entries) + 1 if renumber else line.number
            entries.append((number, line, source))
        if not renumber:
            entries.sort(key=lambda entry: entry[0])
        self.blocks[letter] = Block(letter, label, entries)

    def letter_for(self, owner: tuple) -> str:
        """The letter of another passage's block: its own where it has one,
        else the next free one."""
        for letter, block in self.blocks.items():
            if letter in OTHERS and block.entries \
                    and (block.entries[0][2].owner_kind,
                         block.entries[0][2].owner_id) == tuple(owner):
                return letter
        return next(letter for letter in OTHERS
                    if letter not in self.blocks)

    def rendered(self, letter: str) -> list:
        block = self.blocks.get(letter)
        return block.rendered() if block else []

    def find(self, address: Address) -> Optional[tuple]:
        """(Line, Source) the address names, None where it names no shown
        line."""
        block = self.blocks.get(address.letter)
        if block is None:
            return None
        return next(((line, source) for number, line, source in block.entries
                     if number == address.line), None)

    def around(self, address: Address, minimum: int) -> list:
        """[(Line, Source)] a quote of *address* is: the lines it names,
        and where they are shorter than *minimum*, the shown lines of the
        same passage before them, else after them (as `short_quote` for a
        value)."""
        named = self.stretch(address)
        block = self.blocks.get(address.letter)
        if not named or block is None:
            return named
        owner = (named[0][1].owner_kind, named[0][1].owner_id)
        same = [(number, line, source) for number, line, source
                in block.entries
                if (source.owner_kind, source.owner_id) == owner]
        numbers = [number for number, _, _ in same]
        if address.line not in numbers \
                or (address.last or address.line) not in numbers:
            return named
        first = numbers.index(address.line)
        last = numbers.index(address.last or address.line)
        out = list(named)

        def short() -> bool:
            return len(" ".join(line.text for line, _ in out)) < minimum
        while short() and first > 0:
            first -= 1
            out.insert(0, same[first][1:])
        while short() and last + 1 < len(numbers):
            last += 1
            out.append(same[last][1:])
        return out

    def stretch(self, address: Address) -> list:
        """[(Line, Source)] of a stretch of lines, [] where one of them is
        not shown."""
        last = address.last or address.line
        got = []
        for number in range(address.line, last + 1):
            one = self.find(Address(address.letter, number))
            if one is None:
                return []
            got.append(one)
        return got

    def evidence(self) -> list:
        """What a quote may stand in, each citing the passage it comes
        from: every shown line, and the shown lines of one passage in a
        block together, for a quote of several of them (a stretch, or a
        short line with the lines around it)."""
        out = [replace(source, text=line.text, body=None)
               for block in self.blocks.values()
               for _, line, source in block.entries]
        for block in self.blocks.values():
            runs: dict = {}
            for _, line, source in block.entries:
                runs.setdefault((source.owner_kind, source.owner_id),
                                (source, []))[1].append(line.text)
            out += [replace(source, text=" ".join(texts), body=None)
                    for source, texts in runs.values() if len(texts) > 1]
        return out


def own_lines(chunk: Chunk) -> list:
    """[(Line, Source)] of a piece's shown lines."""
    return [(line, chunk.passage.source) for line in chunk.lines()]


def passage_lines(passage: Passage, numbers) -> list:
    """[(Line, Source)] of *numbers* of a passage, its fixed lines first."""
    wanted = sorted(set(passage.fixed) | {n for n in numbers
                                         if passage.line(n) is not None})
    return [(passage.line(n), passage.source) for n in wanted]


def title_page_of(passages: list, count: int = TITLE_PAGE_LINES) -> list:
    """[(Line, Source)] of the plan's title page: the first *count* lines
    of its first page, else of its second, each the line of its passage
    (`Passage`), in the plan's order; [] for a plan with no page."""
    for page in (1, 2):
        lines: list = []
        for passage in passages:
            if passage.page != page or passage.kind == "figure":
                continue
            for line in passage.lines:
                lines.append((line, passage.source))
                if len(lines) >= count:
                    return lines
        if lines:
            return lines
    return []


def short_quote(passage: Passage, numbers: list, minimum: int) -> str:
    """The quote of lines *numbers* of *passage*: their text, and where it
    is shorter than *minimum*, the lines before it as well, and after it
    where none are before, so that a quote names a place."""
    texts = [passage.line(n).text for n in numbers if passage.line(n)]
    first = min(numbers) if numbers else 1
    last = max(numbers) if numbers else 0
    while len(" ".join(texts)) < minimum and first > 1:
        first -= 1
        texts.insert(0, passage.line(first).text)
    while len(" ".join(texts)) < minimum and passage.line(last + 1):
        last += 1
        texts.append(passage.line(last).text)
    return " ".join(texts) if passage.kind != "table" \
        else "\n".join(texts)
