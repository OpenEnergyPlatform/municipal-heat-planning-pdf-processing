"""
request_log.py – Request logging + response caching, in a separate SQLite file.

Errors are logged but NOT cached — failed queries retry on next occurrence.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    query_text      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    scopes          TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    latency_ms      REAL,
    n_hits          INTEGER,
    n_citations     INTEGER,
    answer_hash     TEXT,
    error_message   TEXT,
    cache_hit       BOOLEAN
);

CREATE TABLE IF NOT EXISTS response_cache (
    cache_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    query_key       TEXT NOT NULL,
    answer          TEXT NOT NULL,
    answer_text     TEXT,
    citations_json  TEXT NOT NULL,
    n_findings      INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, query_key)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the request log database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    # Idempotent migration for DBs created before answer_text existed.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(response_cache)")}
    if "answer_text" not in cols:
        conn.execute("ALTER TABLE response_cache ADD COLUMN answer_text TEXT")
    conn.commit()
    return conn


def make_query_key(plan_id: int, text: Optional[str], scopes: list[str],
                   as_json: bool = False) -> str:
    """
    Deterministic cache key over (plan_id, user question, scopes, output format).

    `text` must be the RAW user question, NOT the LLM-generated search phrase,
    which is regenerated (and varies) on every turn. It is normalized —
    whitespace collapsed, case-folded — so trivially different spellings of the
    same question share a key.
    """
    norm = re.sub(r"\s+", " ", (text or "").strip()).casefold()
    h = hashlib.sha256()
    h.update(str(plan_id).encode("utf-8"))
    h.update(b"\x00")
    h.update(norm.encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(sorted(scopes or []), separators=(",", ":")).encode("utf-8"))
    h.update(b"\x00")
    h.update(b"json" if as_json else b"prose")
    return h.hexdigest()


def get_cached_response(
    conn: sqlite3.Connection,
    plan_id: int,
    query_key: str
) -> Optional[dict]:
    """
    Cached {answer, answer_text, citations, n_findings} for a query, or None on a
    miss (or unparseable row). `answer_text` is the prose form, falling back to
    `answer` for rows written before that column existed.
    """
    row = conn.execute(
        "SELECT answer, answer_text, citations_json, n_findings FROM response_cache "
        "WHERE plan_id = ? AND query_key = ?",
        (plan_id, query_key),
    ).fetchone()
    if row is None:
        return None
    try:
        return {
            "answer": row[0],
            "answer_text": row[1] if row[1] is not None else row[0],
            "citations": json.loads(row[2]),
            "n_findings": row[3],
        }
    except (json.JSONDecodeError, ValueError):
        return None


def log_request(
    conn: sqlite3.Connection,
    plan_id: int,
    query_text: str,
    mode: str,
    scopes: list[str],
    latency_ms: float,
    n_hits: Optional[int] = None,
    n_citations: Optional[int] = None,
    answer_hash: Optional[str] = None,
    error_message: Optional[str] = None,
    cache_hit: bool = False,
) -> int:
    """Log a single request. Returns the request_id."""
    cur = conn.execute(
        """
        INSERT INTO requests
        (plan_id, query_text, mode, scopes, latency_ms, n_hits, n_citations,
         answer_hash, error_message, cache_hit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            query_text,
            mode,
            json.dumps(sorted(scopes or []), separators=(",", ":")),
            latency_ms,
            n_hits,
            n_citations,
            answer_hash,
            error_message,
            cache_hit,
        ),
    )
    conn.commit()
    return cur.lastrowid


def cache_response(
    conn: sqlite3.Connection,
    plan_id: int,
    query_key: str,
    answer: str,
    answer_text: Optional[str],
    citations: list,
    n_findings: int,
) -> None:
    """
    Store a successful response in the cache. Idempotent — overwrites on a repeat
    (plan_id, query_key).

    `answer` is the displayed form (JSON when the JSON toggle is on, else prose);
    `answer_text` is the prose form kept for follow-up context.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO response_cache
        (plan_id, query_key, answer, answer_text, citations_json, n_findings)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            query_key,
            answer,
            answer_text,
            json.dumps(citations, separators=(",", ":"), ensure_ascii=False),
            n_findings,
        ),
    )
    conn.commit()
