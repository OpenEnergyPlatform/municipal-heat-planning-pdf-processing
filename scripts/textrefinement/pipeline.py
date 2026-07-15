"""
pipeline.py – Orchestration of the text-refinement module.

Refines one document directory, or every document subdirectory under a
processed root (--batch). See ``_build_parser`` for the CLI.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import gc
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from .config import STRUCTURED_OUTPUT_JSON, FINAL_OUTPUT_JSON
from .refine import run_refine

log = logging.getLogger(__name__)

# Documents refined concurrently.
# Total in-flight requests ≈ DOC_PARALLEL × LLM_NUM_PARALLEL.
DOC_PARALLEL = int(os.environ.get("DOC_PARALLEL", "8"))


def _has_input(doc_dir: Path) -> bool:
    """True if the document directory carries a Stage-3 structured output."""
    return (doc_dir / STRUCTURED_OUTPUT_JSON).exists()


# ---------------------------------------------------------------------------
# Single-document refinement
# ---------------------------------------------------------------------------

def run_single(doc_dir: Path, *, force: bool = False) -> Optional[dict]:
    """
    Refines one document directory. With ``force`` a cached
    ``structured_output_final.json`` is deleted first so the LLM re-refines.
    Returns the refined dict, or None on failure.
    """
    doc_dir = Path(doc_dir)
    if force:
        final = doc_dir / FINAL_OUTPUT_JSON
        if final.exists():
            final.unlink()
    return run_refine(doc_dir)


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def run_batch(root_dir: Path, *, force: bool = False) -> dict[str, bool]:
    """
    Refines every document subdirectory under *root_dir* that has a Stage-3
    structured output. Returns a dict mapping directory name → success boolean.
    """
    root_dir = Path(root_dir)
    candidates = sorted(
        d for d in root_dir.iterdir() if d.is_dir() and _has_input(d)
    )

    if not candidates:
        log.warning(
            "No documents with %s found under '%s'.",
            STRUCTURED_OUTPUT_JSON, root_dir,
        )
        return {}

    total = len(candidates)
    sep = "=" * 60
    log.info(sep)
    log.info("Text refinement: %d documents in '%s'", total, root_dir)
    log.info(sep)

    results: dict[str, bool] = {}

    def _process(d: Path) -> tuple[str, bool]:
        try:
            res = run_single(d, force=force)
            return d.name, res is not None
        except Exception as e:  # never let one document kill the whole run
            log.error("Error refining '%s': %s", d.name, e, exc_info=True)
            return d.name, False

    # Results are collected in the main thread (no dict races).
    doc_workers = DOC_PARALLEL if DOC_PARALLEL > 1 else 1
    if doc_workers > 1:
        log.info("Refining %d documents with %d concurrent workers", total, doc_workers)
        done = 0
        with ThreadPoolExecutor(max_workers=doc_workers) as ex:
            futures = [ex.submit(_process, d) for d in candidates]
            for fut in as_completed(futures):
                name, ok_flag = fut.result()
                results[name] = ok_flag
                done += 1
                log.info("[%d/%d] %s → %s", done, total, name,
                         "ok" if ok_flag else "FAILED")
                gc.collect()
    else:
        for i, d in enumerate(candidates):
            log.info("[%d/%d] %s", i + 1, total, d.name)
            name, ok_flag = _process(d)
            results[name] = ok_flag
            gc.collect()

    ok = sum(1 for v in results.values() if v)
    log.info(sep)
    log.info("Refinement complete: %d/%d succeeded", ok, total)
    log.info(sep)
    return results


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def run(
    input_path: str | Path,
    *,
    batch: bool = False,
    force: bool = False,
) -> Optional[dict] | dict[str, bool]:
    """Entry point: auto-selects single or batch mode."""
    input_path = Path(input_path)
    if batch:
        return run_batch(input_path, force=force)
    return run_single(input_path, force=force)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.textrefinement",
        description="Text Refinement – LLM-based section refinement of Stage-3 output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Batch: every document subdir under the processed root
  python -m scripts.textrefinement data/pdf/processed --batch

  # Single document directory
  python -m scripts.textrefinement data/pdf/processed/my_doc

  # Re-refine, ignoring a cached final output
  python -m scripts.textrefinement data/pdf/processed --batch --force
        """,
    )
    p.add_argument(
        "input",
        help="Processed root (with --batch) or a single document directory",
    )
    p.add_argument(
        "--batch", action="store_true",
        help="Refine all document subdirectories under the input path",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-refine even if structured_output_final.json already exists",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p


def main() -> None:
    """CLI entry point."""
    args = _build_parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        if args.batch:
            results = run_batch(Path(args.input), force=args.force)
            ok = sum(1 for v in results.values() if v)
            sys.exit(0 if ok == len(results) else 1)
        else:
            res = run_single(Path(args.input), force=args.force)
            sys.exit(0 if res is not None else 1)
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
