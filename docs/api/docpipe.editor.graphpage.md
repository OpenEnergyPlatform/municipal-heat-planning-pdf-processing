# docpipe.editor.graphpage

`docpipe/editor/graphpage.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

graphpage.py: How a profile's harvest becomes its graph, as `docpipe edit`
shows and sets it (owner, 2026-11-10: "sodass man steuern kann, wie die
Ernte in den Graphen aufgenommen wird und welche constraints erfüllt sein
müssen").

The file and what it does are the run's (`docpipe.graphfile`); the shapes
are the ones the profile's last refresh pulled. This module turns them into
what the page draws and decides what a save writes:

- `view`: every class of the shapes with its properties, each with the
  fields that write it, its constraints (required, at most so many, a closed
  list, a class, a datatype) and the effect the graph file gives each; per
  class whether it is written and its address rule; the rules the writer
  declares, each with its value, what it inherits and the setting that wins
  over it.
- `judge` and `save`: an edited graph file, read by the run's own parser.
  A profile that extends another writes only what differs from what it
  inherits, and the rules its writer reads.
- `probe`: the graph of the harvest the page was given, written twice into
  the temp directory, with the saved file and with the edited one, and what
  differs: per document the nodes kept and left out, per constraint its
  violations, the nodes named anew. No model is asked and nothing is saved.

Author: Felix Vossel

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### classes

```python
def classes(profile, made, spec_raw: Optional[dict], files: list,
            snapshot: Optional[dict]) -> dict
```

{"classes": [...], "skipped": why or None}: the shapes' classes with
their properties, the fields that write each and the constraints.

### view

```python
def view(profile, own_raw: Optional[bytes], shown,
         spec_raw: Optional[dict] = None, files: list = (),
         snapshot: Optional[dict] = None) -> dict
```

### own_of

```python
def own_of(profile, data: dict) -> dict
```

What *profile*'s own file holds of *data* (the whole file as the page
has it): what differs from what it inherits, and the rules its writer
reads, which its file starts from where it declares them.

### judge

```python
def judge(profile, own_raw: Optional[bytes], data, name: str) -> dict
```

What a save of *data* ({"classes", "constraints", "rules"}, the whole
file as the page has it) would do.

### save

```python
def save(profile, own_raw: Optional[bytes], data, base: Optional[str],
         name: str) -> tuple
```

(what the page is told, the bytes to write or None, whether the file
is to be removed).

### probe_root

```python
def probe_root() -> Path
```

### compare

```python
def compare(before: dict, after: dict) -> dict
```

What the edited file does against the saved one, per document and
per constraint.

### probe

```python
def probe(profile, data, harvest: Path, db: Path,
          root: Optional[Path] = None, stamp: str = "") -> dict
```

The graph of *harvest* written with the saved graph file and with
*data*, into a folder of *root*; what differs.

[Back to the index](../README.md)
