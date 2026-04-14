"""
chunkingandembedding – Merge, embed, and index pipeline outputs.

Standalone module that combines the output of imageprocessing and
preprocessing, creates embeddings (textual and vision-language),
and updates the database.

Usage:
  python -m scripts.chunkingandembedding /data/processed/ /path/to/KWP.db /path/to/faiss.index
"""
from .pipeline import run

__all__ = ["run"]