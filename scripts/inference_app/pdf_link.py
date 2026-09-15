"""
pdf_link.py: Builds deep links into the source PDF for one citation.

A section's chunk text is refined by the LLM and differs from the raw PDF
text, so a verbatim `#page=N&search=...` term has to come from the raw
page text: the page-tagged `Segments`, or the PDF file itself.

The module is pure: no database access, no Streamlit import. Database
reads live in `db.py`.
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
    Best (page, search_phrase) for a refined `quote` against raw page `segments`
    of (page, raw_text). None if no run of at least `min_words` words is found —
    the caller then links to the page without a highlight.

    The phrase is a VERBATIM substring of the raw text (punctuation/spacing
    preserved, only inner whitespace collapsed), capped at `max_words`. Verbatim
    matters: the phrase must occur literally in the PDF text layer for the
    highlight to land — a punctuation-stripped, space-joined reconstruction
    (e.g. "Emmy Noether Str" for "Emmy-Noether-Str.") would not.
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

    `segments` are (page, text, rects) triples (db.section_segments_geo). None
    when no segment shares a run of at least `min_words` words *and* carries
    geometry — the caller then falls back to the `&search=` phrase.

    NOT used for the live highlight: a segment's stored bbox can cover the whole
    page, which would box everything. Use `best_quote_rects` for that.
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
    on-disk name, so it is percent-encoded exactly once here — pass it unencoded.
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
    Deep link through the bundled pdf.js viewer, which highlights in every
    browser (Chrome's native viewer ignores `#search`).

    The PDF path must be same-origin with the viewer — pdf.js requires it.

    Highlight, in order of precedence:
      * `rects` → `&mhl=<base64url rects>`, drawn by `pdfjs_overlay.js`.
        `&search=` is omitted so the two do not double-highlight.
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
    Verbatim phrase from the ACTUAL PDF page that best matches `quote`, snapped
    to word boundaries and capped at `max_words`.

    `page_number` is 1-based. Returns None if PyMuPDF/rapidfuzz aren't installed,
    the file/page is unavailable, or the best match scores under `min_score` —
    the caller then falls back to the Segments-based phrase (locate_quote).
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
                     min_score: float = 55.0, max_lines: int = 10):
    """Highlight rects for `quote` on a (1-based) PDF page.

    The implementation lives in `docpipe.inference.pdf_locate`, because the
    extraction stage records the same rectangles as a value's provenance and
    two copies would mean two answers to "where does this come from".
    """
    from docpipe.inference.pdf_locate import quote_rects
    return quote_rects(pdf_path, page_number, quote,
                       min_score=min_score, max_lines=max_lines)
