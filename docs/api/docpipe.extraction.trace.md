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

The rule `trace_on` (setting `EXTRACT_TRACE=0` turns it off) decides whether
a run traces at all: off, every call to record an event returns immediately.
`trace_requests` says whether an event carries its request and reply;
`trace_compress`, `trace_time_places` and `trace_piece_min_chars` the file's
form (owner decision 2026-11-11). Each is read where it is used.

Everything a run does can be read back from its trace, not only what it asked
(owner decision 2026-11-14: "sodass eigentlich alles rekonstruierbar ist").
A document's trace starts with its head (`run`: the commit of the code, the
image, the profile, the models, every rule in effect with what authenticates
blanked, the drawing of the flow). Every request is numbered in its document
(`rid`), and one that asks a request again (a follow-up, the same request
with a picture or with the pieces its answer fetched) names the one it
follows (`of`). Every search is numbered too (`sid`, `searching`): the
vector search, the reranker and the pieces taken write their events under
its number, and the requests that show its pieces name it.

Author: Felix Vossel

## Functions

### enabled

```python
def enabled() -> bool
```

Whether the run traces (rule `trace_on`), read when asked: a run's
value, whatever step is writing.

### open_trace

```python
def open_trace(directory, name_of: Callable) -> None
```

Start writing traces under `directory`, naming files via `name_of(id)`.

### open_stage

```python
def open_stage(given, batch: bool, stage: str, prompt_ids=(),
               model: Optional[str] = None) -> None
```

Start the request log of *stage* for the documents of the folder a
run of it was *given*: the processed root where it reads every document
(*batch*), else one document's folder. Each document's log starts with
the head of the run (`stage_head`).

### stage_head

```python
def stage_head(stage: str, prompt_ids=(), model: Optional[str] = None) -> dict
```

What a run of a stage is, at the head of each document's log: the
stage, the commit of its code, the profile, the *model* it asks, and the
text of each prompt of *prompt_ids* as the run reads it. With those
texts the editor reads back what a request's messages were filled with
after a prompt file has changed (`editor.staged`).

### working_on

```python
@contextlib.contextmanager
def working_on(folder)
```

The requests of the block are those of the document in *folder*.

### working

```python
def working() -> Optional[tuple]
```

(name, folder) of the document a stage works on here, None outside
one.

### stage_request

```python
def stage_request(kind: str, sent: dict, attempt: int, asked_at: float, *,
                  response=None, error=None, doc=None, **notes) -> None
```

One attempt of a request of a stage before the harvest, in its
document's log: the request as *sent*, its reply or *error*, its times
and tokens, and *notes* (what it is `made` of, its page and heading).
*doc* is the document's name, the one the stage `working_on` where not
given; nothing outside a document.

### set_head

```python
def set_head(maker: Optional[Callable]) -> None
```

What every document's trace starts with: *maker()* -> {field: value},
made once a run, the first time a trace is opened (`run`). None: no
head.

### blanked

```python
def blanked(values: dict, known: Optional[dict] = None) -> dict
```

*values* as a trace may hold them: a trace is read by people a key
must not reach. What is a secret is what the editor never shows: a rule
that says it is one (`secret`, of *known*, the rules of the run, the
core's when not given), and a name no rule defines that ends the way a
secret's name ends (`settings.SECRET_NAME`); a secret that is set is
written as `BLANKED`, an empty one stays empty. Every other value is
written whole, but an address without the user and password before its
host (`rulespage.masked`).

### compressed

```python
def compressed() -> bool
```

Whether a trace is written compressed (rule `trace_compress`).

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

### last_request

```python
def last_request(document_id: Optional[int] = None) -> Optional[int]
```

The number of the request this thread reported last (`rid`), None
where it reported none, or none of *document_id*.

### searching

```python
@contextlib.contextmanager
def searching(document_id: Optional[int], /, **about)
```

One search of *document_id* under a number of its own (`sid`): its
`search` event with *about* (its sentences, what asked it), and the
events of its vector search, reranker and pieces written under the same
number (`in_search`). A search inside a search of the same document is
part of it and takes its number. Yields the number, None where nothing
is traced.

### search_state

```python
def search_state(document_id: Optional[int] = None) -> Optional[dict]
```

The search running here (`searching`), None where none runs or it
is another document's.

### last_search

```python
def last_search(document_id: Optional[int] = None) -> Optional[int]
```

The number of the search this thread began last, None where it began
none, or none of *document_id*.

### in_search

```python
def in_search(kind: str, document_id: Optional[int], /, **fields) -> None
```

An event of the search running here, under its number; one written
where no search of the document runs begins a search of its own
(`searching`) and is written under that.

### ms_since

```python
def ms_since(started: float) -> int
```

Milliseconds since *started* (`time.time()`).

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

### close_stage

```python
def close_stage() -> None
```

End the request log `open_stage` began: close every trace and forget
the stage's head, so that what traces next in the process starts with a
head of its own or with none.

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

### head_of

```python
def head_of(events, pieces: Optional[dict] = None) -> dict
```

The head of a trace (`run`, `_write_head`), each value written as a
piece put back; {} where the trace has none. *pieces* are those of its
file (`pieces_of`), read from *events* where not given.

### sent

```python
def sent(record: dict, pieces: dict) -> Optional[dict]
```

The request *record* reports, as it was sent, or None where it carries
none. *pieces* are the pieces of its file (`pieces_of`).

[Back to the index](../README.md)
