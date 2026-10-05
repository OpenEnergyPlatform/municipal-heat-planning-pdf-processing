# docpipe.chunking.embedding

`docpipe/chunking/embedding.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

embedding.py: Creates text and vision-language embeddings and builds
the FAISS index, as chunking's third step.

Every embedding lives in one FAISS IDMap(IndexFlatIP), keyed by
globally unique ids allocated from the database.

Where the vectors come from is EMBEDDING_INDEX_BACKEND: `local` runs the
model in this process on the visible GPUs; `api` asks an embeddings endpoint
and needs none. A setting of its own beside the query side's
EMBEDDING_BACKEND, because the two differ in a common setup: the index is
built once with the model on GPUs and queried through an endpoint ever
after. An endpoint takes text only, so with it the inputs that carry a
picture are left out and the index holds the text vectors of a corpus.

Author: Felix Vossel

## Classes

### ApiIndexEmbedder

```python
class ApiIndexEmbedder
```

The api backend at index time: items in, one unit vector each out.

The index is an inner-product index and the local model hands it unit
vectors, so these are scaled to length one as well; an endpoint that
already returns unit vectors is left as it is by that.

#### ApiIndexEmbedder.\_\_init\_\_

```python
def __init__(self, embedder=None)
```

#### ApiIndexEmbedder.process

```python
def process(self, items)
```

## Functions

### load_or_create_index

```python
def load_or_create_index(index_path: Path) -> tuple[faiss.Index, int]
```

Load an existing FAISS index or create a new IDMap(IndexFlatIP).

Returns (index, next_id). next_id is only a floor derived from ntotal —
reconcile it with next_faiss_id(db) before allocating.

### index_ids

```python
def index_ids(index: faiss.Index) -> list
```

Every FAISS id the index currently holds.

ntotal counts vectors, this names them. Needed because ids are allocated
from a high-water mark and because a DB row is only trustworthy if its
vector is really in the index.

### save_index

```python
def save_index(index: faiss.Index, index_path: Path) -> None
```

Save the FAISS index to disk.

### remove_ids_from_index

```python
def remove_ids_from_index(index: faiss.Index, ids: list[int]) -> int
```

Remove vectors by id from a FAISS IDMap index; returns the count removed.

### index_backend

```python
def index_backend() -> str
```

What builds the index: `local` or `api`.

### load_embedder

```python
def load_embedder(model_name: str = EMBEDDING_MODEL)
```

The embedder of this run, for the backend EMBEDDING_INDEX_BACKEND names.

`api`: an ApiIndexEmbedder. Otherwise the model itself, data-parallel
across all visible GPUs in bf16: a MultiGPUEmbedder, which exposes the
same ``process()`` interface as a single Qwen3VLEmbedder.

### create_embeddings

```python
def create_embeddings(
    inputs: list[EmbeddingInput],
    index: faiss.Index,
    next_id: int,
    db_path: Path,
    embedder=None,
    *,
    model_name: str = EMBEDDING_MODEL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> int
```

Embed `inputs` (which may mix pdf_names), add the vectors to `index`, and
write their ids to the DB. Returns the updated next_id.

Inputs are split into text-only and VL groups and packed into full
``batch_size`` batches across documents; each input's ``pdf_name`` keeps the
DB writeback grouped per document. A failed batch is logged and skipped.

Persisting the index is the caller's: this is called once per flush chunk,
and the index is one file rewritten whole.

[Back to the index](../README.md)
