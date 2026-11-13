"""
reembed.py: Embeds every item of an index again, into a new index file and
under the ids it already has.

A vector is comparable only with vectors embedded the same way: the same
model, and the same implementation of it. Moving the embedder to a vLLM
server (the messages form, docpipe/embedding/api.py) changes every vector,
so the corpus is embedded again as a whole. The database keeps its ids and
is not written: each item's vector goes into the new file under the id the
database already gives it. The old file stays as it is, and a run moves to
the new one by its path.

A record beside the new file (`<index>.json`) says what made it and how far
it got. Only a file with such a record is continued; any other file that
exists is refused, so the index a run reads cannot be written into by
naming it here.

What cannot be embedded again is counted and named, never filled in:

- an id the database maps whose item the processed output no longer builds
  (`no_input`): its old vector stays in the old file only;
- an item the output builds that has no id (`no_id`): the old index lacks it
  too, and the embed step, which hands out ids, embeds it;
- an item the embedder could not serve on its own, after its batch failed
  (`missed`): the run ends incomplete, and a rerun embeds it.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .config import (DOCUMENT_JSON, EMBED_FLUSH_ITEMS, EMBED_PREPARE_WORKERS,
                     EMBED_SAVE_VECTORS, EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL)
from .embedding import (IncompleteIndex, Unembedded, _as_array, index_backend,
                        index_ids, load_embedder, load_or_create_index,
                        save_index)

log = logging.getLogger(__name__)


def record_path(index_path: Path) -> Path:
    """Where the record of a re-embedded index file lives: beside it."""
    index_path = Path(index_path)
    return index_path.with_name(index_path.name + ".json")


def check_target(index_path: Path) -> None:
    """Refuses a file that exists without a record: that is an index some run
    reads, and vectors of another embedder have no place in it."""
    index_path = Path(index_path)
    if index_path.exists() and not record_path(index_path).exists():
        raise ValueError(
            f"{index_path} exists and was not written by a re-embedding "
            f"(no {record_path(index_path).name} beside it): name a new file")


@dataclass
class Report:
    """What a re-embedding did, counted by embedding type where it left
    something out."""
    embedded: int = 0
    resumed: int = 0
    documents: int = 0
    no_id: Counter = field(default_factory=Counter)
    no_input: Counter = field(default_factory=Counter)
    unregistered: list = field(default_factory=list)
    missed: Unembedded = field(default_factory=Unembedded)

    def as_dict(self) -> dict:
        return {"embedded": self.embedded, "resumed": self.resumed,
                "documents": self.documents,
                "no_id": dict(self.no_id), "no_input": dict(self.no_input),
                "unregistered": sorted(self.unregistered),
                "missed": dict(self.missed.by_type)}


def plan(inputs: list, ids: dict, done: set) -> tuple:
    """(pending, no_id, no_input) for one document.

    *pending* pairs each input with the id the database gives its key, for
    the ids *done* does not hold yet; an id is taken once, so two inputs of
    one key embed only the first. *no_id* counts the inputs without an id
    and *no_input* the ids without an input, by embedding type.
    """
    pending: list = []
    no_id: Counter = Counter()
    keys = set()
    taken = set()
    for inp in inputs:
        key = (inp.embedding_type, inp.section_index, inp.item_id)
        keys.add(key)
        faiss_id = ids.get(key)
        if faiss_id is None:
            no_id[inp.embedding_type] += 1
        elif faiss_id not in done and faiss_id not in taken:
            taken.add(faiss_id)
            pending.append((faiss_id, inp))
    no_input = Counter(key[0] for key in ids if key not in keys)
    return pending, no_id, no_input


def _vectors(embedder, inputs: list) -> np.ndarray:
    items = []
    for inp in inputs:
        item: dict = {"text": inp.text}
        if inp.image:
            item["image"] = inp.image
        items.append(item)
    return _as_array(embedder.process(items))


def embed_into(index, pending: list, embedder, missed: Unembedded,
               batch_size: int = EMBEDDING_BATCH_SIZE) -> int:
    """Embeds *pending* (id, input) pairs in batches and adds each vector
    under its id; returns how many went in.

    A batch the embedder cannot serve is tried again input by input, so one
    input it cannot take does not cost the others their vectors; an input
    that fails on its own goes to *missed*.
    """
    added = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        try:
            pairs = list(zip(batch, _vectors(embedder, [inp for _, inp in batch])))
        except Exception as exc:
            log.warning("batch of %d input(s) failed (%s); trying them one "
                        "by one", len(batch), exc)
            pairs = []
            for one in batch:
                try:
                    pairs.append((one, _vectors(embedder, [one[1]])[0]))
                except Exception as alone:
                    log.error("%s %s section %d item %s has no vector: %s",
                              one[1].pdf_name, one[1].embedding_type,
                              one[1].section_index, one[1].item_id, alone)
                    missed.add([one[1]])
        if not pairs:
            continue
        vectors = np.stack([vector for _, vector in pairs]).astype(np.float32)
        held = getattr(index, "d", None)
        if isinstance(held, int) and vectors.shape[1] != held:
            raise ValueError(
                f"the embedder returns vectors of {vectors.shape[1]} "
                f"dimensions, the new index holds {held}: set EMBEDDING_DIM")
        ids = np.array([faiss_id for (faiss_id, _), _ in pairs], dtype=np.int64)
        index.add_with_ids(vectors, ids)
        added += len(pairs)
    return added


def write_record(path: Path, embedder, index, report: Report,
                 complete: bool) -> None:
    from docpipe.embedding import config as backend
    record = {
        "model": getattr(embedder, "model", None) or EMBEDDING_MODEL,
        "backend": index_backend(),
        "form": backend.EMBEDDING_API_FORMAT if index_backend() == "api" else None,
        "dim": getattr(index, "d", None),
        "vectors": int(index.ntotal),
        "complete": complete,
        "written": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **report.as_dict(),
    }
    path.write_text(json.dumps(record, indent=1, sort_keys=True),
                    encoding="utf-8")


def run_reembed(data_dir: Path, db_path: Path, index_path: Path, *,
                embedder=None) -> Report:
    """Embeds every item the database maps into *index_path*, a new file or
    one an earlier re-embedding began, under the ids the database gives them.

    Raises IncompleteIndex after saving when an input has no vector, and
    ValueError before anything is written when *index_path* is a file no
    re-embedding wrote or the embedder leaves pictures out.
    """
    from docpipe.artifacts import document_dirs
    from concurrent.futures import ThreadPoolExecutor

    from .chunking import build_embedding_inputs
    from .database import document_id, embedding_ids
    from .pipeline import prepared_ahead

    data_dir, db_path, index_path = Path(data_dir), Path(db_path), Path(index_path)
    check_target(index_path)
    if embedder is None:
        embedder = load_embedder(EMBEDDING_MODEL)
    if getattr(embedder, "text_only", False):
        raise ValueError(
            "this embedder leaves pictures out, and the new index would lack "
            "every table and figure image the old one holds: use "
            "EMBEDDING_API_FORMAT=messages with a vLLM server, or the local "
            "backend")

    index, _ = load_or_create_index(index_path)
    done = set(index_ids(index))
    report = Report(resumed=len(done))
    record = record_path(index_path)
    write_record(record, embedder, index, report, complete=False)

    def prepare(pdf_dir):
        doc = document_id(db_path, pdf_dir.name)
        if doc is None:
            return pdf_dir.name, None, {}
        with open(pdf_dir / DOCUMENT_JSON, "r", encoding="utf-8") as fh:
            merged = json.load(fh)
        return (pdf_dir.name,
                build_embedding_inputs(merged, pdf_dir.name, pdf_dir),
                embedding_ids(db_path, doc))

    candidates = document_dirs(data_dir, DOCUMENT_JSON)
    log.info("Re-embedding %d document(s) into %s (%d vector(s) already "
             "there)", len(candidates), index_path, len(done))
    pending: list = []
    saved = index.ntotal

    def flush() -> None:
        nonlocal pending, saved
        report.embedded += embed_into(index, pending, embedder, report.missed)
        pending = []
        if index.ntotal - saved >= EMBED_SAVE_VECTORS:
            save_index(index, index_path)
            write_record(record, embedder, index, report, complete=False)
            saved = index.ntotal
        log.info("%d document(s) read, %d vector(s) embedded",
                 report.documents, report.embedded)

    with ThreadPoolExecutor(max_workers=EMBED_PREPARE_WORKERS) as pool:
        for name, inputs, ids in prepared_ahead(pool, candidates, prepare):
            if inputs is None:
                report.unregistered.append(name)
                continue
            report.documents += 1
            todo, no_id, no_input = plan(inputs, ids, done)
            report.no_id.update(no_id)
            report.no_input.update(no_input)
            done.update(faiss_id for faiss_id, _ in todo)
            pending.extend(todo)
            if len(pending) >= EMBED_FLUSH_ITEMS:
                flush()
    if pending:
        flush()

    save_index(index, index_path)
    write_record(record, embedder, index, report,
                 complete=not report.missed)
    log.info("Re-embedded %d vector(s) into %s, %d in all; ids without an "
             "input %s, inputs without an id %s, unregistered directories %d",
             report.embedded, index_path, index.ntotal,
             dict(report.no_input) or "none", dict(report.no_id) or "none",
             len(report.unregistered))
    if report.missed:
        raise IncompleteIndex(report.missed.sentence())
    return report
