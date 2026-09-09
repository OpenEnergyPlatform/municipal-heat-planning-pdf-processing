# docpipe.inference.query_cache

`docpipe/inference/query_cache.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

query_cache.py – On-disk cache mapping a query to its embedding vector, so an
identical query skips the on-demand model load.

Stored in a separate SQLite file, never the authoritative KWP.db.

Author: Felix Vossel

## Functions

### connect

```python
def connect(path: Path, create: bool = True) -> sqlite3.Connection
```

Open the query cache database.

`create=False` skips the DDL and its commit. That commit takes a write
lock on a file every planning thread is reading, and a batch run opens one
of these per document: the schema needs creating once, not a thousand
times.

### make_key

```python
def make_key(mode: str, text: Optional[str] = None, image_bytes: Optional[bytes] = None) -> str
```

Deterministic key over the effective query input. `mode` distinguishes
text-only / image-only / image+text so the same phrase embedded differently
does not collide.

### get

```python
def get(conn: sqlite3.Connection, key: str) -> Optional[np.ndarray]
```

Return the cached (float32) vector for `key`, or None on a miss.

### put

```python
def put(conn: sqlite3.Connection, key: str, vector: np.ndarray) -> None
```

Store `vector` under `key` (idempotent; overwrites on repeat).

### put_many

```python
def put_many(conn: sqlite3.Connection, pairs) -> None
```

Store many vectors in one transaction — one fsync, not one per vector.

[Back to the index](../README.md)
