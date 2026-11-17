# docpipe.extraction.acrossruns

`docpipe/extraction/acrossruns.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Disagreement across runs in the graph (owner decision 2026-11-17, from the
literature on run-to-run noise, Ilves et al. 2026): the rows of further
harvests of the same plans take part in a comparison and in nothing else.
The graph stays this run's: a row of another run never becomes a node or a
node's row, and no model is asked.

A row of another run is read like one of this run (`serialize.collect`, the
same admission in `graph.Writer._numbers`) and marked with its run, the name
of its directory, in the key `run`; this run's rows carry no such key.

Place of a row, the key that decides "the same place in the document": the
passage (`readings.place`) and, where the row carries `at` with a line, that
line and cell; else the passage and the quote. A row without a passage has no
place and is compared by its node only.

## Functions

### read_runs

```python
def read_runs(dirs) -> dict
```

{run name: {document: [rows marked with `run`]}} of the harvest
directories *dirs*; the name is the directory's, made unique with a
number where two directories share one.

### place_key

```python
def place_key(row: dict) -> Optional[tuple]
```

### differing

```python
def differing(here: dict, other: dict, extra: tuple = ()) -> list
```

The coordinates two rows of one place give differently: each key
that has a `<key>_state` on either row, and the *extra* keys (the
wording fields of the box); "other" where only the address differs.

### compare

```python
def compare(*, rows: list, kept: dict, others: list, address: Callable,
            fold: Callable, wording: tuple, tolerance: float,
            drawn_tolerance: Optional[float]) -> tuple
```

(contested, seen, counts) for the nodes {address: row} a document
keeps for one box of numbers, against the rows of other runs.

*rows* are this run's admitted rows, *others* [(run, rows)].
contested {address: {"number": [(run, number)], "coordinates": [(run,
[keys], number)]}}: "number" where a row of another run sits at the node
with a number beyond the rounding rule (`readings.rounds_together`, the
comparison `settle` makes); "coordinates" where a row of another run at
the place of one of this run's rows, with its number, sits at another
node. *seen* are the nodes some row of another run reached; *counts*
counts the rows of other runs that reach no node and no place (rows).

### mark_lines

```python
def mark_lines(found: dict) -> list
```

The lines a node's mark says about its disagreement, English.

[Back to the index](../README.md)
