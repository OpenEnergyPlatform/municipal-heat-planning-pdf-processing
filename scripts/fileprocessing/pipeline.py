"""
pipeline.py: The earlier name of stage 1's command line.

`python -m scripts.fileprocessing` keeps working with the same arguments;
the entry point itself is `docpipe ingest` (docpipe/ingest/cli.py).

Author: Felix Vossel
"""
from docpipe.ingest.cli import main

__all__ = ["main"]
