# docpipe.\_revision

`docpipe/_revision.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

\_revision.py: The commit this code is.

`git archive` writes the commit into `REVISION` (`export-subst` in
.gitattributes), so code laid over an image from an archive knows which
commit it is, whatever the archive or the image is called (owner decision
2026-11-14: the trace of a run says which code wrote it). In a checkout the
placeholder stays and git is asked.

Author: Felix Vossel

## Functions

### revision

```python
def revision() -> str
```

The commit of this code, "" where neither the archive nor git says.

[Back to the index](../README.md)
