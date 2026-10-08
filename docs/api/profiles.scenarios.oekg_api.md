# profiles.scenarios.oekg_api

`profiles/scenarios/oekg_api.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

oekg_api.py – What the OEKG scenario-bundle API would be asked, and what it
would answer. A dry run: no request that writes is ever built into a call.

The platform takes a scenario bundle as one JSON body
(`POST /api/v0/scenario-bundles/`), mints every identifier itself and holds
the assembled bundle against the OEKG shapes before it writes anything. A
create is judged strictly, so one missing value refuses the whole bundle.
This module builds that body for every bundle of a harvest, from the same
reading kg.py writes its Turtle from, and holds it against the two things
the platform holds it against:

  the request schema   `ScenarioBundleCreate` in the platform's OpenAPI
                       description: the keys, their types, what is required.
  the shapes           `oekg_shapes.ttl`, over the bundle as the platform
                       would hold it after the create.

    python -m profiles.scenarios.oekg_api OUT DB --refresh
    python -m profiles.scenarios.oekg_api OUT DB --write bodies.jsonl
    python -m profiles.scenarios.oekg_api OUT DB --live

`--refresh` pulls SOURCES first; without it the files of the last refresh
are used, and `--openapi` / `--shapes` name local copies instead. `--live`
reads the platform's public bundle list, a GET, to say which acronyms are
taken: the acronym is unique over there and the only way to find a bundle
again, because no identifier of ours is accepted.

A body is not the Turtle in another syntax in four places, each on purpose:

  one bundle per project   Documents whose bundle has the same label are one
                           bundle with several study reports, as they are one
                           node in the Turtle, which mints the bundle from
                           its label. The oldest paper leads.
  a formed acronym         The platform demands one. A bundle no document
                           gives one is named after the first author and the
                           year of its leading paper, `Riahi-2021`. That is
                           made here, not read, and the run says how often.
  no IAM annotation        The Turtle types every factsheet an IAM scenario.
                           The platform's list does not hold that class yet
                           and refuses a create for it, so a body omits it.
  study region             The Turtle writes the parent property, the API the
                           one its closed scenario shape names.

Exit 0 is a report, whatever it says. Exit 2 is a run that could not be
made: no harvest, no database, no API description or no shapes.

The shape verdict is a model of the server, built from its documentation
and not from its code. It assumes what that documentation says: the server
mints a uuid on every study report and every scenario, a contact,
organisation, funder or author sent with a label alone is minted with that
label, and a region, a tag or a scenario type sent as an IRI is a node that
already exists over there with its own type and label. Where the model is
wrong the verdict is, and only a real create settles it.

Author: Felix Vossel

## Classes

### RequestSchema

```python
class RequestSchema
```

`ScenarioBundleCreate` of one OpenAPI description, ready to ask.

#### RequestSchema.\_\_init\_\_

```python
def __init__(self, openapi: dict)
```

#### RequestSchema.problems

```python
def problems(self, payload: dict) -> list
```

## Functions

### refresh

```python
def refresh(cache: Path = upstream.CACHE) -> dict
```

Pull SOURCES and write their lock.

### labels

```python
def labels(cache: Path = upstream.CACHE) -> dict
```

{IRI: label} for what a body references and a verdict names.

The regions and the terms this profile's snapshot holds are checked in.
A property the shapes name and the spec does not is in neither, so the
OEO closure of the last `vocabulary --refresh` is read where there is
one; without it such a path is named by its identifier alone.

### merge

```python
def merge(studies: list) -> list
```

One study per bundle: the documents of one project, together.

kg.py mints a bundle from its label, so two papers of one project already
are one bundle with two reports in the Turtle. A create is one body per
bundle, and the body of each paper alone would make several bundles of
one study. The oldest paper leads: its spelling labels the bundle and
its abstract is the bundle's, of which the shapes allow one. An acronym
is the one most of the documents give.

The label alone decides, as it does in the Turtle. An acronym two
documents share does not: a harvest pairs a project's name with another
project's acronym often enough (a paper thanks two projects) that
joining on it would chain unrelated papers into one bundle. Such a pair
stays two bundles and is reported for its acronym.

### form_acronyms

```python
def form_acronyms(bundles: list) -> None
```

Name every bundle no document gives an acronym: `Riahi-2021`.

The first author and the year of the leading paper. Made here and not
read anywhere, so the bundle says so in `formed`. Two that come out the
same are told apart by a number, in the order of their documents, which
keeps the name the same from one run over a harvest to the next. A paper
without an author or without a date gets none, and stays refused.

### body

```python
def body(study: dict, known: dict) -> dict
```

The create body for one merged study.

A value the harvest does not hold is a key the body does not carry. An
empty string or an empty list would pass the schema and say something
the document did not, and the refusal for the missing key is the finding.

### schema_problems

```python
def schema_problems(payload: dict, openapi: dict) -> list
```

What the request schema says against one body.

### list_problems

```python
def list_problems(shapes) -> list
```

Where a choice list of the spec and the shapes' list for it differ.

The model picks a tag or a scenario type from a list the spec copied
from the shapes. A class the shapes dropped would be harvested and then
refused; one they gained could never be chosen.

### graph

```python
def graph(payload: dict, known: dict)
```

The bundle as the platform would hold it after creating this body.

The model the module docstring names. Local IRIs stand in for the ones
the server mints; nothing here is written anywhere. A key the model does
not cover raises: a verdict over half a body would read as a verdict.

### shape_problems

```python
def shape_problems(data, shapes, known: dict) -> list
```

What the shapes say against one bundle graph.

### platform_acronyms

```python
def platform_acronyms(url: str = LIST_URL) -> dict
```

{acronym: label} of the bundles the platform lists. Public, a GET.

A bundle listed without an acronym has nothing to compare and is left
out, so the size of this is a count of acronyms, not of bundles.

### acronym_problems

```python
def acronym_problems(entries: list, taken: Optional[dict] = None) -> None
```

Add to each entry what stands against its acronym.

Compared without case and outer spaces. The platform's own rule may be
narrower; two bundles that differ in case alone are one study either way.

### dry_run

```python
def dry_run(harvest: Path, db: Path, openapi: dict, shapes,
            known: dict, taken: Optional[dict] = None) -> tuple
```

(entries, documents without a study) for a harvest directory.

An entry is one request as it would be sent, and every reason the
platform would refuse it: {documents, formed, method, path, body,
problems}. `documents` are the harvest files the bundle was read from,
the leading one first; `formed` names what was made here and not read.

### report

```python
def report(entries: list, without: list, taken: Optional[dict] = None,
           lists: Optional[list] = None) -> str
```

The run in English, one line per kind of refusal.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
