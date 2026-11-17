# scripts.prefix_share

`scripts/prefix_share.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

prefix_share.py - How many prompt tokens the server served from its prefix
cache, per request kind (owner decision 2026-11-17, from the literature on
requests that share their beginning: BatchLLM, SGLang; rule `example_place`).

Reads the traces of a run (plain or .gz, as `stats.from_traces` does) and
prints, per request kind and step: requests, prompt tokens, cached tokens and
the share cached. A trace written before `cached_tokens` was traced says so;
with --usage-db the usage database's totals per stage and model are printed
instead, which are the run's totals and not per kind. No model, no network.

    python scripts/prefix_share.py data/extraction/corpus/trace
    python scripts/prefix_share.py trace --usage-db usage.sqlite

Author: Felix Vossel

## Functions

### shares

```python
def shares(trace_dirs) -> tuple
```

({(kind, step): [requests, prompt tokens, cached tokens]}, requests
that carry no `cached_tokens`). A request is an event `<kind>_ask` that
reports prompt tokens and was sent (not an answer given again).

### report

```python
def report(rows: dict, unreported: int) -> str
```

### database

```python
def database(path: Path) -> str
```

The usage database's totals per stage and model.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
