"""
catalog.py – How AR6 publications present themselves in the picker: by title
and year, filtered by year, venue and the scenarios they document.

Author: Felix Vossel
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from docpipe.inference.catalog import Catalog


class Ar6Catalog(Catalog):
    """The bibliographic view of the corpus."""

    def rows(self, conn: sqlite3.Connection,
             include_superseded: bool = False) -> list:
        """Publications for the picker, newest first. Rows carry the core
        columns plus the DocumentMeta ones."""
        where = "" if include_superseded else "WHERE d.is_current = 1"
        return conn.execute(f"""
            SELECT d.id,
                   d.external_id,
                   d.group_key,
                   d.filename,
                   d.published,
                   d.num_pages,
                   d.is_current,
                   d.supersedes,
                   m.doi,
                   m.title,
                   m.year,
                   m.venue,
                   m.is_oa,
                   m.scenario_count
            FROM Documents d
            LEFT JOIN DocumentMeta m ON m.document = d.id
            {where}
            ORDER BY d.is_current DESC, d.published DESC, m.title, d.filename
        """).fetchall()

    def facet_values(self, conn: sqlite3.Connection, rows) -> dict:
        """document id -> {year, venue, scenario}."""
        scenarios = _scenarios_by_document(conn)
        out = {}
        for row in rows:
            values = {"scenario": scenarios.get(row["id"], [])}
            if row["year"]:
                values["year"] = [str(row["year"])]
            if row["venue"]:
                values["venue"] = [row["venue"]]
            out[row["id"]] = values
        return out

    def label(self, row, facets: Optional[dict] = None) -> str:
        """Title and year — the DOI, then the crawl slug, while the title is
        unknown. No current/old tag: every publication is its own version
        group, so it would be on every entry."""
        name = (row["title"] or row["doi"] or Path(row["filename"] or "").stem
                or row["external_id"] or f"#{row['id']}")
        parts = [str(name)]
        if row["year"]:
            parts.append(str(row["year"]))
        return " · ".join(parts)

    def detail(self, row, facets: Optional[dict] = None):
        lines = []
        if row["venue"]:
            lines.append(f"Erschienen in: {row['venue']}")
        # The stored count is what the index claimed; the links are what was
        # imported. They agree, unless the corpus predates the link table.
        count = row["scenario_count"] or len((facets or {}).get("scenario", ()))
        if count:
            lines.append(f"Dokumentierte AR6-Szenarien: {count}")
        return (("📄 Publikation", lines),) if lines else ()


CATALOG = Ar6Catalog


def _scenarios_by_document(conn: sqlite3.Connection) -> dict:
    """document id -> the names of the AR6 scenarios it documents."""
    out: dict = {}
    for row in conn.execute("""
        SELECT ds.document AS document, s.name AS name
        FROM DocumentScenarios ds
        JOIN Scenarios s ON s.id = ds.scenario
        ORDER BY s.name
    """):
        out.setdefault(row["document"], []).append(row["name"])
    return out
