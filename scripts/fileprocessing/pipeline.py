"""
pipeline.py – CLI for registering a profile's documents.

The work lives in docpipe.ingest (generic) and profiles/<name>/source.py
(project-specific); this module is only the entry point.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from docpipe.ingest import ingest
from docpipe.profile import add_profile_argument, load_profile

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.fileprocessing",
        description="Download and register the source PDFs of a profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
python -m scripts.fileprocessing --profile kwp --excel kww.xlsx --db data/kwp/kwp.db --data-dir data/kwp/pdf
        """,
    )
    p.add_argument("--excel", required=True,
                   help="Path to the excel file containing the meta-data")
    p.add_argument("--db", required=True, help="Path to the SQLite database")
    p.add_argument("--data-dir", help="Directory the PDFs live in")
    p.add_argument("--backfill-meta", action="store_true",
                   help="Only backfill MunicipalityMeta for municipalities already "
                        "in the DB (no downloads, no document changes).")
    add_profile_argument(p)
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    profile = load_profile(args.profile)

    if args.backfill_meta:
        backfill = profile.component("source", "backfill_meta")
        if backfill is None:
            raise SystemExit(f"profile {profile.name!r} has no --backfill-meta step")
        n = backfill(Path(args.excel), Path(args.db))
        log.info("Backfilled project metadata for %d entries", n)
        return

    source_class = profile.component("source", "SOURCE")
    if source_class is None:
        raise SystemExit(f"profile {profile.name!r} provides no document source "
                         f"(profiles/{profile.name}/source.py: SOURCE)")
    if not args.data_dir:
        raise SystemExit("--data-dir is required unless --backfill-meta is given")
    ingest(source_class(Path(args.excel)), Path(args.db), Path(args.data_dir), profile)
