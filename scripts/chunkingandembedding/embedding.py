"""
embedding.py – Step 3: Create embeddings and build FAISS index.

Uses Qwen3-VL-Embedding-8B via the project's Qwen3VLEmbedder wrapper
to create text and vision-language embeddings.  All embeddings are stored
in a single FAISS IDMap(IndexFlatIP) with globally unique IDs.

The database is the single source of truth for which items have been
embedded.  On --force, old FAISS IDs are removed from both the DB and
the index before re-embedding.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import faiss
import torch
import numpy as np

from .config import EMBEDDING_MODEL, EMBEDDING_DIM, EMBEDDING_BATCH_SIZE, MAX_TOKEN_LENGTH
from .chunking import EmbeddingInput
from .database import write_embedding_ids_batch

log = logging.getLogger(__name__)


def load_or_create_index(index_path: Path) -> tuple[faiss.Index, int]:
    """
    Load an existing FAISS index or create a new IDMap(IndexFlatIP).

    Returns:
        Tuple of (index, next_id) where next_id is the next available
        FAISS vector ID.
    """
    if index_path.exists():
        log.info("Loading existing FAISS index: %s", index_path)
        index = faiss.read_index(str(index_path))
        next_id = index.ntotal
        log.info("Index contains %d vectors, next ID: %d", index.ntotal, next_id)
        return index, next_id

    log.info("Creating new FAISS IDMap(IndexFlatIP) with dim=%d", EMBEDDING_DIM)
    base_index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index = faiss.IndexIDMap(base_index)
    return index, 0


def save_index(index: faiss.Index, index_path: Path) -> None:
    """Save the FAISS index to disk."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))
    log.info("FAISS index saved: %s (%d vectors)", index_path, index.ntotal)


def remove_ids_from_index(index: faiss.Index, ids: list[int]) -> int:
    """
    Remove vectors by their IDs from a FAISS IDMap index.

    Args:
        index: The FAISS IDMap index.
        ids:   List of vector IDs to remove.

    Returns:
        Number of vectors actually removed.
    """
    if not ids:
        return 0
    id_array = np.array(ids, dtype=np.int64)
    removed = index.remove_ids(id_array)
    log.info("Removed %d vectors from FAISS index", removed)
    return removed


def load_embedder(model_name: str = EMBEDDING_MODEL):
    """Load the embedding model, data-parallel across all visible GPUs in bf16.

    Returns a MultiGPUEmbedder (one replica per GPU); it exposes the same
    ``process()`` interface as a single Qwen3VLEmbedder and degenerates to one
    replica when only a single device is visible.
    """
    from scripts.qwen3_vl_embedding import MultiGPUEmbedder
    log.info("Loading embedding model: %s", model_name)
    model = MultiGPUEmbedder(
        model_name_or_path=model_name,
        max_length=MAX_TOKEN_LENGTH,
        dtype=torch.bfloat16,
    )
    log.info("Embedding model loaded on %d device(s): %s",
             len(model.replicas), model.devices)
    return model


def create_embeddings(
    inputs: list[EmbeddingInput],
    index: faiss.Index,
    next_id: int,
    db_path: Path,
    embedder=None,
    *,
    model_name: str = EMBEDDING_MODEL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    index_path: Optional[Path] = None,
    save_every: int = 1000,
) -> int:
    """
    Create embeddings for a list of inputs (which may span many documents),
    add them to the FAISS index, and write the IDs to the database in batched
    transactions.

    Inputs are pooled *across documents* and split into two global groups —
    text-only and VL — each then packed into full ``batch_size`` batches. This
    keeps the GPU saturated regardless of how few items any single document
    contributes (a per-document caller would otherwise fire many tiny,
    half-empty batches). Each ``EmbeddingInput`` carries its own ``pdf_name``,
    so DB writeback is grouped per document within every batch.

    The FAISS index is persisted every ``save_every`` batches (and once at the
    end) when ``index_path`` is given, so a long run survives interruption.

    Args:
        inputs:      List of EmbeddingInput objects (may mix pdf_names).
        index:       FAISS IDMap index to add vectors to.
        next_id:     Next available FAISS ID.
        db_path:     Path to the SQLite database for ID writeback.
        embedder:    Pre-loaded embedder (loaded lazily if None).
        model_name:  Model name/path for lazy loading.
        batch_size:  Number of items per embedding batch.
        index_path:  If given, the index is checkpointed here periodically.
        save_every:  Persist the index every N successful batches. The whole
                     index is rewritten each time (FAISS has no incremental
                     flush) and it grows to multiple GB, so this is deliberately
                     coarse — it is crash insurance, not a per-batch durability
                     guarantee. The final save always happens regardless.

    Returns:
        Updated next_id after all embeddings have been added.
    """
    if not inputs:
        return next_id

    if embedder is None:
        embedder = load_embedder(model_name)

    text_inputs = [inp for inp in inputs if inp.image is None]
    vl_inputs = [inp for inp in inputs if inp.image is not None]

    start_id = next_id
    saved_batches = 0

    for group_label, group in [("text", text_inputs), ("vl", vl_inputs)]:
        if not group:
            continue

        total_batches = (len(group) + batch_size - 1) // batch_size
        log.info("Processing %d %s inputs in %d batches", len(group), group_label, total_batches)

        for batch_idx, batch_start in enumerate(range(0, len(group), batch_size)):
            batch = group[batch_start : batch_start + batch_size]

            model_inputs = []
            for inp in batch:
                item: dict = {"text": inp.text}
                if inp.image:
                    item["image"] = inp.image
                model_inputs.append(item)

            try:
                embeddings = embedder.process(model_inputs)
            except Exception as e:
                log.error(
                    "[%s] Batch %d/%d failed (items %d-%d): %s",
                    group_label, batch_idx + 1, total_batches,
                    batch_start, batch_start + len(batch), e,
                )
                continue

            vectors = embeddings.detach().to(torch.float32).cpu().numpy()

            ids = np.arange(next_id, next_id + len(vectors), dtype=np.int64)
            index.add_with_ids(vectors, ids)

            # The batch may straddle several documents — write each doc's ids
            # into its own row group.
            records_by_doc: dict[str, list[tuple]] = defaultdict(list)
            for i, inp in enumerate(batch):
                records_by_doc[inp.pdf_name].append(
                    (inp.embedding_type, inp.section_index, inp.item_id, int(ids[i]))
                )
            for doc_name, db_records in records_by_doc.items():
                write_embedding_ids_batch(db_path, doc_name, db_records)

            next_id += len(vectors)
            saved_batches += 1

            if index_path is not None and save_every and saved_batches % save_every == 0:
                save_index(index, index_path)

            log.info(
                "[%s] Batch %d/%d done – %d items, %d doc(s) (ids %d-%d)",
                group_label, batch_idx + 1, total_batches,
                len(batch), len(records_by_doc), int(ids[0]), int(ids[-1]),
            )

    if index_path is not None:
        save_index(index, index_path)

    created = next_id - start_id
    log.info("Created %d/%d embeddings, index now has %d vectors", created, len(inputs), index.ntotal)
    return next_id