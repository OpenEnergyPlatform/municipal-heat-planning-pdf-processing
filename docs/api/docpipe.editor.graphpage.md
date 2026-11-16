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
  class the groups of properties one of which the shapes demand of a node
  (an sh:or on the node) with that constraint and its effect, whether the
  class is written and its address rule; the rules the writer declares,
  each with its value, what it inherits and the setting that wins over it.
- `judge` and `save`: an edited graph file, read by the run's own parser.
  A profile that extends another writes only what differs from what it
  inherits, and the rules its writer reads.
- the drawing: `view` also returns `map` (how the harvest becomes the
  graph, `graphfile.get_map`), the fields of the harvest as the spec asks
  them (with a real example of each where a harvest is loaded), the bricks
  the run knows and the harvest's documents. `judge` holds an edited drawing
  to the run's own checks (`graphfile.map_problem`, `graph.check`) and
  names the box or arrow each problem is about. `preview` writes one
  document of the harvest as the edited drawing says.
- the blocks (owner request 2026-11-14, wish 4): `view` also returns the
  presets, blocks ready to put in where a brick stands, and what a
  condition of the graph can be about; `try_block` writes one document as
  the edited drawing says and shows what one block of it was given and
  gave, reading by reading.
- `probe`: the graph of the harvest the page was given, written twice into
  the temp directory, with the saved file and with the edited one, and what
  differs: per document the nodes kept and left out, per constraint its
  violations, the nodes named anew. No model is asked and nothing is saved.

Author: Felix Vossel

## Classes

### PreviewError

```python
class PreviewError(ValueError)
```

What stops a preview; the sentence is the page's to show.

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### curie

```python
def curie(iri, prefixes: dict) -> str
```

*iri* as a prefixed name of *prefixes* (the longest namespace wins),
else as \<iri>.

### classes

```python
def classes(profile, made, spec_raw: Optional[dict], files: list,
            snapshot: Optional[dict],
            prefixes: Optional[dict] = None) -> dict
```

{"classes": [...], "skipped": why or None}: the shapes' classes with
their properties and the constraints; per class also the groups of
properties one of which the shapes demand of a node (an sh:or on the
node, `Shape.one_of`), each as the curies of its properties, and that
constraint with its effect.

### view

```python
def view(profile, own_raw: Optional[bytes], shown,
         spec_raw: Optional[dict] = None, files: list = (),
         snapshot: Optional[dict] = None, spec=None,
         harvest: Optional[Path] = None) -> dict
```

### fields

```python
def fields(spec, drawing: dict) -> list
```

The fields of the harvest as the spec asks them, in spec order: one
per parameter; then the dimensions of the numbers a box of one node per
number reads, as fields of their own (unit, carrier, sector, year, ...),
and what a reading carries of itself (`ROW_KEYS`). A dimension or a
reading the drawing names is a field wherever it comes from.

### bricks_of

```python
def bricks_of(profile) -> list
```

### python_of_block

```python
def python_of_block(profile, ref, kind) -> dict
```

A block of the drawing as the Python of a block that does the same,
for the page to show when the form "Python" is chosen:
{"python", "per", "writes"}; {"python": ""} where *ref* is no block of
*kind* or a step's source is not to be had.

### presets_of

```python
def presets_of(profile) -> list
```

The blocks ready to put in where a brick stands, the core's and the
profile's own (`bricks.presets`): {name, kind, does, block, own}.

### graph_conditions

```python
def graph_conditions() -> list
```

What a condition of the drawing can be about (`conditions.catalogue`
with graph): the reading by its keys, what is known of the document.

### harvest_documents

```python
def harvest_documents(harvest: Optional[Path]) -> list
```

The documents of a harvest folder, by name.

### examples

```python
def examples(harvest: Path, names: list, lay: list) -> dict
```

{field: {"value", "document"}}: the first reading of each field a
document of the harvest has, a real one. A parameter is read off the
rows of its own, a dimension or a reading off any row.

### own_of

```python
def own_of(profile, data: dict) -> dict
```

What *profile*'s own file holds of *data* (the whole file as the page
has it): what differs from what it inherits, and the rules its writer
reads, which its file starts from where it declares them. The drawing
is one piece: it is the profile's own where it differs from what the
line below has.

### located

```python
def located(message: str, drawing: dict) -> dict
```

{"box", "arrow", "message"}: what a sentence of the checks of a
drawing is about, the box by its id and the arrow by the name the run
gives it (`graph.arrow_key`); None where it is about neither.

### drawing_problems

```python
def drawing_problems(profile, drawing: dict, spec=None) -> list
```

The sentences of the run's own checks of *drawing* against the spec,
the shapes and the bricks (`graph.check`); the shape of the drawing
itself is `graphfile.map_problem`, held by `graphfile.parse`.

### judge

```python
def judge(profile, own_raw: Optional[bytes], data, name: str,
          spec=None) -> dict
```

What a save of *data* ({"classes", "constraints", "rules", "map"},
the whole file as the page has it) would do. A problem of the drawing
is in `problems` with the box or arrow it is about.

### save

```python
def save(profile, own_raw: Optional[bytes], data, base: Optional[str],
         name: str, spec=None) -> tuple
```

(what the page is told, the bytes to write or None, whether the file
is to be removed).

### preview

```python
def preview(profile, data, harvest: Optional[Path], document,
            db: Optional[Path] = None, strict: bool = False,
            spec=None, root: Optional[Path] = None) -> dict
```

One document of *harvest* written as *data* (the graph file as the
page has it, drawing and rules) says, with the run's own program, into
no file of the profile: {"document", "text", "triples", "nodes"}. No
model is asked; the rows are the harvest's.

### block_at

```python
def block_at(drawing: dict, where: dict) -> tuple
```

(the block, the kind it is) at *where* of *drawing*: {"document":
key, "index"}, {"box": id, "key", "index"} or {"arrow": number from 1}.
An arrow's brick is made a block of its own first, so it stays the one
object the writer is given.

### try_block

```python
def try_block(profile, data, harvest: Optional[Path], document, where,
              db: Optional[Path] = None, strict: bool = False, spec=None,
              root: Optional[Path] = None) -> dict
```

One document written as *data* says, and what the block at *where*
was given and gave each time it was called, the first `TRIED_MOST`:
{"document", "kind", "calls", "shown": [{"reading", "gives"}]}; for an
address made of parts, each number's parts and its address. Nothing is
saved and no model is asked.

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
