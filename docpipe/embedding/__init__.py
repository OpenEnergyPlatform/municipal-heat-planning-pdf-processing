"""
embedding – One interface, two ways to get a vector.

    local   the model runs in this process, on this machine's GPU
    api     an OpenAI-compatible /v1/embeddings endpoint does the work

Which one a deployment uses is a matter of EMBEDDING_BACKEND, not of code:
a laptop without a GPU points at an endpoint, a compute node loads the model.

One limitation worth knowing: the OpenAI embeddings API is text-only. Image
and image+text items (the *_vl embedding types) therefore need the local
backend, or an endpoint that accepts multimodal input.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional, Protocol, Sequence

from . import config


class Embedder(Protocol):
    """Turns items ({"text": ..., "image": ...}) into vectors."""

    def embed(self, items: Sequence[dict]) -> list:
        ...

    def embed_one(self, item: dict) -> list:
        ...


def get_embedder(backend: Optional[str] = None, **kwargs) -> Embedder:
    """The embedder this deployment is configured for."""
    name = (backend or config.BACKEND).strip().lower()
    if name == "api":
        from .api import ApiEmbedder
        return ApiEmbedder(**kwargs)
    if name == "local":
        from .local import LocalEmbedder
        return LocalEmbedder(**kwargs)
    raise ValueError(f"unknown embedding backend {name!r} (local | api)")
