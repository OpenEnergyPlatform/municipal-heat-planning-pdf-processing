"""
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
"""
from __future__ import annotations

import contextlib
import contextvars
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from types import SimpleNamespace
from typing import Callable, Iterator, Optional

from ..extraction import scheduler
from ..extraction.scheduler import Ticket, Withdrawn  # noqa: F401
from ..providers import governor
from . import config

# How often a batch under way looks whether a place came free for the next one.
LOOK_AHEAD_SECONDS = 0.05

_TURN: contextvars.ContextVar = contextvars.ContextVar("chat_turn",
                                                       default=None)
_TICKET: contextvars.ContextVar = contextvars.ContextVar("chat_ticket",
                                                         default=None)
_turns = itertools.count()


class Seats:
    """How many requests may be open, and with which model.

    The limit `Scheduler` reads. A model whose gate is closed does not count:
    its places come back by themselves when the gate opens.
    """

    def __init__(self, clients: dict, slots: int):
        self.clients = clients
        self.slots = slots
        self.maximum = len(clients) * slots
        self.in_flight = 0
        self._used = dict.fromkeys(clients, 0)
        self._last_used = dict.fromkeys(clients, 0)
        self._uses = itertools.count(1)
        self._lock = threading.Lock()

    def _open(self) -> list:
        return [name for name, client in self.clients.items()
                if not client.gate.closed()]

    @property
    def limit(self) -> int:
        return len(self._open()) * self.slots

    def acquire(self) -> None:
        with self._lock:
            self.in_flight += 1

    def release(self) -> None:
        with self._lock:
            self.in_flight -= 1

    def take(self) -> str:
        """The model this request goes to: the most free places among the
        open ones, and of those the one that was asked longest ago."""
        with self._lock:
            names = self._open() or list(self.clients)
            free = [n for n in names if self._used[n] < self.slots] or names
            name = min(free, key=lambda n: (self._used[n], self._last_used[n]))
            self._used[name] += 1
            self._last_used[name] = next(self._uses)
            return name

    def give(self, name: str) -> None:
        with self._lock:
            self._used[name] -= 1


class Pool:
    """A client whose chat.completions.create goes through the queue, for the
    turn and the ticket of the calling thread."""

    def __init__(self, client, models, slots: int):
        self.seats = Seats({name: governor.Governed(client, governor.Gate(name))
                            for name in models}, slots)
        self.queue = scheduler.Scheduler(self.seats)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create))

    def _send(self, kwargs: dict):
        name = self.seats.take()
        try:
            return self.seats.clients[name].chat.completions.create(
                **{**kwargs, "model": name})
        finally:
            self.seats.give(name)

    def create(self, **kwargs):
        ticket = _TICKET.get()
        if ticket is not None and ticket.withdrawn:
            raise Withdrawn()
        return self.queue.submit(lambda: self._send(kwargs), _TURN.get(),
                                 ticket).result()


_pool: Optional[Pool] = None
_pool_lock = threading.Lock()


def wide() -> bool:
    """Whether there is more than one place to send a request to."""
    return len(config.LLM_MODELS) * config.LLM_SLOTS_PER_MODEL > 1


def over(client):
    """*client* behind the pool of this process, or *client* itself where
    there is one place. The first caller's client serves the process."""
    global _pool
    if not wide():
        return client
    with _pool_lock:
        if _pool is None:
            _pool = Pool(client, config.LLM_MODELS, config.LLM_SLOTS_PER_MODEL)
        return _pool


def room() -> int:
    """Places free that nothing is waiting for."""
    return _pool.queue.room() if _pool is not None else 0


@contextlib.contextmanager
def turn():
    """The requests inside belong to one turn: their place in the queue. A
    turn inside a turn is the same one."""
    if _TURN.get() is not None:
        yield
        return
    key = next(_turns)
    token = _TURN.set(key)
    try:
        yield
    finally:
        _TURN.reset(token)
        if _pool is not None:
            _pool.queue.forget(key)


def together(thunks) -> list:
    """What each of *thunks* returns, in their order, each run in its own
    thread with a copy of this context. An exception of a thunk is raised
    here. With one place they run one after the other."""
    thunks = list(thunks)
    if len(thunks) < 2 or not wide():
        return [thunk() for thunk in thunks]
    with ThreadPoolExecutor(len(thunks), thread_name_prefix="chat") as threads:
        futures = [threads.submit(contextvars.copy_context().run, thunk)
                   for thunk in thunks]
    return [future.result() for future in futures]


def in_order(count: int, prepare: Callable, ask: Callable) -> Iterator:
    """`ask(prepare(i))` for i in range(count), yielded in that order, the
    later ones started ahead of being known to be needed.

    `prepare(i)` runs here, in the caller's thread, when i is started: what it
    reads is what the caller has taken in so far. `ask` runs in a thread of its
    own. i is needed once everything before it was taken in; until then it
    asks ahead and takes only places nobody waits for. As many are started as
    there are such places, and no more than that. Leaving the loop withdraws
    what has not been sent; what was sent comes back to nobody. Close the
    iterator (`contextlib.closing`) so that this happens at once.

    With one place nothing is started ahead.
    """
    if not wide():
        for i in range(count):
            yield ask(prepare(i))
        return

    threads = ThreadPoolExecutor(max(count, 1), thread_name_prefix="chat")
    tickets: dict = {}
    futures: dict = {}

    def start(i: int, ahead: bool) -> None:
        ticket = tickets[i] = Ticket(ahead=ahead)
        job = prepare(i)

        def run():
            _TICKET.set(ticket)
            return ask(job)

        futures[i] = threads.submit(contextvars.copy_context().run, run)

    try:
        for i in range(count):
            if i not in futures:
                start(i, False)
            elif tickets[i].ahead and _pool is not None:
                _pool.queue.promote(tickets[i])
            while not wait([futures[i]], LOOK_AHEAD_SECONDS).done:
                # One per look: what was just started has not taken its
                # place yet, and `room` would count that place again.
                if len(futures) < count and room() > 0:
                    start(len(futures), True)
            yield futures[i].result()
    finally:
        for ticket in tickets.values():
            ticket.withdraw()
        threads.shutdown(wait=False, cancel_futures=True)
