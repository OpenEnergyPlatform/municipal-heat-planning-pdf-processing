"""
migrate_profile_split.py – Bring a pre-refactoring KWP.db up to the core schema.

Before the core/profile split, `Documents` carried the project's own fields
(organisation_unit, municipality_ags) and identified a document by its file
name. The core schema now keeps only identity (`external_id`) and versioning
(`group_key`) there, and everything municipal moved into the profile's own
`DocumentMeta`.

The migration is additive and runs in place: the two legacy columns are left
where they are. Nothing reads them any more, they are nullable so they cannot
block an insert, and removing them would mean rewriting a half-gigabyte
database to save two integers per row.

    python -m profiles.kwp.migrate_profile_split data/KWP.db            # dry run
    python -m profiles.kwp.migrate_profile_split data/KWP.db --apply

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LEGACY_COLUMNS = ("organisation_unit", "municipality_ags")


def columns(connection: sqlite3.Connection, table: str) -> list:
    return [r[1] for r in connection.execute(f"PRAGMA table_info({table})")]


def inspect(connection: sqlite3.Connection) -> dict:
    """What this database still lacks."""
    doc_cols = columns(connection, "Documents")
    if not doc_cols:
        raise SystemExit("no Documents table — this is not a corpus database")
    state = {
        "documents": connection.execute("SELECT COUNT(*) FROM Documents").fetchone()[0],
        "has_external_id": "external_id" in doc_cols,
        "has_group_key": "group_key" in doc_cols,
        "has_document_meta": bool(columns(connection, "DocumentMeta")),
        "legacy": [c for c in LEGACY_COLUMNS if c in doc_cols],
    }
    state["migrated"] = (state["has_external_id"] and state["has_group_key"]
                         and state["has_document_meta"])
    return state


def plan(state: dict) -> list:
    steps = []
    if not state["has_document_meta"]:
        steps.append("create DocumentMeta (and any other missing profile table)")
    if not state["has_external_id"]:
        steps.append("add Documents.external_id, fill it from filename")
    if not state["has_group_key"]:
        steps.append("add Documents.group_key, fill it from municipality_ags")
    if state["legacy"] and not state["has_document_meta"]:
        steps.append(f"copy {', '.join(state['legacy'])} into DocumentMeta")
    return steps


def migrate(connection: sqlite3.Connection, profile=None) -> dict:
    """Apply the migration. Returns what was done. Idempotent."""
    from docpipe import store
    from docpipe.profile import load_profile

    state = inspect(connection)
    done = {"external_id": 0, "group_key": 0, "document_meta": 0}
    if state["migrated"]:
        log.info("Already on the core schema — nothing to do.")
        return done

    doc_cols = columns(connection, "Documents")

    # The columns MUST exist before the core schema is applied. Its index
    # definition names the column in double quotes, and SQLite still honours the
    # old rule that a double-quoted identifier which matches no column is a
    # string literal — so applying it to a table without `group_key` builds an
    # index over the constant 'group_key'. That index then answers queries: the
    # column reads back as the word "group_key" and `WHERE group_key IS NULL`
    # matches nothing. Silent, and it survives until someone looks.
    if "external_id" not in doc_cols:
        connection.execute("ALTER TABLE Documents ADD COLUMN external_id TEXT")
    if "group_key" not in doc_cols:
        connection.execute("ALTER TABLE Documents ADD COLUMN group_key TEXT")
    # Drop it in case an earlier run already built the constant index.
    connection.execute("DROP INDEX IF EXISTS idx_documents_group")
    connection.commit()

    # Creates whatever is missing; every statement is CREATE ... IF NOT EXISTS,
    # so the existing tables and their data are untouched.
    store.apply(connection, profile or load_profile("kwp"))

    # The file name WAS the identity before; keep it, so a re-import recognises
    # every document it already has.
    done["external_id"] = connection.execute(
        "UPDATE Documents SET external_id = filename "
        "WHERE external_id IS NULL AND filename IS NOT NULL").rowcount

    if "municipality_ags" in doc_cols:
        done["group_key"] = connection.execute(
            "UPDATE Documents SET group_key = CAST(municipality_ags AS TEXT) "
            "WHERE group_key IS NULL AND municipality_ags IS NOT NULL").rowcount
        done["document_meta"] = connection.execute(
            "INSERT OR IGNORE INTO DocumentMeta "
            "(document, organisation_unit, municipality_ags) "
            "SELECT id, organisation_unit, municipality_ags FROM Documents").rowcount

    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS "
                       "idx_documents_external ON Documents(external_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS "
                       "idx_documents_group ON Documents(group_key)")
    connection.commit()
    return done


def main() -> None:
    p = argparse.ArgumentParser(
        prog="python -m profiles.kwp.migrate_profile_split",
        description="Bring a pre-refactoring KWP database up to the core schema")
    p.add_argument("db", help="the SQLite corpus database")
    p.add_argument("--apply", action="store_true",
                   help="perform the migration (without this it only reports)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    path = Path(args.db)
    if not path.is_file():
        raise SystemExit(f"no such database: {path}")

    with sqlite3.connect(path) as connection:
        state = inspect(connection)
        log.info("%s: %d documents", path.name, state["documents"])
        log.info("  external_id  %s", "yes" if state["has_external_id"] else "MISSING")
        log.info("  group_key    %s", "yes" if state["has_group_key"] else "MISSING")
        log.info("  DocumentMeta %s", "yes" if state["has_document_meta"] else "MISSING")
        if state["legacy"]:
            log.info("  legacy columns still on Documents: %s",
                     ", ".join(state["legacy"]))

        steps = plan(state)
        if not steps:
            log.info("\nAlready on the core schema — nothing to do.")
            return
        log.info("\nWould do:")
        for s in steps:
            log.info("  - %s", s)
        if not args.apply:
            log.info("\nDry run. Re-run with --apply once a backup exists.")
            return

        done = migrate(connection, None)
        log.info("\nDone: external_id %d, group_key %d, DocumentMeta %d row(s)",
                 done["external_id"], done["group_key"], done["document_meta"])
        after = inspect(connection)
        log.info("Now on the core schema: %s", "yes" if after["migrated"] else "NO")
        if not after["migrated"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
