# scripts.harvest_report

`scripts/harvest_report.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

harvest_report.py - The numbers a curator pulls by hand after every run.

Reads every plan of a harvest directory (one \<plan>.jsonl per document, e.g.
data/extraction/corpus_m5; *.trace.jsonl and *.stamp.json are not a plan and
are skipped) and prints the distributions a corpus run is judged by: how many
tuples a plan carries, how many of them came off an image, how trustworthy
they are, why a claim was refused, what state every coordinate and every
parameter ended in, and what the run cost in tokens.

    python scripts/harvest_report.py data/extraction/corpus_m5
    python scripts/harvest_report.py <dir> --usage-db data/usage.db --json out.json

No model, no GPU, no document database. The token usage database is the one
optional SQLite read, and a missing one is reported, not an error.

Author: Felix Vossel

## Functions

### percentile

```python
def percentile(values: list, share: float)
```

The value at this share into the sorted list. Mirrors trace_report.py's
helper so the two reports agree on what "p10" means.

### refusal_family

```python
def refusal_family(reason: str) -> str
```

Which REFUSAL_REASONS pattern this reason matches, its quoted parts
and numbers collapsed into the pattern that owns them. '(unmatched)' for
a reason no published pattern names -- which must not happen, and is
counted separately so a drift between verify.py and schema.py is visible.

### harvest_files

```python
def harvest_files(directory: Path) -> list
```

Every plan of the harvest, sorted; a trace file is not a plan.

### read_plan

```python
def read_plan(path: Path)
```

Stream one plan's rows. A line that is not JSON is skipped, not fatal:
a corpus harvest is hundreds of MB and one torn line must not lose it.

### scan

```python
def scan(files: list) -> dict
```

One streamed pass over every plan into the counters this report prints.

Nothing here holds a whole file in memory: each row is folded into a
counter and dropped. `plan_tuples` and `plan_image` are pre-seeded with
every file so a plan that wrote no tuple still has an entry (needed for
"n plans" and for the thinnest-N cut).

### build_stats

```python
def build_stats(files: list, scanned: dict, usage_rows: list,
                usage_db: Path) -> dict
```

`scan`'s counters, reduced to the JSON-safe numbers this report prints.

Kept separate from `scan` so `--json` writes exactly what the terminal
reads from, rather than a second, independently computed rendering.

### render_report

```python
def render_report(stats: dict) -> str
```

The whole terminal report, as one string, so a test can assert on it
without capturing stdout and `--json` can be checked against the exact
numbers that were printed.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
