# profiles.kwp.vocabulary

`profiles/kwp/vocabulary.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

vocabulary.py – This profile's half of the ontology snapshot.

The builder, the index and the two complaints every profile shares moved to
`docpipe/ontology.py` when the second profile needed them. What stays here is
what is genuinely about heat plans: which roots this profile's lists draw
from, where its ontology files live, and the one rule that is about its own
carrier axis.

    python -m profiles.kwp.vocabulary --closure oeo-closure.owl \
        --mhpo mhpo-edit.owl --write
    python -m profiles.kwp.vocabulary --check      # spec against the pin

The closure itself is not vendored: it is 3.9 MB, it belongs to the ontology
repository, and what this profile needs from it is a few hundred terms. The
check runs against the checked-in snapshot and needs neither the file nor
rdflib, which is what lets it run on the cluster.

Author: Felix Vossel

## Functions

### build

```python
def build(closure: Path, mhpo: Path = None) -> dict
```

### load

```python
def load(path: Path = VOCABULARY_PATH) -> dict
```

### spec_terms

```python
def spec_terms(spec_raw: dict) -> dict
```

### carrier_problems

```python
def carrier_problems(spec_raw: dict, snapshot: dict) -> list
```

A carrier the ontology does not call a carrier, undeclared.

This profile is allowed to offer a heat source under `carrier` -- district
heat, geothermal, waste heat, which every plan writes in that column --
but it has to declare it, and the serializer drops the edge for exactly
the declared ones. Undeclared is the drift this exists to catch: a carrier
that is not one and nobody decided.

Stays in the profile because `outside_root` is this profile's answer to a
question the other one does not have.

### edges

```python
def edges(spec_raw: dict) -> list
```

Every triple shape this profile emits, the spec's and the writer's.

The `kg` blocks carry most of them and `kg.py` declares the handful that
sit behind no parameter, so the two together are the whole output and the
pin can be asked about all of it.

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
