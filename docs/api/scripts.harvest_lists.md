# scripts.harvest_lists

`scripts/harvest_lists.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

harvest_lists.py – Two lists a corpus run leaves for a curator to check.

A tuple's `unit` is the entry of the list the model read the passage as, and
`unit_raw` is what the passage prints. The lists in the ontology are known
to be incomplete, so the census of wordings is what a longer list is written
from: every wording a plan uses, beside the entry it was read as, and the
wordings that were read as no entry at all and refused for it ("kWh/m²a",
"kWp", "g/kWh"). A planning office's name is a second such census -- two
spellings of one office ("ecb energie.concept.bayern",
"energie.concept.bayern.") mint two different IRIs and nothing in the harvest
says so.

So: one row per unit as a plan actually writes it, with the entry it was
read as, and one row per organisation spelling, with the IRI key it
collapses onto. Neither is a filter that drops anything -- both are a
census, for a person to read once per run.

    python scripts/harvest_lists.py data/extraction/corpus_m5
    python scripts/harvest_lists.py <dir> --out-dir out --spec profiles/kwp/extraction_spec.json

No model, no database, no GPU: everything it prints was written by the run.

Author: Felix Vossel

## Functions

### default_spec_path

```python
def default_spec_path() -> Path
```

The active profile's extraction_spec.json, else kwp's.

### organisation_normaliser

```python
def organisation_normaliser(spec_path: Path)
```

The organisation-key function of the spec's own profile's `kg.py`.

Imported, not reimplemented: `profiles/<name>/kg.py` is what mints the
organisation IRI (`mint("organisation", normalise(name))`), so this is
the one function that decides which spellings share a node. It is a pure
string function with no rdflib or database import behind it.

### harvest_files

```python
def harvest_files(directory: Path) -> list
```

One file per plan, newest-glob order excluded: sorted for stable output.

### read_rows

```python
def read_rows(path: Path) -> list
```

The lines of one harvest file that parse as JSON objects. Skips the rest.

### unit_rows

```python
def unit_rows(files: list, spec) -> list
```

One row per (parameter, unit as written, unit chosen), a census only.

Counts a refusal too when its claim names a unit: a unit no list holds is
still a unit the plans use, and it is the row the list is grown from.
`listed` says whether the wording is itself an entry; a wording that is
not was read onto its entry by the model, which is what `unit_raw` is
kept for.

### organisation_parameters

```python
def organisation_parameters(spec) -> list
```

The spec's parameters that mint an organisation node, by `kg.node`.

### organisation_rows

```python
def organisation_rows(files: list, spec, normalise=None) -> list
```

One row per organisation name as a plan writes it.

`normalise` is the profile's own `kg.py` function; two names share
`iri_key` exactly when the profile's serializer would mint them the same
node. `related_names` catches the case that does not: two keys that do
not match but one contains the other, which is a spelling the profile
still mints as two organisations.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
