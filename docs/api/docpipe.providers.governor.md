# docpipe.providers.governor

`docpipe/providers/governor.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

governor.py: One gate per endpoint, closed while the API says to wait.

A hosted API answers a request over its rate with 429 and, most of the time,
with the seconds to wait. Each request loop of a stage waited on its own, so
a hundred threads learned the same thing a hundred times and came back
together. The gate is shared by every request to one endpoint: the first
answer that says wait closes it for all of them, and each request passes it
before it is sent.

Without a number from the API the wait doubles from HOLD_START up to
HOLD_MAX with every round of refusals, and starts over with the first
request that is served. A round is what finds the gate open: the requests
that were already under way when it closed come back refused too, and they
say nothing new.

The gate decides when a request is sent. It retries nothing: the refused
request raises as it did, and the loop that sent it asks again.

Author: Felix Vossel

## Classes

### Gate

```python
class Gate
```

#### Gate.\_\_init\_\_

```python
def __init__(self, name: str = "", *, clock: Callable = time.monotonic,
             sleep: Callable = time.sleep)
```

#### Gate.listen

```python
def listen(self, callback: Callable) -> None
```

Call *callback()* whenever the API says to wait.

#### Gate.wait

```python
def wait(self) -> None
```

Return once the gate is open.

#### Gate.closed

```python
def closed(self) -> bool
```

#### Gate.limited

```python
def limited(self, retry_after: Optional[float] = None) -> float
```

The API said to wait; returns the seconds the gate stays closed.

#### Gate.served

```python
def served(self) -> None
```

### Governed

```python
class Governed
```

A client whose requests pass *gate* and tell it what they were told.

#### Governed.\_\_init\_\_

```python
def __init__(self, client, gate: Gate)
```

#### Governed.chat

```python
@property
def chat(self)
```

#### Governed.embeddings

```python
@property
def embeddings(self)
```

## Functions

### status_of

```python
def status_of(exc: BaseException) -> Optional[int]
```

The HTTP status behind a failed request, if it carries one.

### retry_after

```python
def retry_after(exc: BaseException) -> Optional[float]
```

The seconds a failed request was told to wait, if it was told.

### gate_for

```python
def gate_for(provider: str, base_url: Optional[str]) -> Gate
```

The one gate of an endpoint, shared by every client made for it.

[Back to the index](../README.md)
