import argparse
import logging
import os
import sqlite3
import tempfile
import fitz
import requests
import pandas as pd
from .config import EXCEL_SHEET, DATABASE_SCHEMA, PDF_OVERRIDES
from pathlib import Path
from urllib.parse import urlparse
from tqdm import tqdm
from datetime import datetime
from typing import Any
from utils import database

def _load_and_filter_excel(excel_file: Path) -> pd.DataFrame:
    """
    Completed Wärmepläne ("Stand in der KWP" == "abgeschlossen") that have a PDF
    link. Column names are returned with spaces replaced by underscores.
    """
    kww_data = pd.read_excel(
        excel_file,
        sheet_name=EXCEL_SHEET
    )

    kww_data = kww_data[
        (kww_data["Stand in der KWP"] == "abgeschlossen") &
        (kww_data["Link Wärmeplan"].str.lower().str.contains(".pdf", na=False))
    ]

    kww_data.columns = kww_data.columns.str.replace(" ", "_")

    return kww_data

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


def process_entry(row: Any, connection: sqlite3.Connection, data_dir: Path) -> None:
    """
    Register one row of the filtered Excel data, downloading its PDF if the
    document is not in the DB yet.

    `row` is an itertuples row and must carry Gemeindename, Gemeindeschlüssel,
    Verbandsname, Bundesland_lang, Link_Wärmeplan and Datum_der_Veröffentlichung.
    """
    municipality_name = row.Gemeindename
    municipality_ags = int(row.Gemeindeschlüssel)   # Excel gives float when the column has any NaN
    organisation_unit = row.Verbandsname
    state = row.Bundesland_lang
    published = pd.Timestamp(row.Datum_der_Veröffentlichung).strftime("%Y%m%d")
    added = datetime.now().strftime("%Y%m%d")

    # A hand-sourced replacement for a broken KWW link (PDF_OVERRIDES) is a local
    # filename that must already be in data_dir — never downloaded.
    override = PDF_OVERRIDES.get(municipality_ags)
    link = override if override else str(row.Link_Wärmeplan).strip()
    # urlparse(link).path is absolute, so joining it with data_dir would discard
    # data_dir — use the bare filename against data_dir instead.
    filename = Path(urlparse(link.lower()).path).name.lower()

    orga_id = database.update_organisation_unit(organisation_unit, state, connection)

    if database.document_exists(filename, connection):
        database.add_municipality(municipality_name, municipality_ags, orga_id, connection)
        return

    if not (data_dir / filename).exists():
        if override:
            raise FileNotFoundError(
                f"Override PDF for ags {municipality_ags} missing in {data_dir}: {filename}"
            )
        filename = download_pdf(link, data_dir)

    num_pages = get_num_pages(filename, data_dir)
    database.add_document(filename, orga_id, published, num_pages, added, municipality_ags, connection)
    database.add_municipality(municipality_name, municipality_ags, orga_id, connection)

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

    with sqlite3.connect(db_file) as connection:
        for row in tqdm(kww_data.itertuples(), desc="Processing municipality", total=kww_data.shape[0]):
            process_entry(row, connection, data_dir)
        # Link re-published plans: newest per municipality = current, older ones
        # superseded. Runs over the full table, so re-runs stay correct.
        database.link_document_versions(connection)
    

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
        help="Directory where the pdf files should be stored",
        type=str,
        required=True
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
    run(Path(args.excel), Path(args.db), Path(args.data_dir))

if __name__ == "__main__":
    main()