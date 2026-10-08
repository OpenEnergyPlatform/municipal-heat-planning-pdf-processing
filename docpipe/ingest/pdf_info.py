"""
pdf_info.py: What a PDF says about itself in its information dictionary.

The software that wrote a PDF usually put the document's title and its
creation date into the file. A folder of PDFs has no register to say what
they are called, so this is the one place to learn it. A dictionary that is
empty, or says neither, gives nothing; so does one that cannot be read, and
that is said, once, in the log. Nothing here decides whether a document is
usable: the text layer is graded by pdf_quality.

Author: Felix Vossel
"""
from __future__ import annotations

import calendar
import logging
import re
from pathlib import Path
from typing import Optional

import fitz

log = logging.getLogger(__name__)

# D:YYYYMMDDHHmmSSOHH'mm': after the year, every part is optional. ASCII
# digits only: a date of other digits would be stored as it was written.
_DATE = re.compile(r"^\s*D:(\d{4})(\d{2})?(\d{2})?", re.ASCII)


def parse_date(text) -> Optional[str]:
    """A PDF date as far as it is given: YYYY, YYYY-MM or YYYY-MM-DD.

    None for no date, for a text that is not written the way the PDF
    specification writes one, and for a date that is not on the calendar.
    """
    found = _DATE.match(text) if isinstance(text, str) else None
    if not found:
        return None
    year, month, day = found.group(1), found.group(2), found.group(3)
    if int(year) < 1:
        return None
    if month is None:
        return year
    if not 1 <= int(month) <= 12:
        return None
    if day is None:
        return f"{year}-{month}"
    if not 1 <= int(day) <= calendar.monthrange(int(year), int(month))[1]:
        return None
    return f"{year}-{month}-{day}"


def _title(text) -> Optional[str]:
    """One line, with nothing in it a picker could not show."""
    if not isinstance(text, str):
        return None
    shown = "".join(ch for ch in text if ch.isprintable() or ch.isspace())
    return " ".join(shown.split()) or None


def from_metadata(metadata) -> dict:
    """{"title": ..., "created": ...} from PyMuPDF's metadata dictionary.

    A key the dictionary does not say is not in the result.
    """
    if not isinstance(metadata, dict):
        return {}
    said = {"title": _title(metadata.get("title")),
            "created": parse_date(metadata.get("creationDate"))}
    return {key: value for key, value in said.items() if value}


def read(path) -> dict:
    """What the information dictionary of the PDF at *path* says, as
    `from_metadata`; {} when it says nothing and when it cannot be read."""
    path = Path(path)
    try:
        # PyMuPDF can segfault rather than raise on a non-PDF file.
        with open(path, "rb") as handle:
            if not handle.read(5).startswith(b"%PDF"):
                raise ValueError("no %PDF header")
        document = fitz.open(str(path))
        try:
            metadata = document.metadata
        finally:
            document.close()
    except Exception as exc:        # PyMuPDF raises a different type for each
        log.warning(                # way a file can be damaged
            "%s: its information dictionary could not be read (%s: %s); it "
            "is ingested with no title or date of its own", path.name,
            type(exc).__name__, exc)
        return {}
    return from_metadata(metadata)
