"""
__init__.py: Vision-LLM enrichment of tables and figures.

Reads the preprocessing pipeline's structured output plus its images/
directory and adds Markdown tables and figure descriptions.
"""
from .pipeline import run, run_single, run_batch

__all__ = ["run", "run_single", "run_batch"]