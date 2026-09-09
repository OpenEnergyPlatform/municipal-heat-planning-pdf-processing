# docpipe.inference.answer

`docpipe/inference/answer.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

answer.py: Runs one retrieval and answer turn, with no user interface
attached.

The chat app and the batch runner ask the same question of the same
corpus. Only what they do with the progress and the result differs,
so everything the turn needs from outside is passed in: the open
corpus, how to embed a query, where an image lives, and an optional
progress reporter.

Author: Felix Vossel

## Classes

### Corpus

```python
@dataclass
class Corpus
```

The open resources one turn works on.

Fields:

- `conn: sqlite3.Connection`
- `index: Any`
- `id_to_pos: dict`
- `embed: Callable[[dict], tuple]`: query item -> (vector, came_from_cache)
- `resolve_image: Callable[[Optional[str]], Optional[Path]] = lambda p: None`: stored image path -> a readable path, or None
- `log_conn: Optional[sqlite3.Connection] = None`

## Functions

### scopes_are_visual

```python
def scopes_are_visual(scopes: list) -> bool
```

True if the query targets ONLY figure/table scopes → caption-style anchor.

### answer_question

```python
def answer_question(task: str, corpus: Corpus, document_id: int, scopes: list, *,
                    image_bytes: Optional[bytes] = None, image_only: bool = False,
                    as_json: bool = False, history: Optional[list] = None,
                    progress: Callable = _silent) -> dict
```

Execute one full retrieval + answer turn. Returns a dict with:
answer (str|None), answer_text (str|None), citations (list[dict]),
n_findings (int), cache_hit (bool), n_hits (int), phrase (str|None),
as_json (bool), n_batches (int), compute (list), examined, recheck,
n_excluded.

answer is None when nothing was retrieved or nothing could be grounded.

[Back to the index](../README.md)
