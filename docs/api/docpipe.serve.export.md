# docpipe.serve.export

`docpipe/serve/export.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

export.py: What a harvest holds, as a table.

Three tables, each as a CSV for a spreadsheet or as JSON lines for a
program:

    values    one line per accepted value, with its quote and its page,
              because a number handed on without what backs it is no
              longer a verified one
    states    one line per document and parameter: what the harvest says
              about it, so "the plan does not say it" (unstated) leaves the
              harvest as a line and not as an absence
    refusals  one line per claim the harvest refused, with the reason

A coordinate of a value is three columns: what was read (`<name>`), its
label where the spec has one (`<name>_label`) and how the reading ended
(`<name>_state`). The columns of a file are the coordinates its values
have, in alphabetical order after the fixed ones. After all of those come
the passages the coordinates were read from (`<name>_quote`), appended so
that a table written before they existed keeps its columns where they were.

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

### states_to_csv

```python
def states_to_csv(cells: Iterable[dict]) -> str
```

### refusals_to_csv

```python
def refusals_to_csv(refusals: Iterable[dict]) -> str
```

### to_jsonl

```python
def to_jsonl(values: Iterable[dict]) -> str
```

[Back to the index](../README.md)
