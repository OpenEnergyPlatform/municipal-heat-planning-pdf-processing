# docpipe.graphfile

`docpipe/graphfile.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

graphfile.py: How a harvest becomes the graph, read from a file of the
profile (owner, 2026-11-10: "sodass man steuern kann, wie die Ernte in den
Graphen aufgenommen wird und welche constraints erfüllt sein müssen").

    <profile folder>/graph.json

    {"classes": {class: {"written": false} |
                        {"address": {"folder": ..., "key": [property, ...],
                                     "base": ...}}},
     "constraints": {"<constraint> <property> <class>": effect},
     "rules": {name: value}}

What a writer does stays code (`profiles/<name>/kg.py`); the file says what
the writer is to do with it:

- a class that is not written: its nodes, and every triple that names them,
  leave the written graph;
- an address rule: the nodes of the class are named anew, the folder under
  the writer's base and a UUID over the values of the named properties, and
  every triple that names them follows;
- a constraint's effect, after the written graph is held to the shapes:
  `report` (what every constraint does where the file says nothing),
  `leave_out_value` (the node the violation is about leaves the graph),
  `leave_out_paper` (every node of its document does) or `stop` (the gate,
  `docpipe.extraction.gate`, shuts before a job starts its model);
- the rules a profile's writer declares (`rules.py: GRAPH`), each read by the
  writer where it applies it.

A class is named by its identifier (`OEO_00030022`), a property by its
identifier or `prefix:name`, a constraint by the words the validation
reports it with (`MinCount OEO_00390079 OEO_00020227`: the constraint, the
property, the class of the node). The file of the default profile has no
entry; a profile writes what its writer reads and what it sets otherwise,
laid over the files it extends entry by entry. A file named by
`DOCPIPE_GRAPH_FILE` is laid over all of them: what `docpipe edit` writes a
probe with before anything is saved.

With nothing set, the written graph is the writer's, byte for byte: no file
is rewritten. Where something is set, the graph is edited as text, block by
block, so the writer's comments stay; a block the edit cannot read is
written anew by rdflib, and the result is held against the graph the rule
asks for before it is written.

Author: Felix Vossel

## Classes

### GraphError

```python
class GraphError(ValueError)
```

A graph file a run cannot read. It names the file and the entry.

### Graph

```python
@dataclass(frozen=True)
class Graph
```

Fields:

- `classes: dict = field(default_factory=dict)`
- `constraints: dict = field(default_factory=dict)`
- `rules: dict = field(default_factory=dict)`
- `owners: dict = field(default_factory=dict)`
- `files: tuple = ()`
- `sha256: str = ""`

#### Graph.written

```python
def written(self, klass: str) -> bool
```

#### Graph.address

```python
def address(self, klass: str) -> Optional[dict]
```

#### Graph.effect

```python
def effect(self, key: str) -> str
```

#### Graph.acts

```python
def acts(self) -> bool
```

Whether the file asks anything of a written graph.

## Functions

### declared

```python
def declared(profile) -> dict
```

{name: Rule} the writers of *profile*'s line declare.

### parse

```python
def parse(raw: str, where, known: Optional[dict] = None) -> dict
```

The entries of the text *raw*, read strictly: {"classes",
"constraints", "rules"}.

### dump

```python
def dump(data: dict, known: Optional[dict] = None, newline: str = "\n") -> str
```

A graph file's text in the one form it is written in.

### path_of

```python
def path_of(profile) -> Path
```

### line

```python
def line(profile) -> list
```

[(profile name, path)] of the files, nearest first, the default's
last.

### load

```python
def load(profile=None, environ=None, skip_own: bool = False) -> Graph
```

The graph file of *profile*: the default's, the files of its line
laid over it farthest first, and the file `DOCPIPE_GRAPH_FILE` names
over all. *skip_own* leaves the profile's own file and the named one
out: what it inherits.

### get

```python
def get(name: str, owner: str)
```

The value of the graph rule *name* of the profile called *owner*,
as its files and `DOCPIPE_GRAPH_FILE` say it now.

### reset

```python
def reset() -> None
```

### local

```python
def local(iri) -> str
```

### remove

```python
def remove(text: str, nodes: set) -> str
```

*text* without *nodes*: edited as text where every block can be
read, else written anew by rdflib; held against the graph the removal
asks for either way.

### addresses

```python
def addresses(text: str, made: Graph, base: str) -> dict
```

{old IRI: new IRI} for the nodes of every class with an address
rule.

### readdress

```python
def readdress(text: str, moved: dict) -> str
```

### of_class

```python
def of_class(text: str, classes: set) -> set
```

### violations

```python
def violations(text: str, shapes: list, context=()) -> list
```

[(constraint key, focus node)] of the graph held to *shapes*.

### finish

```python
def finish(path: Path, made: Graph, base: str, shapes: list = (),
           context=(), index: Optional[dict] = None) -> dict
```

What the graph file asks of the graph written to *path*, done: the
classes not written leave it, the classes with an address rule are named
anew, and the effects of the constraints are applied after the graph is
held to *shapes*. *index* is {document: [its subjects]}, which a
paper's leaving out needs. The file is rewritten only where something
changed. Returns what was done, counted.

[Back to the index](../README.md)
