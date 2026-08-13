"""
pipeline.py – Orchestration of the PDF preprocessing pipeline (Stages 1-3).

  1. PyMuPDF        → Text blocks (rawdict)
  2. PP-DocLayoutV3 → Table / image crops + layout labels + caption resolution
  3. Section assembly → sections.json

LLM-based section refinement lives in ``docpipe.refinement``.

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

from docpipe.profile import add_profile_argument, resolve_profile

from .config import (
    PAGES_JSON,
    SECTIONS_JSON,
    clean_data,
    dump_json_atomic,
)
from .models import PageData
from .stage3_structure import build_sections, save_output, sections_to_dict
# Keep Stage 1/2 imports (fitz, torch, PP-DocLayout) lazy inside the functions
# that need them: --rebuild-stage3 must run without pulling in the GPU stack.

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page cache helpers
# ---------------------------------------------------------------------------

def _save_pages_cache(pages: list[PageData], output_dir: Path) -> None:
    cache_path = output_dir / PAGES_JSON
    cleaned = [clean_data(pg.to_dict()) for pg in pages]
    dump_json_atomic(cleaned, cache_path)
    log.info(f"Pages cached: {cache_path}")


def _load_pages_cache(output_dir: Path) -> Optional[list[PageData]]:
    cache_path = output_dir / PAGES_JSON
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
    column_layout: str = "auto",
) -> Optional[dict]:
    """
    Processes a single PDF through Stages 1-3; returns the Stage-3 dict, or
    None on failure. Stage 1+2 results are cached in pages.json and
    reused unless *force_reextract*.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"{'=' * 60}")
    log.info(f"PDF:    {pdf_path.name}")
    log.info(f"Output: {output_dir}")
    log.info(f"{'=' * 60}")

    # ── Stage 1 + 2 (with cache) ────────────────────────────────────────
    pages: Optional[list[PageData]] = None
    n_failed = 0
    if not force_reextract:
        pages = _load_pages_cache(output_dir)

    if pages is None:
        from .stage1_extract import extract_all_pages
        from .stage2_layout import detect_layout_all_pages, load_model
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

        # Never cache an incomplete extraction — it would be reused as if
        # complete. Skipping the write forces a retry on the next run.
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
    stage3_path = output_dir / SECTIONS_JSON
    result: Optional[dict] = None
    # Stage 1+2 refuse to cache an incomplete extraction, but Stage 3 used to
    # cache its sections either way — so the next run paid for the re-extraction
    # and then loaded the sections built from the broken pages anyway.
    if n_failed and stage3_path.exists():
        log.warning("%s: dropping the Stage-3 cache, it was built from an "
                    "incomplete extraction", pdf_path.name)
        stage3_path.unlink(missing_ok=True)
    if stage3_path.exists() and not force_reextract:
        try:
            with open(stage3_path, encoding="utf-8") as f:
                result = json.load(f)
            log.info(f"Stage 3: cache hit → {stage3_path}")
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Stage 3 cache unreadable ({e}); rebuilding")
            result = None
    if result is None:
        sections = build_sections(pages, column_layout)
        if not n_failed:
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
    column_layout: str = "auto",
) -> dict[str, Optional[dict]]:
    """
    Processes all PDFs in *input_dir* sequentially, keyed by path relative to
    *input_dir*. The layout model is loaded once and reused; it is not
    thread-safe, so processing must stay sequential. _index.json is rewritten
    after each PDF so partial results survive an interruption.
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

    needs_extraction = force_reextract or any(
        not (output_dir / p.relative_to(input_dir).with_suffix("") / PAGES_JSON).exists()
        for p in pdf_files
    )
    if needs_extraction:
        from .stage2_layout import load_model
        model_tuple = load_model()
    else:
        log.info("All PDFs have cached extractions – skipping layout model load")
        model_tuple = None

    # Keyed by relative path, not file name: a recursive glob can yield two
    # same-named PDFs in different subdirectories.
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
                column_layout=column_layout,
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

def rebuild_stage3_from_cache(output_dir: Path, column_layout: str = "auto") -> int:
    """
    Re-run ONLY Stage 3 for every doc under *output_dir* that has a readable
    pages cache, overwriting its sections.json. No PDF input and no
    layout model. Returns the number of docs rebuilt.
    """
    output_dir = Path(output_dir)
    doc_dirs = sorted(
        d for d in output_dir.iterdir()
        if d.is_dir() and (d / PAGES_JSON).exists()
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
        save_output(build_sections(pages, column_layout), d)
        done += 1
        if (i + 1) % 50 == 0 or (i + 1) == len(doc_dirs):
            log.info("  [%d/%d] rebuilt", i + 1, len(doc_dirs))
    log.info("Rebuild Stage 3 complete: %d/%d docs", done, len(doc_dirs))
    return done


def report_columns(output_dir: Path, top: int = 20) -> dict[str, tuple[int, int]]:
    """
    Report how many pages the column detector would read as two columns, per
    doc, from the cached pages. Changes nothing — this is what a corpus is
    asked before its profile switches to column_layout: auto.
    """
    from .columns import count_multi_column_pages

    output_dir = Path(output_dir)
    doc_dirs = sorted(
        d for d in output_dir.iterdir()
        if d.is_dir() and (d / PAGES_JSON).exists()
    )
    found: dict[str, tuple[int, int, int]] = {}
    total_pages = total_multi = 0
    for d in doc_dirs:
        pages = _load_pages_cache(d)
        if pages is None:
            continue
        multi, widest = count_multi_column_pages(pages)
        total_pages += len(pages)
        total_multi += multi
        if multi:
            found[d.name] = (multi, len(pages), widest)

    log.info("Column report: %d/%d docs have multi-column pages | %d/%d pages",
             len(found), len(doc_dirs), total_multi, total_pages)
    for name, (multi, n, widest) in sorted(found.items(), key=lambda kv: -kv[1][0])[:top]:
        log.info("  %-56s %3d/%3d pages | up to %d columns", name[:56], multi, n, widest)
    return found


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
    column_layout: str = "auto",
) -> Optional[dict] | dict[str, Optional[dict]]:
    """
    Entry point: dispatches to run_single() or run_folder() depending on
    whether *input_path* is a file or a folder. With *rebuild_stage3*, ignores
    *input_path* and re-runs only Stage 3 over *output_dir*'s caches.
    """
    output_dir = Path(output_dir)

    if rebuild_stage3:
        rebuild_stage3_from_cache(output_dir, column_layout)
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
            column_layout=column_layout,
        )
    elif input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return run_single(
            pdf_path=input_path,
            output_dir=output_dir,
            force_reextract=force_reextract,
            page_range=page_range,
            column_layout=column_layout,
        )
    else:
        raise ValueError(f"Input is neither a PDF nor a folder: {input_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m docpipe.preprocessing.pipeline",
        description="Municipal Heat Planning – PDF Preprocessing Pipeline (Stages 1-3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m docpipe.preprocessing.pipeline doc.pdf ./out
  python -m docpipe.preprocessing.pipeline ./pdfs/ ./out
  python -m docpipe.preprocessing.pipeline doc.pdf ./out --pages 0 20
  python -m docpipe.preprocessing.pipeline ./pdfs/ ./out --glob "*.pdf"
  python -m docpipe.preprocessing.pipeline doc.pdf ./out --force-reextract
  python -m docpipe.preprocessing.pipeline ./out --rebuild-stage3
        """,
    )
    p.add_argument("input",  nargs="?", default=None,
                   help="PDF file or folder containing PDFs "
                        "(omit with --rebuild-stage3)")
    p.add_argument("output", nargs="?", default=None,
                   help="Output directory (default: the profile's processed dir)")
    p.add_argument("--force-reextract", action="store_true",
                   help="Ignore cache and re-run Stages 1+2")
    p.add_argument("--report-columns", action="store_true",
                   help="Report which cached pages the column detector reads as "
                        "two-column, and change nothing")
    p.add_argument("--rebuild-stage3", action="store_true",
                   help="Re-run ONLY Stage 3 over the output dir's cached docs "
                        "(no PDF input, no layout model); rewrites "
                        "%s from %s" % (SECTIONS_JSON, PAGES_JSON))
    p.add_argument("--pages", nargs=2, type=int, metavar=("START", "END"),
                   help="Only process pages START..END, 0-indexed (single PDF only)")
    p.add_argument("--glob", default="*.pdf",
                   help="Glob pattern for PDF search in folder (default: *.pdf)")
    add_profile_argument(p)
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

    profile = resolve_profile(args)
    explicit_output = args.output is not None
    if args.output is None:
        if profile is None:
            raise SystemExit("give an output directory or a --profile to take it from")
        args.output = str(profile.processed_dir)

    page_range = tuple(args.pages) if args.pages else None

    if args.report_columns:
        # The report reads a processed root, which is the second positional in
        # a normal run but the only one anybody types here.
        root = args.output if (explicit_output or args.input is None) else args.input
        report_columns(Path(root))
        sys.exit(0)

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
            column_layout=(profile.column_layout if profile else "auto"),
        )
        sys.exit(0)
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
