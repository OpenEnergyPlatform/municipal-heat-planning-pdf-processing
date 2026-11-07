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
are not sent. A withdrawn request raises `Withdrawn` in its caller. A request
sent ahead of knowing it is needed (`Ticket(ahead=True)`) waits behind every
other one until its ticket is promoted.

A request sent word for word a second time in the same document is not sent
again: it gets the first one's answer, and one sent while its twin is still
out waits for that answer (`Once`, owner decision 2026-11-07). A document's
answers are kept while it is read and go when it is done (`read_out`). Every
request is traced with when it was asked, when it left this queue for the
server and when its answer came (`trace.exchanged`).

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
def __init__(self, ahead: bool = False)
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
the search sentence a run shares, the frame's warm-up) goes before every
document: everything waits on it.

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

#### Scheduler.promote

```python
def promote(self, ticket: Ticket) -> None
```

The requests of *ticket* are needed now: they stop waiting behind
the others, and so do the ones it sends from here on.

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

### Once

```python
class Once
```

The answers of a document's requests, by what each sent
(`request_key`), owner decision 2026-11-07: a request sent word for word
a second time in the same document gets the first one's answer and is
not sent; one sent while its twin is still out waits for that answer. A
request that ended without an answer is forgotten, so its next twin is
sent. A request of no document is sent every time (`Repeats`). A
document's answers are kept while it is read and go when it is done
(`read_out`).

#### Once.\_\_init\_\_

```python
def __init__(self)
```

#### Once.claim

```python
def claim(self, document, key: str) -> tuple
```

(the future that holds or will hold the answer to *key* in
*document*, whether the caller is the first to ask it and so sends
it and settles the future).

#### Once.forget

```python
def forget(self, document) -> None
```

*document* is done: the answers to its requests go.

#### Once.answered

```python
@staticmethod
def answered(held: Future, response) -> None
```

#### Once.failed

```python
def failed(self, document, key: str, held: Future,
           error: BaseException) -> None
```

The first asking ended without an answer: its twins waiting are
told, and the next one is sent.

#### Once.wait

```python
@staticmethod
def wait(held: Future)
```

The twin's answer as this request's (`answered_again`), or None
where the twin ended without one.

### Repeats

```python
class Repeats
```

A client whose repeat of a request that timed out gets *repeat*
seconds, or more where the request's own time is longer.

A repeat is the calling thread's next request with the same messages:
every retry loop asks again unchanged after a failure, and with one more
message (what was wrong) after a reply. The rule stands here and not in
each loop: three of the nine loops kept it, and the eight-plan probe lost
the replies that take longer, asked three times in the same 180 s.

Every request of the stage passes here, so here it is also taken for the
trace: what was sent and what came back (`trace.exchanged`), for the
event that reports it, with when it was asked, sent and answered. And
here a request sent word for word a second time in the same document is
answered with the first one's answer (`Once`, owner decision
2026-11-07).

#### Repeats.\_\_init\_\_

```python
def __init__(self, client, repeat: float, usual: float)
```

#### Repeats.create

```python
def create(self, *args, **kwargs)
```

## Functions

### current

```python
def current() -> tuple
```

(document, ticket) the calling thread is sending for.

### read_out

```python
def read_out(document) -> None
```

*document* is done: every memo forgets the answers to its requests, so
a run keeps them only for the documents it is reading.

### request_key

```python
def request_key(request: dict) -> Optional[str]
```

What a request asks, as one key: everything it sends but the time it
may take, which a repeat after a timeout changes (`Repeats`). None where
it cannot be written as JSON.

### answered_again

```python
def answered_again(response)
```

*response* as the answer to its twin: the same reply, and no usage,
since nothing was sent and nothing spent.

### repeating

```python
def repeating(client, repeat: float, usual: float)
```

*client* as `Repeats`, once.

[Back to the index](../README.md)
