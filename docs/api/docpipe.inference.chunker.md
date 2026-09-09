# docpipe.inference.chunker

`docpipe/inference/chunker.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

chunker.py – Pack ranked retrieval hits into token-budgeted chunks, each fed to
the LLM as one QA attempt.

Author: Felix Vossel

## Classes

### Chunk

```python
@dataclass
class Chunk
```

One LLM QA attempt: a list of source-tagged content items.

Fields:

- `items: list[dict] = field(default_factory=list)`

## Functions

### get_tokenizer

```python
def get_tokenizer(tokenizer_id: str = LLM_TOKENIZER_ID)
```

Lazily load the LLM tokenizer, cached across calls. None if it cannot be
loaded (offline, gated repo, missing dependency) → char/4 heuristic.

### count_tokens

```python
def count_tokens(text: str, tokenizer=None) -> int
```

Token count via the tokenizer if given, else a char/4 estimate.

### citation_label

```python
def citation_label(hit: dict) -> str
```

Human-readable source label for a retrieval hit.

Goes both ways: the user reads it under the answer and the model reads it
as the excerpt's `source`. So the words are the profile's, only the shape
is ours.

### format_hit

```python
def format_hit(index: int, hit: dict) -> dict
```

Build the per-item dict embedded in a chunk (with source + text).

### pack_chunks

```python
def pack_chunks(hits: list[dict], token_budget: int, tokenizer=None) -> list[Chunk]
```

Greedily pack score-ranked hits into chunks under `token_budget` each.

A single hit larger than the whole budget gets its own OVERSIZED chunk —
content is never truncated, so a chunk can exceed the budget.

[Back to the index](../README.md)
