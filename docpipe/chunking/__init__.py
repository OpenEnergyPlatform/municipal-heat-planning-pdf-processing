"""
__init__.py: Merges the preprocessing and visuals outputs, embeds
them, and indexes them.

Runs as a command line module:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db
      /path/to/faiss.index
"""
from .pipeline import run

__all__ = ["run"]