"""
request_log.py – Logging and response caching for inference app requests.

Maintains a separate SQLite database with two tables:
  - requests: Full log of every request (plan_id, query, scopes, timestamp, latency, stats, errors)
  - response_cache: Query-response pairs keyed by (plan_id, query_key) for fast hits

Errors are logged but NOT cached — failed queries retry on next occurrence.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
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
    conn.commit()
    return conn


def make_query_key(plan_id: int, phrase: Optional[str], scopes: list[str]) -> str:
    """
    Deterministic cache key over (plan_id, search phrase, scopes).

    Same query to different plans or with different scopes → different keys.
    """
    h = hashlib.sha256()
    h.update(str(plan_id).encode("utf-8"))
    h.update(b"\x00")
    if phrase:
        h.update(phrase.encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(sorted(scopes or []), separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


def get_cached_response(
    conn: sqlite3.Connection,
    plan_id: int,
    query_key: str
) -> Optional[dict]:
    """
    Return cached (answer, citations, n_findings) for a query, or None on a miss.

    Returns a dict with keys: answer, citations (list), n_findings.
    """
    row = conn.execute(
        "SELECT answer, citations_json, n_findings FROM response_cache "
        "WHERE plan_id = ? AND query_key = ?",
        (plan_id, query_key),
    ).fetchone()
    if row is None:
        return None
    try:
        return {
            "answer": row[0],
            "citations": json.loads(row[1]),
            "n_findings": row[2],
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
    """
    Log a single request. Returns the request_id.

    - Successful requests: n_hits, n_citations, answer_hash set; error_message=None
    - Failed requests: error_message set; other fields as available
    - Cache hits: cache_hit=True, usually no retrieval stats
    """
    conn.execute(
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
    return conn.lastrowid


def cache_response(
    conn: sqlite3.Connection,
    plan_id: int,
    query_key: str,
    answer: str,
    citations: list,
    n_findings: int,
) -> None:
    """
    Store a successful response in the cache.

    Idempotent — overwrites on repeat (same plan_id + query_key).
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO response_cache
        (plan_id, query_key, answer, citations_json, n_findings)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            query_key,
            answer,
            json.dumps(citations, separators=(",", ":"), ensure_ascii=False),
            n_findings,
        ),
    )
    conn.commit()
