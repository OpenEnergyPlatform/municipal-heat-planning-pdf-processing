# docpipe.inference.faiss_store

`docpipe/inference/faiss_store.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

faiss_store.py: Loads the global index and runs scoped retrieval
against an ephemeral sub-index.

The corpus is one global FAISS `IndexIDMap(IndexFlatIP)`. A search is
scoped to a document and a set of embedding types by reconstructing
only the candidate vectors into a small in-memory `IndexFlatIP` and
searching that.

Author: Felix Vossel

## Functions

### load_global_index

```python
def load_global_index(index_path: Path) -> tuple[faiss.Index, dict[int, int]]
```

Load the global FAISS index into RAM, with a dict mapping each stored
faiss_id → its internal position.

The dict is needed because an IndexIDMap does NOT support reconstruct(id);
a vector is pulled back out by inverting the position→id table (`id_map`)
and reconstructing by position on the wrapped flat index — see
reconstruct_vector().

### reconstruct_vector

```python
def reconstruct_vector(global_index: faiss.Index, id_to_pos: dict[int, int], faiss_id: int)
```

Reconstruct one stored vector by its original faiss_id.

### build_subindex

```python
def build_subindex(
    global_index: faiss.Index,
    id_to_pos: dict[int, int],
    faiss_ids: list[int],
) -> faiss.IndexFlatIP
```

Reconstruct the given vector ids from the global index and pack them into a
fresh IndexFlatIP.

Local position p in the sub-index corresponds to faiss_ids[p]; the caller
maps results back through that list. Every id in `faiss_ids` MUST be present
in `id_to_pos`.

### search_subindex

```python
def search_subindex(
    sub_index: faiss.Index,
    query_vec: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]
```

Search a single query row; returns (scores, local_positions) 1×k arrays.

### retrieve_many

```python
def retrieve_many(
    conn: sqlite3.Connection,
    global_index: faiss.Index,
    id_to_pos: dict[int, int],
    document_id: int,
    embedding_types: list[str],
    query_vecs,
    top_k: int,
    content_fetcher: Optional[Callable[[sqlite3.Connection, str, int], Optional[dict]]] = None,
    exclude: Optional[set] = None,
) -> list[list[dict]]
```

Many probes against ONE sub-index. Same results as retrieve() per probe.

build_subindex reconstructs every candidate vector of the document, and a
sweep asks that document some sixty questions per round: rebuilding the
same sub-index for each of them was the whole cost of planning a document.
Here the candidate ids are read once, the sub-index is built once, and FAISS
is handed the probes as one query matrix — which is what its search() has
always taken.

The per-probe exclusion is reproduced exactly, not approximated. Callers
ran the probes in order and grew the excluded set as each one answered, so
that is what happens here, inside one call: `taken` starts as `exclude` and
every probe's answers join it. Searching the unfiltered sub-index and
skipping excluded rows afterwards gives the same rows as filtering first,
because dropping rows from an exact flat index cannot reorder the rest.

### prepare_document

```python
def prepare_document(conn: sqlite3.Connection, global_index: faiss.Index,
                     id_to_pos: dict[int, int], document_id: int,
                     embedding_types: list[str]) -> dict
```

One document's candidate vectors, ready to search.

Everything here depends on the document and not on the probe: the
candidate-id join and the reconstruction of a few hundred vectors are the
expensive half of a sweep and are identical for every parameter and every
round. Kept separate so a caller can build it once and search it many
times.

### search_prepared

```python
def search_prepared(prepared: dict, query_vecs) -> tuple
```

Every probe against a prepared document, in one search.

The full ranking, not top_k: a later probe has to reach past everything
the earlier ones took. On a flat index every score is computed anyway, so
asking for all of them costs the sort, not the search.

### rank_prepared

```python
def rank_prepared(conn: sqlite3.Connection, prepared: dict, scores, positions,
                  top_k: int,
                  content_fetcher: Optional[Callable] = None,
                  exclude: Optional[set] = None) -> list[list[dict]]
```

Walk one search result into per-probe hit lists.

`taken` starts as the caller's exclusion and grows as each probe answers,
which is what the sweep used to do by handing every probe a fresh snapshot
and searching a filtered index.

### fuse_prepared

```python
def fuse_prepared(conn: sqlite3.Connection, prepared: dict, scores, positions,
                  limit: int,
                  content_fetcher: Optional[Callable] = None,
                  exclude: Optional[set] = None,
                  probes: Optional[list] = None,
                  per_probe_top: int = 0) -> list[dict]
```

ONE ranking over all probes, best score per owner. Not one list per probe.

`rank_prepared` answers a different question: it gives each probe its own
top_k and lets each take what the next one may no longer have. Read as a
plan, that puts probe 17's best match behind everything probes 1 to 16
surfaced, whatever the scores were. Measured over 65 documents and 15,082
values, the source a value was actually read from sat at median rank 77
that way and at median 26 under this one, with the same index and the same
probes.

Max over probes, not sum and not mean: a passage is relevant because ONE
question matches it well, and averaging that against fifteen questions it
has nothing to do with is how a good hit gets buried. It also means adding
a probe can only move an owner up, so a probe list is safe to grow — but
only with probes that say something. A vague probe raises everything it
half-matches, which is how the query templates pushed the median from 26
to 84 when they were merged in beside the anchors.

Each hit carries the score AND the probe that won it, because "which
wording found this" is the question the next round of anchors is written
from.

### retrieve

```python
def retrieve(
    conn: sqlite3.Connection,
    global_index: faiss.Index,
    id_to_pos: dict[int, int],
    document_id: int,
    embedding_types: list[str],
    query_vec: np.ndarray,
    top_k: int,
    content_fetcher: Optional[Callable[[sqlite3.Connection, str, int], Optional[dict]]] = None,
    exclude: Optional[set] = None,
) -> list[dict]
```

Full scoped retrieval: candidate ids → sub-index → top-k → dedup by owner →
content + citation, ranked by score descending. Empty list if nothing matches.

`exclude` drops candidates whose (owner_kind, owner_id) is in the set — used
by re-check turns to search past the sources an earlier attempt already
examined.

Dedup must happen POST-search on (owner_kind, owner_id): when e.g. table_text
and table_vl point at the same Table row, only the higher-scoring hit is
kept, and which type scores higher is not known until the search is done.

[Back to the index](../README.md)
