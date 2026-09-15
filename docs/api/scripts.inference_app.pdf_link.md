# scripts.inference_app.pdf_link

`scripts/inference_app/pdf_link.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pdf_link.py: Builds deep links into the source PDF for one citation.

A section's chunk text is refined by the LLM and differs from the raw PDF
text, so a verbatim `#page=N&search=...` term has to come from the raw
page text: the page-tagged `Segments`, or the PDF file itself.

The module is pure: no database access, no Streamlit import. Database
reads live in `db.py`.

## Functions

### locate_quote

```python
def locate_quote(
    quote: str,
    segments: list[tuple[int, str]],
    min_words: int = 3,
    max_words: int = 8,
) -> Optional[tuple[int, str]]
```

Best (page, search_phrase) for a refined `quote` against raw page `segments`
of (page, raw_text). None if no run of at least `min_words` words is found —
the caller then links to the page without a highlight.

The phrase is a VERBATIM substring of the raw text (punctuation/spacing
preserved, only inner whitespace collapsed), capped at `max_words`. Verbatim
matters: the phrase must occur literally in the PDF text layer for the
highlight to land — a punctuation-stripped, space-joined reconstruction
(e.g. "Emmy Noether Str" for "Emmy-Noether-Str.") would not.

### best_segment_rects

```python
def best_segment_rects(
    quote: str,
    segments: list[tuple[int, str, Optional[list]]],
    min_words: int = 3,
) -> Optional[tuple[int, list]]
```

(page, rects) of the raw text segment that best matches `quote`, for a
coordinate highlight overlay in the PDF viewer.

`segments` are (page, text, rects) triples (db.section_segments_geo). None
when no segment shares a run of at least `min_words` words *and* carries
geometry — the caller then falls back to the `&search=` phrase.

NOT used for the live highlight: a segment's stored bbox can cover the whole
page, which would box everything. Use `best_quote_rects` for that.

### encode_rects

```python
def encode_rects(rects: list) -> str
```

URL-safe token carrying the highlight rects for the viewer's `&mhl=` hash
param: base64url of compact JSON, padding stripped (added back in JS).

### pdf_page_url

```python
def pdf_page_url(prefix: str, filename: str, page: int,
                 phrase: Optional[str] = None) -> str
```

Deep link to `filename` in the served PDF area at `page`, optionally with a
`search` highlight term.

`filename` is stored RAW in the DB (e.g. a literal `ö`) and matches the
on-disk name, so it is percent-encoded exactly once here — pass it unencoded.

### pdf_viewer_url

```python
def pdf_viewer_url(viewer_prefix: str, pdf_prefix: str, filename: str, page: int,
                   phrase: Optional[str] = None,
                   rects: Optional[list] = None) -> str
```

Deep link through the bundled pdf.js viewer, which highlights in every
browser (Chrome's native viewer ignores `#search`).

The PDF path must be same-origin with the viewer — pdf.js requires it.

Highlight, in order of precedence:
  * `rects` → `&mhl=<base64url rects>`, drawn by `pdfjs_overlay.js`.
    `&search=` is omitted so the two do not double-highlight.
  * else `phrase` → `&search="…"&phrase=true` (pdf.js text-layer find).

### best_search_phrase

```python
def best_search_phrase(pdf_path, page_number: int, quote: str,
                       max_words: int = 8, min_score: float = 55.0) -> Optional[str]
```

Verbatim phrase from the ACTUAL PDF page that best matches `quote`, snapped
to word boundaries and capped at `max_words`.

`page_number` is 1-based. Returns None if PyMuPDF/rapidfuzz aren't installed,
the file/page is unavailable, or the best match scores under `min_score` —
the caller then falls back to the Segments-based phrase (locate_quote).

### best_quote_rects

```python
def best_quote_rects(pdf_path, page_number: int, quote: str,
                     min_score: float = 55.0, max_lines: int = 10)
```

Highlight rects for `quote` on a (1-based) PDF page.

The implementation lives in `docpipe.inference.pdf_locate`, because the
extraction stage records the same rectangles as a value's provenance and
two copies would mean two answers to "where does this come from".

[Back to the index](../README.md)
