# docpipe.chunking.reembed

`docpipe/chunking/reembed.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reembed.py: Embeds every item of an index again, into a new index file and
under the ids it already has.

A vector is comparable only with vectors embedded the same way: the same
model, and the same implementation of it. Moving the embedder to a vLLM
server (the messages form, docpipe/embedding/api.py) changes every vector,
so the corpus is embedded again as a whole. The database keeps its ids and
is not written: each item's vector goes into the new file under the id the
database already gives it. The old file stays as it is, and a run moves to
the new one by its path.

A record beside the new file (`<index>.json`) says what made it and how far
it got. Only a file with such a record is continued; any other file that
exists is refused, so the index a run reads cannot be written into by
naming it here.

What cannot be embedded again is counted and named, never filled in:

- an id the database maps whose item the processed output no longer builds
  (`no_input`): its old vector stays in the old file only;
- an item the output builds that has no id (`no_id`): the old index lacks it
  too, and the embed step, which hands out ids, embeds it;
- an item the embedder could not serve on its own, after its batch failed
  (`missed`): the run ends incomplete, and a rerun embeds it.

Author: Felix Vossel

## Classes

### Report

```python
@dataclass
class Report
```

What a re-embedding did, counted by embedding type where it left
something out.

Fields:

- `embedded: int = 0`
- `resumed: int = 0`
- `documents: int = 0`
- `no_id: Counter = field(default_factory=Counter)`
- `no_input: Counter = field(default_factory=Counter)`
- `unregistered: list = field(default_factory=list)`
- `missed: Unembedded = field(default_factory=Unembedded)`

#### Report.as_dict

```python
def as_dict(self) -> dict
```

## Functions

### record_path

```python
def record_path(index_path: Path) -> Path
```

Where the record of a re-embedded index file lives: beside it.

### check_target

```python
def check_target(index_path: Path) -> None
```

Refuses a file that exists without a record: that is an index some run
reads, and vectors of another embedder have no place in it.

### plan

```python
def plan(inputs: list, ids: dict, done: set) -> tuple
```

(pending, no_id, no_input) for one document.

*pending* pairs each input with the id the database gives its key, for
the ids *done* does not hold yet; an id is taken once, so two inputs of
one key embed only the first. *no_id* counts the inputs without an id
and *no_input* the ids without an input, by embedding type.

### embed_into

```python
def embed_into(index, pending: list, embedder, missed: Unembedded,
               batch_size: int = EMBEDDING_BATCH_SIZE) -> int
```

Embeds *pending* (id, input) pairs in batches and adds each vector
under its id; returns how many went in.

A batch the embedder cannot serve is tried again input by input, so one
input it cannot take does not cost the others their vectors; an input
that fails on its own goes to *missed*.

### write_record

```python
def write_record(path: Path, embedder, index, report: Report,
                 complete: bool) -> None
```

### run_reembed

```python
def run_reembed(data_dir: Path, db_path: Path, index_path: Path, *,
                embedder=None) -> Report
```

Embeds every item the database maps into *index_path*, a new file or
one an earlier re-embedding began, under the ids the database gives them.

Raises IncompleteIndex after saving when an input has no vector, and
ValueError before anything is written when *index_path* is a file no
re-embedding wrote or the embedder leaves pictures out.

[Back to the index](../README.md)
