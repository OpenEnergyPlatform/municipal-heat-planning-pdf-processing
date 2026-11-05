"""
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

Author: Felix Vossel
"""
from __future__ import annotations

import heapq
import itertools
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import Callable, Optional

from docpipe import providers


class Withdrawn(Exception):
    """The request was withdrawn before it was sent."""


class Ticket:
    """What a sweep withdraws the requests it no longer needs with."""

    def __init__(self, ahead: bool = False):
        self._withdrawn = threading.Event()
        self.ahead = ahead

    def withdraw(self) -> None:
        self._withdrawn.set()

    @property
    def withdrawn(self) -> bool:
        return self._withdrawn.is_set()


_local = threading.local()


class on_behalf:
    """`with on_behalf(document_id, ticket):` -- the requests sent inside
    belong to this document (their place in the queue) and to this ticket."""

    def __init__(self, document: Optional[int], ticket: Optional[Ticket] = None):
        self.document = document
        self.ticket = ticket

    def __enter__(self):
        self._before = (getattr(_local, "document", None),
                        getattr(_local, "ticket", None))
        _local.document, _local.ticket = self.document, self.ticket
        return self

    def __exit__(self, *exc) -> None:
        _local.document, _local.ticket = self._before


def current() -> tuple:
    """(document, ticket) the calling thread is sending for."""
    return (getattr(_local, "document", None),
            getattr(_local, "ticket", None))


class Scheduler:
    """Requests in, sent in the order of their document, as the limit allows.

    *limit* is an `AdaptiveLimit`. A request without a document (anchors,
    the frame's warm-up) goes before every document: everything waits on it.
    """

    def __init__(self, limit, workers: Optional[int] = None):
        self.limit = limit
        self._heap: list = []
        self._seq = itertools.count()
        self._rank: dict = {}
        self._ranks = itertools.count()
        self._cond = threading.Condition()
        # Why the dispatcher stopped, once it has: every request ends with it.
        self._broken: Optional[BaseException] = None
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, workers or limit.maximum),
            thread_name_prefix="llm-send")
        threading.Thread(target=self._dispatch, name="llm-scheduler",
                         daemon=True).start()

    def rank(self, document: Optional[int]) -> int:
        """The document's place: the order it first asked in."""
        if document is None:
            return -1
        with self._cond:
            if document not in self._rank:
                self._rank[document] = next(self._ranks)
            return self._rank[document]

    def forget(self, document: Optional[int]) -> None:
        """A document written out leaves the ranking."""
        with self._cond:
            self._rank.pop(document, None)

    @property
    def waiting(self) -> int:
        with self._cond:
            return len(self._heap)

    def room(self) -> int:
        """Places the limit has that no request holds or waits for."""
        with self._cond:
            return self.limit.limit - self.limit.in_flight - len(self._heap)

    def submit(self, send: Callable, document: Optional[int] = None,
               ticket: Optional[Ticket] = None) -> Future:
        future: Future = Future()
        ahead = int(ticket is not None and ticket.ahead)
        entry = (ahead, self.rank(document), next(self._seq), send, future,
                 ticket)
        with self._cond:
            if self._broken is not None:
                future.set_exception(self._broken)
                return future
            heapq.heappush(self._heap, entry)
            self._cond.notify_all()
        return future

    def promote(self, ticket: Ticket) -> None:
        """The requests of *ticket* are needed now: they stop waiting behind
        the others, and so do the ones it sends from here on."""
        ticket.ahead = False
        with self._cond:
            self._heap = [(0, *entry[1:]) if entry[-1] is ticket else entry
                          for entry in self._heap]
            heapq.heapify(self._heap)
            self._cond.notify_all()

    def _dispatch(self) -> None:
        try:
            while True:
                with self._cond:
                    while not self._heap or (self.limit.in_flight
                                             >= self.limit.limit):
                        self._cond.wait(timeout=1.0)
                    *_order, send, future, ticket = heapq.heappop(self._heap)
                if ticket is not None and ticket.withdrawn:
                    future.set_exception(Withdrawn())
                    continue
                if not future.set_running_or_notify_cancel():
                    continue
                self.limit.acquire()
                try:
                    self._pool.submit(self._send, send, future)
                except BaseException as exc:
                    self.limit.release()
                    future.set_exception(exc)
                    raise
        except BaseException as exc:     # the dispatcher sends no more
            self._close(exc)

    def _close(self, exc: BaseException) -> None:
        """Every waiting request, and every later one, ends with *exc*. A
        caller waits on its future without a limit, and a dispatcher that
        died without answering them held a crashed probe open until its time
        limit, two hours of a node doing nothing."""
        with self._cond:
            self._broken = exc
            waiting, self._heap = self._heap, []
        for *_order, _send, future, _ticket in waiting:
            if not future.done():
                future.set_exception(exc)

    def _send(self, send: Callable, future: Future) -> None:
        try:
            future.set_result(send())
        except BaseException as exc:            # handed to the caller
            future.set_exception(exc)
        finally:
            self.limit.release()
            with self._cond:
                self._cond.notify_all()


class Scheduled:
    """A client whose chat.completions.create goes through *scheduler*, for
    the document and ticket of the calling thread (`on_behalf`)."""

    def __init__(self, client, scheduler: Scheduler):
        self._client = client
        self._scheduler = scheduler
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create))

    def create(self, *args, **kwargs):
        document, ticket = current()
        if ticket is not None and ticket.withdrawn:
            raise Withdrawn()
        return self._scheduler.submit(
            lambda: self._client.chat.completions.create(*args, **kwargs),
            document, ticket).result()


class Repeats:
    """A client whose repeat of a request that timed out gets *repeat*
    seconds, or more where the request's own time is longer.

    A repeat is the calling thread's next request with the same messages:
    every retry loop asks again unchanged after a failure, and with one more
    message (what was wrong) after a reply. The rule stands here and not in
    each loop: three of the nine loops kept it, and the eight-plan probe lost
    the replies that take longer, asked three times in the same 180 s.
    """

    def __init__(self, client, repeat: float, usual: float):
        self._client = client
        self._repeat = repeat
        self._usual = usual
        self._local = threading.local()
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create))

    def create(self, *args, **kwargs):
        messages = kwargs.get("messages")
        if messages is not None and messages == getattr(self._local,
                                                        "timed_out", None):
            kwargs["timeout"] = max(kwargs.get("timeout") or self._usual,
                                    self._repeat)
        self._local.timed_out = None
        try:
            return self._client.chat.completions.create(*args, **kwargs)
        except Exception as exc:
            if messages is not None and providers.timed_out(exc):
                self._local.timed_out = list(messages)
            raise


def repeating(client, repeat: float, usual: float):
    """*client* as `Repeats`, once."""
    if isinstance(client, Repeats):
        return client
    return Repeats(client, repeat, usual)


def serve_for(document: Optional[int]) -> None:
    """The requests this thread sends from now on belong to *document*, until
    it is told another; its ticket stays."""
    _local.document = document
