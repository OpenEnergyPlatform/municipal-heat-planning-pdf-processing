# scripts.trace_report

`scripts/trace_report.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

trace_report.py – The four questions a run must be able to answer afterwards.

Reads the JSONL the harvest writes under \<out>/trace and prints distributions,
not totals. Every setting this stage has is a cut through one of these, and a
cut can only be defended against the distribution it cuts.

    python scripts/trace_report.py data/extraction/corpus/trace
    python scripts/trace_report.py data/extraction/corpus/trace --top 20

Author: Felix Vossel

## Functions

### percentile

```python
def percentile(values: list, share: float)
```

### spread

```python
def spread(name: str, values: list, unit: str = "") -> str
```

### read

```python
def read(directory: Path)
```

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
