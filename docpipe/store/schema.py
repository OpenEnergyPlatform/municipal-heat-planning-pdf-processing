"""
schema.py: Builds a database from the core schema plus a profile's
own schema.

The core tables (Documents, Pages, Sections, SectionPages, Segments,
Tables, Images, Embeddings) are the same for every corpus. A profile
adds its own entities and its per-document fields through its own
schema.sql. apply() runs both scripts against one connection inside
one transaction, core first and then the profile's, so a profile's
tables can reference the core tables but not the other way round.
connect() opens the database file, creating its parent directory and
applying both schemas if needed, and is idempotent because every
statement is written IF NOT EXISTS.

Author: Felix Vossel
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from ..profile import Profile

CORE_SCHEMA = Path(__file__).resolve().parent / "schema.sql"
CORE_TABLES = ("Documents", "Pages", "Sections", "SectionPages", "Segments",
               "Tables", "Images", "Embeddings", "Meta")

# The shape of the core tables, counted up whenever it changes. A database
# carries it as PRAGMA user_version. One made before the counter existed
# reads 0 and is brought up by `migrate`, which only ever adds: a column, a
# table. Nothing an older reader looks at is renamed or removed, so a
# database can be read by the code that wrote it and by this one.
FORMAT = 1
# (table, column, type) of every column a later format added.
ADDED_COLUMNS = (("Documents", "sha256", "TEXT"),
                 ("Documents", "bytes", "INTEGER"))


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
    migrate(connection)


def readonly_uri(path) -> str:
    """The address that opens a database file for reading only.

    The path is percent-encoded. Written into the address as it is, a `#`
    in it starts a fragment and a `?` a query: SQLite then opens another
    file than the one that was named, and without `mode=ro` makes it.
    """
    # abspath, not resolve(): a path that is not there yet stays relative
    # under resolve() on some platforms, and has no address then.
    return Path(os.path.abspath(path)).as_uri() + "?mode=ro"


def columns(connection: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in connection.execute(
        f'PRAGMA table_info("{table}")')}


def add_missing_column(connection: sqlite3.Connection, table: str,
                       column: str, kind: str) -> bool:
    """Add *column* to *table* where the table is there and lacks it.

    For a table of the profile's, which `CREATE TABLE IF NOT EXISTS` leaves
    as it was made: a source that fills a column the table was made without
    adds it first. A table that is not there is left alone, so that the write
    that needed it is the one to fail. Returns whether a column was added.
    """
    held = columns(connection, table)
    if not held or column in held:
        return False
    connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {kind}')
    return True


def migrate(connection: sqlite3.Connection) -> int:
    """Bring a database of an older format up to this one. Returns the
    format it had. Adds what is missing and touches nothing that is there."""
    had = connection.execute("PRAGMA user_version").fetchone()[0]
    for table, column, kind in ADDED_COLUMNS:
        if column not in columns(connection, table):
            connection.execute(
                f'ALTER TABLE "{table}" ADD COLUMN "{column}" {kind}')
    if had < FORMAT:
        connection.execute(f"PRAGMA user_version = {FORMAT}")
    connection.commit()
    return had


class MixedIndex(RuntimeError):
    """Vectors of one model were about to be appended to an index that holds
    vectors of another. Raised before a vector is written; says both."""

    def __init__(self, recorded: str, configured: str):
        self.recorded, self.configured = recorded, configured
        super().__init__(
            f"this index holds vectors of {recorded} and is continued with "
            f"{configured}: vectors of two models do not compare, so a "
            f"search over both is not one search. Nothing was written")


def note_embedding(connection: sqlite3.Connection, model: str, dim: int,
                   backend: str, max_token_length: int, version: str,
                   *, allow_mixed: bool = False) -> Optional[str]:
    """Write down what builds this database's index.

    An index that holds vectors of another model is not continued with this
    one: vectors of two models do not compare, so a search over both is not
    one search, and nothing in a vector says which model it is of. That
    raises `MixedIndex` naming both, and writes nothing. `allow_mixed` is the
    deliberate mixture: the first model stays the recorded one, the other is
    recorded beside it, and the sentence comes back for the caller's log. An
    index that holds no vectors may change its model.

    A database that records no model cannot be checked, whatever it holds:
    the configured one is recorded as the one that built it. Where it holds
    vectors the sentence says that, because nothing proved them to be its.
    """
    said = meta(connection)
    before = said.get("embedding/model")
    # A database that has no table of vectors yet holds none.
    holds = "Embeddings" in tables(connection) and connection.execute(
        'SELECT EXISTS(SELECT 1 FROM "Embeddings")').fetchone()[0]
    if before and before != str(model) and holds:
        if not allow_mixed:
            raise MixedIndex(before, str(model))
        others = [m for m in (said.get("embedding/also") or "").split("\n")
                  if m]
        if str(model) not in others:
            others.append(str(model))
        set_meta(connection, {"embedding/also": "\n".join(others),
                              "docpipe/version": version})
        return (f"this index holds vectors of {before} and is continued "
                f"with {model}: vectors of two models do not compare, so a "
                f"search over both is not one search")
    set_meta(connection, {"embedding/model": model, "embedding/dim": dim,
                          "embedding/backend": backend,
                          "embedding/max_token_length": max_token_length,
                          "docpipe/version": version})
    if holds and not before:
        return (f"this index holds vectors and records no embedding model, so "
                f"they cannot be checked against {model}: it is recorded as "
                f"the model that built the index")
    return None


def recorded_model(connection: sqlite3.Connection) -> Optional[str]:
    """The model the database says its index was built with, or None."""
    return meta(connection).get("embedding/model") or None


def embedding_mismatch(connection: sqlite3.Connection,
                       model: str) -> Optional[str]:
    """A sentence when a query would be embedded with another model than the
    index was built with, else None. For the query side to log; a database
    that records no model says nothing."""
    built = recorded_model(connection)
    if built and built != str(model):
        return (f"the index was built with {built}, queries are embedded "
                f"with {model}: their vectors do not compare")
    return None


def dimension_mismatch(connection: sqlite3.Connection,
                       dim: int) -> Optional[str]:
    """A sentence when a query would be embedded to another length than the
    vectors the index holds, else None. The same name can be set to another
    length, and vectors of two lengths do not compare. A database that
    records no dimension says nothing."""
    built = meta(connection).get("embedding/dim")
    if built is not None and str(built).strip() != str(dim):
        return (f"the index holds vectors of {built} dimensions, queries "
                f"are embedded to {dim}: their vectors do not compare")
    return None


def meta(connection: sqlite3.Connection) -> dict:
    """Everything the database says about itself; empty for one that was
    made before it said anything."""
    if "Meta" not in tables(connection):
        return {}
    return {row[0]: row[1] for row in connection.execute(
        'SELECT "key", "value" FROM "Meta"')}


def set_meta(connection: sqlite3.Connection, values: dict) -> None:
    connection.execute('CREATE TABLE IF NOT EXISTS "Meta" '
                       '("key" TEXT PRIMARY KEY, "value" TEXT)')
    connection.executemany(
        'INSERT INTO "Meta" ("key", "value") VALUES (?, ?) '
        'ON CONFLICT("key") DO UPDATE SET "value" = excluded."value"',
        [(key, None if value is None else str(value))
         for key, value in values.items()])
    connection.commit()


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
