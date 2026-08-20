"""
artifacts.py – The per-document files under ``<doc>/results/``, in the order
the pipeline writes them.

One definition for all five modules: a filename spelled out in four config.py
files drifts, and the module that reads it is rarely the one that wrote it.

Author: Felix Vossel
"""

DIR_RESULTS = "results"
DIR_IMAGES  = "images"

PAGES_JSON            = f"{DIR_RESULTS}/pages.json"             # preprocessing (extract)
SECTIONS_JSON         = f"{DIR_RESULTS}/sections.json"          # preprocessing (structure)
SECTIONS_REFINED_JSON = f"{DIR_RESULTS}/sections_refined.json"  # refinement
REFINEMENT_REPORT_JSON = f"{DIR_RESULTS}/refinement_report.json"  # refinement (what failed)
VISUALS_JSON          = f"{DIR_RESULTS}/visuals.json"           # visuals
DOCUMENT_JSON         = f"{DIR_RESULTS}/document.json"          # chunking (merge) → database
