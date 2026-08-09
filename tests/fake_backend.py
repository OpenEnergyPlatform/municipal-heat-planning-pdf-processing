"""Stands in for a deployment-supplied embedding backend.

The real one lives on the inference server (an NF4-quantized, on-demand
loader). What this repository can test is the binding: that an import path in
EMBEDDING_BACKEND is resolved, constructed with the caller's keyword arguments,
and used through embed / embed_one like any other.
"""
from __future__ import annotations

from typing import Sequence


class FakeEmbedder:
    def __init__(self, tag: str = "plain"):
        self.tag = tag

    def embed(self, items: Sequence[dict]) -> list:
        return [[float(len(it.get("text", "")))] for it in items]

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]


def make_embedder(**kwargs) -> FakeEmbedder:
    return FakeEmbedder(tag="factory", **kwargs)
