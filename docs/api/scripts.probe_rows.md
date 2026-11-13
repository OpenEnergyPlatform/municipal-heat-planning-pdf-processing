# scripts.probe_rows

`scripts/probe_rows.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

probe_rows.py – The requests of the harvest over a few passages.

A corpus job is the slow way to learn whether a prompt or a reply format
works. This asks the real request over named passages against whatever
LLM_BASE_URL and LLM_MODEL say, with the prompt, the split and the reading of
the run, and needs neither a GPU job nor retrieval:

    python scripts/probe_rows.py data/scenarios/scenarios.db --out probe --survey --read --documents 4,23
    python scripts/probe_rows.py --hits passages.json --out new --compute probe

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

`--documents` takes every passage of these documents from the database, in
the order the run reads the rest of a document, and closes each document's
own lists from it as the run does (the profile's `document_axes`).

`--compute` takes the verified rows of a stored probe and asks only what
the compute step leaves open, so its prompt can be tried without reading the
plans again. The plans' passages come from `--hits` or, with the database,
from `--documents`. With the database and `--index` its search by a sentence ranks
the plan as a run does; without them that search finds nothing.

`--survey` with `--documents` makes only the order of each field's pieces
of each whole plan, the first step of the harvest, and keeps it in
`<out>/survey`. With `--read` each plan is then read as the run reads it
(`runner.make_harvest`): its figures transcribed once, every field in every
piece, the fields a document has once asked once, each value's coordinates
asked one by one and searched where its own place does not say them; the
values are folded as the run folds them. With `--index` the search over the
plan is the run's: the global index it names and the embedding model, on the
CPU when the machine has no GPU; without it a search shows the pieces in the
plan's order, and with RERANK_BASE_URL the reranker orders every field's
pieces.

A sandbox round needs CODE_EXEC_URL; `report.json` counts the rounds either way.

## Functions

### states_of

```python
def states_of(tuples: list, names) -> dict
```

{coordinate: {state: tuples}} over the rows that came back.

### trace_events

```python
def trace_events(out: Path) -> list
```

### source_of

```python
def source_of(hit: dict, args)
```

### ranking

```python
def ranking(args)
```

rank(document_id, probes, exclude): the plan ranked for sentences as a
run ranks it, over the global index named by `--index`.

### survey_over

```python
def survey_over(passages: dict, spec, args, document_spec=None) -> list
```

Each document as the run harvests it (`runner.make_harvest`), with
the lists it closes (*document_spec*), made once per document: without
--read the order of each field's pieces, with it the whole reading and
the fold.

### compute_over

```python
def compute_over(stored: Path, hits: list, spec, args, passages=None) -> list
```

The compute step over the verified rows of a stored `--whole` probe.
The raw claims cannot be folded again: their source is a label of the batch
they were read in, and the batches are not stored.

### main

```python
def main() -> int
```

### write_report

```python
def write_report(out: Path, report: list) -> int
```

[Back to the index](../README.md)
