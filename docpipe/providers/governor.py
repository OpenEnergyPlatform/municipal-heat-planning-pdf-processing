"""
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
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# The statuses that mean "not now" rather than "not like this".
LIMITED = (429, 503, 529)
HOLD_START = 2.0
HOLD_MAX = 120.0
# Doublings counted; more of them would not lengthen a wait HOLD_MAX bounds.
STREAK_MAX = 16


class Gate:
    def __init__(self, name: str = "", *, clock: Callable = time.monotonic,
                 sleep: Callable = time.sleep):
        self.name = name
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._until = 0.0
        self._streak = 0
        self._listeners: list = []
        self.holds = 0                 # times the API said to wait
        self.last_limited: Optional[float] = None

    def listen(self, callback: Callable) -> None:
        """Call *callback()* whenever the API says to wait."""
        self._listeners.append(callback)

    def wait(self) -> None:
        """Return once the gate is open."""
        while True:
            with self._lock:
                left = self._until - self._clock()
            if left <= 0:
                return
            self._sleep(left)

    def closed(self) -> bool:
        with self._lock:
            return self._until > self._clock()

    def limited(self, retry_after: Optional[float] = None) -> float:
        """The API said to wait; returns the seconds the gate stays closed."""
        with self._lock:
            now = self._clock()
            opened = self._until <= now
            if retry_after is not None:
                hold = min(max(0.0, retry_after), HOLD_MAX * 5)
            elif opened:
                hold = min(HOLD_START * 2 ** self._streak, HOLD_MAX)
            else:
                hold = 0.0          # one more of a round that already waits
            if opened:
                self._streak = min(self._streak + 1, STREAK_MAX)
            self._until = max(self._until, now + hold)
            self.holds += 1
            self.last_limited = now
            left = self._until - now
            listeners = list(self._listeners)
        if opened:
            log.warning("%s: the API asked to wait, holding every request "
                        "for %.0f s", self.name or "provider", left)
        for callback in listeners:
            callback()
        return left

    def served(self) -> None:
        with self._lock:
            self._streak = 0


def status_of(exc: BaseException) -> Optional[int]:
    """The HTTP status behind a failed request, if it carries one."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def retry_after(exc: BaseException) -> Optional[float]:
    """The seconds a failed request was told to wait, if it was told."""
    said = getattr(exc, "retry_after", None)
    if isinstance(said, (int, float)):
        return float(said)
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        text = headers.get("retry-after")
    except Exception:
        return None
    if text is None:
        return None
    try:
        return max(0.0, float(str(text).strip()))
    except ValueError:
        return None


class Governed:
    """A client whose requests pass *gate* and tell it what they were told."""

    def __init__(self, client, gate: Gate):
        self._client = client
        self.gate = gate

    def __getattr__(self, name):
        return getattr(self._client, name)

    @property
    def chat(self):
        from types import SimpleNamespace
        return SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: self._ask(
                self._client.chat.completions.create, kwargs)))

    @property
    def embeddings(self):
        from types import SimpleNamespace
        return SimpleNamespace(create=lambda **kwargs: self._ask(
            self._client.embeddings.create, kwargs))

    def _ask(self, send: Callable, kwargs: dict):
        self.gate.wait()
        try:
            answer = send(**kwargs)
        except Exception as exc:
            if status_of(exc) in LIMITED:
                self.gate.limited(retry_after(exc))
            raise
        self.gate.served()
        return answer


_GATES: dict = {}
_GATES_LOCK = threading.Lock()


def gate_for(provider: str, base_url: Optional[str]) -> Gate:
    """The one gate of an endpoint, shared by every client made for it."""
    key = (provider, base_url or "")
    with _GATES_LOCK:
        if key not in _GATES:
            _GATES[key] = Gate(provider if not base_url
                               else f"{provider} {base_url}")
        return _GATES[key]
