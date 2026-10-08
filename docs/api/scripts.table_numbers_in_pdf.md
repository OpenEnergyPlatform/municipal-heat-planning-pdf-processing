# scripts.table_numbers_in_pdf

`scripts/table_numbers_in_pdf.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

table_numbers_in_pdf.py: How much of a stored table the PDF itself prints.

Stage 5 has a vision model read every table off its picture, and the Markdown
it wrote is what the database stores and what a harvest quotes. A PDF with a
text layer prints the same numbers as text, inside the same frame. This sets
the two side by side and counts. It reads a corpus database, the PDFs and,
when it is given one, a harvest directory:

  (a) per table: how many of the distinct numbers of the stored transcription
      stand in the PDF text at the table's place;
  (b) per parameter: of the values the harvest read out of a table, how many
      have their digits in that text.

It judges nothing and changes nothing. No trust level, reason or flag reads
what it prints, the database is opened for reading only, and a table it
cannot judge is listed with the reason and left out of every share, never
counted as a miss.

    python scripts/table_numbers_in_pdf.py data/KWP.db data/pdf
    python scripts/table_numbers_in_pdf.py <db> <pdf root> --harvest data/extraction/corpus
    python scripts/table_numbers_in_pdf.py <db> <pdf root> --document 12 --json counts.json

What the numbers are. A number is compared the way the harvest compares one:
1.234,5 and 1234.5 are one number, and how a point or comma is read is the
profile's decimal mark (--profile or DOCPIPE_PROFILE; with neither the comma,
as everywhere else the harvest reads a number). Each table counts
its DISTINCT numbers, so a number that stands in six cells is one. The table's
place is its stored bbox, which stage 2 widens by a few points on each side:
a number printed just beside a table can stand in its text. The PDF text is
the text layer. A page without one (a plan a model transcribed) cannot be
judged, and neither can a table whose frame holds no text, and both are said
so.

What (b) compares: the value of a numeric parameter, as the harvest wrote it,
against the numbers in the frame text of the table the value was read from.
A value the sandbox computed is not read off a page and is counted apart. A
harvest names its table by Tables.id, which a rebuilt database renews, so a
tuple whose id is not a table of this database, or is one of another document
or block, is counted apart too.

Needs PyMuPDF. No model, no GPU.

Author: Felix Vossel

## Classes

### PdfFrames

```python
class PdfFrames
```

The text a PDF carries inside a rectangle of a page.

One document is held open at a time: the tables are read in document
order. MuPDF is entered from this one thread only, which is why nothing
here takes a lock.

#### PdfFrames.\_\_init\_\_

```python
def __init__(self, root)
```

#### PdfFrames.close

```python
def close(self) -> None
```

#### PdfFrames.text

```python
def text(self, filename: Optional[str], page: int, rect: tuple)
```

(text, None) for the text inside *rect* of 1-based *page*, or
(None, reason) when the frame cannot be read.

## Functions

### share_class

```python
def share_class(found: int, numbers: int) -> str
```

Which class a table with *found* of *numbers* distinct numbers is in.

### numbers_of

```python
def numbers_of(text: str) -> set
```

The distinct numbers of *text*, each in its one canonical spelling.

### frame_of

```python
def frame_of(bbox_json) -> Optional[tuple]
```

The one rectangle a table's stored bbox spans, or None.

Tables.bbox is a JSON list holding one [x0, y0, x1, y1]. More than one is
joined into the box that holds them all, and a rect that is not four
numbers or has no area is not used.

### frame_numbers

```python
def frame_numbers(frames, table: dict)
```

(numbers of the frame text, None), or (None, why it cannot be read).

### table_rows

```python
def table_rows(connection: sqlite3.Connection, documents=None)
```

Every table of the database, in document and page order, as dicts.

A database that predates Tables.bbox has no such column and every one of
its tables is then without a place.

### read_harvest

```python
def read_harvest(directory: Path, documents=None) -> dict
```

What (b) needs of a harvest: the tuples read out of a table.

{"files", "tuples" (all), "by_owner" (tuples per owner kind), "wanted"
(table id -> the tuples read from it)}. A line that is not JSON is
skipped: one torn line must not lose a plan. With *documents* only the
tuples of those documents are looked at.

### judge_values

```python
def judge_values(table: dict, frame: Optional[set], wanted: list,
                 counts: dict) -> None
```

Book the harvested values of one table into *counts*, per parameter.

### measure

```python
def measure(connection: sqlite3.Connection, frames, harvest: Optional[dict],
            documents=None) -> dict
```

Run (a) over the tables and, with a harvest, (b) over its tuples.

### worst

```python
def worst(report: dict, limit: int) -> list
```

The judged tables with the lowest share of their numbers found.

### render

```python
def render(report: dict, limit: int) -> list
```

The lines the report prints. Every count says what it counts.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
