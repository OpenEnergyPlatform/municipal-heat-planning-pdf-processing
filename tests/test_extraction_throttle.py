"""The adaptive request limit: read the server's queue, steer by it."""
import threading
import time

import pytest

from docpipe.extraction import runner, throttle
from docpipe.extraction.throttle import (AdaptiveLimit, Controller, Limited,
                                         Reader, Sample, parse_metrics)

METRICS = """\
# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="m"} 140.0
vllm:num_requests_waiting{engine="0",model_name="m"} 0.0
vllm:kv_cache_usage_perc{engine="0",model_name="m"} 0.586
vllm:num_preemptions_total{engine="0",model_name="m"} %(preempted)s
vllm:inter_token_latency_seconds_sum{engine="0",model_name="m"} %(tpot_sum)s
vllm:inter_token_latency_seconds_count{engine="0",model_name="m"} %(tpot_count)s
vllm:inter_token_latency_seconds_bucket{engine="0",le="0.01",model_name="m"} 3.0
"""


def _metrics(preempted=0, tpot_sum=0.0, tpot_count=0):
    return METRICS % {"preempted": preempted, "tpot_sum": tpot_sum,
                      "tpot_count": tpot_count}


def _reader(*texts):
    reader = Reader("http://server:8000/v1")
    queue = list(texts)
    reader.fetch = lambda: queue.pop(0)
    return reader


def test_metrics_are_summed_over_their_label_sets():
    values = parse_metrics(
        "# TYPE x gauge\n"
        'vllm:num_requests_running{engine="0"} 3\n'
        'vllm:num_requests_running{engine="1"} 4\n'
        "vllm:kv_cache_usage_perc 0.5\n"
        "garbage line\n")
    assert values["vllm:num_requests_running"] == 7
    assert values["vllm:kv_cache_usage_perc"] == 0.5


def test_the_reader_asks_the_server_root_not_the_api():
    assert Reader("http://server:8000/v1").url == "http://server:8000/metrics"
    assert Reader("http://server:8000/v1/").url == "http://server:8000/metrics"


def test_counters_become_differences_between_samples():
    reader = _reader(_metrics(preempted=5, tpot_sum=10.0, tpot_count=100),
                     _metrics(preempted=7, tpot_sum=16.0, tpot_count=150))
    first = reader.sample()
    assert (first.running, first.waiting, first.kv) == (140, 0, 0.586)
    assert first.preempted == 0 and first.tpot is None
    second = reader.sample()
    assert second.preempted == 2
    assert second.tpot == pytest.approx(0.12)


def test_a_server_without_scheduler_metrics_gives_no_sample():
    assert _reader("process_cpu_seconds_total 3.0\n").sample() is None


def _controller(start=100, **kw):
    limit = AdaptiveLimit(start=start, minimum=16, maximum=200)
    return limit, Controller(limit, step=8, backoff=0.8, kv_grow=0.8,
                             kv_high=0.92, **kw)


def _idle(**kw):
    return Sample(**{"running": 90, "waiting": 0, "kv": 0.5, **kw})


def test_a_reached_limit_grows_while_nothing_waits():
    limit, controller = _controller()
    assert controller.decide(_idle(), used=100) == (108, None)


def test_a_limit_nobody_reaches_is_not_raised():
    """The pools or the documents in flight hold the requests below it."""
    limit, controller = _controller()
    assert controller.decide(_idle(), used=60) == (100, None)


def test_a_full_cache_stops_the_growth_before_it_steps_down():
    limit, controller = _controller()
    assert controller.decide(_idle(kv=0.85), used=100) == (100, None)


def test_one_waiting_sample_is_a_blip_two_are_a_queue():
    limit, controller = _controller()
    assert controller.decide(_idle(waiting=4), used=100) == (100, None)
    after, why = controller.decide(_idle(waiting=6), used=100)
    assert after == 80 and "6 waiting" in why


@pytest.mark.parametrize("pressure, reason", [
    ({"kv": 0.95}, "KV cache"),
    ({"preempted": 3}, "preemption"),
])
def test_cache_pressure_steps_down_at_once(pressure, reason):
    limit, controller = _controller()
    after, why = controller.decide(_idle(**pressure), used=100)
    assert after == 80 and reason in why


def test_after_a_step_down_the_limit_holds_while_the_server_drains():
    limit, controller = _controller()
    controller.decide(_idle(kv=0.95), used=100)
    limit.resize(80)
    for _ in range(throttle.HOLD_SAMPLES):
        assert controller.decide(_idle(), used=80) == (80, None)
    assert controller.decide(_idle(), used=80) == (88, None)


def test_the_token_time_steps_down_only_when_a_ceiling_is_set():
    limit, controller = _controller()
    assert controller.decide(_idle(tpot=0.2), used=100) == (108, None)
    limit, controller = _controller(tpot_max=0.1)
    after, why = controller.decide(_idle(tpot=0.2), used=100)
    assert after == 80 and "ms per token" in why


def test_the_limit_stays_inside_its_bounds():
    limit, controller = _controller(start=196)
    assert controller.decide(_idle(), used=196)[0] == 200
    limit, controller = _controller(start=18)
    assert controller.decide(_idle(kv=0.99), used=18)[0] == 16


def test_a_shrunk_limit_lets_no_new_request_in_until_enough_are_back():
    limit = AdaptiveLimit(start=2, minimum=1, maximum=4)
    limit.acquire()
    limit.acquire()
    limit.resize(1)
    entered = threading.Event()

    def third():
        limit.acquire()
        entered.set()

    threading.Thread(target=third, daemon=True).start()
    limit.release()
    assert not entered.wait(0.2), "one request still holds the only place"
    limit.release()
    assert entered.wait(2)
    limit.release()
    assert limit.in_flight == 0


def test_a_grown_limit_wakes_the_requests_waiting_for_it():
    limit = AdaptiveLimit(start=1, minimum=1, maximum=4)
    limit.acquire()
    entered = []
    threads = [threading.Thread(target=lambda: (limit.acquire(),
                                                entered.append(1)),
                                daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.1)
    assert not entered
    limit.resize(3)
    for thread in threads:
        thread.join(2)
    assert len(entered) == 2 and limit.in_flight == 3


def test_the_peak_is_what_was_open_at_most_since_the_last_look():
    limit = AdaptiveLimit(start=4, minimum=1, maximum=4)
    for _ in range(3):
        limit.acquire()
    for _ in range(2):
        limit.release()
    assert limit.take_peak() == 3
    assert limit.take_peak() == 1


def test_a_limited_client_holds_its_place_only_while_it_asks():
    limit = AdaptiveLimit(start=2, minimum=1, maximum=2)
    seen = []

    class Completions:
        def create(self, **kwargs):
            seen.append((limit.in_flight, kwargs))
            if kwargs.get("fail"):
                raise RuntimeError("server said no")
            return "reply"

    class Client:
        chat = type("Chat", (), {"completions": Completions()})()

    client = Limited(Client(), limit)
    assert client.chat.completions.create(model="m") == "reply"
    with pytest.raises(RuntimeError):
        client.chat.completions.create(fail=True)
    assert seen == [(1, {"model": "m"}), (1, {"fail": True})]
    assert limit.in_flight == 0


def test_no_metrics_no_limit():
    def refused():
        raise OSError("connection refused")

    reader = Reader("http://server:8000/v1")
    reader.fetch = refused
    assert throttle.start("http://server:8000/v1", reader=reader) is None
    assert throttle.start("http://server:8000/v1",
                          reader=_reader("other_metric 1\n")) is None


def test_readable_metrics_start_the_limit():
    limit = throttle.start("http://server:8000/v1",
                           reader=_reader(_metrics()), poll=3600,
                           limit=AdaptiveLimit(start=64, minimum=16,
                                               maximum=128))
    assert limit is not None and limit.limit == 64


def test_every_client_the_runner_makes_waits_in_the_limit(monkeypatch):
    limit = AdaptiveLimit(start=8, minimum=1, maximum=8)
    monkeypatch.setattr(runner, "LIMIT", limit)
    assert isinstance(runner._client(), Limited)
    monkeypatch.setattr(runner, "LIMIT", None)
    assert not isinstance(runner._client(), Limited)


def test_the_adaptive_limit_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(runner, "LIMIT", None)
    monkeypatch.setenv("EXTRACT_LIMIT_ADAPTIVE", "0")
    monkeypatch.setattr(throttle, "start",
                        lambda *a, **kw: pytest.fail("asked the server"))
    runner.start_limit()
    assert runner.LIMIT is None
