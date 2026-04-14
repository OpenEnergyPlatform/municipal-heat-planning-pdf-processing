"""
database.py – Step 2 and 4: Database operations.

Step 2: Insert Sections, Tables, Images from merged data.
        Documents are already populated by the fileprocessing module.
Step 4: Write FAISS embedding IDs back to the DB.

The database is the single source of truth for which items have been
embedded.  The embedding step queries the DB to determine what is
missing, and --force clears all embedding IDs before re-processing.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import sqlite3
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


def _delete_document_content(document_id: int, connection: sqlite3.Connection) -> None:
    """
    Delete all sections, tables, and images for a document.

    Used by --force to allow clean re-insertion.
    """
    connection.execute(
        "DELETE FROM Images WHERE section IN "
        "(SELECT id FROM Sections WHERE document = ?)",
        (document_id,),
    )
    connection.execute(
        "DELETE FROM Tables WHERE section IN "
        "(SELECT id FROM Sections WHERE document = ?)",
        (document_id,),
    )
    connection.execute(
        "DELETE FROM Sections WHERE document = ?",
        (document_id,),
    )


def _insert_sections(
    document_id: int,
    merged_data: dict,
    connection: sqlite3.Connection,
) -> None:
    """
    Insert all sections, tables, and images for one document.

    Sections are numbered by their index in the sections list.
    Tables and Images reference the section they belong to via foreign key.
    """
    for sec_idx, section in enumerate(merged_data.get("sections", [])):
        cursor = connection.execute(
            "INSERT INTO Sections (document, section_number, page_number, title) "
            "VALUES (?, ?, ?, ?)",
            (document_id, sec_idx, section.get("page_number", 0), section.get("title")),
        )
        section_id = cursor.lastrowid

        for t in section.get("tables", []):
            connection.execute(
                "INSERT INTO Tables (section, path, page_number, caption, markdown) "
                "VALUES (?, ?, ?, ?, ?)",
                (section_id, t.get("path", ""), t.get("page_number"),
                 t.get("caption"), t.get("markdown")),
            )

        for fig in section.get("figures", []):
            connection.execute(
                "INSERT INTO Images (section, path, page_number, caption, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (section_id, fig.get("path", ""), fig.get("page_number"),
                 fig.get("caption"), fig.get("description")),
            )


def update_database(
    db_path: Path,
    root_dir: Path,
    *,
    force: bool = False,
) -> None:
    """
    Read merged output.json for each PDF and insert sections, tables,
    and images into the database.

    Documents must already exist in the DB (created by fileprocessing).

    Args:
        db_path:   Path to the SQLite database file.
        root_dir:  Root directory containing PDF subdirectories.
        force:     Delete and re-insert even if sections already exist.
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

    with sqlite3.connect(db_path) as conn:
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
            log.info("[%d/%d] %s: %d sections, %d tables, %d images", i + 1, len(candidates), pdf_name, n_sec, n_tbl, n_fig)

    log.info("Step 2 complete.")


def get_existing_embeddings(
    db_path: Path,
    pdf_name: str,
) -> set[tuple[str, int, Optional[str]]]:
    """
    Query the DB for items that already have embeddings for a given PDF.

    Returns a set of (embedding_type, section_index, item_id) tuples
    that already have a FAISS ID in the database.
    """
    existing: set[tuple[str, int, Optional[str]]] = set()

    with sqlite3.connect(db_path) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return existing

        rows = conn.execute(
            "SELECT section_number, text_embedding, title_embedding "
            "FROM Sections WHERE document = ?",
            (doc_id,),
        ).fetchall()

        for section_number, text_emb, title_emb in rows:
            if text_emb is not None:
                existing.add((EMBEDDING_TYPE_SECTION_TEXT, section_number, None))
            if title_emb is not None:
                existing.add((EMBEDDING_TYPE_SECTION_TITLE, section_number, None))

        rows = conn.execute(
            "SELECT s.section_number, t.path, t.text_embedding, t.image_embedding "
            "FROM Tables t JOIN Sections s ON t.section = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ).fetchall()

        for section_number, path, text_emb, img_emb in rows:
            item_id = Path(path).stem
            if text_emb is not None:
                existing.add((EMBEDDING_TYPE_TABLE_TEXT, section_number, item_id))
            if img_emb is not None:
                existing.add((EMBEDDING_TYPE_TABLE_VL, section_number, item_id))

        rows = conn.execute(
            "SELECT s.section_number, i.path, i.text_embedding, i.image_embedding "
            "FROM Images i JOIN Sections s ON i.section = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ).fetchall()

        for section_number, path, text_emb, img_emb in rows:
            item_id = Path(path).stem
            if text_emb is not None:
                existing.add((EMBEDDING_TYPE_FIGURE_TEXT, section_number, item_id))
            if img_emb is not None:
                existing.add((EMBEDDING_TYPE_FIGURE_VL, section_number, item_id))

    return existing


def clear_embedding_ids(db_path: Path, pdf_name: str) -> list[int]:
    """
    Clear all embedding IDs for a given PDF and return the old FAISS IDs
    so they can be removed from the index.

    Args:
        db_path:   Path to the SQLite database file.
        pdf_name:  PDF directory name.

    Returns:
        List of FAISS IDs that were cleared from the DB.
    """
    old_ids: list[int] = []

    with sqlite3.connect(db_path) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return old_ids

        for row in conn.execute(
            "SELECT text_embedding, title_embedding FROM Sections WHERE document = ?",
            (doc_id,),
        ).fetchall():
            for val in row:
                if val is not None:
                    old_ids.append(val)

        for row in conn.execute(
            "SELECT t.text_embedding, t.image_embedding "
            "FROM Tables t JOIN Sections s ON t.section = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ).fetchall():
            for val in row:
                if val is not None:
                    old_ids.append(val)

        for row in conn.execute(
            "SELECT i.text_embedding, i.image_embedding "
            "FROM Images i JOIN Sections s ON i.section = s.id "
            "WHERE s.document = ?",
            (doc_id,),
        ).fetchall():
            for val in row:
                if val is not None:
                    old_ids.append(val)

        conn.execute(
            "UPDATE Sections SET text_embedding = NULL, title_embedding = NULL "
            "WHERE document = ?",
            (doc_id,),
        )
        conn.execute(
            "UPDATE Tables SET text_embedding = NULL, image_embedding = NULL "
            "WHERE section IN (SELECT id FROM Sections WHERE document = ?)",
            (doc_id,),
        )
        conn.execute(
            "UPDATE Images SET text_embedding = NULL, image_embedding = NULL "
            "WHERE section IN (SELECT id FROM Sections WHERE document = ?)",
            (doc_id,),
        )
        conn.commit()

    log.info("Cleared %d embedding IDs for '%s'", len(old_ids), pdf_name)
    return old_ids


def write_embedding_ids_batch(
    db_path: Path,
    pdf_name: str,
    records: list[tuple[str, int, Optional[str], int]],
) -> None:
    """
    Write multiple FAISS embedding IDs to the DB in a single transaction.

    Args:
        db_path:  Path to the SQLite database file.
        pdf_name: PDF directory name.
        records:  List of (embedding_type, section_index, item_id, faiss_id) tuples.
    """
    if not records:
        return

    with sqlite3.connect(db_path) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return

        section_cache: dict[int, Optional[int]] = {}

        for embedding_type, section_index, item_id, faiss_id in records:
            if section_index not in section_cache:
                row = conn.execute(
                    "SELECT id FROM Sections WHERE document = ? AND section_number = ?",
                    (doc_id, section_index),
                ).fetchone()
                section_cache[section_index] = row[0] if row else None

            section_db_id = section_cache[section_index]
            if section_db_id is None:
                continue

            if embedding_type == EMBEDDING_TYPE_SECTION_TEXT:
                conn.execute(
                    "UPDATE Sections SET text_embedding = ? WHERE id = ?",
                    (faiss_id, section_db_id),
                )
            elif embedding_type == EMBEDDING_TYPE_SECTION_TITLE:
                conn.execute(
                    "UPDATE Sections SET title_embedding = ? WHERE id = ?",
                    (faiss_id, section_db_id),
                )
            elif embedding_type == EMBEDDING_TYPE_TABLE_TEXT:
                conn.execute(
                    "UPDATE Tables SET text_embedding = ? WHERE section = ? AND path LIKE ?",
                    (faiss_id, section_db_id, "%" + item_id + "%"),
                )
            elif embedding_type == EMBEDDING_TYPE_TABLE_VL:
                conn.execute(
                    "UPDATE Tables SET image_embedding = ? WHERE section = ? AND path LIKE ?",
                    (faiss_id, section_db_id, "%" + item_id + "%"),
                )
            elif embedding_type == EMBEDDING_TYPE_FIGURE_TEXT:
                conn.execute(
                    "UPDATE Images SET text_embedding = ? WHERE section = ? AND path LIKE ?",
                    (faiss_id, section_db_id, "%" + item_id + "%"),
                )
            elif embedding_type == EMBEDDING_TYPE_FIGURE_VL:
                conn.execute(
                    "UPDATE Images SET image_embedding = ? WHERE section = ? AND path LIKE ?",
                    (faiss_id, section_db_id, "%" + item_id + "%"),
                )

        conn.commit()