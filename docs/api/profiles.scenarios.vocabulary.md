# profiles.scenarios.vocabulary

`profiles/scenarios/vocabulary.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

vocabulary.py – This profile's half of the ontology snapshot.

The builder lives in `docpipe/ontology.py`. What is here is what is about AR6
scenario publications: which roots this profile's one static list draws from,
and the 249 study regions, which come from the OEKG rather than from an
ontology release and are therefore pinned differently.

    python -m profiles.scenarios.vocabulary --refresh   # needs OEP_API_TOKEN
    python -m profiles.scenarios.vocabulary --closure oeo-closure.owl --write
    python -m profiles.scenarios.vocabulary --check

`--refresh` is what a run calls first: the OEO closure at its latest release,
the study regions live from the OEKG, the OEKG shapes at the head of their
branch and the groups of countries a scenario may cover (IIASA, UN M49),
then the check. Without
OEP_API_TOKEN in the environment it stops, because the regions are offered to
the model and a list nobody pulled is not the OEKG's current one.

Why this profile needed it more than the other one. Its spec names 32 ontology
identifiers and, before this, exactly zero of them were checked against
anything: the old walk looked in three named places, and this profile writes
its terms as full IRIs in vocabulary KEYS and as predicates inside `kg`
blocks. Most of them ARE predicates, so an index over classes and individuals
would have called every one of them missing.

Author: Felix Vossel

## Functions

### build

```python
def build(closure: Path) -> dict
```

### load

```python
def load(path: Path = VOCABULARY_PATH) -> dict
```

### merge_regions

```python
def merge_regions(rows: list, aliases: dict) -> dict
```

{region IRI: labels} from the live rows and the hand-kept spellings.

The OEKG decides which regions exist. region_aliases.json keeps the
spellings a document writes that the graph does not carry (both "Cabo
Verde" and "Cape Verde", say); they come first, in
their order, and a live label they lack is appended. A region with no
label from either side cannot be offered to the model and raises.

### aggregates

```python
def aggregates(families: list, tree: list, regions: dict) -> tuple
```

({key: {labels, members, source}}, Counter of what could not be placed).

*families* are the parsed IIASA region files, *tree* the M49 tree,
*regions* regions.json. A member is an OEKG region, found by one of its
labels, or by a label with the same words in another order and
punctuation ("Republic of Moldova", "Moldova (the Republic of)"), so a
country both lists spell alike needs no table; one no label names, or
two regions' labels do, is counted, never guessed. A group's label that is a country's
label is the country, and a label two groups share is the first one's:
both would make one answer mean two things, so each is counted too.

### refresh

```python
def refresh(cache: Path = upstream.CACHE) -> dict
```

Pull SOURCES, write regions.json and vocabulary.json, write the lock.

The lock is what `shapes` reads: the serializer and the validation of
the written graph take the shapes this refresh pulled.

### shapes

```python
def shapes(cache: Path = upstream.CACHE) -> list
```

The OEKG shapes of the last refresh; empty if none has run.

### context

```python
def context(cache: Path = upstream.CACHE) -> list
```

[(subject, predicate, object)] the OEKG holds about the nodes it already
has, as the last refresh pulled them; empty if none has pulled them.

### spec_terms

```python
def spec_terms(spec_raw: dict) -> dict
```

### region_problems

```python
def region_problems(snapshot: dict, regions=None) -> list
```

The regions file against the snapshot it was pinned with.

`document_regions` filters this list per document, so a region that
silently disappears from it stops being offered for every publication that
names it, and nothing else would say so.

`regions` is the file's content and is read from disk when not given; a
caller passes it so the comparison can be exercised without editing the
checked-in file.

### edges

```python
def edges(spec_raw: dict) -> list
```

Every triple shape this profile emits, the spec's and the writer's.

### check

```python
def check(spec_raw: dict, snapshot: dict) -> list
```

Every complaint the pinned ontology has about this spec.

### foreign_labels

```python
def foreign_labels(spec_raw: dict, snapshot: dict) -> list
```

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
