"""
units.py: A plan's passages as numbered lines, cut into pieces of at most
as many lines as the flow says (`flow.Numbers.piece_lines`, eight by
default; owner decisions 2026-11-08 evening, both profiles).

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

A piece (`Chunk`) is at most as many lines of its passage as the run's flow
says (`flow.Numbers.piece_lines`), a table's
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

import json
import re
from dataclasses import dataclass, field, replace
from typing import Optional

from .. import rules
from .pipeline import Source
from .verify import flat

# How many lines a piece holds and how many lines of the plan's first page
# are its title page are numbers of the flow (`flow.Numbers.piece_lines`,
# `title_page_lines`; owner decision 2026-11-08, f: 8 lines, and 12 measured
# only where a probe loses values against the runs before).

# The letters of the blocks a request shows beside its own passage, and the
# letters of other passages, in order (rules `letter_title_page`,
# `letter_headings`, `letter_settings`, `letters_others`).
def letter_title_page() -> str:
    return rules.get("letter_title_page")


def letter_headings() -> str:
    return rules.get("letter_headings")


def letter_settings() -> str:
    return rules.get("letter_settings")


def letters_others() -> tuple:
    reserved = (letter_title_page(), letter_headings(), letter_settings())
    return tuple(letter for letter in rules.get("letters_others")
                 if letter not in reserved)


# The role of a line that is one number a figure shows.
NUMBER_LINE = "number"


def _abbreviation_ends() -> tuple:
    """The abbreviations whose point ends no sentence (rule
    `abbreviations`, both languages, written as the plan prints them),
    longest first, matched at the end of the text before a break."""
    return rules.derived("units.abbreviations", lambda: tuple(sorted(
        {flat(a) for a in rules.get("abbreviations")}, key=len,
        reverse=True)))


def _sentence_end():
    """A mark that ends a sentence (rule `sentence_marks`) with what closes
    it, a space, and what may begin the next one."""
    return rules.derived("units.sentence_end", lambda: re.compile(
        r"(?<=[" + re.escape(rules.get("sentence_marks")) + r"])"
        r"([\"'”“»)\]]*)\s+(?=[\"'„“«(\[•▪●◦\-–]?"
        r"[A-ZÄÖÜ0-9])"))


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
    for abbreviation in _abbreviation_ends():
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
            for match in _sentence_end().finditer(item):
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
        return rules.get("head_joiner").join(words) or None


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
    lines every piece of the passage shows (*carried*, the passage's fixed
    lines where not given). Two pieces are the same piece where their
    passage and place are the same (`key`)."""

    def __init__(self, passage: Passage, index: int, numbers: tuple,
                 carried: Optional[tuple] = None):
        self.passage = passage
        self.index = index
        self.numbers = tuple(numbers)
        self.carried = None if carried is None else tuple(carried)

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
        carried = self.passage.fixed if self.carried is None \
            else self.carried
        return tuple(sorted(set(carried) | set(self.numbers)))

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


def chunks_of(passage: Passage, size: int) -> list:
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


@dataclass(frozen=True)
class Cut:
    """How a flow's split box cuts a document (`blocks.LIBRARY["split"]`):
    a piece holds at most *lines* lines; a new piece begins where a passage
    begins, unless a piece may hold several (*across*), and where the
    condition *new_piece* holds for the next line (`conditions`, the line's
    properties of `line_facts`). A table's title and head go with each of
    its pieces (*table_head*), a figure's caption with each of its pieces
    (*caption*); a figure's numbers are pieces of their own, its caption
    one (*figure_numbers*). *headings* is how many headings a request shows
    up to a place."""
    lines: int = 8
    new_piece: Optional[dict] = None
    across: bool = False
    table_head: bool = True
    caption: bool = True
    figure_numbers: bool = True
    headings: int = 10

    def plain(self) -> bool:
        """Is this the cut of every flow before 2026-11-11: pieces of at
        most *lines* lines of one passage, heads and captions carried?"""
        return (self.new_piece is None and not self.across
                and self.table_head and self.caption
                and self.figure_numbers)

    def key(self):
        """What an order of the pieces is kept under (`addressed.order_key`):
        the lines of a piece for the plain cut, as before, else every
        setting."""
        if self.plain():
            return self.lines
        return json.dumps({"lines": self.lines, "new_piece": self.new_piece,
                           "across": self.across,
                           "table_head": self.table_head,
                           "caption": self.caption,
                           "figure_numbers": self.figure_numbers},
                          sort_keys=True, ensure_ascii=False)


def line_facts(passage: Passage, line: Line, first: bool,
               page_before: Optional[int], in_piece: int):
    """What a condition of the split box knows of the next line
    (`conditions.SUBJECTS["line"]`)."""
    from .conditions import Facts
    heading = line.role == "title" or (first and passage.kind == "section"
                                       and bool(passage.title))
    values = {"heading": heading, "passage_begins": first,
              "table_begins": first and passage.kind == "table",
              "figure_begins": first and passage.kind == "figure",
              "new_page": first and passage.page is not None
              and page_before is not None and passage.page != page_before,
              "role": "heading" if heading and line.role == "text"
              else line.role,
              "lines_in_piece": in_piece}

    def get(subject: str, prop: str):
        if subject != "line":
            raise LookupError(f"{subject} is not known while cutting")
        return values[prop]
    return Facts(get)


def cut_pieces(passages: list, cut: Cut) -> tuple:
    """([Chunk] in reading order, [group]) of *passages* cut as *cut*
    says. A group is a tuple of the chunks of one piece that holds lines of
    several passages, each chunk the lines of one of them; a piece of one
    passage is a chunk alone. The plain cut is `chunks_of`, passage by
    passage."""
    if cut.plain():
        return [c for p in passages for c in chunks_of(p, cut.lines)], []
    from .conditions import holds
    size = max(1, int(cut.lines))
    chunks: list = []
    groups: list = []
    index: dict = {}
    current: list = []          # [(passage, [line numbers])]

    def carried_of(passage: Passage) -> tuple:
        if passage.kind == "table" and not cut.table_head:
            return ()
        if passage.kind == "figure" and not cut.caption:
            return ()
        return passage.fixed

    def close() -> None:
        made = []
        for passage, numbers in current:
            if not numbers:
                continue
            at = index.get(passage.owner, 0)
            index[passage.owner] = at + 1
            made.append(Chunk(passage, at, tuple(numbers),
                              carried_of(passage)))
        current.clear()
        chunks.extend(made)
        if len(made) > 1:
            groups.append(tuple(made))

    in_piece = 0
    page_before = None
    for passage in passages:
        carried = carried_of(passage)
        own = [line for line in passage.lines
               if line.number not in carried]
        alone = passage.has_numbers and cut.figure_numbers
        if alone:
            # A figure's caption a piece of its own, its numbers pieces of
            # their own, each shown with the caption.
            close()
            in_piece = 0
            at = index.get(passage.owner, 0)
            if passage.fixed:
                chunks.append(Chunk(passage, at, () if carried
                                    else tuple(passage.fixed), carried))
                at += 1
            numbers = [line.number for line in own
                       if line.number not in passage.fixed]
            for start in range(0, len(numbers), size):
                chunks.append(Chunk(passage, at, tuple(
                    numbers[start:start + size]), carried))
                at += 1
            index[passage.owner] = at
            page_before = passage.page
            continue
        if not own:
            if carried:
                close()
                at = index.get(passage.owner, 0)
                chunks.append(Chunk(passage, at, (), carried))
                index[passage.owner] = at + 1
                in_piece = 0
            page_before = passage.page
            continue
        for i, line in enumerate(own):
            first = i == 0
            new = in_piece >= size
            if first and not cut.across:
                new = True
            if not new and cut.new_piece is not None and in_piece:
                new = holds(cut.new_piece, line_facts(
                    passage, line, first, page_before, in_piece))
            if new and in_piece:
                close()
                in_piece = 0
            if not current or current[-1][0] is not passage:
                current.append((passage, []))
            current[-1][1].append(line.number)
            in_piece += 1
        page_before = passage.page
        if not cut.across:
            close()
            in_piece = 0
    close()
    return chunks, groups


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
            if letter in letters_others() and block.entries \
                    and (block.entries[0][2].owner_kind,
                         block.entries[0][2].owner_id) == tuple(owner):
                return letter
        return next(letter for letter in letters_others()
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


def title_page_of(passages: list, count: int) -> list:
    """[(Line, Source)] of the plan's title page: the first *count* lines
    of its first page, else of the page the rule `title_page_also` names,
    each the line of its passage (`Passage`), in the plan's order; [] for a
    plan with no page."""
    for page in dict.fromkeys((1, rules.get("title_page_also"))):
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
