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
wrong and neither should find that out in production. What the PDF does not
print of DOI and year the run looks up in OpenAlex with the title and the
authors it read (`completion.py`); such a value names its record.

## Functions

### node_names

```python
def node_names(regions: Path = REGION_NAMES_PATH,
               snapshot: Path = SNAPSHOT_PATH) -> dict
```

{IRI: name} of every node this graph may point at without minting it:
a region by the English short name LCC gives it, an OEO term by its
label in the release the snapshot is pinned to. A file no refresh has
written names nothing.

### default_model

```python
def default_model()
```

The OEKG shapes of the last refresh, or SchemaError without one.

A graph written without them is one nobody can say anything about, so
there is no fallback to the paths this module would otherwise assume.

### edges

```python
def edges() -> list
```

The triple shapes this serializer writes that no `kg` block carries.

`ontology.edge_problems` holds the rest of the output to the pinned
ontology through the spec; without this the writer's own literals are the
part nobody checks, which is where three of kwp's defects lived. The
uuid is written where the shapes have its path, so without shapes from a
refresh nothing is said about it.

### bind

```python
def bind(model) -> SimpleNamespace
```

What the shapes say about the graph this module writes.

Every path WRITTEN names has to be a property of the shape its node is
held to, and the two dates have to be the xsd:dateTime this module
writes: a shapes file that dropped or retyped one stops the serializer
here rather than in a report after the run. What is read off them:

  single    the per-document fields whose path the shapes allow once,
            so the harvest's several readings are settled to one
  required  the per-document fields the shapes demand, so a document
            that misses one is reported
  uuid_on   the shaped nodes whose shape has the uuid path
  author, organisation, funder, region
            the class at the end of each edge, where the shape names
            exactly one

### normalise

```python
def normalise(label: str) -> str
```

One spelling for a name, so two writings of it mint one IRI.

### mint

```python
def mint(collection: str, name: str) -> str
```

UUIDv5 over the identifying name, folded by `normalise`. Never v4: two
runs over one document must mint the same IRI.

### uuid_of

```python
def uuid_of(iri: str) -> str
```

### in_graph

```python
def in_graph(value) -> bool
```

Is this answer something the graph takes, or one of the out: entries?

### region_members

```python
def region_members(value, groups: dict) -> list
```

The OEKG regions a scenario_region answer stands for: a country is
itself, a group its members, an out: entry none.

### graph_value

```python
def graph_value(row: dict)
```

What this row actually put in the graph.

For an out: entry the model's `value` is that entry's own label — a
description of why nothing fitted, not a reading of the document. The
graph carries the wording instead, so the evidence has to name the wording
too, or it would cite a passage for a string that is nowhere in it.

### scenario_names

```python
def scenario_names(row: dict) -> list
```

The names of the scenarios a row belongs to.

A scenario_label row names one by its value, any other row by its
`scenario` coordinate, both as the publication prints them. Which of a
publication's names mean the same scenario was asked once it was read
(`value_means`, `scenario_means`, docpipe/extraction/naming.py): a name
of one scenario means the name that scenario is called by, a name of
several scenarios means each of theirs (owner decisions 2026-11-06). A
row read before that was asked belongs to the scenario of its own name.

### decision_text

```python
def decision_text(decision: dict) -> str
```

What a person decided about one field of a value, as a comment line:
the verdict, who made it and when, and the note.

### make_serializer

```python
def make_serializer(db_path: Path, model=None, groups: Optional[dict] = None,
                    names: Optional[dict] = None)
```

(document name, accepted tuple rows) -> TTL string or None.

Written to *model*, the shapes of the last refresh by default, with the
*groups* and *names* of the last refresh by default (`_make_builder`).

What people decided about the rows is left in `serializer.decisions` by
`serialize.run`, {document: {tuple name: [decision]}}, and goes into the
Turtle as comment lines above the value each concerns.

### make_study_reader

```python
def make_study_reader(db_path: Path, model=None)
```

(document name, accepted tuple rows) -> study dict or None.

What the serializer decided for one document, without the Turtle: the
bundle, its one study report and its scenarios, each value as the graph
carries it. A document with no title has no study, as it has no graph.

[Back to the index](../README.md)
