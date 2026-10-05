"""
catalog.py – How documents present themselves in the picker when nothing is
known about them but what the source wrote into DocumentMeta.

Every filter the profile declares is filled from the DocumentMeta column of
the same name. So a profile that extends this one adds a column to its
schema, lets its source fill it, declares the facet, and has the filter.

Author: Felix Vossel
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from docpipe.inference.catalog import Catalog
from docpipe.store import schema


class MetaCatalog(Catalog):
    """The Documents table with the profile's DocumentMeta beside it."""

    def _meta_columns(self, conn: sqlite3.Connection) -> list:
        return sorted(schema.columns(conn, "DocumentMeta") - {"document"})

    def rows(self, conn: sqlite3.Connection,
             include_superseded: bool = False) -> list:
        where = "" if include_superseded else "WHERE d.is_current = 1"
        columns = self._meta_columns(conn)
        meta = "".join(f', m."{column}"' for column in columns)
        join = ("LEFT JOIN DocumentMeta m ON m.document = d.id"
                if columns else "")
        return conn.execute(f"""
            SELECT d.id, d.external_id, d.group_key, d.filename, d.published,
                   d.num_pages, d.is_current, d.supersedes{meta}
            FROM Documents d
            {join}
            {where}
            ORDER BY d.is_current DESC, d.published DESC, d.filename
        """).fetchall()

    def facet_values(self, conn: sqlite3.Connection, rows) -> dict:
        """document id -> {facet field: [value]}, for the facets that are a
        DocumentMeta column."""
        fields = [facet.field for facet in self.facets
                  if facet.field in self._meta_columns(conn)]
        out = {}
        for row in rows:
            out[row["id"]] = {field: [str(row[field])] for field in fields
                              if row[field] not in (None, "")}
        return out

    def label(self, row, facets: Optional[dict] = None) -> str:
        """The title, else the file name. No current/old tag: a folder has
        no versions, every file is its own document."""
        title = row["title"] if "title" in row.keys() else None
        return str(title or Path(row["filename"] or "").stem
                   or row["external_id"] or f"#{row['id']}")


CATALOG = MetaCatalog
