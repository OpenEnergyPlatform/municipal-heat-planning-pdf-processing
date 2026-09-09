# scripts.fileprocessing

`scripts/fileprocessing/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

\_\_init\_\_.py: CLI entry point for registering a profile's source PDFs.

The generic half lives in docpipe.ingest, the project-specific half in
profiles/\<name>/source.py.

Runs as a command line module:
  python -m scripts.fileprocessing --profile kwp --source kww.xlsx
      --db data/kwp/kwp.db --data-dir data/kwp/pdf

## Exports

What `__all__` names, and where each name is defined:

- `main` from [scripts.fileprocessing.pipeline](scripts.fileprocessing.pipeline.md)

[Back to the index](../README.md)
