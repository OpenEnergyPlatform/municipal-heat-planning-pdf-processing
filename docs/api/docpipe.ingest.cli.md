# docpipe.ingest.cli

`docpipe/ingest/cli.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

cli.py: Command line for registering a profile's documents.

The work lives in `pipeline.py` (generic) and in the profile's `source.py`
(where its documents come from); this module is only the entry point. The
database and the PDF directory default to the profile's own.

Author: Felix Vossel

## Functions

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> None
```

[Back to the index](../README.md)
