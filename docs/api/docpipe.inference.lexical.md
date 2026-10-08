# docpipe.inference.lexical

`docpipe/inference/lexical.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

lexical.py: A word index over the corpus, beside the vector index.

The vector search finds a passage by what it means. It is weak exactly
where a question is most specific: a name, an abbreviation, a number, a
place. "Stadtwerke Marburg" and "Stadtwerke Kassel" are neighbours in the
embedding space and different words on the page, and a search over a whole
corpus that cannot tell them apart answers from the wrong document. A word
index can, so the chat asks both and merges the two rankings
(`hybrid.py`).

The index is a file of its own beside the corpus database
(`<name>.lexical.db`), built from it and never written into it: the corpus
database stays what the chunk stage made, and the chat keeps opening it
read-only.

    docpipe lexical DB          build it, or build it again
    docpipe lexical DB --check  say whether it is there and current

It holds one row per section, table and figure with its title and text
(SQLite FTS5). It notes a digest of the passages it was built from; a
database whose passages have since changed makes it stale, and a stale
index is not asked: a hit for a passage that no longer exists, or for a
word it no longer has, would be worse than none.

Author: Felix Vossel

## Functions

### path_for

```python
def path_for(db_path) -> Path
```

### build

```python
def build(db_path, out: Optional[Path] = None) -> dict
```

Build the word index of a corpus database. Returns what it holds.

### state

```python
def state(db_path, index_path: Optional[Path] = None) -> str
```

`current`, `stale` or `missing`.

### connect

```python
def connect(db_path, index_path: Optional[Path] = None
            ) -> Optional[sqlite3.Connection]
```

The word index of a corpus, opened read-only, or None when it is
missing or stale. None is said in the log, once, with what to do.

### words

```python
def words(text: str) -> list
```

The words of a question as they are looked for: each once, in the
order they came, and not more than a question plausibly has.

### search

```python
def search(index: sqlite3.Connection, text: str, *,
           document: Optional[int] = None,
           kinds: Optional[Iterable[str]] = None,
           limit: int = 50) -> list
```

[(owner_kind, owner_id, document)] best first, for the passages that
carry words of *text*. A passage with more of them, and with rarer
ones, ranks higher (BM25); a word in the title counts double.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
