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

The reranker reads pieces, not whole passages (owner decision 2026-11-17,
"**Nichts** kürzen, einfach ggf. clever aufteilen"): a passage is cut into
the pieces the harvest reads (`pieces_of`: a section's heading with its
lines, a table's title, head, lines under it and rows its rows stand under
with its own rows), each piece is scored with the sentence, and the passage
counts with its best piece. A piece the harvest hands over (an owner of a
passage and a place) is read as it is. A pair of sentence and piece that
does not fit the server's window (`window_for`: its `max_model_len`, the
frame of a pair as the server counts it, its tokenizer) is split into parts,
each with the lines its piece carries, and the piece counts with its best
part. Nothing is cut, by us or by the server: no request asks it to cut.

What a passage is shown as is the caller's: its text, and the picture of a
figure where the run attaches figures (`image_of`) and the rule
`rerank_with_images` allows it; every piece of a figure goes with its
picture.

Every value is read when it is used (`docpipe.rules`), so a step of the flow
may set its own: the model, the pool, the waiting time.

Each order is written to the trace of its document (`rerank`, owner decision
2026-11-14), under the search it is part of: which passages were the best of
their kind and which were drawn, each one's score and the order they came
to, and how many pairs were scored, taken from the scores the threads share
or waited for.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from typing import Callable, Iterable, Optional, Sequence

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
            seed: str = "", also: Iterable = ()) -> tuple:
    """(pool, rest): of each kind its first *size* passages and *drawn* of
    those at its places after them up to place *upto*, drawn at random as
    *seed* says, and the passages *also* names ((kind, id), the word
    index's hits of the search, owner decision 2026-11-17), the pool in the
    order of *sources* and the others after it in theirs. Without *size*
    each kind has the number the rules give it (`pool_size`); a kind whose
    number is 0 draws none either, and where fewer places are left than
    *drawn*, all of them are taken."""
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
    named = {(kind, owner) for kind, owner in also}
    if named:
        chosen.update(at for at, source in enumerate(sources)
                      if (source.owner_kind, source.owner_id) in named)
    pool = [s for at, s in enumerate(sources) if at in chosen]
    rest = [s for at, s in enumerate(sources) if at not in chosen]
    return pool, rest


def drawn_in(sources: Sequence, pool: Sequence, size: Optional[int] = None,
             rule: str = "rerank_pool") -> list:
    """The passages of *pool* (`pool_of`) that were drawn: not among the
    first of their kind in *sources* that the pool takes as its best."""
    seen: dict = {}
    best: set = set()
    for source in sources:
        kind = source.owner_kind
        seen[kind] = seen.get(kind, 0) + 1
        wanted = size if size is not None else pool_size(kind, rule)
        if seen[kind] <= wanted:
            best.add((kind, _named(source.owner_id)))
    return [source for source in pool
            if (source.owner_kind, _named(source.owner_id)) not in best]


def _named(owner_id):
    """An owner id as the trace writes it: a passage's number, or a piece's
    passage and place as a list."""
    return owner_id if isinstance(owner_id, (int, str)) \
        else tuple(owner_id)


def traced(document_id, reranker: "Reranker", probes: list, sources: list,
           pool: list, rest: list, scored: list, seed: str, drawn: int,
           upto: int, tally: dict, started: float) -> None:
    """One order in the trace of its document (`rerank`), under the search
    it is part of (`trace.in_search`): passages or pieces, the model, how
    many sentences, the pool's best of each kind and those drawn up to
    place *upto*, each one's score in the order they came to, the passages
    left after the pool, the pairs scored now, kept from before or waited
    for, and the time it took. Never raises."""
    try:
        from docpipe.extraction import trace
        if not trace.enabled():
            return
        pieces = bool(pool) and not isinstance(pool[0].owner_id, (int, str))

        def key(source) -> list:
            named = _named(source.owner_id)
            return list(named) if pieces else [source.owner_kind, named]
        trace.in_search(
            "rerank", document_id, level="pieces" if pieces else "passages",
            model=reranker.model, pool_rule=reranker.pool_rule,
            sentences=len(probes),
            drawn=[key(s) for s in drawn_in(
                sources, pool, reranker._pool or None, reranker.pool_rule)],
            draws=drawn, upto=upto,
            seed=hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16],
            order=[[*key(source), round(float(score), 4)]
                   for score, source in scored],
            rest=len(rest), pairs=dict(tally), ms=trace.ms_since(started))
    except Exception as exc:                      # pragma: no cover - defensive
        log.debug("rerank: trace dropped: %s", exc)


# -- pieces and the window ------------------------------------------------------

_WINDOWS: dict = {}
_ASKED: dict = {}
# One lookup per server and model at a time; a caller that comes while it
# runs waits for its answer.
_LOOKUPS: dict = {}
_WINDOWS_LOCK = threading.Lock()


def window_for(base: str, model: str, api_key: str,
               post: Callable) -> Optional[object]:
    """What one pair holds on the reranker at *base* (`docpipe.window.
    Window`): the window the server reports for *model*; the frame of a
    pair, the tokens the server counted for a pair of one character each;
    its tokenizer for a text; a picture at most as the model's processor
    scales one. Kept per server and model once learned whole. A window or
    frame that could not be learned (no window reported, a failed probe) is
    not kept: None now, and asked again after the interval the chat window
    uses (`window.ASK_AGAIN_S`), while pairs go as they are. One
    caller asks at a time; the others wait for its answer."""
    from docpipe.window import ASK_AGAIN_S
    key = (base, model)
    with _WINDOWS_LOCK:
        if key in _WINDOWS:
            return _WINDOWS[key]
        lookup = _LOOKUPS.setdefault(key, threading.Lock())
    with lookup:
        with _WINDOWS_LOCK:
            if key in _WINDOWS:
                return _WINDOWS[key]
            asked = _ASKED.get(key)
            if asked is not None \
                    and time.monotonic() - asked < ASK_AGAIN_S:
                return None
            _ASKED[key] = time.monotonic()
        made = _learn_window(base, model, api_key, post)
        if made is not None:
            with _WINDOWS_LOCK:
                _WINDOWS[key] = made
        return made


def _learn_window(base: str, model: str, api_key: str,
                  post: Callable) -> Optional[object]:
    """The `window_for` of a server and model as the server says it now;
    None where it says no window or counts no pair."""
    from docpipe import window as windows
    from docpipe.embedding.config import IMAGE_FACTOR, IMAGE_MAX_PIXELS
    limit = windows.served_limit(base, model, api_key)
    if not limit:
        log.warning("rerank: %s reports no window; pairs go as they are "
                    "until it is asked again", base)
        return None
    try:
        answer = post({"model": model, "query": ".", "documents": ["."]})
        frame = int((answer.get("usage") or {}).get("prompt_tokens") or 0)
    except Exception as exc:
        log.warning("rerank: %s counted no pair (%s); pairs go as they are "
                    "until it is asked again", base, exc)
        return None
    if frame <= 0:
        log.warning("rerank: %s counted no tokens for a pair; pairs go as "
                    "they are until it is asked again", base)
        return None
    most = IMAGE_MAX_PIXELS // (IMAGE_FACTOR * IMAGE_FACTOR) + 2
    return windows.Window(
        limit=int(limit), frame=frame,
        count=windows.server_counter(base, model, api_key),
        picture=lambda _image: most)


def pieces_of(source) -> list:
    """[(place, piece)] of a passage as the reranker reads it: the pieces
    the harvest cuts it into (`docpipe.chunking.pieces.IndexPiece`, the
    flow's `piece_lines` lines each), a section's with its heading, place
    the piece's number; a piece the harvest hands over (an owner id that is
    a passage and a place) is itself, as a `units.Chunk` where it brings
    one, else its text."""
    if not isinstance(source.owner_id, (int, str)):
        chunk = getattr(source, "chunk", None)
        if chunk is not None:
            from docpipe.chunking.pieces import IndexPiece
            return [((), IndexPiece(chunk))]
        return [((), None)]
    from docpipe.chunking.pieces import IndexPiece, _with_heading, piece_lines
    from docpipe.extraction import units
    from docpipe.extraction.pipeline import Source
    provenance = dict(getattr(source, "provenance", None) or {})
    kind = source.owner_kind
    heading = ((provenance.get("section_title") or "") if kind == "section"
               else (provenance.get("title") or ""))
    text = _with_heading(heading, source.text or "")
    passage = units.passage_of(Source(kind, source.owner_id, text,
                                      provenance))
    chunks = units.chunks_of(passage, piece_lines())
    if not chunks:
        return [((), None)]
    return [((chunk.index,), IndexPiece(
        chunk, "", heading.strip() if kind == "section" else ""))
        for chunk in chunks]


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
                 store: Optional[Scores] = None,
                 window: Optional[object] = None):
        self._window = window
        self._base_url = base_url
        self._model = model
        self._pool = pool
        self._api_key = api_key
        self.pool_rule = pool_rule
        self._post = post
        self.image_of = image_of or (lambda source: None)
        self._document = None
        self.store = store if store is not None else Scores()
        # What the order running now took from the shared scores: pairs
        # scored, kept from before, waited for (`traced`).
        self._tally: Optional[dict] = None

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

    def window(self):
        """What one pair holds on this reranker's server (`window_for`), or
        the window this reranker was given. A reranker given its own way of
        sending (*post*) is given its server's window with it, or none: it
        asks no other server."""
        if self._window is not None or self._post is not None:
            return self._window
        return window_for(self.base_url, self.model, self.api_key, self.post)

    def units_of(self, probe: str, source, image) -> list:
        """[(place, text)] that *source* is read as for *probe*: each of
        its pieces (`pieces_of`), whole where the pair fits the window,
        else in parts, each with the lines its piece carries; place is the
        piece's number and the part's."""
        from docpipe.window import TooLong
        window = self.window()
        out: list = []
        for place, piece in pieces_of(source):
            text = (source.text or "") if piece is None else piece.render()
            if window is None or _pair_fits(window, probe, text, image):
                out.append((place + (0,), text))
                continue
            if piece is None:
                out.append((place + (0,), text))
                log.warning("rerank: a piece of %s %s does not fit the "
                            "window and has no lines to split by; it goes "
                            "as it is", source.owner_kind, source.owner_id)
                continue
            try:
                parts = piece.parts(
                    lambda part: _pair_fits(window, probe, part, image),
                    f"{source.owner_kind} {source.owner_id}")
            except TooLong as exc:
                log.warning("rerank: %s; it goes whole", exc)
                out.append((place + (0,), text))
                continue
            out.extend((place + (at,), part.text)
                       for at, part in enumerate(parts))
        return out

    def scores(self, document_id, probe: str, sources: list) -> list:
        """The reranker's score of each of *sources* for *probe*: of its
        best piece, and of a piece its best part (`units_of`)."""
        if self._document != document_id:
            self.store.enter(self._document, document_id)
            self._document = document_id
        model = self.model
        pictures = bool(rules.get("rerank_with_images"))
        # Every piece (and part) a pair of its own, scored once for the
        # document; a passage counts with its best.
        unit_keys: list = []
        by_key: dict = {}
        for source in sources:
            image = self.image_of(source) if pictures else None
            keys = []
            for place, text in self.units_of(probe, source, image):
                key = (model, pictures, probe, source.owner_kind,
                       source.owner_id) + tuple(place)
                keys.append(key)
                by_key.setdefault(key, (text, image))
            unit_keys.append(keys)
        first = True
        while True:
            mine, waits = self.store.claim(document_id, list(by_key))
            if self._tally is not None:
                self._tally["scored"] += len(mine)
                if first:
                    self._tally["waited"] += len(waits)
                    self._tally["kept"] += len(by_key) - len(mine) \
                        - len(waits)
            first = False
            if mine:
                missing = [by_key[k] for k in mine]
                try:
                    answer = self.post({
                        "model": model, "query": probe,
                        "documents": [document_of(
                            _Text(text), image)
                            for text, image in missing]})
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
            got = [[self.store.get(document_id, key) for key in keys]
                   for keys in unit_keys]
            if all(score is not None for keys in got for score in keys):
                return [max(keys) for keys in got]
            if mine and not waits:
                raise ValueError("the reranker left passages without a "
                                 "score")

    def order(self, document_id, probes: Sequence[str],
              sources: Sequence, also: Iterable = ()) -> list:
        """*sources* best first for *probes*: the pool (`pool_of`, with
        the passages *also* names) in the reranker's order, the rest after
        it in theirs."""
        sources = list(sources)
        probes = [p for p in probes if p and p.strip()]
        if not probes or not sources:
            return sources
        started = time.time()
        drawn, upto = drawn_of(self.pool_rule)
        seed = "\x00".join([str(document_id)] + sorted(set(probes)))
        pool, rest = pool_of(sources, self._pool or None, self.pool_rule,
                             drawn, upto, seed, also)
        self._tally = {"scored": 0, "kept": 0, "waited": 0}
        try:
            best = [fused(column) for column in zip(
                *(self.scores(document_id, probe, pool) for probe in probes))]
            tally = dict(self._tally)
        finally:
            self._tally = None
        # Equal scores keep the vector search's order (sorted is stable).
        scored = sorted(zip(best, pool), key=lambda pair: -pair[0])
        ranked = [source for _, source in scored]
        traced(document_id, self, probes, sources, pool, rest, scored, seed,
               drawn, upto, tally, started)
        return ranked + rest


class _Text:
    """A text as `document_of` reads a passage."""

    def __init__(self, text: str):
        self.text = text


def _pair_fits(window, probe: str, text: str, image) -> bool:
    """Does a pair of *probe* and *text*, with *image* where it has one,
    fit *window*: their bytes where those fit, else their counted tokens."""
    room = window.room((image,) if image is not None else ())
    if room < 0:
        return False
    size = len((probe or "").encode("utf-8")) + len((text or "").encode("utf-8"))
    if size <= room:
        return True
    return window.tokens(probe or "", None) + window.tokens(text or "", None) \
        <= room


def make_reranker(image_of: Optional[Callable] = None,
                  store: Optional[Scores] = None) -> Optional[Reranker]:
    """The reranker this run is configured for, or None where the rule
    `rerank_base_url` names no server. Rerankers given the same *store*
    share their scores."""
    if not base_url():
        return None
    return Reranker(image_of=image_of, store=store)

