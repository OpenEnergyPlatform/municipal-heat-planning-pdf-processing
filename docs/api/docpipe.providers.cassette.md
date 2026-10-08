# docpipe.providers.cassette

`docpipe/providers/cassette.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

cassette.py: The answers of a run, kept, so the run can be made again
without a model.

A change to the code moves what the harvest finds, and whether it moved
for the better is only seen on documents. With a model that costs a GPU and
an afternoon. A cassette is the answers of one run, each filed under what
was asked. Replayed, every request that is asked again in the same words
gets the answer it got, and the run ends where the code now takes it, on a
machine that has no model: which is what a test server is.

That holds the model still and shows the code: how an answer is read, what
is accepted, how rows are settled. It does not show a new prompt or a new
spec. Those ask in other words, and for other words there is no answer
here.

    DOCPIPE_CASSETTE_RECORD=file    a run with a model writes its answers
    DOCPIPE_CASSETTE_REPLAY=file    a run takes its answers from the file

A request is filed under its messages and the reply format it names. Not
under the model, the temperature or the room for the answer: those are the
installation's, and a replay has none. An image is filed under its pixels,
so the same picture encoded again is the same request, and under its bytes
only where it cannot be decoded. A request the file does not hold is not
answered and counted,
and it stops the stage like a server that is gone: a replay that asks
something new is the finding, not a fault to work around.

A cassette holds the text of the documents the run read. So recording is
refused for a profile that does not say its documents may be passed on
(`Profile(documents_shareable=True)`).

Author: Felix Vossel

## Classes

### CassetteMiss

```python
class CassetteMiss(LookupError)
```

A request the cassette holds no answer for.

### Recorder

```python
class Recorder
```

A client whose answers are also written to a file.

#### Recorder.\_\_init\_\_

```python
def __init__(self, client, path)
```

#### Recorder.chat

```python
@property
def chat(self)
```

#### Recorder.embeddings

```python
@property
def embeddings(self)
```

### Player

```python
class Player
```

A client that answers from a file and from nothing else.

#### Player.\_\_init\_\_

```python
def __init__(self, path)
```

#### Player.chat

```python
@property
def chat(self)
```

#### Player.embeddings

```python
@property
def embeddings(self)
```

#### Player.vector

```python
def vector(self, text: str) -> list
```

#### Player.window

```python
def window(self, model: Optional[str] = None) -> Optional[int]
```

The context size the recorded run was planned for.

#### Player.models

```python
@property
def models(self)
```

### ReplayEmbedder

```python
class ReplayEmbedder
```

The embedder of a replay. A run that searched with a model on its
own machine left its query vectors in the query cache, which goes with
the cassette; one that embedded through an API left them in the
cassette. What neither holds is not embedded: there is no model.

#### ReplayEmbedder.embed

```python
def embed(self, items) -> list
```

#### ReplayEmbedder.embed_one

```python
def embed_one(self, item: dict) -> list
```

## Functions

### recording

```python
def recording() -> Optional[str]
```

### replaying

```python
def replaying() -> Optional[str]
```

### chat_key

```python
def chat_key(kwargs: dict) -> str
```

What a chat request is filed under.

### embedding_key

```python
def embedding_key(text: str) -> str
```

What the vector of one text is filed under: the text, not the batch
it happened to travel in.

### note_limits

```python
def note_limits(model: str, max_model_len: Optional[int]) -> None
```

Write down what the server of a recorded run offered. A replay plans
its requests for that window, or it would ask other ones.

### player

```python
def player(path: Optional[str] = None) -> Player
```

The one player of a file: every stage of a run reads the same one,
so an answer that was given is not given twice.

[Back to the index](../README.md)
