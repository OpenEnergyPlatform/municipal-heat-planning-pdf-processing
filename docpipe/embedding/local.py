"""
local.py – Embeddings from a model loaded in this process.

Two loading strategies, both deployment detail:

  on_demand  load, embed, free again (a small card that also serves an app;
             see quantized.py)
  resident   keep the model on the GPUs for a batch run (qwen3_vl_embedding)

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from . import config

log = logging.getLogger(__name__)


class LocalEmbedder:
    def __init__(self, model: Optional[str] = None, strategy: str = "on_demand",
                 max_length: Optional[int] = None,
                 idle_unload_seconds: Optional[int] = None):
        self.model = model or config.EMBEDDING_MODEL
        self.strategy = strategy
        self.max_length = max_length or config.EMBEDDING_MAX_TOKEN_LENGTH
        self.idle_unload_seconds = (config.EMBED_IDLE_UNLOAD_SECONDS
                                    if idle_unload_seconds is None else idle_unload_seconds)
        self._resident = None

    def embed_one(self, item: dict) -> list:
        if self.strategy == "on_demand":
            from .quantized import embed_query
            return embed_query(item, self.model, self.max_length,
                               idle_unload_seconds=self.idle_unload_seconds)
        return self.embed([item])[0]

    def embed(self, items: Sequence[dict]) -> list:
        if self.strategy == "on_demand":
            return [self.embed_one(it) for it in items]
        if self._resident is None:
            from docpipe.chunking.qwen3_vl_embedding import MultiGPUEmbedder
            self._resident = MultiGPUEmbedder(self.model, max_length=self.max_length)
        return self._resident.embed(list(items))
