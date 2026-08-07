"""
pdf_quality.py – Reject source PDFs whose text layer is missing or garbled.

The pipeline reads text with PyMuPDF, never OCR, so a scanned PDF yields empty
sections and a PDF with a broken ToUnicode map yields symbol garbage — both are
silently useless downstream. `check()` gates them at download time.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import fitz

SAMPLE_PAGES = 40          # pages sampled evenly across the document
EMPTY_PAGE_CHARS = 50      # a page below this counts as "no text"
MAX_EMPTY_FRACTION = 0.8   # more empty than this → scan without OCR
MIN_TEXT_CHARS = 2000      # below this the encoding checks are not meaningful
MIN_ALPHA_RATIO = 0.5      # German prose is ~0.7-0.8; garbled text is punctuation

UMLAUTS = set("äöüßÄÖÜ")
CID_RE = re.compile(r"\(cid:\d+\)")


def _sample_page_numbers(page_count: int, limit: int = SAMPLE_PAGES) -> list[int]:
    """Evenly spread page indices, so a text cover page cannot mask a scanned body."""
    if page_count <= limit:
        return list(range(page_count))
    step = page_count / limit
    return [min(page_count - 1, int(i * step)) for i in range(limit)]


def inspect(pdf_path: Path, limit: int = SAMPLE_PAGES) -> dict:
    """Text-layer metrics over a page sample. Raises on an unreadable PDF."""
    doc = fitz.open(str(pdf_path))
    try:
        pages = _sample_page_numbers(doc.page_count, limit)
        m = {"page_count": doc.page_count, "sampled": len(pages), "empty": 0,
             "chars": 0, "alpha": 0, "umlauts": 0, "cid": 0, "replacement": 0}
        for pno in pages:
            try:
                t = doc.load_page(pno).get_text()
            except Exception:
                m["empty"] += 1
                continue
            if len(t.strip()) < EMPTY_PAGE_CHARS:
                m["empty"] += 1
            m["chars"] += len(t)
            m["alpha"] += sum(1 for c in t if c.isalpha())
            m["umlauts"] += sum(1 for c in t if c in UMLAUTS)
            m["cid"] += len(CID_RE.findall(t))
            m["replacement"] += t.count("�")
        return m
    finally:
        doc.close()


def check(pdf_path: Path, limit: int = SAMPLE_PAGES) -> tuple[bool, str]:
    """
    (usable, reason). `usable` is False when the PDF has no text layer or its
    text is garbled; `reason` is a short diagnosis for the log.
    """
    try:
        m = inspect(pdf_path, limit)
    except Exception as e:
        return False, f"UNREADABLE: {type(e).__name__}: {e}"

    if m["sampled"] == 0:
        return False, "UNREADABLE: no pages"

    empty_frac = m["empty"] / m["sampled"]
    if empty_frac > MAX_EMPTY_FRACTION:
        return False, (f"NO_TEXT: {m['empty']}/{m['sampled']} sampled pages empty "
                       f"({empty_frac:.0%}) – scan without OCR")

    if m["cid"]:
        return False, f"BROKEN_ENCODING: {m['cid']} (cid:N) artefacts – broken ToUnicode map"

    if m["chars"] >= MIN_TEXT_CHARS:
        alpha_ratio = m["alpha"] / m["chars"]
        # Garbled glyph maps produce punctuation/symbols, not letters. Requiring
        # zero umlauts as well keeps clean non-German-heavy docs from tripping.
        if alpha_ratio < MIN_ALPHA_RATIO and m["umlauts"] == 0:
            return False, (f"BROKEN_ENCODING: only {alpha_ratio:.0%} letters and no "
                           f"umlauts in {m['chars']} chars – garbled glyph map")

    return True, ""
