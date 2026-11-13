# profiles.scenarios.completion

`profiles/scenarios/completion.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

completion.py: What a publication's own text leaves open of its identity,
looked up in an open catalogue (owner decisions 2026-11-04).

A paper's PDF is often the authors' manuscript: it prints its title and its
authors, and neither its DOI nor its year. After a document's fold a program
asks OpenAlex, whose records are CC0, for the publication's record and fills
the parameters its front pages do not give: the DOI, the year and, where
they name no author, the authors. The year is the value, as the parameter
defines it, and the record keeps the full date.

The record is the first one these keys find, in this order: the DOI the
corpus index holds for the document (`DocumentMeta.doi` in the run's
database), the DOI the harvest read, the title the harvest read. The index's DOI goes first because it
belongs to this very file, while a DOI read off the page can be one the
paper cites, such as a dataset's. A DOI names one publication, so its
record is taken as it is; a record the title finds counts only where at
least two of its authors' family names stand among the authors the harvest
read, those of the front pages where it read any there, or one where either
side names one author.

Such a row is built like a computed one: its quote and its passage are those
of the read value the record was found with, the printed DOI, else the
title; the record stands beside it (`catalogue`), and the flag `catalogue`
makes it a D (`trust.FLAG_REASONS`). A value the document prints on its
front pages goes first: a parameter read there, or looked up already, is not
looked up. One read only elsewhere is, since a chapter on other studies and
a reference list print other works' values, and the graph takes the record's
value before such a reading (owner decision 2026-11-05, `front.py`). The
title and the DOI the record is found with are those of the front pages
where they were read there. No model is asked.

The first time the catalogue cannot be reached at all, the run asks it no
more (`OFFLINE`, rule `catalogue_stop_when_offline`): each later document of
that run says so at once instead of waiting out the timeout. The state is the
run's, not the process's: a run that starts afterwards asks again.

Every value here is a rule read when the catalogue is asked (`rules.json`
beside `rules.py`): its address, the waiting time, the name the run gives it,
the keys and their order, the hits looked at, what a hit has to agree in, the
values it fills in and the flags a looked-up row shares with its anchor.

Author: Felix Vossel

## Functions

### works

```python
def works() -> str
```

Where the catalogue answers (rule `catalogue_address`).

### offline

```python
def offline() -> bool
```

Whether the catalogue was found unreachable by the run that goes on
(rule `catalogue_stop_when_offline`).

### went_offline

```python
def went_offline() -> None
```

Note that the catalogue could not be reached, for this run.

### search_hits

```python
def search_hits(title: str) -> list
```

The records OpenAlex finds for *title*, as many as the rule
`catalogue_hits_taken` says, best first.

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

Whether the record a title found is the document: as many of its
family names among the authors read as the rule `catalogue_family_names`
says. Where a side names fewer authors than that, all of its authors
have to agree, unless the rule `catalogue_fewer_authors_suffice` is off:
then the number is kept as it is, and a record or a paper with fewer
authors is never accepted by its title.

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

Fill what the document's front pages leave open of DOI, year and
authors from its catalogue record. *catalogue_doi* is the DOI the corpus
index holds for the document; where it is not given, it is read from
*db*, the run's database. What it came to, for the trace, or None where
nothing was open.

[Back to the index](../README.md)
