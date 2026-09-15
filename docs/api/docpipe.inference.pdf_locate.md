# docpipe.inference.pdf_locate

`docpipe/inference/pdf_locate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pdf_locate.py: Locates where a quote sits on the page of the source
PDF.

One implementation serves two callers: the app highlights the
passage it shows, and the extraction stage records the same
rectangles as the provenance of a value. A second implementation
would give two answers to where a value comes from, the one question
the whole evidence chain exists to answer.

The match is fuzzy on purpose. The corpus text has passed through
extraction and refinement, so it is never byte-identical to what
PyMuPDF reads off the page: ligatures, hyphenation, running heads and
column order all differ. Alignment finds the passage anyway; the
score floor keeps it from pointing at something else.

Author: Felix Vossel

## Functions

### quote_rects

```python
def quote_rects(pdf_path, page_number: int, quote: str,
                min_score: float = MIN_SCORE,
                max_lines: int = MAX_LINES) -> Optional[list]
```

Highlight rects for *quote* on a (1-based) PDF page, one box per text LINE
the matched span touches, capped at *max_lines*.

Rects are [x0, y0, x1, y1] in PDF points, top-left origin (fitz) — the
convention `pdfjs_overlay.js` draws. Returns None if PyMuPDF/rapidfuzz are
missing, the file or page is unavailable, or the best match scores under
*min_score*.

### page_words

```python
def page_words(pdf_path, page_number: int) -> Optional[list]
```

PyMuPDF's word tuples for one (1-based) page, or None.

Split out so a caller placing many quotes on the same page can open the
file once. The extraction stage places several hundred quotes per
document, and opening a PDF over NFS per quote costs far more than the
matching does.

### rects_from_words

```python
def rects_from_words(words: list, quote: str,
                     min_score: float = MIN_SCORE,
                     max_lines: int = MAX_LINES) -> Optional[list]
```

The matching itself: no file access, only the page's words and a quote.

[Back to the index](../README.md)
