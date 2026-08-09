"""
query_cache.py – On-disk cache mapping a query to its embedding vector, so an
identical query skips the on-demand model load.

Stored in a separate SQLite file, never the authoritative KWP.db.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_cache (
    query_key  TEXT PRIMARY KEY,
    vector     BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the query cache database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def make_key(mode: str, text: Optional[str] = None, image_bytes: Optional[bytes] = None) -> str:
    """
    Deterministic key over the effective query input. `mode` distinguishes
    text-only / image-only / image+text so the same phrase embedded differently
    does not collide.
    """
    h = hashlib.sha256()
    h.update(mode.encode("utf-8"))
    h.update(b"\x00")
    if text:
        h.update(text.encode("utf-8"))
    h.update(b"\x00")
    if image_bytes:
        h.update(image_bytes)
    return h.hexdigest()


def get(conn: sqlite3.Connection, key: str) -> Optional[np.ndarray]:
    """Return the cached (float32) vector for `key`, or None on a miss."""
    row = conn.execute(
        "SELECT vector FROM query_cache WHERE query_key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return np.frombuffer(row[0], dtype="float32").copy()


def put(conn: sqlite3.Connection, key: str, vector: np.ndarray) -> None:
    """Store `vector` under `key` (idempotent; overwrites on repeat)."""
    blob = np.asarray(vector, dtype="float32").tobytes()
    conn.execute(
        "INSERT OR REPLACE INTO query_cache (query_key, vector) VALUES (?, ?)",
        (key, blob),
    )
    conn.commit()
