"""
identity.py: Which value a harvested row is, and where its passage is now.

A row points at its passage with the database's own ids (`provenance`:
owner_kind, owner_id). Those are counters. Build the chunks of a document
again and every section, table and figure of it gets new ones, and a harvest
that was read from the old ones points at nothing. What does not move is
what the row says: the document and the words it quotes.

    tuple_id    a name for a row made from the document, the quote and the
                value as it was written. It survives a re-chunk, and a
                re-harvest that reads the same thing gives the same name, so
                a label, an export and a provenance record can hold on to it.
    reanchor    the passage of a row found again after the database was
                rebuilt: the one passage of its kind in the document that
                carries the quote. Run as a pass of its own
                (`python -m docpipe.extraction.identity DB HARVEST_DIR`); no
                other pass moves a row's address.

Neither adds a key to a row and neither judges one: a row whose passage is
not found again is left exactly as it is and counted.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from docpipe import jsonl
from docpipe.store.schema import readonly_uri
from docpipe.profile import (add_profile_argument, bind_command_line,
                             program, require_profile)

log = logging.getLogger(__name__)

TUPLE = "tuple"
OWNER_TABLES = {
    "section": 'SELECT "id" FROM "Sections" WHERE "document" = ?',
    "table": 'SELECT t."id" FROM "Tables" t JOIN "Sections" s '
             'ON s."id" = t."section" WHERE s."document" = ?',
    "figure": 'SELECT i."id" FROM "Images" i JOIN "Sections" s '
              'ON s."id" = i."section" WHERE s."document" = ?',
}


def _squash(text) -> str:
    return " ".join(str(text or "").split())


def said(row: dict):
    """The value as the document wrote it, else as it was read."""
    raw = row.get("value_raw")
    return raw if raw not in (None, "") else row.get("value")


def tuple_id(document: str, row: dict) -> str:
    """The name of one row: the document, its quote, its value.

    *document* is whatever names the document's bytes: the sha256 the
    database recorded, or the file name for a database that recorded none.
    """
    key = json.dumps([document, _squash(row.get("quote")), said(row)],
                     ensure_ascii=False, default=str)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def tuple_ids(document: str, rows: list) -> list:
    """One name per row, in order. A row that says exactly what an earlier
    one of the same document says is the second of that name: `<id>.2`."""
    seen: Counter = Counter()
    out = []
    for row in rows:
        name = tuple_id(document, row)
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}.{seen[name]}")
    return out


def owners_of_kind(connection: sqlite3.Connection, document_id,
                   kind: str) -> list:
    query = OWNER_TABLES.get(kind)
    if query is None:
        return []
    return [row[0] for row in connection.execute(query, (document_id,))]


def find_again(row: dict, connection: sqlite3.Connection,
               owner_sources: Callable, carries: Callable) -> Optional[tuple]:
    """(kind, id) of the passage that carries the row's quote now, or None.

    None when the row's own address still carries it, when no passage of its
    kind in the document does, and when more than one does and none of them
    is the row's own table or figure: a guess between two passages would be
    an address nobody read the value from.
    """
    provenance = row.get("provenance") or {}
    kind, owner = provenance.get("owner_kind"), provenance.get("owner_id")
    quote = row.get("quote") or ""
    if not kind or not quote:
        return None
    here = owner_sources([(kind, owner)]).get((kind, owner))
    if here is not None and carries(here.text or "", quote):
        return None
    candidates = owners_of_kind(connection, provenance.get("document_id"),
                                kind)
    found = [pair for pair, source in owner_sources(
        [(kind, candidate) for candidate in candidates]).items()
        if carries(source.text or "", quote)]
    if len(found) == 1:
        return found[0]
    return None


def reanchor_file(path: Path, connection: sqlite3.Connection,
                  owner_sources: Callable, carries: Callable,
                  *, write: bool = True) -> Counter:
    """Give every row of one harvest file whose passage moved its new
    address. Rows are counted, never dropped; the file is rewritten only
    when a row changed."""
    stats: Counter = Counter()
    lines = jsonl.read(path)
    out, changed = [], False
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        if not isinstance(row, dict) or row.get("kind") != TUPLE:
            out.append(line)
            continue
        stats["rows"] += 1
        again = find_again(row, connection, owner_sources, carries)
        provenance = row.get("provenance") or {}
        if again is None:
            pair = (provenance.get("owner_kind"), provenance.get("owner_id"))
            here = owner_sources([pair]).get(pair)
            still = here is not None and carries(here.text or "",
                                                 row.get("quote") or "")
            stats["rows whose passage is where it was" if still
                  else "rows whose passage was not found again"] += 1
            out.append(line)
            continue
        provenance["owner_id"] = again[1]
        stats["rows given their passage's new address"] += 1
        changed = True
        out.append(json.dumps(row, ensure_ascii=False))
    if changed and write:
        tmp = Path(path).with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(path)
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.extraction.identity"),
        description="After a database was rebuilt under a harvest: find "
                    "each row's passage again by its quote and write its "
                    "new address into the harvest file.")
    parser.add_argument("db", type=Path)
    parser.add_argument("harvest_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="count, write nothing")
    add_profile_argument(parser)
    bind_command_line(argv)      # before the stage is imported below
    args = parser.parse_args(argv)
    require_profile(args)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .pipeline import quote_in
    from .runner import make_owner_sources
    owner_sources = make_owner_sources(args.db)
    total: Counter = Counter()
    if not args.harvest_dir.is_dir():
        raise SystemExit(f"{args.harvest_dir} is not a directory: name the "
                         f"directory of the harvest")
    if not any(args.harvest_dir.glob("*.jsonl")):
        raise SystemExit(f"{args.harvest_dir} holds no harvest file "
                         f"(*.jsonl): there is nothing to find again")
    connection = sqlite3.connect(readonly_uri(args.db), uri=True)
    try:
        for path in sorted(args.harvest_dir.glob("*.jsonl")):
            total.update(reanchor_file(path, connection, owner_sources,
                                       quote_in, write=not args.dry_run))
            total["files"] += 1
    finally:
        connection.close()
    for name in sorted(total):
        log.info("%7d %s", total[name], name)
    if args.dry_run:
        log.info("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
