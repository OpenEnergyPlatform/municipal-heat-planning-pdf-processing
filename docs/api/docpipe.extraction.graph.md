# docpipe.extraction.graph

`docpipe/extraction/graph.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

graph.py: Writes a harvest as the graph a compiled spec describes.

`docpipe compile` drafts a spec from the shapes of a graph, and with it
what each answer becomes there: the `graph` block names the nodes and how
they are linked, and every parameter's `kg` names the node and the property
its value is written to. That is everything a writer needs, so a project
whose spec was compiled needs no writer of its own. A profile that has one
(`kg.make_serializer`) keeps it: its graph knows things no shape says.

What is written, per document:

    a node per document   one of each node the block declares as
                          `per: document`, at <base><node>/<document name>,
                          once it carries something
    a property            the value of a parameter on its node: a literal
                          of the property's datatype, or the term chosen
                          from the parameter's list (`object: term`)
    a named thing         a node of its own for a value that names one
                          (`edge_from`), at <base><node>/<its wording>, with
                          that wording under the parameter's property, and
                          the edge to it
    a link                between two nodes that are both there

Three things are left out and counted in the log, none silently:

  * a parameter with coordinates. Where a year or a scenario of a value
    goes is not something the block says, and written onto the node without
    them two values of two years would be one property with two numbers.
  * a property that allows fewer values than the harvest has for it
    (`max`). The values of the best trust level are taken; if those are
    still too many, none is written, because picking one would be a guess.
    A value that is left out leaves no node of its own behind either.
  * an answer that is not a term where a term has to be written.

Author: Felix Vossel

## Classes

### GraphError

```python
class GraphError(ValueError)
```

A spec that does not describe a graph this writer can write.

### Names

```python
class Names
```

Prefixed names and IRIs of one spec, as IRIs.

#### Names.\_\_init\_\_

```python
def __init__(self, prefixes: dict)
```

#### Names.iri

```python
def iri(self, name) -> Optional[str]
```

The IRI a prefixed name or an IRI stands for, or None.

#### Names.predicate

```python
def predicate(self, described: dict) -> Optional[str]
```

## Functions

### ttl_string

```python
def ttl_string(text) -> str
```

A text as a Turtle string literal, quotes included.

### slug

```python
def slug(text) -> str
```

What a wording becomes in an IRI: the same for the same name written
with other spacing or capitals.

### make_serializer

```python
def make_serializer(raw: dict) -> Callable
```

(document name, accepted rows) -> Turtle or None, for a spec with a
`graph` block. Raises GraphError when the block cannot be written
from.

[Back to the index](../README.md)
