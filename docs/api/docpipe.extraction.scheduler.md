# docpipe.extraction.scheduler

`docpipe/extraction/scheduler.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

scheduler.py: One queue for every model request of a run, served oldest
document first.

The adaptive limit (throttle.py) says how many requests may be open. Before
this, every caller waited for a place on its own, in no order: a document
that had read all but one coordinate waited behind the first requests of the
newest one, and the last document of a run asked one window at a time while
the server stood almost idle.

Here the callers hand their request to one dispatcher thread and wait for
its future. The dispatcher sends the waiting request of the document that
came first whenever the limit has room. The request's own timeout starts when
it is sent, not while it waits: waiting is the harvest's queue, not the
server's slowness.

A request may be withdrawn while it waits (`Ticket.withdraw`): the sweep
that asked several windows ahead has its answer, and the windows behind it
are not sent. A withdrawn request raises `Withdrawn` in its caller.

Author: Felix Vossel

## Classes

### Withdrawn

```python
class Withdrawn(Exception)
```

The request was withdrawn before it was sent.

### Ticket

```python
class Ticket
```

What a sweep withdraws the requests it no longer needs with.

#### Ticket.\_\_init\_\_

```python
def __init__(self)
```

#### Ticket.withdraw

```python
def withdraw(self) -> None
```

#### Ticket.withdrawn

```python
@property
def withdrawn(self) -> bool
```

### on_behalf

```python
class on_behalf
```

`with on_behalf(document_id, ticket):` -- the requests sent inside
belong to this document (their place in the queue) and to this ticket.

#### on_behalf.\_\_init\_\_

```python
def __init__(self, document: Optional[int], ticket: Optional[Ticket] = None)
```

### Scheduler

```python
class Scheduler
```

Requests in, sent in the order of their document, as the limit allows.

*limit* is an `AdaptiveLimit`. A request without a document (anchors,
the frame's warm-up) goes before every document: everything waits on it.

#### Scheduler.\_\_init\_\_

```python
def __init__(self, limit, workers: Optional[int] = None)
```

#### Scheduler.rank

```python
def rank(self, document: Optional[int]) -> int
```

The document's place: the order it first asked in.

#### Scheduler.forget

```python
def forget(self, document: Optional[int]) -> None
```

A document written out leaves the ranking.

#### Scheduler.waiting

```python
@property
def waiting(self) -> int
```

#### Scheduler.room

```python
def room(self) -> int
```

Places the limit has that no request holds or waits for.

#### Scheduler.submit

```python
def submit(self, send: Callable, document: Optional[int] = None,
           ticket: Optional[Ticket] = None) -> Future
```

### Scheduled

```python
class Scheduled
```

A client whose chat.completions.create goes through *scheduler*, for
the document and ticket of the calling thread (`on_behalf`).

#### Scheduled.\_\_init\_\_

```python
def __init__(self, client, scheduler: Scheduler)
```

#### Scheduled.create

```python
def create(self, *args, **kwargs)
```

## Functions

### current

```python
def current() -> tuple
```

(document, ticket) the calling thread is sending for.

### serve_for

```python
def serve_for(document: Optional[int]) -> None
```

The requests this thread sends from now on belong to *document*, until
it is told another; its ticket stays.

[Back to the index](../README.md)
