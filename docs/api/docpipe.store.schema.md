# docpipe.store.schema

`docpipe/store/schema.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

schema.py: Builds a database from the core schema plus a profile's
own schema.

The core tables (Documents, Pages, Sections, SectionPages, Segments,
Tables, Images, Embeddings) are the same for every corpus. A profile
adds its own entities and its per-document fields through its own
schema.sql. apply() runs both scripts against one connection inside
one transaction, core first and then the profile's, so a profile's
tables can reference the core tables but not the other way round.
connect() opens the database file, creating its parent directory and
applying both schemas if needed, and is idempotent because every
statement is written IF NOT EXISTS.

Author: Felix Vossel

## Functions

### core_sql

```python
def core_sql() -> str
```

### profile_sql

```python
def profile_sql(profile: Optional[Profile]) -> str
```

### apply

```python
def apply(connection: sqlite3.Connection, profile: Optional[Profile] = None) -> None
```

Create every missing table. Idempotent (everything is IF NOT EXISTS).

### readonly_uri

```python
def readonly_uri(path) -> str
```

The address that opens a database file for reading only.

The path is percent-encoded. Written into the address as it is, a `#`
in it starts a fragment and a `?` a query: SQLite then opens another
file than the one that was named, and without `mode=ro` makes it.

### columns

```python
def columns(connection: sqlite3.Connection, table: str) -> set
```

### migrate

```python
def migrate(connection: sqlite3.Connection) -> int
```

Bring a database of an older format up to this one. Returns the
format it had. Adds what is missing and touches nothing that is there.

### note_embedding

```python
def note_embedding(connection: sqlite3.Connection, model: str, dim: int,
                   backend: str, max_token_length: int,
                   version: str) -> Optional[str]
```

Write down what builds this database's index.

Returns a sentence when the index already holds vectors of another
model, else None. Vectors of two models do not compare, so that is worth
a line in the log; it is the caller's line, and nothing is refused here.
The first model stays the recorded one and the other is recorded beside
it, so the database says both.

### embedding_mismatch

```python
def embedding_mismatch(connection: sqlite3.Connection,
                       model: str) -> Optional[str]
```

A sentence when a query would be embedded with another model than the
index was built with, else None. For the query side to log; a database
that records no model says nothing.

### meta

```python
def meta(connection: sqlite3.Connection) -> dict
```

Everything the database says about itself; empty for one that was
made before it said anything.

### set_meta

```python
def set_meta(connection: sqlite3.Connection, values: dict) -> None
```

### connect

```python
def connect(path: Path, profile: Optional[Profile] = None) -> sqlite3.Connection
```

Open (creating if needed) a database with core + profile schema applied.

### tables

```python
def tables(connection: sqlite3.Connection) -> set
```

[Back to the index](../README.md)
