# profiles.scenarios.vocabulary

`profiles/scenarios/vocabulary.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

vocabulary.py – This profile's half of the ontology snapshot.

The builder lives in `docpipe/ontology.py`. What is here is what is about AR6
scenario publications: which roots this profile's one static list draws from,
and the 249 study regions, which come from the OEKG rather than from an
ontology release and are therefore pinned differently.

    python -m profiles.scenarios.vocabulary --closure oeo-closure.owl --write
    python -m profiles.scenarios.vocabulary --check

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
