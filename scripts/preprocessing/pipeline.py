"""
pipeline.py – Orchestration of the PDF preprocessing pipeline (Stages 1-3).

Stages:
  1. PyMuPDF        → Text blocks (rawdict) + page PNGs
  2. PP-DocLayoutV3 → Table / image crops + layout labels + caption resolution
  3. Section assembly → Deterministic JSON output (structured_output.json)

LLM-based section refinement is a separate concern handled by the
``scripts.textrefinement`` module (which reads structured_output.json and
writes structured_output_final.json).

CLI:
  python -m scripts.preprocessing.pipeline input.pdf ./output
  python -m scripts.preprocessing.pipeline ./pdfs/ ./output

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import (
    CACHE_PAGES_JSON,
    STRUCTURED_OUTPUT_JSON,
    clean_data,
    dump_json_atomic,
)
from .models import PageData
from .stage1_extract import extract_all_pages
from .stage2_layout import detect_layout_all_pages, load_model
from .stage3_structure import build_sections, save_output, sections_to_dict

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page cache helpers
# ---------------------------------------------------------------------------

def _save_pages_cache(pages: list[PageData], output_dir: Path) -> None:
    cache_path = output_dir / CACHE_PAGES_JSON
    cleaned = [clean_data(pg.to_dict()) for pg in pages]
    dump_json_atomic(cleaned, cache_path)
    log.info(f"Pages cached: {cache_path}")


def _load_pages_cache(output_dir: Path) -> Optional[list[PageData]]:
    cache_path = output_dir / CACHE_PAGES_JSON
    if not cache_path.exists():
        return None
    log.info(f"Loading pages from cache: {cache_path}")
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Pages cache unreadable ({e}); re-extracting from PDF")
        return None
    return [PageData.from_dict(d) for d in data]


# ---------------------------------------------------------------------------
# Single-PDF processing
# ---------------------------------------------------------------------------

def run_single(
    pdf_path: Path,
    output_dir: Path,
    model_tuple=None,
    force_reextract: bool = False,
    page_range: Optional[tuple[int, int]] = None,
) -> Optional[dict]:
    """
    Processes a single PDF through Stages 1-3.

    Stage 1 + 2 results are cached in *pages_extracted.json*.  If the cache
    exists and *force_reextract* is False, Stages 1 and 2 are skipped.

    Output structure in output_dir:
        pages_extracted.json   – Stage 1+2 cache
        pages/                 – Page PNGs
        images/                – Table and image crops
        structured_output.json – Structured JSON (Stage 3)

    Returns the Stage-3 dict or None on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"{'=' * 60}")
    log.info(f"PDF:    {pdf_path.name}")
    log.info(f"Output: {output_dir}")
    log.info(f"{'=' * 60}")

    # ── Stage 1 + 2 (with cache) ────────────────────────────────────────
    pages: Optional[list[PageData]] = None
    if not force_reextract:
        pages = _load_pages_cache(output_dir)

    if pages is None:
        # Only load the layout model when we actually need it
        if model_tuple is None:
            model_tuple = load_model()

        pages, fitz_pages, fitz_doc, n_failed = extract_all_pages(
            pdf_path,
            page_range=page_range,
        )
        try:
            pages = detect_layout_all_pages(
                pages, fitz_pages, output_dir, model_tuple
            )
        finally:
            fitz_doc.close()

        # Do not cache an incomplete extraction: a partial cache would be
        # silently reused as if complete on the next run. Skipping the write
        # forces a re-extraction (which retries the failed pages) next time.
        if n_failed:
            log.warning(
                f"{pdf_path.name}: {n_failed} page(s) failed extraction – "
                f"not caching the partial result (re-run to retry)"
            )
        else:
            _save_pages_cache(pages, output_dir)
    else:
        log.info(f"Stages 1+2: cache loaded ({len(pages)} pages)")

    total_text   = sum(
        sum(1 for b in pg.blocks if b.type == "text")  for pg in pages
    )
    total_tables = sum(
        sum(1 for b in pg.blocks if b.type == "table") for pg in pages
    )
    total_images = sum(
        sum(1 for b in pg.blocks if b.type == "image") for pg in pages
    )
    log.info(
        f"Extraction: {len(pages)} pages | "
        f"{total_text} text blocks | {total_tables} tables | {total_images} images"
    )

    # ── Stage 3: section assembly (with cache) ─────────────────────────────
    stage3_path = output_dir / STRUCTURED_OUTPUT_JSON
    result: Optional[dict] = None
    if stage3_path.exists() and not force_reextract:
        try:
            with open(stage3_path, encoding="utf-8") as f:
                result = json.load(f)
            log.info(f"Stage 3: cache hit → {stage3_path}")
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Stage 3 cache unreadable ({e}); rebuilding")
            result = None
    if result is None:
        sections = build_sections(pages)
        save_output(sections, output_dir)
        result = clean_data(sections_to_dict(sections))

    log.info(
        f"Stage 3: {len(result['sections'])} sections | "
        f"{sum(len(s['tables']) for s in result['sections'])} tables | "
        f"{sum(len(s['figures']) for s in result['sections'])} figures"
    )

    return result


# ---------------------------------------------------------------------------
# Folder processing
# ---------------------------------------------------------------------------

def run_folder(
    input_dir: Path,
    output_dir: Path,
    force_reextract: bool = False,
    glob: str = "*.pdf",
) -> dict[str, Optional[dict]]:
    """
    Processes all PDFs in *input_dir* sequentially.

    The PP-DocLayoutV3 model is loaded once and reused for every PDF (it is
    GPU-bound and not thread-safe, so processing is sequential). Each PDF gets
    its own subdirectory named after its stem. *_index.json* is written after
    each PDF so partial results are preserved on interruption.
    """
    pdf_files = sorted(input_dir.glob(glob))
    if not pdf_files:
        log.warning(f"No PDFs found in '{input_dir}' (pattern: {glob})")
        return {}

    log.info(f"{'=' * 60}")
    log.info(f"Folder mode: {len(pdf_files)} PDFs in '{input_dir}'")
    for p in pdf_files:
        log.info(f"  - {p.relative_to(input_dir)}")
    log.info(f"{'=' * 60}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Check if any PDF actually needs Stages 1+2 (no cache or force)
    needs_extraction = force_reextract or any(
        not (output_dir / p.relative_to(input_dir).with_suffix("") / CACHE_PAGES_JSON).exists()
        for p in pdf_files
    )
    if needs_extraction:
        model_tuple = load_model()
    else:
        log.info("All PDFs have cached extractions – skipping layout model load")
        model_tuple = None

    # Keyed by the path relative to input_dir (not just the file name) so two
    # same-named PDFs in different subdirectories under a recursive glob do not
    # collide and overwrite each other in the results dict and _index.json.
    results: dict[str, Optional[dict]] = {}
    output_dirs: dict[str, str] = {}

    total = len(pdf_files)
    for i, pdf_path in enumerate(pdf_files):
        rel        = pdf_path.relative_to(input_dir)
        pdf_key    = str(rel)
        pdf_output = output_dir / rel.with_suffix("")
        log.info(f"[{i + 1}/{total}] Processing: {rel}")
        try:
            result = run_single(
                pdf_path=pdf_path,
                output_dir=pdf_output,
                model_tuple=model_tuple,
                force_reextract=force_reextract,
            )
            status = "ok" if result is not None else "error"
        except Exception as e:
            log.error(f"Error processing '{pdf_key}': {e}", exc_info=True)
            result, status = None, "error"

        results[pdf_key] = result
        output_dirs[pdf_key] = str(pdf_output)
        log.info(f"  [{i + 1}/{total}] {pdf_key} → {status}")
        _write_index(results, output_dir, output_dirs)
        gc.collect()

    ok_count = sum(1 for r in results.values() if r is not None)
    log.info(f"\n{'=' * 60}")
    log.info(f"Done: {ok_count}/{len(pdf_files)} PDFs processed successfully")
    log.info(f"Index: {output_dir / '_index.json'}")
    log.info(f"{'=' * 60}")

    return results


def _write_index(
    results: dict[str, Optional[dict]],
    output_dir: Path,
    output_dirs: Optional[dict[str, str]] = None,
) -> None:
    """Writes _index.json with status and key metrics for all processed PDFs."""
    output_dirs = output_dirs or {}
    index = {}
    for name, r in results.items():
        status = "ok" if r is not None else "error"
        index[name] = {
            "status":     status,
            "output_dir": output_dirs.get(name, str(output_dir / Path(name).stem)),
            "sections":   len(r.get("sections", [])) if r else 0,
        }
    dump_json_atomic(index, output_dir / "_index.json")


# ---------------------------------------------------------------------------
# Stage-3-only rebuild (no PDF, no layout model)
# ---------------------------------------------------------------------------

def rebuild_stage3_from_cache(output_dir: Path) -> int:
    """
    Re-run ONLY Stage 3 for every already-extracted doc, overwriting its
    structured_output.json from the cached Stage-1/2 layout blocks.

    No PDF input, no layout model — pure CPU. Use this to propagate a Stage-3
    change (e.g. a new per-segment field like bbox) across a corpus that was
    already extracted, without re-running the GPU extraction or any downstream
    LLM/VL stage. A doc is processed iff it has a readable pages cache.
    """
    output_dir = Path(output_dir)
    doc_dirs = sorted(
        d for d in output_dir.iterdir()
        if d.is_dir() and (d / CACHE_PAGES_JSON).exists()
    )
    log.info("Rebuild Stage 3: %d docs with a pages cache under '%s'",
             len(doc_dirs), output_dir)
    done = 0
    for i, d in enumerate(doc_dirs):
        pages = _load_pages_cache(d)
        if pages is None:
            log.warning("  [%d/%d] %s: pages cache unreadable – skipping",
                        i + 1, len(doc_dirs), d.name)
            continue
        save_output(build_sections(pages), d)
        done += 1
        if (i + 1) % 50 == 0 or (i + 1) == len(doc_dirs):
            log.info("  [%d/%d] rebuilt", i + 1, len(doc_dirs))
    log.info("Rebuild Stage 3 complete: %d/%d docs", done, len(doc_dirs))
    return done


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def run(
    input_path: str | Path,
    output_dir: str | Path,
    force_reextract: bool = False,
    page_range: Optional[tuple[int, int]] = None,
    glob: str = "*.pdf",
    rebuild_stage3: bool = False,
) -> Optional[dict] | dict[str, Optional[dict]]:
    """
    Entry point of the preprocessing pipeline.

    Automatically detects whether input_path is a file or folder and
    delegates to run_single() or run_folder(). With *rebuild_stage3*, skips
    input entirely and re-runs only Stage 3 over *output_dir*'s caches.
    """
    output_dir = Path(output_dir)

    if rebuild_stage3:
        rebuild_stage3_from_cache(output_dir)
        return {}

    input_path = Path(input_path)

    if input_path.is_dir():
        if page_range is not None:
            log.warning("--pages is ignored in folder mode (single-PDF only)")
        return run_folder(
            input_dir=input_path,
            output_dir=output_dir,
            force_reextract=force_reextract,
            glob=glob,
        )
    elif input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return run_single(
            pdf_path=input_path,
            output_dir=output_dir,
            force_reextract=force_reextract,
            page_range=page_range,
        )
    else:
        raise ValueError(f"Input is neither a PDF nor a folder: {input_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.preprocessing.pipeline",
        description="Municipal Heat Planning – PDF Preprocessing Pipeline (Stages 1-3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.preprocessing.pipeline doc.pdf ./out
  python -m scripts.preprocessing.pipeline ./pdfs/ ./out
  python -m scripts.preprocessing.pipeline doc.pdf ./out --pages 0 20
  python -m scripts.preprocessing.pipeline ./pdfs/ ./out --glob "*.pdf"
  python -m scripts.preprocessing.pipeline doc.pdf ./out --force-reextract
  python -m scripts.preprocessing.pipeline ./out --rebuild-stage3
        """,
    )
    p.add_argument("input",  nargs="?", default=None,
                   help="PDF file or folder containing PDFs "
                        "(omit with --rebuild-stage3)")
    p.add_argument("output", help="Output directory")
    p.add_argument("--force-reextract", action="store_true",
                   help="Ignore cache and re-run Stages 1+2")
    p.add_argument("--rebuild-stage3", action="store_true",
                   help="Re-run ONLY Stage 3 over the output dir's cached docs "
                        "(no PDF input, no layout model); rewrites "
                        "structured_output.json from pages_extracted.json")
    p.add_argument("--pages", nargs=2, type=int, metavar=("START", "END"),
                   help="Only process pages START..END, 0-indexed (single PDF only)")
    p.add_argument("--glob", default="*.pdf",
                   help="Glob pattern for PDF search in folder (default: *.pdf)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args   = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    page_range = tuple(args.pages) if args.pages else None

    if not args.rebuild_stage3 and args.input is None:
        log.error("input is required unless --rebuild-stage3 is given")
        sys.exit(1)

    try:
        run(
            input_path=args.input,
            output_dir=args.output,
            force_reextract=args.force_reextract,
            page_range=page_range,
            glob=args.glob,
            rebuild_stage3=args.rebuild_stage3,
        )
        sys.exit(0)
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
