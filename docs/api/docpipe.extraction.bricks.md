# docpipe.extraction.bricks

`docpipe/extraction/bricks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

bricks.py: The pieces a drawing of the graph puts on its arrows and boxes.

The drawing in a profile's graph file (`map`, read by `graph.py`) says which
box a field becomes, which property an arrow writes and which brick turns a
reading into the object of a triple. A brick is code: it takes one kind of
thing, gives one kind of thing back, and says in one sentence what it does.
The core's bricks are here; a profile adds the ones only it needs in
`profiles/<name>/kg.py` (`BRICKS`), and a drawing names a brick by its name.

The kinds, by where a drawing puts them:

  object     on an arrow: the object(s) of the triple from a reading, or
             from the node itself
  condition  in a box's or the document's list: None where a row is taken,
             else the reason it is not
  facts      on the document: what is known of it beyond its harvest
  nodes      on a box of one node per name: the names a row gives
  address    on a box of one node per number: the address of a number
  class      on a box: the class(es) a node is written as
  evidence   on a box: the comment lines above a node
  name       on a box: a node's name from its first reading
  check      on the document: a diagnostic over what was chosen
  claims     on a box: what the provenance file records of a node

Every brick is called with one `Call`; what it reads of it depends on its
kind. An object brick gives [(Turtle term, value)], the value being what
another writer (the OEKG API body) and a later document see.

Author: Felix Vossel

## Classes

### Setting

```python
@dataclass(frozen=True)
class Setting
```

Fields:

- `key: str`
- `kind: str`
- `help: str`
- `default: object = None`

### Brick

```python
@dataclass(frozen=True)
class Brick
```

Fields:

- `name: str`
- `kind: str`
- `does: str`
- `takes: str`
- `gives: str`
- `run: Callable`
- `settings: tuple = ()`
- `per: str = "row"`: An object brick reads one reading at a time ("row") or all the readings of its node at once ("node").
- `writes: str = ""`: What an object brick writes, for the checks that hold every triple shape to the ontology (`ontology.drawing_edges`): "answers" (a class of the coordinate's list), "entries" (an entry of the field's list), "key:\<name>" (the identifier a key of the field holds), "xsd:\<type>" (a literal of that datatype), "setting:datatype" (the datatype its settings name), "" (a plain literal or nothing known).

#### Brick.describe

```python
def describe(self) -> dict
```

What `docpipe edit` shows of the brick.

### Call

```python
@dataclass
class Call
```

What a brick is called with. `doc` is the document being written
(`graph.Document`), `node` the node, `row` the reading, `value` what the
arrow reads of it, `settings` the brick's settings in the drawing,
`label` the words a number's address is split by, `source` the field
or coordinate the arrow starts at, `rows` the readings a node-wide
brick reads.

Fields:

- `doc: object = None`
- `node: object = None`
- `row: Optional[dict] = None`
- `value: object = None`
- `settings: dict = field(default_factory=dict)`
- `label: str = ""`
- `source: Optional[str] = None`
- `rows: list = field(default_factory=list)`

## Functions

### literal

```python
def literal(text, form: str = "long") -> str
```

A text as a Turtle string literal: `long` may run over several lines
(`ttl_literal`), `line` escapes every line break (`ttl_string`).

### in_graph

```python
def in_graph(value) -> bool
```

Is this answer something the graph takes, or one of the out: entries
of a list, which say what a row is when nothing fits?

### is_class

```python
def is_class(value, family: str = "") -> bool
```

True for a class identifier (OEO_00000128) of *family*, where one is
given; false for every deliberate non-class answer.

### registry

```python
def registry(profile=None) -> dict
```

{name: Brick}: the core's and *profile*'s own (`kg.BRICKS`).

[Back to the index](../README.md)
