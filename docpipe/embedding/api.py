"""
api.py: Embeds items by calling an embeddings API.

ApiEmbedder is for deployments without a GPU, or for a deployment
where the embedding model is served centrally. Which API it calls is
the provider of the `embedding` role (EMBEDDING_PROVIDER, see
docpipe/providers): an OpenAI-compatible /v1/embeddings endpoint, or
a hosted one. It batches items into groups of batch_size before
calling it, and asks a hosted API again that answers "not now". The
embeddings request has no place for an image, so embed() is text
only: an item carrying an image is refused with a ValueError rather
than silently embedded as text.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from docpipe import providers, usage
from docpipe.providers import governor

from . import config

log = logging.getLogger(__name__)

# Attempts at one batch for a hosted API that answers "not now".
HOSTED_ATTEMPTS = 6


class ApiEmbedder:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None, batch_size: Optional[int] = None):
        self.base_url = base_url or config.EMBEDDING_BASE_URL
        self.api_key = api_key or config.EMBEDDING_API_KEY
        self.model = model or config.EMBEDDING_MODEL
        self.batch_size = batch_size or config.EMBEDDING_BATCH_SIZE
        if not self.base_url and not providers.hosted("embedding"):
            raise ValueError("EMBEDDING_BASE_URL is required for the api backend")
        self._client = None

    def client(self):
        if self._client is None:
            self._client = providers.client(
                "embedding", base_url=self.base_url, api_key=self.api_key)
        return self._client

    def _create(self, batch: list):
        """The vectors of one batch.

        A hosted API that says "not now" is asked again: its gate has made
        every request wait by then (docpipe/providers/governor.py), so the
        next attempt goes out when the API said it may. A server of one's
        own is asked once, as before; its client retries by itself.
        """
        attempts = HOSTED_ATTEMPTS if providers.hosted("embedding") else 1
        for attempt in range(1, attempts + 1):
            try:
                return self.client().embeddings.create(model=self.model,
                                                       input=batch)
            except Exception as exc:
                again = (governor.status_of(exc) in governor.LIMITED
                         or providers.timed_out(exc))
                if attempt == attempts or not again:
                    raise
                log.warning("embeddings: attempt %d of %d not served (%s)",
                            attempt, attempts, exc)

    def embed(self, items: Sequence[dict]) -> list:
        visual = [i for i, it in enumerate(items) if it.get("image")]
        if visual:
            raise ValueError(
                f"item(s) {visual} carry an image; the OpenAI embeddings API is "
                f"text-only. Use EMBEDDING_BACKEND=local for *_vl embeddings.")

        out = []
        texts = [str(it.get("text") or "") for it in items]
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = self._create(batch)
            out.extend(d.embedding for d in response.data)
            tokens = getattr(getattr(response, "usage", None), "prompt_tokens", None)
            if isinstance(tokens, int):
                usage.add(self.model, embedding_tokens=tokens, requests=len(batch))
        return out

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]
