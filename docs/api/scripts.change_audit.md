# scripts.change_audit

`scripts/change_audit.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

change_audit.py – What this change touches that is not in the files it changes.

Every defect this repo lost a GPU run to had the same shape: the change was
correct inside the file it was written in, and wrong about something outside
it. A lock was put around the memo dicts and not the MuPDF call. A guard was
added to the carrier edge and not the sector edge. Resume stamps were deleted
to force a redo, and the code that reads them treats a missing stamp as "done"
— 165 documents skipped, the job exited 0.

None of those needed cleverness to catch. They needed someone to read the
other end. That is mechanical, so it is done here rather than remembered:

  siblings   a name this change touches that other places also use
  consumers  a literal this change writes that other files read
  untested   a function this change adds or moves that no test names

What it cannot check is the shape that needs judgement — a guarantee written
in a docstring and half implemented. "The quote sits in the source AND carries
the answer" is two clauses and was one check; no tool reads that. The rule for
it is in the procedure, not here: one clause, one assertion, and a case that
violates it by construction.

Usage:
    python scripts/change_audit.py                 # working tree against HEAD
    python scripts/change_audit.py HEAD~1..HEAD    # one commit

Author: Felix Vossel

## Functions

### changed

```python
def changed(spec: str | None) -> tuple
```

(files touched, lines added) for a commit range or the working tree.

### siblings

```python
def siblings(written: set, added: list) -> dict
```

Names this change touches that other places also use.

### consumers

```python
def consumers(written: set, added: list) -> dict
```

Literals this change writes that other files read.

The check that would have caught the resume defect: recheck.py deleted
*.stamp.json, and already_done reads that name to decide whether a
document needs work.

### untested

```python
def untested(added: list) -> list
```

Functions this change adds that no test file names.

### report

```python
def report(spec: str | None = None) -> int
```

[Back to the index](../README.md)
