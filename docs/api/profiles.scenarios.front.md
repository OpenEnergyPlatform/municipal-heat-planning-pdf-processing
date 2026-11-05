# profiles.scenarios.front

`profiles/scenarios/front.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

front.py: What a publication says of itself, and which reading of it goes
first (owner decisions 2026-11-05).

A publication prints its own title, authors, date and DOI on its first page
or on its title page. A chapter that presents other studies prints theirs,
and a reference list prints the DOIs it cites, so a value read anywhere else
may belong to another work. For these fields a reading on a front page goes
first; where there is none, the record the catalogue holds for the
publication (`completion.py`); only then a reading anywhere else. The
completion looks a field up wherever no front page gave it, and the graph
takes its value in this order (`kg.py`).

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

[Back to the index](../README.md)
