# profiles.scenarios.store

`profiles/scenarios/store.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

store.py – The project's own tables: publication metadata, the AR6 scenarios
and the links between them. The core never touches these.

Author: Felix Vossel

## Functions

### document_id

```python
def document_id(filename: str, connection: sqlite3.Connection) -> Optional[int]
```

The id the core gave this file, or None if it was never registered.

### upsert_publication_meta

```python
def upsert_publication_meta(document: int, values: dict,
                            connection: sqlite3.Connection) -> None
```

Refresh the publication's DocumentMeta row.

The core writes it once, when the document is first registered. A re-run
skips an already registered document, so this is the only path by which
metadata that arrived after the first import (the OpenAlex fetch runs on its
own schedule) reaches the corpus.

### upsert_scenario

```python
def upsert_scenario(ar6_id: int, name: str, connection: sqlite3.Connection) -> int
```

The row for an AR6 scenario, created or renamed. Returns its id.

### link_scenario

```python
def link_scenario(document: int, scenario: int,
                  connection: sqlite3.Connection) -> None
```

Record that `document` documents `scenario`; a re-import is a no-op.

[Back to the index](../README.md)
