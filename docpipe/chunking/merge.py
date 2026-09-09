"""
merge.py: Merges the preprocessing and imageprocessing outputs as
chunking's first step.

Replaces each table and figure in sections_refined.json with its
enriched counterpart from visuals.json, matched by item id, and
writes the result to document.json with an atomic replace. A
directory is cached and skipped on rerun once document.json is newer
than both inputs, unless force is set.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Optional

from .config import SECTIONS_REFINED_JSON, VISUALS_JSON, DOCUMENT_JSON
from .models import MergeStats

log = logging.getLogger(__name__)


def _build_enriched_lookup(images_data: dict) -> dict[str, dict]:
    """
    Build an id-to-item dict from the images JSON.

    Only enriched items are included: tables need a `markdown`, figures a
    `description`.
    """
    lookup: dict[str, dict] = {}
    for section in images_data.get("sections", []):
        for t in section.get("tables", []):
            if t.get("markdown"):
                lookup[t["id"]] = t
        for f in section.get("figures", []):
            if f.get("description"):
                lookup[f["id"]] = f
    return lookup


def _is_cached(output_dir: Path) -> bool:
    """
    True if this directory's output.json can be reused as-is.

    Stale once either input is newer — Stage 5 rewrites its images JSON on every
    run, including the fully-cached one, and its enrichment would otherwise never
    reach the merge. A zero-byte file counts as absent so a killed run re-merges
    rather than serving a truncated cache, and an unreadable directory counts as
    uncached so merge_batch fails that one entry instead of the whole corpus.
    """
    try:
        merged = (output_dir / DOCUMENT_JSON).stat()
        if merged.st_size == 0:
            return False
        inputs = [p.stat().st_mtime_ns
                  for p in (output_dir / SECTIONS_REFINED_JSON, output_dir / VISUALS_JSON)
                  if p.exists()]
    except OSError:
        return False
    return max(inputs, default=0) <= merged.st_mtime_ns


def merge_single(output_dir: Path, *, force: bool = False) -> Optional[dict]:
    """
    Merge final + images JSONs for a single PDF output directory.

    Sections come from sections_refined.json; each table/figure is
    replaced by its enriched counterpart from visuals.json,
    matched by item id. Writes output.json and returns the merged dict, or
    None if the final JSON is missing. `force` re-merges past a cached
    output.json.
    """
    output_dir = Path(output_dir)
    merged_path = output_dir / DOCUMENT_JSON

    if not force and _is_cached(output_dir):
        log.debug("Merge cache hit: %s", merged_path)
        with open(merged_path, "r", encoding="utf-8") as f:
            return json.load(f)

    final_path = output_dir / SECTIONS_REFINED_JSON
    images_path = output_dir / VISUALS_JSON

    if not final_path.exists():
        log.error("Final JSON not found: %s", final_path)
        return None

    with open(final_path, "r", encoding="utf-8") as f:
        final_data = json.load(f)

    enriched_lookup: dict[str, dict] = {}
    if images_path.exists():
        with open(images_path, "r", encoding="utf-8") as f:
            images_data = json.load(f)
        enriched_lookup = _build_enriched_lookup(images_data)
        log.debug("Loaded %d enriched items from %s", len(enriched_lookup), images_path)
    else:
        log.warning("Images JSON not found: %s – merging without enrichment", images_path)

    stats = MergeStats()
    merged = copy.deepcopy(final_data)

    for section in merged["sections"]:
        stats.total_sections += 1

        new_tables = []
        for t in section.get("tables", []):
            if t["id"] in enriched_lookup:
                new_tables.append(enriched_lookup[t["id"]])
                stats.tables_merged += 1
            else:
                new_tables.append(t)
                if enriched_lookup:
                    stats.tables_missing += 1
        section["tables"] = new_tables

        new_figures = []
        for fig in section.get("figures", []):
            if fig["id"] in enriched_lookup:
                new_figures.append(enriched_lookup[fig["id"]])
                stats.figures_merged += 1
            else:
                new_figures.append(fig)
                if enriched_lookup:
                    stats.figures_missing += 1
        section["figures"] = new_figures

    # Atomic write: a killed job must not leave a half-written output.json that
    # the next run's cache check accepts.
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = merged_path.with_name(merged_path.name + ".part")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, merged_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    log.info(
        "Merged: %d sections, %d/%d tables enriched, %d/%d figures enriched"
        " (%d tables missing, %d figures missing)",
        stats.total_sections,
        stats.tables_merged, stats.tables_merged + stats.tables_missing,
        stats.figures_merged, stats.figures_merged + stats.figures_missing,
        stats.tables_missing, stats.figures_missing,
    )

    return merged


def merge_batch(root_dir: Path, *, force: bool = False) -> dict[str, bool]:
    """Run merge for every PDF subdirectory under root_dir."""
    root_dir = Path(root_dir)
    results: dict[str, bool] = {}

    candidates = sorted(
        d for d in root_dir.iterdir()
        if d.is_dir() and (d / SECTIONS_REFINED_JSON).exists()
    )

    if not candidates:
        log.warning("No PDF output directories found in '%s'.", root_dir)
        return results

    log.info("Merge: %d directories in '%s'", len(candidates), root_dir)

    cached = 0
    for i, d in enumerate(candidates):
        # Same predicate merge_single uses, checked here so a cache hit costs a
        # stat instead of parsing a merged JSON whose dict this loop discards.
        if not force and _is_cached(d):
            results[d.name] = True
            cached += 1
            continue
        log.info("[%d/%d] Merging %s", i + 1, len(candidates), d.name)
        try:
            result = merge_single(d, force=force)
            results[d.name] = result is not None
        except Exception as e:
            log.error("Error merging '%s': %s", d.name, e, exc_info=True)
            results[d.name] = False

    ok = sum(1 for v in results.values() if v)
    log.info("Merge complete: %d/%d succeeded (%d cached)", ok, len(candidates), cached)
    return results