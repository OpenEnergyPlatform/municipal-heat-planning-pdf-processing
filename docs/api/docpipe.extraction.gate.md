# docpipe.extraction.gate

`docpipe/extraction/gate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

gate.py: Whether the graph of a run can still be written, before the run.

    python -m docpipe.extraction.gate HARVEST DB TTL --against REPORT.shacl.json

A corpus run spends its GPU hours on a harvest that ends in a graph. The
graph is written last, and every reason it could not be (a serializer that
no longer builds against the shapes the run just pulled, a Turtle no parser
reads, a validator that does not run, a kind of violation the shapes newly
ask for) showed only then. This writes the graph of the harvest that is
already there, with the code and the shapes the run will use, and exits
non-zero for any of those, so a job stops before it starts its model.

Violations are compared by kind (constraint, path, collection: the keys of
`<ttl>.shacl.json`) with the report of the graph the last run wrote. Counts
move with the harvest and are not compared; a kind that was not there
before is the shapes asking for something the serializer does not write.
Without an earlier report there is nothing to compare, and the gate says
so and stays open.

Exit 0: written, parsed, validated, no new kind. Exit 3: shut, the reasons
are in the log.

Author: Felix Vossel

## Functions

### new_kinds

```python
def new_kinds(report: dict, against: dict) -> list
```

The kinds of violation in *report* that *against* does not have.

### check

```python
def check(harvest: Path, db: Path, out: Path,
          against: Optional[Path] = None, profile=None) -> list
```

Why the graph of *harvest* cannot be written as the run would write
it; empty when it can.

### main

```python
def main(argv: Optional[list] = None) -> int
```

[Back to the index](../README.md)
