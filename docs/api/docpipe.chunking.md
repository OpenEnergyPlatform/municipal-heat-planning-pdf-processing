# docpipe.chunking

`docpipe/chunking/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

\_\_init\_\_.py: Merges the preprocessing and visuals outputs, embeds
them, and indexes them.

Runs as a command line module:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db
      /path/to/faiss.index

## Exports

What `__all__` names, and where each name is defined:

- `run` from [docpipe.chunking.pipeline](docpipe.chunking.pipeline.md)

[Back to the index](../README.md)
