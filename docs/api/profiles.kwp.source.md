# profiles.kwp.source

`profiles/kwp/source.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

source.py – Where heat plans come from: the KWW "Status quo KWP" sheet.

One Excel row is one municipality. Several rows can point at the same PDF (a
convoy plan), so the document is registered once while every row still gets its
municipality and its metadata.

Author: Felix Vossel

## Classes

### KwwSource

```python
class KwwSource(Source)
```

The KWW register as a document source.

#### KwwSource.\_\_init\_\_

```python
def __init__(self, excel_file: Path)
```

#### KwwSource.documents

```python
def documents(self, connection: sqlite3.Connection)
```

#### KwwSource.document_for

```python
def document_for(self, row: dict, connection: sqlite3.Connection) -> SourceDoc
```

#### KwwSource.after_document

```python
def after_document(self, connection: sqlite3.Connection, doc: SourceDoc) -> None
```

## Functions

### load_and_filter_excel

```python
def load_and_filter_excel(excel_file: Path) -> pd.DataFrame
```

Completed Wärmepläne ("Stand in der KWP" == "abgeschlossen") that have a PDF
link. Original KWW column names are kept (rows are consumed as dicts).

### coerce

```python
def coerce(value: Any, sqltype: str)
```

Excel cell → a SQLite-storable value (NaN/NaT → None) for the given type.

### extract_meta

```python
def extract_meta(row: dict) -> dict
```

{db_column: coerced value} for the metadata columns of one Excel row.

Columns the sheet does not carry are LEFT OUT rather than written as NULL.
The KWW export drops and renames columns between releases — August 2026 came
with 24 instead of 35 — and since the upsert writes every column it is
handed, a missing one would quietly erase what an earlier export stored for
every municipality in the register.

### missing_meta_columns

```python
def missing_meta_columns(frame) -> list
```

The metadata columns this export does not carry (their values are kept).

### filename_for

```python
def filename_for(row: dict) -> str
```

The local file name a register row resolves to (override or KWW link).

### group_keys_by_filename

```python
def group_keys_by_filename(rows: list) -> dict
```

{filename: group_key} with the group key being the SMALLEST ags among the
municipalities that share the file.

A convoy plan is one document for many municipalities, and the group key is
what makes a re-published plan a new version of the old one rather than a
second current document. Taking the ags of whichever row happened to come
first would tie that to KWW's row order: reorder the sheet and next year's
edition lands in a different group, so both editions stay "current" side by
side. The smallest ags of the group is a property of the group itself.

Where the sharing is a register error rather than a convoy, SHARED_FILE_OWNERS
names the municipality the document really belongs to — read off the document.
The smallest ags would pick the wrong one there; it did in all three known
cases.

### backfill_meta

```python
def backfill_meta(excel_file: Path, db_file: Path) -> int
```

Backfill MunicipalityMeta for municipalities ALREADY in the DB, from
`excel_file`, matched by ags. Additive and minimal-invasive: only writes
MunicipalityMeta — no downloads, no changes to Documents/Sections/
Embeddings. Returns the number of rows written.

Reads the full sheet (unfiltered) so a municipality's metadata is found even
if its own row would not pass the completed-plan import filter.

[Back to the index](../README.md)
