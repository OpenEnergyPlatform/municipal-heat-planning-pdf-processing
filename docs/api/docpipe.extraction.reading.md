# docpipe.extraction.reading

`docpipe/extraction/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: The values of one parameter in the passages the survey named for
it, every coordinate of a value in the same request.

Step 3 of the rebuilt harvest (owner decision 2026-11-04). A table is read as
one unit: one request says which of its columns and rows hold the
parameter's values and where each coordinate stands, at a row label, a
column head or for the whole table, each with its quote. Code then makes one
row per number of a cell and reads the number by its place, never by its
value: a table row "27 % | 28 % | 27 % | 23 %" gives each 27 % its own column.
A cell may print several numbers, a value with its share in brackets or
values stacked in one cell (owner decision 2026-11-04): the reply says how
many numbers the cells of such a column print and which of them are values
of the parameter, and a number's place is then its row, its column and its
place in the cell, a coordinate answered for that place alone. A section or
a figure is read in one request that names its values with every coordinate
at once, each with its own quote.

Every coordinate is answered: the grammar requires each of them, a value's
entry in text and a table's entry for the whole table, and "the passage does
not say" is one of the answers (`fields.UNSTATED`). One request for all
coordinates is otherwise the request that lets a model drop the one it is
unsure of (fields.py).

Nothing is checked here. Every coordinate goes through `pipeline.merge_field`,
the check every field answer of the harvest goes through, and every value
through `fold_batch`. What that check refuses is asked once more, with the
reason it was refused for, as the harvest asks a failed field answer again;
a coordinate the reply left out is asked for by name. A frame coordinate the
passage leaves open is taken from the survey's tuple of the passage, with its
quote, where the survey named one (window `frame`). A coordinate no reply
answered ends `unanswered`.

Author: Felix Vossel

## Classes

### Grid

```python
@dataclass
class Grid
```

A transcribed table: its head lines and its body rows, cell by cell.

Fields:

- `text: str`
- `heads: list`: the lines above the rule
- `body: list`: [(line, [cells])] below it
- `columns: int`

### Gathered

```python
@dataclass
class Gathered
```

What one read fetched of the rest of the plan, in the order the model
asked for it: the passages its request shows under "more", the hit lists
of its searches under "hits", and what could not be found, with why,
under "not_found". *seen* are the passages the request already shows,
*cursor* where "next" and "previous" go on from.

Fields:

- `seen: set = field(default_factory=set)`
- `cursor: dict = field(default_factory=dict)`
- `sources: list = field(default_factory=list)`
- `shown: list = field(default_factory=list)`
- `hits: list = field(default_factory=list)`
- `missed: list = field(default_factory=list)`
- `by_hit: dict = field(default_factory=dict)`

#### Gathered.context

```python
def context(self) -> dict
```

#### Gathered.list_hits

```python
def list_hits(self, found: list, **about) -> int
```

Show *found*, [(owner, title, line)], as one list of hits, each
with the id a later ask names it by. Returns how many.

#### Gathered.fetch

```python
def fetch(self, asks, order: list, passages: dict,
          budget: Optional[int]) -> bool
```

The asks of one reply resolved (`lookup`), each passage cut to
*budget*, the survey's two pages. True when a passage or a hit list
came of them the request has not shown yet: an ask for something
shown already, or for nothing, ends the gathering.

### Read

```python
@dataclass
class Read
```

What reading one parameter in one passage came to.

Fields:

- `batch: Batch`
- `claims: list`
- `asked: int = 0`
- `skipped: int = 0`: cells of value rows and columns not read
- `faulty: Optional[str] = None`
- `unread: bool = False`: no readable reply
- `why: Optional[str] = None`: and why: cut_off or no_answer
- `corrected: int = 0`: corrections the second request carried
- `failed: dict = field(default_factory=dict)`: what the check refused of the first reply, by reason
- `unanswered: int = 0`: coordinates no reply answered
- `fetched: int = 0`: passages shown under "more"
- `searched: int = 0`: hit lists shown under "hits"
- `missed: int = 0`: asks that found nothing

### Reader

```python
class Reader
```

(document_id, survey, passages) -> [Read], one per parameter and
passage the survey named for it.

*ask_table(source, grid, parameter, slots, context, corrections)* and
*ask_text(source, parameter, slots, context, corrections)* are one
request each: the reply as a dict, CUT, or None; *context* is what the
request shows beside its passage (`context_of`), *corrections* None the
first time and what was wrong the second. *shown_with(source)* is what a
coordinate's quote may stand in besides the passage: its section's
heading. *pool* reads passages side by side.

#### Reader.\_\_init\_\_

```python
def __init__(self, spec, ask_table: Callable, ask_text: Callable,
             frame_slots: list, *, shown_with: Optional[Callable] = None,
             bases: Optional[Callable] = None, pool=None, trace=None)
```

#### Reader.context_of

```python
def context_of(self, source: Source, slots: list, tuples: list,
               bases: list, passages: dict,
               budget: Optional[int]) -> tuple
```

(what a request shows beside its passage, the section it was
cut from): the text around a table or figure (`around_of`), the
survey's pairs of the passage and the plan's years (`years_of`).

#### Reader.read

```python
def read(self, document_id: int, parameter, source: Source,
         tuples: list, pairs: list, passages: dict,
         shown: Optional[Source] = None,
         budget: Optional[int] = None) -> Read
```

*source* is the passage a value is verified against, *shown* the
piece of it the request shows, *budget* the survey's two pages.

## Functions

### cells_of

```python
def cells_of(line: str) -> list
```

### grid_of

```python
def grid_of(text: str) -> Optional[Grid]
```

The table of *text*, or None when it has no Markdown table.

### cell_number

```python
def cell_number(cell: str)
```

The one number a cell prints, as int or float, or None for a cell
with none or with several. Digits after a letter are part of a name,
"CO2" or "Q3", and no number of the cell.

### cell_numbers

```python
def cell_numbers(cell: str, count: int) -> Optional[list]
```

The *count* numbers a cell prints, in the order it prints them, as int
or float, or None for a cell that does not print that many. Digits after
a letter are part of a name. Digits grouped by a space are read as one
number and as several, whichever gives *count*: "967 168%" is two numbers
where its column prints two, "1 234" one where it prints one.

### slots_of

```python
def slots_of(spec, parameter) -> list
```

The coordinates a value of *parameter* is read with: its unit, then
every axis the spec does not decide.

### coordinate_shown

```python
def coordinate_shown(slot) -> dict
```

### answer_schema

```python
def answer_schema(slot, where: Optional[str] = None) -> dict
```

One coordinate's answer as the grammar takes it, at a row or a column
when *where* names it.

### known_of

```python
def known_of(tuples: list, frame_slots: list) -> list
```

### years_of

```python
def years_of(bases: list, slots: list) -> dict
```

The plan's base years and target years, numbers only, where a
coordinate asked is the one they date: what the field request shows
(`runner._field_payload`), so a value whose passage names its state by
the plan's word and prints no year can answer one of them
(`pipeline.named_year`).

### around_of

```python
def around_of(source: Source, passages: dict,
              budget: Optional[int]) -> Optional[Source]
```

The text of the section a table or figure stands in, as its request
shows it (owner decision 2026-11-04): the sentence that announces it,
the heading over it and the paragraph under it, where its year and its
scenario are printed. The whole section when it fits *budget*, the
survey's two pages, else that many characters around the table's place
in it. None for a section, and for a table or figure whose section is
not among *passages*.

### more_schema

```python
def more_schema() -> dict
```

The asks a reply may carry under "more".

### first_line

```python
def first_line(source: Source) -> str
```

The first line of a passage under its title: what a hit list shows
of it.

### gather

```python
def gather(ask: Callable, reply: dict, gathered: Gathered, order: list,
           passages: dict, budget: Optional[int]) -> tuple
```

(the reply that stands, the requests made): what each reply asks of
the rest of the plan is fetched and the request sent again, until a round
asks for nothing the request has not shown or the request no longer fits
the model's window. The reply before such a round stands.

### table_payload

```python
def table_payload(source: Source, grid: Grid, parameter, slots: list,
                  context: dict, corrections: Optional[list] = None) -> dict
```

The table request: the table, the text around it and *context*
(`Reader.context_of`); with *corrections* the same request asked once
more, what was wrong with the first reply beside it.

### table_response_format

```python
def table_response_format(slots: list) -> dict
```

Every coordinate answered, at least for the whole table: its entry
there is the answer of every value no row or column entry answers, and
UNSTATED when the table does not print it.

### parts_of

```python
def parts_of(reply: dict, grid: Grid) -> dict
```

{column: (numbers, [places])} of the columns whose cells print several
numbers, as the reply's "cells" says: how many numbers each cell of the
column prints and the places of those that are values, counted from 1 in
the order the cell prints them. An entry naming no such place says
nothing; the first entry of a column stands.

### table_rows

```python
def table_rows(reply: dict, grid: Grid) -> tuple
```

(rows, {label: (row, column, part)}, cells not read) of a table reply:
one row per number of a cell of a value row and a value column, its quote
the table row, its head the words over its column. A cell prints one
number, part None; or, in a column the reply's "cells" names, as many as
it says, and each of them it names a value is a row of its own, part its
place in the cell (`parts_of`). A cell that does not print that many is
not read.

### answer_of

```python
def answer_of(entry: dict) -> dict
```

### table_replies

```python
def table_replies(reply: dict, slot, at: dict) -> list
```

[(level, window, field reply)] of one coordinate of a table reply,
the most particular first: a row label, then a column head, for one
place in the column's cells before the whole column, then the table.

### table_corrections

```python
def table_corrections(failed: list, at: dict) -> list
```

What the check refused of a table reply, once per coordinate and
place: [{coordinate, row | column [, part], what}], the row or column
numbered as the request numbered it, the place in a cell where the cell
prints several numbers, neither for the whole table.

### text_payload

```python
def text_payload(source: Source, parameter, slots: list,
                 context: dict, corrections: Optional[list] = None) -> dict
```

The request of a section or a figure, the text around a figure and
*context* (`Reader.context_of`) beside it; with *corrections* the same
request asked once more for the values the check refused something of.

### text_response_format

```python
def text_response_format(parameter, slots: list,
                         labels: Optional[list] = None) -> dict
```

Every value with every coordinate. Asked again, each entry names the
value of the first reply it answers for, one of *labels*.

### text_rows

```python
def text_rows(reply: dict) -> tuple
```

(rows, the entry of each row) of a text reply.

### text_replies

```python
def text_replies(entries: dict, slot) -> list
```

### value_failure

```python
def value_failure(claim: dict, source: Source) -> Optional[str]
```

Why the check of a value refuses it, or None: a number its quote does
not print (the harvest's own `number_outside_quote`), a quote not in its
passage. Said as the harvest says it.

### text_corrections

```python
def text_corrections(rows: list, failed: list, source: Source,
                     slots: list) -> list
```

What the check refused of a text reply, one entry per value it
refused something of: [{row, value, quote, what: {value | coordinate:
reason}}]. A coordinate the reply left out is named as missing.

### same

```python
def same(slot, a, b) -> bool
```

### inherit

```python
def inherit(rows: list, slots: list, tuples: list, pairs: list,
            shown: list) -> int
```

A frame coordinate still open on a row takes the survey's tuple of
the passage, when the survey named exactly one, through the field check
with the tuple's own quote. Not on a row that read a frame coordinate of
its own the tuple contradicts: a year under its column head is not the
year of the table's title. Returns the coordinates taken.

[Back to the index](../README.md)
