# scripts.harvest_compare

`scripts/harvest_compare.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

harvest_compare.py – What a harvest is worth, without a GPU.

Two harvests of the same plans differ in ways a log line cannot show. This
reads the JSONL a run wrote, puts it through the profile's own serializer and
prints the numbers a decision is made on: how many tuples survived into the
graph, how many were lost to a contested identity, which coordinate is still
open how often, and what the run cost in requests. Run it on the old
directory and on the new one and the diff is the answer.

It never loads a model and never touches the index. The one thing it needs
besides the harvest is the document database, because value IRIs are minted
from a plan's AGS and publication date.

A truth file is optional and is how a claim about a plan gets checked:
{"\_comment": "read off the plan by hand",
 "years":     {"87457": 2040, ...},
 "scenarios": {"87438": "status_quo", ...}}
Coordinate at the top, then owner id to the value the plan really states, and
the report says how often the harvest agrees. Keys are strings because JSON
has no int keys, and a key starting with an underscore is prose, not a
coordinate.

No document level: an owner id is a Tables row of the database and unique
across the corpus, so a claim about one plan matches nothing in another and
the file is checked against every harvest in the directory. This paragraph
used to show a document name around it, the caller believed the docstring
over the file, and the measurement it feeds printed "keine Ernte" on every
run from 1f609f8 until it was noticed on the M3 acceptance run.

    python scripts/harvest_compare.py data/extraction/corpus data/KWP.db
    python scripts/harvest_compare.py <dir> <db> --truth kassel_truth.json

Author: Felix Vossel

## Functions

### read_harvest

```python
def read_harvest(path: Path) -> tuple
```

(tuples, refusals, summary, parameter_lines) of one document's JSONL.

The summary is the file's own last line and is neither: counting it as a
refusal would add one to every document's refusal count, and the ratio
that is read off it is the one this whole report exists for. The same
holds for the parameter_state lines, and there is one per parameter of
the spec, so an `else` that swept them into the refusals would report
fourteen model errors per ar6 document that nobody made.

### serialize_counts

```python
def serialize_counts(serializer, name: str, tuples: list, records: list) -> dict
```

Run the profile's serializer and pick the skip counts out of its log.

The counts live in a closure and reach the outside only as a log line, so
the line is captured rather than the function rewritten: the serializer
stays the one the corpus run uses, which is the whole point of measuring
with it.

### trace_costs

```python
def trace_costs(directory: Path, name: str) -> dict
```

Requests, milliseconds and windows of one document's trace.

### agreement

```python
def agreement(tuples: list, truth: dict) -> dict
```

How often a coordinate matches what the plan really states.

Keyed by owner, so it says nothing about tuples from owners the truth file
does not mention: a claim about twelve tables is checked on those twelve
and the rest is reported as untested rather than counted as right.

### truth_report

```python
def truth_report(files: list, truth: dict) -> list
```

The lines comparing a harvest against what the plan really states.

Over EVERY harvest file, because a truth entry is keyed by owner id and
those are Tables rows of the database, unique across the corpus: a claim
about one plan matches nothing in another. The caller used to read the
truth file's top level as DOCUMENT names -- it is coordinate names -- and
looked for `years.jsonl` and `scenarios.jsonl`. So it printed "keine
Ernte" on every run since 1f609f8 and the acceptance measurement it feeds
has never once been made.

Its own function rather than a block inside `main`, because that is what
let it go unseen: `agreement` had a test and the glue calling it had none.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
