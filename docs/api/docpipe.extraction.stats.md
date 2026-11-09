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
- the reasons answers were dropped, per axis;
- the open questions of the compute step, per kind and how they ended;
- the harvest piece by piece: requests and tokens per kind of request,
  the pieces each document was cut into, the passages it was read in and
  for how many fields, the readings per reason unread, the fields a
  document has once and the values read of them, the works a document
  presents beside itself, and the search sentences that were questions
  (owner decisions 2026-11-08);
- how many requests were with the server at once, on average and at most,
  and the seconds they spent with it and waiting for a place, all and per
  stage; and per stage the requests answered with the answer of the same
  request sent before, which went out once (owner decision 2026-11-07).

Every count says what it counts. Read from the harvest files and the trace
directories named; written to `<harvest dir>/stats/<pass>-<run start>.json`.

## Functions

### at_once

```python
def at_once(timed: list) -> dict
```

How many requests were with the server at once (owner decision
2026-11-07): the mean over the time from the first one sent to the last
answer, and the most at one moment; and the seconds they were with the
server and waited for a place in the run's queue, all and per stage.
*timed* is [(stage, event)] of the events that report a request sent,
whatever their kind. One without its times (a trace from before
2026-11-07) counts in none of these; one no queue held waited no time.

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
