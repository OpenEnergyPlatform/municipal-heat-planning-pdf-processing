# docpipe.serve.export

`docpipe/serve/export.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

export.py: The harvested values as a table.

One line per value. A CSV for a spreadsheet, JSON lines for a program; both
carry the same columns, and both carry the quote and the page, because a
number handed on without what backs it is no longer a verified one.

A coordinate is three columns: what was read (`<name>`), its label where
the spec has one (`<name>_label`) and how the reading ended
(`<name>_state`). The columns of a file are the coordinates its values
have, in alphabetical order after the fixed ones.

Author: Felix Vossel

## Functions

### flat

```python
def flat(value: dict) -> dict
```

One value as one line.

### columns

```python
def columns(lines: Iterable[dict]) -> list
```

### to_csv

```python
def to_csv(values: Iterable[dict]) -> str
```

### to_jsonl

```python
def to_jsonl(values: Iterable[dict]) -> str
```

[Back to the index](../README.md)
