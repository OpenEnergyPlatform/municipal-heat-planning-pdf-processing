# profiles.scenarios.completion

`profiles/scenarios/completion.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

completion.py: What a publication's own text leaves open of its identity,
looked up in an open catalogue (owner decisions 2026-11-04).

A paper's PDF is often the authors' manuscript: it prints its title and its
authors, and neither its DOI nor its year. After a document's fold a program
asks OpenAlex, whose records are CC0, for the title the harvest read, and
takes the first hit only where at least two of its authors' family names
stand among the authors the harvest read; where either side names one
author, that one. Its DOI and its year then enter the harvest for the
parameters no reading filled. The year is the value, as the parameter
defines it, and the record keeps the full date.

Such a row is built like a computed one: its quote and its passage are the
title it was looked up with, the record stands beside it (`catalogue`), and
the flag `catalogue` makes it a D (`trust.FLAG_REASONS`). A value the
document prints goes first: a parameter that has a row is not looked up. No
model is asked.

Author: Felix Vossel

## Functions

### search

```python
def search(title: str) -> Optional[dict]
```

The first record OpenAlex finds for *title*, or None.

### words

```python
def words(name) -> set
```

The words of a person's name as two lists can share them: without
accents, marks, digits and case ("Keywan Riahi1,2*" -> keywan, riahi).

### family

```python
def family(name) -> str
```

The family name of a catalogue's author, the last word of the name
it displays ("Jingyu Liu" -> liu).

### authors_of

```python
def authors_of(record: dict) -> list
```

### matched

```python
def matched(record: dict, read: list) -> list
```

The family names of the record's authors that stand among the words
of the authors the harvest read, each once, in the record's order.

### accepted

```python
def accepted(record: dict, read: list) -> bool
```

Whether the record is the document: two of its family names among the
authors read, or one where either side names one author.

### doi_of

```python
def doi_of(record: dict) -> Optional[str]
```

The DOI alone, without the resolver before it.

### year_of

```python
def year_of(record: dict) -> Optional[str]
```

### evidence

```python
def evidence(record: dict, title: str, hit: list) -> dict
```

The record a looked-up value stands on, as the row carries it.

### row_of

```python
def row_of(title_row: dict, uri: str, value: str, record: dict,
           hit: list) -> dict
```

A looked-up value in the shape of the title row it was looked up
with: its quote and its passage, the record beside it.

### complete

```python
def complete(report, spec, *, fetch: Optional[Callable] = None
             ) -> Optional[dict]
```

Fill what the document leaves open of DOI and year from the record
its title and authors find. What it came to, for the trace, or None
where nothing was open.

[Back to the index](../README.md)
