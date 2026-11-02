# docpipe.extraction.found

`docpipe/extraction/found.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

found.py: Where the harvests before this run found something.

A run starts from nothing: it writes its anchors, takes the top of the ranking
once per document and once per pair, and reads the rest of the plan, although
the harvest before it says which passages carried anything. Of the 24,308
passages of corpus_m7_100, 7,229 gave a tuple.

`--start-at` begins at those. A found place is a passage a stored row stands
in, a stored row was refused in, or a coordinate of a stored row was read in.
Only the place is taken and never an answer, so it outlives a change of a
prompt, the ontology or the graph: the model reads the passage again and the
checks run as ever. The frame and the rows are read over these passages alone.
A coordinate is first asked where it was read last time for a row of the same
passage, and what is still open then is searched as in any run, so `unstated`
keeps its meaning.

A number in a passage no harvest found anything in stays unread. The stamp
says so (`PASS`): a run without `--start-at` harvests such a document again,
and `--top-up-open` reads the passages its trace did not ask.

A document has no found places when no stamped harvest holds it, when nothing
was found in it, or when it no longer holds every place: then it is planned
as in any run.

Author: Felix Vossel

## Classes

### Kept

```python
@dataclass
class Kept
```

The found places of one document, by key: (owner kind, owner id).

Fields:

- `passages: set = field(default_factory=set)`
- `read_at: dict = field(default_factory=dict)`: axis -> {row's passage:

### Found

```python
class Found
```

The found places of a run's documents.

*harvests* are the directories they are read from, *name_of* gives a
document's file stem and *passages_of* is (document, exclude) -> every
passage of it. Only the keys are kept per document; the passages are read
again from the run's shared store.

#### Found.\_\_init\_\_

```python
def __init__(self, harvests, name_of: Callable, passages_of: Callable)
```

#### Found.kept

```python
def kept(self, document_id: int) -> Kept
```

#### Found.passages

```python
def passages(self, document_id: int) -> list
```

Every found place of the document, in document order.

#### Found.read_at

```python
def read_at(self, document_id: int, axes) -> dict
```

{a row's passage: [the passages *axes* were read in for a row of
that passage]}.

## Functions

### own_passage

```python
def own_passage(row: dict)
```

The passage a harvest line stands in, or None.

### places_of

```python
def places_of(rows, kept: Kept) -> None
```

Enter the tuples and refusals of a stored harvest into *kept*.

[Back to the index](../README.md)
