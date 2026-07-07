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
        url += f"&search={_urlquote(phrase)}"
    return url


def pdf_viewer_url(viewer_prefix: str, pdf_prefix: str, filename: str, page: int,
                   phrase: Optional[str] = None) -> str:
    """
    Deep link through the bundled **pdf.js** viewer, for DETERMINISTIC highlight
    in every browser (Chrome's native viewer ignores `#search`).

    Form: `<viewer>/viewer.html?file=<encoded pdf path>#page=N&search=<phrase>&phrase=true`.
    The PDF path is same-origin (both under the static route), which pdf.js
    requires; `phrase=true` makes `search` an exact-phrase find.
    """
    pdf_path = f"{pdf_prefix.rstrip('/')}/{_urlquote(filename)}"
    file_param = _urlquote(pdf_path, safe="")
    url = f"{viewer_prefix.rstrip('/')}/viewer.html?file={file_param}#page={int(page)}"
    if phrase:
        url += f"&search={_urlquote(phrase)}&phrase=true"
    return url
