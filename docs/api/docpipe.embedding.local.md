# docpipe.embedding.local

`docpipe/embedding/local.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

local.py: Embeds items with a model loaded and kept resident in this
process.

LocalEmbedder loads the model once, under a lock, and keeps it on the
GPUs for every later call. This is what a batch run wants: thousands
of items against one load. embed() delegates to
docpipe.chunking.qwen3_vl_embedding.MultiGPUEmbedder, whose
process() method returns a bf16 tensor; embed() converts that tensor
to a list of floats, so this backend returns the same shape of
result as ApiEmbedder. The `normalize` setting is left at its
default because the corpus vectors already stored in the index were
written by the same call with that default
(docpipe/chunking/embedding.py); a query embedded with a different
setting would score against them wrongly rather than fail outright.

The opposite case, a small card that also serves an interactive app
and must give its memory back between queries, is deployment specific
(which quantization, which card, how long to wait for the lock) and
lives outside this repository. Point EMBEDDING_BACKEND at it by
import path; see docpipe/embedding/\_\_init\_\_.py.

Author: Felix Vossel

## Classes

### LocalEmbedder

```python
class LocalEmbedder
```

#### LocalEmbedder.\_\_init\_\_

```python
def __init__(self, model: Optional[str] = None,
             max_length: Optional[int] = None)
```

#### LocalEmbedder.embed_one

```python
def embed_one(self, item: dict) -> list
```

#### LocalEmbedder.embed

```python
def embed(self, items: Sequence[dict]) -> list
```

[Back to the index](../README.md)
