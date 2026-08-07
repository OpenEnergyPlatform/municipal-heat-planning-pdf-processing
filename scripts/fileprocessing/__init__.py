"""
fileprocessing – CLI entry point for registering a profile's source PDFs.

The generic half lives in docpipe.ingest, the KWW half in profiles/kwp/source.py.

Usage:
  python -m scripts.fileprocessing --profile kwp --excel kww.xlsx --db data/kwp/kwp.db --data-dir data/kwp/pdf
"""
from .pipeline import main

__all__ = ["main"]
