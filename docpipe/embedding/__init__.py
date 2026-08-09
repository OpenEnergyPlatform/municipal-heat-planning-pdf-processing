"""
embedding – One interface, several ways to get a vector.

    local            the model runs in this process, on this machine's GPU
    api              an OpenAI-compatible /v1/embeddings endpoint does the work
    pkg.mod:Klasse   whatever that import path provides

Which one a deployment uses is a matter of EMBEDDING_BACKEND, not of code:
a laptop without a GPU points at an endpoint, a compute node loads the model.

The third form is the extension point. Loading a model quantized, on demand,
unloading it again between queries — that is a property of one machine's
hardware, not of the pipeline, and such an implementation has no business
sitting in this repository. It lives next to the deployment that needs it and
is named here by import path; all this package requires of it is `embed` and
`embed_one`. See scripts/inference_app/README.md.

One limitation worth knowing: the OpenAI embeddings API is text-only. Image
and image+text items (the *_vl embedding types) therefore need a local
backend, or an endpoint that accepts multimodal input.

Author: Felix Vossel
"""
from __future__ import annotations

from importlib import import_module
from typing import Optional, Protocol, Sequence

from . import config


class Embedder(Protocol):
    """Turns items ({"text": ..., "image": ...}) into vectors."""

    def embed(self, items: Sequence[dict]) -> list:
        ...

    def embed_one(self, item: dict) -> list:
        ...


def _from_path(spec: str, **kwargs) -> Embedder:
    """Import "package.module:attribute" and call it."""
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise ValueError(
            f"embedding backend {spec!r} needs the form 'package.module:attribute'"
        )
    try:
        module = import_module(module_name)
    except ImportError as e:
        raise ValueError(f"embedding backend {spec!r}: {e}") from e
    try:
        factory = getattr(module, attr)
    except AttributeError as e:
        raise ValueError(f"embedding backend {spec!r}: no {attr!r} in {module_name}") from e
    return factory(**kwargs)


def get_embedder(backend: Optional[str] = None, **kwargs) -> Embedder:
    """The embedder this deployment is configured for."""
    spec = (backend or config.BACKEND).strip()
    if ":" in spec:
        return _from_path(spec, **kwargs)
    name = spec.lower()
    if name == "api":
        from .api import ApiEmbedder
        return ApiEmbedder(**kwargs)
    if name == "local":
        from .local import LocalEmbedder
        return LocalEmbedder(**kwargs)
    raise ValueError(
        f"unknown embedding backend {name!r} (local | api | package.module:attribute)"
    )
