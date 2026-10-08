"""
embedding.py: Creates text and vision-language embeddings and builds
the FAISS index, as chunking's third step.

Every embedding lives in one FAISS IDMap(IndexFlatIP), keyed by
globally unique ids allocated from the database.

Where the vectors come from is EMBEDDING_INDEX_BACKEND: `local` runs the
model in this process on the visible GPUs; `api` asks an embeddings endpoint
and needs none. A setting of its own beside the query side's
EMBEDDING_BACKEND, because the two differ in a common setup: the index is
built once with the model on GPUs and queried through an endpoint ever
after. An endpoint takes text only, so with it the inputs that carry a
picture are left out and the index holds the text vectors of a corpus.

A batch the embedder could not serve leaves its inputs without a vector. The
other batches are finished first; the inputs left over are counted by
embedding type and by document, and the run ends with them named, not with
them forgotten.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

from .config import EMBEDDING_MODEL, EMBEDDING_DIM, EMBEDDING_BATCH_SIZE, MAX_TOKEN_LENGTH
from .chunking import EmbeddingInput
from .database import EmbeddingWriter

if TYPE_CHECKING:       # imported where it is used: a build through an api needs none before
    import faiss

log = logging.getLogger(__name__)


class IncompleteIndex(RuntimeError):
    """A run ended with inputs that have no vector. What was embedded stays;
    a rerun embeds the rest."""


class Unembedded:
    """The inputs of a run that came back without a vector.

    Counted by embedding type and by document, so the sentence that ends the
    run says how many inputs of which kind have none. Inputs a text-only
    backend leaves out on purpose are not here: nothing went wrong with them.
    """

    def __init__(self) -> None:
        self.by_type: Counter = Counter()
        self.documents: set = set()

    def add(self, inputs) -> None:
        for inp in inputs:
            self.by_type[inp.embedding_type] += 1
            self.documents.add(inp.pdf_name)

    def __len__(self) -> int:
        """How many inputs have no vector."""
        return sum(self.by_type.values())

    def sentence(self) -> str:
        kinds = ", ".join(f"{kind}={n}"
                          for kind, n in sorted(self.by_type.items()))
        return (f"{len(self)} input(s) of {len(self.documents)} document(s) "
                f"have no vector ({kinds}); a rerun embeds them")


def load_or_create_index(index_path: Path) -> tuple[faiss.Index, int]:
    """
    Load an existing FAISS index or create a new IDMap(IndexFlatIP).

    Returns (index, next_id). next_id is only a floor derived from ntotal —
    reconcile it with next_faiss_id(db) before allocating.
    """
    import faiss
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


def index_ids(index: faiss.Index) -> list:
    """Every FAISS id the index currently holds.

    ntotal counts vectors, this names them. Needed because ids are allocated
    from a high-water mark and because a DB row is only trustworthy if its
    vector is really in the index.
    """
    id_map = getattr(index, "id_map", None)
    if id_map is None:                       # a plain, non-IDMap index
        return []
    import faiss
    try:
        return [int(i) for i in faiss.vector_to_array(id_map)]
    except Exception:                        # a test double, or an empty map
        return [int(i) for i in id_map]


def save_index(index: faiss.Index, index_path: Path) -> None:
    """Save the FAISS index to disk."""
    import faiss
    index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))
    log.info("FAISS index saved: %s (%d vectors)", index_path, index.ntotal)


def remove_ids_from_index(index: faiss.Index, ids: list[int]) -> int:
    """Remove vectors by id from a FAISS IDMap index; returns the count removed."""
    if not ids:
        return 0
    id_array = np.array(ids, dtype=np.int64)
    removed = index.remove_ids(id_array)
    log.info("Removed %d vectors from FAISS index", removed)
    return removed


def index_backend() -> str:
    """What builds the index: `local` or `api`."""
    return os.environ.get("EMBEDDING_INDEX_BACKEND", "local").strip()


class ApiIndexEmbedder:
    """The api backend at index time: items in, one unit vector each out.

    The index is an inner-product index and the local model hands it unit
    vectors, so these are scaled to length one as well; an endpoint that
    already returns unit vectors is left as it is by that.
    """
    text_only = True

    def __init__(self, embedder=None):
        if embedder is None:
            from docpipe.embedding.api import ApiEmbedder
            embedder = ApiEmbedder()
        self._embedder = embedder
        self.model = getattr(embedder, "model", None)

    def process(self, items):
        vectors = np.asarray(self._embedder.embed(items), dtype=np.float32)
        lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(lengths == 0, 1.0, lengths)


def _as_array(embeddings):
    """A batch of vectors as float32, whichever backend made it."""
    if hasattr(embeddings, "detach"):           # a torch tensor
        import torch
        return embeddings.detach().to(torch.float32).cpu().numpy()
    return np.asarray(embeddings, dtype=np.float32)


def load_embedder(model_name: str = EMBEDDING_MODEL):
    """
    The embedder of this run, for the backend EMBEDDING_INDEX_BACKEND names.

    `api`: an ApiIndexEmbedder. Otherwise the model itself, data-parallel
    across all visible GPUs in bf16: a MultiGPUEmbedder, which exposes the
    same ``process()`` interface as a single Qwen3VLEmbedder.
    """
    if index_backend() == "api":
        embedder = ApiIndexEmbedder()
        log.info("Embedding through the api backend: %s (text inputs only)",
                 embedder.model)
        return embedder
    import torch
    from docpipe.chunking.qwen3_vl_embedding import MultiGPUEmbedder
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
    unembedded: Optional[Unembedded] = None,
) -> int:
    """
    Embed `inputs` (which may mix pdf_names), add the vectors to `index`, and
    write their ids to the DB. Returns the updated next_id.

    Inputs are split into text-only and VL groups and packed into full
    ``batch_size`` batches across documents; each input's ``pdf_name`` keeps the
    DB writeback grouped per document.

    A batch that fails is logged and the others are finished. Its inputs have
    no row, so a rerun finds them again. They are added to `unembedded`, which
    the caller keeps across calls and ends its run on. Without one this call
    raises IncompleteIndex once every batch has been tried, with the vectors
    of the others already in `index` and the database: a failure is never
    only a log line.

    Persisting the index is the caller's: this is called once per flush chunk,
    and the index is one file rewritten whole.
    """
    if not inputs:
        return next_id

    if embedder is None:
        embedder = load_embedder(model_name)

    text_inputs = [inp for inp in inputs if inp.image is None]
    vl_inputs = [inp for inp in inputs if inp.image is not None]
    if vl_inputs and getattr(embedder, "text_only", False):
        log.warning("%d input(s) with a picture are not embedded: this "
                    "backend takes text only", len(vl_inputs))
        vl_inputs = []

    start_id = next_id
    missed = Unembedded() if unembedded is None else unembedded

    with EmbeddingWriter(db_path) as writer:
        for group_label, group in [("text", text_inputs), ("vl", vl_inputs)]:
            if not group:
                continue

            # Batches pad to their longest member. Unsorted, a section title of
            # five tokens rides in the same batch as an 1800-word section and
            # costs the same — sorting by length puts short with short, so the
            # padding a batch carries is bounded by its own spread instead of the
            # corpus-wide max. Order is free: a vector's identity comes from the
            # (type, section, item) triple written alongside its FAISS id, not
            # from its position.
            group = sorted(group, key=lambda inp: len(inp.text or ""))

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
                    missed.add(batch)
                    continue

                vectors = _as_array(embeddings)
                held = getattr(index, "d", None)
                if (isinstance(held, int) and vectors.ndim == 2
                        and vectors.shape[1] != held):
                    # Not a batch that failed: every batch of this run would,
                    # and a vector of another model has no place in the index.
                    raise ValueError(
                        f"the embedder returns vectors of {vectors.shape[1]} "
                        f"dimensions, the index holds {held}: set "
                        f"EMBEDDING_DIM={vectors.shape[1]} for a new index, "
                        f"or embed with the model this index was built with")

                ids = np.arange(next_id, next_id + len(vectors), dtype=np.int64)
                index.add_with_ids(vectors, ids)

                # The batch may straddle several documents.
                records_by_doc: dict[str, list[tuple]] = defaultdict(list)
                for i, inp in enumerate(batch):
                    records_by_doc[inp.pdf_name].append(
                        (inp.embedding_type, inp.section_index, inp.item_id, int(ids[i]))
                    )
                for doc_name, db_records in records_by_doc.items():
                    writer.write(doc_name, db_records)

                next_id += len(vectors)

                log.info(
                    "[%s] Batch %d/%d done – %d items, %d doc(s) (ids %d-%d)",
                    group_label, batch_idx + 1, total_batches,
                    len(batch), len(records_by_doc), int(ids[0]), int(ids[-1]),
                )

    created = next_id - start_id
    log.info("Created %d/%d embeddings, index now has %d vectors", created, len(inputs), index.ntotal)
    if unembedded is None and missed:
        raise IncompleteIndex(missed.sentence())
    return next_id