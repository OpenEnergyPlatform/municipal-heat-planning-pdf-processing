# docpipe.preprocessing.stage1_extract

`docpipe/preprocessing/stage1_extract.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stage1_extract.py: Extracts text with PyMuPDF, as rawdict.

Text blocks are extracted per page and returned as PageData. Paragraphs are
deliberately not merged: Stage 2 suppression needs block boundaries precise
enough to match model-predicted boxes. Bboxes are [x0, y0, x1, y1] in points,
origin top-left, stored without coordinate flipping.

Author: Felix Vossel

## Functions

### hyphen_exceptions

```python
def hyphen_exceptions()
```

Words that must not be pulled across a line-ending hyphen.

"Wärme-" + "und Kälteversorgung" is one construction, not one word, and so
is "short-" + "and long-term". Which words do that is a property of the
language, so the profile says so; the core would silently glue the wrong
corpus together.

### extract_all_pages

```python
def extract_all_pages(
    pdf_path: str | Path,
    page_range: Optional[tuple[int, int]] = None,
) -> tuple[list[PageData], list[fitz.Page], fitz.Document, int]
```

Extracts text and returns (pages, fitz_pages, fitz_doc, n_failed), where
fitz_pages is index-aligned with pages and n_failed counts pages that were
skipped. *page_range* is (start, end), 0-indexed and end-exclusive.

The caller MUST close fitz_doc once Stage 2 is done: the returned
fitz.Page objects are only valid while their parent document is open.

[Back to the index](../README.md)
