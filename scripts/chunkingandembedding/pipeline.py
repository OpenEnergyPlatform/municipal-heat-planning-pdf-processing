"""
pipeline.py – Orchestration of the chunkingandembedding module.

Steps:
  1. Merge: Combine structured_output_final.json + structured_output_images.json
  2. Database: Insert sections, tables, images into SQLite
  3. Embedding: Create text + VL embeddings, build FAISS index
     (writes IDs to DB immediately after each batch)

CLI:
  python -m scripts.chunkingandembedding /data/processed/ /path/to/KWP.db /path/to/faiss.index
  python -m scripts.chunkingandembedding /data/processed/ /path/to/KWP.db /path/to/faiss.index --step merge

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import MERGED_JSON, EMBEDDING_MODEL
from .merge import merge_batch
from .database import (
    update_database,
    get_existing_embeddings,
    clear_embedding_ids,
    get_document_faiss_ids,
    next_faiss_id,
)
from .chunking import build_embedding_inputs
from .embedding import (
    load_or_create_index,
    save_index,
    remove_ids_from_index,
    create_embeddings,
    load_embedder,
)

log = logging.getLogger(__name__)


def run(
    data_dir: str | Path,
    db_path: str | Path,
    index_path: str | Path,
    *,
    step: Optional[str] = None,
    force: bool = False,
) -> None:
    """
    Run all steps (or a specific step) of the chunking and embedding pipeline.

    Args:
        data_dir:    Root directory containing PDF subdirectories.
        db_path:     Path to the SQLite database.
        index_path:  Path to the FAISS index file.
        step:        Run only a specific step: 'merge', 'db', 'embed', or None for all.
        force:       Force re-processing (ignore caches, clear old embeddings).
    """
    data_dir = Path(data_dir)
    db_path = Path(db_path)
    index_path = Path(index_path)

    steps = [step] if step else ["merge", "db", "embed"]

    if "merge" in steps:
        sep = "=" * 60
        log.info(sep)
        log.info("Step 1: Merging preprocessing + imageprocessing outputs")
        log.info(sep)
        merge_batch(data_dir, force=force)

    # Snapshot the FAISS ids of each document BEFORE Step 2's forced delete
    # removes the Embeddings rows, so Step 3 can still evict the stale vectors
    # from the shared index. (Only needed when both steps run under --force; an
    # embed-only --force still finds the rows via clear_embedding_ids.)
    evict_ids: dict[str, list[int]] = {}
    if force and "db" in steps and "embed" in steps:
        for d in sorted(p for p in data_dir.iterdir()
                        if p.is_dir() and (p / MERGED_JSON).exists()):
            ids = get_document_faiss_ids(db_path, d.name)
            if ids:
                evict_ids[d.name] = ids

    if "db" in steps:
        sep = "=" * 60
        log.info(sep)
        log.info("Step 2: Updating database")
        log.info(sep)
        update_database(db_path, data_dir, force=force)

    if "embed" in steps:
        sep = "=" * 60
        log.info(sep)
        log.info("Step 3: Creating embeddings")
        log.info(sep)

        index, next_id = load_or_create_index(index_path)
        # The DB is the id source of truth: never reuse an id still held by a
        # row (index.ntotal is a live count and can dip below the high-water
        # mark after a --force eviction, which the faiss_id PK would reject).
        next_id = max(next_id, next_faiss_id(db_path))
        embedder = load_embedder(EMBEDDING_MODEL)

        candidates = sorted(
            d for d in data_dir.iterdir()
            if d.is_dir() and (d / MERGED_JSON).exists()
        )

        log.info("Found %d PDFs with merged output", len(candidates))

        # Gather every document's new inputs into one pool, then embed them in
        # full cross-document batches (see create_embeddings). Each input keeps
        # its pdf_name, so DB writeback stays correct. Building the inputs is
        # cheap (text + image *paths*, not pixel data), so pooling is light.
        all_inputs: list = []
        for i, pdf_dir in enumerate(candidates):
            pdf_name = pdf_dir.name

            if force:
                # Prefer the pre-Step-2 snapshot (rows may already be deleted);
                # fall back to a live read when db step did not run this time.
                old_ids = evict_ids.get(pdf_name)
                stragglers = clear_embedding_ids(db_path, pdf_name)
                if old_ids is None:
                    old_ids = stragglers
                if old_ids:
                    remove_ids_from_index(index, old_ids)

            existing = get_existing_embeddings(db_path, pdf_name)

            with open(pdf_dir / MERGED_JSON, "r", encoding="utf-8") as f:
                merged_data = json.load(f)

            inputs = build_embedding_inputs(merged_data, pdf_name, pdf_dir)

            inputs = [
                inp for inp in inputs
                if (inp.embedding_type, inp.section_index, inp.item_id)
                not in existing
            ]

            if inputs:
                all_inputs.extend(inputs)

        log.info(
            "Pooled %d new items to embed across %d/%d docs",
            len(all_inputs), sum(1 for _ in candidates), len(candidates),
        )

        if all_inputs:
            next_id = create_embeddings(
                all_inputs, index, next_id, db_path, embedder=embedder,
                index_path=index_path,
            )

        save_index(index, index_path)
        log.info("Embedding complete: %d total vectors in index", index.ntotal)


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="python -m scripts.chunkingandembedding",
        description="Chunking & Embedding – Merge, embed, and index pipeline outputs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m scripts.chunkingandembedding ./data/processed/ ./KWP.db ./faiss.index
  python -m scripts.chunkingandembedding ./data/processed/ ./KWP.db ./faiss.index --step merge
  python -m scripts.chunkingandembedding ./data/processed/ ./KWP.db ./faiss.index --step embed
  python -m scripts.chunkingandembedding ./data/processed/ ./KWP.db ./faiss.index --force
        """,
    )
    p.add_argument("data_dir", help="Root directory containing PDF subdirectories")
    p.add_argument("db_path", help="Path to the SQLite database file")
    p.add_argument("index_path", help="Path to the FAISS index file")
    p.add_argument(
        "--step", choices=["merge", "db", "embed"], default=None,
        help="Run only a specific step (default: all steps)",
    )
    p.add_argument("--force", action="store_true", help="Force re-processing")
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

    try:
        run(
            data_dir=args.data_dir,
            db_path=args.db_path,
            index_path=args.index_path,
            step=args.step,
            force=args.force,
        )
        sys.exit(0)
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()