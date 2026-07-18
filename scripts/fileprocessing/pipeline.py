import argparse
import logging
import os
import sqlite3
import tempfile
import fitz
import requests
import pandas as pd
from . import pdf_quality
from .config import EXCEL_SHEET, DATABASE_SCHEMA, PDF_OVERRIDES, MUNICIPALITY_META_COLUMNS
from pathlib import Path
from urllib.parse import urlparse
from tqdm import tqdm
from datetime import datetime
from typing import Any
from utils import database

log = logging.getLogger(__name__)


class UnusablePDF(Exception):
    """A source PDF has no usable text layer — it is not registered."""


def _load_and_filter_excel(excel_file: Path) -> pd.DataFrame:
    """
    Completed Wärmepläne ("Stand in der KWP" == "abgeschlossen") that have a PDF
    link. Original KWW column names are kept (rows are consumed as dicts).
    """
    kww_data = pd.read_excel(
        excel_file,
        sheet_name=EXCEL_SHEET
    )

    kww_data = kww_data[
        (kww_data["Stand in der KWP"] == "abgeschlossen") &
        (kww_data["Link Wärmeplan"].str.lower().str.contains(".pdf", na=False))
    ]

    return kww_data


def _coerce(value: Any, sqltype: str):
    """Excel cell → a SQLite-storable value (NaN/NaT → None) for the given type."""
    if pd.isna(value):
        return None
    if sqltype == "INTEGER":
        return int(value)
    if sqltype == "DATE":
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    return str(value).strip()


def _extract_meta(row: dict) -> dict:
    """{db_column: coerced value} for the metadata columns of one Excel row."""
    return {
        db: _coerce(row.get(excel), sqltype)
        for excel, db, sqltype in MUNICIPALITY_META_COLUMNS
    }

def download_pdf(url: str, data_dir: Path) -> str:
    """
    Download `url` into `data_dir` and return the saved filename (lowercased).

    A no-op returning the existing name if the file is already there. Raises
    requests.HTTPError on a failed request and IOError if the response is not a
    PDF.
    """
    filename = Path(urlparse(url).path).name.lower()
    file_path = data_dir / filename

    if file_path.exists():
        return file_path.name

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF"):
        raise IOError(f"Downloaded file is not a PDF (no %PDF header): {url}")

    # Atomic write: a killed job must not leave a partial .pdf that a later run
    # reuses and feeds to PyMuPDF, which can segfault on a truncated file.
    data_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(data_dir), prefix=filename + ".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, file_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return file_path.name

def get_num_pages(filename: str, data_dir: Path) -> int:
    """
    Page count of `data_dir / filename`.

    Raises IOError if the file is not a PDF, FileNotFoundError if it is missing.
    """
    file_path = data_dir / filename
    # PyMuPDF can segfault rather than raise on a non-PDF / truncated file.
    with open(file_path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            raise IOError(f"Not a valid PDF (missing %PDF header): {file_path}")
    document = fitz.open(str(file_path))
    num_pages = len(document)
    document.close()
    return num_pages


def process_entry(row: dict, connection: sqlite3.Connection, data_dir: Path) -> None:
    """
    Register one row of the filtered Excel data, downloading its PDF if the
    document is not in the DB yet, and store the row's KWW metadata.

    `row` is a dict keyed by the original Excel column names.
    """
    municipality_name = row["Gemeindename"]
    municipality_ags = int(row["Gemeindeschlüssel"])   # Excel gives float when the column has any NaN
    organisation_unit = row["Verbandsname"]
    state = row["Bundesland lang"]
    published = pd.Timestamp(row["Datum der Veröffentlichung"]).strftime("%Y%m%d")
    added = datetime.now().strftime("%Y%m%d")

    # A hand-sourced replacement for a broken KWW link (PDF_OVERRIDES) is a local
    # filename that must already be in data_dir — never downloaded.
    override = PDF_OVERRIDES.get(municipality_ags)
    link = override if override else str(row["Link Wärmeplan"]).strip()
    # urlparse(link).path is absolute, so joining it with data_dir would discard
    # data_dir — use the bare filename against data_dir instead.
    filename = Path(urlparse(link.lower()).path).name.lower()

    orga_id = database.update_organisation_unit(organisation_unit, state, connection)

    if not database.document_exists(filename, connection):
        if not (data_dir / filename).exists():
            if override:
                raise FileNotFoundError(
                    f"Override PDF for ags {municipality_ags} missing in {data_dir}: {filename}"
                )
            filename = download_pdf(link, data_dir)
        # Gate before any DB write: a scanned or garbled PDF yields empty/garbage
        # sections downstream, so refuse it loudly instead of carrying it along.
        usable, reason = pdf_quality.check(data_dir / filename)
        if not usable:
            raise UnusablePDF(f"{filename}: {reason}")
        num_pages = get_num_pages(filename, data_dir)
        database.add_document(filename, orga_id, published, num_pages, added, municipality_ags, connection)

    database.add_municipality(municipality_name, municipality_ags, orga_id, connection)
    database.upsert_municipality_meta(municipality_ags, _extract_meta(row), connection)

def run(excel_file: Path, db_file: Path, data_dir: Path) -> None:
    """
    Load the municipality metadata from `excel_file`, create `db_file` if it does
    not exist, download the PDFs into `data_dir` and register them in the DB.
    """
    kww_data = _load_and_filter_excel(excel_file)
    data_dir.mkdir(parents=True, exist_ok=True)
    if not db_file.exists():
        # A "<db_file>.sql" next to the DB wins over the bundled DATABASE_SCHEMA:
        # only it carries the foreign keys and page-provenance tables.
        schema_path = db_file.with_name(db_file.name + ".sql")
        with sqlite3.connect(db_file) as connection:
            if schema_path.exists():
                connection.executescript(schema_path.read_text(encoding="utf-8"))
            else:
                connection.executescript(DATABASE_SCHEMA)

    rejected: dict[str, str] = {}
    with sqlite3.connect(db_file) as connection:
        database.ensure_municipality_meta_table(MUNICIPALITY_META_COLUMNS, connection)
        for row in tqdm(kww_data.to_dict("records"), desc="Processing municipality", total=kww_data.shape[0]):
            try:
                process_entry(row, connection, data_dir)
            except UnusablePDF as e:
                fn, _, reason = str(e).partition(": ")
                if fn not in rejected:   # a convoy PDF appears on many rows
                    log.error("UNUSABLE PDF – not registered: %s", e)
                rejected[fn] = reason
        # Link re-published plans: newest per municipality = current, older ones
        # superseded. Runs over the full table, so re-runs stay correct.
        database.link_document_versions(connection)

    if rejected:
        _report_rejected(rejected, db_file)


def _report_rejected(rejected: dict, db_file: Path) -> None:
    """Loud end-of-run summary + a file listing the PDFs that were refused."""
    out = db_file.parent / "rejected_pdfs.txt"
    banner = "=" * 78
    log.error("\n%s\n%d PDF(s) REFUSED — no usable text layer, not in the corpus.\n"
              "Source a correct file by hand, then add it to config.PDF_OVERRIDES\n"
              "(keyed by Gemeindeschlüssel) and re-run.\n%s",
              banner, len(rejected), banner)
    for fn, reason in sorted(rejected.items()):
        log.error("  %-60s %s", fn, reason)
    try:
        out.write_text(
            "".join(f"{fn}\t{reason}\n" for fn, reason in sorted(rejected.items())),
            encoding="utf-8",
        )
        log.error("List written to %s", out)
    except OSError as e:
        log.error("Could not write %s: %s", out, e)


def backfill_meta(excel_file: Path, db_file: Path) -> int:
    """
    Backfill MunicipalityMeta for municipalities ALREADY in the DB, from
    `excel_file`, matched by ags. Additive and minimal-invasive: creates the
    table if absent and only writes MunicipalityMeta — no downloads, no changes
    to Documents/Sections/Embeddings. Returns the number of rows written.

    Reads the full sheet (unfiltered) so a municipality's metadata is found even
    if its own row would not pass the completed-plan import filter.
    """
    kww_data = pd.read_excel(excel_file, sheet_name=EXCEL_SHEET)
    with sqlite3.connect(db_file) as connection:
        database.ensure_municipality_meta_table(MUNICIPALITY_META_COLUMNS, connection)
        existing = {r[0] for r in connection.execute("SELECT ags FROM Municipalities")}
        written = 0
        for row in kww_data.to_dict("records"):
            ags = row.get("Gemeindeschlüssel")
            if pd.isna(ags) or int(ags) not in existing:
                continue
            database.upsert_municipality_meta(int(ags), _extract_meta(row), connection)
            written += 1
        connection.commit()
    return written


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="python -m scripts.fileprocessing",
        description="Download and meta-data enrichments of the original KWP PDF files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
python -m scripts.fileprocessing /path_to_kww_excel/file.xlxs /path_to_db/KWP.db
        """,
    )
    p.add_argument(
        "--excel",
        help="Path to excel file containing the meta-data",
        type=str,
        required=True
    )
    p.add_argument(
        "--db",
        help="Path to the existing db. If the db doesn't exists it will be created.",
        type=str,
        required=True
    )
    p.add_argument(
        "--data-dir",
        help="Directory where the pdf files should be stored (not needed with --backfill-meta)",
        type=str,
    )
    p.add_argument(
        "--backfill-meta",
        action="store_true",
        help="Only backfill MunicipalityMeta for municipalities already in the DB "
             "(no downloads, no document changes).",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p

def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.backfill_meta:
        n = backfill_meta(Path(args.excel), Path(args.db))
        logging.info("MunicipalityMeta backfilled for %d municipalities", n)
        return
    if not args.data_dir:
        parser.error("--data-dir is required unless --backfill-meta is given")
    run(Path(args.excel), Path(args.db), Path(args.data_dir))

if __name__ == "__main__":
    main()