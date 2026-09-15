"""
catalog.py: Presents a corpus for selection.

Retrieval only ever needs a document id. Everything around that id,
what a document is called in the picker, which filters make sense
over the corpus, what to show about the selected one, is project
knowledge. The core supplies a plain default over the `Documents`
table; a profile replaces it with its own
(`profiles/<name>/catalog.py: CATALOG`) and fills the facets it
declared.

Author: Felix Vossel
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence


@dataclass
class Entry:
    """One selectable document, as the picker needs it."""
    id: int
    label: str
    # facet field -> the values this document has (a plan may cover several
    # municipalities, so a document can sit under more than one value)
    facets: dict = field(default_factory=dict)
    # (heading, lines) blocks shown for the selected document
    detail: Sequence = ()
    row: Any = None


def format_published(published: Any) -> str:
    """The stored publish token, readable: 20240708 → 2024-07-08, 2023q4 → 2023 Q4."""
    text = str(published or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    quarter = re.fullmatch(r"(\d{4})q([1-4])", text, re.IGNORECASE)
    if quarter:
        return f"{quarter.group(1)} Q{quarter.group(2)}"
    return text


class Catalog:
    """The generic catalog: the core Documents table and nothing else."""

    def __init__(self, profile=None):
        self.profile = profile

    @property
    def facets(self) -> Sequence:
        return tuple(getattr(self.profile, "facets", ()) or ())

    @property
    def document_noun(self) -> str:
        return getattr(self.profile, "document_noun", None) or "Dokument"

    def rows(self, conn: sqlite3.Connection,
             include_superseded: bool = False) -> list:
        """Documents for the picker, current ones first."""
        where = "" if include_superseded else "WHERE is_current = 1"
        return conn.execute(
            f"""SELECT id, external_id, group_key, filename, published, num_pages,
                       is_current, supersedes
                FROM Documents
                {where}
                ORDER BY is_current DESC, published DESC, filename"""
        ).fetchall()

    def facet_values(self, conn: sqlite3.Connection, rows: Sequence) -> dict:
        """document id -> {facet field: [values]}. The core knows no facets."""
        return {}

    def label(self, row, facets: Optional[dict] = None) -> str:
        name = Path(row["filename"] or "").stem or row["external_id"] or f"#{row['id']}"
        parts = [str(name)]
        published = format_published(row["published"])
        if published:
            parts.append(published)
        parts.append("(aktuell)" if row["is_current"] else "(alt)")
        return " · ".join(parts)

    def detail(self, row, facets: Optional[dict] = None) -> Sequence:
        return ()

    def entries(self, conn: sqlite3.Connection,
                include_superseded: bool = False) -> list:
        """Everything the picker shows, in one pass over the corpus."""
        rows = self.rows(conn, include_superseded)
        values = self.facet_values(conn, rows)
        out = []
        for row in rows:
            own = values.get(row["id"], {})
            out.append(Entry(id=row["id"], label=self.label(row, own), facets=own,
                             detail=self.detail(row, own), row=row))
        return out


def _sort_key(value):
    """Years newest first, everything else alphabetically."""
    text = str(value)
    if text.isdigit():
        return (0, -int(text), "")
    return (1, 0, text.casefold())


def facet_options(entries: Sequence[Entry], facets: Sequence) -> dict:
    """
    facet field -> its values across `entries`.

    A facet nothing carries a value for is left out entirely: a corpus whose
    project metadata was never imported should offer no filter rather than an
    empty one that silently matches nothing.
    """
    out = {}
    for facet in facets:
        values = {v for e in entries for v in e.facets.get(facet.field, ()) if v}
        if values:
            out[facet.field] = sorted(values, key=_sort_key)
    return out


def apply_filters(entries: Sequence[Entry], selections: Optional[dict]) -> list:
    """Entries matching every active filter — AND across facets, OR within one."""
    active = {f: set(v) for f, v in (selections or {}).items() if v}
    if not active:
        return list(entries)
    return [e for e in entries
            if all(chosen & set(e.facets.get(field, ()))
                   for field, chosen in active.items())]


def load_catalog(profile=None) -> Catalog:
    """The profile's catalog, or the generic one."""
    if profile is None:
        return Catalog()
    provided = profile.component("catalog", "CATALOG")
    if provided is None:
        return Catalog(profile)
    if isinstance(provided, Catalog):        # already built
        return provided
    if isinstance(provided, type) and issubclass(provided, Catalog):
        return provided(profile)
    raise TypeError(f"profiles.{profile.name}.catalog.CATALOG must be a Catalog "
                    f"(subclass or instance), got {provided!r}")
