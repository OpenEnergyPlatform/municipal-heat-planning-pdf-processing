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
