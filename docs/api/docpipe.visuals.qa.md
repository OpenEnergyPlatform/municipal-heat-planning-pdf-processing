# docpipe.visuals.qa

`docpipe/visuals/qa.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

qa.py: Quality checks for vision model table extraction.

Pure helper functions that judge a vision model's Markdown
transcription of a table. Coverage compares it against the PyMuPDF
source text and catches truncation; duplication counts repeated rows
and catches repetition loops.

Author: Felix Vossel

## Functions

### salient_tokens

```python
def salient_tokens(text: str) -> set[str]
```

Lowercased numbers and words (>= 2 letters) found in *text*.

### coverage

```python
def coverage(source_text: str, markdown: str,
             min_source_tokens: int = 8) -> Optional[float]
```

Fraction of the source's salient tokens that also appear in the markdown.

None when the source has fewer than *min_source_tokens* salient tokens
(e.g. an image-only table with no text layer) — too little reference text
to judge fairly. Not 1.0: an unmeasurable table is unknown, not perfect,
and a scanned corpus would otherwise report a flawless QA pass for every
table nobody ever checked.

### duplication

```python
def duplication(markdown: str) -> float
```

Fraction of duplicate data rows (0..1); 0 when there are fewer than 2.

### dedup_consecutive_rows

```python
def dedup_consecutive_rows(markdown: str) -> str
```

Collapse runs of identical consecutive data rows (the stutter pattern).

### assess

```python
def assess(
    markdown: str,
    source_text: str = "",
    *,
    min_coverage: float = 0.5,
    max_duplication: float = 0.4,
    min_source_tokens: int = 8,
) -> tuple[bool, dict]
```

Judge a table Markdown transcription. Returns (passed, metrics).

Fails when there are no data rows, duplication exceeds *max_duplication*,
or coverage (when assessable) is below *min_coverage*.

[Back to the index](../README.md)
