"""
Preprocessing module for PDF document layout analysis and structuring.

This module orchestrates a four-stage pipeline for extracting and structuring
content from PDF documents:
  1. Text extraction via PyMuPDF
  2. Layout detection using PP-DocLayoutV3
  3. Section assembly and structuring
  4. LLM-based refinement via Ollama

Usage:
  python -m scripts.preprocessing input.pdf ./output
  python -m scripts.preprocessing ./pdf_folder/ ./output
"""
from .pipeline import run, run_single, run_folder, main

__all__ = ["run", "run_single", "run_folder", "main"]
