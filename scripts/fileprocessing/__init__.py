"""
__init__.py: CLI entry point for registering a profile's source PDFs.

The generic half lives in docpipe.ingest, the project-specific half in
profiles/<name>/source.py.

Runs as a command line module:
  python -m scripts.fileprocessing --profile kwp --source kww.xlsx
      --db data/kwp/kwp.db --data-dir data/kwp/pdf
"""
from .pipeline import main

__all__ = ["main"]
