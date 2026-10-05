# docpipe.serve.cli

`docpipe/serve/cli.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

cli.py: `docpipe export` and `docpipe serve`.

    docpipe export HARVEST_DIR --out values.csv
    docpipe export HARVEST_DIR --format jsonl --level B --out values.jsonl
    docpipe serve HARVEST_DIR --http [--port 8750]
    docpipe serve HARVEST_DIR --mcp

Both read the harvest once (`values.py`). With a profile the values carry
the labels of its spec and the transcribed mark of its database; without
one they carry what the harvest itself says.

Author: Felix Vossel

## Functions

### open_store

```python
def open_store(args) -> Values
```

The value store the arguments name.

### export_main

```python
def export_main(argv: Optional[Sequence[str]] = None) -> int
```

### serve_main

```python
def serve_main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
