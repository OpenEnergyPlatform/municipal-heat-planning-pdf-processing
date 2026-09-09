# profiles.kwp.migrate_convoy_group_keys

`profiles/kwp/migrate_convoy_group_keys.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

migrate_convoy_group_keys.py – Regroup convoy documents by their smallest ags.

A convoy plan is one document for many municipalities. Its `group_key` used to
be the ags of whichever register row happened to be registered first, which ties
version detection to KWW's row order: reorder the sheet and next year's edition
lands in a different group, so both editions stay "current" side by side.

This recomputes every document's group_key from the register the same way
KwwSource does now, then re-links the versions.

    python -m profiles.kwp.migrate_convoy_group_keys data/KWP.db kww.xlsx
    python -m profiles.kwp.migrate_convoy_group_keys data/KWP.db kww.xlsx --apply

Author: Felix Vossel

## Functions

### planned_keys

```python
def planned_keys(excel_file: Path) -> dict
```

{filename: group_key} the current code would assign.

### changes

```python
def changes(connection: sqlite3.Connection, wanted: dict) -> list
```

(id, filename, old_key, new_key) for every document whose key moves.

### migrate

```python
def migrate(connection: sqlite3.Connection, wanted: dict) -> list
```

Apply the new keys and re-link versions. Returns what changed.

### main

```python
def main() -> None
```

[Back to the index](../README.md)
