"""
models.py – Data structures for the chunkingandembedding module.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MergeStats:
    """Statistics for the merge step."""
    total_sections: int = 0
    tables_merged: int = 0
    figures_merged: int = 0
    tables_missing: int = 0
    figures_missing: int = 0