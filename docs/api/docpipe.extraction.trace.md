# docpipe.extraction.trace

`docpipe/extraction/trace.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

trace.py: Records what the harvest did as one JSON event per line, so it can be
counted after the run.

A text log tells a human reading it live what happened. It cannot answer
questions about a distribution over many requests, such as at which rank a
value was found, in which window a coordinate closed, or whether a retry
helped. Every setting this stage has, including `top_k`, the window budget, and
the batch thread count, was chosen at least once without such a distribution,
and every one of those choices was wrong.

Each document therefore gets a second file next to its harvest, with one JSON
object per event and nothing aggregated. Aggregation is left to the report
script, which can be rewritten when the question changes; the trace itself
cannot be rewritten after the fact.

The cost is a few hundred bytes per model request, about half a megabyte per
document. Setting `EXTRACT_TRACE=0` turns tracing off, and every call to record
an event then returns immediately.

Author: Felix Vossel

## Functions

### open_trace

```python
def open_trace(directory, name_of: Callable) -> None
```

Start writing traces under `directory`, naming files via `name_of(id)`.

### event

```python
def event(kind: str, document_id: Optional[int] = None, /, **fields) -> None
```

One line of trace. Never raises: a broken trace must not kill a harvest.

Both arguments are positional-only: an event's own fields are free-form
and several of them are called `kind` or `status`, which would otherwise
collide with the signature rather than land in the record.

### flush

```python
def flush(document_id: Optional[int] = None) -> None
```

Push what is buffered to disk, for one document or for all of them.

### close

```python
def close() -> None
```

Close every open trace. Safe to call twice.

[Back to the index](../README.md)
