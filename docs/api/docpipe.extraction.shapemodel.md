# docpipe.extraction.shapemodel

`docpipe/extraction/shapemodel.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

shapemodel.py: The graph a writer produces, as the shapes it is held to say.

A serializer used to carry the shapes a second time: the paths it writes,
which of them may occur once, which must occur at all and what class sits at
the end of each. Copied by hand, every one of those drifted from the file it
was copied from, and a shapes file that moved on was only noticed in a
validation report nobody had to read.

Here the shapes the last refresh pulled are read when the writer is built,
and the writer asks them: which property of this class leads to nodes of
that class, or takes entries of that list, or values of that datatype; how
often may it occur, must it. A question with no answer, or with two, is a
`SchemaError` and never a default: a path the shapes no longer have stops
the writer before it produces a graph, which is what a renamed or dropped
property looks like from here.

What is read is what `docpipe.compile.shapes` reads: one record per
property shape with a single path. Several shapes on one class (a generated
file and a hand-written one beside it) are one set of constraints, and
several property shapes on one path are one slot with the tightest bounds.

Author: Felix Vossel

## Classes

### SchemaError

```python
class SchemaError(ValueError)
```

The shapes do not answer what a writer asks of them.

### Slot

```python
@dataclass(frozen=True)
class Slot
```

One property of a class, as every shape on that class constrains it.

Fields:

- `path: str`
- `min_count: int = 0`
- `max_count: Optional[int] = None`
- `classes: tuple = ()`
- `choices: tuple = ()`
- `datatype: Optional[str] = None`

#### Slot.required

```python
@property
def required(self) -> bool
```

#### Slot.single

```python
@property
def single(self) -> bool
```

### Model

```python
class Model
```

What the shapes say about each class they target.

*ancestors* gives the classes above a class, nearest first, as full
IRIs. A class no shape targets is held to the nearest one above it that
a shape does target, so a CO2 emission value finds the shape of the
greenhouse gas emission value it is one of.

#### Model.\_\_init\_\_

```python
def __init__(self, shapes: list,
             ancestors: Optional[Callable[[str], Iterable[str]]] = None)
```

#### Model.load

```python
@classmethod
def load(cls, paths, ancestors=None) -> "Model"
```

From shapes files on disk.

#### Model.from_graph

```python
@classmethod
def from_graph(cls, graph, ancestors=None) -> "Model"
```

From shapes already parsed into an rdflib graph.

#### Model.parse

```python
@classmethod
def parse(cls, *texts: str, ancestors=None) -> "Model"
```

From Turtle text, one or several files' worth.

#### Model.classes

```python
def classes(self) -> list
```

#### Model.shaped

```python
def shaped(self, cls: str) -> Optional[str]
```

*cls* if a shape targets it, else the nearest class above it one
does, else None.

#### Model.slots

```python
def slots(self, cls: str) -> dict
```

{path: Slot} of the shape *cls* is held to; empty without one.

#### Model.has

```python
def has(self, cls: str, path: str) -> bool
```

#### Model.slot

```python
def slot(self, cls: str, *, path: Optional[str] = None,
         to_class: Optional[str] = None, members: Iterable = (),
         datatype: Optional[str] = None) -> Slot
```

The one property of *cls* that answers the question.

By its path; by the class at its end (*to_class* or a class above
it); by the entries of its list (the slot whose sh:in holds the most
of *members*); by its datatype. Several criteria narrow together.

## Functions

### snapshot_ancestors

```python
def snapshot_ancestors(snapshot: dict, base: str) -> Callable
```

`ancestors` over a vocabulary snapshot, nearest first, as IRIs.

The snapshot names terms by their bare id and its parents the same way;
*base* is the namespace a bare id stands in.

[Back to the index](../README.md)
