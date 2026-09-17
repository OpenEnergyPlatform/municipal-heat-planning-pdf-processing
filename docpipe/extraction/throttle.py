"""
throttle.py: How many model requests the harvest keeps open, steered by the
server's own queue.

A fixed number of client threads left the server idle: at 140 requests in
flight vLLM reported nothing waiting and 58 percent of its KV cache in use,
so the harvest, not the four GPUs, set the pace. The right number is not a
constant either. It moves with what is being asked (a field request over two
passages is a fraction of a rows request over a table) and with how much of
each prompt the server already holds in its prefix cache.

So the limit is steered while the run goes (additive increase, multiplicative
decrease). Every few seconds the controller reads the server's /metrics:

  up    nothing waiting, the KV cache below KV_GROW, and the client actually
        using the limit it has
  down  requests waiting (twice in a row), the KV cache at KV_HIGH, or a
        preemption

The time per output token is not a reason to step down: it grows with every
sequence in the batch while the tokens per second of the whole batch still
rise, and those are what the harvest waits for. EXTRACT_LIMIT_TPOT_MAX makes
it one for a server shared with interactive users.

After a step down it holds for a few samples, so the server can drain before
it is pushed again. A server without /metrics gets no limit at all, and one
that stops answering them leaves the limit where it is. The limit decides only
when a request is sent, never what it asks or what is accepted from its answer.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

log = logging.getLogger(__name__)

START = int(os.environ.get("EXTRACT_LIMIT_START", "128"))
MINIMUM = int(os.environ.get("EXTRACT_LIMIT_MIN", "16"))
MAXIMUM = int(os.environ.get("EXTRACT_LIMIT_MAX", "512"))
STEP = int(os.environ.get("EXTRACT_LIMIT_STEP", "8"))
BACKOFF = float(os.environ.get("EXTRACT_LIMIT_BACKOFF", "0.8"))
POLL = float(os.environ.get("EXTRACT_LIMIT_POLL", "5"))
# KV cache fractions: grow only below the first, step down at the second.
KV_GROW = float(os.environ.get("EXTRACT_LIMIT_KV_GROW", "0.80"))
KV_HIGH = float(os.environ.get("EXTRACT_LIMIT_KV_HIGH", "0.92"))
# Seconds per output token above which a sample counts as pressure; unset,
# the token time never steps the limit down.
TPOT_MAX = (float(os.environ["EXTRACT_LIMIT_TPOT_MAX"])
            if os.environ.get("EXTRACT_LIMIT_TPOT_MAX") else None)
# Consecutive waiting samples before stepping down, and samples held after.
WAITING_SAMPLES = 2
HOLD_SAMPLES = 6


class AdaptiveLimit:
    """A semaphore whose size can change while requests hold it."""

    def __init__(self, start: int = START, minimum: int = MINIMUM,
                 maximum: int = MAXIMUM):
        self.minimum = max(1, int(minimum))
        self.maximum = max(self.minimum, int(maximum))
        self._limit = min(self.maximum, max(self.minimum, int(start)))
        self._open = 0
        self._peak = 0
        self._cond = threading.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        return self._open

    def take_peak(self) -> int:
        """The most requests open at once since the last call."""
        with self._cond:
            peak, self._peak = self._peak, self._open
            return peak

    def acquire(self) -> None:
        with self._cond:
            while self._open >= self._limit:
                self._cond.wait()
            self._open += 1
            self._peak = max(self._peak, self._open)

    def release(self) -> None:
        with self._cond:
            self._open -= 1
            self._cond.notify()

    def resize(self, limit: int) -> int:
        with self._cond:
            self._limit = min(self.maximum, max(self.minimum, int(limit)))
            self._cond.notify_all()
            return self._limit

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class Limited:
    """A client whose chat.completions.create waits for a place in *limit*.

    The client's own timeout starts once the place is taken: waiting here is
    the harvest's queue, not the server's slowness.
    """

    def __init__(self, client, limit: AdaptiveLimit):
        self._client = client
        self._limit = limit
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create))

    def create(self, *args, **kwargs):
        with self._limit:
            return self._client.chat.completions.create(*args, **kwargs)


@dataclass
class Sample:
    """One reading of the server, differences taken against the last one."""
    running: float
    waiting: float
    kv: float                          # fraction of KV cache blocks in use
    preempted: float = 0.0             # preemptions since the last sample
    tpot: Optional[float] = None       # mean seconds per output token


_LINE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+(\S+)")


def parse_metrics(text: str) -> dict:
    """{metric name: value summed over its label sets} from Prometheus text."""
    out: dict = {}
    for line in (text or "").splitlines():
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        try:
            value = float(match.group(3))
        except ValueError:
            continue
        out[match.group(1)] = out.get(match.group(1), 0.0) + value
    return out


def _first(values: dict, *names) -> Optional[float]:
    for name in names:
        if name in values:
            return values[name]
    return None


class Reader:
    """Samples the server's /metrics, turning counters into differences."""

    def __init__(self, base_url: str, timeout: float = 3.0):
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        self.url = root + "/metrics"
        self.timeout = timeout
        self._last: Optional[dict] = None

    def fetch(self) -> str:
        with urllib.request.urlopen(self.url, timeout=self.timeout) as reply:
            return reply.read().decode("utf-8", "replace")

    def sample(self) -> Optional[Sample]:
        values = parse_metrics(self.fetch())
        running = _first(values, "vllm:num_requests_running")
        waiting = _first(values, "vllm:num_requests_waiting")
        kv = _first(values, "vllm:kv_cache_usage_perc",
                    "vllm:gpu_cache_usage_perc")
        if running is None or waiting is None or kv is None:
            return None
        now = {
            "preempted": _first(values, "vllm:num_preemptions_total",
                                "vllm:num_preemptions") or 0.0,
            "tpot_sum": _first(values, "vllm:inter_token_latency_seconds_sum",
                               "vllm:time_per_output_token_seconds_sum"),
            "tpot_count": _first(values,
                                 "vllm:inter_token_latency_seconds_count",
                                 "vllm:time_per_output_token_seconds_count"),
        }
        last, self._last = self._last, now
        preempted = 0.0
        tpot = None
        if last is not None:
            preempted = max(0.0, now["preempted"] - last["preempted"])
            if None not in (now["tpot_sum"], last["tpot_sum"],
                            now["tpot_count"], last["tpot_count"]):
                tokens = now["tpot_count"] - last["tpot_count"]
                if tokens > 0:
                    tpot = (now["tpot_sum"] - last["tpot_sum"]) / tokens
        return Sample(running=running, waiting=waiting, kv=kv,
                      preempted=preempted, tpot=tpot)


class Controller:
    """Decides the next limit from one sample; no threads, no I/O."""

    def __init__(self, limit: AdaptiveLimit, *, step: int = STEP,
                 backoff: float = BACKOFF, kv_grow: float = KV_GROW,
                 kv_high: float = KV_HIGH,
                 tpot_max: Optional[float] = TPOT_MAX):
        self.limit = limit
        self.step = max(1, int(step))
        self.backoff = backoff
        self.kv_grow = kv_grow
        self.kv_high = kv_high
        self.tpot_max = tpot_max
        self._waiting_streak = 0
        self._hold = 0

    def decide(self, sample: Sample, used: int) -> tuple:
        """(new limit, reason) for *sample*, *used* the peak requests open."""
        current = self.limit.limit
        self._waiting_streak = (self._waiting_streak + 1
                                if sample.waiting > 0 else 0)
        why = None
        if sample.preempted > 0:
            why = f"{sample.preempted:.0f} preemption(s)"
        elif sample.kv >= self.kv_high:
            why = f"KV cache {sample.kv:.0%}"
        elif self._waiting_streak >= WAITING_SAMPLES:
            why = f"{sample.waiting:.0f} waiting"
        elif (self.tpot_max is not None and sample.tpot is not None
              and sample.tpot > self.tpot_max):
            why = f"{sample.tpot * 1000:.0f} ms per token"
        if why is not None:
            self._hold = HOLD_SAMPLES
            self._waiting_streak = 0
            return max(self.limit.minimum,
                       int(current * self.backoff)), why
        if self._hold > 0:
            self._hold -= 1
            return current, None
        # Only a limit that is reached is a limit worth raising: while the
        # thread pools or the documents in flight hold the requests below it,
        # a larger number would change nothing but the log.
        if (sample.waiting == 0 and sample.kv < self.kv_grow
                and used >= current - self.step // 2):
            return min(self.limit.maximum, current + self.step), None
        return current, None


def start(base_url: str, *, limit: Optional[AdaptiveLimit] = None,
          reader: Optional[Reader] = None,
          poll: float = POLL) -> Optional[AdaptiveLimit]:
    """An adaptive limit and the daemon thread that steers it.

    None when the server does not serve vLLM's /metrics: without a queue to
    read there is nothing to steer by, and the thread pools bound the
    requests as they did before.
    """
    reader = reader or Reader(base_url)
    try:
        first = reader.sample()
        error = "no vLLM scheduler metrics"
    except Exception as exc:
        first, error = None, exc
    if first is None:
        log.warning("llm limit: %s unreadable (%s) -- no adaptive limit, the "
                    "thread pools bound the requests", reader.url, error)
        return None
    limit = limit or AdaptiveLimit()
    controller = Controller(limit)

    def steer() -> None:
        failed = 0
        while True:
            time.sleep(poll)
            try:
                sample = reader.sample()
            except Exception as exc:
                failed += 1
                if failed in (1, 60):
                    log.warning("llm limit: %s unreadable (%s) -- held at %d",
                                reader.url, exc, limit.limit)
                continue
            failed = 0
            if sample is None:
                continue
            used = limit.take_peak()
            before = limit.limit
            after, why = controller.decide(sample, used)
            if after != before:
                limit.resize(after)
                log.info("llm limit %d -> %d%s (running %.0f, waiting %.0f, "
                         "KV %.0f%%, open %d)", before, limit.limit,
                         f": {why}" if why else "", sample.running,
                         sample.waiting, sample.kv * 100, used)

    threading.Thread(target=steer, name="llm-limit", daemon=True).start()
    log.info("llm limit: adaptive from %d (%d..%d), step +%d / x%.2f, "
             "KV %.0f%%..%.0f%%, %s", limit.limit, limit.minimum,
             limit.maximum, controller.step, controller.backoff,
             controller.kv_grow * 100, controller.kv_high * 100, reader.url)
    return limit
