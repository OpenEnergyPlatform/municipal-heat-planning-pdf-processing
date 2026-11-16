# docpipe.extraction.graphblocks

`docpipe/extraction/graphblocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

graphblocks.py: The blocks a drawing of the graph is made of, beside the
bricks it names (owner request 2026-11-14, wish 4: "Beim Graphen ... sollten
die Baublöcke und Einstellungsmöglichkeiten genau wie im Flow fein sein,
sodass man da wirklich alles konfigurieren kann").

Wherever a drawing names a brick (`{"brick": name, "settings": {...}}`) it
may set one of these instead:

  {"if": condition, "reason": "..."}      a condition (`conditions.py`) about
        the reading and what is known of the document; where it does not
        hold, the reading is left out for the reason, whose {key} stands for
        that key of the reading and {a|b|'?'} for the first of them that is
        there, else the words in quotes
  {"steps": [block, ...]}                 one block after another: each
        takes the value the one before it gave; the last one writes
  {"python": "def run(call): ...", "per", "writes", "settings"}
        Python of the drawing's own, run in the run's process as the flow's
        Python step is (owner decision 2026-11-12, point 12); it sees the
        profile's own module `kg`, `log`, `literal`, `in_graph`, `is_class`
        and `ttl_string`

and an address may be made of parts (`address_part`). Every block becomes a
`Brick`, so the writer calls a block as it calls a brick, and a drawing
that names only bricks is written as before. A block put in from a preset
keeps the preset's name under "preset" (`name_of`), changed or not.

Author: Felix Vossel

## Classes

### BlockError

```python
class BlockError(ValueError)
```

A block the program cannot run. It names what is wrong.

## Functions

### name_of

```python
def name_of(ref) -> Optional[str]
```

The name a block of a drawing goes by: the brick it names, else the
preset it was put in from, else None.

### shape

```python
def shape(ref) -> str
```

Which form a block of a drawing has: brick, if, steps or python.

### derived

```python
def derived(spec, row: dict, key: str)
```

A key of a reading the harvest does not write but the spec decides:
`unit_target`, the unit its number was converted onto (the entry's own
target, else the field's).

### value_at

```python
def value_at(doc, row: Optional[dict], path: str)
```

The value at *path* of a reading ("quantity", "provenance.page"),
a key the spec decides where the reading has none (`derived`).

### listed

```python
def listed(doc, row: dict, path: str) -> bool
```

Is the answer at *path* an entry of the list the spec gives that
dimension of the reading's field (the field's own list for its value),
and no out: entry?

### facts

```python
def facts(doc, row: Optional[dict]) -> conditions.Facts
```

What a condition of the drawing knows of one reading.

### reason

```python
def reason(template: str, doc, row: Optional[dict]) -> str
```

The reason a reading is left out, its {key} filled from the reading:
{a|b|'?'} is the first of a and b that is there, else the words in
quotes; a single {key} is that key as Python writes it, None too.

### python_problem

```python
def python_problem(code) -> Optional[str]
```

Why *code* is no block, None where it is one: Python that defines
run(call).

### compiled

```python
def compiled(code: str, space: dict) -> Callable
```

run(call) of *code*, with the names of *space* beside it.

### python_of

```python
def python_of(brick: Brick, names=BLOCK_NAMES) -> str
```

The logic of a brick as the Python of a block: its own function with
the def line `def run(call):`, and an import line for every name its body
uses that a block does not have (*names*), taken from the brick's own
module, so the code runs as it stands. Relative imports in the body are
written out in full. The empty text where the source is not to be had.

### python_block

```python
def python_block(ref, kind: str, bricks: dict, space: Optional[dict] = None
                 ) -> str
```

Any block of a drawing as the Python of a block that does the same:
a brick as its own logic (`python_of`), a condition as the test and the
reason it gives, steps as each step's code in a function of its own and
the chain that hands each step what the step before gave, its settings
beside it. The code runs as it stands where a block of Python runs.
The empty text where a step's source is not to be had; BlockError where
*ref* is no block of *kind*.

### resolve

```python
def resolve(ref, kind: str, bricks: dict, space: Optional[dict] = None,
            cache: Optional[dict] = None) -> Brick
```

The brick a block of a drawing is, for a place that wants a block of
*kind*. BlockError where there is none.

### settings_of

```python
def settings_of(ref) -> dict
```

The settings a block is called with.

### part_value

```python
def part_value(doc, box: dict, part, node=None, row: Optional[dict] = None,
               label: str = "", holds: Optional[Callable] = None)
```

What one part of an address is before it is written: a string token
as a drawing has always had it (@name, @key, @fact:x, a field whose one
reading the document gives), or a part {"from", "of", "box", "when"}.

### part_written

```python
def part_written(doc, part, value)
```

A part as the address writes it, None where it is absent.

### parts_name

```python
def parts_name(doc, box: dict, parts: list, node=None,
               row: Optional[dict] = None, label: str = "")
```

The words an address is minted from, the parts joined by |, or None
where a part that refuses to be absent is.

### part_problem

```python
def part_problem(part, fields: set, boxes: dict) -> Optional[str]
```

Why a part of an address cannot be made, None where it can.

### names_in

```python
def names_in(ref) -> list
```

The keys of a reading a block reads: the paths of its conditions'
rows about the reading, the `of` of its parts, its steps' and its
settings' strings.

[Back to the index](../README.md)
