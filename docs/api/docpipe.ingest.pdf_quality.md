# docpipe.ingest.pdf_quality

`docpipe/ingest/pdf_quality.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pdf_quality.py: Grades what a source PDF's text layer is worth.

Stage 1 reads text with PyMuPDF, never OCR. A PDF with a broken ToUnicode map
yields symbol garbage, useless at every later stage. A PDF with no text layer
at all yields nothing, which preprocessing can now make good by rendering the
page and having the model read it (page_text_fallback).

`check()` reports the fact and nothing more. What to do about it is policy, and
lives in the ingest pipeline: garbled text is refused, a scan is registered and
put on a worklist. Keeping the two apart is the point. This module used to
decide both, and its verdict on a scan cost the corpus eleven complete plans.

## Functions

### is_missing_text_layer

```python
def is_missing_text_layer(reason: str) -> bool
```

True if check() withheld a file only because it carries no text layer.

Such a file is a scan, not garbage: preprocessing renders each page and the
model transcribes it, so it belongs in the corpus. Anything else check()
reports is a file nothing downstream can repair.

### inspect

```python
def inspect(pdf_path: Path, limit: int = SAMPLE_PAGES) -> dict
```

Text-layer metrics over a page sample. Raises on an unreadable PDF.

### check

```python
def check(pdf_path: Path, limit: int = SAMPLE_PAGES) -> tuple[bool, str]
```

(usable, reason). `usable` is False when the PDF has no text layer or its
text is garbled; `reason` is a short diagnosis for the log.

[Back to the index](../README.md)
