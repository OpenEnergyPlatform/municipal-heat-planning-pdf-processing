# docpipe.extraction.evaluate

`docpipe/extraction/evaluate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

evaluate.py: Holds a harvest against what people decided about it.

    docpipe evaluate HARVEST_DIR --gold gold.jsonl
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --baseline OTHER_DIR
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --min-precision 0.9

Precision is counted field by field over the rows somebody decided
(`gold.py`): of the values, units and coordinates a person looked at, how
many does the document say. Recall is counted only over the documents
somebody read whole for a parameter: of the values the document states,
how many does the harvest carry.

Every share comes with its 95 percent interval (Wilson). Forty decided
rows with two wrong are 95 percent, and anything between 84 and 99: a
change that moves precision inside that range has shown nothing, and the
interval is what says so. What nobody decided is counted as undecided and
is in no share.

The numbers are split by parameter, by the level the harvest gave a value
(`trust.py`) and by where it was read (text, table or figure), because
those are the splits a decision hangs on: whether level C may be left out
of a graph is a question about the precision of level C.

`--baseline` holds a second harvest of the same documents beside this one,
row by row: which rows both carry, which only one does, and what was
decided about those. That is the comparison a replayed run is made for.

Nothing here writes into a harvest or decides anything about a value.

Author: Felix Vossel

## Classes

### Count

```python
class Count
```

How many of something were decided correct, wrong, or not at all.

#### Count.\_\_init\_\_

```python
def __init__(self)
```

#### Count.add

```python
def add(self, verdict: Optional[str]) -> None
```

#### Count.decided

```python
@property
def decided(self) -> int
```

#### Count.share

```python
@property
def share(self) -> Optional[float]
```

#### Count.as_dict

```python
def as_dict(self) -> dict
```

## Functions

### wilson

```python
def wilson(hits: int, total: int, z: float = Z95) -> Optional[tuple]
```

The interval the true share lies in, given *hits* of *total*.

### row_verdict

```python
def row_verdict(verdicts: dict) -> Optional[str]
```

One row from its fields: wrong as soon as one field is, correct
once every field was decided and none is wrong.

### evaluate

```python
def evaluate(rows_by_document: dict, gold: golden.Gold, *,
             transcribed: Sequence[str] = ()) -> dict
```

The report of one harvest. *transcribed* names the documents whose
pages a model transcribed: their values are level B at best.

### compare

```python
def compare(rows_by_document: dict, baseline: dict,
            gold: golden.Gold) -> dict
```

This harvest beside another of the same documents, row by row.

A row is the same row when its document, its name and its parameter
are. Where several rows of a document share a name, those that read
the same in every field are paired first, and what is left on both
sides is a row read differently. What only one harvest carries is
counted with what was decided about its value: a row that was correct
and is gone is a loss, one that was wrong and is gone is not.

### render

```python
def render(report: dict, comparison: Optional[dict] = None) -> str
```

### below

```python
def below(report: dict, min_precision: Optional[float],
          min_recall: Optional[float]) -> list
```

What the report falls short of. A share nobody can count (nothing
decided, nothing read whole) falls short of a floor that was asked
for: a floor that passes on no evidence is not one.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
