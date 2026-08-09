"""
schema.py – Build a database from the core schema plus a profile's own.

The core tables are the same for every corpus; the profile adds its entities
and its per-document fields. Both are applied to one connection, in that
order, so the profile can reference core tables but not the other way round.

Author: Felix Vossel
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ..profile import Profile

CORE_SCHEMA = Path(__file__).resolve().parent / "schema.sql"
CORE_TABLES = ("Documents", "Pages", "Sections", "SectionPages", "Segments",
               "Tables", "Images", "Embeddings")


def core_sql() -> str:
    return CORE_SCHEMA.read_text(encoding="utf-8")


def profile_sql(profile: Optional[Profile]) -> str:
    if profile is None or profile.schema_sql is None:
        return ""
    return profile.schema_sql.read_text(encoding="utf-8")


def apply(connection: sqlite3.Connection, profile: Optional[Profile] = None) -> None:
    """Create every missing table. Idempotent (everything is IF NOT EXISTS)."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("BEGIN;\n" + core_sql() + profile_sql(profile) + "\nCOMMIT;")


def connect(path: Path, profile: Optional[Profile] = None) -> sqlite3.Connection:
    """Open (creating if needed) a database with core + profile schema applied."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    apply(connection, profile)
    return connection


def tables(connection: sqlite3.Connection) -> set:
    return {r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
