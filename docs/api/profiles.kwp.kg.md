# profiles.kwp.kg

`profiles/kwp/kg.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

kg.py: The bricks only the kwp profile's graph needs, and how the answer
app asks that graph.

How the harvest of a heat plan becomes the MHPKG graph is the drawing in
graph.json beside this file (`map`), written by the core's program
(`docpipe/extraction/graph.py`). Here are the pieces only this profile has:
what the register knows of a plan (its AGS, publication date and
municipality), which numbers the graph takes and why the others stay in the
harvest, the address of a number (the coordinate list of the IRI policy,
mint_slice.py), its class and unit, the comment lines above it, and what the
provenance file records of it.

The IRI policy must stay a pure function of the data: two runs over the
same plan mint byte-identical IRIs.

Author: Felix Vossel

## Functions

### spec

```python
def spec()
```

The spec as the extraction stage loads it with the rules in effect
now. The answer app's graph route reads its lists off it
(`docpipe.inference.kg_route`).

### drawing

```python
def drawing() -> dict
```

The drawing, as the graph file of this profile has it now.

### prefix_iri

```python
def prefix_iri() -> dict
```

{prefix: IRI} of the header the drawing writes now.

### expand

```python
def expand(name: str) -> str
```

`mhpo:MHPO_00020007` -> the full IRI, from the header this graph
writes. An unbound prefix raises rather than defaults.

### is_class

```python
def is_class(value) -> bool
```

True for a real OEO class, false for every deliberate non-class: the
axes hold entries that say what a row IS when no class fits.

### qualified

```python
def qualified(identifier: str) -> str
```

A bare ontology id as this graph writes it.

### has_property

```python
def has_property(klass: str, prop: str) -> Optional[bool]
```

Whether the MHPKG schema gives the class (a curie) the property (a
curie); None where the schema has no such class.

### target_of

```python
def target_of(row: dict) -> Optional[str]
```

The unit this value's number was converted onto.

### unit_of

```python
def unit_of(row: dict) -> Optional[str]
```

The unit the graph writes this value in, None outside the graph: the
unit its number was converted onto, where that is an ontology term.

### totals

```python
def totals(drawing: dict, box_id: str) -> dict
```

{coordinate: class} the arrows of *box_id* write for out:total.

### written

```python
def written(row: dict, axis: str, total: dict)
```

What the graph writes for this coordinate: the class read, or for a
number the plan does not split by this axis (`out:total`) the class the
drawing names for it, or nothing.

### schema_class_of

```python
def schema_class_of(row: dict, table: dict) -> Optional[str]
```

The schema class this value is in its part: the class the model
chose, or the schema's value class it falls under, or None.

### strict_refusal

```python
def strict_refusal(row: dict, table: dict, total: dict) -> Optional[str]
```

Why this value has no place in the strict graph, or None: the strict
graph holds what the schema's shapes take, a value class the part
holds, every required slot, and every slot's answer from the schema's
own closed list.

### document_identity

```python
def document_identity(db_path: Path, name: str)
```

(ags, published, municipality name) or None.

### facts_of

```python
def facts_of(identity) -> dict
```

### heatplan_iri

```python
def heatplan_iri(db_path: Path, name: str) -> Optional[str]
```

The plan node the drawing makes for this document, or None: one
making for the graph and for whoever asks it.

### evidence_comment

```python
def evidence_comment(row: dict, document: str, prose: dict, join: str, *,
                     transcribed: bool = False, conflict: bool = False,
                     corroborated: bool = False,
                     resolved: Optional[str] = None,
                     named: Optional[str] = None) -> list
```

Where this value was read, as comment lines above its node: the
coordinates in English, the passage, the page, how it was aggregated,
what was computed, and how far the run stands behind it.

### trust_prose

```python
def trust_prose() -> dict
```

The trust words of the comment above a number, for the answer app,
as the drawing's value box has them now.

### parts

```python
def parts() -> dict
```

{scenario: (class, folder, label)} of the plan parts the drawing's
part box lists now.

### value_query

```python
def value_query() -> str
```

The query, over the drawing the graph is written from now, so the
two cannot drift.

### value_bindings

```python
def value_bindings(coordinates: dict) -> tuple
```

(constraint lines for ##CONSTRAINTS##, {variable: (kind, value)}).

An unbound axis adds no line. A quantity the graph does not hold and any
`out:` entry are dropped here, because `oeo:out:share` is an IRI that
does not exist.

### label_of

```python
def label_of(identifier: str) -> str
```

What a reader calls a class: the spec's first spelling for it, else
the pinned vocabulary's label, else the identifier itself.

[Back to the index](../README.md)
