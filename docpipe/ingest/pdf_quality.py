"""
pdf_quality.py: Grades what a source PDF's text layer is worth.

Stage 1 reads text with PyMuPDF, never OCR. A PDF with a broken ToUnicode map
yields symbol garbage, useless at every later stage. A PDF with no text layer
at all yields nothing, which preprocessing can now make good by rendering the
page and having the model read it (page_text_fallback).

`check()` reports the fact and nothing more. What to do about it is policy, and
lives in the ingest pipeline: garbled text is refused, a scan is registered and
put on a worklist. Keeping the two apart is the point. This module used to
decide both, and its verdict on a scan cost the corpus eleven complete plans.
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
MIN_ALPHA_RATIO = 0.5      # prose is ~0.7-0.8; garbled text is punctuation
PROSE_PAGE_CHARS = 200     # below this a page says nothing about the glyph map

CID_RE = re.compile(r"\(cid:\d+\)")

# Verdict prefixes. NO_TEXT is the one that is not fatal: the document is
# readable, just not by PyMuPDF alone.
NO_TEXT = "NO_TEXT"


def is_missing_text_layer(reason: str) -> bool:
    """True if check() withheld a file only because it carries no text layer.

    Such a file is a scan, not garbage: preprocessing renders each page and the
    model transcribes it, so it belongs in the corpus. Anything else check()
    reports is a file nothing downstream can repair.
    """
    return str(reason).startswith(NO_TEXT)


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
             "chars": 0, "alpha": 0, "best_alpha": 0.0, "cid": 0, "replacement": 0}
        for pno in pages:
            try:
                t = doc.load_page(pno).get_text()
            except Exception:
                m["empty"] += 1
                continue
            if len(t.strip()) < EMPTY_PAGE_CHARS:
                m["empty"] += 1
            alpha = sum(1 for c in t if c.isalpha())
            m["chars"] += len(t)
            m["alpha"] += alpha
            if len(t) >= PROSE_PAGE_CHARS:
                m["best_alpha"] = max(m["best_alpha"], alpha / len(t))
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
        return False, (f"{NO_TEXT}: {m['empty']}/{m['sampled']} sampled pages empty "
                       f"({empty_frac:.0%}) – scan without OCR")

    if m["cid"]:
        return False, f"BROKEN_ENCODING: {m['cid']} (cid:N) artefacts – broken ToUnicode map"

    if m["chars"] >= MIN_TEXT_CHARS:
        alpha_ratio = m["alpha"] / m["chars"]
        # Garbled glyph maps produce punctuation and symbols, not letters — but
        # so does a statistical annex, and a sample spread evenly over a
        # 300-page outlook lands in one. A broken glyph map is broken on every
        # page, so a single page of ordinary prose acquits the document. This
        # used to be "and no umlauts", which acquitted German prose only: the
        # first English corpus lost a readable 318-page report to it.
        if alpha_ratio < MIN_ALPHA_RATIO and m["best_alpha"] < MIN_ALPHA_RATIO:
            return False, (f"BROKEN_ENCODING: only {alpha_ratio:.0%} letters in "
                           f"{m['chars']} chars, no page above {MIN_ALPHA_RATIO:.0%} "
                           f"– garbled glyph map")

    return True, ""
