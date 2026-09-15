"""
db.py – The queries retrieval needs: which vectors belong to a document, and
what text sits behind a hit. Nothing here knows what the documents are about.

Author: Felix Vossel
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

from ..captions import resolve_title
from .config import (
    SECTION_EMBEDDING_TYPES,
    TABLE_EMBEDDING_TYPES,
    FIGURE_EMBEDDING_TYPES,
)

def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """
    Open a read-only connection to a corpus database.

    The `mode=ro` URI keeps the app from ever writing to the authoritative
    database or taking a write lock that would contend with the batch pipeline
    running against the same file.
    """
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def get_candidate_faiss_ids(
    conn: sqlite3.Connection,
    document_id: int,
    embedding_types: list[str],
) -> list[tuple[int, str, str, int]]:
    """
    Every (faiss_id, embedding_type, owner_kind, owner_id) belonging to
    `document_id` whose embedding_type is in `embedding_types`, across all three
    owner kinds (section / table / figure). Empty list if no type matches.

    sqlite3 cannot bind a list into `IN (...)`, so the placeholder lists are
    built per branch and the parameters flattened.
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

_PLACEHOLDER_RE = re.compile(r"\[([a-z0-9_]+)\]")


def section_item_captions(conn: sqlite3.Connection, section_id: int,
                          content: Optional[str] = None) -> dict[str, str]:
    """block_id -> caption for every table and figure anchored in this section.

    With the section's own text in hand a caption Stage 2 failed to link is
    resolved from the sentence before the placeholder — the same rule
    fetch_owner_content uses, so the name a reader sees in the section and the
    title the table itself carries are one string and not two.
    """
    out: dict[str, str] = {}
    for row in conn.execute(
        "SELECT block_id, caption FROM Tables WHERE section = ? "
        "UNION ALL "
        "SELECT block_id, caption FROM Images WHERE section = ?",
        (section_id, section_id),
    ):
        block_id = row["block_id"]
        if not block_id:
            continue
        caption = (resolve_title(row["caption"], content, block_id) or "").strip()
        if caption:
            out[block_id] = caption
    return out


def annotate_placeholders(content: str, captions: dict[str, str]) -> str:
    """
    Name the figure a placeholder stands for: [p17_img1] → [p17_img1: Abbildung 2-3 …].

    The stored content keeps the bare id, which is right for the record but
    useless to a reader: the section says "wie Abbildung 2-3 verdeutlicht" and
    then shows a token that could be anything. The id stays, because it is the
    handle the model uses to ask for the picture itself (see request_item).
    """
    def _replacer(match: re.Match) -> str:
        caption = captions.get(match.group(1))
        return f"[{match.group(1)}: {caption}]" if caption else match.group(0)

    return _PLACEHOLDER_RE.sub(_replacer, content or "")


def request_item(conn: sqlite3.Connection, document_id: Optional[int],
                 block_id: str) -> Optional[dict]:
    """
    Look up one table/figure by the placeholder id the model quoted.

    Scoped to `document_id`: block ids are only unique within a document, and
    p17_img1 exists in nearly every plan.
    """
    block_id = (block_id or "").strip().strip("[]")
    if not block_id:
        return None
    for table, kind, text_col in (("Tables", "table", "markdown"),
                                  ("Images", "figure", "description")):
        row = conn.execute(
            f"SELECT i.id, i.caption, i.path, i.page_number, i.{text_col} AS text, i.section "
            f"FROM {table} i JOIN Sections s ON s.id = i.section "
            f"WHERE i.block_id = ? AND (? IS NULL OR s.document = ?)",
            (block_id, document_id, document_id),
        ).fetchone()
        if row is None:
            continue
        doc_id = document_id if document_id is not None else _section_document(conn, row["section"])
        return {
            "owner_kind": kind,
            "owner_id": row["id"],
            "block_id": block_id,
            "title": row["caption"],
            "text": row["text"] or "",
            "page_number": row["page_number"],
            "image_path": _asset_path(_document_folder(conn, doc_id), row["path"]),
            "document_id": doc_id,
        }
    return None


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
    image_path is None for section owners; for table/figure owners it is the crop
    path made RELATIVE TO IMAGE_ROOT. None if the row does not exist. Raises
    ValueError on an unknown owner_kind.
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
            "text": annotate_placeholders(
                row["content"] or "",
                section_item_captions(conn, owner_id, row["content"])),
            "page_number": row["page_number"],
            "image_path": None,
            "section_number": row["section_number"],
            "section_title": row["title"],
            "document_id": row["document"],
        }

    # Tables and figures: one join, not four statements. The section number,
    # the section title, the owning document and that document's asset folder
    # all hang off the same two rows, and reading them apart meant four NFS
    # round trips per owner, two of them the same Sections row twice.
    if owner_kind in ("table", "figure"):
        table, body = (("Tables", "markdown") if owner_kind == "table"
                       else ("Images", "description"))
        row = conn.execute(
            f"SELECT o.caption, o.block_id, o.{body} AS body, o.page_number, "
            f"       o.path, s.id AS section_id, s.section_number, "
            f"       s.title AS section_title, "
            f"       s.content AS section_content, s.document, d.filename "
            f"FROM {table} o "
            f"JOIN Sections s ON o.section = s.id "
            f"LEFT JOIN Documents d ON s.document = d.id "
            f"WHERE o.id = ?",
            (owner_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            # The stored caption where Stage 2 linked one, the sentence before
            # the placeholder where it linked a footnote instead. _source_of
            # puts this in front of the body, so whichever it is, it is
            # quotable and the year in it can be cited.
            "title": resolve_title(row["caption"], row["section_content"],
                                   row["block_id"]),
            "caption_stored": row["caption"],
            # Which section it stands in, and under which placeholder. The
            # section is where the sentence announcing the table lives, and
            # the placeholder is where in that section to look.
            "section_id": row["section_id"],
            "block_id": row["block_id"],
            "text": row["body"] or "",
            "page_number": row["page_number"],
            "image_path": _asset_path(_folder_name(row["filename"]), row["path"]),
            "section_number": row["section_number"],
            "section_title": row["section_title"],
            "document_id": row["document"],
        }

    raise ValueError(f"unknown owner_kind: {owner_kind!r}")

def _section_document(conn: sqlite3.Connection, section_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT document FROM Sections WHERE id = ?", (section_id,)
    ).fetchone()
    return row["document"] if row else None

def document_filename(conn: sqlite3.Connection, document_id: Optional[int]) -> Optional[str]:
    """The stored PDF filename for a document (used to build the source-PDF link)."""
    if document_id is None:
        return None
    row = conn.execute(
        "SELECT filename FROM Documents WHERE id = ?", (document_id,)
    ).fetchone()
    return row["filename"] if row and row["filename"] else None

def section_segments(
    conn: sqlite3.Connection, section_id: int
) -> list[tuple[int, str]]:
    """
    Raw, page-tagged text segments of a section (pre-refinement provenance):
    [(page_number, text), ...] in reading order, kind 'text' only. These carry
    the verbatim PDF-text-layer wording a `&search=` highlight must match, which
    the refined Sections.content may not. See pdf_link.locate_quote.

    NB `Segments.page` is a foreign key to `Pages.id`, NOT the human page number,
    so it is joined to `Pages` to return the real 1-based `page_number` the PDF
    viewer's `#page=` expects.
    """
    rows = conn.execute(
        "SELECT p.page_number AS page, s.text AS text "
        "FROM Segments s JOIN Pages p ON s.page = p.id "
        "WHERE s.section = ? AND s.kind = 'text' "
        "AND s.text IS NOT NULL AND s.text != '' "
        "ORDER BY s.ordinal",
        (section_id,),
    ).fetchall()
    return [(r["page"], r["text"]) for r in rows]

def section_segments_geo(
    conn: sqlite3.Connection, section_id: int
) -> list[tuple[int, str, Optional[list]]]:
    """
    Like `section_segments`, but each triple also carries the segment's stored
    `bbox`: a list of [x0, y0, x1, y1] rectangles in PDF points (top-left
    origin), or None. See pdf_link.best_segment_rects.

    On a pre-bbox database (no `bbox` column) every rects slot is None, so the
    caller falls back to the `&search=` phrase highlight.
    """
    try:
        rows = conn.execute(
            "SELECT p.page_number AS page, s.text AS text, s.bbox AS bbox "
            "FROM Segments s JOIN Pages p ON s.page = p.id "
            "WHERE s.section = ? AND s.kind = 'text' "
            "AND s.text IS NOT NULL AND s.text != '' "
            "ORDER BY s.ordinal",
            (section_id,),
        ).fetchall()
    except sqlite3.OperationalError:               # no `bbox` column yet
        return [(p, t, None) for (p, t) in section_segments(conn, section_id)]

    out: list[tuple[int, str, Optional[list]]] = []
    for r in rows:
        rects = None
        if r["bbox"]:
            try:
                rects = json.loads(r["bbox"])
            except (ValueError, TypeError):
                rects = None
        out.append((r["page"], r["text"], rects))
    return out

def _document_folder(conn: sqlite3.Connection, document_id: Optional[int]) -> Optional[str]:
    """
    Name of the on-disk folder holding a document's extracted assets: the
    Documents.filename with a trailing `.pdf` stripped.

    Folder names keep the exact (URL-encoded, e.g. ``ö`` → ``%c3%b6``) spelling
    stored in `filename` — do NOT re-encode.
    """
    if document_id is None:
        return None
    row = conn.execute(
        "SELECT filename FROM Documents WHERE id = ?", (document_id,)
    ).fetchone()
    return _folder_name(row["filename"] if row else None)


def _folder_name(filename: Optional[str]) -> Optional[str]:
    """The asset folder a stored PDF filename names: the same string without
    its `.pdf`. Split out so a query that already read `filename` in a join
    does not have to read it again."""
    if not filename:
        return None
    return filename[:-4] if filename.lower().endswith(".pdf") else filename

def _asset_path(folder: Optional[str], stored_path: Optional[str]) -> Optional[str]:
    """
    Join a document's asset `folder` with a stored `images/..` path into a path
    relative to IMAGE_ROOT. Falls back to the bare stored path if the folder is
    unknown; None if there is no stored path.
    """
    if not stored_path:
        return None
    return f"{folder}/{stored_path}" if folder else stored_path
