"""Sharding across replicas: the caller's order back, and balanced shards.

Both properties used to be wrong in a way nothing would have noticed until a
corpus build: the order was restored by a Python loop copying one 4096-float
row at a time, and shards were dealt by position, so a single long item padded
its whole shard and every other GPU waited for it.
"""
import pytest

torch = pytest.importorskip("torch")
qwen = pytest.importorskip("docpipe.chunking.qwen3_vl_embedding")


class _Replica:
    """Answers with the length of each input, so a row identifies its item."""

    def __init__(self):
        self.seen = []

    def process(self, inputs, normalize=True):
        self.seen.append([len(i["text"]) for i in inputs])
        return torch.tensor([[float(len(i["text"]))] for i in inputs])


def _embedder(n):
    obj = qwen.MultiGPUEmbedder.__new__(qwen.MultiGPUEmbedder)
    obj.replicas = [_Replica() for _ in range(n)]
    obj.devices = [f"cuda:{i}" for i in range(n)]
    return obj


def test_the_result_comes_back_in_the_caller_order():
    embedder = _embedder(4)
    inputs = [{"text": "x" * k} for k in range(1, 31)]
    out = embedder.process(inputs)
    assert out.shape == (30, 1)
    assert [int(v) for v in out[:, 0].tolist()] == list(range(1, 31))


def test_one_long_item_does_not_land_in_a_shard_of_short_ones():
    """Padding is per shard, so the cost of a shard is its longest member
    times its size. Dealing the longest items out first spreads them."""
    embedder = _embedder(4)
    inputs = [{"text": "x" * 8000} for _ in range(4)] + \
             [{"text": "x" * 10} for _ in range(40)]
    embedder.process(inputs)
    longest_per_shard = [max(r.seen[0]) for r in embedder.replicas]
    assert longest_per_shard == [8000] * 4, (
        "each replica takes one of the four long items, not one shard all four")


def test_a_single_replica_needs_no_sharding():
    embedder = _embedder(1)
    out = embedder.process([{"text": "abc"}, {"text": "de"}])
    assert [int(v) for v in out[:, 0].tolist()] == [3, 2]
