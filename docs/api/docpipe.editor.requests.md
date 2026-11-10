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
def __init__(self, path, events: list)
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
its payload, () where it shows none. Which parts of its prompt a
request is told hangs on them (`thread.Parts.system`).

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

The traces of a harvest folder, each read at most once per state of
its file.

#### Traces.\_\_init\_\_

```python
def __init__(self, folder: Optional[Path], lines=trace.lines)
```

#### Traces.names

```python
def names(self) -> list
```

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
def requests_of(events: list) -> list
```

One dict per `*_ask` event, in trace order.

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
