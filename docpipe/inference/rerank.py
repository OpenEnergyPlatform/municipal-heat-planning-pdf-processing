"""
rerank.py: The passages of one search, put in order by a reranker.

The vector search ranks a plan's passages by how close their vectors are to
the search sentences. A reranker reads each passage with the sentence and
scores the pair itself (Qwen3-VL-Reranker, served by vLLM's /rerank). It
reorders, of each kind, the best passages the vector search found (rule
`rerank_pool`) and some drawn at random from the places after them (rules
`rerank_drawn` and `rerank_drawn_from`), all read when the search runs; the
rest follow in the vector search's order, so a walk down the list still
reaches every passage (owner decisions 2026-11-06 and 2026-11-08: the
reranker for the retrieval; 2026-11-13: of each kind the best 15 and 10
drawn from the places up to 100, instead of the best 100). The draw is the
same for the same document and sentences, so a run asked again draws the
same passages and the scores the threads share are found again.

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

import hashlib
import logging
import random
import threading
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


# The rules that say how many passages a pool rule draws at random from the
# places after its best, and up to which place: the search's. The reranker
# of the pieces of a plan scores every piece and draws none.
DRAWS = {"rerank_pool": ("rerank_drawn", "rerank_drawn_from")}


def drawn_of(rule: str) -> tuple:
    """(drawn, up to): how many passages of each kind the pool rule *rule*
    draws from the places after its best, and the last place drawn from;
    (0, 0) for a rule that draws none."""
    names = DRAWS.get(rule)
    if names is None:
        return 0, 0
    return int(rules.get(names[0])), int(rules.get(names[1]))


def drawing(seed: str, kind: str) -> random.Random:
    """The chance of one search for one kind: the same for the same *seed*
    in every process (Python's own hash is not)."""
    digest = hashlib.sha256(f"{seed}\x00{kind}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def pool_of(sources: Sequence, size: Optional[int] = None,
            rule: str = "rerank_pool", drawn: int = 0, upto: int = 0,
            seed: str = "") -> tuple:
    """(pool, rest): of each kind its first *size* passages and *drawn* of
    those at its places after them up to place *upto*, drawn at random as
    *seed* says, the pool in the order of *sources* and the others after it
    in theirs. Without *size* each kind has the number the rules give it
    (`pool_size`); a kind whose number is 0 draws none either, and where
    fewer places are left than *drawn*, all of them are taken."""
    places: dict = {}
    for at, source in enumerate(sources):
        places.setdefault(source.owner_kind, []).append(at)
    chosen: set = set()
    for kind, at in places.items():
        wanted = size if size is not None else pool_size(kind, rule)
        chosen.update(at[:wanted])
        if wanted <= 0 or drawn <= 0:
            continue
        after = at[wanted:max(upto, wanted)]
        chosen.update(after if len(after) <= drawn
                      else drawing(seed, kind).sample(after, drawn))
    pool = [s for at, s in enumerate(sources) if at in chosen]
    rest = [s for at, s in enumerate(sources) if at not in chosen]
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


class Scores:
    """The scores the rerankers of one run share, per document.

    A pair of sentence and passage is scored once for the document, not
    once per thread: a thread that wants a pair another one is scoring
    waits for that answer instead of sending its own (`claim`). A
    document's scores are kept while a reranker is on it and dropped when
    the last one moves to another document (`enter`), as each thread
    dropped its own before. Where the scoring fails, the pairs are given
    back (`release`) and a waiting thread scores them itself."""

    def __init__(self):
        self.lock = threading.Lock()
        self.scores: dict = {}
        self.pending: dict = {}
        self.on: dict = {}

    def enter(self, left, document_id) -> None:
        """A reranker moves from document *left* (None: none) to
        *document_id*."""
        with self.lock:
            if left is not None:
                self.on[left] -= 1
                if not self.on[left]:
                    del self.on[left]
                    self.scores.pop(left, None)
            self.on[document_id] = self.on.get(document_id, 0) + 1
            self.scores.setdefault(document_id, {})

    def claim(self, document_id, keys: list) -> tuple:
        """(mine, waits): the keys this caller scores, now marked as being
        scored, and the events of those another caller is scoring."""
        mine, waits = [], []
        with self.lock:
            known = self.scores.setdefault(document_id, {})
            for key in keys:
                if key in known:
                    continue
                event = self.pending.get((document_id, key))
                if event is not None:
                    waits.append(event)
                else:
                    self.pending[(document_id, key)] = threading.Event()
                    mine.append(key)
        return mine, waits

    def put(self, document_id, scored: dict) -> None:
        with self.lock:
            self.scores.setdefault(document_id, {}).update(scored)
            for key in scored:
                event = self.pending.pop((document_id, key), None)
                if event is not None:
                    event.set()

    def release(self, document_id, keys: list) -> None:
        with self.lock:
            for key in keys:
                event = self.pending.pop((document_id, key), None)
                if event is not None:
                    event.set()

    def get(self, document_id, key):
        with self.lock:
            return self.scores.get(document_id, {}).get(key)


class Reranker:
    """order(probes, sources) -> the sources, the pool in the reranker's
    order and the rest after it.

    *post(body)* sends one /rerank request and returns its JSON answer
    (httpx against the server of the rule `rerank_base_url` by default).
    *image_of(source)* is the picture part a request about *source* carries,
    or None. Scores are kept per document, model, sentence and passage, so a
    search asked again with the same sentence and fewer passages left scores
    nothing twice, and a step that names another model scores them again.
    *store* (`Scores`) is shared by the rerankers of all threads of a run,
    so no pair is scored twice for a document, whichever thread asks.

    Server, model, key and pool are read from the rules each time it sends
    or orders, so the step that runs decides; one given here wins.
    *pool_rule* names the rule that says how many passages of each kind it
    scores (`rerank_pool` for a search, with the passages it draws as
    `DRAWS` names; the reranker of the pieces of a plan has a rule of its
    own and draws none).
    """

    def __init__(self, base_url: str = "", model: str = "", pool: int = 0,
                 api_key: str = "", post: Optional[Callable] = None,
                 image_of: Optional[Callable] = None,
                 pool_rule: str = "rerank_pool",
                 store: Optional[Scores] = None):
        self._base_url = base_url
        self._model = model
        self._pool = pool
        self._api_key = api_key
        self.pool_rule = pool_rule
        self._post = post
        self.image_of = image_of or (lambda source: None)
        self._document = None
        self.store = store if store is not None else Scores()

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
            # No time limit (owner decision 2026-11-13): a request given up
            # was scored by the server all the same, and asked again it
            # queued once more behind the ones nobody waited for.
            timeout=None)
        response.raise_for_status()
        return response.json()

    def scores(self, document_id, probe: str, sources: list) -> list:
        """The reranker's score of each of *sources* for *probe*."""
        if self._document != document_id:
            self.store.enter(self._document, document_id)
            self._document = document_id
        model = self.model
        pictures = bool(rules.get("rerank_with_images"))
        cut = int(rules.get("rerank_truncate_tokens"))
        key = lambda s: (model, pictures, cut, probe, s.owner_kind,
                         s.owner_id)
        by_key = {key(s): s for s in sources}
        while True:
            mine, waits = self.store.claim(document_id, list(by_key))
            if mine:
                missing = [by_key[k] for k in mine]
                try:
                    answer = self.post({
                        "model": model, "query": probe,
                        "documents": [document_of(
                            s, self.image_of(s) if pictures else None)
                            for s in missing],
                        "truncate_prompt_tokens": cut})
                    tokens = (answer.get("usage") or {}).get(
                        "prompt_tokens")
                    usage.add(model, input_tokens=int(tokens or 0),
                              requests=1)
                    self.store.put(document_id, {
                        mine[r["index"]]: float(r["relevance_score"])
                        for r in answer["results"]})
                finally:
                    # Pairs the answer left out, or all of them where it
                    # failed, go back; a waiting thread scores them.
                    self.store.release(document_id, mine)
            for event in waits:
                event.wait()
            scores = [self.store.get(document_id, key(s)) for s in sources]
            if all(score is not None for score in scores):
                return scores
            if mine and not waits:
                raise ValueError("the reranker left passages without a "
                                 "score")

    def order(self, document_id, probes: Sequence[str],
              sources: Sequence) -> list:
        sources = list(sources)
        probes = [p for p in probes if p and p.strip()]
        if not probes or not sources:
            return sources
        drawn, upto = drawn_of(self.pool_rule)
        seed = "\x00".join([str(document_id)] + sorted(set(probes)))
        pool, rest = pool_of(sources, self._pool or None, self.pool_rule,
                             drawn, upto, seed)
        best = [fused(column) for column in zip(
            *(self.scores(document_id, probe, pool) for probe in probes))]
        # Equal scores keep the vector search's order (sorted is stable).
        ranked = [source for _, source in sorted(
            zip(best, pool), key=lambda pair: -pair[0])]
        return ranked + rest


def make_reranker(image_of: Optional[Callable] = None,
                  store: Optional[Scores] = None) -> Optional[Reranker]:
    """The reranker this run is configured for, or None where the rule
    `rerank_base_url` names no server. Rerankers given the same *store*
    share their scores."""
    if not base_url():
        return None
    return Reranker(image_of=image_of, store=store)

