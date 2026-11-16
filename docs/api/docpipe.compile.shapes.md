# docpipe.compile.shapes

`docpipe/compile/shapes.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

shapes.py: What SHACL shapes say about a graph, read into plain records.

A shapes file states which nodes a graph has (a node shape and its target
class), which properties each carries (a property shape and its path), what
a value may be (a datatype, a class, a closed list) and how many there may
be. That is most of an extraction spec, written once already by whoever
maintains the graph. This module reads it and decides nothing: the records
say what the file says, and `draft.py` turns them into a spec.

A node shape may also say "one of these properties at least": an sh:or on
the node whose alternatives each name one property with sh:minCount. That
is read as a group (`Shape.one_of`), since none of its properties is
required on its own and one of them is.

What a shape says in a way this reader does not follow (a path that is no
single property, a constraint only SPARQL states, an sh:and, sh:xone or
sh:not on the node, an sh:or on the node of another form) is kept as a note
on the record, so the draft can say what it left out.

rdflib is imported where it is used, as in `docpipe.ontology`.

Author: Felix Vossel

## Classes

### Property

```python
@dataclass
class Property
```

Fields:

- `path: str`: the property's IRI
- `datatype: Optional[str] = None`: IRI of an XSD type
- `choices: list = field(default_factory=list)`: sh:in, as written
- `choices_are_terms: bool = False`: IRIs, as opposed to literals
- `classes: list = field(default_factory=list)`: sh:class, sh:or of them
- `node: Optional[str] = None`: sh:node: the shape of the object
- `min_count: Optional[int] = None`
- `max_count: Optional[int] = None`
- `name: Optional[str] = None`: sh:name
- `description: Optional[str] = None`: sh:description
- `notes: list = field(default_factory=list)`

### Shape

```python
@dataclass
class Shape
```

Fields:

- `iri: str`: "" for a shape without a name
- `name: str`
- `target_class: Optional[str] = None`
- `properties: list = field(default_factory=list)`
- `one_of: list = field(default_factory=list)`: [[property IRI]]: per sh:or on the node, the properties one of which a node must have at least once
- `notes: list = field(default_factory=list)`

## Functions

### read

```python
def read(paths) -> tuple
```

(shapes, {prefix: namespace}) of the files at *paths*.

### shapes_of

```python
def shapes_of(graph) -> list
```

[Back to the index](../README.md)
