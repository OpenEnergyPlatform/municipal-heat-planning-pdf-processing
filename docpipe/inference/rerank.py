"""
rerank.py: The passages of one search, put in order by a reranker.

The vector search ranks a plan's passages by how close their vectors are to
the search sentences. A reranker reads each passage with the sentence and
scores the pair itself (Qwen3-VL-Reranker, served by vLLM's /rerank). It
reorders the best RERANK_POOL passages of each kind the vector search found;
the rest follow in the vector search's order, so a walk down the list still
reaches every passage (owner decisions 2026-11-06 and 2026-11-08: the
reranker for the retrieval, 100 per kind).

A search asks with several sentences, and the vector search keeps the best
score any of them gave a passage. The reranker does the same: each sentence
is one request over the pool, and a passage's score is its best.

What a passage is shown as is the caller's: its text, and the picture of a
figure where the run attaches figures (`image_of`). The server cuts a pair
that outgrows the model to the model's length (`truncate_prompt_tokens`
-1), so no length of our own decides what it reads.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional, Sequence

from docpipe import usage

log = logging.getLogger(__name__)

RERANK_BASE_URL = os.environ.get("RERANK_BASE_URL", "").strip()
RERANK_API_KEY = os.environ.get("RERANK_API_KEY", "EMPTY")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "Qwen/Qwen3-VL-Reranker-8B")
RERANK_POOL = int(os.environ.get("RERANK_POOL", "100"))

# How long one request may take, as the embedding client waits.
REQUEST_SECONDS = 600.0


def pool_of(sources: Sequence, size: int) -> tuple:
    """(pool, rest): the first *size* passages of each kind in their order,
    and the others in theirs."""
    taken: dict = {}
    pool, rest = [], []
    for source in sources:
        kind = source.owner_kind
        if taken.get(kind, 0) < size:
            taken[kind] = taken.get(kind, 0) + 1
            pool.append(source)
        else:
            rest.append(source)
    return pool, rest


def document_of(source, image: Optional[dict]):
    """A passage as /rerank takes it: its text, the picture before the text
    where it has one (as the embedder lays out an item)."""
    if image is None:
        return source.text or ""
    content = [image]
    if source.text:
        content.append({"type": "text", "text": source.text})
    return {"content": content}


class Reranker:
    """order(probes, sources) -> the sources, the pool in the reranker's
    order and the rest after it.

    *post(body)* sends one /rerank request and returns its JSON answer
    (httpx against RERANK_BASE_URL by default). *image_of(source)* is the
    picture part a request about *source* carries, or None. Scores are kept
    per document, sentence and passage, so a search asked again with the
    same sentence and fewer passages left scores nothing twice.
    """

    def __init__(self, base_url: str = "", model: str = "", pool: int = 0,
                 api_key: str = "", post: Optional[Callable] = None,
                 image_of: Optional[Callable] = None):
        self.base_url = (base_url or RERANK_BASE_URL).rstrip("/")
        self.model = model or RERANK_MODEL
        self.pool = pool or RERANK_POOL
        self.api_key = api_key or RERANK_API_KEY
        self._post = post
        self.image_of = image_of or (lambda source: None)
        self._document = None
        self._scores: dict = {}

    def post(self, body: dict) -> dict:
        if self._post is not None:
            return self._post(body)
        import httpx
        response = httpx.post(
            self.base_url + "/rerank", json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=REQUEST_SECONDS)
        response.raise_for_status()
        return response.json()

    def scores(self, document_id, probe: str, sources: list) -> list:
        """The reranker's score of each of *sources* for *probe*."""
        if self._document != document_id:
            self._document, self._scores = document_id, {}
        key = lambda s: (probe, s.owner_kind, s.owner_id)
        missing = [s for s in sources if key(s) not in self._scores]
        if missing:
            answer = self.post({
                "model": self.model, "query": probe,
                "documents": [document_of(s, self.image_of(s))
                              for s in missing],
                "truncate_prompt_tokens": -1})
            tokens = (answer.get("usage") or {}).get("prompt_tokens")
            usage.add(self.model, input_tokens=int(tokens or 0), requests=1)
            for result in answer["results"]:
                self._scores[key(missing[result["index"]])] = float(
                    result["relevance_score"])
        return [self._scores[key(s)] for s in sources]

    def order(self, document_id, probes: Sequence[str],
              sources: Sequence) -> list:
        sources = list(sources)
        probes = [p for p in probes if p and p.strip()]
        if not probes or not sources:
            return sources
        pool, rest = pool_of(sources, self.pool)
        best = [max(column) for column in zip(
            *(self.scores(document_id, probe, pool) for probe in probes))]
        # Equal scores keep the vector search's order (sorted is stable).
        ranked = [source for _, source in sorted(
            zip(best, pool), key=lambda pair: -pair[0])]
        return ranked + rest


def make_reranker(image_of: Optional[Callable] = None) -> Optional[Reranker]:
    """The reranker this run is configured for, or None without
    RERANK_BASE_URL."""
    if not RERANK_BASE_URL:
        return None
    return Reranker(image_of=image_of)
