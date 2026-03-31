"""
pipeline.py – Orchestration of the PDF processing pipeline.

Stages:
  1. PyMuPDF        → Text blocks (rawdict) + page PNGs
  2. PP-DocLayoutV3 → Table / image crops + layout labels + caption resolution
  3. Section assembly → Deterministic JSON output (no LLM required)
  4. LLM refinement → Clean artefacts, remove directory pages, convert
     bibliography to BibTeX (Ollama gpt-oss:120b)

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
import unicodedata
from pathlib import Path
from typing import Optional

from .config import (
    CACHE_PAGES_JSON,
    STRUCTURED_OUTPUT_JSON,
    FINAL_OUTPUT_JSON,
    clean_data,
)
from .models import PageData
from .stage1_extract import extract_all_pages
from .stage2_layout import detect_layout_all_pages, load_model
from PIL import Image
from .stage3_structure import build_sections, save_output, sections_to_dict
from .stage4_refine import run_stage4

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unicode cleaning (unchanged from original)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Page cache helpers
# ---------------------------------------------------------------------------

def _save_pages_cache(pages: list[PageData], output_dir: Path) -> None:
    cache_path = output_dir / CACHE_PAGES_JSON
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = [clean_data(pg.to_dict()) for pg in pages]
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    log.info(f"Pages cached: {cache_path}")


def _load_pages_cache(output_dir: Path) -> Optional[list[PageData]]:
    cache_path = output_dir / CACHE_PAGES_JSON
    if not cache_path.exists():
        return None
    log.info(f"Loading pages from cache: {cache_path}")
    with open(cache_path, encoding="utf-8") as f:
        data = json.load(f)
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
    skip_refine: bool = False,
) -> Optional[dict]:
    """
    Processes a single PDF through all four stages.

    Stage 1 + 2 results are cached in *pages_extracted.json*.  If the cache
    exists and *force_reextract* is False, Stages 1 and 2 are skipped.

    Output structure in output_dir:
        pages_extracted.json  – Stage 1+2 cache
        pages/                – Page PNGs
        images/               – Table and image crops
        final_output.json     – Structured JSON (after Stage 3 + 4)

    Returns the final dict or None on failure.
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

        pages, pil_images, fitz_pages, fitz_doc = extract_all_pages(
            pdf_path,
            page_range=page_range,
        )
        try:
            pages = detect_layout_all_pages(
                pages, pil_images, fitz_pages, output_dir, model_tuple
            )
        finally:
            fitz_doc.close()
        del pil_images

        # Free layout model from GPU to reclaim VRAM for Stage 4 (Ollama)
        if not skip_refine:
            del model_tuple
            model_tuple = None
            gc.collect()
            try:
                import torch
                torch.cuda.empty_cache()
                log.info("Layout model unloaded, CUDA cache cleared")
            except ImportError:
                pass

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
    if stage3_path.exists() and not force_reextract:
        log.info(f"Stage 3: cache hit → {stage3_path}")
        with open(stage3_path, encoding="utf-8") as f:
            result = json.load(f)
    else:
        sections = build_sections(pages)
        save_output(sections, output_dir)
        result = sections_to_dict(sections)

    log.info(
        f"Stage 3: {len(result['sections'])} sections | "
        f"{sum(len(s['tables']) for s in result['sections'])} tables | "
        f"{sum(len(s['figures']) for s in result['sections'])} figures"
    )

    # ── Stage 4: LLM refinement ──────────────────────────────────────────
    if not skip_refine:
        refined = run_stage4(output_dir)
        if refined is not None:
            result = refined
            log.info(
                f"Stage 4 done: {len(result['sections'])} sections | "
                f"{sum(len(s.get('tables', [])) for s in result['sections'])} tables | "
                f"{sum(len(s.get('figures', [])) for s in result['sections'])} figures"
            )
        else:
            log.warning("Stage 4 failed – keeping Stage 3 output")
    else:
        log.info("Stage 4: skipped (--skip-refine)")

    return result


# ---------------------------------------------------------------------------
# Folder processing
# ---------------------------------------------------------------------------

def run_folder(
    input_dir: Path,
    output_dir: Path,
    force_reextract: bool = False,
    glob: str = "*.pdf",
    skip_refine: bool = False,
) -> dict[str, Optional[dict]]:
    """
    Processes all PDFs in *input_dir* sequentially.

    The PP-DocLayoutV3 model is loaded once and reused for every PDF.
    Each PDF gets its own subdirectory named after its stem.
    *_index.json* is written after each PDF so partial results are
    preserved on interruption.
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

    results: dict[str, Optional[dict]] = {}

    for i, pdf_path in enumerate(pdf_files):
        pdf_name   = pdf_path.name
        pdf_output = output_dir / pdf_path.relative_to(input_dir).with_suffix("")

        log.info(f"[{i + 1}/{len(pdf_files)}] Processing: {pdf_name}")

        try:
            result = run_single(
                pdf_path=pdf_path,
                output_dir=pdf_output,
                model_tuple=model_tuple,
                force_reextract=force_reextract,
                skip_refine=skip_refine,
            )
            results[pdf_name] = result
            status = "ok" if result is not None else "error"
            gc.collect()
        except Exception as e:
            log.error(f"Error processing '{pdf_name}': {e}", exc_info=True)
            results[pdf_name] = None
            status = "error"

        log.info(f"  [{i + 1}/{len(pdf_files)}] {pdf_name} → {status}")
        _write_index(results, output_dir)

    ok_count = sum(1 for r in results.values() if r is not None)
    log.info(f"\n{'=' * 60}")
    log.info(f"Done: {ok_count}/{len(pdf_files)} PDFs processed successfully")
    log.info(f"Index: {output_dir / '_index.json'}")
    log.info(f"{'=' * 60}")

    return results


def _write_index(
    results: dict[str, Optional[dict]],
    output_dir: Path,
) -> None:
    """Writes _index.json with status and key metrics for all processed PDFs."""
    index = {}
    for name, r in results.items():
        status = "ok" if r is not None else "error"
        index[name] = {
            "status":    status,
            "output_dir": str(output_dir / Path(name).stem),
            "sections":  len(r.get("sections", [])) if r else 0,
        }
    with open(output_dir / "_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def run(
    input_path: str | Path,
    output_dir: str | Path,
    force_reextract: bool = False,
    page_range: Optional[tuple[int, int]] = None,
    glob: str = "*.pdf",
    skip_refine: bool = False,
) -> Optional[dict] | dict[str, Optional[dict]]:
    """
    Entry point of the pipeline.

    Automatically detects whether input_path is a file or folder and
    delegates to run_single() or run_folder().
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if input_path.is_dir():
        return run_folder(
            input_dir=input_path,
            output_dir=output_dir,
            force_reextract=force_reextract,
            glob=glob,
            skip_refine=skip_refine,
        )
    elif input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return run_single(
            pdf_path=input_path,
            output_dir=output_dir,
            force_reextract=force_reextract,
            page_range=page_range,
            skip_refine=skip_refine,
        )
    else:
        raise ValueError(f"Input is neither a PDF nor a folder: {input_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.preprocessing.pipeline",
        description="Municipal Heat Planning – PDF Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.preprocessing.pipeline doc.pdf ./out
  python -m scripts.preprocessing.pipeline ./pdfs/ ./out
  python -m scripts.preprocessing.pipeline doc.pdf ./out --pages 0 20
  python -m scripts.preprocessing.pipeline ./pdfs/ ./out --glob "*.pdf"
  python -m scripts.preprocessing.pipeline doc.pdf ./out --force-reextract
        """,
    )
    p.add_argument("input",  help="PDF file or folder containing PDFs")
    p.add_argument("output", help="Output directory")
    p.add_argument("--force-reextract", action="store_true",
                   help="Ignore cache and re-run Stages 1+2")
    p.add_argument("--pages", nargs=2, type=int, metavar=("START", "END"),
                   help="Only process pages START..END, 0-indexed (single PDF only)")
    p.add_argument("--glob", default="*.pdf",
                   help="Glob pattern for PDF search in folder (default: *.pdf)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--skip-refine", action="store_true",
                   help="Skip Stage 4 (LLM-based section refinement)")
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

    try:
        run(
            input_path=args.input,
            output_dir=args.output,
            force_reextract=args.force_reextract,
            page_range=page_range,
            glob=args.glob,
            skip_refine=args.skip_refine,
        )
        sys.exit(0)
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()