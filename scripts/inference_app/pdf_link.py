"""
pdf_link.py – Build deep links into the source PDF for a citation.

A section's chunk text is LLM-refined, so it differs from the raw PDF text; a
verbatim `#page=N&search=...` term must therefore come from the RAW page text.
The batch pipeline already stores that as page-tagged `Segments` (the
pre-refinement provenance the LLM never saw). Given the grounding quote (drawn
from the refined text) we find the longest contiguous word-run it shares with a
raw segment: that run exists verbatim in the segment — hence in the PDF text
layer (extraction is PyMuPDF `get_text`, not OCR) — so it is a safe `&search=`
anchor, and the segment's page is the exact page of the quote.

Pure (no DB, no Streamlit) so it is unit-testable; the DB reads live in db.py.
"""
from __future__ import annotations

import base64
import json
import re
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import quote as _urlquote

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(s: str) -> list[str]:
    return _WORD.findall(s or "")


def locate_quote(
    quote: str,
    segments: list[tuple[int, str]],
    min_words: int = 3,
    max_words: int = 8,
) -> Optional[tuple[int, str]]:
    """
    Best (page, search_phrase) for a refined `quote` against raw page `segments`.

    Each segment is (page, raw_text). Returns the page of the segment sharing the
    longest contiguous word-run with the quote, plus that run as a **verbatim
    substring of the raw text** (original punctuation/spacing preserved, only
    inner whitespace collapsed), capped at `max_words` words, as the `&search=`
    phrase. Verbatim matters: the phrase must occur literally in the PDF text
    layer for the highlight to land — a punctuation-stripped, space-joined
    reconstruction (e.g. "Emmy Noether Str" for "Emmy-Noether-Str.") would not.
    Returns None if no run of at least `min_words` words is found (refinement
    diverged too far → the caller links to the page only, without a highlight).
    """
    q = [w.casefold() for w in _words(quote)]
    if len(q) < min_words:
        return None
    best: Optional[tuple[int, int, str]] = None   # (size, page, phrase)
    for page, text in segments:
        toks = list(_WORD.finditer(text))         # words WITH their char offsets
        if len(toks) < min_words:
            continue
        r = [m.group(0).casefold() for m in toks]
        m = SequenceMatcher(None, q, r, autojunk=False).find_longest_match(
            0, len(q), 0, len(r))
        if m.size >= min_words and (best is None or m.size > best[0]):
            last = min(m.b + m.size, m.b + max_words) - 1
            phrase = re.sub(r"\s+", " ", text[toks[m.b].start(): toks[last].end()]).strip()
            best = (m.size, page, phrase)
    if best is None:
        return None
    return best[1], best[2]


def best_segment_rects(
    quote: str,
    segments: list[tuple[int, str, Optional[list]]],
    min_words: int = 3,
) -> Optional[tuple[int, list]]:
    """
    (page, rects) of the raw text segment that best matches `quote`, for a
    coordinate highlight overlay in the PDF viewer.

    `segments` are (page, text, rects) triples (db.section_segments_geo); rects
    is that segment's list of [x0, y0, x1, y1] PDF-point rectangles. The matched
    segment is the one sharing the longest contiguous word-run with the quote —
    the same rule `locate_quote` uses for its search phrase, so the coordinate
    overlay lands on the exact segment the phrase highlight would. Returns None
    when no segment shares a run of at least `min_words` words *and* carries
    geometry (the caller then falls back to the `&search=` phrase).
    """
    q = [w.casefold() for w in _words(quote)]
    if len(q) < min_words:
        return None
    best: Optional[tuple[int, int, list]] = None    # (size, page, rects)
    for page, text, rects in segments:
        if not rects:
            continue
        r = [w.casefold() for w in _words(text)]
        if len(r) < min_words:
            continue
        m = SequenceMatcher(None, q, r, autojunk=False).find_longest_match(
            0, len(q), 0, len(r))
        if m.size >= min_words and (best is None or m.size > best[0]):
            best = (m.size, page, rects)
    if best is None:
        return None
    return best[1], best[2]


def encode_rects(rects: list) -> str:
    """URL-safe token carrying the highlight rects for the viewer's `&mhl=` hash
    param: base64url of compact JSON, padding stripped (added back in JS)."""
    raw = json.dumps(rects, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pdf_page_url(prefix: str, filename: str, page: int,
                 phrase: Optional[str] = None) -> str:
    """
    Deep link to `filename` in the served PDF area at `page`, optionally with a
    `search` highlight term.

    `filename` is stored RAW in the DB (e.g. a literal `ö`) and matches the
    on-disk name, so it is percent-encoded once here for the URL path; the static
    server decodes it back to the on-disk name. The `#page=N&search=...` fragment
    is the PDF Open-Parameters / pdf.js form.
    """
    url = f"{prefix.rstrip('/')}/{_urlquote(filename)}#page={int(page)}"
    if phrase:
        # the search value must be wrapped in double quotes → search="…"
        url += "&search=" + _urlquote(f'"{phrase}"')
    return url


def pdf_viewer_url(viewer_prefix: str, pdf_prefix: str, filename: str, page: int,
                   phrase: Optional[str] = None,
                   rects: Optional[list] = None) -> str:
    """
    Deep link through the bundled **pdf.js** viewer, for DETERMINISTIC highlight
    in every browser (Chrome's native viewer ignores `#search`).

    Form: `<viewer>/viewer.html?file=<encoded pdf path>#page=N&…`. The PDF path
    is same-origin (both under the static route), which pdf.js requires.

    Highlight, in order of precedence:
      * `rects` given → `&mhl=<base64url rects>`, read by the bundled
        `pdfjs_overlay.js` companion, which draws a coordinate box on the page
        (exact, resolution-independent). `&search=` is omitted so the two do not
        double-highlight.
      * else `phrase` → `&search="…"&phrase=true` (pdf.js text-layer find).
    """
    pdf_path = f"{pdf_prefix.rstrip('/')}/{_urlquote(filename)}"
    file_param = _urlquote(pdf_path, safe="")
    url = f"{viewer_prefix.rstrip('/')}/viewer.html?file={file_param}#page={int(page)}"
    if rects:
        url += "&mhl=" + encode_rects(rects)
    elif phrase:
        # the search value must be wrapped in double quotes → search="…"
        url += "&search=" + _urlquote(f'"{phrase}"') + "&phrase=true"
    return url


def best_search_phrase(pdf_path, page_number: int, quote: str,
                       max_words: int = 8, min_score: float = 55.0) -> Optional[str]:
    """
    Verbatim phrase from the ACTUAL PDF page that best matches `quote`.

    Opens the real PDF (PyMuPDF) and fuzzy-aligns the refined quote to the page's
    OWN extracted text (rapidfuzz `partial_ratio`, a Levenshtein-based score),
    then returns that text slice. Because the phrase is drawn from the same text
    layer the browser searches, pdf.js is far likelier to highlight it than a
    phrase reconstructed from our (differently-extracted, refined) Segments. The
    span is snapped to word boundaries and capped at `max_words`.

    Returns None if PyMuPDF/rapidfuzz aren't installed, the file/page is
    unavailable, or the best match is too weak — the caller then falls back to
    the Segments-based phrase (locate_quote).
    """
    try:
        import fitz
        from rapidfuzz import fuzz
    except ImportError:
        return None
    if not (quote or "").strip():
        return None
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        if not (1 <= int(page_number) <= doc.page_count):
            return None
        text = doc.load_page(int(page_number) - 1).get_text()
    except Exception:
        return None
    finally:
        doc.close()
    if not text.strip():
        return None
    al = fuzz.partial_ratio_alignment(quote, text)
    if al is None or al.score < min_score:
        return None
    a, b = al.dest_start, al.dest_end
    while a > 0 and text[a - 1].isalnum():           # snap start to a word boundary
        a -= 1
    while b < len(text) and text[b].isalnum():        # snap end to a word boundary
        b += 1
    span = re.sub(r"\s+", " ", text[a:b]).strip()
    words = span.split(" ")
    if len(words) > max_words:
        span = " ".join(words[:max_words])
    return span if len(span.split(" ")) >= 3 else None


def best_quote_rects(pdf_path, page_number: int, quote: str,
                     min_score: float = 55.0, max_lines: int = 10) -> Optional[list]:
    """
    Precise highlight rects for `quote` on a PDF page, one box per text LINE.

    Fuzzy-aligns the (refined) quote to the page's OWN word stream (PyMuPDF +
    rapidfuzz `partial_ratio`, a Levenshtein score) and returns the bounding
    rect of each line the matched span actually touches — so the overlay marks
    exactly the quoted passage, NOT the whole segment or page (a Stage-3 text
    segment can span a page; its stored bbox would light up everything).

    Rects are [x0,y0,x1,y1] in PDF points, top-left origin (fitz) — the same
    convention `pdfjs_overlay.js` draws. Returns None if PyMuPDF/rapidfuzz are
    missing, the file/page is unavailable, or the best match is too weak (the
    caller then falls back to the `&search=` phrase).
    """
    try:
        import fitz
        from rapidfuzz import fuzz
    except ImportError:
        return None
    if not (quote or "").strip():
        return None
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        if not (1 <= int(page_number) <= doc.page_count):
            return None
        words = doc.load_page(int(page_number) - 1).get_text("words")
    except Exception:
        return None
    finally:
        doc.close()
    if not words:
        return None

    # Rebuild the page text as space-joined words, tracking each word's char
    # span, rect and (block, line) key (words = x0,y0,x1,y1,word,block,line,n).
    parts: list[str] = []
    spans: list[tuple] = []
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
            r[0] = min(r[0], x0); r[1] = min(r[1], y0)
            r[2] = max(r[2], x1); r[3] = max(r[3], y1)
    if not order:
        return None
    return [[round(v, 2) for v in lines[k]] for k in order[:max_lines]]
