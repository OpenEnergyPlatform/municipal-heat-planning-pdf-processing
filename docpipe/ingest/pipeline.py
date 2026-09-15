"""
pipeline.py: Registers a profile's documents in its database.

The core repeats four steps for every corpus: it fetches the file,
checks its text layer, writes the Documents row, and links versions.
A file whose text is unreadable or garbled is refused and left out
of the corpus. A file with no text layer at all is registered
anyway and listed for preprocessing to read with the vision model,
because the pages exist to be read. What the documents are and
where they come from is defined by the profile's Source.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

from ..profile import Profile
from ..store import documents as docs
from ..store import schema
from . import pdf_quality
from .fetch import download_pdf, get_num_pages
from .models import SourceDoc, UnusablePDF

log = logging.getLogger(__name__)


def register(doc: SourceDoc, connection: sqlite3.Connection, data_dir: Path,
             *, scans: Optional[dict] = None) -> bool:
    """Fetch and register one document. False if it was already in the DB.

    `scans` collects the documents that carry no text layer, keyed by filename.
    They ARE registered: preprocessing reads their pages with the model. They are
    collected so the run can say which documents depend on that.
    """
    if docs.document_exists(doc.filename, connection):
        return False

    if not (data_dir / doc.filename).exists():
        if not doc.url:
            raise FileNotFoundError(
                f"{doc.external_id}: file missing in {data_dir}: {doc.filename}")
        doc.filename = download_pdf(doc.url, data_dir)

    # Gate before any DB write. Garbled text is useless at every later stage, so
    # it is refused. A missing text layer is not the same thing: the pages are
    # there to be read, and preprocessing --transcribe-missing-text reads them.
    # Refusing those too is what kept eleven complete plans out of the corpus.
    usable, reason = pdf_quality.check(data_dir / doc.filename)
    if not usable:
        if not pdf_quality.is_missing_text_layer(reason):
            raise UnusablePDF(f"{doc.filename}: {reason}")
        if scans is not None:
            scans[doc.filename] = reason

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
    unreachable: dict = {}
    scans: dict = {}
    with sqlite3.connect(db_file) as connection:
        schema.apply(connection, profile)
        try:
            total = len(source)
        except TypeError:
            total = None
        for doc in tqdm(source.documents(connection), desc="Registering", total=total):
            try:
                register(doc, connection, data_dir, scans=scans)
            except UnusablePDF as exc:
                filename, _, reason = str(exc).partition(": ")
                if filename not in rejected:   # one PDF can serve many entries
                    log.error("UNUSABLE PDF – not registered: %s", exc)
                rejected[filename] = reason
                continue
            # A dead link is the normal case, not a crash: the registers we read
            # link to municipal websites that reorganise. Collect them all and
            # report at the end, so one run yields the whole worklist.
            except (requests.RequestException, OSError) as exc:
                if doc.filename not in unreachable:
                    log.warning("UNREACHABLE – not registered: %s (%s)",
                                doc.filename, _reason(exc))
                unreachable[doc.filename] = (doc.group_key, doc.url, _reason(exc))
                continue
            source.after_document(connection, doc)
        docs.link_document_versions(connection)

    if rejected:
        _report_rejected(rejected, db_file)
    else:
        _drop_stale(db_file.parent / "rejected_pdfs.txt")
    if unreachable:
        _report_unreachable(unreachable, db_file)
    else:
        _drop_stale(db_file.parent / "unreachable_pdfs.txt")
    if scans:
        _report_scans(scans, db_file)
    else:
        _drop_stale(db_file.parent / "scanned_pdfs.txt")
    return rejected


def _drop_stale(path: Path) -> None:
    """A worklist from an earlier run must not survive a clean one — it would
    read as this run's result."""
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("Could not remove the stale %s: %s", path.name, exc)
        return
    log.info("Removed %s — nothing left on it this run.", path.name)


def _reason(exc: BaseException) -> str:
    """One short line for the log and the worklist."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return f"{type(exc).__name__}: {exc}"


def _report_unreachable(unreachable: dict, db_file: Path) -> None:
    """End-of-run summary + a worklist of the links that could not be fetched."""
    out = db_file.parent / "unreachable_pdfs.txt"
    banner = "=" * 78
    log.error("\n%s\n%d PDF(s) UNREACHABLE — not in the corpus.\n"
              "Source each one by hand, drop it in the data dir and add it to the "
              "profile's PDF_OVERRIDES, then re-run.\n%s",
              banner, len(unreachable), banner)
    for filename, (group_key, url, reason) in sorted(unreachable.items()):
        log.error("  %-12s %-55s %s", group_key or "-", filename, reason)
    try:
        out.write_text(
            "".join(f"{group_key or ''}\t{fn}\t{reason}\t{url or ''}\n"
                    for fn, (group_key, url, reason) in sorted(unreachable.items())),
            encoding="utf-8",
        )
        log.error("Worklist written to %s", out)
    except OSError as exc:
        log.error("Could not write %s: %s", out, exc)


def _report_scans(scans: dict, db_file: Path) -> None:
    """The documents that are in the corpus but have nothing for Stage 1 to read.

    Not an error and not a worklist for a human: a worklist for the next step.
    Preprocess these with --transcribe-missing-text, or they become documents of
    empty sections and refinement deletes them.
    """
    out = db_file.parent / "scanned_pdfs.txt"
    log.warning("%d PDF(s) have NO TEXT LAYER. They are registered, and their "
                "text has to come from the model: preprocess with "
                "--transcribe-missing-text.", len(scans))
    for filename, reason in sorted(scans.items()):
        log.warning("  %-60s %s", filename, reason)
    try:
        out.write_text("".join(f"{fn}\t{reason}\n"
                               for fn, reason in sorted(scans.items())),
                       encoding="utf-8")
        log.warning("List written to %s", out)
    except OSError as exc:
        log.warning("Could not write %s: %s", out, exc)


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
