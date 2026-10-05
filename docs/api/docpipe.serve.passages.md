# docpipe.serve.passages

`docpipe/serve/passages.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

passages.py: The passages of the corpus, found by word.

`find_values` answers from what the harvest read. This answers from what
the documents say, for the question the harvest has no value for: it asks
the word index (`inference/lexical.py`) and hands back each passage with
its document, the title of its section, its page and its text, so that a
program can quote it. It is a search and not a reading: a passage found
here is not a verified value.

It needs the corpus database and the word index built from it. Without
either it says so, with what to do about it, and answers no search. A
missing index that answered "nothing found" would read as "the corpus does
not say it", and a stale one would name a passage the database no longer
has. The index is checked once, when the server starts, as the chat does.

Author: Felix Vossel

## Classes

### Unavailable

```python
class Unavailable(RuntimeError)
```

A search that cannot be answered here, and why.

### Passages

```python
class Passages
```

The corpus database and its word index, opened read-only.

Never raises for what is missing: `why` says what, and `search` raises
`Unavailable` with it. Documents are named as the harvest names them,
the file name without its ending.

#### Passages.\_\_init\_\_

```python
def __init__(self, db_path=None)
```

#### Passages.available

```python
@property
def available(self) -> bool
```

#### Passages.close

```python
def close(self) -> None
```

#### Passages.search

```python
def search(self, text: str, *, document: Optional[str] = None,
           limit: int = DEFAULT_LIMIT) -> dict
```

{words, passages}: the passages that carry words of *text*, best
first, at most *limit* of them and never more than `MAX_LIMIT`.

`words` are the words that were looked for; a passage with any of
them is found, one with more of them and rarer ones ranks higher. A
passage is {document, kind, id, title, section_title, page, text,
rank}. *document* limits the search to one document, by its harvest
name. Raises `Unavailable` where there is no search to ask and
`NotFound` for a document the database does not have.

[Back to the index](../README.md)
