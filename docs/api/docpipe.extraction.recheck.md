# docpipe.extraction.recheck

`docpipe/extraction/recheck.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

recheck.py: Reapplies the answer-in-quote rule to a harvest written before
the rule existed.

A coordinate is only as good as the passage cited for it. For one corpus run,
that passage was checked against the wrong thing: `merge_field` held it to
sitting verbatim in the source, never to containing the answer. In that run,
27.6% of the years cite a passage that contains no year at all; one of them is
a table caption listing existing heat networks and heating plants, offered as
evidence for the year 1990.

Both halves of a coordinate are already in the harvest file, the wording in
`<axis>_raw` and the passage in `<axis>_quote`, so the rule can be applied to
what is written without asking a model anything. Keeping the evidence next to
the claim is what makes this possible: a rule that tightens later can still be
enforced on an earlier harvest.

The pass cannot fill a coordinate it drops. A dropped coordinate is one the
next run has to read again, and it is marked so that the difference between the
plan not stating a value and the last run not having checked it stays visible
instead of collapsing into an empty cell.

Author: Felix Vossel

## Functions

### recheck_row

```python
def recheck_row(row: dict, slots: list) -> Counter
```

Strip every coordinate of one tuple whose quote does not carry it.

### recheck_file

```python
def recheck_file(path: Path, spec: Spec) -> Counter
```

Rewrite one harvest file in place. Returns what it dropped and why.

The summary line is recomputed rather than carried over: it counts the
trust levels of the tuples above it, and this pass is in the business of
demoting them. A kept summary would report the run that no longer exists.

### run

```python
def run(harvest_dir: Path, spec: Spec, *, drop_stamps: bool = True) -> Counter
```

Recheck a whole harvest directory.

The stamps go with it. A file rewritten by a rule the harvest did not
apply is not the output of the run its stamp names, and leaving the stamp
would make the next run skip the document — which is exactly how 205 plans
kept a whole-tuple harvest through a field-wise corpus run.

[Back to the index](../README.md)
