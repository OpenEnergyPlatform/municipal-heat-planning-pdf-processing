# profiles.kwp.extraction

`profiles/kwp/extraction.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Extraction stage wiring: where the kwp spec and its anchors live.

## Functions

### document_context

```python
def document_context(conn, document_id: int) -> dict
```

What this plan says about itself, for the sentence it is searched with.

The municipality, because a plan writes its own name into headings,
captions and table titles, and a search anchor that carries it ranks this
plan's own sections above the boilerplate every plan shares. It lives in
the catalog join and in no query the core makes, so the core asks the
profile for it rather than growing a second idea of what a document is.

Missing metadata is not an error here. The anchor is written from the
ontology annotation either way and this only makes it sharper.

[Back to the index](../README.md)
