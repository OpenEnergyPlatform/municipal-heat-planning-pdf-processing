"""The groups a call to the embedding model runs in
(docpipe/chunking/qwen3_vl_embedding.py, owner decision 2026-11-07).

Promise: a call's inputs are sorted by length AND cut into ten groups of
neighbouring lengths, fewer where there are fewer inputs, AND each group runs
on its own, so it is padded only to its own longest, AND every input is
embedded once, AND the rows come back in the caller's order.
"""
import random

import torch

from docpipe.chunking import qwen3_vl_embedding as qwen


def items(lengths):
    return [{"text": "x" * length} for length in lengths]


def recording():
    """run(items) noting each group's text lengths, one row per item that
    carries its own length."""
    calls = []

    def run(group):
        lengths = [len(item["text"]) for item in group]
        calls.append(lengths)
        return torch.tensor([[float(length)] for length in lengths])
    return calls, run


def test_a_call_runs_in_ten_groups_of_neighbouring_lengths():
    lengths = list(range(1, 26))
    random.Random(3).shuffle(lengths)
    calls, run = recording()
    qwen.in_groups(items(lengths), run)
    assert len(calls) == 10
    assert sorted(len(call) for call in calls) == [2] * 5 + [3] * 5
    for shorter, longer in zip(calls, calls[1:]):
        assert max(shorter) < min(longer)


def test_every_input_is_embedded_once_and_comes_back_at_its_place():
    lengths = [40, 3, 403, 116, 7, 90, 250, 12, 5, 61, 33, 118]
    calls, run = recording()
    rows = qwen.in_groups(items(lengths), run)
    assert sorted(length for call in calls for length in call) == sorted(lengths)
    assert rows[:, 0].tolist() == [float(length) for length in lengths]


def test_fewer_inputs_than_groups_make_as_many_groups_as_inputs():
    calls, run = recording()
    rows = qwen.in_groups(items([30, 10, 20]), run)
    assert calls == [[10], [20], [30]]
    assert rows[:, 0].tolist() == [30.0, 10.0, 20.0]
    calls, run = recording()
    qwen.in_groups(items([30]), run)
    assert calls == [[30]]


def test_the_groups_cover_every_index_once_in_order_of_size():
    sizes = [9, 1, 8, 2, 7, 3, 6, 4, 5, 0, 11, 10]
    groups = qwen.pad_groups(sizes, many=4)
    assert sorted(at for group in groups for at in group) == list(range(12))
    assert [[sizes[at] for at in group] for group in groups] == [
        [0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]


def test_the_model_embeds_each_call_through_the_groups():
    embedder = object.__new__(qwen.Qwen3VLEmbedder)
    calls = []

    def embed(group, normalize):
        calls.append(len(group))
        return torch.zeros((len(group), 2))
    embedder._embed = embed
    rows = embedder.process(items(range(1, 26)))
    assert len(calls) == 10 and sum(calls) == 25
    assert tuple(rows.shape) == (25, 2)
