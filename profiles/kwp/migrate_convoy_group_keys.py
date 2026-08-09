"""
migrate_convoy_group_keys.py – Regroup convoy documents by their smallest ags.

A convoy plan is one document for many municipalities. Its `group_key` used to
be the ags of whichever register row happened to be registered first, which ties
version detection to KWW's row order: reorder the sheet and next year's edition
lands in a different group, so both editions stay "current" side by side.

This recomputes every document's group_key from the register the same way
KwwSource does now, then re-links the versions.

    python -m profiles.kwp.migrate_convoy_group_keys data/KWP.db kww.xlsx
    python -m profiles.kwp.migrate_convoy_group_keys data/KWP.db kww.xlsx --apply

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from docpipe.store import documents as docs

from .source import group_keys_by_filename, load_and_filter_excel

log = logging.getLogger(__name__)


def planned_keys(excel_file: Path) -> dict:
    """{filename: group_key} the current code would assign."""
    rows = load_and_filter_excel(Path(excel_file)).to_dict("records")
    return group_keys_by_filename(rows)


def changes(connection: sqlite3.Connection, wanted: dict) -> list:
    """(id, filename, old_key, new_key) for every document whose key moves."""
    out = []
    for doc_id, filename, old in connection.execute(
            "SELECT id, filename, group_key FROM Documents ORDER BY id"):
        new = wanted.get(filename)
        if new is not None and new != old:
            out.append((doc_id, filename, old, new))
    return out


def migrate(connection: sqlite3.Connection, wanted: dict) -> list:
    """Apply the new keys and re-link versions. Returns what changed."""
    moved = changes(connection, wanted)
    for doc_id, _filename, _old, new in moved:
        connection.execute("UPDATE Documents SET group_key = ? WHERE id = ?",
                           (new, doc_id))
    docs.link_document_versions(connection)
    connection.commit()
    return moved


def main() -> None:
    p = argparse.ArgumentParser(
        prog="python -m profiles.kwp.migrate_convoy_group_keys",
        description="Regroup convoy documents by their smallest ags")
    p.add_argument("db", help="the SQLite corpus database")
    p.add_argument("excel", help="the KWW register the corpus was built from")
    p.add_argument("--apply", action="store_true",
                   help="perform the change (without this it only reports)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    wanted = planned_keys(Path(args.excel))
    with sqlite3.connect(args.db) as connection:
        moved = changes(connection, wanted)
        log.info("%d document(s) would change group:", len(moved))
        for _id, filename, old, new in moved[:40]:
            log.info("  %-58s %s -> %s", filename[:58], old, new)
        if len(moved) > 40:
            log.info("  ... and %d more", len(moved) - 40)

        unknown = connection.execute(
            "SELECT COUNT(*) FROM Documents WHERE filename NOT IN (%s)"
            % ",".join("?" * len(wanted)), list(wanted)).fetchone()[0] if wanted else 0
        if unknown:
            log.info("\n%d document(s) are not in this register and keep their key.",
                     unknown)

        if not args.apply:
            log.info("\nDry run. Re-run with --apply once a backup exists.")
            return

        migrate(connection, wanted)
        groups = connection.execute(
            "SELECT COUNT(*) FROM (SELECT group_key FROM Documents "
            "WHERE group_key IS NOT NULL GROUP BY group_key HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        current = connection.execute(
            "SELECT COUNT(*) FROM Documents WHERE is_current = 0").fetchone()[0]
        log.info("\nDone: %d group(s) now hold more than one version, "
                 "%d document(s) marked superseded.", groups, current)


if __name__ == "__main__":
    main()
