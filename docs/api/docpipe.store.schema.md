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

## Classes

### MixedIndex

```python
class MixedIndex(RuntimeError)
```

Vectors of one model were about to be appended to an index that holds
vectors of another. Raised before a vector is written; says both.

#### MixedIndex.\_\_init\_\_

```python
def __init__(self, recorded: str, configured: str)
```

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

### add_missing_column

```python
def add_missing_column(connection: sqlite3.Connection, table: str,
                       column: str, kind: str) -> bool
```

Add *column* to *table* where the table is there and lacks it.

For a table of the profile's, which `CREATE TABLE IF NOT EXISTS` leaves
as it was made: a source that fills a column the table was made without
adds it first. A table that is not there is left alone, so that the write
that needed it is the one to fail. Returns whether a column was added.

### migrate

```python
def migrate(connection: sqlite3.Connection) -> int
```

Bring a database of an older format up to this one. Returns the
format it had. Adds what is missing and touches nothing that is there.

### note_embedding

```python
def note_embedding(connection: sqlite3.Connection, model: str, dim: int,
                   backend: str, max_token_length: int, version: str,
                   *, allow_mixed: bool = False) -> Optional[str]
```

Write down what builds this database's index.

An index that holds vectors of another model is not continued with this
one: vectors of two models do not compare, so a search over both is not
one search, and nothing in a vector says which model it is of. That
raises `MixedIndex` naming both, and writes nothing. `allow_mixed` is the
deliberate mixture: the first model stays the recorded one, the other is
recorded beside it, and the sentence comes back for the caller's log. An
index that holds no vectors may change its model.

A database that records no model cannot be checked, whatever it holds:
the configured one is recorded as the one that built it. Where it holds
vectors the sentence says that, because nothing proved them to be its.

### recorded_model

```python
def recorded_model(connection: sqlite3.Connection) -> Optional[str]
```

The model the database says its index was built with, or None.

### embedding_mismatch

```python
def embedding_mismatch(connection: sqlite3.Connection,
                       model: str) -> Optional[str]
```

A sentence when a query would be embedded with another model than the
index was built with, else None. For the query side to log; a database
that records no model says nothing.

### dimension_mismatch

```python
def dimension_mismatch(connection: sqlite3.Connection,
                       dim: int) -> Optional[str]
```

A sentence when a query would be embedded to another length than the
vectors the index holds, else None. The same name can be set to another
length, and vectors of two lengths do not compare. A database that
records no dimension says nothing.

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
