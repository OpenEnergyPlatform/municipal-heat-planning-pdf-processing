# profiles.scenarios.kg

`profiles/scenarios/kg.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

kg.py: The bricks only the scenarios profile's graph needs.

How the harvest of a publication becomes the OEKG graph is the drawing in
graph.json beside this file (`map`), written by the core's program
(`docpipe/extraction/graph.py`). Here are the pieces of it that only this
profile has: which scenarios a row names, the short name of a scenario, the
regions a region answer stands for, the names of the nodes the graph points
at without making them, the cross-check against the crawl, and `study`, the
same decisions as plain data for the OEKG API body (`oekg_api.py`).

The passages of every value are Turtle comments above the triple by default
(the shapes are sh:closed); the rule `evidence_as` of graph.json writes one
`oekgprov:ExtractionEvidence` node per value instead, linked with
`oekgprov:hasEvidence`, knowingly ahead of the shapes.

Author: Felix Vossel

## Functions

### node_names

```python
def node_names(regions: Path = REGION_NAMES_PATH,
               snapshot: Path = SNAPSHOT_PATH) -> dict
```

{IRI: name} of every node this graph may point at without making
it: a region by the English short name LCC gives it, an OEO term by its
label in the release the snapshot is pinned to. A file no refresh has
written names nothing.

### default_model

```python
def default_model()
```

The OEKG shapes of the last refresh, or SchemaError without one.

### has_property

```python
def has_property(klass: str, prop: str) -> Optional[bool]
```

Whether the OEKG shapes give the class (a curie) the property (a
curie); None where no shape targets the class, or there are no shapes
from a refresh.

### context

```python
def context(db_path=None) -> dict
```

What the bricks of this profile share while a graph is written: the
groups of countries a region answer may name and the names of the nodes
the graph points at.

### printed_region

```python
def printed_region(row: dict) -> Optional[str]
```

The name of a study region the list did not carry, as the row's
document prints it (`value_raw`); None for any other row.

### region_members

```python
def region_members(value, groups: dict) -> list
```

The OEKG regions a region answer stands for: a country is itself, a
group its members, an out: entry none.

### scenario_names

```python
def scenario_names(row: dict, name_in_quote: bool = True) -> list
```

The names of the scenarios a row belongs to.

A scenario_label row names one by its value, any other row by its
`scenario` coordinate, both as the publication prints them. Which entry
of the publication's list of scenarios a name is was asked while it was
read (`value_means`, `scenario_means`, owner decisions 2026-11-08): a
name means the entry it is, the words of a group of scenarios each
member, and words found to name no scenario (an empty list) none (owner
decision 2026-11-09). With *name_in_quote* a name the publication's
passage does not print names nothing.

### study_of

```python
def study_of(written) -> dict
```

What the drawing decided for one document, as plain data: the bundle,
its one study report and its scenarios, each value as the graph carries
it (`oekg_api.py` builds the platform's request body from it).

### box_class

```python
def box_class(box_id: str) -> str
```

The bare class of a box of the drawing.

### property_of

```python
def property_of(source: str, to: str, brick: Optional[str] = None) -> str
```

The property of the drawing's arrow from *source* to *to*.

### normalise

```python
def normalise(name: str) -> str
```

One spelling for a name, as the drawing folds it.

### tag_property

```python
def tag_property(key: str) -> str
```

The property a tag field of the bundle is written under.

### make_study_reader

```python
def make_study_reader(db_path: Path, extra: Optional[dict] = None)
```

(document name, accepted tuple rows) -> study dict or None: what the
drawing decides for one document, without the Turtle. A document
without a title has no study, as it has no graph.

[Back to the index](../README.md)
