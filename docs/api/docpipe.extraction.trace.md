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

Every event that reports a model request also carries the request as it was
sent (`input`) and what came back (`output`: the reply, or the error the
request ended in), so that a run can be read back request by request (owner
decision 2026-11-05). The request is taken where every request of the stage
passes (`scheduler.Repeats`, `exchanged`) and goes into the next event of the
same thread that reports it: one that carries `prompt_tokens`, or an error of
kind `exception`. With it go the request's times, to the millisecond
(`asked_at`, `sent_at`, `answered_at`: when the caller asked, when it left
the run's queue for the server, when its answer or error came), and `once`
where the answer is that of the same request sent before in the document
and nothing was sent (owner decision 2026-11-07).

Nothing repeated is written twice. A text longer than a reference to it -- a
system prompt, a reply format, a passage, a parameter's description, a list of
options, a picture -- is written once per document as a `piece` event and
referenced by its hash; a payload that is a JSON object is split at its
top-level keys first, and put back with the writing that made it, so `sent`
returns each message character for character. The file is compressed
(`<name>.trace.jsonl.gz`). `lines` reads it, and a trace an earlier run wrote
uncompressed (`<name>.trace.jsonl`), and ends quietly where a killed run left
it.

Setting `EXTRACT_TRACE=0` turns tracing off, and every call to record an event
then returns immediately.

Author: Felix Vossel

## Functions

### open_trace

```python
def open_trace(directory, name_of: Callable) -> None
```

Start writing traces under `directory`, naming files via `name_of(id)`.

### exchanged

```python
def exchanged(request: dict, response=None, error=None, *,
              times: Optional[tuple] = None, once: bool = False) -> None
```

The request the calling thread has just sent, with the reply that came
back or the error it ended in, for the event that reports it (`event`).
A thread's next request takes the place of one no event reported.
*times* are (asked, sent, answered) in seconds since the epoch, sent
None where no queue held the request; *once* says the answer is that of
the same request sent before and nothing was sent
(`scheduler.Once`).

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

### is_trace

```python
def is_trace(path) -> bool
```

### name_of

```python
def name_of(path) -> str
```

The document name a trace file is written under.

### path_of

```python
def path_of(directory, name: str) -> Optional[Path]
```

The trace of *name* in *directory*, or None where there is none.

### files

```python
def files(directory) -> list
```

Every trace in *directory*, one per name in name order; where a name
has both files, the compressed one, which is the later run's.

### lines

```python
def lines(path, kinds: Optional[Iterable[str]] = None) -> Iterator[dict]
```

The events of a trace file of either kind, pieces among them; none for
a file that is not there. A run that was killed leaves a last line cut
short or a compressed stream without its end: reading stops there, with
everything before it.

*kinds*, where given, are the only events read. A line that does not name
one of them anywhere is passed over without being parsed, which spares
the requests and pieces that make most of a trace; the order of an
event's keys decides nothing.

### pieces_of

```python
def pieces_of(events) -> dict
```

{reference: text} of the pieces among *events*.

### sent

```python
def sent(record: dict, pieces: dict) -> Optional[dict]
```

The request *record* reports, as it was sent, or None where it carries
none. *pieces* are the pieces of its file (`pieces_of`).

[Back to the index](../README.md)
