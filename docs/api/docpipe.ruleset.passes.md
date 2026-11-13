# docpipe.ruleset.passes

`docpipe/ruleset/passes.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

passes.py: The record of a run, its archive, the check before a run and the
passes after it (trace.py, stats.py, archive.py, preflight.py, topup*.py,
remap.py, recheck.py, review.py, survey.py). Every rule here is the run's: the
follow-up passes are switches of the call and no steps of the flow yet, so no
step has an own value of them. The one exception is `trace_requests`, which
each step that asks may set for itself.

## Functions

### run_value

```python
def run_value(name: str)
```

The value of the rule *name* for the whole run, whatever step asks:
for a rule no step sets, read where a step is running (the record of a
request, the archive).

[Back to the index](../README.md)
