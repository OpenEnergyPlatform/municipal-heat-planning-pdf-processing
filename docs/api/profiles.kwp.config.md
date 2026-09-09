# profiles.kwp.config

`profiles/kwp/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Constants for the fileprocessing module. The schema lives in docpipe/store
plus profiles/\<name>/schema.sql.

## Functions

### link_filename

```python
def link_filename(link) -> str
```

A KWW "Link Wärmeplan" reduced to the local file name it becomes.

Ingest names documents this way and the catalog looks them up this way, so
the two must not drift: whoever changes it changes both at once.

[Back to the index](../README.md)
