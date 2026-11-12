"""
rerank.py: The passages of one search, put in order by a reranker.

The vector search ranks a plan's passages by how close their vectors are to
the search sentences. A reranker reads each passage with the sentence and
scores the pair itself (Qwen3-VL-Reranker, served by vLLM's /rerank). It
reorders the best passages of each kind the vector search found (rule
`rerank_pool`, read when the search runs); the rest follow in the vector
search's order, so a walk down the list still reaches every passage (owner
decisions 2026-11-06 and 2026-11-08: the reranker for the retrieval, 100 per
kind).

A search asks with several sentences, and the vector search keeps the best
score any of them gave a passage. The reranker does the same: each sentence
is one request over the pool, and a passage's score is the sentences' scores
put together as the rule `sentence_fusion` says (`fused`, the one place the
vector search uses too).

What a passage is shown as is the caller's: its text, and the picture of a
figure where the run attaches figures (`image_of`) and the rule
`rerank_with_images` allows it. The server cuts a pair that outgrows the
model to the model's length (rule `rerank_truncate_tokens`, -1: the model's
own), so no length of our own decides what it reads.

Every value is read when it is used (`docpipe.rules`), so a step of the flow
may set its own: the model, the pool, the waiting time.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Sequence

from docpipe import rules, usage

log = logging.getLogger(__name__)

# The model a server is asked for where no setting names one (rule
# `rerank_model` empty): what the machine this was built for serves.
SERVED_MODEL = "Qwen/Qwen3-VL-Reranker-8B"
# What a key says where it is none (rule `rerank_api_key` empty).
NO_KEY = "EMPTY"


def base_url() -> str:
    """The server whose /rerank orders the passages (rule
    `rerank_base_url`), empty where the run has none."""
    return str(rules.get("rerank_base_url") or "").strip()


def model_name() -> str:
    """The model that orders them (rule `rerank_model`)."""
    return str(rules.get("rerank_model") or "").strip() or SERVED_MODEL


def fused(values: Sequence, how: str = "") -> float:
    """What several sentences' scores for one passage come to (rule
    `sentence_fusion`, or *how*): the best, the mean or the sum. The one
    place the reranker and the vector search put sentences together."""
    how = how or rules.get("sentence_fusion")
    values = list(values)
    if how == "max":
        return max(values)
    if how == "mean":
        return sum(values) / len(values)
    if how == "sum":
        return sum(values)
    raise ValueError(f"sentence_fusion {how!r} is neither max, mean nor "
                     f"sum")


def pool_size(kind: str, rule: str = "rerank_pool") -> int:
    """How many passages of *kind* the reranker is given: the rule
    `rerank_pool_by_kind` where it names the kind, else the rule *rule*."""
    by_kind = rules.get("rerank_pool_by_kind") or {}
    if kind in by_kind:
        return int(by_kind[kind])
    return int(rules.get(rule))


def pool_of(sources: Sequence, size: Optional[int] = None,
            rule: str = "rerank_pool") -> tuple:
    """(pool, rest): the first *size* passages of each kind in their order,
    and the others in theirs. Without *size* each kind has the number the
    rules give it (`pool_size`)."""
    taken: dict = {}
    pool, rest = [], []
    for source in sources:
        kind = source.owner_kind
        wanted = size if size is not None else pool_size(kind, rule)
        if taken.get(kind, 0) < wanted:
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
    (httpx against the server of the rule `rerank_base_url` by default).
    *image_of(source)* is the picture part a request about *source* carries,
    or None. Scores are kept per document, model, sentence and passage, so a
    search asked again with the same sentence and fewer passages left scores
    nothing twice, and a step that names another model scores them again.

    Server, model, key and pool are read from the rules each time it sends
    or orders, so the step that runs decides; one given here wins.
    *pool_rule* names the rule that says how many passages of each kind it
    scores (`rerank_pool` for a search; the reranker of the pieces of a plan
    has a rule of its own).
    """

    def __init__(self, base_url: str = "", model: str = "", pool: int = 0,
                 api_key: str = "", post: Optional[Callable] = None,
                 image_of: Optional[Callable] = None,
                 pool_rule: str = "rerank_pool"):
        self._base_url = base_url
        self._model = model
        self._pool = pool
        self._api_key = api_key
        self.pool_rule = pool_rule
        self._post = post
        self.image_of = image_of or (lambda source: None)
        self._document = None
        self._scores: dict = {}

    @property
    def base_url(self) -> str:
        return (self._base_url or base_url()).rstrip("/")

    @property
    def model(self) -> str:
        return self._model or model_name()

    @property
    def api_key(self) -> str:
        return (self._api_key or str(rules.get("rerank_api_key") or "")
                or NO_KEY)

    def post(self, body: dict) -> dict:
        if self._post is not None:
            return self._post(body)
        import httpx
        response = httpx.post(
            self.base_url + "/rerank", json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=float(rules.get("rerank_timeout_s")))
        response.raise_for_status()
        return response.json()

    def scores(self, document_id, probe: str, sources: list) -> list:
        """The reranker's score of each of *sources* for *probe*."""
        if self._document != document_id:
            self._document, self._scores = document_id, {}
        model = self.model
        pictures = bool(rules.get("rerank_with_images"))
        cut = int(rules.get("rerank_truncate_tokens"))
        key = lambda s: (model, pictures, cut, probe, s.owner_kind,
                         s.owner_id)
        missing = [s for s in sources if key(s) not in self._scores]
        if missing:
            answer = self.post({
                "model": model, "query": probe,
                "documents": [document_of(
                    s, self.image_of(s) if pictures else None)
                    for s in missing],
                "truncate_prompt_tokens": cut})
            tokens = (answer.get("usage") or {}).get("prompt_tokens")
            usage.add(model, input_tokens=int(tokens or 0), requests=1)
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
        pool, rest = pool_of(sources, self._pool or None, self.pool_rule)
        best = [fused(column) for column in zip(
            *(self.scores(document_id, probe, pool) for probe in probes))]
        # Equal scores keep the vector search's order (sorted is stable).
        ranked = [source for _, source in sorted(
            zip(best, pool), key=lambda pair: -pair[0])]
        return ranked + rest


def make_reranker(image_of: Optional[Callable] = None) -> Optional[Reranker]:
    """The reranker this run is configured for, or None where the rule
    `rerank_base_url` names no server."""
    if not base_url():
        return None
    return Reranker(image_of=image_of)

