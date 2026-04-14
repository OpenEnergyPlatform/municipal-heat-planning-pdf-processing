import argparse
import logging
import sqlite3
import fitz
import requests
import pandas as pd
from .config import EXCEL_SHEET, DATABASE_SCHEMA
from pathlib import Path
from urllib.parse import urlparse
from tqdm import tqdm
from datetime import datetime
from typing import Any
from utils import database

def _load_and_filter_excel(excel_file: Path) -> pd.DataFrame:
    """
    Load and filter the Excel datasource for completed Wärmepläne with PDF links.
    
    Returns:
        A pandas DataFrame containing only completed plans (Stand in der KWP == "abgeschlossen")
        that have valid PDF links.
    
    Note:
        Column names are normalized by replacing spaces with underscores for easier access.
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
    Download a PDF file from the given URL and save it locally.
    
    Args:
        url: The full URL to the PDF file.
    
    Returns:
        The filename of the saved PDF (lowercase).
    
    Raises:
        requests.HTTPError: If the HTTP request fails.
        IOError: If writing the file fails.
    
    Note:
        Files are saved to the 'data/pdf' directory with lowercase filenames.
        Skips download if file already exists locally to optimize performance.
    """
    filename = Path(urlparse(url).path).name.lower()
    file_path = data_dir / filename
    
    if file_path.exists():
        return file_path.name
    
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    with open(file_path, "wb") as f:
        f.write(response.content)
    
    return file_path.name

def get_num_pages(filename: str, data_dir: Path) -> int:
    """
    Extract the number of pages from a PDF document.
    
    Args:
        filename: The name of the PDF file (located in 'data/pdf' directory).
    
    Returns:
        The total number of pages in the PDF document.
    
    Raises:
        FileNotFoundError: If the PDF file cannot be found.
        Exception: If the file cannot be opened as a valid PDF.
    
    Note:
        The PDF file is opened and closed within this function to retrieve metadata.
    """
    file_path = data_dir / filename
    document = fitz.open(str(file_path))
    num_pages = len(document)
    document.close()
    return num_pages


def process_entry(row: Any, connection: sqlite3.Connection, data_dir: Path) -> None:
    """
    Process a single entry from the Excel datasource.
    
    Handles two scenarios:
    1. Document already exists in database: Link municipality to existing organizational unit
    2. Document is new: Download PDF, extract metadata, and store both document and municipality
    
    Args:
        row: A namedtuple-like object representing one row from the filtered Excel data.
             Expected attributes: Gemeindename, Verbandsname, Bundesland_lang, 
             Link_Wärmeplan, Datum_der_Veröffentlichung
        connection: Active SQLite database connection.
    
    Note:
        Logs all operations for transparency. Properly handles both new and existing documents.
    """
    municipality_name = row.Gemeindename
    municipality_ags = row.Gemeindeschlüssel
    organisation_unit = row.Verbandsname
    state = row.Bundesland_lang
    link = str(row.Ersetzte_Datei if pd.notna(row.Ersetzte_Datei) else row.Link_Wärmeplan.strip())
    published = pd.Timestamp(row.Datum_der_Veröffentlichung).strftime("%Y%m%d")
    added = datetime.now().strftime("%Y%m%d")
    
    orga_id = database.update_organisation_unit(organisation_unit, state, connection)

    if database.document_exists(Path(urlparse(link.lower()).path).name.lower(), connection):
        database.add_municipality(municipality_name, municipality_ags, orga_id, connection)
    else:
        if not (Path(data_dir) / Path(urlparse(link.lower()).path)).exists():
            filename = download_pdf(link, data_dir)
        else:
            filename = Path(urlparse(link.lower()).path).name.lower()
            
        num_pages = get_num_pages(filename, data_dir)
        database.add_document(filename, orga_id, published, num_pages, added, connection)
        database.add_municipality(municipality_name, municipality_ags, orga_id, connection)

def run(excel_file: Path, db_file: Path, data_dir: Path) -> None:
    """
    Execute the complete file processing pipeline.

    Loads municipality data from Excel, creates database if needed,
    downloads PDFs, and stores documents and municipalities in the database.

    Args:
        excel_file: Path to the Excel file containing municipality metadata.
        db_file: Path to the SQLite database file.
        data_dir: Directory where PDF files will be stored.
    """
    kww_data = _load_and_filter_excel(excel_file)
    if not db_file.exists():
        with sqlite3.connect(db_file) as connection:
            connection.executescript(DATABASE_SCHEMA)
    
    with sqlite3.connect(db_file) as connection:
        for row in tqdm(kww_data.itertuples(), desc="Processing municipality", total=kww_data.shape[0]):
            process_entry(row, connection, data_dir)
    

def _build_parser() -> argparse.ArgumentParser:
    """
    Build and return the command-line argument parser.

    Returns:
        An ArgumentParser configured with all required and optional arguments
        for the file processing CLI.
    """
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
    """
    Entry point for the command-line interface.

    Parses command-line arguments, configures logging, and executes the
    file processing pipeline.
    """
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