"""
database.py – Insert sections/tables/images from merged data, and write FAISS
embedding IDs back. Documents themselves are populated by fileprocessing.

The DB (schema: data/KWP.db.sql) is the source of truth for what has been
embedded and for FAISS id allocation.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from collections import Counter
import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Optional

from .config import (
    DOCUMENT_JSON,
    SECTIONS_JSON,
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

# Every per-document lookup below must drive from Sections, whose index narrows
# to the one document first. CROSS JOIN pins that order and is otherwise an
# ordinary inner join; with a plain JOIN, SQLite instead drives from Embeddings
# on owner_kind alone and rescans that whole partition once per document —
# 338 ms rather than 1.1 ms per document at corpus scale. Do not "simplify"
# these back to JOIN; test_database.py asserts the resulting query plans.

# Items of one document that already carry an embedding.
_EXISTING_SECTION_SQL = (
    "SELECT s.section_number, e.embedding_type "
    "FROM Sections s CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'section' AND e.owner_id = s.id "
    "WHERE s.document = ?"
)
_EXISTING_TABLE_SQL = (
    "SELECT s.section_number, t.block_id, e.embedding_type "
    "FROM Sections s CROSS JOIN Tables t ON t.section = s.id "
    "CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'table' AND e.owner_id = t.id "
    "WHERE s.document = ?"
)
_EXISTING_FIGURE_SQL = (
    "SELECT s.section_number, i.block_id, e.embedding_type "
    "FROM Sections s CROSS JOIN Images i ON i.section = s.id "
    "CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'figure' AND e.owner_id = i.id "
    "WHERE s.document = ?"
)

# All FAISS ids mapped to one document's items (section + table + figure owners).
_DOCUMENT_FAISS_IDS_SQL = (
    "SELECT e.faiss_id FROM Sections s CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'section' AND e.owner_id = s.id WHERE s.document = ? "
    "UNION ALL "
    "SELECT e.faiss_id FROM Sections s CROSS JOIN Tables t ON t.section = s.id "
    "CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'table' AND e.owner_id = t.id WHERE s.document = ? "
    "UNION ALL "
    "SELECT e.faiss_id FROM Sections s CROSS JOIN Images i ON i.section = s.id "
    "CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'figure' AND e.owner_id = i.id WHERE s.document = ?"
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
    # The embed step now prepares documents in a thread pool while the batches
    # it already has are being written back. sqlite3's default is to give up
    # after 5 s; a batch write on a half-gigabyte database over shared storage
    # can hold the lock longer than that, and the reader would fail rather than
    # wait for it.
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


_thread_state = threading.local()


def _worker_connection(db_path: Path) -> sqlite3.Connection:
    """The calling thread's connection to this DB, opened on first use.

    Each prepare worker asks two questions per document back to back, and every
    one of them used to cost a connect, two PRAGMAs and a close. One slot per
    thread: pointing at another database replaces the connection rather than
    piling connections up.
    """
    key = str(db_path)
    cached = getattr(_thread_state, "conn", None)
    if cached is not None:
        if cached[0] == key:
            return cached[1]
        cached[1].close()
    conn = connect(db_path)
    _thread_state.conn = (key, conn)
    return conn


def _ensure_bbox_columns(connection: sqlite3.Connection) -> None:
    """Add the `bbox` column to Segments/Tables/Images on a DB that predates it."""
    for table in ("Segments", "Tables", "Images"):
        cols = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if "bbox" not in cols:
            connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "bbox" TEXT')


def _bbox_json(item: dict) -> Optional[str]:
    """Serialise an item's `bbox` (a list of rects) to JSON text, or None."""
    b = item.get("bbox")
    return json.dumps(b, ensure_ascii=False) if b else None


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

    Embeddings are polymorphic (no FK) and must be deleted explicitly first;
    Sections/Pages then cascade to their children.
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

    A section's children go out per statement, not per row: the corpus holds
    hundreds of thousands of segments and one execute() each is that many
    round trips into sqlite for nothing.
    """
    # Segments.page / SectionPages.page are FKs to Pages.id, not page numbers.
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
        page_rows = []
        for pno in section.get("pages", []) or []:
            pid = _page_id(document_id, pno, connection, page_cache)
            if pid is not None:
                page_rows.append((section_id, pid))
        connection.executemany(
            "INSERT OR IGNORE INTO SectionPages (section, page) VALUES (?, ?)",
            page_rows,
        )

        # Segments: ordered, page-tagged content pieces (fine provenance).
        segment_rows = []
        for ordinal, seg in enumerate(section.get("segments", []) or []):
            if not isinstance(seg, dict):
                continue
            pid = _page_id(document_id, seg.get("page"), connection, page_cache)
            if pid is None:
                continue
            kind = seg.get("kind")
            if kind not in ("text", "table", "figure"):
                continue
            segment_rows.append(
                (section_id, ordinal, pid, kind, seg.get("ref"), seg.get("text"),
                 _bbox_json(seg))
            )
        connection.executemany(
            "INSERT INTO Segments (section, ordinal, page, kind, ref, text, bbox) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            segment_rows,
        )

        connection.executemany(
            "INSERT INTO Tables (section, block_id, path, page_number, caption, markdown, bbox) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(section_id, t.get("id"), t.get("path", ""), t.get("page_number"),
              t.get("caption"), t.get("markdown"), _bbox_json(t))
             for t in section.get("tables", [])],
        )

        connection.executemany(
            "INSERT INTO Images (section, block_id, path, page_number, caption, description, bbox) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(section_id, fig.get("id"), fig.get("path", ""), fig.get("page_number"),
              fig.get("caption"), fig.get("description"), _bbox_json(fig))
             for fig in section.get("figures", [])],
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
        if d.is_dir() and (d / DOCUMENT_JSON).exists()
    )

    if not candidates:
        log.warning("No PDF directories with merged output found in '%s'.", root_dir)
        return

    log.info("Step 2: Inserting sections for %d documents", len(candidates))

    with closing(connect(db_path)) as conn:
        _ensure_bbox_columns(conn)
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

            with open(pdf_dir / DOCUMENT_JSON, "r", encoding="utf-8") as f:
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
# Additive bbox backfill (non-destructive)
# ---------------------------------------------------------------------------

# SECTIONS_JSON, imported above, carries the raw geometry-bearing sections:
# the source of bbox. Refinement rewrites the text and drops the boxes.


def _norm_seg_text(text: Optional[str]) -> str:
    """Whitespace-collapsed key for matching a text segment across JSON/DB."""
    return re.sub(r"\s+", " ", text or "").strip()


def _bbox_lookups_from_stage3(stage3: dict) -> tuple[dict, dict]:
    """
    Build (media_by_id, text_by_page_text) bbox lookups from a Stage-3 doc.

    media_by_id:       block id           → bbox JSON  (tables + figures + media segments)
    text_by_page_text: (page, norm_text)  → bbox JSON  (text segments)
    """
    media_by_id: dict[str, str] = {}
    text_by_page_text: dict[tuple, str] = {}
    for section in stage3.get("sections", []):
        for item in (section.get("tables") or []) + (section.get("figures") or []):
            if isinstance(item, dict) and item.get("id") and item.get("bbox"):
                media_by_id[item["id"]] = json.dumps(item["bbox"], ensure_ascii=False)
        for seg in section.get("segments") or []:
            if not isinstance(seg, dict) or not seg.get("bbox"):
                continue
            bbox_json = json.dumps(seg["bbox"], ensure_ascii=False)
            if seg.get("kind") == "text":
                text_by_page_text[(seg.get("page"), _norm_seg_text(seg.get("text")))] = bbox_json
            elif seg.get("ref"):
                media_by_id.setdefault(seg["ref"], bbox_json)
    return media_by_id, text_by_page_text


def enrich_bbox(db_path: Path, root_dir: Path, *, force: bool = False) -> dict:
    """
    Backfill the `bbox` column on existing Segments/Tables/Images rows from
    Stage-3 outputs, updating that column only — no delete, re-embed or re-chunk.

    Requires Stage 3 to have been re-run so each doc's sections.json
    carries the geometry. `force` also re-derives rows that already have a bbox;
    by default those are skipped, so a partial run resumes. Returns a stats dict
    of updated counts.
    """
    root_dir = Path(root_dir)
    stats = {"documents": 0, "segments": 0, "tables": 0, "images": 0}

    candidates = sorted(
        d for d in root_dir.iterdir()
        if d.is_dir() and (d / SECTIONS_JSON).exists()
    )
    if not candidates:
        log.warning("enrich-bbox: no Stage-3 outputs found under '%s'.", root_dir)
        return stats

    log.info("enrich-bbox: %d documents", len(candidates))
    cond = "" if force else " AND bbox IS NULL"

    with closing(connect(db_path)) as conn:
        _ensure_bbox_columns(conn)
        for pdf_dir in candidates:
            doc_id = _resolve_document_id(pdf_dir.name, conn)
            if doc_id is None:
                continue

            with open(pdf_dir / SECTIONS_JSON, "r", encoding="utf-8") as f:
                stage3 = json.load(f)
            media_by_id, text_by_page_text = _bbox_lookups_from_stage3(stage3)
            if not media_by_id and not text_by_page_text:
                continue

            rows = conn.execute(
                "SELECT sg.id, p.page_number, sg.kind, sg.ref, sg.text "
                "FROM Segments sg "
                "JOIN Sections s ON sg.section = s.id "
                "JOIN Pages p ON sg.page = p.id "
                f"WHERE s.document = ?{cond}",
                (doc_id,),
            ).fetchall()
            for seg_id, page_number, kind, ref, text in rows:
                if kind == "text":
                    bbox_json = text_by_page_text.get((page_number, _norm_seg_text(text)))
                else:
                    bbox_json = media_by_id.get(ref)
                if bbox_json is not None:
                    conn.execute("UPDATE Segments SET bbox = ? WHERE id = ?",
                                 (bbox_json, seg_id))
                    stats["segments"] += 1

            for table, key in (("Tables", "tables"), ("Images", "images")):
                for row_id, block_id in conn.execute(
                    f"SELECT t.id, t.block_id FROM {table} t "
                    f"JOIN Sections s ON t.section = s.id "
                    f"WHERE s.document = ?{cond}",
                    (doc_id,),
                ).fetchall():
                    bbox_json = media_by_id.get(block_id)
                    if bbox_json is not None:
                        conn.execute(f"UPDATE {table} SET bbox = ? WHERE id = ?",
                                     (bbox_json, row_id))
                        stats[key] += 1

            conn.commit()
            stats["documents"] += 1

    log.info(
        "enrich-bbox complete: %d docs, %d segments, %d tables, %d images updated",
        stats["documents"], stats["segments"], stats["tables"], stats["images"],
    )
    return stats


# ---------------------------------------------------------------------------
# Embeddings (Step 4)
# ---------------------------------------------------------------------------

def get_existing_embeddings(
    db_path: Path,
    pdf_name: str,
    *,
    doc_id: Optional[int] = None,
) -> set[tuple[str, int, Optional[str]]]:
    """
    Items of this PDF that already have embeddings, as a set of
    (embedding_type, section_index, item_id) — item_id is the table/figure
    block id, None for section-level embeddings. Empty if the doc is unknown.

    Runs on the calling thread's connection. Pass `doc_id` when the caller has
    already resolved it — the prepare loop asks document_id() first.
    """
    existing: set[tuple[str, int, Optional[str]]] = set()

    conn = _worker_connection(db_path)
    if doc_id is None:
        doc_id = _resolve_document_id(pdf_name, conn)
    if doc_id is None:
        return existing

    for section_number, etype in conn.execute(_EXISTING_SECTION_SQL, (doc_id,)):
        existing.add((etype, section_number, None))

    for section_number, block_id, etype in conn.execute(
        _EXISTING_TABLE_SQL, (doc_id,)
    ):
        existing.add((etype, section_number, block_id))

    for section_number, block_id, etype in conn.execute(
        _EXISTING_FIGURE_SQL, (doc_id,)
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
    Read-only snapshot of every FAISS id currently mapped to a document; [] if
    the doc is unknown.

    Must be called BEFORE the db step's --force delete removes the Embeddings
    rows, or the ids are gone and their vectors are orphaned in the index.
    """
    with closing(connect(db_path)) as conn:
        doc_id = _resolve_document_id(pdf_name, conn)
        if doc_id is None:
            return []
        return _document_faiss_ids(doc_id, conn)


def document_id(db_path: Path, pdf_name: str) -> Optional[int]:
    """The Documents row id for this processed directory, or None.

    Asked BEFORE embedding: a directory whose document was never registered
    (renamed in the register, an import that failed, a leftover from an older
    corpus) produces perfectly good vectors that no row can ever point at.

    Shares the calling thread's connection with get_existing_embeddings, which
    the prepare loop calls straight afterwards.
    """
    return _resolve_document_id(pdf_name, _worker_connection(db_path))


def drop_embeddings_missing_from_index(db_path: Path, known_ids) -> int:
    """Delete Embeddings rows whose vector is not in the index. Returns the count.

    A DB row is written per batch, the index is persisted per flush chunk, so a
    crash between the two (an OOM kill, a node failure, a timeout) leaves rows
    pointing at vectors that never reached the file. The next run reads those
    rows as "already embedded" and skips the item forever: the DB says it is
    searchable, the index has nothing, and no error is ever raised. Reconciling
    at startup turns that silent hole into re-work.

    An EMPTY index is not treated as "nothing is embedded" — that is what a
    mistyped index path looks like, and it would delete every row in the
    database. It is refused loudly instead.
    """
    known = {int(i) for i in known_ids}
    if not known:
        log.warning("index holds no vectors — skipping the embedding "
                    "reconciliation instead of dropping every row")
        return 0
    with closing(connect(db_path)) as conn:
        conn.execute("CREATE TEMP TABLE known_ids (faiss_id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO known_ids VALUES (?)",
                         ((i,) for i in known))
        dropped = conn.execute(
            "DELETE FROM Embeddings WHERE faiss_id NOT IN "
            "(SELECT faiss_id FROM known_ids)").rowcount
        conn.commit()
    if dropped:
        log.warning("%d embedding row(s) had no vector in the index (a crash "
                    "between the DB write and the index save) — cleared, they "
                    "will be embedded again", dropped)
    return int(dropped)


def next_faiss_id(db_path: Path) -> int:
    """
    Smallest FAISS id not currently claimed by any Embeddings row.

    Seed id allocation from here, not from index.ntotal: ntotal is a live count
    and can dip below the high-water mark after an eviction, so it hands back an
    id another row still holds and the faiss_id PK rejects the insert.
    """
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(faiss_id), -1) + 1 FROM Embeddings"
        ).fetchone()
    return int(row[0])


_EMBEDDING_UPSERT_SQL = (
    "INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, owner_id) "
    "VALUES (?, ?, ?, ?) "
    "ON CONFLICT(owner_kind, owner_id, embedding_type) "
    "DO UPDATE SET faiss_id = excluded.faiss_id"
)


class EmbeddingWriter:
    """Writes FAISS ids for many batches and many documents over one connection.

    Batches are packed by text length and straddle documents freely, so a
    connection per (batch, document) pair came to roughly one connect, two
    PRAGMAs and a document lookup per embedding. What a document's rows are
    called cannot change while it is being embedded, so every lookup here is
    read once per document and kept.
    """

    def __init__(self, db_path: Path):
        self._conn = connect(db_path)
        self._doc_ids: dict[str, Optional[int]] = {}
        self._sections: dict[int, dict[int, int]] = {}
        self._blocks: dict[tuple[int, str], dict[tuple[int, Optional[str]], int]] = {}

    def __enter__(self) -> "EmbeddingWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _document_id(self, pdf_name: str) -> Optional[int]:
        if pdf_name not in self._doc_ids:
            self._doc_ids[pdf_name] = _resolve_document_id(pdf_name, self._conn)
        return self._doc_ids[pdf_name]

    def _section_ids(self, doc_id: int) -> dict[int, int]:
        """section_number → Sections.id, one query for the whole document."""
        cached = self._sections.get(doc_id)
        if cached is None:
            cached = self._sections[doc_id] = dict(self._conn.execute(
                "SELECT section_number, id FROM Sections WHERE document = ?",
                (doc_id,),
            ))
        return cached

    def _block_ids(self, doc_id: int, table: str) -> dict[tuple[int, Optional[str]], int]:
        """(Sections.id, block_id) → row id for one document's Tables or Images.

        The subquery keeps this one statement per document however many sections
        it has; a parameter list would run into SQLite's variable limit.
        """
        key = (doc_id, table)
        cached = self._blocks.get(key)
        if cached is None:
            cached = self._blocks[key] = {
                (section, block_id): row_id
                for section, block_id, row_id in self._conn.execute(
                    f"SELECT section, block_id, id FROM {table} WHERE section IN "
                    "(SELECT id FROM Sections WHERE document = ?)",
                    (doc_id,),
                )
            }
        return cached

    def write(
        self,
        pdf_name: str,
        records: list[tuple[str, int, Optional[str], int]],
    ) -> None:
        """Write one document's share of a batch; see write_embedding_ids_batch."""
        if not records:
            return

        doc_id = self._document_id(pdf_name)
        if doc_id is None:
            # This return used to be silent, and it cost 1096 vectors on every
            # single run: the batch is already IN the FAISS index by the time
            # this is called, so dropping its rows leaves that many vectors
            # nothing can resolve, and the next run embeds the same document
            # again. The embed step now skips such documents up front; this
            # stays as the backstop and says so out loud.
            log.error(
                "%s: no Documents row — %d embedding(s) already in the FAISS "
                "index have no row to hang off and cannot be found again. "
                "Register the document or remove its processed directory.",
                pdf_name, len(records))
            return

        sections = self._section_ids(doc_id)
        rows: list[tuple] = []
        unresolved: list[tuple] = []

        for embedding_type, section_index, item_id, faiss_id in records:
            section_db_id = sections.get(section_index)
            if section_db_id is None:
                unresolved.append((embedding_type, item_id))
                continue

            if embedding_type in _SECTION_TYPES:
                owner_kind, owner_id = "section", section_db_id
            elif embedding_type in _TABLE_TYPES:
                owner_kind = "table"
                owner_id = self._block_ids(doc_id, "Tables").get(
                    (section_db_id, item_id))
            elif embedding_type in _FIGURE_TYPES:
                owner_kind = "figure"
                owner_id = self._block_ids(doc_id, "Images").get(
                    (section_db_id, item_id))
            else:
                continue

            if owner_id is None:
                # The vector is in FAISS but has no row to hang off: a search
                # can return it and nothing can say what it is. Counted and
                # reported below rather than skipped in silence.
                unresolved.append((embedding_type, item_id))
                continue

            rows.append((faiss_id, embedding_type, owner_kind, owner_id))

        self._conn.executemany(_EMBEDDING_UPSERT_SQL, rows)

        if unresolved:
            kinds = Counter(t for t, _ in unresolved)
            log.warning(
                "%s: %d of %d embeddings have no owner row (%s). Those vectors "
                "stay in the FAISS index with nothing in the database to "
                "explain them — a search can return one and get no answer.",
                pdf_name, len(unresolved), len(records),
                ", ".join(f"{k}={n}" for k, n in sorted(kinds.items())),
            )

        self._conn.commit()


def write_embedding_ids_batch(
    db_path: Path,
    pdf_name: str,
    records: list[tuple[str, int, Optional[str], int]],
) -> None:
    """
    Write FAISS embedding ids to the DB in one transaction.

    `records` are (embedding_type, section_index, item_id, faiss_id); item_id is
    the table/figure block id, None for sections. Records whose owner row
    cannot be resolved are skipped and counted — the vector is already in the
    FAISS index, so skipping one means index and database have drifted apart,
    which is worth a line in the log rather than silence.

    One-shot wrapper. The embed loop keeps a single EmbeddingWriter for the
    whole chunk instead of reconnecting per batch and document.
    """
    if not records:
        return

    with EmbeddingWriter(db_path) as writer:
        writer.write(pdf_name, records)
