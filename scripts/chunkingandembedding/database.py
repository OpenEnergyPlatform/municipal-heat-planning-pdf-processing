"""
database.py – Step 2 and 4: Database operations.

Step 2: Insert Sections (+ their Pages, SectionPages, Segments), Tables and
        Images from merged data. Documents are populated by fileprocessing.
Step 4: Write FAISS embedding IDs back to the DB (Embeddings table).

The database is the single source of truth for which items have been embedded.
The embedding step queries the DB to determine what is missing, and --force
clears all embeddings for a document before re-processing.

The schema is defined in data/KWP.db.sql (foreign keys + page-provenance
tables). Every connection enables `PRAGMA foreign_keys = ON`.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from .config import (
    MERGED_JSON,
    EMBEDDING_TYPE_SECTION_TEXT,
    EMBEDDING_TYPE_SECTION_TITLE,
    EMBEDDING_TYPE_TABLE_TEXT,
    EMBEDDING_TYPE_TABLE_VL,
    EMBEDDING_TYPE_FIGURE_TEXT,
    EMBEDDING_TYPE_FIGURE_VL,
)

log = logging.getLogger(__name__)

# Which owner kind each embedding type belongs to.
_SECTION_TYPES = {EMBEDDING_TYPE_SECTION_TEXT, EMBEDDING_TYPE_SECTION_TITLE}
_TABLE_TYPES = {EMBEDDING_TYPE_TABLE_TEXT, EMBEDDING_TYPE_TABLE_VL}
_FIGURE_TYPES = {EMBEDDING_TYPE_FIGURE_TEXT, EMBEDDING_TYPE_FIGURE_VL}

# All FAISS ids mapped to one document's items (section + table + figure owners).
_DOCUMENT_FAISS_IDS_SQL = (
    "SELECT e.faiss_id FROM Embeddings e JOIN Sections s "
    "  ON e.owner_kind = 'section' AND e.owner_id = s.id WHERE s.document = ? "
    "UNION ALL "
    "SELECT e.faiss_id FROM Embeddings e JOIN Tables t "
    "  ON e.owner_kind = 'table' AND e.owner_id = t.id "
    "JOIN Sections s ON t.section = s.id WHERE s.document = ? "
    "UNION ALL "
    "SELECT e.faiss_id FROM Embeddings e JOIN Images i "
    "  ON e.owner_kind = 'figure' AND e.owner_id = i.id "
    "JOIN Sections s ON i.section = s.id WHERE s.document = ?"
)


def _document_faiss_ids(doc_id: int, connection: sqlite3.Connection) -> list[int]:
    """Every FAISS id currently mapped to this document's items."""
    return [r[0] for r in connection.execute(
        _DOCUMENT_FAISS_IDS_SQL, (doc_id, doc_id, doc_id)
    ).fetchall()]


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _get_document_id(filename: str, connection: sqlite3.Connection) -> Optional[int]:
    """Look up the document ID by filename."""
    row = connection.execute(
        "SELECT id FROM Documents WHERE filename = ?", (filename,)
    ).fetchone()
    return row[0] if row else None


def _resolve_document_id(pdf_name: str, connection: sqlite3.Connection) -> Optional[int]:
    """
    Resolve a PDF directory name to a document ID.

    Tries pdf_name + '.pdf' first (the common case), then pdf_name alone.
    """
    doc_id = _get_document_id(pdf_name + ".pdf", connection)
    if doc_id is None:
        doc_id = _get_document_id(pdf_name, connection)
    return doc_id


def _sections_exist(document_id: int, connection: sqlite3.Connection) -> bool:
    """Check if sections for this document are already in the DB."""
    row = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM Sections WHERE document = ?)",
        (document_id,)
    ).fetchone()
    return bool(row[0])


def _page_id(
    document_id: int,
    page_number: Optional[int],
    connection: sqlite3.Connection,
    cache: dict[int, int],
) -> Optional[int]:
    """Get-or-create the Pages row for (document, page_number); cached per run."""
    if page_number is None:
        return None
    if page_number in cache:
        return cache[page_number]
    connection.execute(
        "INSERT OR IGNORE INTO Pages (document, page_number) VALUES (?, ?)",
        (document_id, page_number),
    )
    row = connection.execute(
        "SELECT id FROM Pages WHERE document = ? AND page_number = ?",
        (document_id, page_number),
    ).fetchone()
    cache[page_number] = row[0]
    return row[0]


# ---------------------------------------------------------------------------
# Delete (for --force)
# ---------------------------------------------------------------------------

def _delete_document_content(document_id: int, connection: sqlite3.Connection) -> None:
    """
    Delete all content for a document so it can be cleanly re-inserted.

    Embeddings are polymorphic (no FK), so they are deleted explicitly first;
    Sections/Pages cascade to their children (SectionPages, Segments, Tables,
    Images) via ON DELETE CASCADE.
    """
    _delete_document_embeddings(document_id, connection)
    connection.execute("DELETE FROM Sections WHERE document = ?", (document_id,))
    connection.execute("DELETE FROM Pages WHERE document = ?", (document_id,))


def _delete_document_embeddings(document_id: int, connection: sqlite3.Connection) -> None:
    """Delete every Embeddings row whose owner belongs to this document."""
    connection.execute(
        "DELETE FROM Embeddings WHERE owner_kind = 'section' AND owner_id IN "
        "(SELECT id FROM Sections WHERE document = ?)",
        (document_id,),
    )
    connection.execute(
        "DELETE FROM Embeddings WHERE owner_kind = 'table' AND owner_id IN "
        "(SELECT t.id FROM Tables t JOIN Sections s ON t.section = s.id "
        " WHERE s.document = ?)",
        (document_id,),
    )
    connection.execute(
        "DELETE FROM Embeddings WHERE owner_kind = 'figure' AND owner_id IN "
        "(SELECT i.id FROM Images i JOIN Sections s ON i.section = s.id "
        " WHERE s.document = ?)",
        (document_id,),
    )


# ---------------------------------------------------------------------------
# Insert (Step 2)
# ---------------------------------------------------------------------------

def _insert_sections(
    document_id: int,
    merged_data: dict,
    connection: sqlite3.Connection,
) -> None:
    """
    Insert all sections (with page provenance), tables and images for one
    document. Sections are numbered by their index in the sections list.
    """
    page_cache: dict[int, int] = {}

    for sec_idx, section in enumerate(merged_data.get("sections", [])):
        content = section.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(c) for c in content)

        cursor = connection.execute(
            "INSERT INTO Sections (document, section_number, title, content, page_number) "
            "VALUES (?, ?, ?, ?, ?)",
            (document_id, sec_idx, section.get("title"), content,
             section.get("page_number")),
        )
        section_id = cursor.lastrowid

        # SectionPages: the distinct pages this chunk covers.
        for pno in section.get("pages", []) or []:
            pid = _page_id(document_id, pno, connection, page_cache)
            if pid is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO SectionPages (section, page) VALUES (?, ?)",
                    (section_id, pid),
                )

        # Segments: ordered, page-tagged content pieces (fine provenance).
        for ordinal, seg in enumerate(section.get("segments", []) or []):
            if not isinstance(seg, dict):
                continue
            pid = _page_id(document_id, seg.get("page"), connection, page_cache)
            if pid is None:
                continue
            kind = seg.get("kind")
            if kind not in ("text", "table", "figure"):
                continue
            connection.execute(
                "INSERT INTO Segments (section, ordinal, page, kind, ref, text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (section_id, ordinal, pid, kind, seg.get("ref"), seg.get("text")),
            )

        for t in section.get("tables", []):
            connection.execute(
                "INSERT INTO Tables (section, block_id, path, page_number, caption, markdown) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (section_id, t.get("id"), t.get("path", ""), t.get("page_number"),
                 t.get("caption"), t.get("markdown")),
            )

        for fig in section.get("figures", []):
            connection.execute(
                "INSERT INTO Images (section, block_id, path, page_number, caption, description) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (section_id, fig.get("id"), fig.get("path", ""), fig.get("page_number"),
                 fig.get("caption"), fig.get("description")),
            )


def update_database(
    db_path: Path,
    root_dir: Path,
    *,
    force: bool = False,
) -> None:
    """
    Read merged output.json for each PDF and insert its sections, page
    provenance, tables and images into the database.

    Documents must already exist in the DB (created by fileprocessing).
    """
    root_dir = Path(root_dir)

    candidates = sorted(
        d for d in root_dir.iterdir()
        if d.is_dir() and (d / MERGED_JSON).exists()
    )

    if not candidates:
        log.warning("No PDF directories with merged output found in '%s'.", root_dir)
        return

    log.info("Step 2: Inserting sections for %d documents", len(candidates))

    with closing(connect(db_path)) as conn:
        for i, pdf_dir in enumerate(candidates):
            pdf_name = pdf_dir.name
            doc_id = _resolve_document_id(pdf_name, conn)

            if doc_id is None:
                log.warning(
                    "[%d/%d] Document not found in DB for '%s' – skipping",
                    i + 1, len(candidates), pdf_name,
                )
                continue

            if _sections_exist(doc_id, conn) and not force:
                log.debug("[%d/%d] '%s' already populated – skipping", i + 1, len(candidates), pdf_name)
                continue

            if force and _sections_exist(doc_id, conn):
                _delete_document_content(doc_id, conn)

            with open(pdf_dir / MERGED_JSON, "r", encoding="utf-8") as f:
                merged_data = json.load(f)

            _insert_sections(doc_id, merged_data, conn)
            conn.commit()

            n_sec = len(merged_data.get("sections", []))
            n_tbl = sum(len(s.get("tables", [])) for s in merged_data["sections"])
            n_fig = sum(len(s.get("figures", [])) for s in merged_data["sections"])
            n_seg = sum(len(s.get("segments", []) or []) for s in merged_data["sections"])
            log.info(
                "[%d/%d] %s: %d sections, %d tables, %d images, %d segments",
                i + 1, len(candidates), pdf_name, n_sec, n_tbl, n_fig, n_seg,
            )

    log.info("Step 2 complete.")


# ---------------------------------------------------------------------------
# Embeddings (Step 4)
# ---------------------------------------------------------------------------

def get_existing_embeddings(
    db_path: Path,
    pdf_name: str,
) -> set[tuple[str, int, Optional[str]]]:
    """
    Query the DB for items that already have embeddings for a given PDF.

    Returns a set of (embedding_type, section_index, item_id) tuples, where
    item_id is the table/figure block id (None for section-level embeddings).
    """
    existing: set[tuple[str, int, Optional[str]]] = set()

    with closing(connect(db_path)) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return existing

        # Section embeddings.
        for section_number, etype in conn.execute(
            "SELECT s.section_number, e.embedding_type "
            "FROM Embeddings e JOIN Sections s "
            "  ON e.owner_kind = 'section' AND e.owner_id = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ):
            existing.add((etype, section_number, None))

        # Table embeddings.
        for section_number, block_id, etype in conn.execute(
            "SELECT s.section_number, t.block_id, e.embedding_type "
            "FROM Embeddings e JOIN Tables t "
            "  ON e.owner_kind = 'table' AND e.owner_id = t.id "
            "JOIN Sections s ON t.section = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ):
            existing.add((etype, section_number, block_id))

        # Figure embeddings.
        for section_number, block_id, etype in conn.execute(
            "SELECT s.section_number, i.block_id, e.embedding_type "
            "FROM Embeddings e JOIN Images i "
            "  ON e.owner_kind = 'figure' AND e.owner_id = i.id "
            "JOIN Sections s ON i.section = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ):
            existing.add((etype, section_number, block_id))

    return existing


def clear_embedding_ids(db_path: Path, pdf_name: str) -> list[int]:
    """
    Clear all embeddings for a given PDF and return the old FAISS IDs so they
    can be removed from the index.
    """
    old_ids: list[int] = []

    with closing(connect(db_path)) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return old_ids

        old_ids = _document_faiss_ids(doc_id, conn)
        _delete_document_embeddings(doc_id, conn)
        conn.commit()

    log.info("Cleared %d embedding IDs for '%s'", len(old_ids), pdf_name)
    return old_ids


def get_document_faiss_ids(db_path: Path, pdf_name: str) -> list[int]:
    """
    Read-only snapshot of every FAISS id currently mapped to a document.

    The pipeline snapshots these BEFORE Step 2 deletes the Embeddings rows so
    Step 3 can still evict the now-stale vectors from the shared index — a full
    --force run would otherwise orphan them (the DB delete races ahead of the
    index cleanup).
    """
    with closing(connect(db_path)) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return []
        return _document_faiss_ids(doc_id, conn)


def next_faiss_id(db_path: Path) -> int:
    """
    Smallest FAISS id not currently claimed by any Embeddings row.

    The DB is the source of truth for id allocation. Seeding the next id from
    here (rather than from index.ntotal, a live vector *count*) prevents reusing
    an id still held by another document after a --force pass removed some
    vectors — which, with the v2 `faiss_id` PRIMARY KEY, would otherwise raise an
    IntegrityError and abort the run.
    """
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(faiss_id), -1) + 1 FROM Embeddings"
        ).fetchone()
    return int(row[0])


def write_embedding_ids_batch(
    db_path: Path,
    pdf_name: str,
    records: list[tuple[str, int, Optional[str], int]],
) -> None:
    """
    Write multiple FAISS embedding IDs to the DB in a single transaction.

    Args:
        records: list of (embedding_type, section_index, item_id, faiss_id).
                 item_id is the table/figure block id (None for sections).
    """
    if not records:
        return

    with closing(connect(db_path)) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return

        section_id_cache: dict[int, Optional[int]] = {}

        def _section_id(section_index: int) -> Optional[int]:
            if section_index not in section_id_cache:
                row = conn.execute(
                    "SELECT id FROM Sections WHERE document = ? AND section_number = ?",
                    (doc_id, section_index),
                ).fetchone()
                section_id_cache[section_index] = row[0] if row else None
            return section_id_cache[section_index]

        for embedding_type, section_index, item_id, faiss_id in records:
            section_db_id = _section_id(section_index)
            if section_db_id is None:
                continue

            if embedding_type in _SECTION_TYPES:
                owner_kind, owner_id = "section", section_db_id
            elif embedding_type in _TABLE_TYPES:
                owner_kind = "table"
                row = conn.execute(
                    "SELECT id FROM Tables WHERE section = ? AND block_id = ?",
                    (section_db_id, item_id),
                ).fetchone()
                owner_id = row[0] if row else None
            elif embedding_type in _FIGURE_TYPES:
                owner_kind = "figure"
                row = conn.execute(
                    "SELECT id FROM Images WHERE section = ? AND block_id = ?",
                    (section_db_id, item_id),
                ).fetchone()
                owner_id = row[0] if row else None
            else:
                continue

            if owner_id is None:
                continue

            conn.execute(
                "INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, owner_id) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(owner_kind, owner_id, embedding_type) "
                "DO UPDATE SET faiss_id = excluded.faiss_id",
                (faiss_id, embedding_type, owner_kind, owner_id),
            )

        conn.commit()
