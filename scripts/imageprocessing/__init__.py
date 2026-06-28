"""
imageprocessing – Vision-LLM enrichment of tables and figures.

Standalone module that builds on the output of the preprocessing pipeline.
Reads structured_output_final.json and the images/ directory, sends each
table/figure to a vision model (Qwen3-VL served by vLLM) concurrently, and
produces enriched_output.json with Markdown tables and figure descriptions.

Usage:
  python -m scripts.imageprocessing ./output/my_pdf
  python -m scripts.imageprocessing ./output/ --batch
"""
from .pipeline import run, run_single, run_batch

__all__ = ["run", "run_single", "run_batch"]