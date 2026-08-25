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
import threading
from typing import Optional, Sequence

from . import config

log = logging.getLogger(__name__)


class LocalEmbedder:
    def __init__(self, model: Optional[str] = None,
                 max_length: Optional[int] = None):
        self.model = model or config.EMBEDDING_MODEL
        self.max_length = max_length or config.EMBEDDING_MAX_TOKEN_LENGTH
        self._resident = None
        self._lock = threading.Lock()

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]

    def embed(self, items: Sequence[dict]) -> list:
        if self._resident is None:
            # "Loaded once and kept" only holds if concurrent callers wait for
            # the first load instead of each starting their own. Several threads
            # share one of these, and a second replica of an 8B model is 16 GB
            # of card that nothing gives back.
            with self._lock:
                if self._resident is None:
                    from docpipe.chunking.qwen3_vl_embedding import MultiGPUEmbedder
                    self._resident = MultiGPUEmbedder(
                        self.model, max_length=self.max_length)
        # MultiGPUEmbedder speaks process() and returns a bf16 tensor; this
        # protocol speaks embed() and returns lists of floats, the same thing
        # ApiEmbedder gives back. Calling .embed() on it raised AttributeError,
        # so this backend had never once run.
        #
        # `normalize` stays at its default: the corpus vectors in the index were
        # written by this very call with that default (chunking/embedding.py),
        # and a query embedded any other way would score against them wrongly
        # instead of failing.
        vectors = self._resident.process(list(items))
        return vectors.detach().float().cpu().tolist()
