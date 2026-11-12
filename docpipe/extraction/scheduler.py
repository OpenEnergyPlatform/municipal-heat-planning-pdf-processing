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

A step that has a value of its own for the rule `parallel` has a lane of its
own: its requests wait in a queue of their own and are sent while fewer than
that many of them are open, whatever the limit above says, up or down from
it. The other steps keep sharing the limit (`Lane`).

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
"""
from __future__ import annotations

import contextvars
import copy
import functools
import hashlib
import heapq
import itertools
import json
import threading
import time
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import Callable, Optional

from docpipe import providers, rules

from . import trace


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


class Lane:
    """The requests of one step that has its own value of the rule
    `parallel`: how many may be open at once, and how many are."""

    def __init__(self, key: str, limit: int):
        self.key = key
        self.limit = limit
        self.open = 0
        self.heap: list = []
        self.pool: Optional[ThreadPoolExecutor] = None
        self.workers = 0

    def sender(self) -> ThreadPoolExecutor:
        """The threads that send this lane's requests, as many as the lane
        has places, so that no other lane or the shared limit starves it."""
        if self.pool is None or self.workers < self.limit:
            self.workers = max(1, self.limit)
            self.pool = ThreadPoolExecutor(
                max_workers=self.workers,
                thread_name_prefix=f"llm-lane-{self.key}"[:40])
        return self.pool


def lane_of() -> Optional[tuple]:
    """(key, limit) of the lane the calling step sends its requests in, None
    where it shares the limit: the rule `parallel` of the step that runs, 0
    for the shared one. The key names whose value it is (the step or the
    frame that set it), so that the requests of every step a frame covers
    are one lane."""
    limit = int(rules.get("parallel"))
    if limit < 1:
        return None
    step = rules.STEP.get()
    key = (step.owners.get("parallel") if step is not None else None) or "run"
    return key, limit


class Scheduler:
    """Requests in, sent in the order of their document, as the limit allows.

    *limit* is an `AdaptiveLimit`. A request without a document (anchors,
    the search sentence a run shares, the frame's warm-up) goes before every
    document: everything waits on it. A request of a step with a lane of its
    own (`lane_of`) is not counted by the limit.
    """

    def __init__(self, limit, workers: Optional[int] = None):
        self.limit = limit
        self._lanes: dict = {}
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
        """The document's place by the rule `queue_order`: the order it first
        asked in, the reverse of it, or none at all. A request of no
        document goes before every document in any order."""
        if document is None:
            return -(1 << 60)
        with self._cond:
            if document not in self._rank:
                self._rank[document] = next(self._ranks)
            place = self._rank[document]
        order = rules.get("queue_order")
        return (place if order == "oldest_document"
                else -place if order == "newest_document" else 0)

    def forget(self, document: Optional[int]) -> None:
        """A document written out leaves the ranking."""
        with self._cond:
            self._rank.pop(document, None)

    @property
    def waiting(self) -> int:
        with self._cond:
            return len(self._heap) + sum(len(lane.heap)
                                         for lane in self._lanes.values())

    def room(self) -> int:
        """Places the limit has that no request holds or waits for."""
        with self._cond:
            return self.limit.limit - self.limit.in_flight - len(self._heap)

    def submit(self, send: Callable, document: Optional[int] = None,
               ticket: Optional[Ticket] = None,
               lane: Optional[tuple] = None) -> Future:
        """*send* for *document*, in the lane (key, limit) a step with its
        own `parallel` sends in (`lane_of`), else with the shared limit."""
        # Sent in the context of the caller, so that what the sending reads
        # is what the step that asks reads (`rules.STEP`).
        send = functools.partial(contextvars.copy_context().run, send)
        future: Future = Future()
        ahead = int(ticket is not None and ticket.ahead)
        entry = (ahead, self.rank(document), next(self._seq), send, future,
                 ticket)
        with self._cond:
            if self._broken is not None:
                future.set_exception(self._broken)
                return future
            if lane is None:
                heapq.heappush(self._heap, entry)
            else:
                held = self._lanes.get(lane[0])
                if held is None:
                    held = self._lanes[lane[0]] = Lane(*lane)
                held.limit = lane[1]
                heapq.heappush(held.heap, entry)
            self._cond.notify_all()
        return future

    def promote(self, ticket: Ticket) -> None:
        """The requests of *ticket* are needed now: they stop waiting behind
        the others, and so do the ones it sends from here on."""
        ticket.ahead = False
        with self._cond:
            for held in (self._heap, *(lane.heap
                                       for lane in self._lanes.values())):
                held[:] = [(0, *entry[1:]) if entry[-1] is ticket else entry
                           for entry in held]
                heapq.heapify(held)
            self._cond.notify_all()

    def _take(self) -> Optional[tuple]:
        """(entry, the lane it goes in or None) of the next request that has
        a place, None where none has. Called with the lock held. A lane has a
        place while fewer of its requests are open than it allows; the shared
        queue has one while the limit has room."""
        for lane in self._lanes.values():
            if lane.heap and lane.open < lane.limit:
                return heapq.heappop(lane.heap), lane
        if self._heap and self.limit.in_flight < self.limit.limit:
            return heapq.heappop(self._heap), None
        return None

    def _dispatch(self) -> None:
        try:
            while True:
                with self._cond:
                    while True:
                        taken = self._take()
                        if taken is not None:
                            break
                        self._cond.wait(timeout=1.0)
                *_order, send, future, ticket = taken[0]
                lane = taken[1]
                if ticket is not None and ticket.withdrawn:
                    future.set_exception(Withdrawn())
                    continue
                if not future.set_running_or_notify_cancel():
                    continue
                if lane is None:
                    self.limit.acquire()
                else:
                    with self._cond:
                        lane.open += 1
                try:
                    (self._pool if lane is None else lane.sender()).submit(
                        self._send, send, future, lane)
                except BaseException as exc:
                    self._release(lane)
                    future.set_exception(exc)
                    raise
        except BaseException as exc:     # the dispatcher sends no more
            self._close(exc)

    def _release(self, lane: Optional[Lane]) -> None:
        if lane is None:
            self.limit.release()
        else:
            with self._cond:
                lane.open -= 1

    def _close(self, exc: BaseException) -> None:
        """Every waiting request, and every later one, ends with *exc*. A
        caller waits on its future without a limit, and a dispatcher that
        died without answering them held a crashed probe open until its time
        limit, two hours of a node doing nothing."""
        with self._cond:
            self._broken = exc
            waiting, self._heap = self._heap, []
            for lane in self._lanes.values():
                waiting += lane.heap
                lane.heap = []
        for *_order, _send, future, _ticket in waiting:
            if not future.done():
                future.set_exception(exc)

    def _send(self, send: Callable, future: Future,
              lane: Optional[Lane] = None) -> None:
        try:
            # When the request leaves the queue for the server, for its trace
            # (`Scheduled.create`, owner decision 2026-11-07).
            future.sent = time.time()
            future.set_result(send())
        except BaseException as exc:            # handed to the caller
            future.set_exception(exc)
        finally:
            self._release(lane)
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
        future = self._scheduler.submit(
            lambda: self._client.chat.completions.create(*args, **kwargs),
            document, ticket, lane_of())
        try:
            return future.result()
        finally:
            # When it left the queue, for the trace of the request (`Repeats`).
            _local.sent = getattr(future, "sent", None)


# Every memo of the run (`Once`), so a document that is done is forgotten in
# each (`read_out`).
_memos: "weakref.WeakSet" = weakref.WeakSet()
_memos_lock = threading.Lock()


def read_out(document) -> None:
    """*document* is done: every memo forgets the answers to its requests, so
    a run keeps them only for the documents it is reading."""
    with _memos_lock:
        memos = list(_memos)
    for memo in memos:
        memo.forget(document)


def request_key(request: dict) -> Optional[str]:
    """What a request asks, as one key: everything it sends but the time it
    may take, which a repeat after a timeout changes (`Repeats`). None where
    it cannot be written as JSON."""
    try:
        text = json.dumps({key: value for key, value in request.items()
                           if key != "timeout"}, sort_keys=True,
                          ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def answered_again(response):
    """*response* as the answer to its twin: the same reply, and no usage,
    since nothing was sent and nothing spent."""
    copier = getattr(response, "model_copy", None)
    if callable(copier):
        return copier(update={"usage": None})
    clone = copy.copy(response)
    try:
        clone.usage = None
    except AttributeError:
        pass
    return clone


class Once:
    """The answers of a document's requests, by what each sent
    (`request_key`), owner decision 2026-11-07: a request sent word for word
    a second time in the same document gets the first one's answer and is
    not sent; one sent while its twin is still out waits for that answer. A
    request that ended without an answer is forgotten, so its next twin is
    sent. A request of no document is sent every time (`Repeats`). A
    document's answers are kept while it is read and go when it is done
    (`read_out`)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._held: dict = {}
        with _memos_lock:
            _memos.add(self)

    def claim(self, document, key: str) -> tuple:
        """(the future that holds or will hold the answer to *key* in
        *document*, whether the caller is the first to ask it and so sends
        it and settles the future)."""
        with self._lock:
            held = self._held.setdefault(document, {})
            twin = held.get(key)
            if twin is not None:
                return twin, False
            mine = held[key] = Future()
            return mine, True

    def forget(self, document) -> None:
        """*document* is done: the answers to its requests go."""
        with self._lock:
            self._held.pop(document, None)

    @staticmethod
    def answered(held: Future, response) -> None:
        if not held.done():
            held.set_result(response)

    def failed(self, document, key: str, held: Future,
               error: BaseException) -> None:
        """The first asking ended without an answer: its twins waiting are
        told, and the next one is sent."""
        with self._lock:
            kept = self._held.get(document)
            if kept is not None and kept.get(key) is held:
                del kept[key]
        if not held.done():
            held.set_exception(error)

    @staticmethod
    def wait(held: Future):
        """The twin's answer as this request's (`answered_again`), or None
        where the twin ended without one."""
        try:
            return answered_again(held.result())
        except BaseException:           # the waiting request is sent itself
            return None


class Repeats:
    """A client whose repeat of a request that timed out gets *repeat*
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
    """

    def __init__(self, client, repeat: Optional[float] = None,
                 usual: Optional[float] = None):
        self._client = client
        # None: the rules `repeat_timeout_s` and `llm_timeout_s` of the step
        # that sends the request, read when it is sent.
        self._repeat = repeat
        self._usual = usual
        self._local = threading.local()
        self._once = Once()
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create))

    def create(self, *args, **kwargs):
        messages = kwargs.get("messages")
        # A step with a time of its own for the first attempt sends it with
        # the request; the others keep the one the client was made with.
        own, waits = rules.stepped_value("llm_timeout_s")
        if own and kwargs.get("timeout") is None:
            kwargs["timeout"] = waits
        if messages is not None and messages == getattr(self._local,
                                                        "timed_out", None):
            usual = (self._usual if self._usual is not None
                     else rules.get("llm_timeout_s"))
            repeat = (self._repeat if self._repeat is not None
                      else rules.get("repeat_timeout_s"))
            kwargs["timeout"] = max(kwargs.get("timeout") or usual, repeat)
        self._local.timed_out = None
        asked = time.time()
        here = current()
        document = here[0]
        # Word for word in the same document: a request of no document
        # (anchors, a run's own questions) is sent every time, and every
        # request is where the rule `same_request_once` is off.
        key = (request_key(kwargs) if document is not None and not args
               and rules.get("same_request_once") else None)
        held, first = (self._once.claim(document, key) if key is not None
                       else (None, False))
        if held is not None and not first:
            answer = self._once.wait(held)
            if answer is not None:
                trace.exchanged(kwargs, answer,
                                times=(asked, None, time.time()), once=True)
                return answer
        _local.sent = None
        try:
            response = self._client.chat.completions.create(*args, **kwargs)
        except BaseException as exc:
            if first:
                self._once.failed(document, key, held, exc)
            if isinstance(exc, Exception):
                # What was sent and how it ended, for the trace event that
                # reports the request (owner decision 2026-11-05).
                trace.exchanged(kwargs, error=exc, times=(
                    asked, getattr(_local, "sent", None), time.time()))
                if messages is not None and providers.timed_out(exc):
                    self._local.timed_out = list(messages)
            raise
        if first:
            self._once.answered(held, response)
        trace.exchanged(kwargs, response, times=(
            asked, getattr(_local, "sent", None), time.time()))
        return response


def repeating(client, repeat: Optional[float] = None,
              usual: Optional[float] = None):
    """*client* as `Repeats`, once."""
    if isinstance(client, Repeats):
        return client
    return Repeats(client, repeat, usual)
