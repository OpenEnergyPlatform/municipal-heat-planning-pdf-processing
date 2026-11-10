# docpipe.editor.flow

`docpipe/editor/flow.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

flow.py: A profile's flow for the editor: its steps as a diagram shows them,
its numbers with where each comes from, the check of edited numbers and what
a save writes.

The flow itself is the run's (`extraction.flow`): its file, its strict
reading, the numbers a run takes and the settings that win over them. This
module only turns it into what the page draws and decides what a save does
to the profile's own file:

- `view`: every number with its value, whether the profile sets it itself,
  what it inherits and what a run started here would read with; every step
  with its bound cut into texts and numbers, the prompt of the request it
  asks, why this profile never takes it (`off`), and the switches of the
  spec that belong to it, each entry a link into the spec.
- `judge`: whether edited numbers are numbers of the flow, what changes and
  what the profile's file would then be. A profile that extends another
  writes only the numbers that differ from what it inherits, so a number
  set back leaves the file, and a file that would hold none is removed.
- `save`: `judge`, and the bytes to write where it holds.

No file is read here but through the run's loader; the server checks every
path first and hands in the bytes of the profile's own file.

Author: Felix Vossel

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### view

```python
def view(profile, own_raw: Optional[bytes], data: Optional[dict],
         shown: Callable, computes: bool = False) -> dict
```

The flow of *profile* as the page draws it (see the module's head).
*own_raw* are the bytes of the profile's own flow file, None where it
has none; *data* its spec as written, None where it has none;
*shown(path)* a path as the user sees it; *computes* whether the
profile computes.

### judge

```python
def judge(profile, own_raw: Optional[bytes], numbers, name: str) -> dict
```

What a save of *numbers* ({name: value}, those not named as the
files say them) would do: {"ok", "errors": [{"name", "message"}],
"changed": [{"name", "from", "to"}], "file", "writes" ("created",
"changed", "removed", "unchanged"), "diff", "says", "text"}. *text* is
the profile's file as it would stand, in the line ends it has (plain
ones where it is new), None where it would be removed. *name* is the
file as the user sees it.

### save

```python
def save(profile, own_raw: Optional[bytes], numbers, base: Optional[str],
         name: str) -> tuple
```

(what the page is told, the bytes to write or None, whether the
file is to be removed). Bytes come back only for numbers the flow
takes, and only where the file is as the page loaded it (*base*, the
sha256 of its bytes, None where it had none).

[Back to the index](../README.md)
