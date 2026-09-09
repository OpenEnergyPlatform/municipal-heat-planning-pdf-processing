# profiles.kwp.migrate_profile_split

`profiles/kwp/migrate_profile_split.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

migrate_profile_split.py – Bring a pre-refactoring KWP.db up to the core schema.

Before the core/profile split, `Documents` carried the project's own fields
(organisation_unit, municipality_ags) and identified a document by its file
name. The core schema now keeps only identity (`external_id`) and versioning
(`group_key`) there, and everything municipal moved into the profile's own
`DocumentMeta`.

The migration is additive and runs in place: the two legacy columns are left
where they are. Nothing reads them any more, they are nullable so they cannot
block an insert, and removing them would mean rewriting a half-gigabyte
database to save two integers per row.

    python -m profiles.kwp.migrate_profile_split data/KWP.db            # dry run
    python -m profiles.kwp.migrate_profile_split data/KWP.db --apply

Author: Felix Vossel

## Functions

### columns

```python
def columns(connection: sqlite3.Connection, table: str) -> list
```

### inspect

```python
def inspect(connection: sqlite3.Connection) -> dict
```

What this database still lacks.

### plan

```python
def plan(state: dict) -> list
```

### migrate

```python
def migrate(connection: sqlite3.Connection, profile=None) -> dict
```

Apply the migration. Returns what was done. Idempotent.

### main

```python
def main() -> None
```

[Back to the index](../README.md)
