# profiles.scenarios.catalog

`profiles/scenarios/catalog.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

catalog.py – How AR6 publications present themselves in the picker: by title
and year, filtered by year, venue and the scenarios they document.

Author: Felix Vossel

## Classes

### Ar6Catalog

```python
class Ar6Catalog(Catalog)
```

The bibliographic view of the corpus.

#### Ar6Catalog.rows

```python
def rows(self, conn: sqlite3.Connection,
         include_superseded: bool = False) -> list
```

Publications for the picker, newest first. Rows carry the core
columns plus the DocumentMeta ones.

#### Ar6Catalog.facet_values

```python
def facet_values(self, conn: sqlite3.Connection, rows) -> dict
```

document id -> {year, venue, scenario}.

#### Ar6Catalog.label

```python
def label(self, row, facets: Optional[dict] = None) -> str
```

Title and year — the DOI, then the crawl slug, while the title is
unknown. No current/old tag: every publication is its own version
group, so it would be on every entry.

#### Ar6Catalog.detail

```python
def detail(self, row, facets: Optional[dict] = None)
```

[Back to the index](../README.md)
