"""
__init__.py: Exposes one Embedder interface behind several backends.

get_embedder() reads EMBEDDING_BACKEND and returns one of three
things. "local" loads the model in this process, on this machine's
GPU (embedding/local.py). "api" calls an OpenAI-compatible
/v1/embeddings endpoint (embedding/api.py). Anything of the form
"package.module:attribute" is an import path: the module is imported,
the named attribute is called with the given keyword arguments, and
whatever it returns is used as the embedder. Which of the three a
deployment uses is a matter of configuration, not of code: a laptop
without a GPU points at an endpoint, a compute node loads the model.

The import-path form is the extension point. Loading a model
quantized, on demand, and freeing the memory again between queries
depends on one machine's hardware and not on the pipeline, so such an
implementation lives next to the deployment that needs it rather than
in this repository. It is named here only by import path; the
package requires of it only an `embed` method and an `embed_one`
method. See scripts/inference_app/README.md.

One limitation holds for every deployment: the OpenAI embeddings API
is text only. Image and image+text items (the *_vl embedding types)
therefore need a local backend, or an endpoint that accepts
multimodal input.

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
