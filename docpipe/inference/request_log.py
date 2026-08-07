"""
request_log.py – Request logging in a separate SQLite file.

Answers are deliberately NOT cached: follow-up queries ("schau noch einmal
nach") are context-dependent, and a cache keyed on the query text alone serves
an answer from a different conversation.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import sqlite3
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
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the request log database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


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
