# profiles.scenarios.source

`profiles/scenarios/source.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

source.py – Where the scenarios corpus comes from: pdf_index.json, the crawl
over the publications of the corpus.

One entry is one publication. Its PDF is staged by hand. What a publication
says about its scenarios is read from the publication alone.

Author: Felix Vossel

## Classes

### ScenarioSource

```python
class ScenarioSource(Source)
```

The publication crawl as a document source.

#### ScenarioSource.\_\_init\_\_

```python
def __init__(self, index_file: Path)
```

#### ScenarioSource.documents

```python
def documents(self, connection: sqlite3.Connection)
```

#### ScenarioSource.document_for

```python
def document_for(self, entry: dict) -> SourceDoc
```

#### ScenarioSource.after_document

```python
def after_document(self, connection: sqlite3.Connection, doc: SourceDoc) -> None
```

## Functions

### has_local_pdf

```python
def has_local_pdf(entry: dict) -> bool
```

Whether the crawl left a file for this entry. The rest is bibliography:
a paywalled paper, or a citation of a whole journal volume.

### external_id_for

```python
def external_id_for(entry: dict) -> str
```

A DOI identifies a paper. Agency reports, national roadmaps and working
papers often have none, so the crawl's slug stands in.

### filename_for

```python
def filename_for(entry: dict) -> str
```

### extract_meta

```python
def extract_meta(entry: dict, publication_meta: dict) -> dict
```

{db_column: value} for one entry's DocumentMeta row.

publication_meta.json is the authority on title, year, venue and open
access; the index fills in what it happens to carry. Whatever neither knows
stays NULL — nothing is inferred from the DOI or read out of the PDF.

### published_for

```python
def published_for(year: Optional[int]) -> Optional[str]
```

[Back to the index](../README.md)
