# profiles.kwp.kg

`profiles/kwp/kg.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

kg.py: Serializes harvested tuples into MHPKG Turtle.

The IRI policy is rebuilt from the schema repo's mint_slice.py and must stay
a pure function of the data: two runs over the same plan mint byte-identical
IRIs (tested against their published reference UUIDs). One deliberate
deviation: the value coordinates include the sector, because our tables carry
several sectors per carrier/year and the published coordinate list would
collide them into one node, which was flagged to the schema side.

Serialized is what the graph can hold: a value whose scenario names one of
the three plan parts of PARTS, whose scope is the municipality, whose
indicator label is accepted and whose year is read. Everything else stays in
the JSONL harvest and is counted here, not lost.

## Functions

### expand

```python
def expand(name: str) -> str
```

`mhpo:MHPO_00020007` -> the full IRI, from the header this graph writes.

Two of the three plan parts are mhpo: and one is oeo:, so a query that
assumed one namespace would bind IRIs no graph holds and return nothing,
silently. An unbound prefix raises rather than defaults.

### is_class

```python
def is_class(value) -> bool
```

True for a real OEO class, false for every deliberate non-class.

The axes hold entries that say what a row IS when no class fits — a sum,
a residual, a sector the source calls unknown. They are answers, not
classes, and writing one as `oeo:out:total` mints an IRI that does not
exist. Checked by shape rather than by prefix so a new entry cannot slip
past by being spelled differently.

### qualified

```python
def qualified(identifier: str) -> str
```

A bare ontology id as this graph writes it.

### year_iri

```python
def year_iri(year) -> str
```

The node a value points at for its year.

One node per calendar year for the whole graph, keyed by the year itself
rather than minted from a uuid: two plans naming 2030 mean the same 2030,
and a year is the one coordinate with no document in it.

### ns

```python
def ns(collection: str) -> uuid.UUID
```

### normalise

```python
def normalise(label: str) -> str
```

The umlaut rule from the policy, applied in order.

### display_name

```python
def display_name(label: str) -> str
```

The name as the graph shows it: the document's own spelling, minus the
legal form. `normalise` decides identity and casefolds for that; a label a
reader sees must keep its capitals, and kassel_valid.ttl shows the
stripped form.

### mint

```python
def mint(collection: str, name: str) -> str
```

Tier 3: UUIDv5 over the identifying name. Never v4 — v4 is random.

### plan_iri

```python
def plan_iri(ags: str, published: str) -> str
```

Tier 2: the plan's register key and its full publication date.

### heatplan_iri

```python
def heatplan_iri(db_path: Path, name: str) -> Optional[str]
```

The plan node the serializer mints for this document, or None.

One minting site for the graph and for whoever asks it. The app was one
f-string away from building its own, and `_iso_date` is exactly where a
second copy diverges: ingest stores YYYYMMDD, the policy wants
YYYY-MM-DD, and that mismatch once produced an empty graph with every
test green.

### evidence_comment

```python
def evidence_comment(row: dict, document: str, *,
                     transcribed: bool = False,
                     conflict: bool = False) -> list
```

Where this value was read, as comment lines above its node.

The prototype's evidence: the wording the document used, the passage it
was read in, and the page it stands on. A comment rather than triples
because the shapes are sh:closed and an extra triple on a value node
invalidates it.

### make_serializer

```python
def make_serializer(db_path: Path)
```

(document name, accepted tuple rows) -> TTL string or None.

### value_bindings

```python
def value_bindings(coordinates: dict) -> tuple
```

(constraint lines for ##CONSTRAINTS##, {variable: (kind, value)}).

An unbound axis adds no line, which is why the constraints are text and
not initBindings alone. The kinds are plain strings ("iri", "literal") so
this module stays rdflib-free; the core wraps them. Gates: a quantity the
graph does not hold and any `out:` entry are dropped here, because
`oeo:out:potential` is an IRI that does not exist.

### label_of

```python
def label_of(identifier: str) -> str
```

What a reader calls a class: the spec's first spelling for it, else
the pinned vocabulary's label, else the identifier itself.

Takes the full IRI the query returns, a qualified name or a bare id, so
the display never carries a second table of German words.

[Back to the index](../README.md)
