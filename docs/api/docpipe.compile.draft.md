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

### draft

```python
def draft(shapes: list, prefixes: dict, terms: Optional[Terms] = None, *,
          base: Optional[str] = None, sources: tuple = ()) -> dict
```

The spec these shapes ask for, as far as they and the ontology say.

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

### differences

```python
def differences(shapes: list, spec_raw: dict,
                terms: Optional[Terms] = None) -> list
```

What the spec says differently from the shapes, and what one of them
does not say at all. [{kind, parameter, path, detail}], nothing changed.

A parameter is held against the property shape whose path its `kg` block
names. Where several shapes carry that path (a label, on every node),
the one is taken whose target class the block names, or the node of the
block is of. Where that settles nothing, the parameter is compared to
nothing rather than to a guess, and is listed as ambiguous only if no
other predicate of its block found its shape.

An entry of a list that starts with `out:` is the profile's own word for
"none of these" and no term, so the shapes are not expected to have it.

[Back to the index](../README.md)
