# docpipe.inference.rerank

`docpipe/inference/rerank.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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
scores (`rerank_pool` for a search; the reranker of the pieces of a plan
has a rule of its own).

#### Reranker.\_\_init\_\_

```python
def __init__(self, base_url: str = "", model: str = "", pool: int = 0,
             api_key: str = "", post: Optional[Callable] = None,
             image_of: Optional[Callable] = None,
             pool_rule: str = "rerank_pool",
             store: Optional[Scores] = None)
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

#### Reranker.scores

```python
def scores(self, document_id, probe: str, sources: list) -> list
```

The reranker's score of each of *sources* for *probe*.

#### Reranker.order

```python
def order(self, document_id, probes: Sequence[str],
          sources: Sequence) -> list
```

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

### pool_of

```python
def pool_of(sources: Sequence, size: Optional[int] = None,
            rule: str = "rerank_pool") -> tuple
```

(pool, rest): the first *size* passages of each kind in their order,
and the others in theirs. Without *size* each kind has the number the
rules give it (`pool_size`).

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
