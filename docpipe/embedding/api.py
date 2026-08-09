"""
api.py – Embeddings from an OpenAI-compatible /v1/embeddings endpoint.

For deployments without a GPU, or where the embedding model is served
centrally. Text only: the OpenAI embeddings schema has no place for an image,
so an item carrying one is refused rather than silently embedded as text.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from . import config

log = logging.getLogger(__name__)


class ApiEmbedder:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None, batch_size: Optional[int] = None):
        self.base_url = base_url or config.EMBEDDING_BASE_URL
        self.api_key = api_key or config.EMBEDDING_API_KEY
        self.model = model or config.EMBEDDING_MODEL
        self.batch_size = batch_size or config.EMBEDDING_BATCH_SIZE
        if not self.base_url:
            raise ValueError("EMBEDDING_BASE_URL is required for the api backend")
        self._client = None

    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        return self._client

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
            response = self.client().embeddings.create(model=self.model, input=batch)
            out.extend(d.embedding for d in response.data)
        return out

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]
