# docpipe.inference.pool

`docpipe/inference/pool.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pool.py: The places the chat's model requests take, shared by everyone asking.

Several model names on one endpoint (LLM_MODELS) each take a few requests at
once (LLM_SLOTS_PER_MODEL). Everything one Streamlit process asks shares those
places: the documents of a comparison, the harvest beside the search, the
closed questions of a turn, and all of this for two users at the same time.

The queue is the harvest's (`docpipe/extraction/scheduler.py`): oldest turn
first, and a request sent ahead of knowing it is needed only ever takes a place
nobody else is waiting for. What is added here is which model a request goes
to: the one with the most free places that has not asked to wait. A request
asked again therefore lands on another model, and a 429 closes the gate of the
one model that sent it, not of the others.

With one place in all there is no pool: `over` hands back the plain client and
`together` runs its work one after the other, which is what the chat did
before.

A request is a leaf: the threads here wait for the queue, and nothing the queue
runs waits for anything but the model, so the threads cannot starve each other.

Author: Felix Vossel

## Classes

### Seats

```python
class Seats
```

How many requests may be open, and with which model.

The limit `Scheduler` reads. A model whose gate is closed does not count:
its places come back by themselves when the gate opens.

#### Seats.\_\_init\_\_

```python
def __init__(self, clients: dict, slots: int)
```

#### Seats.limit

```python
@property
def limit(self) -> int
```

#### Seats.acquire

```python
def acquire(self) -> None
```

#### Seats.release

```python
def release(self) -> None
```

#### Seats.take

```python
def take(self) -> str
```

The model this request goes to: the most free places among the
open ones, and of those the one that was asked longest ago.

#### Seats.give

```python
def give(self, name: str) -> None
```

### Pool

```python
class Pool
```

A client whose chat.completions.create goes through the queue, for the
turn and the ticket of the calling thread.

#### Pool.\_\_init\_\_

```python
def __init__(self, client, models, slots: int)
```

#### Pool.create

```python
def create(self, **kwargs)
```

## Functions

### wide

```python
def wide() -> bool
```

Whether there is more than one place to send a request to.

### over

```python
def over(client)
```

*client* behind the pool of this process, or *client* itself where
there is one place. The first caller's client serves the process.

### room

```python
def room() -> int
```

Places free that nothing is waiting for.

### turn

```python
@contextlib.contextmanager
def turn()
```

The requests inside belong to one turn: their place in the queue. A
turn inside a turn is the same one.

### together

```python
def together(thunks) -> list
```

What each of *thunks* returns, in their order, each run in its own
thread with a copy of this context. An exception of a thunk is raised
here. With one place they run one after the other.

### in_order

```python
def in_order(count: int, prepare: Callable, ask: Callable) -> Iterator
```

`ask(prepare(i))` for i in range(count), yielded in that order, the
later ones started ahead of being known to be needed.

`prepare(i)` runs here, in the caller's thread, when i is started: what it
reads is what the caller has taken in so far. `ask` runs in a thread of its
own. i is needed once everything before it was taken in; until then it
asks ahead and takes only places nobody waits for. As many are started as
there are such places, and no more than that. Leaving the loop withdraws
what has not been sent; what was sent comes back to nobody. Close the
iterator (`contextlib.closing`) so that this happens at once.

With one place nothing is started ahead.

[Back to the index](../README.md)
