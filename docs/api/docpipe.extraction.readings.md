# docpipe.extraction.readings

`docpipe/extraction/readings.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

readings.py: Which reading of a value the graph takes, where a document
has several.

Three parts of the program that writes a drawing (`graph.py`), each with
the rules of the graph file it reads:

- the pages a publication states itself on (`front_pages`, `in_order`):
  for the fields of the rule `front_first_fields` a reading on a front page
  goes first, then the catalogue's record, then any other (owner decisions
  2026-11-05);
- one reading where the shapes allow one (`pick_one`): the one the most
  sources agree on, a tie to the one located on its page, then to the
  longer, and a reading contained in another never wins;
- the numbers of one address (`settle`): one number several times is one
  node, different numbers are told apart by the plan's wording, a rounded
  statement loses to the precise one (rule `rounding_tolerance`), a lower
  trust level to the higher, and what is left is either kept as nodes
  marked contested (rule `contested_in_full`, the full graph) or left out.

Author: Felix Vossel

## Functions

### page_of

```python
def page_of(row: dict) -> Optional[int]
```

The page a row was read on, None where it names none.

### front_pages

```python
def front_pages(titles: list) -> set
```

Page 1 and the first page the document's title was read on (*titles*,
its rows of the title): its title page, where a cover stands before
it.

### looked_up

```python
def looked_up(row: dict) -> bool
```

Whether *row* holds a value looked up outside the document
(`completion.row_of`). Such a row keeps the page of the reading it was
found with, so its page says nothing of where its value stands.

### read_in_front

```python
def read_in_front(rows: list, front: set) -> list
```

The rows of *rows* read on one of the *front* pages.

### in_order

```python
def in_order(rows: list, front: set) -> list
```

The readings of a front field that count: those read on a *front*
page where there are any, else those looked up in the catalogue, else
every one of *rows*.

### pick_one

```python
def pick_one(rows: list) -> tuple
```

(value, how many other readings were offered) for a field the shapes
allow once.

The reading the most sources agree on wins. A tie goes to the one that
could be located on its PDF page, then to the longer text: a truncated
title is a common failure and the full one is never the shorter reading
of the same passage.

### place

```python
def place(row: dict) -> tuple
```

The passage a row was read from, where the plan prints its number.

### precision

```python
def precision(row: dict) -> int
```

Significant digits of the number as the document printed it.

### wording_key

```python
def wording_key(row: dict, fields: tuple) -> str
```

The document's words for what tells two numbers on one address
apart, the *fields* of the row joined: "Wirtschaftlich genutzte
Gebäude" and "Öffentliche Gebäude" are one class and not one number.

### settle

```python
def settle(iri: str, rows: list, address: Callable, *, fold: Callable,
           wording: tuple, tolerance: float, transcribed: bool = False,
           keep_open: bool = False) -> tuple
```

({iri: row} kept, Counter skipped, {iri: marks}) for one address.

*address(row, label)* names a node split off by its wording or kept as
contested, *fold* is the graph's folding of a name. One number several
times is one node, marked as confirmed where a second passage prints it:
one passage read twice is one statement, whatever its quotes (owner
decision 2026-11-05). Different numbers are settled in this order (owner
decision 2026-09-23): the document's different wording splits them into
a node each, named by that wording; a rounded statement of the other
loses to the more precise one; a lower trust grade loses to the higher;
and what is left is a question for a human. With *keep_open* each of
those stays as a node of its own, marked as contested (owner decision
2026-11-02); without it, as for the strict graph, nothing stays. The
counts are per tuple that left the graph: a repeat of the winner is a
`duplicate`, a repeat of a loser is one too, and the losers are
`conflict:<rule>`. `conflict:open` counts nodes kept, not tuples lost.

[Back to the index](../README.md)
