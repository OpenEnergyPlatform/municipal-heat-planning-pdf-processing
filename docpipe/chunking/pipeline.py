"""
pipeline.py – Orchestration of the chunkingandembedding module: merge → db → embed.

CLI:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db /path/to/faiss.index

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from docpipe.profile import add_profile_argument, resolve_profile

from .config import (
    EMBED_FLUSH_ITEMS,
    EMBED_PREPARE_WORKERS,
    EMBEDDING_MODEL,
    DOCUMENT_JSON,
)
from .merge import merge_batch
from .database import (
    update_database,
    enrich_bbox,
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
    Run the pipeline over the PDF subdirectories of `data_dir`.

    `step` limits the run to 'merge', 'db', 'embed' or the standalone
    'enrich-bbox'; None runs merge → db → embed. `force` ignores caches and
    clears old embeddings.
    """
    data_dir = Path(data_dir)
    db_path = Path(db_path)
    index_path = Path(index_path)

    # Standalone maintenance step: never part of the default merge→db→embed run.
    if step == "enrich-bbox":
        sep = "=" * 60
        log.info(sep)
        log.info("Additive bbox backfill (non-destructive; no re-embed)")
        log.info(sep)
        enrich_bbox(db_path, data_dir, force=force)
        return

    steps = [step] if step else ["merge", "db", "embed"]

    if "merge" in steps:
        sep = "=" * 60
        log.info(sep)
        log.info("Step 1: Merging preprocessing + imageprocessing outputs")
        log.info(sep)
        merge_batch(data_dir, force=force)

    # Must run BEFORE the db step's forced delete removes the Embeddings rows,
    # or the embed step can no longer evict the stale vectors from the index.
    evict_ids: dict[str, list[int]] = {}
    if force and "db" in steps and "embed" in steps:
        for d in sorted(p for p in data_dir.iterdir()
                        if p.is_dir() and (p / DOCUMENT_JSON).exists()):
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
        # The DB is the id source of truth; index.ntotal alone can reuse an id.
        next_id = max(next_id, next_faiss_id(db_path))
        embedder = load_embedder(EMBEDDING_MODEL)

        candidates = sorted(
            d for d in data_dir.iterdir()
            if d.is_dir() and (d / DOCUMENT_JSON).exists()
        )

        log.info("Found %d PDFs with merged output", len(candidates))

        # Index eviction is the one part that must stay on this thread: it
        # mutates the FAISS index, which the embedding loop also writes to.
        if force:
            for pdf_dir in candidates:
                pdf_name = pdf_dir.name
                # Prefer the snapshot (rows may already be deleted); fall back
                # to a live read when the db step did not run this time.
                old_ids = evict_ids.get(pdf_name)
                stragglers = clear_embedding_ids(db_path, pdf_name)
                if old_ids is None:
                    old_ids = stragglers
                if old_ids:
                    remove_ids_from_index(index, old_ids)

        # Reading a document's merged JSON and asking the DB what it already has
        # took 6.6 s per document in the last full run — 91 of 184 minutes, with
        # every GPU idle, because all 800 documents were prepared before the
        # first batch was embedded. Prepared in a pool, the work overlaps with
        # the embedding instead of preceding it.
        def prepare(pdf_dir):
            pdf_name = pdf_dir.name
            existing = get_existing_embeddings(db_path, pdf_name)
            with open(pdf_dir / DOCUMENT_JSON, "r", encoding="utf-8") as f:
                merged_data = json.load(f)
            return [
                inp for inp in build_embedding_inputs(merged_data, pdf_name, pdf_dir)
                if (inp.embedding_type, inp.section_index, inp.item_id) not in existing
            ]

        # Embedded in chunks rather than one pooled call: the pool keeps
        # preparing while the GPUs work on what is ready. A chunk still holds
        # thousands of items, which is what the length sorting in
        # create_embeddings needs to build length-homogeneous batches.
        pending: list = []
        docs_with_inputs = 0
        embedded = 0

        with ThreadPoolExecutor(max_workers=EMBED_PREPARE_WORKERS) as pool:
            for inputs in pool.map(prepare, candidates):
                if not inputs:
                    continue
                docs_with_inputs += 1
                pending.extend(inputs)
                if len(pending) >= EMBED_FLUSH_ITEMS:
                    embedded += len(pending)
                    next_id = create_embeddings(
                        pending, index, next_id, db_path, embedder=embedder,
                        index_path=index_path,
                    )
                    pending = []

        if pending:
            embedded += len(pending)
            next_id = create_embeddings(
                pending, index, next_id, db_path, embedder=embedder,
                index_path=index_path,
            )

        log.info(
            "Embedded %d new items across %d/%d docs",
            embedded, docs_with_inputs, len(candidates),
        )

        save_index(index, index_path)
        log.info("Embedding complete: %d total vectors in index", index.ntotal)


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="python -m docpipe.chunking",
        description="Chunking & Embedding – Merge, embed, and index pipeline outputs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m docpipe.chunking ./data/processed/ ./KWP.db ./faiss.index
  python -m docpipe.chunking ./data/processed/ ./KWP.db ./faiss.index --step merge
  python -m docpipe.chunking ./data/processed/ ./KWP.db ./faiss.index --step embed
  python -m docpipe.chunking ./data/processed/ ./KWP.db ./faiss.index --force
        """,
    )
    p.add_argument("data_dir", nargs="?", default=None,
                   help="Root with the PDF subdirectories "
                        "(default: the profile's processed directory)")
    p.add_argument("db_path", nargs="?", default=None,
                   help="SQLite database (default: the profile's)")
    p.add_argument("index_path", nargs="?", default=None,
                   help="FAISS index (default: the profile's)")
    p.add_argument(
        "--step", choices=["merge", "db", "embed", "enrich-bbox"], default=None,
        help="Run only a specific step (default: merge, db, embed). "
             "'enrich-bbox' additively backfills segment/table/image bbox from "
             "re-run Stage-3 outputs without re-embedding (index_path is ignored).",
    )
    add_profile_argument(p)
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

    profile = resolve_profile(args)
    if profile is not None:
        args.data_dir = args.data_dir or str(profile.processed_dir)
        args.db_path = args.db_path or str(profile.db_path)
        args.index_path = args.index_path or str(profile.index_path)
    missing = [n for n in ("data_dir", "db_path", "index_path") if not getattr(args, n)]
    if missing:
        raise SystemExit(f"missing path(s): {', '.join(missing)} — give them or a --profile")

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