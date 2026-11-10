# docpipe.sources

`docpipe/sources.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

sources.py: Where a profile's ontology, shapes and graph come from, read
from a file of the profile.

A profile's lists are drawn from an ontology, its graph is written to the
shapes of a knowledge graph, and some of its lists are what that graph
already holds. Until 2026-11-10 the addresses stood in the profile's Python
(`vocabulary.py: SOURCES`, the roots of its lists in `SETS`); since then they
stand beside its spec, so that `docpipe edit` shows them and can fetch them
(owner, 2026-11-10: "einfach die URLs angeben für Ontologie und KG"):

    <profile folder>/sources.json

    {"sources": {name: {"kind": ..., ...}},     what `upstream.fetch` pulls
     "lists": {name: {"kind": "class" | "individual", "root": IRI}},
     "axis_lists": {coordinate: list name}}     which list a coordinate
                                                answers from

A source is one of the kinds `upstream` fetches, with the keys that kind
reads (`KEYS`); a token is never in the file, only the name of the setting
that holds it (`token_env`). The file is read strictly: an unknown kind, a
missing key, a key no kind reads, a list without its root is refused with
the file and the source named. Nothing here fetches anything.

Author: Felix Vossel

## Classes

### SourcesError

```python
class SourcesError(ValueError)
```

A sources file a run cannot read. It names the file and the
source.

### Sources

```python
@dataclass(frozen=True)
class Sources
```

Fields:

- `sources: dict = field(default_factory=dict)`
- `lists: dict = field(default_factory=dict)`
- `axis_lists: dict = field(default_factory=dict)`
- `path: Optional[Path] = None`
- `sha256: str = ""`

#### Sources.sets

```python
def sets(self) -> dict
```

{list name: (kind, root)}, as the vocabulary builders take it.

## Functions

### source_problem

```python
def source_problem(name: str, source) -> Optional[str]
```

Why *source* is no source a run can fetch, None where it is.

### parse

```python
def parse(raw: str, where) -> Sources
```

The sources of the text *raw*, read strictly.

### dump

```python
def dump(sources: Sources, newline: str = "\n") -> str
```

### path_of

```python
def path_of(profile) -> Path
```

### load

```python
def load(profile) -> Sources
```

The sources of *profile*: its own file, else that of the nearest
profile it extends; empty where none writes one.

### of

```python
def of(name: str) -> Sources
```

The sources of the profile called *name*.

[Back to the index](../README.md)
