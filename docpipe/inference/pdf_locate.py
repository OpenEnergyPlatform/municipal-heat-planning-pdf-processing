"""
pdf_locate.py – Where a quote sits on the page of the source PDF.

One implementation, two callers: the app highlights the passage it shows, the
extraction stage records the same rectangles as the provenance of a value.
Duplicating it would have meant two answers to "where does this come from",
which is the one question the whole evidence chain exists to answer.

The match is fuzzy on purpose. The corpus text has been through extraction
and refinement, so it is never byte-identical to what PyMuPDF reads off the
page: ligatures, hyphenation, running heads and column order all differ.
Alignment finds the passage anyway; the score floor keeps it from pointing at
something else.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

MIN_SCORE = 55.0
MAX_LINES = 10


_MISSING: Optional[str] = None


def _have_deps() -> bool:
    """True when PyMuPDF and rapidfuzz are both importable, said out loud once.

    Both imports used to sit in a `except ImportError: return None`, which
    made an uninstalled dependency indistinguishable from a quote that is
    genuinely not on the page. rapidfuzz is declared only in the inference
    app's requirements, so on the cluster every call returned None and every
    extracted value came out with no rectangles and a not_located flag — a
    whole evidence chain missing, without one line of log.
    """
    global _MISSING
    if _MISSING is not None:
        return _MISSING == ""
    try:
        import fitz            # noqa: F401
        from rapidfuzz import fuzz    # noqa: F401
    except ImportError as exc:
        _MISSING = str(exc)
        log.error("quote location is OFF for this whole run: %s. Every value "
                  "will be recorded without the rectangles that show where it "
                  "came from. pip install rapidfuzz pymupdf", exc)
        return False
    _MISSING = ""
    return True


def quote_rects(pdf_path, page_number: int, quote: str,
                min_score: float = MIN_SCORE,
                max_lines: int = MAX_LINES) -> Optional[list]:
    """
    Highlight rects for *quote* on a (1-based) PDF page, one box per text LINE
    the matched span touches, capped at *max_lines*.

    Rects are [x0, y0, x1, y1] in PDF points, top-left origin (fitz) — the
    convention `pdfjs_overlay.js` draws. Returns None if PyMuPDF/rapidfuzz are
    missing, the file or page is unavailable, or the best match scores under
    *min_score*.
    """
    words = page_words(pdf_path, page_number)
    if not words:
        return None
    return rects_from_words(words, quote, min_score=min_score,
                            max_lines=max_lines)


def page_words(pdf_path, page_number: int) -> Optional[list]:
    """PyMuPDF's word tuples for one (1-based) page, or None.

    Split out so a caller placing many quotes on the same page can open the
    file once. The extraction stage places several hundred quotes per
    document, and opening a PDF over NFS per quote costs far more than the
    matching does.
    """
    if not _have_deps():
        return None
    import fitz
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        if not (1 <= int(page_number) <= doc.page_count):
            return None
        return doc.load_page(int(page_number) - 1).get_text("words")
    except Exception:
        return None
    finally:
        doc.close()


def rects_from_words(words: list, quote: str,
                     min_score: float = MIN_SCORE,
                     max_lines: int = MAX_LINES) -> Optional[list]:
    """The matching itself: no file access, only the page's words and a quote."""
    if not _have_deps():
        return None
    from rapidfuzz import fuzz
    if not (quote or "").strip() or not words:
        return None

    # Rebuild the page text as space-joined words, tracking each word's char
    # span, rect and (block, line) key (words = x0,y0,x1,y1,word,block,line,n).
    parts: list = []
    spans: list = []
    pos = 0
    for w in words:
        wt = w[4]
        if not wt:
            continue
        if parts:
            pos += 1                              # the joining space
        start = pos
        pos += len(wt)
        parts.append(wt)
        spans.append((start, pos, (w[0], w[1], w[2], w[3]), (w[5], w[6])))
    text = " ".join(parts)
    if not text.strip():
        return None

    al = fuzz.partial_ratio_alignment(quote, text)
    if al is None or al.score < min_score:
        return None
    a, b = al.dest_start, al.dest_end

    # Merge every word inside the matched char span into one rect per line.
    lines: dict = {}
    order: list = []
    for s, e, (x0, y0, x1, y1), key in spans:
        if e <= a or s >= b:                      # word outside the matched span
            continue
        if key not in lines:
            lines[key] = [x0, y0, x1, y1]
            order.append(key)
        else:
            r = lines[key]
            r[0] = min(r[0], x0)
            r[1] = min(r[1], y0)
            r[2] = max(r[2], x1)
            r[3] = max(r[3], y1)
    if not order:
        return None
    return [[round(v, 2) for v in lines[k]] for k in order[:max_lines]]
