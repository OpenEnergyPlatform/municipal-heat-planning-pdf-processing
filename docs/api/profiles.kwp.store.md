# profiles.kwp.store

`profiles/kwp/store.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

store.py – The project's own tables: organisations, municipalities and
their KWW metadata. The core never touches these.

Author: Felix Vossel

## Functions

### update_organisation_unit

```python
def update_organisation_unit(name: str, state: str, connection: sqlite3.Connection) -> int
```

Update or create an organizational unit (Organisationseinheiten) and return its ID.

Args:
    name: The name of the organizational unit.
    bundesland: The federal state (Bundesland) to which the organization belongs.
    connection: Active SQLite database connection.

Returns:
    The ID of the organizational unit (either newly created or existing).

Note:
    If an organizational unit with the same name and federal state already exists,
    its ID is returned without creating a duplicate.

### add_municipality

```python
def add_municipality(name: str, ags: str, orga_id: int, connection: sqlite3.Connection) -> None
```

Add a municipality (Gemeinden) to the database.

Args:
    name: The name of the municipality.
    orga_id: The ID of the associated organizational unit.
    connection: Active SQLite database connection.

Note:
    ags is the municipality's unique key; on a re-run the existing row is
    refreshed (ON CONFLICT(ags) DO UPDATE), so name / organisation_unit
    follow the latest Excel without tripping the UNIQUE(ags) constraint.

### ensure_municipality_meta_table

```python
def ensure_municipality_meta_table(columns: list, connection: sqlite3.Connection) -> None
```

Create the MunicipalityMeta table if absent. Idempotent (additive migration
for DBs that predate it).

`columns` is a list of (excel_column, db_column, sqltype) triples; only
db_column + sqltype are used here. sqltype "DATE" maps to TEXT (ISO string).
Keyed by `ags` (FK to Municipalities.ags — one metadata row per municipality).

### upsert_municipality_meta

```python
def upsert_municipality_meta(ags: int, values: dict, connection: sqlite3.Connection) -> None
```

Insert or replace the metadata row for `ags`. `values` maps db_column → value
(already coerced; None for missing). On a re-run the row is refreshed, so the
metadata follows the latest Excel.

[Back to the index](../README.md)
