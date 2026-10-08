# docpipe.serve.cli

`docpipe/serve/cli.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

cli.py: `docpipe export` and `docpipe serve`.

    docpipe export HARVEST_DIR --out values.csv
    docpipe export HARVEST_DIR --format jsonl --level B --out values.jsonl
    docpipe export HARVEST_DIR --what states --out states.csv
    docpipe export HARVEST_DIR --what refusals --out refusals.csv
    docpipe serve HARVEST_DIR --http [--port 8750]
    docpipe serve HARVEST_DIR --mcp

Both read the harvest once (`values.py`). With a profile the values carry
the labels of its spec and the transcribed mark of its database; without
one they carry what the harvest itself says.

The corpus database is named as the chat names it: `--db`, else
INFERENCE_DB_PATH, else the profile's when it is there. `serve` opens the
passage search on it (`passages.py`); without a database, or without the
word index `docpipe lexical` builds, the search says so and answers none.
`export` does not need the passages and does not open them.

Author: Felix Vossel

## Functions

### open_store

```python
def open_store(args, search: bool = False) -> Values
```

The value store the arguments name, with the passage search on its
database where *search* asks for it. Opening the search checks the word
index against the whole database, which an export has no use for.

### export_main

```python
def export_main(argv: Optional[Sequence[str]] = None) -> int
```

### serve_main

```python
def serve_main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
