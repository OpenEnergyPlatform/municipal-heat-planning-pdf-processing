"""
pipeline.py – Register a profile's documents in its database.

The core does the same four things for every corpus: get the file, refuse it if
it has no usable text layer, write the Documents row, and link versions. What
the documents are and where they come from is the profile's Source.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from ..profile import Profile
from ..store import documents as docs
from ..store import schema
from . import pdf_quality
from .fetch import download_pdf, get_num_pages
from .models import SourceDoc, UnusablePDF

log = logging.getLogger(__name__)


def register(doc: SourceDoc, connection: sqlite3.Connection, data_dir: Path) -> bool:
    """Fetch and register one document. False if it was already in the DB."""
    if docs.document_exists(doc.filename, connection):
        return False

    if not (data_dir / doc.filename).exists():
        if not doc.url:
            raise FileNotFoundError(
                f"{doc.external_id}: file missing in {data_dir}: {doc.filename}")
        doc.filename = download_pdf(doc.url, data_dir)

    # Gate before any DB write: a scanned or garbled PDF yields empty/garbage
    # sections downstream, so refuse it loudly instead of carrying it along.
    usable, reason = pdf_quality.check(data_dir / doc.filename)
    if not usable:
        raise UnusablePDF(f"{doc.filename}: {reason}")

    docs.add_document(doc.filename, doc.external_id, doc.group_key, doc.published,
                      get_num_pages(doc.filename, data_dir),
                      datetime.now().strftime("%Y%m%d"), doc.meta, connection)
    return True


def ingest(source, db_file: Path, data_dir: Path,
           profile: Optional[Profile] = None) -> dict:
    """Run a profile's source into its database. Returns the refused files."""
    db_file, data_dir = Path(db_file), Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    rejected: dict = {}
    with sqlite3.connect(db_file) as connection:
        schema.apply(connection, profile)
        try:
            total = len(source)
        except TypeError:
            total = None
        for doc in tqdm(source.documents(connection), desc="Registering", total=total):
            try:
                register(doc, connection, data_dir)
            except UnusablePDF as exc:
                filename, _, reason = str(exc).partition(": ")
                if filename not in rejected:   # one PDF can serve many entries
                    log.error("UNUSABLE PDF – not registered: %s", exc)
                rejected[filename] = reason
                continue
            source.after_document(connection, doc)
        docs.link_document_versions(connection)

    if rejected:
        _report_rejected(rejected, db_file)
    return rejected


def _report_rejected(rejected: dict, db_file: Path) -> None:
    """Loud end-of-run summary + a file listing the PDFs that were refused."""
    out = db_file.parent / "rejected_pdfs.txt"
    banner = "=" * 78
    log.error("\n%s\n%d PDF(s) REFUSED — no usable text layer, not in the corpus.\n"
              "Source a correct file by hand and point the profile at it, then "
              "re-run.\n%s", banner, len(rejected), banner)
    for filename, reason in sorted(rejected.items()):
        log.error("  %-60s %s", filename, reason)
    try:
        out.write_text(
            "".join(f"{fn}\t{reason}\n" for fn, reason in sorted(rejected.items())),
            encoding="utf-8",
        )
        log.error("List written to %s", out)
    except OSError as exc:
        log.error("Could not write %s: %s", out, exc)
