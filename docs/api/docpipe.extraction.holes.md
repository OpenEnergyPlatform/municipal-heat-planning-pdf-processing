# docpipe.extraction.holes

`docpipe/extraction/holes.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

holes.py: What an earlier stage left without content in the documents a run
reads (owner request 2026-11-19).

Stage 5 can leave a table or figure without content; the merge writes those
into the document and the database keeps them beside it (Documents.holes,
`docpipe.visuals.holes`). A run reads them with the documents
(`runner.note_documents`). In such a document a value whose search found
nothing is no finding about the document: what it would have been read from
may stand in what has no content. So its search ends in the state of
`unstated_with_holes`, and a field with no value in that of
`parameter_with_holes` (rule `state_rules`, both "exhausted" by default: a
finding about the run). The stamp records the holes, and one filled since
makes the document work again (`runner.holes_filled`).

Author: Felix Vossel

## Functions

### parse

```python
def parse(text) -> list
```

The holes the database keeps for a document (Documents.holes, JSON),
as a list; [] for none, NULL or anything unreadable.

### note

```python
def note(document_id, found: list) -> None
```

Record the holes of one document of the run's database.

### clear

```python
def clear() -> None
```

### of

```python
def of(document_id) -> list
```

The holes of the document, [] where it has none or none is known.

### ids

```python
def ids(found) -> set
```

The ids of the items of *found* (holes as recorded).

[Back to the index](../README.md)
