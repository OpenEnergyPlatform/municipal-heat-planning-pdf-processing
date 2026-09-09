# profiles.scenarios.kg

`profiles/scenarios/kg.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

kg.py – Harvested publication metadata to OEKG Turtle.

What the shapes ask of a scenario bundle, its study report and its scenario
factsheets — plus the evidence for every value.

That last part is PROVISIONAL. The shapes are `sh:closed true` today, which
would make an evidence triple invalidate the node; whether they stay closed
is being decided on the ontology side, and this is written as if they will
not. The whole point of reading metadata out of the PDF rather than taking
the crawl's copy is that each value can name the passage it came from, so a
graph that drops the passage gives up the reason it was built this way. One
By default every passage is a Turtle comment above the triple it belongs to,
which survives sh:closed; OEKG_EVIDENCE=1 emits one `oekgprov:ExtractionEvidence`
node per value instead, linked with `oekgprov:hasEvidence` — the same content as
triples, and knowingly ahead of the shapes.

Cardinality is enforced here rather than in the verifier, because the
verifier sees one claim at a time and `exactly one title` is a property of a
document's whole harvest. Where the shape says maxCount 1 and the harvest
offers several, the one the most sources agree on wins; the rest are counted,
not dropped silently.

The crawl's DocumentMeta (title, year, doi) is not the source here — it comes
with the crawl's licence. It is the cross-check: a disagreement between what
the PDF says and what the crawl said is logged, because one of the two is
wrong and neither should find that out in production.

## Functions

### edges

```python
def edges() -> list
```

The triple shapes this serializer writes that no `kg` block carries.

`ontology.edge_problems` holds the rest of the output to the pinned
ontology through the spec; without this the writer's own literals are the
part nobody checks, which is where three of kwp's defects lived.

### normalise

```python
def normalise(label: str) -> str
```

One spelling for a name, so two writings of it mint one IRI.

### ns

```python
def ns(collection: str) -> uuid.UUID
```

### mint

```python
def mint(collection: str, name: str) -> str
```

UUIDv5 over the identifying name. Never v4 — v4 is random, and two runs
over one document must mint the same IRI.

### uuid_of

```python
def uuid_of(iri: str) -> str
```

### in_graph

```python
def in_graph(value) -> bool
```

Is this answer something the graph takes, or one of the out: entries?

### graph_value

```python
def graph_value(row: dict)
```

What this row actually put in the graph.

For an out: entry the model's `value` is that entry's own label — a
description of why nothing fitted, not a reading of the document. The
graph carries the wording instead, so the evidence has to name the wording
too, or it would cite a passage for a string that is nowhere in it.

### ambiguous

```python
def ambiguous(wording, known: dict) -> bool
```

Does this wording fit more than one AR6 run of this publication?

Measured on the 146-scenario pilot document: the paper writes "NPi" and
"NDC", and the database has EN_NPi2020_300f, EN_NPi2020_400 and
EN_NPi2020_3000. Those are three runs, and "NPi" names the family, not one
of them. A model handed the list picks one anyway, which is a guess
dressed as a link — so a wording that fits several is treated as fitting
none, and the wording alone survives.

### resolve_wording

```python
def resolve_wording(wording, known: Optional[dict] = None) -> Optional[str]
```

The run this wording names, when the list settles it without a guess.

The mirror of `ambiguous()`. That one refuses the link where several runs
fit and none matches exactly; this one MAKES the link where exactly one
does. Both read the same list, and between them the model's own choice is
only consulted where the list is genuinely undecided.

Measured on the corpus run: the model answered with an out: entry 1171
times for a wording its own list resolved unambiguously — 347 of them a
character-for-character match of a run name, one document refusing "BaU"
against a list whose single entry is "BaU".

Short wordings are exact-match only. "NPi" is three characters and sits
inside a dozen run names; a containment hit that short is a coincidence,
not a reading.

### scenario_key

```python
def scenario_key(row: dict, known: Optional[dict] = None,
                 synonyms: Optional[dict] = None) -> tuple
```

(identity, label) for the scenario a row belongs to.

The model picks the AR6 run from this publication's own list and keeps the
document's wording beside it. The run identifier is the identity whenever
there is one, because that is what links to the AR6 database; the wording
is what a reader recognises. With no match, and with a wording that fits
several runs equally, the wording is both.

### literal

```python
def literal(text: str) -> str
```

A Turtle string literal. Abstracts run over several lines, so the long
form is used whenever the text is not a single clean line.

### make_serializer

```python
def make_serializer(db_path: Path)
```

(document name, accepted tuple rows) -> TTL string or None.

[Back to the index](../README.md)
