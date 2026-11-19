# docpipe.editor.requests

`docpipe/editor/requests.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

requests.py: The model requests of an extraction trace, read from its events.

One dict per `*_ask` event with what was sent, what came back and what became
of it (taken, asked again, no answer, unreadable); the chain of one value; the
filter that picks requests; and `Traces`, which reads each trace of a harvest
folder once per state of its file. No page and no server in here. Moved out of
`scripts/chat_view.py` so that the script and the editor share one version.

Author: Felix Vossel

## Classes

### Trace

```python
class Trace
```

One trace file read once: its events, its pieces and its requests.

#### Trace.\_\_init\_\_

```python
def __init__(self, path, events: list, profile=None)
```

#### Trace.sent

```python
def sent(self, index: int) -> Optional[dict]
```

The request `requests[index]` reports, as it was sent.

#### Trace.carried

```python
def carried(self, index: int) -> tuple
```

The fields the message of request *index* carries: the keys of
its payload, and what its reply form offers ("more", "get_image"),
() where it shows none. Which parts of its prompt a request is told
hangs on them (`runner.request_prompt`).

#### Trace.kinds

```python
def kinds(self) -> list
```

#### Trace.fields

```python
def fields(self) -> list
```

### Traces

```python
class Traces
```

The traces of a harvest folder, and the request logs of the stages
before the harvest in the documents' folders of *stages* (the processed
folder: `<document>/<stage>.trace.jsonl.gz`, named "\<document>/\<stage>";
owner request 2026-11-19, A3), each read at most once per state of its
file.

#### Traces.\_\_init\_\_

```python
def __init__(self, folder: Optional[Path], lines=trace.lines,
             stages: Optional[Path] = None, profile=None)
```

#### Traces.names

```python
def names(self, which: Optional[str] = None) -> list
```

The traces by name: every one, or for *which* "harvest" the
harvest's only, for a stage's name ("refinement", "visuals") that
stage's logs only.

#### Traces.path_of

```python
def path_of(self, name: str) -> Optional[Path]
```

#### Traces.load

```python
def load(self, name: str) -> Trace
```

The trace *name*; KeyError for a name the folder has not. The same
object comes back until the file changes on disk.

## Functions

### requests_of

```python
def requests_of(events: list, profile=None) -> list
```

One dict per `*_ask` event, in trace order. A reply of a stage
before the harvest is read with the sentences of *profile*
(`stage_check`), the ambient one's where not given.

### reply_key

```python
def reply_key(shape) -> Optional[tuple]
```

(the key a stage before the harvest reads its reply by, the type it
has to be) from the reply form *shape* a request was sent with: the
first required key of its schema, as the stage reads it
(`vision.reply_type`, `refine`); None where it names none.

### stage_check

```python
def stage_check(request: dict, profile=None) -> str
```

What became of a request of a stage before the harvest, read as the
stage reads its reply (`reading.read`, by the key of its reply form):
"taken", or "unreadable: \<cause>", a reply the stage asks again. The
sentences of *profile* where it is not the ambient one.

### chain_of

```python
def chain_of(requests: list, index: int) -> list
```

Indexes of the requests of one value: the find of its parameter and
passage, the readings and follow-ups, and the list entries asked for its words.

### keep

```python
def keep(request: dict, kinds=(), fields=(), owners=(), values=(),
         contains=()) -> bool
```

Whether *request* passes the filter: one of *kinds* (`coord_ask` counts
as `coord`), one of *fields*, *owners* and *values* (compared as strings),
and every text of *contains* (any case) somewhere in its instruction,
message or answer. An empty argument keeps everything.

[Back to the index](../README.md)
