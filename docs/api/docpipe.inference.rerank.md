# docpipe.inference.rerank

`docpipe/inference/rerank.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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

## Classes

### Reranker

```python
class Reranker
```

order(probes, sources) -> the sources, the pool in the reranker's
order and the rest after it.

*post(body)* sends one /rerank request and returns its JSON answer
(httpx against RERANK_BASE_URL by default). *image_of(source)* is the
picture part a request about *source* carries, or None. Scores are kept
per document, sentence and passage, so a search asked again with the
same sentence and fewer passages left scores nothing twice.

#### Reranker.\_\_init\_\_

```python
def __init__(self, base_url: str = "", model: str = "", pool: int = 0,
             api_key: str = "", post: Optional[Callable] = None,
             image_of: Optional[Callable] = None)
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

### pool_of

```python
def pool_of(sources: Sequence, size: int) -> tuple
```

(pool, rest): the first *size* passages of each kind in their order,
and the others in theirs.

### document_of

```python
def document_of(source, image: Optional[dict])
```

A passage as /rerank takes it: its text, the picture before the text
where it has one (as the embedder lays out an item).

### make_reranker

```python
def make_reranker(image_of: Optional[Callable] = None) -> Optional[Reranker]
```

The reranker this run is configured for, or None without
RERANK_BASE_URL.

[Back to the index](../README.md)
