# docpipe.inference.request_log

`docpipe/inference/request_log.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

request_log.py – Request logging in a separate SQLite file.

Answers are deliberately NOT cached: follow-up queries ("schau noch einmal
nach") are context-dependent, and a cache keyed on the query text alone serves
an answer from a different conversation.

Author: Felix Vossel

## Functions

### connect

```python
def connect(path: Path) -> sqlite3.Connection
```

Open (creating if needed) the request log database.

### log_request

```python
def log_request(
    conn: sqlite3.Connection,
    plan_id: int,
    query_text: str,
    mode: str,
    scopes: list[str],
    latency_ms: float,
    n_hits: Optional[int] = None,
    n_citations: Optional[int] = None,
    answer_hash: Optional[str] = None,
    error_message: Optional[str] = None,
    cache_hit: bool = False,
) -> int
```

Log a single request. Returns the request_id.

[Back to the index](../README.md)
