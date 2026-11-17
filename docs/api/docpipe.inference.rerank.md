# docpipe.inference.rerank

`docpipe/inference/rerank.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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

## Classes

### Scores

```python
class Scores
```

The scores the rerankers of one run share, per document.

A pair of sentence and passage is scored once for the document, not
once per thread: a thread that wants a pair another one is scoring
waits for that answer instead of sending its own (`claim`). A
document's scores are kept while a reranker is on it and dropped when
the last one moves to another document (`enter`), as each thread
dropped its own before. Where the scoring fails, the pairs are given
back (`release`) and a waiting thread scores them itself.

#### Scores.\_\_init\_\_

```python
def __init__(self)
```

#### Scores.enter

```python
def enter(self, left, document_id) -> None
```

A reranker moves from document *left* (None: none) to
*document_id*.

#### Scores.claim

```python
def claim(self, document_id, keys: list) -> tuple
```

(mine, waits): the keys this caller scores, now marked as being
scored, and the events of those another caller is scoring.

#### Scores.put

```python
def put(self, document_id, scored: dict) -> None
```

#### Scores.release

```python
def release(self, document_id, keys: list) -> None
```

#### Scores.get

```python
def get(self, document_id, key)
```

### Reranker

```python
class Reranker
```

order(probes, sources) -> the sources, the pool in the reranker's
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

#### Reranker.\_\_init\_\_

```python
def __init__(self, base_url: str = "", model: str = "", pool: int = 0,
             api_key: str = "", post: Optional[Callable] = None,
             image_of: Optional[Callable] = None,
             pool_rule: str = "rerank_pool",
             store: Optional[Scores] = None,
             window: Optional[object] = None)
```

#### Reranker.base_url

```python
@property
def base_url(self) -> str
```

#### Reranker.model

```python
@property
def model(self) -> str
```

#### Reranker.api_key

```python
@property
def api_key(self) -> str
```

#### Reranker.post

```python
def post(self, body: dict) -> dict
```

#### Reranker.window

```python
def window(self)
```

What one pair holds on this reranker's server (`window_for`), or
the window this reranker was given. A reranker given its own way of
sending (*post*) is given its server's window with it, or none: it
asks no other server.

#### Reranker.units_of

```python
def units_of(self, probe: str, source, image) -> list
```

[(place, text)] that *source* is read as for *probe*: each of
its pieces (`pieces_of`), whole where the pair fits the window,
else in parts, each with the lines its piece carries; place is the
piece's number and the part's.

#### Reranker.scores

```python
def scores(self, document_id, probe: str, sources: list) -> list
```

The reranker's score of each of *sources* for *probe*: of its
best piece, and of a piece its best part (`units_of`).

#### Reranker.order

```python
def order(self, document_id, probes: Sequence[str],
          sources: Sequence, also: Iterable = ()) -> list
```

*sources* best first for *probes*: the pool (`pool_of`, with
the passages *also* names) in the reranker's order, the rest after
it in theirs.

## Functions

### base_url

```python
def base_url() -> str
```

The server whose /rerank orders the passages (rule
`rerank_base_url`), empty where the run has none.

### model_name

```python
def model_name() -> str
```

The model that orders them (rule `rerank_model`).

### fused

```python
def fused(values: Sequence, how: str = "") -> float
```

What several sentences' scores for one passage come to (rule
`sentence_fusion`, or *how*): the best, the mean or the sum. The one
place the reranker and the vector search put sentences together.

### pool_size

```python
def pool_size(kind: str, rule: str = "rerank_pool") -> int
```

How many passages of *kind* the reranker is given: the rule
`rerank_pool_by_kind` where it names the kind, else the rule *rule*.

### drawn_of

```python
def drawn_of(rule: str) -> tuple
```

(drawn, up to): how many passages of each kind the pool rule *rule*
draws from the places after its best, and the last place drawn from;
(0, 0) for a rule that draws none.

### drawing

```python
def drawing(seed: str, kind: str) -> random.Random
```

The chance of one search for one kind: the same for the same *seed*
in every process (Python's own hash is not).

### pool_of

```python
def pool_of(sources: Sequence, size: Optional[int] = None,
            rule: str = "rerank_pool", drawn: int = 0, upto: int = 0,
            seed: str = "", also: Iterable = ()) -> tuple
```

(pool, rest): of each kind its first *size* passages and *drawn* of
those at its places after them up to place *upto*, drawn at random as
*seed* says, and the passages *also* names ((kind, id), the word
index's hits of the search, owner decision 2026-11-17), the pool in the
order of *sources* and the others after it in theirs. Without *size*
each kind has the number the rules give it (`pool_size`); a kind whose
number is 0 draws none either, and where fewer places are left than
*drawn*, all of them are taken.

### drawn_in

```python
def drawn_in(sources: Sequence, pool: Sequence, size: Optional[int] = None,
             rule: str = "rerank_pool") -> list
```

The passages of *pool* (`pool_of`) that were drawn: not among the
first of their kind in *sources* that the pool takes as its best.

### traced

```python
def traced(document_id, reranker: "Reranker", probes: list, sources: list,
           pool: list, rest: list, scored: list, seed: str, drawn: int,
           upto: int, tally: dict, started: float) -> None
```

One order in the trace of its document (`rerank`), under the search
it is part of (`trace.in_search`): passages or pieces, the model, how
many sentences, the pool's best of each kind and those drawn up to
place *upto*, each one's score in the order they came to, the passages
left after the pool, the pairs scored now, kept from before or waited
for, and the time it took. Never raises.

### window_for

```python
def window_for(base: str, model: str, api_key: str,
               post: Callable) -> Optional[object]
```

What one pair holds on the reranker at *base* (`docpipe.window.
Window`): the window the server reports for *model*; the frame of a
pair, the tokens the server counted for a pair of one character each;
its tokenizer for a text; a picture at most as the model's processor
scales one. Kept per server and model once learned whole. A window or
frame that could not be learned (no window reported, a failed probe) is
not kept: None now, and asked again after the interval the chat window
uses (`window.ASK_AGAIN_S`), while pairs go as they are. One
caller asks at a time; the others wait for its answer.

### pieces_of

```python
def pieces_of(source) -> list
```

[(place, piece)] of a passage as the reranker reads it: the pieces
the harvest cuts it into (`docpipe.chunking.pieces.IndexPiece`, the
flow's `piece_lines` lines each), a section's with its heading, place
the piece's number; a piece the harvest hands over (an owner id that is
a passage and a place) is itself, as a `units.Chunk` where it brings
one, else its text.

### document_of

```python
def document_of(source, image: Optional[dict])
```

A passage as /rerank takes it: its text, the picture before the text
where it has one (as the embedder lays out an item).

### make_reranker

```python
def make_reranker(image_of: Optional[Callable] = None,
                  store: Optional[Scores] = None) -> Optional[Reranker]
```

The reranker this run is configured for, or None where the rule
`rerank_base_url` names no server. Rerankers given the same *store*
share their scores.

[Back to the index](../README.md)
