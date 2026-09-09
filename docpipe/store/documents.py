"""
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
"""
from __future__ import annotations

import sqlite3
from itertools import groupby
from typing import Optional


def document_exists(filename: str, connection: sqlite3.Connection) -> bool:
    cursor = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM Documents WHERE filename = ?)", (filename,))
    return bool(cursor.fetchone()[0])


def add_document(filename: str, external_id: str, group_key: Optional[str],
                 published: Optional[str], num_pages: Optional[int],
                 added: Optional[str], meta: Optional[dict],
                 connection: sqlite3.Connection) -> int:
    """Insert one document and its profile metadata. Returns the new id."""
    document_id = connection.execute(
        """
        INSERT INTO Documents (filename, external_id, group_key, published, num_pages, added)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (filename, external_id, group_key, published, num_pages, added),
    ).fetchone()[0]
    if meta:
        upsert_document_meta(document_id, meta, connection)
    return document_id


def upsert_document_meta(document_id: int, values: dict,
                         connection: sqlite3.Connection) -> None:
    """Write the profile's per-document fields into its DocumentMeta table.

    The core knows the table only by name; which columns exist is the profile's
    business (profiles/<name>/schema.sql).
    """
    cols = list(values)
    assignments = ", ".join(f'"{c}" = excluded."{c}"' for c in cols)
    placeholders = ", ".join(["?"] * (len(cols) + 1))
    quoted = ", ".join(f'"{c}"' for c in ["document"] + cols)
    connection.execute(
        f'INSERT INTO DocumentMeta ({quoted}) VALUES ({placeholders}) '
        f'ON CONFLICT(document) DO UPDATE SET {assignments}',
        [document_id] + [values[c] for c in cols],
    )


def link_document_versions(connection: sqlite3.Connection) -> None:
    """
    Mark current vs. superseded document versions.

    Documents that share a `group_key` are versions of the same work — the
    profile decides what groups (a municipality for heat plans, a DOI for
    papers). Within each group the newest `published` date is the current
    version (`is_current`=1); every older one is marked `is_current`=0 and
    points at the next-older version via `supersedes` (NULL for the oldest).
    Documents without a group_key, or alone in their group, stay current with
    no predecessor.

    Idempotent: recomputes the whole grouping on every call.
    """
    rows = connection.execute(
        """
        SELECT id, group_key, COALESCE(published, '')
        FROM Documents
        WHERE group_key IS NOT NULL
        ORDER BY group_key, COALESCE(published, ''), id
        """
    ).fetchall()

    for _key, grp in groupby(rows, key=lambda r: r[1]):
        docs = list(grp)  # already oldest -> newest
        for i, (doc_id, _, _) in enumerate(docs):
            is_current = 1 if i == len(docs) - 1 else 0
            supersedes = docs[i - 1][0] if i > 0 else None
            connection.execute(
                "UPDATE Documents SET is_current = ?, supersedes = ? WHERE id = ?",
                (is_current, supersedes, doc_id),
            )
