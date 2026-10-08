# docpipe.visuals.process

`docpipe/visuals/process.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

process.py: Core processing logic for table and figure enrichment.

Sends one table or figure image to the vision model, together with
its section context, and returns a copy of the item carrying the
model's markdown or description. A table's transcription passes a
quality gate and gets one retry with a stronger prompt on failure. An
image the model could not be read an object for (see vision.call_vision)
has no content: the item carries no markdown or description, says why in
`vlm_why`, and is counted by cause. No plain-text request fills in for it.

Author: Felix Vossel

## Functions

### process_table

```python
def process_table(
    table: dict,
    section: dict,
    base_path: Path,
    client: openai.OpenAI,
    stats: ProcessingStats,
    *,
    model: str | None = None,
    lock: threading.Lock | None = None,
    source_text: str = "",
) -> dict
```

Returns a copy of *table* enriched with a ``markdown`` key.

A QA gate checks coverage against *source_text* and row duplication; on
failure the table is still returned (best effort) but carries a
``qa_warning`` field. The result of the check is kept for every table the
model transcribed, as ``qa`` (the metrics of the kept attempt and whether
it passed). A table the model gave no object for has none: it was not
checked, which is not the same as passed. It has no ``markdown`` either,
and says why in ``vlm_why``.

*lock* guards the shared ProcessingStats: without it this is not safe to
call from several threads at once.

### process_figure

```python
def process_figure(
    figure: dict,
    section: dict,
    base_path: Path,
    client: openai.OpenAI,
    stats: ProcessingStats,
    *,
    model: str | None = None,
    lock: threading.Lock | None = None,
) -> dict
```

Returns a copy of *figure* enriched with a ``description`` key.

*lock* guards the shared ProcessingStats: without it this is not safe to
call from several threads at once.

[Back to the index](../README.md)
