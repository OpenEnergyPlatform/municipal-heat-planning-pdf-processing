"""
query_cache.py – On-disk cache mapping a query to its embedding vector, so an
identical query skips the on-demand model load.

The key names the model and the vector size as well as the query: a vector
of another model is not an answer to the same question, and one file serves
whichever model is configured next.

Stored in a separate SQLite file, never the authoritative KWP.db.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from docpipe.embedding import config as embedding_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_cache (
    query_key  TEXT PRIMARY KEY,
    vector     BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path, create: bool = True) -> sqlite3.Connection:
    """Open the query cache database.

    `create=False` skips the DDL and its commit. That commit takes a write
    lock on a file every planning thread is reading, and a batch run opens one
    of these per document: the schema needs creating once, not a thousand
    times.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not create:
        return sqlite3.connect(path, check_same_thread=False)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def make_key(mode: str, text: Optional[str] = None,
             image_bytes: Optional[bytes] = None, *,
             model: Optional[str] = None, dim: Optional[int] = None) -> str:
    """
    Deterministic key over the effective query input. `mode` distinguishes
    text-only / image-only / image+text so the same phrase embedded differently
    does not collide.

    `model` and `dim` are the embedding model and the size of its vectors;
    left out, they are the configured ones, read now. Entries written under
    keys without them match nothing and are embedded again.
    """
    if model is None:
        model = embedding_config.EMBEDDING_MODEL
    if dim is None:
        dim = embedding_config.EMBEDDING_DIM
    h = hashlib.sha256()
    h.update(str(model).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(dim).encode("utf-8"))
    h.update(b"\x00")
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
    put_many(conn, [(key, vector)])


def put_many(conn: sqlite3.Connection, pairs) -> None:
    """Store many vectors in one transaction — one fsync, not one per vector."""
    rows = [(key, np.asarray(vector, dtype="float32").tobytes())
            for key, vector in pairs]
    if not rows:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO query_cache (query_key, vector) VALUES (?, ?)",
        rows,
    )
    conn.commit()
