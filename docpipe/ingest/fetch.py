"""
fetch.py: Downloads a source PDF to disk and counts its pages.

download_pdf sends a browser User-Agent, because municipal sites answer a
default requests client with 403, and writes the response through a temporary
file before the atomic rename, so a killed job leaves no partial PDF for a
later run to reuse. get_num_pages and download_pdf both check the file for a
%PDF header before handing it to PyMuPDF, which can segfault on a truncated or
non-PDF file rather than raise.

Author: Felix Vossel
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import fitz
import requests


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


def filename_for(url: str) -> str:
    """The name a download of *url* will be saved under (lowercased)."""
    return Path(urlparse(url.lower()).path).name.lower()


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

    # Municipal sites regularly answer 403 to a default requests User-Agent.
    response = requests.get(url, timeout=30, headers=BROWSER_HEADERS)
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
