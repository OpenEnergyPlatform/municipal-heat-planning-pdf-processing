"""
fetch.py: Downloads a source PDF to disk and counts its pages.

download_pdf sends a configurable User-Agent (a browser's by default, because
municipal sites answer a default requests client with 403) and streams the
body into a temporary file in the data directory, so a PDF is never held in
memory whole and a killed job leaves no partial file for a later run to
reuse. A body over the size limit is refused with its size. A file is named
after the last segment of its URL, so two URLs can claim one name: the URL a
file came from is kept beside it, and a second, different URL for that name
is refused with both named, instead of being read from the first one's
bytes. get_num_pages and download_pdf both check the file for a %PDF header
before handing it to PyMuPDF, which can segfault on a truncated or non-PDF
file rather than raise.

Author: Felix Vossel
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlsplit, urlunsplit

import fitz
import requests

from docpipe import settings

USER_AGENT_ENV = "DOCPIPE_USER_AGENT"
MAX_DOWNLOAD_ENV = "DOCPIPE_MAX_DOWNLOAD_MB"
MEGABYTE = 1024 * 1024
CHUNK_BYTES = MEGABYTE
# Written beside each downloaded file: the URL it came from.
SOURCE_SUFFIX = ".url"


class DownloadRefused(OSError):
    """A download that was not kept. An OSError, so that ingest lists it with
    the other files it could not fetch and goes on."""


class NameTaken(DownloadRefused):
    """Two different URLs end in one file name."""


class TooLarge(DownloadRefused):
    """A body over the size limit."""


def user_agent() -> str:
    """The User-Agent a download sends: the setting, else its default."""
    return (os.environ.get(USER_AGENT_ENV)
            or settings.BY_ENV[USER_AGENT_ENV].default)


def max_download_bytes() -> int:
    """The size limit of one download, in bytes."""
    text = (os.environ.get(MAX_DOWNLOAD_ENV)
            or settings.BY_ENV[MAX_DOWNLOAD_ENV].default)
    try:
        megabytes = int(text)
    except ValueError:
        megabytes = 0
    if megabytes < 1:
        raise ValueError(f"{MAX_DOWNLOAD_ENV} is {text!r}: it has to be a "
                         f"whole number of megabytes, 1 or more")
    return megabytes * MEGABYTE


def filename_for(url: str) -> str:
    """The name a download of *url* will be saved under (lowercased)."""
    return Path(urlparse(url.lower()).path).name.lower()


def source_file(filename: str, data_dir: Path) -> Path:
    """Where the URL of a downloaded file is kept."""
    return Path(data_dir) / (filename + SOURCE_SUFFIX)


def source_of(filename: str, data_dir: Path) -> Optional[str]:
    """The URL *filename* was downloaded from, None if nobody wrote it down
    (a file put there by hand, or downloaded before this was kept)."""
    try:
        text = source_file(filename, data_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return text.strip() or None


def _canonical(url: str) -> str:
    """A URL as far as its spelling goes: the scheme and the host are not
    case sensitive, and a fragment is not sent."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       parts.query, ""))


def check_name(filename: str, url: str, data_dir: Path) -> None:
    """Raise NameTaken if *filename* in *data_dir* came from another URL.

    A name is taken by a file that is there. The URL a killed job left
    beside a file that never arrived holds nothing, and the next download
    of that name overwrites it.
    """
    if not (Path(data_dir) / filename).is_file():
        return
    kept = source_of(filename, data_dir)
    if kept is not None and _canonical(kept) != _canonical(url):
        raise NameTaken(
            f"two URLs end in the file name {filename}: {kept} (kept) and "
            f"{url} (refused)")


def _discard(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _declared_size(response) -> Optional[int]:
    """The length the server announces, None if it announces none or a
    malformed one: the count while streaming is what is held to the limit."""
    try:
        return int(response.headers.get("Content-Length"))
    except (TypeError, ValueError):
        return None


def _stream(response, out, url: str, limit: int) -> int:
    """Copy the body to *out*, checking the %PDF header on its first bytes
    and the size as it grows. Returns the bytes written."""
    written, head = 0, b""
    for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
        if not chunk:
            continue
        if len(head) < 4:
            head += chunk[:4 - len(head)]
            if len(head) == 4 and head != b"%PDF":
                raise IOError(
                    f"Downloaded file is not a PDF (no %PDF header): {url}")
        written += len(chunk)
        if written > limit:
            raise TooLarge(
                f"{url}: over the limit of {limit} bytes ({MAX_DOWNLOAD_ENV}) "
                f"after {written} bytes, so it was not kept")
        out.write(chunk)
    if head != b"%PDF":                 # an empty body, or one under 4 bytes
        raise IOError(
            f"Downloaded file is not a PDF (no %PDF header): {url}")
    return written


def download_pdf(url: str, data_dir: Path) -> str:
    """
    Download `url` into `data_dir` and return the saved filename (lowercased).

    A no-op returning the existing name if the file is already there and came
    from this URL. Raises NameTaken if it came from another one, TooLarge if
    the body is over the size limit, requests.HTTPError on a failed request
    and IOError if the response is not a PDF.
    """
    filename = Path(urlparse(url).path).name.lower()
    file_path = data_dir / filename

    if file_path.exists():
        check_name(filename, url, data_dir)
        return file_path.name

    limit = max_download_bytes()
    # Municipal sites regularly answer 403 to a default requests User-Agent.
    response = requests.get(url, timeout=30, stream=True,
                            headers={"User-Agent": user_agent()})
    try:
        response.raise_for_status()
        declared = _declared_size(response)
        if declared is not None and declared > limit:
            raise TooLarge(
                f"{url}: the server announces {declared} bytes, over the "
                f"limit of {limit} bytes ({MAX_DOWNLOAD_ENV}), so it was not "
                f"fetched")
        data_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write: a killed job must not leave a partial .pdf that a later
        # run reuses and feeds to PyMuPDF, which can segfault on a truncated file.
        fd, tmp = tempfile.mkstemp(dir=str(data_dir), prefix=filename + ".",
                                   suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                _stream(response, f, url, limit)
            # The URL goes down before the PDF does: a file that is there has
            # its URL beside it. A job killed in between leaves a URL with no
            # file, which the next download of that name overwrites.
            kept = source_file(filename, data_dir)
            kept.write_text(url.strip() + "\n", encoding="utf-8")
            os.replace(tmp, file_path)
        except BaseException:
            _discard(tmp)
            raise
    finally:
        response.close()

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
