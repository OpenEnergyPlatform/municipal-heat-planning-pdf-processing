# docpipe.extraction.identity

`docpipe/extraction/identity.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

identity.py: Which value a harvested row is, and where its passage is now.

A row points at its passage with the database's own ids (`provenance`:
owner_kind, owner_id). Those are counters. Build the chunks of a document
again and every section, table and figure of it gets new ones, and a harvest
that was read from the old ones points at nothing. What does not move is
what the row says: the document and the words it quotes.

    tuple_id    a name for a row made from the document, the quote and the
                value as it was written. It survives a re-chunk, and a
                re-harvest that reads the same thing gives the same name, so
                a label, an export and a provenance record can hold on to it.
    reanchor    the passage of a row found again after the database was
                rebuilt: the one passage of its kind in the document that
                carries the quote. Run as a pass of its own
                (`python -m docpipe.extraction.identity DB HARVEST_DIR`); no
                other pass moves a row's address.

Neither adds a key to a row and neither judges one: a row whose passage is
not found again is left exactly as it is and counted.

Author: Felix Vossel

## Functions

### said

```python
def said(row: dict)
```

The value as the document wrote it, else as it was read.

### tuple_id

```python
def tuple_id(document: str, row: dict) -> str
```

The name of one row: the document, its quote, its value.

*document* is whatever names the document's bytes: the sha256 the
database recorded, or the file name for a database that recorded none.

### tuple_ids

```python
def tuple_ids(document: str, rows: list) -> list
```

One name per row, in order. A row that says exactly what an earlier
one of the same document says is the second of that name: `<id>.2`.

### owners_of_kind

```python
def owners_of_kind(connection: sqlite3.Connection, document_id,
                   kind: str) -> list
```

### find_again

```python
def find_again(row: dict, connection: sqlite3.Connection,
               owner_sources: Callable, carries: Callable) -> Optional[tuple]
```

(kind, id) of the passage that carries the row's quote now, or None.

None when the row's own address still carries it, when no passage of its
kind in the document does, and when more than one does and none of them
is the row's own table or figure: a guess between two passages would be
an address nobody read the value from.

### reanchor_file

```python
def reanchor_file(path: Path, connection: sqlite3.Connection,
                  owner_sources: Callable, carries: Callable,
                  *, write: bool = True) -> Counter
```

Give every row of one harvest file whose passage moved its new
address. Rows are counted, never dropped; the file is rewritten only
when a row changed.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
