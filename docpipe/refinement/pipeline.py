"""
pipeline.py: Orchestrates the textrefinement stage.

Refines one document directory, or every document subdirectory under
a processed root with `--batch`, sending each document's Stage 3
sections through the LLM refinement pass in refine.py.
`_build_parser` lists the CLI flags.

Before refining, `assert_serving` (docpipe.llm_preflight) checks that
the configured LLM server accepts a request of the worst-case size
this stage can send, so an undersized server is caught before the
first document rather than mid-run.

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

from docpipe import prompts, reading, usage
from docpipe.artifacts import document_dirs
from docpipe.llm_preflight import assert_serving
from docpipe.profile import add_profile_argument, program, require_profile

from .config import (DIR_RESULTS, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
                     SECTIONS_REFINED_JSON, PROMPT_IDS, SECTIONS_JSON,
                     llm_max_tokens, llm_temperature, max_request_tokens)
from .refine import reply_shapes, run_refine

log = logging.getLogger(__name__)

# Documents refined concurrently.
# Total in-flight requests ≈ DOC_PARALLEL × LLM_NUM_PARALLEL.
DOC_PARALLEL = int(os.environ.get("DOC_PARALLEL", "8"))


# ---------------------------------------------------------------------------
# Single-document refinement
# ---------------------------------------------------------------------------

def run_single(doc_dir: Path, *, force: bool = False,
               force_stale: bool = False,
               holes: Optional[list] = None) -> Optional[dict]:
    """
    Refines one document directory. With ``force`` the cached
    ``sections_refined.json`` is ignored and the LLM re-refines; the old file
    stays until the new one atomically replaces it. ``force_stale`` does the
    same, but only when the prompt has changed since the cached output was
    written. *holes*, when given, gets one entry for the document if it has
    windows that kept their original text or sections that were cut
    mechanically (see `run_refine`).
    Returns the refined dict, or None on failure.
    """
    doc_dir = Path(doc_dir)
    results_dir = doc_dir / DIR_RESULTS
    final = doc_dir / SECTIONS_REFINED_JSON

    changed = prompts.check(results_dir, PROMPT_IDS) if final.exists() else []
    if changed and not force:
        if force_stale:
            log.info("Stage 4: %s was refined with an older prompt (%s) – redoing",
                     doc_dir.name, ", ".join(changed))
            force = True
        else:
            log.warning("Stage 4: %s was refined with an older prompt (%s); "
                        "re-run with --force-stale to redo it",
                        doc_dir.name, ", ".join(changed))

    result = run_refine(doc_dir, force=force, holes=holes)
    if result is not None:
        prompts.record(results_dir, PROMPT_IDS)
    return result


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def run_batch(root_dir: Path, *, force: bool = False,
              force_stale: bool = False,
              holes: Optional[list] = None) -> dict[str, bool]:
    """
    Refines every document directory under *root_dir*, at any depth, that has
    a Stage-3 structured output. Returns a dict mapping directory name →
    success boolean.
    """
    root_dir = Path(root_dir)
    candidates = document_dirs(root_dir, SECTIONS_JSON)

    if not candidates:
        log.warning(
            "No documents with %s found under '%s'.",
            SECTIONS_JSON, root_dir,
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
            res = run_single(d, force=force, force_stale=force_stale,
                             holes=holes)
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
# What a run left unread
# ---------------------------------------------------------------------------

def summarise(holes: list) -> str:
    """One sentence for what a run could not read, in the units each number
    counts: windows, sections and documents. *holes* are the entries
    `run_refine` adds, one per document."""
    parts = []
    kept = [h for h in holes if h["windows"]]
    if kept:
        by_cause: dict = {}
        for entry in kept:
            for cause, n in entry["holes"].items():
                by_cause[cause] = by_cause.get(cause, 0) + n
        parts.append(
            f"{sum(h['windows'] for h in kept)} window(s) "
            f"({sum(h['sections'] for h in kept)} section(s)) in {len(kept)} "
            f"document(s) kept their original text; hole(s) by cause: "
            + ", ".join(f"{c} {n}" for c, n in sorted(by_cause.items())))
    cut = [h for h in holes if h["mechanical"]]
    if cut:
        by_cause = {}
        for entry in cut:
            for cause, n in entry["mechanical"].items():
                by_cause[cause] = by_cause.get(cause, 0) + n
        parts.append(
            f"{sum(by_cause.values())} section(s) in {len(cut)} document(s) "
            f"were cut mechanically, the model's cuts being unusable; "
            f"section(s) by cause: "
            + ", ".join(f"{c} {n}" for c, n in sorted(by_cause.items())))
    return "Stage 4: " + "; ".join(parts)


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def run(
    input_path: str | Path,
    *,
    batch: bool = False,
    force: bool = False,
    force_stale: bool = False,
) -> Optional[dict] | dict[str, bool]:
    """Entry point: auto-selects single or batch mode."""
    input_path = Path(input_path)
    # Before the first document, not after the first failure: a server with too
    # little context rejects requests mid-run, and the affected windows quietly
    # keep their raw text.
    reading.phrases()
    assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, max_request_tokens(),
                   what="refinement", shapes=reply_shapes())
    if batch:
        return run_batch(input_path, force=force, force_stale=force_stale)
    return run_single(input_path, force=force, force_stale=force_stale)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=program("docpipe.refinement"),
        description="Text Refinement – LLM-based section refinement of Stage-3 output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Batch: every document subdir under the processed root
  python -m docpipe.refinement data/pdf/processed --batch

  # Single document directory
  python -m docpipe.refinement data/pdf/processed/my_doc

  # Re-refine, ignoring a cached final output
  python -m docpipe.refinement data/pdf/processed --batch --force
        """,
    )
    p.add_argument(
        "input", nargs="?", default=None,
        help="Processed root (with --batch) or a single document directory "
             "(default: the profile's processed directory)",
    )
    p.add_argument(
        "--batch", action="store_true",
        help="Refine all document subdirectories under the input path",
    )
    p.add_argument(
        "--force-stale", action="store_true",
        help="re-refine documents whose prompt changed since the cached run",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-refine even if %s already exists" % SECTIONS_REFINED_JSON,
    )
    p.add_argument(
        "--print-context-budget", action="store_true",
        help="Print the worst-case tokens one request needs, then exit "
             "(feed it to the server's --max-model-len)",
    )
    add_profile_argument(p)
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

    profile = require_profile(args)
    usage.begin("refinement")
    # Read once before the first document: a setting that cannot be read
    # would otherwise fail inside every request of every document.
    llm_temperature(), llm_max_tokens()

    # Lets the job script derive --max-model-len from the code instead of
    # restating it in a comment that nothing checks.
    if args.print_context_budget:
        print(max_request_tokens())
        sys.exit(0)

    # The sentences a retry says are the profile's, and a profile that lacks
    # one hears about it now, not in the middle of the first document. After
    # the budget: that asks nothing of the model and needs no sentence.
    reading.phrases()

    if args.input is None:
        args.input = str(profile.processed_dir)

    holes: list = []
    try:
        assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
                       max_request_tokens(), what="refinement",
                       shapes=reply_shapes())
        if args.batch:
            results = run_batch(Path(args.input), force=args.force,
                                force_stale=args.force_stale, holes=holes)
            ok = sum(1 for v in results.values() if v)
            code = 0 if ok == len(results) else 1
        else:
            res = run_single(Path(args.input), force=args.force,
                             force_stale=args.force_stale, holes=holes)
            code = 0 if res is not None else 1
        # A hole is a result with a cause and does not change the exit code;
        # it is said once, in the units it is counted in, where the run ends.
        if holes:
            log.warning("%s", summarise(holes))
        sys.exit(code)
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
