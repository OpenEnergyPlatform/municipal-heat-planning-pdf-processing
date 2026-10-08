# docpipe.extraction.evaluate

`docpipe/extraction/evaluate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

evaluate.py: Holds a harvest against what people decided about it.

    docpipe evaluate HARVEST_DIR --gold gold.jsonl
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --baseline OTHER_DIR
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --min-precision 0.9
    docpipe evaluate HARVEST_DIR --diff OTHER_DIR
    docpipe evaluate HARVEST_DIR --diff OTHER_DIR --top 10 --max-gone 0.05

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

`--diff` needs no decisions. It holds this harvest against another one of
the same documents, OTHER_DIR being the baseline, and says what changed:
per parameter and per field (the value, the unit, each coordinate) how
many rows are the same, read differently, gone (only the baseline has
them) and new (only this harvest has them); how the states of the
coordinates of the rows both carry moved (read to unbacked, counted in
coordinates); how their trust levels moved; and the largest changes, each
with its quote and both readings side by side. Rows are paired as
`--baseline` pairs them, by document, `identity.tuple_id` and parameter. It
exits with 0 whatever it finds; only a ceiling (`--max-changed`,
`--max-gone`, shares of the baseline's rows) makes it exit with 1. Levels
are counted as `evaluate` counts them: a document is transcribed only if a
database (`--db`, else the profile's) says so, and the report says how many
it took as transcribed.

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

### pair_rows

```python
def pair_rows(rows_by_document: dict, baseline: dict)
```

(kind, key, row, other) for every row of two harvests.

A row is the same row when its document, its name and its parameter
are (`gold.row_key`). Where several rows of a document share a name,
those that read the same in every field are paired first, and what is
left on both sides is paired in file order as a row read differently.
What one harvest carries and the other does not is `gone` (only the
baseline has it: `other` is its row, `row` is None) or `new` (only this
harvest has it: `row` is its row, `other` is None). The order is the
same every time.

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

### diff

```python
def diff(rows_by_document: dict, baseline: dict, *,
         transcribed: Sequence[str] = (), top: int = DIFF_TOP) -> dict
```

What changed between two harvests of the same documents, without a
decision about either.

Counted in rows, except where it says coordinates or documents.
`rows` and `parameters` hold the rows that are the same, changed, gone
and new (`pair_rows`); `fields` the same for every field a row carries
(the value, the unit, each coordinate's answer), a row counted under
each field it carries; `transitions` how the states of the coordinates
of the rows both harvests carry moved; `levels` how the trust level of
those rows moved, and the level of the rows gone and new; `largest` the
*top* rows of both harvests that differ most, each with both readings.
A document is changed when one of its rows reads differently, moved in
a coordinate state or in its level, is gone or is new.

A row whose quote or written value changed is not the same row any
more: it is gone and another is new. A row that reads differently is
one whose quote and written value stand and whose unit, parsed value or
coordinates do not. One that reads the same can still have a coordinate
that moved from read to unbacked or a level that moved, and those are
counted under `transitions` and `levels`.

### render_diff

```python
def render_diff(report: dict) -> str
```

### moved_too_far

```python
def moved_too_far(report: dict, max_changed: Optional[float],
                  max_gone: Optional[float]) -> list
```

What the comparison exceeds, as shares of the baseline's rows. A
share nobody can count (the baseline has no row) exceeds a ceiling that
was asked for: a ceiling that passes on no evidence is not one.

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
