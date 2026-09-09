# docpipe.inference.catalog

`docpipe/inference/catalog.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

catalog.py: Presents a corpus for selection.

Retrieval only ever needs a document id. Everything around that id,
what a document is called in the picker, which filters make sense
over the corpus, what to show about the selected one, is project
knowledge. The core supplies a plain default over the `Documents`
table; a profile replaces it with its own
(`profiles/<name>/catalog.py: CATALOG`) and fills the facets it
declared.

Author: Felix Vossel

## Classes

### Entry

```python
@dataclass
class Entry
```

One selectable document, as the picker needs it.

Fields:

- `id: int`
- `label: str`
- `facets: dict = field(default_factory=dict)`: facet field -> the values this document has (a plan may cover several municipalities, so a document can sit under more than one value)
- `detail: Sequence = ()`: (heading, lines) blocks shown for the selected document
- `row: Any = None`

### Catalog

```python
class Catalog
```

The generic catalog: the core Documents table and nothing else.

#### Catalog.\_\_init\_\_

```python
def __init__(self, profile=None)
```

#### Catalog.facets

```python
@property
def facets(self) -> Sequence
```

#### Catalog.document_noun

```python
@property
def document_noun(self) -> str
```

#### Catalog.rows

```python
def rows(self, conn: sqlite3.Connection,
         include_superseded: bool = False) -> list
```

Documents for the picker, current ones first.

#### Catalog.facet_values

```python
def facet_values(self, conn: sqlite3.Connection, rows: Sequence) -> dict
```

document id -> {facet field: [values]}. The core knows no facets.

#### Catalog.label

```python
def label(self, row, facets: Optional[dict] = None) -> str
```

#### Catalog.detail

```python
def detail(self, row, facets: Optional[dict] = None) -> Sequence
```

#### Catalog.entries

```python
def entries(self, conn: sqlite3.Connection,
            include_superseded: bool = False) -> list
```

Everything the picker shows, in one pass over the corpus.

## Functions

### format_published

```python
def format_published(published: Any) -> str
```

The stored publish token, readable: 20240708 → 2024-07-08, 2023q4 → 2023 Q4.

### facet_options

```python
def facet_options(entries: Sequence[Entry], facets: Sequence) -> dict
```

facet field -> its values across `entries`.

A facet nothing carries a value for is left out entirely: a corpus whose
project metadata was never imported should offer no filter rather than an
empty one that silently matches nothing.

### apply_filters

```python
def apply_filters(entries: Sequence[Entry], selections: Optional[dict]) -> list
```

Entries matching every active filter — AND across facets, OR within one.

### load_catalog

```python
def load_catalog(profile=None) -> Catalog
```

The profile's catalog, or the generic one.

[Back to the index](../README.md)
