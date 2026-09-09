# profiles.kwp.catalog

`profiles/kwp/catalog.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

catalog.py – How heat plans present themselves in the picker.

Plans are published per municipality, sometimes as one convoy plan for several
of them; the label has to say which, and the filters are municipality,
Bundesland and year. All of that is project knowledge, so it lives here and not
in docpipe.

Author: Felix Vossel

## Classes

### KwpCatalog

```python
class KwpCatalog(Catalog)
```

The municipal view of the corpus: who a plan covers, and where.

#### KwpCatalog.rows

```python
def rows(self, conn: sqlite3.Connection,
         include_superseded: bool = False) -> list
```

Documents for the picker, newest/current first. Only current versions
(is_current=1) unless include_superseded.

Rows carry the core columns plus municipality_ags, organisation_unit,
municipality_name and organisation_unit_name.

#### KwpCatalog.facet_values

```python
def facet_values(self, conn: sqlite3.Connection, rows) -> dict
```

document id -> {gemeinde, bundesland_lang, jahr}.

#### KwpCatalog.label

```python
def label(self, row, facets: Optional[dict] = None) -> str
```

#### KwpCatalog.detail

```python
def detail(self, row, facets: Optional[dict] = None)
```

## Functions

### municipality_coverage

```python
def municipality_coverage(conn: sqlite3.Connection, documents) -> dict
```

Map each document id → the sorted list of municipalities it covers.

The register decides: every municipality whose plan link resolves to this
document's file. Only a corpus without imported register metadata falls
back to `_covered_names`, computed over the SAME `documents` set passed in
so sibling-plan claims match what the picker shows.

### document_label

```python
def document_label(row, covered: Optional[list] = None) -> str
```

Plan-centric picker label.

`covered` = the municipalities this plan covers (from municipality_coverage).
A plan covering several is labelled by its administrative unit + the count,
one covering a single municipality by that municipality. If `covered` is
omitted, falls back to the plan's own municipality_name.

[Back to the index](../README.md)
