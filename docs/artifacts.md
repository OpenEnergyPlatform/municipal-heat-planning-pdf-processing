# What each stage leaves behind

Generated from `docpipe/artifacts.py` by `scripts/build_docs.py`: the names below and the stage against each are that module's own constants and its own comments.

artifacts.py – The per-document files under ``<doc>/results/``, in the order
the pipeline writes them.

One definition for all five modules: a filename spelled out in four config.py
files drifts, and the module that reads it is rarely the one that wrote it.

Author: Felix Vossel

## Directories

| name | path |
|---|---|
| `DIR_RESULTS` | `results` |
| `DIR_IMAGES` | `images` |

## Files

| name | path | written by |
|---|---|---|
| `PAGES_JSON` | `results/pages.json` | preprocessing (extract) |
| `SECTIONS_JSON` | `results/sections.json` | preprocessing (structure) |
| `PAGE_TRANSCRIPTION_REPORT_JSON` | `results/page_transcription_report.json` | preprocessing (model-read pages) |
| `SECTIONS_REFINED_JSON` | `results/sections_refined.json` | refinement |
| `REFINEMENT_REPORT_JSON` | `results/refinement_report.json` | refinement (what failed) |
| `VISUALS_JSON` | `results/visuals.json` | visuals |
| `DOCUMENT_JSON` | `results/document.json` | chunking (merge) → database |

[Back to the index](README.md)
