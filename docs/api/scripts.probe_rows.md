# scripts.probe_rows

`scripts/probe_rows.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

probe_rows.py – The requests of the harvest over a few passages.

A corpus job is the slow way to learn whether a prompt or a reply format
works. This asks the real request over named passages against whatever
LLM_BASE_URL and LLM_MODEL say, with the prompt, the split and the reading of
the run, and needs neither a GPU job nor retrieval:

    python scripts/probe_rows.py data/KWP.db --out probe --owner table/89205
    python scripts/probe_rows.py data/KWP.db --out probe --document 1021 --largest 5
    python scripts/probe_rows.py --hits passages.json --out probe
    python scripts/probe_rows.py --hits passages.json --out probe --whole

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

For each passage it reports the tokens and seconds of its requests, the values
read, how many share a quote, and how many stand the two checks of the harvest:
the quote stands in the passage and the number in the quote.

`--whole` asks what a run asks of these passages: the frame, the rows of each
pair and every coordinate of them, with the prompts and the checks of the run.
There is no search: a coordinate is looked for in the other passages given,
in their order, and a list a document closes from the database stays empty.
With `--places` the coordinates are searched over the map of the run instead,
and `--every-row` asks each of its windows for every open row. It writes each
document's report when it is done, and reports the pairs and each coordinate's
states. Several agents share the work through LLM_MODELS and
LLM_SLOTS_PER_MODEL, as in the chat.

A sandbox round needs CODE_EXEC_URL; `report.json` counts the rounds either way.

## Functions

### owners_of

```python
def owners_of(args, conn) -> list
```

### tally

```python
def tally(tuples: list, text: str) -> dict
```

What came back for one passage, by the harvest's two checks.

### states_of

```python
def states_of(tuples: list, slots: list) -> dict
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

### whole

```python
def whole(hits: list, spec, args) -> list
```

The frame, the rows and the coordinates of each document's passages.

### main

```python
def main() -> int
```

### write_report

```python
def write_report(out: Path, report: list) -> int
```

[Back to the index](../README.md)
