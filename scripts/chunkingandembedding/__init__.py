"""
chunkingandembedding – Merge preprocessing + imageprocessing outputs, embed them, index them.

Usage:
  python -m scripts.chunkingandembedding /data/processed/ /path/to/KWP.db /path/to/faiss.index
"""
from .pipeline import run

__all__ = ["run"]