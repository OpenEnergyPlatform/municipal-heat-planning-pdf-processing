"""
cli.py: Command line for registering a profile's documents.

The work lives in `pipeline.py` (generic) and in the profile's `source.py`
(where its documents come from); this module is only the entry point. The
database and the PDF directory default to the profile's own.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional, Sequence

from ..profile import add_profile_argument, program, require_profile
from .pipeline import ingest

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=program("docpipe.ingest"),
        description="Download and register the source PDFs of a profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
docpipe ingest --profile kwp --source kww.xlsx
docpipe ingest --profile scenarios --source pdf_index.json --db data/ar6/ar6.db --data-dir data/ar6/pdf
docpipe ingest --profile default --source ~/reports
        """,
    )
    # --excel is what this was called while kwp was the only profile, and
    # existing callers still say it.
    p.add_argument("--source", "--excel", dest="source",
                   help="The profile's document list (kwp: the KWW sheet, "
                        "ar6: the crawl index), or for a profile that reads "
                        "a folder, the folder of PDFs (default: the data "
                        "directory)")
    p.add_argument("--db", help="Path to the SQLite database "
                                "(default: the profile's)")
    p.add_argument("--data-dir", help="Directory the PDFs live in "
                                      "(default: the profile's)")
    p.add_argument("--backfill-meta", action="store_true",
                   help="Only backfill MunicipalityMeta for municipalities already "
                        "in the DB (no downloads, no document changes).")
    add_profile_argument(p)
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    profile = require_profile(args)
    db = Path(args.db) if args.db else profile.db_path
    data_dir = Path(args.data_dir) if args.data_dir else profile.pdf_dir

    if args.backfill_meta:
        backfill = profile.component("source", "backfill_meta")
        if backfill is None:
            raise SystemExit(f"profile {profile.name!r} has no --backfill-meta step")
        if not args.source:
            raise SystemExit("--backfill-meta needs --source")
        n = backfill(Path(args.source), db)
        log.info("Backfilled project metadata for %d entries", n)
        return

    source_class = profile.component("source", "SOURCE")
    if source_class is None:
        raise SystemExit(f"profile {profile.name!r} provides no document source "
                         f"(source.py: SOURCE)")
    location = Path(args.source) if args.source else None
    if location is None:
        default = getattr(source_class, "default_location", None)
        location = default(data_dir) if default else None
    if location is None:
        raise SystemExit(f"profile {profile.name!r} needs --source: its "
                         f"document list")
    db.parent.mkdir(parents=True, exist_ok=True)
    ingest(source_class(Path(location)), db, data_dir, profile)
