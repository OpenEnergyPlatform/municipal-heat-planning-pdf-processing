# docpipe.inference.hybrid

`docpipe/inference/hybrid.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

hybrid.py: One ranking out of two searches, over one document or all.

The chat used to search one document by meaning. Two things were missing:
a search over the whole corpus, and a search by word for the questions a
vector is weak at (`lexical.py` says why). This module is both.

    by meaning   the query vector against the passages' vectors: the
                 document's own sub-index as before, or the global index
                 when no document is named
    by word      the question's words against the word index, where there
                 is one

and the two rankings merged by reciprocal rank: a passage's score is the
sum of 1 / (60 + its rank) over the searches that found it. Ranks, not
scores, because a cosine and a BM25 number share no scale; 60 is the
constant of the method's paper and nothing here was tuned on it.

Without a word index, or for a question that is an image, the result is
the search by meaning alone, in its order and with its scores: what the
chat did before.

Over the whole corpus only the current version of a document answers. An
older version of the same plan would otherwise put two numbers for one
place into one answer.

Author: Felix Vossel

## Functions

### kinds_of

```python
def kinds_of(embedding_types) -> list
```

section | table | figure for a list of embedding types.

### current_documents

```python
def current_documents(conn: sqlite3.Connection) -> Optional[set]
```

The ids of the documents that are the current version of their
work, or None for a database that does not record versions.

### dense_corpus

```python
def dense_corpus(conn: sqlite3.Connection, global_index, embedding_types,
                 query_vec, top_k: int, *, exclude: Optional[set] = None,
                 content_fetcher: Optional[Callable] = None) -> list
```

The best passages of the whole corpus by meaning, as content dicts
with their score, best first, one per passage.

### fuse

```python
def fuse(rankings: list) -> list
```

[(key, score)] best first, from several rankings of keys. A key's
score is the sum of 1 / (RRF_K + rank) over the rankings that hold it;
equal scores keep the order of the first ranking that held them.

### retrieve

```python
def retrieve(conn: sqlite3.Connection, global_index, id_to_pos: dict,
             document_id: Optional[int], embedding_types: list, query_vec,
             top_k: int, *, text: Optional[str] = None,
             lexical_index: Optional[sqlite3.Connection] = None,
             exclude: Optional[set] = None,
             content_fetcher: Optional[Callable] = None) -> list
```

The passages to answer from, best first.

*document_id* None searches the whole corpus. *text* is what the word
index is asked; without it, or without *lexical_index*, the result is
the search by meaning alone. Every hit is a content dict with `score`;
a merged hit also says where each search ranked it (`dense_rank`,
`lexical_rank`, None where that search did not find it).

[Back to the index](../README.md)
