"""
db.py – Read-only database access for the inference app.

Opens KWP.db in read-only mode (never writes) and provides the queries the app
needs: list documents for the picker, resolve the set of FAISS ids belonging to
a (document, scope) selection, and fetch displayable content + citation for a
retrieved owner (section / table / figure).

The candidate-id query generalizes the 3-way UNION pattern from
scripts/chunkingandembedding/database.py (_DOCUMENT_FAISS_IDS_SQL) by adding a
per-branch embedding_type filter, so a scope selection maps precisely onto the
Embeddings rows it should search.

Author: Felix Vossel
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

from .config import (
    SECTION_EMBEDDING_TYPES,
    TABLE_EMBEDDING_TYPES,
    FIGURE_EMBEDDING_TYPES,
)


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """
    Open a read-only connection to KWP.db.

    Uses a `file:...?mode=ro` URI so the app can never write to the
    authoritative database, and so it does not take a write lock that could
    contend with the batch pipeline running against the same file.
    """
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Document picker
# ---------------------------------------------------------------------------

def list_documents(
    conn: sqlite3.Connection,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    """
    Documents for the picker, newest/current first.

    Joins the municipality name (via municipality_ags) and organisation unit
    name for a human-readable label. When include_superseded is False, only
    current versions (is_current=1) are returned.

    Returns rows with keys: id, filename, published, num_pages,
    municipality_ags, is_current, municipality_name, organisation_unit_name.
    """
    where = "" if include_superseded else "WHERE d.is_current = 1"
    sql = f"""
        SELECT d.id,
               d.filename,
               d.published,
               d.num_pages,
               d.municipality_ags,
               d.is_current,
               m.name AS municipality_name,
               o.name AS organisation_unit_name
        FROM Documents d
        LEFT JOIN Municipalities m   ON d.municipality_ags = m.ags
        LEFT JOIN OrganisationUnits o ON d.organisation_unit = o.id
        {where}
        ORDER BY d.is_current DESC, d.published DESC, d.filename
    """
    return conn.execute(sql).fetchall()


_KONVOI_DROP_PREFIX = {"waermeplan", "waermepaln", "wärmeplan", "energiekonzept", "kwp"}


def _konvoi_lead(filename: str) -> str:
    """
    Best-effort convoy name from a `*_konvoi_*` filename.

    Member municipalities of a joint ("Konvoi") plan are each mapped to the same
    convoy Document by their own ags, so the picker would otherwise show a member
    name (e.g. "Gemmrigheim") for a plan actually led by another town. Strip the
    known plan-type prefix, the trailing date/quarter, and the "konvoi" marker;
    what remains is the convoy lead (e.g. waermeplan_konvoi_hessigheim_20260401 →
    "Hessigheim"). Returns "" if nothing sensible is left.
    """
    stem = (filename or "").rsplit(".", 1)[0]
    out = []
    for tok in re.split(r"[_\s]+", stem):
        t = tok.strip()
        tl = t.lower()
        if not t or tl in _KONVOI_DROP_PREFIX or tl == "konvoi":
            continue
        if re.fullmatch(r"\d{6,8}", t) or re.fullmatch(r"\d{4}q[1-4]", tl):
            continue  # date (20260401 / 250327) or quarter (2024q2)
        out.append(t)
    return " ".join(out).strip().title()


def document_label(row: sqlite3.Row) -> str:
    """Build a readable picker label from a list_documents() row."""
    name = row["municipality_name"] or row["organisation_unit_name"] or row["filename"]
    parts = [str(name)]
    if row["organisation_unit_name"] and row["municipality_name"]:
        parts.append(f"({row['organisation_unit_name']})")
    if row["published"]:
        parts.append(str(row["published"]))
    # Flag joint/convoy plans so a member-municipality label is not mistaken for
    # a standalone plan (see _konvoi_lead).
    filename = row["filename"] or ""
    if "konvoi" in filename.lower():
        lead = _konvoi_lead(filename)
        parts.append(f"Konvoi: {lead}" if lead else "Konvoi")
    parts.append("(aktuell)" if row["is_current"] else "(alt)")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Candidate FAISS ids for a (document, scope) selection
# ---------------------------------------------------------------------------

def get_candidate_faiss_ids(
    conn: sqlite3.Connection,
    document_id: int,
    embedding_types: list[str],
) -> list[tuple[int, str, str, int]]:
    """
    Every (faiss_id, embedding_type, owner_kind, owner_id) belonging to
    `document_id` whose embedding_type is in `embedding_types`, across all three
    owner kinds (section / table / figure).

    Only owner-kind branches whose valid types intersect `embedding_types` are
    included, so selecting e.g. only "section_title" scans just the section
    branch. sqlite3 cannot bind a list into `IN (...)`, so the placeholder lists
    are built per branch and the parameters flattened.
    """
    wanted = set(embedding_types)
    section_types = sorted(wanted & SECTION_EMBEDDING_TYPES)
    table_types   = sorted(wanted & TABLE_EMBEDDING_TYPES)
    figure_types  = sorted(wanted & FIGURE_EMBEDDING_TYPES)

    branches: list[str] = []
    params: list = []

    if section_types:
        ph = ",".join("?" * len(section_types))
        branches.append(
            "SELECT e.faiss_id, e.embedding_type, e.owner_kind, e.owner_id "
            "FROM Embeddings e "
            "JOIN Sections s ON e.owner_kind = 'section' AND e.owner_id = s.id "
            f"WHERE s.document = ? AND e.embedding_type IN ({ph})"
        )
        params.extend([document_id, *section_types])

    if table_types:
        ph = ",".join("?" * len(table_types))
        branches.append(
            "SELECT e.faiss_id, e.embedding_type, e.owner_kind, e.owner_id "
            "FROM Embeddings e "
            "JOIN Tables t ON e.owner_kind = 'table' AND e.owner_id = t.id "
            "JOIN Sections s ON t.section = s.id "
            f"WHERE s.document = ? AND e.embedding_type IN ({ph})"
        )
        params.extend([document_id, *table_types])

    if figure_types:
        ph = ",".join("?" * len(figure_types))
        branches.append(
            "SELECT e.faiss_id, e.embedding_type, e.owner_kind, e.owner_id "
            "FROM Embeddings e "
            "JOIN Images i ON e.owner_kind = 'figure' AND e.owner_id = i.id "
            "JOIN Sections s ON i.section = s.id "
            f"WHERE s.document = ? AND e.embedding_type IN ({ph})"
        )
        params.extend([document_id, *figure_types])

    if not branches:
        return []

    sql = " UNION ALL ".join(branches)
    return [
        (int(r[0]), str(r[1]), str(r[2]), int(r[3]))
        for r in conn.execute(sql, params).fetchall()
    ]


# ---------------------------------------------------------------------------
# Content + citation for a retrieved owner
# ---------------------------------------------------------------------------

def _parent_section(conn: sqlite3.Connection, section_id: int) -> tuple[Optional[int], Optional[str]]:
    """(section_number, title) of the owning Section, for table/figure citations."""
    row = conn.execute(
        "SELECT section_number, title FROM Sections WHERE id = ?", (section_id,)
    ).fetchone()
    if row is None:
        return None, None
    return row["section_number"], row["title"]


def fetch_owner_content(
    conn: sqlite3.Connection,
    owner_kind: str,
    owner_id: int,
) -> Optional[dict]:
    """
    Fetch displayable content + citation fields for one retrieved owner.

    Returns a uniform dict:
        {owner_kind, owner_id, title, text, page_number, image_path,
         section_number, section_title, document_id}
    image_path is None for section owners; for table/figure owners it is the
    stored crop path made **relative to IMAGE_ROOT** (i.e. prefixed with the
    document's asset folder: `<filename-without-.pdf>/images/..`), so the app
    can resolve it directly. Returns None if the row vanished (should not happen
    for a consistent DB, but guards against races).
    """
    if owner_kind == "section":
        row = conn.execute(
            "SELECT title, content, page_number, document, section_number "
            "FROM Sections WHERE id = ?",
            (owner_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "owner_kind": "section",
            "owner_id": owner_id,
            "title": row["title"],
            "text": row["content"] or "",
            "page_number": row["page_number"],
            "image_path": None,
            "section_number": row["section_number"],
            "section_title": row["title"],
            "document_id": row["document"],
        }

    if owner_kind == "table":
        row = conn.execute(
            "SELECT caption, markdown, page_number, path, section "
            "FROM Tables WHERE id = ?",
            (owner_id,),
        ).fetchone()
        if row is None:
            return None
        sec_num, sec_title = _parent_section(conn, row["section"])
        doc_id = _section_document(conn, row["section"])
        return {
            "owner_kind": "table",
            "owner_id": owner_id,
            "title": row["caption"],
            "text": row["markdown"] or "",
            "page_number": row["page_number"],
            "image_path": _asset_path(_document_folder(conn, doc_id), row["path"]),
            "section_number": sec_num,
            "section_title": sec_title,
            "document_id": doc_id,
        }

    if owner_kind == "figure":
        row = conn.execute(
            "SELECT caption, description, page_number, path, section "
            "FROM Images WHERE id = ?",
            (owner_id,),
        ).fetchone()
        if row is None:
            return None
        sec_num, sec_title = _parent_section(conn, row["section"])
        doc_id = _section_document(conn, row["section"])
        return {
            "owner_kind": "figure",
            "owner_id": owner_id,
            "title": row["caption"],
            "text": row["description"] or "",
            "page_number": row["page_number"],
            "image_path": _asset_path(_document_folder(conn, doc_id), row["path"]),
            "section_number": sec_num,
            "section_title": sec_title,
            "document_id": doc_id,
        }

    raise ValueError(f"unknown owner_kind: {owner_kind!r}")


def _section_document(conn: sqlite3.Connection, section_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT document FROM Sections WHERE id = ?", (section_id,)
    ).fetchone()
    return row["document"] if row else None


def _document_folder(conn: sqlite3.Connection, document_id: Optional[int]) -> Optional[str]:
    """
    Name of the on-disk folder holding a document's extracted assets.

    imageprocessing writes each document's crops under
    `<IMAGE_ROOT>/<filename-without-.pdf>/images/...`, so the folder is the
    Documents.filename with a trailing `.pdf` stripped. Folder names keep the
    exact (URL-encoded, e.g. ``ö`` → ``%c3%b6``) spelling stored in `filename`
    — do NOT re-encode.
    """
    if document_id is None:
        return None
    row = conn.execute(
        "SELECT filename FROM Documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None or not row["filename"]:
        return None
    fn = row["filename"]
    return fn[:-4] if fn.lower().endswith(".pdf") else fn


def _asset_path(folder: Optional[str], stored_path: Optional[str]) -> Optional[str]:
    """
    Join a document's asset `folder` with a stored `images/..` path into a path
    relative to IMAGE_ROOT (the app resolves it as `IMAGE_ROOT / result`).

    Falls back to the bare stored path if the folder is unknown (keeps the old
    behaviour rather than dropping the reference).
    """
    if not stored_path:
        return None
    return f"{folder}/{stored_path}" if folder else stored_path
