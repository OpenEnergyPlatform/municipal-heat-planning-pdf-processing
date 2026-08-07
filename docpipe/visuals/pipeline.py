"""
pipeline.py – Orchestration of the imageprocessing module.

Enriches one PDF's output directory, or all PDF subdirectories under a root
(--batch), via a vision LLM. See ``_build_parser`` for the CLI.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from docpipe import prompts
from docpipe.profile import add_profile_argument, resolve_profile

from .config import (
    PROMPT_IDS,
    VLM_MODEL,
    VLM_BASE_URL,
    VLM_NUM_PARALLEL,
    FINAL_OUTPUT_JSON,
    STRUCTURED_OUTPUT_JSON,
    ENRICHED_OUTPUT_JSON,
    dump_json_atomic,
)
from .models import ProcessingStats
from .vision import create_client, check_model_available
from .process import process_table, process_figure

log = logging.getLogger(__name__)

# Documents (PDF output dirs) enriched concurrently.
# Total in-flight requests ≈ DOC_PARALLEL × VLM_NUM_PARALLEL.
DOC_PARALLEL = int(os.environ.get("DOC_PARALLEL", "8"))


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------

def _resolve_input(output_dir: Path) -> Optional[Path]:
    """
    Best available input JSON inside a preprocessing output_dir: the Stage-4
    output, else the Stage-3 one. None if neither exists.
    """
    for candidate in (FINAL_OUTPUT_JSON, STRUCTURED_OUTPUT_JSON):
        p = output_dir / candidate
        if p.exists():
            return p
    return None


def _load_source_texts(output_dir: Path) -> dict[str, str]:
    """
    Maps table id → PyMuPDF source text, for the table QA gate. Empty if
    unreadable.

    Always read from the Stage-3 structured_output.json rather than the chosen
    input: Stage 4 does not preserve source_text.
    """
    p = output_dir / STRUCTURED_OUTPUT_JSON
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not read source texts (%s)", e)
        return {}
    out: dict[str, str] = {}
    for section in data.get("sections", []):
        for t in section.get("tables", []):
            if t.get("source_text"):
                out[t["id"]] = t["source_text"]
    return out


# ---------------------------------------------------------------------------
# Single-directory processing
# ---------------------------------------------------------------------------

def run_single(
    output_dir: Path,
    *,
    input_json: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    force_stale: bool = False,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[dict]:
    """
    Sends each table/figure image in one PDF's output directory to the vision
    model and writes the enriched output.

    Caching is item-level: tables that already have a "markdown" key and figures
    that already have a "description" key are reused from a previous enriched
    output unless *force* is set. *input_json* is relative to *output_dir*.

    Returns:
        Enriched data dict, or None on failure.
    """
    output_dir = Path(output_dir)
    model = model or VLM_MODEL
    out_path = output_dir / ENRICHED_OUTPUT_JSON

    changed = prompts.check(output_dir, PROMPT_IDS) if out_path.exists() else []
    if changed and not force:
        if force_stale:
            log.info("Prompts changed (%s) – re-describing every item",
                     ", ".join(changed))
            force = True
        else:
            log.warning("Cached items were described with older prompts (%s); "
                        "re-run with --force-stale to redo them", ", ".join(changed))

    cached_items: dict[str, dict] = {}       # id → cached table/figure dict
    if out_path.exists() and not force:
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            for section in cached_data.get("sections", []):
                for t in section.get("tables", []):
                    if t.get("markdown"):
                        cached_items[t["id"]] = t
                for fig in section.get("figures", []):
                    if fig.get("description"):
                        cached_items[fig["id"]] = fig
            if cached_items:
                log.info(
                    "Loaded %d cached items from previous run: %s",
                    len(cached_items), out_path,
                )
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Could not load cache (%s), processing all items", e)

    if input_json:
        src_path = output_dir / input_json
    else:
        src_path = _resolve_input(output_dir)

    if src_path is None or not src_path.exists():
        log.error("No input file found in: %s", output_dir)
        return None

    log.info("Loading: %s", src_path)
    with open(src_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stats = ProcessingStats()
    pending_tables = 0
    pending_figures = 0

    for section in data["sections"]:
        for t in section.get("tables", []):
            stats.total_tables += 1
            if t["id"] not in cached_items:
                pending_tables += 1
        for fig in section.get("figures", []):
            stats.total_figures += 1
            if fig["id"] not in cached_items:
                pending_figures += 1

    cached_tables = stats.total_tables - pending_tables
    cached_figures = stats.total_figures - pending_figures

    log.info(
        "Found: %d tables (%d cached, %d pending), "
        "%d figures (%d cached, %d pending) in %d sections",
        stats.total_tables, cached_tables, pending_tables,
        stats.total_figures, cached_figures, pending_figures,
        len(data["sections"]),
    )

    stats.processed_tables = cached_tables
    stats.processed_figures = cached_figures

    if dry_run:
        log.info("Dry-run – skipping processing.")
        log.info(stats.summary())
        return data

    # Everything cached → skip the server, but still merge and write.
    if pending_tables == 0 and pending_figures == 0:
        log.info("All items cached – nothing to process.")
        log.info(stats.summary())
        enriched = _merge_cache(data, cached_items)
        _strip_source_text(enriched)
        dump_json_atomic(enriched, out_path)
        return enriched

    client = create_client(base_url=base_url)
    if not check_model_available(client, model):
        log.error(
            "Model '%s' not available at the vLLM endpoint. Serve it with: "
            "vllm serve <model> --served-model-name %s",
            model, model,
        )
        return None

    # Build the worklist: fill cached items in place, collect pending.
    enriched = copy.deepcopy(data)
    # (kind, section_index, item_index, item, section)
    tasks: list[tuple[str, int, int, dict, dict]] = []

    for si, section in enumerate(enriched["sections"]):
        for ti, t in enumerate(section.get("tables", [])):
            if t["id"] in cached_items:
                section["tables"][ti] = cached_items[t["id"]]
            else:
                tasks.append(("table", si, ti, t, section))
        for fi, f in enumerate(section.get("figures", [])):
            if f["id"] in cached_items:
                section["figures"][fi] = cached_items[f["id"]]
            else:
                tasks.append(("figure", si, fi, f, section))

    log.info(
        "Processing %d pending items with %d parallel slots",
        len(tasks), VLM_NUM_PARALLEL,
    )
    lock = threading.Lock()
    source_texts = _load_source_texts(output_dir)

    def _enrich(task: tuple) -> tuple:
        kind, si, ti, item, section = task
        try:
            if kind == "table":
                res = process_table(
                    item, section, output_dir, client, stats,
                    model=model, lock=lock,
                    source_text=source_texts.get(item["id"], ""),
                )
            else:
                res = process_figure(
                    item, section, output_dir, client, stats,
                    model=model, lock=lock,
                )
        except Exception as e:  # never let one item kill the whole run
            log.error("  ✗ %s %s crashed: %s", kind, item.get("id", "?"), e)
            res = item
        return kind, si, ti, res

    if tasks:
        with ThreadPoolExecutor(max_workers=VLM_NUM_PARALLEL) as ex:
            for kind, si, ti, res in ex.map(_enrich, tasks):
                key = "tables" if kind == "table" else "figures"
                enriched["sections"][si][key][ti] = res

    # Write unconditionally, to persist partial progress.
    _strip_source_text(enriched)
    log.info("Writing: %s", out_path)
    dump_json_atomic(enriched, out_path)
    prompts.record(output_dir, PROMPT_IDS)

    log.info(stats.summary())
    return enriched


def _strip_source_text(enriched: dict) -> None:
    """Drop the QA-only source_text from every table before writing the output.

    process_table already strips it on the normal path; this also covers the
    crash-fallback branch.
    """
    for section in enriched.get("sections", []):
        for t in section.get("tables", []):
            if isinstance(t, dict):
                t.pop("source_text", None)


def _merge_cache(data: dict, cached_items: dict[str, dict]) -> dict:
    """Merges cached table/figure dicts into a fresh data structure."""
    merged = copy.deepcopy(data)
    for section in merged["sections"]:
        section["tables"] = [
            cached_items.get(t["id"], t) for t in section.get("tables", [])
        ]
        section["figures"] = [
            cached_items.get(f["id"], f) for f in section.get("figures", [])
        ]
    return merged


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def run_batch(
    root_dir: Path,
    **kwargs,
) -> dict[str, bool]:
    """
    Runs enrichment for every subdirectory under *root_dir* that contains one of
    the expected structured output JSONs.

    Returns:
        Dict mapping directory name → success boolean.
    """
    root_dir = Path(root_dir)
    results: dict[str, bool] = {}

    candidates = sorted(
        d for d in root_dir.iterdir()
        if d.is_dir() and _resolve_input(d) is not None
    )

    if not candidates:
        log.warning("No PDF output directories found in '%s'.", root_dir)
        return results

    sep = "=" * 60
    log.info(sep)
    log.info("Batch: %d directories in '%s'", len(candidates), root_dir)
    for d in candidates:
        log.info("  - %s", d.name)
    log.info(sep)

    def _process(d: Path) -> tuple[str, bool]:
        try:
            result = run_single(d, **kwargs)
            return d.name, result is not None
        except Exception as e:
            log.error("Error processing '%s': %s", d.name, e, exc_info=True)
            return d.name, False

    total = len(candidates)
    # Results are collected in the main thread (no dict races).
    doc_workers = DOC_PARALLEL if DOC_PARALLEL > 1 else 1
    if doc_workers > 1:
        log.info("Processing %d dirs with %d concurrent workers", total, doc_workers)
        done = 0
        with ThreadPoolExecutor(max_workers=doc_workers) as ex:
            futures = [ex.submit(_process, d) for d in candidates]
            for fut in as_completed(futures):
                name, ok_flag = fut.result()
                results[name] = ok_flag
                done += 1
                log.info("[%d/%d] %s → %s", done, total, name,
                         "ok" if ok_flag else "FAILED")
    else:
        for i, d in enumerate(candidates):
            log.info("[%d/%d] %s", i + 1, total, d.name)
            name, ok_flag = _process(d)
            results[name] = ok_flag

    ok = sum(1 for v in results.values() if v)
    log.info("%s", sep)
    log.info("Batch complete: %d/%d succeeded", ok, len(candidates))
    log.info(sep)
    return results


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def run(
    input_path: str | Path,
    *,
    batch: bool = False,
    **kwargs,
) -> Optional[dict] | dict[str, bool]:
    """Entry point: auto-selects single or batch mode."""
    input_path = Path(input_path)

    if batch:
        return run_batch(input_path, **kwargs)
    else:
        return run_single(input_path, **kwargs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m docpipe.visuals",
        description="Image Processing – Vision-LLM enrichment of tables and figures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Single PDF output directory
  python -m docpipe.visuals ./output/my_pdf

  # Batch: all PDF subdirs
  python -m docpipe.visuals ./output/ --batch

  # Dry-run (statistics only)
  python -m docpipe.visuals ./output/my_pdf --dry-run

  # Force re-processing (ignore cache)
  python -m docpipe.visuals ./output/my_pdf --force

  # Custom model / vLLM endpoint
  python -m docpipe.visuals ./output/my_pdf \\
      --model Qwen/Qwen3.5-122B-A10B-FP8 --base-url http://gpu-server:8001/v1
        """,
    )
    p.add_argument(
        "input", nargs="?", default=None,
        help="Preprocessing output directory (single PDF, or root with --batch); "
             "default: the profile's processed directory",
    )
    p.add_argument(
        "--batch", action="store_true",
        help="Process all PDF subdirectories under the input path",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Only report statistics, do not call the vLLM server",
    )
    p.add_argument(
        "--force-stale", action="store_true",
        help="re-describe items whose prompts changed since the cached run",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-process even if %s already exists" % ENRICHED_OUTPUT_JSON,
    )
    p.add_argument(
        "--input-json", default=None,
        help="Override input JSON path (relative to output dir)",
    )
    p.add_argument(
        "--model", default=None,
        help="vLLM vision model / served-model-name (default: %s)" % VLM_MODEL,
    )
    p.add_argument(
        "--base-url", default=None,
        help="vLLM OpenAI-compatible base URL (default: %s)" % VLM_BASE_URL,
    )
    add_profile_argument(p)
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    profile = resolve_profile(args)
    if args.input is None:
        if profile is None:
            raise SystemExit("give an input path or a --profile to take it from")
        args.input = str(profile.processed_dir)

    common = dict(
        dry_run=args.dry_run,
        force=args.force,
        force_stale=args.force_stale,
        base_url=args.base_url,
        model=args.model,
    )

    if args.input_json:
        common["input_json"] = args.input_json

    try:
        if args.batch:
            results = run_batch(Path(args.input), **common)
            ok = sum(1 for v in results.values() if v)
            sys.exit(0 if ok == len(results) else 1)
        else:
            result = run_single(Path(args.input), **common)
            sys.exit(0 if result is not None else 1)
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()