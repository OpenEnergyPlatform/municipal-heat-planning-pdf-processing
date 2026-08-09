"""
local.py – Embeddings from a model loaded in this process.

The model stays resident: it is loaded once and kept on the GPUs. That is what
a batch run wants — thousands of items, one load.

The opposite case, a small card that also serves an interactive app and must
give the memory back between queries, is deployment-specific (which
quantization, which card, how long to wait for the lock) and lives outside
this repository. Point EMBEDDING_BACKEND at it by import path; see
docpipe/embedding/__init__.py.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from . import config

log = logging.getLogger(__name__)


class LocalEmbedder:
    def __init__(self, model: Optional[str] = None,
                 max_length: Optional[int] = None):
        self.model = model or config.EMBEDDING_MODEL
        self.max_length = max_length or config.EMBEDDING_MAX_TOKEN_LENGTH
        self._resident = None

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]

    def embed(self, items: Sequence[dict]) -> list:
        if self._resident is None:
            from docpipe.chunking.qwen3_vl_embedding import MultiGPUEmbedder
            self._resident = MultiGPUEmbedder(self.model, max_length=self.max_length)
        return self._resident.embed(list(items))
