# docpipe.extraction.scratch

`docpipe/extraction/scratch.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

scratch.py: Where a column of one's own lives, and why its harvest stays there.

A column of one's own is a spec of one parameter that no profile holds,
harvested over a few documents to see what the plans say. Its harvest is
written like every other: a JSONL per document with a stamp beside it, the
anchors, a query cache. A stamp is compared with the spec the run reads, so a
folder that holds the harvests of two specs reads as stale for one of them,
and a forced run of the one overwrites the files of the other. So the folder
is the column's own: a run that takes its spec from a file writes only below
the folder that file lies in, and never into the harvest of a profile.

The folder holds, under these names, what the commands in turn leave there:

    draft.json   `docpipe column` writes it, `docpipe compile examples`
                 proposes its example, `docpipe compile apply` carries the
                 accepted one over
    spec.json    what `compile apply --out` writes once nothing is open
    harvest/     `docpipe extract --spec spec.json`, its stamps and anchors
    values.csv   `docpipe export harvest`, if one asks for the table there

Nothing in the folder is meant for the graph. Nothing here hands it to the
serializer, and no run that reads its spec from a file serializes.

Author: Felix Vossel

## Functions

### folder_problem

```python
def folder_problem(spec_file, out) -> Optional[str]
```

Why a run that reads *spec_file* may not write into *out*, or None.

*out* has to lie below the folder of the spec file and not in it, so the
harvest has a folder of its own beside the spec, the draft and the
proposals. A profile's harvest lies elsewhere, so a run that took its
spec from a file cannot reach it, forced or not.

[Back to the index](../README.md)
