# docpipe.extraction.units

`docpipe/extraction/units.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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
whose cells are numbered from 1; lines under the table are lines as well. A
figure is the lines a model transcribed it into once, its title first
(`transcripts`), else the lines of its description.

A piece (`Chunk`) is at most `CHUNK_UNITS` lines of its passage, a table's
title and head lines shown with every piece of it under the same numbers, a
figure's title line likewise. Every line of a passage keeps one number in
every request that shows it.

A request shows besides its own passage other blocks of lines, each under a
letter of its own so that no two lines of a request share an address: the
title page `T`, the headings up to a place `H`, the plan's settings `F`, and
any other passage `A`, `B`, ... (`Shown`).

Author: Felix Vossel

## Classes

### Line

```python
@dataclass(frozen=True)
class Line
```

One numbered line of a passage: a sentence, a heading, a table's
title, head or body row, a line under a table, or a figure's line.

Fields:

- `number: int`
- `text: str`
- `cells: tuple = ()`
- `role: str = "text"`: "text", "title", "head", "body", "foot", "figure"

### Passage

```python
@dataclass
class Passage
```

A passage as numbered lines. *source* is what a value read from it
is checked against: the passage itself, a figure as its transcription.
*fixed* are the lines every piece of it shows (a table's title and
head, a figure's title).

Fields:

- `source: Source`
- `lines: list`
- `fixed: tuple = ()`
- `drawn: bool = False`

#### Passage.owner

```python
@property
def owner(self) -> tuple
```

#### Passage.kind

```python
@property
def kind(self) -> str
```

#### Passage.page

```python
@property
def page(self) -> Optional[int]
```

#### Passage.title

```python
@property
def title(self) -> str
```

The table's or figure's title line, the section's heading.

#### Passage.line

```python
def line(self, number: int) -> Optional[Line]
```

#### Passage.head_of

```python
def head_of(self, cell: int) -> Optional[str]
```

The words over *cell* of a body row, top first, each once, from
the head lines with as many cells as the rows: None where none.

### Chunk

```python
class Chunk
```

A piece of a passage: its own lines (*numbers*), shown with the
lines every piece of the passage shows. Two pieces are the same piece
where their passage and place are the same (`key`).

#### Chunk.\_\_init\_\_

```python
def __init__(self, passage: Passage, index: int, numbers: tuple)
```

#### Chunk.owner

```python
@property
def owner(self) -> tuple
```

#### Chunk.key

```python
@property
def key(self) -> tuple
```

What names the piece in a document: its passage and place.

#### Chunk.shown

```python
@property
def shown(self) -> tuple
```

Every line number the piece shows, in order.

#### Chunk.lines

```python
def lines(self) -> list
```

#### Chunk.text

```python
def text(self) -> str
```

Its lines as the reranker reads them, without numbers.

### Address

```python
@dataclass(frozen=True)
class Address
```

What a model's address names: a block's letter ("" for the
request's own passage), a line, a cell, and the last line of a
stretch.

Fields:

- `letter: str`
- `line: int`
- `cell: Optional[int] = None`
- `last: Optional[int] = None`

### Block

```python
@dataclass
class Block
```

Lines a request shows under one letter: each the number it is shown
under, the line of its passage and the passage a quote of it cites.

Fields:

- `letter: str`
- `label: str`
- `entries: list`: [(shown number, Line, Source)]

#### Block.lines

```python
@property
def lines(self) -> list
```

#### Block.rendered

```python
def rendered(self) -> list
```

### Shown

```python
@dataclass
class Shown
```

Everything a request shows as lines, by letter: its own passage
under "" and every other block under a letter of its own, so that each
address names one line. A block of lines from several passages (the
title page, the headings, the settings) is shown numbered from 1; a
passage under its own numbers.

Fields:

- `blocks: dict = field(default_factory=dict)`

#### Shown.add

```python
def add(self, letter: str, label: str, lines: list,
        renumber: bool = False) -> None
```

#### Shown.letter_for

```python
def letter_for(self, owner: tuple) -> str
```

The letter of another passage's block: its own where it has one,
else the next free one.

#### Shown.rendered

```python
def rendered(self, letter: str) -> list
```

#### Shown.find

```python
def find(self, address: Address) -> Optional[tuple]
```

(Line, Source) the address names, None where it names no shown
line.

#### Shown.around

```python
def around(self, address: Address, minimum: int) -> list
```

[(Line, Source)] a quote of *address* is: the lines it names,
and where they are shorter than *minimum*, the shown lines of the
same passage before them, else after them (as `short_quote` for a
value).

#### Shown.stretch

```python
def stretch(self, address: Address) -> list
```

[(Line, Source)] of a stretch of lines, [] where one of them is
not shown.

#### Shown.evidence

```python
def evidence(self) -> list
```

What a quote may stand in, each citing the passage it comes
from: every shown line, and the shown lines of one passage in a
block together, for a quote of several of them (a stretch, or a
short line with the lines around it).

## Functions

### ends_abbreviated

```python
def ends_abbreviated(text: str, after: str = "") -> bool
```

Does *text* end with an abbreviation or an ordinal, whose point ends
no sentence? *after* is what follows the break, which completes an
abbreviation of two parts ("z." and "B.").

### sentences_of

```python
def sentences_of(text: str) -> list
```

*text* cut at its line ends, then at its sentence ends and before a
list item it runs on into: every piece a line, none empty.

### cells_of

```python
def cells_of(line: str) -> tuple
```

### table_lines

```python
def table_lines(text: str) -> Optional[tuple]
```

([Line], fixed) of a table's text, None where it holds no Markdown
table with a rule under its head.

### passage_of

```python
def passage_of(source: Source, transcript: Optional[list] = None) -> Passage
```

*source* as numbered lines: a table's title, head and rows, a
figure's transcribed lines (*transcript*, its title first), else its
sentences.

### chunks_of

```python
def chunks_of(passage: Passage, size: int = CHUNK_UNITS) -> list
```

The pieces of *passage*: its lines but the fixed ones, *size* at a
time, in order; a passage of fixed lines only is one piece.

### neighbours

```python
def neighbours(chunks: list, chunk: Chunk) -> list
```

The pieces right before and after *chunk* among a document's
*chunks* in reading order, the one before first.

### rendered

```python
def rendered(line: Line, letter: str = "") -> str
```

A line as a request shows it: its address, a space, its text.

### address_of

```python
def address_of(raw) -> Optional[Address]
```

*raw* ("19.5", "T3", "12-14", 19) as an Address, None where it is
none. 0 is no address: the answer that nothing shown says it.

### own_lines

```python
def own_lines(chunk: Chunk) -> list
```

[(Line, Source)] of a piece's shown lines.

### passage_lines

```python
def passage_lines(passage: Passage, numbers) -> list
```

[(Line, Source)] of *numbers* of a passage, its fixed lines first.

### title_page_of

```python
def title_page_of(passages: list, count: int = TITLE_PAGE_LINES) -> list
```

[(Line, Source)] of the plan's title page: the first *count* lines
of its first page, else of its second, each the line of its passage
(`Passage`), in the plan's order; [] for a plan with no page.

### short_quote

```python
def short_quote(passage: Passage, numbers: list, minimum: int) -> str
```

The quote of lines *numbers* of *passage*: their text, and where it
is shorter than *minimum*, the lines before it as well, and after it
where none are before, so that a quote names a place.

[Back to the index](../README.md)
