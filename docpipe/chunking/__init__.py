"""
chunking – Merge the preprocessing and visuals outputs, embed them, index them.

Usage:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db /path/to/faiss.index
"""
from .pipeline import run

__all__ = ["run"]