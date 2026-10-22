# docpipe.extraction.archive

`docpipe/extraction/archive.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

archive.py: A harvest or stamp file is never overwritten. Before one is
replaced, the file as it was is copied to

    <its directory>/archive/<pass>-<run start>/<its name>

once per run: a pass that rewrites a stamp three times keeps the stamp it
found, which is the one that says what the harvest was before the pass. The
archive sits beside the harvest and not in it, so the readers that list a
harvest directory (`*.jsonl`, `*.stamp.json`) never see it.

A pass that went wrong is then undone by copying its archive back; the
read-to-the-end pass of 2026-10-22 rewrote five plans in place and their
earlier state had to be fetched from another machine.

## Functions

### begin

```python
def begin(pass_name: str) -> None
```

Name the pass this process runs, before it writes anything.

### folder

```python
def folder(directory: Path) -> Path
```

Where this run keeps what it replaces in *directory*.

### keep

```python
def keep(path) -> Optional[Path]
```

Copy *path* into this run's archive before it is replaced. Returns the
copy, or None when there is nothing yet to keep. A file this run already
kept is left as it was kept.

[Back to the index](../README.md)
