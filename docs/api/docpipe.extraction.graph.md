# docpipe.extraction.graph

`docpipe/extraction/graph.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

graph.py: Writes a harvest as the graph the drawing of its profile says.

How the harvest becomes the graph is a drawing in the profile's graph file
(`map` in graph.json, `docpipe.graphfile`), drawn in the Graph tab of
`docpipe edit`. This program writes the graph from that drawing alone,
without a model and without a new harvest:

    a box       a class of the graph; how many nodes it has in a document
                (one per document, per name, per distinct reading, per
                answer of a table, per number, per object another arrow
                wrote) and how a node's address is made
    an arrow    from a field or a coordinate of the harvest to a property
                of a box, from a box to itself (what a brick knows of the
                node), or from a box to a box over a property
    a brick     on an arrow or a box: the code that turns a reading into
                the object of a triple (`bricks.py`, and a profile's own in
                `profiles/<name>/kg.py`)

What the program does for every drawing, with the rules of the graph file
it reads (`readings.py`): one reading where the drawing says the shapes
allow one (rule `front_first_fields` for the fields a publication states on
its front pages), the numbers of one address settled (`rounding_tolerance`,
`contested_in_full`), the first value a file gives a property of a node
kept for later documents, and every triple's passages as comment lines
above it or as evidence nodes (`evidence_as`). The full and the strict
graph are one drawing: a condition or a requirement marked `strict` holds
only for the strict one.

Author: Felix Vossel

## Classes

### GraphError

```python
class GraphError(ValueError)
```

A drawing the program cannot write from. It names the entry.

### Drawing

```python
@dataclass
class Drawing
```

Fields:

- `raw: dict`

#### Drawing.header

```python
def header(self) -> str
```

#### Drawing.subject_of

```python
def subject_of(self, arrow: dict) -> str
```

The box whose nodes an arrow writes on: the box it points at,
unless it runs from one box to another, then the one it starts
at.

#### Drawing.kind_of

```python
def kind_of(self, arrow: dict) -> str
```

`link` from a box to a box, `node` from a box to itself, `field`
from a reading.

#### Drawing.written

```python
def written(self, box_id: str) -> bool
```

#### Drawing.fields_of

```python
def fields_of(self, box: dict) -> tuple
```

#### Drawing.serves

```python
def serves(self, box: dict, uri: str, seen: tuple = ()) -> bool
```

Whether the nodes of *box* are written from the readings of the
field *uri*: it is one the box is of, or one of the box it takes its
answers from (`among`).

#### Drawing.readers

```python
def readers(self, uri: str, coordinate: Optional[str] = None) -> list
```

The arrows that read the field *uri*, or its coordinate
*coordinate*: an arrow that starts at the field, at a key of its
reading into a box written from it, or at the coordinate (bare or
as its wording, `<coordinate>_raw`) into such a box; for a field,
also the arrow that links to the box of its readings (one node per
distinct reading); for a coordinate, the arrows that link to the
box that is of it (one node per answer).

#### Drawing.says

```python
def says(self) -> set
```

Every name of the spec the drawing names as a source: where an
arrow starts, what a box is of, takes its value, name or address
from, and the strings of the settings of a brick and of a box's
`settle`.

### Memory

```python
@dataclass
class Memory
```

Fields:

- `header: bool = True`
- `settled: dict = field(default_factory=dict)`: (node, property) -> (value, term)
- `told: set = field(default_factory=set)`: nodes written once per file
- `minted: dict = field(default_factory=dict)`: (box, node) -> document

### Node

```python
@dataclass
class Node
```

Fields:

- `box: str`
- `iri: str`
- `key: object = None`
- `name: object = None`
- `rows: list = field(default_factory=list)`
- `data: dict = field(default_factory=dict)`
- `values: dict = field(default_factory=dict)`: arrow key -> [value]

#### Node.row

```python
@property
def row(self) -> Optional[dict]
```

### Entry

```python
@dataclass
class Entry
```

Fields:

- `predicate: str`
- `objects: list`
- `comments: list = field(default_factory=list)`
- `joined: bool = False`

### Document

```python
class Document
```

One document being written: its rows, its facts, its nodes, and
what a brick asks of the writer.

#### Document.\_\_init\_\_

```python
def __init__(self, writer: "Writer", name: str, rows: list,
             decided: Optional[dict])
```

#### Document.spec

```python
@property
def spec(self)
```

#### Document.strict

```python
@property
def strict(self) -> bool
```

#### Document.prefixes

```python
@property
def prefixes(self) -> dict
```

#### Document.legal_forms

```python
@property
def legal_forms(self) -> str
```

#### Document.extra

```python
@property
def extra(self) -> dict
```

#### Document.base

```python
@property
def base(self) -> str
```

#### Document.rule

```python
def rule(self, name: str)
```

#### Document.fold

```python
def fold(self, text) -> str
```

#### Document.mint

```python
def mint(self, folder: str, key: str, name: str) -> str
```

#### Document.count

```python
def count(self, what: str, name: str = "") -> None
```

#### Document.chosen

```python
def chosen(self, field_: str)
```

The one reading of *field\_* the document gives (`pick_one`), the
front pages first where the rule names the field; the others are
counted as contested.

#### Document.picked

```python
def picked(self, field_: str)
```

The one reading of *field\_* already chosen, None where none
was.

#### Document.address_of_answer

```python
def address_of_answer(self, box_id: str, answer) -> Optional[str]
```

#### Document.node_of

```python
def node_of(self, box_id: str, key) -> Optional[Node]
```

### Writer

```python
class Writer
```

#### Writer.\_\_init\_\_

```python
def __init__(self, drawing: Drawing, *, spec, rules: dict, bricks: dict,
             db_path=None, strict: bool = False,
             extra: Optional[dict] = None,
             required: Optional[dict] = None)
```

#### Writer.brick

```python
def brick(self, ref, kind: str)
```

#### Writer.call

```python
def call(self, ref, kind: str, **given)
```

#### Writer.condition

```python
def condition(self, refs, doc: Document, row: dict) -> Optional[str]
```

#### Writer.named_address

```python
def named_address(self, doc: Document, box: dict, entry=None) -> str
```

#### Writer.minted_address

```python
def minted_address(self, doc: Document, box: dict,
                   node: Optional[Node]) -> tuple
```

(address, the name it was made from) or (None, None).

#### Writer.write

```python
def write(self, name: str, rows: list,
          decided: Optional[dict] = None) -> Optional["Written"]
```

#### Writer.lacking

```python
def lacking(self, doc: Document, entries: dict) -> dict
```

{box id: [property]} the shapes demand of the class of a node
written for the box and some node of it does not say.

#### Writer.by_choice

```python
def by_choice(self, doc: Document) -> Counter
```

The answers the drawing leaves out on purpose, per answer: an
out: entry of a list, on a row the document took that no node of
its own (not one of the document) carries.

#### Writer.unhung

```python
def unhung(self, doc: Document) -> Counter
```

The readings of a box of names or of readings that no node of the
box carries, per field and state; an out: entry is counted by
choice instead.

#### Writer.names_of

```python
def names_of(self, doc: Document, box: dict, row: dict,
             field_: str) -> list
```

The names a row of *field\_* gives the nodes of *box*, folded.

#### Writer.rows_of

```python
def rows_of(self, doc: Document, node: Node, box: dict,
            source: str) -> list
```

#### Writer.related

```python
def related(self, doc: Document, node: Node, box: dict,
            target: dict) -> list
```

### Written

```python
class Written
```

One document as the drawing wrote it: its nodes, their triples, the
text, and what the provenance file records of it.

#### Written.\_\_init\_\_

```python
def __init__(self, writer: Writer, doc: Document, entries: dict)
```

#### Written.nodes

```python
@property
def nodes(self) -> dict
```

#### Written.values

```python
def values(self, node: Node, source: str, to: Optional[str] = None,
           prop: Optional[str] = None) -> list
```

What the arrow from *source* wrote on *node*, as values.

#### Written.text

```python
def text(self) -> str
```

#### Written.claims

```python
def claims(self) -> Optional[dict]
```

## Functions

### arrow_key

```python
def arrow_key(arrow: dict) -> str
```

How an arrow is named where a drawing or a writer refers to it.

### required_by_class

```python
def required_by_class(profile) -> dict
```

{class: {property}} the shapes of *profile* demand (min count 1 or
more), taken as the Graph tab takes them; {} for a profile without
shapes, or without the library that reads them.

### shown_value

```python
def shown_value(row: dict)
```

What a row put in the graph: for an out: entry the document's
wording, not the entry's own label.

### decision_text

```python
def decision_text(decision: dict) -> str
```

What a person decided about one field of a value, as a comment line:
the verdict, who made it and when, and the note.

### check

```python
def check(drawing: Drawing, profile, spec=None, bricks=None) -> list
```

What *drawing* names that the spec, the shapes or the bricks of
*profile* do not have, one sentence each: a field the spec does not
ask, a brick no code has or of another kind, a property the shapes do
not give the class of the node it is written on. A property the shapes
demand and no arrow writes is no problem here: the Graph tab shows it
red.

### load_drawing

```python
def load_drawing(profile, environ=None) -> Drawing
```

The drawing of *profile*'s graph file, or GraphError without one.

### make_writer

```python
def make_writer(profile, db_path=None, *, strict: bool = False,
                extra: Optional[dict] = None,
                drawing: Optional[Drawing] = None,
                environ=None) -> Writer
```

### make_serializer

```python
def make_serializer(profile, db_path=None, *, strict: bool = False,
                    extra: Optional[dict] = None,
                    drawing: Optional[Drawing] = None) -> Callable
```

(document name, accepted rows) -> Turtle or None, written from the
drawing of *profile*. `claims` holds per document what the provenance
file records.

[Back to the index](../README.md)
