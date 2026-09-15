# docpipe.store.documents

`docpipe/store/documents.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

documents.py: Writes and reads the core's Documents table.

Nothing here knows what a document is about; a project's own fields
go into DocumentMeta, whose columns the profile defines. add_document
inserts a row into Documents and, when metadata is given, upserts the
matching DocumentMeta row through upsert_document_meta.

link_document_versions marks which document is the current version of
each group and which it supersedes. Documents that share a group_key
are versions of the same work; what a group is stays the profile's
choice (a municipality for heat plans, a DOI for papers). Within a
group, the document with the newest published date is current
(is_current = 1); every older document is marked is_current = 0 and
points at the next-older document through supersedes, which is NULL
for the oldest. A document with no group_key, or alone in its group,
stays current with no predecessor. The function is idempotent: it
recomputes the whole grouping on every call.

Author: Felix Vossel

## Functions

### document_exists

```python
def document_exists(filename: str, connection: sqlite3.Connection) -> bool
```

### add_document

```python
def add_document(filename: str, external_id: str, group_key: Optional[str],
                 published: Optional[str], num_pages: Optional[int],
                 added: Optional[str], meta: Optional[dict],
                 connection: sqlite3.Connection) -> int
```

Insert one document and its profile metadata. Returns the new id.

### upsert_document_meta

```python
def upsert_document_meta(document_id: int, values: dict,
                         connection: sqlite3.Connection) -> None
```

Write the profile's per-document fields into its DocumentMeta table.

The core knows the table only by name; which columns exist is the profile's
business (profiles/\<name>/schema.sql).

### link_document_versions

```python
def link_document_versions(connection: sqlite3.Connection) -> None
```

Mark current vs. superseded document versions.

Documents that share a `group_key` are versions of the same work — the
profile decides what groups (a municipality for heat plans, a DOI for
papers). Within each group the newest `published` date is the current
version (`is_current`=1); every older one is marked `is_current`=0 and
points at the next-older version via `supersedes` (NULL for the oldest).
Documents without a group_key, or alone in their group, stay current with
no predecessor.

Idempotent: recomputes the whole grouping on every call.

[Back to the index](../README.md)
