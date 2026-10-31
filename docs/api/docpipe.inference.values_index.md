# docpipe.inference.values_index

`docpipe/inference/values_index.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

values_index.py: Finds harvested values by what they mean.

A question names a value in a person's words, and the harvest holds it in the
plan's words and the spec's lists. Closed questions have to land on exactly
what was read there, and a word they miss leaves nothing. So every value gets
a line of words (`entry_text`) and a vector of that line, the chat looks for
the lines nearest to its search anchor, and the model chooses among them
(`values_route.answer_from_index`).

The vectors are a file of their own beside the harvest
(`<harvest>.values.db`), built from it and never written into it:

    docpipe values-index HARVEST          build it, or bring it up to date
    docpipe values-index HARVEST --check  say whether it is there and current

A vector is filed under a digest of its line. So a line that stayed keeps its
vector through a new harvest, two values that read alike share one, and a
build that stopped goes on where it stopped: what it finished stays in the
`.building` file beside the index, and two builds on two machines can be
poured into one.

A value without a vector, or vectors of another model, make the index stale.
A stale index is not asked: a value it does not hold could never be found, and
nobody would see that it is missing. The chat then asks its closed questions,
and the log says why.

Author: Felix Vossel

## Classes

### Index

```python
@dataclass
class Index
```

The vectors of one harvest in memory, one row per different line.

Fields:

- `values: list`: the store's values
- `lines: list`: the line of each, in the same order
- `matrix: np.ndarray`: (different lines, dimensions)
- `rows: np.ndarray`: the row of each value
- `of_document: dict = field(default_factory=dict)`

#### Index.search

```python
def search(self, vector, *, document: Optional[str] = None,
           levels: Optional[Sequence[str]] = None) -> list
```

[(value, line)] of the values of *document* (None: of all) in
*levels* (None: every one), nearest to *vector* first. Values that
read alike are one line, and stand here once.

## Functions

### path_for

```python
def path_for(harvest_dir) -> Path
```

### entry_text

```python
def entry_text(value: dict, name: str) -> str
```

The line one value is searched and chosen by: whose it is, what it is
a number of, the number as the plan writes it, and the passage it stands
in. Made of what the harvest holds and nothing else, so the same value
gives the same line in every language a profile has.

### lines_of

```python
def lines_of(store, names: dict) -> list
```

The line of every value of *store*, in its order. *names* says what a
document is called; one it does not know goes by its harvest name.

### document_names

```python
def document_names(catalog, conn) -> dict
```

{harvest name of a document: what it is called}, for every document of
the corpus, superseded ones too.

### build

```python
def build(harvest_dir, lines: Iterable[str], *, embedder=None,
          out: Optional[Path] = None, batch: Optional[int] = None) -> dict
```

Bring the index of a harvest up to *lines*.

Only a line without a vector is embedded, shortest first, so a batch pads
to about its own length. Each batch is committed: a build that stops
keeps what it finished in `<index>.building`, and the next one goes on
from there. The index itself is replaced whole, at the end. Returns
{lines, reused, embedded, seconds}, which the index keeps too.

### state

```python
def state(lines: Iterable[str], index_path: Path) -> str
```

`current`, `stale` or `missing`.

### load

```python
def load(harvest_dir, store, names: dict,
         index_path: Optional[Path] = None) -> Optional[Index]
```

The index of a harvest in memory, or None when it is missing or stale.
None is said in the log, once, with what to do.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
