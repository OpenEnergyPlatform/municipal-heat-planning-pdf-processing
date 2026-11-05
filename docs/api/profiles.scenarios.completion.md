# profiles.scenarios.completion

`profiles/scenarios/completion.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

completion.py: What a publication's own text leaves open of its identity,
looked up in an open catalogue (owner decisions 2026-11-04).

A paper's PDF is often the authors' manuscript: it prints its title and its
authors, and neither its DOI nor its year. After a document's fold a program
asks OpenAlex, whose records are CC0, for the publication's record and fills
the parameters no reading filled: the DOI, the year and, where the text
yields no author at all, the authors. The year is the value, as the
parameter defines it, and the record keeps the full date.

The record is the first one these keys find, in this order: the DOI the
corpus index holds for the document (`DocumentMeta.doi` in the run's
database), the DOI the harvest read, the title the harvest read. The index's DOI goes first because it
belongs to this very file, while a DOI read off the page can be one the
paper cites, such as a dataset's. A DOI names one publication, so its
record is taken as it is; a record the title finds counts only where at
least two of its authors' family names stand among the authors the harvest
read, or one where either side names one author.

Such a row is built like a computed one: its quote and its passage are those
of the read value the record was found with, the printed DOI, else the
title; the record stands beside it (`catalogue`), and the flag `catalogue`
makes it a D (`trust.FLAG_REASONS`). A value the document prints goes
first: a parameter that has a row is not looked up. No model is asked.

The first time the catalogue cannot be reached at all, the run asks it no
more (`OFFLINE`): each later document says so at once instead of waiting
out the timeout.

Author: Felix Vossel

## Functions

### search

```python
def search(title: str) -> Optional[dict]
```

The first record OpenAlex finds for *title*, or None.

### by_doi

```python
def by_doi(doi: str) -> Optional[dict]
```

The record OpenAlex holds under *doi*, or None where it holds none.

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

Whether the record a title found is the document: two of its family
names among the authors read, or one where either side names one.

### bare_doi

```python
def bare_doi(text) -> Optional[str]
```

A DOI alone, without the resolver or the "doi:" before it.

### index_doi

```python
def index_doi(conn, document_id) -> Optional[str]
```

The DOI the corpus index holds for the document (`DocumentMeta.doi`),
without its resolver, or None where it holds none.

### doi_of

```python
def doi_of(record: dict) -> Optional[str]
```

### year_of

```python
def year_of(record: dict) -> Optional[str]
```

### evidence

```python
def evidence(record: dict, key: tuple, hit: list) -> dict
```

The record a looked-up value stands on, as the row carries it.

### row_of

```python
def row_of(anchor: dict, uri: str, value: str, record: dict, key: tuple,
           hit: list) -> dict
```

A looked-up value in the shape of the read row it was found with:
its quote and its passage, the record beside it.

### complete

```python
def complete(report, spec, *, fetch: Optional[Callable] = None,
             fetch_doi: Optional[Callable] = None,
             catalogue_doi: Optional[str] = None,
             db=None) -> Optional[dict]
```

Fill what the document leaves open of DOI, year and authors from its
catalogue record. *catalogue_doi* is the DOI the corpus index holds for
the document; where it is not given, it is read from *db*, the run's
database. What it came to, for the trace, or None where nothing was
open.

[Back to the index](../README.md)
