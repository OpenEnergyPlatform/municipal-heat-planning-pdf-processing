# docpipe.compile.draft

`docpipe/compile/draft.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

draft.py: An extraction spec drafted from shapes and an ontology, and what
an existing spec says differently.

One property shape becomes one parameter. What the shapes and the ontology
state is carried over as it stands: the closed list with the ontology's own
labels, other names and definitions, the datatype, how many values there may
be, and which node of the graph a value belongs to. What they cannot state
is left open and listed: how a document words a term, what a number's unit
is, and the one real example every parameter needs. A draft is therefore
not a spec yet. `todo` says what is missing, and `spec.load` stays the judge
of the finished file.

For a number's unit the draft only suggests. The units a shape lists itself
and the unit family the ontology gives the shape's class hang on the number
under `_drafted`, and `todo` names them; `units_accepted` and the factors
between the entries stay the author's to write.

The same reading, held against a spec somebody wrote by hand, gives the
differences: a list entry the shapes have and the spec lacks, a property
nobody asks for, a parameter the shapes do not know. That is a report and
changes nothing.

Author: Felix Vossel

## Classes

### Names

```python
class Names
```

IRIs as the spec writes them: a prefix of the file and a local name.

#### Names.\_\_init\_\_

```python
def __init__(self, prefixes: dict)
```

#### Names.split

```python
def split(self, iri: str) -> tuple
```

(prefix, local name). A namespace no prefix is bound to gets one.

#### Names.curie

```python
def curie(self, iri: str) -> str
```

## Functions

### local

```python
def local(iri: str) -> str
```

### path_name

```python
def path_name(predicate: str) -> str
```

The end of a property's IRI, from the IRI or a prefixed name.

### slug

```python
def slug(text: str) -> str
```

### unit_listing

```python
def unit_listing(shape: Shape, unit_properties=UNIT_PROPERTIES) -> tuple
```

(the properties of this shape that list units, the properties that
are numbers). The first is empty where there is no number to hang a list
of units on.

### draft

```python
def draft(shapes: list, prefixes: dict, terms: Optional[Terms] = None, *,
          base: Optional[str] = None, sources: tuple = (),
          unit_properties=UNIT_PROPERTIES) -> dict
```

The spec these shapes ask for, as far as they and the ontology say.

A number's unit stays open: the author writes `units_accepted` and the
factors. What is known about it is hung on the parameter as a suggestion
(`_drafted`): the units the shape itself lists, which are no parameter of
their own, and the unit family the ontology gives the shape's class.

### finished

```python
def finished(raw: dict) -> dict
```

The draft as a spec: without the marks only the drafting needs.

### graph_file

```python
def graph_file(raw: dict) -> dict
```

What the draft says for the project's graph file (graph.json): the
rule `base` and the drawing, {} where it says nothing.

### todo

```python
def todo(raw: dict) -> list
```

What stands between this draft and a spec, one line each.

The lines this function can name itself, and after them whatever
`spec.load` still refuses: that is the judge, and a draft is done when
it has nothing left to say.

### drawn

```python
def drawn(drawing: Optional[dict], spec_raw: dict) -> tuple
```

What a drawing (`map` of a graph file) writes, as `differences`
holds it to the shapes: ({field: [(predicate, listed)]}, {field: the
local names of the classes of its nodes}, {(class, predicate)} every
arrow writes, {field: whether its node takes its class from a
coordinate}).

An arrow from a field, from one of its coordinates or from a key of its
reading is the field's; an arrow from a box to a box of one node per
distinct reading is the field's whose readings those are; any other
arrow between boxes, and an arrow from a box to itself, is the
drawing's structure and no field's: it only says the property is
written.

### differences

```python
def differences(shapes: list, spec_raw: dict,
                terms: Optional[Terms] = None,
                unit_properties=UNIT_PROPERTIES,
                pairs: Optional[list] = None,
                drawing: Optional[dict] = None) -> list
```

What the spec and its drawing (`map` of the graph file) say
differently from the shapes, and what one of them does not say at all.
[{kind, parameter, path, detail}], nothing changed.

A field is held against the property shape whose path an arrow of the
drawing writes for it (`drawn`). Where several shapes carry that path (a
label, on every node), the one is taken whose target class is the class
of the field's node. A node that takes its class from a coordinate is
held against the shape of every class that coordinate offers. Where that
settles nothing, the field is compared to nothing rather than to a
guess, and is listed as ambiguous only if no other property it writes
found its shape. A property no shape carries, or none of the classes its
node is written as, is named on its own. A property of the shapes no
arrow writes is `not_asked`.

An entry of a list that starts with `out:` is the profile's own word for
"none of these" and no term, so the shapes are not expected to have it.
The units a shape lists are no property to ask for where the spec asks
for the shape's number. *pairs*, where given, is filled with (field,
shape, property) for every property a field was held against.

[Back to the index](../README.md)
