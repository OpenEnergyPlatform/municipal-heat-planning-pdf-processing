# docpipe.builtin.default.catalog

`docpipe/builtin/default/catalog.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

catalog.py – How documents present themselves in the picker when nothing is
known about them but what the source wrote into DocumentMeta.

Every filter the profile declares is filled from the DocumentMeta column of
the same name. So a profile that extends this one adds a column to its
schema, lets its source fill it, declares the facet, and has the filter.

A document is shown by its title, which the folder source takes from the
PDF's own information dictionary and sets to the file name where the PDF has
none, and by its date, the creation date of the same dictionary.

Author: Felix Vossel

## Classes

### MetaCatalog

```python
class MetaCatalog(Catalog)
```

The Documents table with the profile's DocumentMeta beside it.

#### MetaCatalog.rows

```python
def rows(self, conn: sqlite3.Connection,
         include_superseded: bool = False) -> list
```

#### MetaCatalog.facet_values

```python
def facet_values(self, conn: sqlite3.Connection, rows) -> dict
```

document id -> {facet field: [value]}, for the facets that are a
DocumentMeta column.

#### MetaCatalog.label

```python
def label(self, row, facets: Optional[dict] = None) -> str
```

The title, else the file name, and the date where there is one.
No current/old tag: a folder has no versions, every file is its own
document.

[Back to the index](../README.md)
