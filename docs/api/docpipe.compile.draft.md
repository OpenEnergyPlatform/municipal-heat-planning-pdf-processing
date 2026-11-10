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

### todo

```python
def todo(raw: dict) -> list
```

What stands between this draft and a spec, one line each.

The lines this function can name itself, and after them whatever
`spec.load` still refuses: that is the judge, and a draft is done when
it has nothing left to say.

### field_classes

```python
def field_classes(parameter: dict, node_class: Optional[dict] = None) -> set
```

The local names of the classes a parameter's node is written as: the
classes its `kg` block names, its node's (*node_class*, as
`_node_classes` reads them), and every entry the axis it takes its class
from offers (`class_from`), an `out:` entry none.

### predicate_places

```python
def predicate_places(parameter: dict) -> list
```

[(where, block)] of every block of *parameter* that names a predicate
it writes: those of its own `kg` block and of its axes that draw an edge
from its node (`role: edge`). *where* is the tuple of keys from the
parameter to the block, the place a merge writes `also` to. A block
names its predicate with `predicate`, or with `schema_slot` where the
profile's schema says it (KWP); the blocks an `also` names are none.

### read_as_shapes

```python
def read_as_shapes(spec_raw: dict, profile=None) -> dict
```

The spec as *profile*'s shapes name its properties. A profile whose
`kg` blocks name the slots of a schema of its own says how they become
predicates (`extraction.spec_for_shapes`, KWP through the MHPKG schema);
any other spec is held to the shapes as written.

### differences

```python
def differences(shapes: list, spec_raw: dict,
                terms: Optional[Terms] = None,
                unit_properties=UNIT_PROPERTIES,
                pairs: Optional[list] = None) -> list
```

What the spec says differently from the shapes, and what one of them
does not say at all. [{kind, parameter, path, detail}], nothing changed.

A parameter is held against the property shape whose path its `kg` block
names. Where several shapes carry that path (a label, on every node),
the one is taken whose target class the block names, or the node of the
block is of. A block whose node takes its class from an axis
(`class_from`) is held against the shape of every class that axis
offers, as `ontology.spec_edges` reads it. Where that settles nothing,
the parameter is compared to nothing rather than to a guess, and is
listed as ambiguous only if no other predicate of its block found its
shape. A predicate no shape carries, or none of the classes its node is
written as, is named on its own.

An entry of a list that starts with `out:` is the profile's own word for
"none of these" and no term, so the shapes are not expected to have it.
The units a shape lists are no property to ask for where the spec asks
for the shape's number. *pairs*, where given, is filled with (parameter,
shape, property) for every property a parameter was held against.

[Back to the index](../README.md)
