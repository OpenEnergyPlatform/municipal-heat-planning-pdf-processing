# scripts.curation_list

`scripts/curation_list.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

curation_list.py – The values a person should look at, and where to look.

Trust is per value and the summary line is per plan, and between the two sits
the question a curator actually has: which values, in which order, and on
which page. A corpus run produces tens of thousands of tuples and a share of
them carry a reason -- a coordinate the run gave up on or could not back, a
repaired quote, a computed number. Reading the JSONL for those is a filter
nobody should have to write twice.

So: one row per value the harvest cannot stand behind, newest doubt first,
with the page, the crop and the passage that was cited. It is the input to the
mini peer review and, until that runs, the review itself.

    python scripts/curation_list.py data/extraction/corpus
    python scripts/curation_list.py <dir> --level C --out kuration.csv
    python scripts/curation_list.py <dir> --reason exhausted: --limit 200

No model, no database, no GPU: everything it prints was written by the run.

Author: Felix Vossel

## Functions

### coordinates

```python
def coordinates(row: dict) -> str
```

The row's coordinates as one readable cell: axis=value per state.

The state is what makes the cell worth reading. "year=2040" says nothing
about whether anyone should trust it; "year=2040(read)" next to
"sector=(exhausted)" says where to look first.

### rows_of

```python
def rows_of(document: str, tuples: list, *, levels: set,
            reason: str = "") -> list
```

The tuples of one document that a curator should see, worst first.

### read_tuples

```python
def read_tuples(path: Path) -> list
```

The accepted tuples of one harvest file. Refusals and the summary are
not values, so they are not curated.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
