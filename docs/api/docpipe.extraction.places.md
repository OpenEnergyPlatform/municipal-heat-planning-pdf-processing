# docpipe.extraction.places

`docpipe/extraction/places.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

places.py: Where a document says something to each axis, read once per
document before its coordinates are searched.

The search for a coordinate the value's own passage does not answer used to
read the whole plan for it, window after window: the embedding ranking first,
then every remaining passage in order. Most passages say nothing to most
axes, and the rest stage of one AR6 document took two hours for nineteen
coordinates.

Here the model reads every passage of the document once, side by side, and
names for each one the parameters whose numbers stand in it and the axes it
answers, with a verbatim quote. It reads no value. The search then shows a
coordinate only the places of its axis, nearest to the row first. A place
whose quote does not stand in its passage, or is too short to name a place,
is not taken: the two halves of the one check every reading passes, minus the
answer, because there is none.

A map is complete when every window of the document came back readable. Only
a complete map stands for the document (owner decision 2026-10-22: an axis
still open after all its places is unstated, the map having read the whole
plan). An incomplete one is not used, and the search reads as before.

The map is kept per document (`places/<document>.json`) under a key over the
prompt, the questions and the model, so a pass over a stored harvest reads it
again instead of asking for it again.

Author: Felix Vossel

## Classes

### Map

```python
@dataclass
class Map
```

The places of one document: which passages answer which axis.

Fields:

- `complete: bool`
- `by_axis: dict = field(default_factory=dict)`: axis -> {(kind, id)}
- `by_parameter: dict = field(default_factory=dict)`

#### Map.keys_of

```python
def keys_of(self, axes) -> Optional[set]
```

The passages that answer any of *axes*, or None when the map does
not stand for the document or does not know one of them.

### Places

```python
class Places
```

(document_id, axes) -> the passages that answer them, or None.

*ask(window, document_id)* is one request: the reply as a dict, CUT, or
None when it could not be read. *passages_of(document_id)* is every
passage of the document in its order. *pool* runs a document's
requests side by side (None: one after another). *store* is where maps
are kept.

#### Places.\_\_init\_\_

```python
def __init__(self, ask: Callable, passages_of: Callable, fits: Callable,
             axes: dict, parameters: dict, key: str, *,
             store: Optional[Path] = None, pool=None, trace=None)
```

#### Places.map_for

```python
def map_for(self, document_id: int) -> Map
```

## Functions

### questions

```python
def questions(spec) -> tuple
```

({axis: question}, {parameter: label}) the map is asked with: every
axis the spec asks with a question, the first wording of each.

### key_of

```python
def key_of(prompt_text: str, axes: dict, parameters: dict,
           model: str) -> str
```

### payload

```python
def payload(window: list, axes: dict, parameters: dict) -> dict
```

### response_format

```python
def response_format(window: list, axes: dict, parameters: dict) -> dict
```

The reply as a server grammar: a list of places, each one passage of
the window, parameters and axes from their lists, and a quote.

### read_hits

```python
def read_hits(reply: dict, window: list, axes: dict,
              parameters: dict) -> tuple
```

([(source, axes, parameters, quote)], places not taken) of one reply.

A place is taken when its quote stands in its own passage and is long
enough to name a place there. Nothing else is checked.

### windows_of

```python
def windows_of(sources: list, fits: Callable) -> list
```

The passages in document order, as many to a request as *fits*
allows. A passage that does not fit alone goes alone, and its request
says so (`ask` returns CUT when the prompt leaves no room).

### nearest_first

```python
def nearest_first(pool: list, rows_at: list) -> list
```

*pool* ordered by its distance to the rows' own sections, the
document's order among equals. *rows_at* are section numbers.

[Back to the index](../README.md)
