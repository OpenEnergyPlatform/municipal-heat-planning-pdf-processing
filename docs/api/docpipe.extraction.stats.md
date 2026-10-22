# docpipe.extraction.stats

`docpipe/extraction/stats.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stats.py: Where a harvest is hard, written beside it after every run.

    python -m docpipe.extraction.stats <harvest dir> [--trace trace ...]

The harvest says what was read; this says what was not and why, in the
numbers a report and the ontology side can act on:

- coordinates per parameter, axis and state (`read`, `unstated`,
  `exhausted`, ...), and per document the share still open, hardest first;
- the plan's wordings the model mapped onto a class although no listed
  spelling matched (`<axis>_raw_foreign`): spellings the vocabulary lacks,
  or classes it lacks;
- answers outside the closed list (`not_an_option` drops in the trace),
  with the wording given: candidates for a class the ontology does not have;
- the `out:total` readings per axis and wording, which include the numbers
  a plan does not split by that axis at all;
- per axis and search stage, the requests sent and the coordinates they
  filled, which is what a coordinate costs;
- the reasons answers were dropped, per axis.

Every count says what it counts. Read from the harvest files and the trace
directories named; written to `<harvest dir>/stats/<pass>-<run start>.json`.

## Functions

### from_harvest

```python
def from_harvest(harvest_dir: Path, names: Optional[set] = None) -> dict
```

The counts the harvest files carry.

### from_traces

```python
def from_traces(trace_dirs: Iterable[Path],
                names: Optional[set] = None) -> dict
```

The counts the traces carry: requests and fills per axis and stage,
the reasons answers were dropped, the answers outside the list.

### collect

```python
def collect(harvest_dir: Path, trace_dirs: Iterable[Path] = (),
            names: Optional[set] = None) -> dict
```

### write

```python
def write(harvest_dir: Path, trace_dirs: Iterable[Path] = (),
          names: Optional[set] = None) -> Path
```

Collect and write; returns the file. Logs the lines a report starts
with: the open coordinates per axis and the costliest stages.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
