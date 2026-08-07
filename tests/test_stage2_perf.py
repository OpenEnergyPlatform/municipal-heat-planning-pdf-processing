"""Mixed precision and the render prefetch of Stage 2 — no GPU, no model."""
import threading
import time

import pytest
import torch

from docpipe.preprocessing import stage2_layout as s2


# ---------------------------------------------------------------------------
# Prefetch
# ---------------------------------------------------------------------------

def test_the_order_survives_the_worker_thread():
    got = list(s2._prefetch(range(6), lambda i: i * 2, depth=1))
    assert got == [0, 2, 4, 6, 8, 10]


def test_depth_zero_is_plain_sequential_evaluation():
    order = []
    list(s2._prefetch(range(3), lambda i: order.append(i), depth=0))
    assert order == [0, 1, 2]


def test_a_failure_in_the_worker_reaches_the_consumer():
    def boom(i):
        if i == 2:
            raise RuntimeError("render failed")
        return i

    with pytest.raises(RuntimeError, match="render failed"):
        list(s2._prefetch(range(5), boom, depth=1))


def test_it_really_runs_ahead():
    """The point of the exercise: item n+1 is produced while the consumer is
    still busy with item n."""
    produced = []

    def produce(i):
        produced.append(i)
        return i

    it = s2._prefetch(range(4), produce, depth=1)
    first = next(it)
    # give the worker a moment to fill the queue
    for _ in range(100):
        if len(produced) > 1:
            break
        time.sleep(0.01)
    assert first == 0
    assert len(produced) > 1, "the next batch was not rendered ahead of time"


def test_abandoning_the_generator_does_not_leave_a_wedged_thread():
    before = threading.active_count()
    it = s2._prefetch(range(50), lambda i: i, depth=1)
    next(it)
    it.close()
    for _ in range(200):
        if threading.active_count() <= before:
            break
        time.sleep(0.01)
    assert threading.active_count() <= before


# ---------------------------------------------------------------------------
# Mixed precision
# ---------------------------------------------------------------------------

def test_cpu_never_autocasts():
    assert s2._autocast_dtype("cpu") is None


def test_the_dtype_comes_from_the_config(monkeypatch):
    monkeypatch.setattr(s2, "LAYOUT_AUTOCAST", "bf16")
    assert s2._autocast_dtype("cuda") is torch.bfloat16
    monkeypatch.setattr(s2, "LAYOUT_AUTOCAST", "fp16")
    assert s2._autocast_dtype("cuda") is torch.float16


def test_off_and_nonsense_both_mean_fp32(monkeypatch):
    for value in ("off", "", "float8", "no"):
        monkeypatch.setattr(s2, "LAYOUT_AUTOCAST", value)
        assert s2._autocast_dtype("cuda") is None


def test_boxes_come_back_as_float32():
    """bf16 has 8 mantissa bits: post-processing scales pred_boxes to pixels, so
    a box that stays bf16 lands several pixels off on a 1700 px page."""
    outputs = {"logits": torch.zeros(1, 3, dtype=torch.bfloat16),
               "pred_boxes": torch.tensor([[[0.1234567, 0.2, 0.3, 0.4]]],
                                          dtype=torch.bfloat16),
               "labels": torch.tensor([1, 2])}

    out = s2._to_float32(outputs)

    assert out["logits"].dtype is torch.float32
    assert out["pred_boxes"].dtype is torch.float32
    assert out["labels"].dtype is torch.int64      # ints are left alone
