# scripts.probe_rows

`scripts/probe_rows.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

probe_rows.py – The rows request of the harvest over a few passages.

A corpus job is the slow way to learn whether a prompt or a reply format
works. This asks the real request over named passages against whatever
LLM_BASE_URL and LLM_MODEL say, with the prompt, the split and the reading of
the run, and needs neither a GPU job nor retrieval:

    python scripts/probe_rows.py data/KWP.db --out probe --owner table/89205
    python scripts/probe_rows.py data/KWP.db --out probe --document 1021 --largest 5
    python scripts/probe_rows.py --hits passages.json --out probe

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

For each passage it reports the tokens and seconds of its requests, the values
read, how many share a quote, and how many stand the two checks of the harvest:
the quote stands in the passage and the number in the quote.

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

### main

```python
def main() -> int
```

[Back to the index](../README.md)
