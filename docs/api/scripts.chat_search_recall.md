# scripts.chat_search_recall

`scripts/chat_search_recall.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

chat_search_recall.py - How often the chat's search puts the passage and the
page a harvested value was read from among its hits.

The harvest read every accepted value from one passage, and its two checks
(the quote stands in a shown passage, the answer stands in the quote) already
say that passage carries the value. That is a target nobody has to judge. For
each accepted value this script puts the spec's question for the value's
parameter, the parameter's label, to the chat's own search path: the search
sentence the model writes, its embedding, and the hybrid search over the
scopes the index holds. It then counts whether the value's passage, and the
page that passage starts on, are among the first hits the chat reads and
among all the hits it retrieves.

    python scripts/chat_search_recall.py data/extraction/corpus --profile kwp
    python scripts/chat_search_recall.py <harvest dir> --db <db> --index <index>
    python scripts/chat_search_recall.py <harvest dir> --whole-corpus

The counts are split by how the harvest came to read the passage, as far as
its trace says: found by a search of its own (the plan listed the passage as a
retrieval hit), or by the document's structure (the plan listed it so and not
as a hit). A passage the harvest found by search is one a search is likely to
find again, so that row reads better than the other and the two are not one
number. Two more rows hold what the trace does not say: a passage that no plan
event of its document lists (read after the plan, for instance from a search
the model asked for, so not a finding by structure either) and a document
without a plan in the trace.

It stops after the search. No passage is read, no answer is written, nothing
judges a number, and so nothing here says whether the chat answers right. A
passage is named by the database's own ids, which are counters: a database
built again since the harvest needs `python -m docpipe.extraction.identity`
first, or a value's passage is another one. A value whose passage is not in the
database under its document is counted and left out. Where the search sentence
is the question itself, the model did not answer and the chat's own fallback
searched with the question: that is counted and said, not hidden.

Needs the model server and the embedder, and reads the corpus database and
index read-only. The vectors are not cached, so a run measures the embedder
that is configured now.

Author: Felix Vossel

## Classes

### Value

```python
@dataclass(frozen=True)
class Value
```

One accepted value and where the harvest read it from.

Fields:

- `document: str`: the harvest's name for the document
- `document_id: int`
- `parameter: str`: the spec's uri
- `kind: str`: section | table | figure
- `owner: int`: the passage's id in the database
- `page: Optional[int]`: the page the passage starts on

### Plans

```python
@dataclass
class Plans
```

What the harvest's trace says about how passages were planned.

Fields:

- `origins: dict`: (document id, kind, owner) -> {plan origins}
- `traced: set`: ids of the documents that have plan events

#### Plans.of

```python
def of(self, value: Value) -> str
```

### ChatSearch

```python
class ChatSearch
```

The chat's search for one question, as the chat runs it.

The search sentence is the model's, the embedding the configured
embedder's, and the ranking `answer.search_hits`, which `answer_question`
calls too. One search per (document, parameter): its question does not
change with the value, and the ranking does not either.

#### ChatSearch.\_\_init\_\_

```python
def __init__(self, corpus, scopes: list, questions: dict)
```

## Functions

### harvest_values

```python
def harvest_values(rows_by_document: dict) -> tuple
```

([Value], {why: rows}) of the accepted rows of a harvest.

A row that does not say where it was read from cannot be asked about, and
is counted under `no address` instead of being dropped without a word.

### read_plans

```python
def read_plans(directory: Path, names: Iterable[str]) -> Plans
```

The plan events of the trace beside a harvest, for the named
documents. A missing trace is no plan, not an error: it is said.

### measure

```python
def measure(values: list, search: Callable, plans: Plans,
            in_database: Callable, first: int, *,
            whole_corpus: bool = False) -> dict
```

{origin: Counter} and {"left": Counter} of the values.

A value counts `passage first` / `passage hits` when its passage is among
the first `first` hits / among all the hits, and the same for its page;
`pages` counts the values that name one. A value whose passage is not in
the database under its document is left out and counted.

### render

```python
def render(result: dict, *, first: int, hits: int, searches: int,
           sentence_is_question: int, whole_corpus: bool, accepted: int,
           unplaced: dict) -> str
```

The report, as text.

### open_chat

```python
def open_chat(db_path: Path, index_path: Path)
```

(corpus, scopes, in_database) as the chat opens them: the database
read-only, the global index, the word index where it is current, and the
configured embedder asked one query at a time without a cache.

### main

```python
def main(argv: Optional[list] = None) -> int
```

[Back to the index](../README.md)
