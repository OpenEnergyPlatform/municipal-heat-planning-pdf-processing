"""
trace.py – What the harvest did, written down so it can be counted afterwards.

The text log says what happened to a human reading it live. It cannot answer
"at which rank was this value found", "in which window did this coordinate
close", "did the retry help", because those are questions about a million
requests and the answer is a distribution, not a line. Every setting this
stage has was picked without such a distribution at least once, and every one
of those picks was wrong: top_k, the window budget, the batch threads.

So each document gets a second file next to its harvest, one JSON object per
event, and nothing in it is aggregated. Aggregating is what the report script
does, and it can be rewritten when the question changes. The trace cannot.

Cost is a few hundred bytes per model request, about half a megabyte per
document. EXTRACT_TRACE=0 turns it off and every call becomes a return.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

ENABLED = os.environ.get("EXTRACT_TRACE", "1") != "0"

_lock = threading.Lock()
_files: dict = {}
_root: Optional[Path] = None
_name_of: Optional[Callable] = None


def open_trace(directory, name_of: Callable) -> None:
    """Start writing traces under `directory`, naming files via `name_of(id)`."""
    global _root, _name_of
    if not ENABLED:
        return
    _root = Path(directory)
    _root.mkdir(parents=True, exist_ok=True)
    _name_of = name_of


def _handle(document_id: int):
    """The open file for this document, truncated the first time it is asked for.

    Truncated, not appended: a document harvested a second time in the same
    run is a document being redone, and a trace holding both attempts cannot
    be counted without knowing which line belongs to which.
    """
    handle = _files.get(document_id)
    if handle is not None:
        return handle
    name = (_name_of(document_id) if _name_of else None) or f"doc{document_id}"
    path = _root / f"{name}.trace.jsonl"
    handle = open(path, "w", encoding="utf-8", buffering=1 << 16)
    _files[document_id] = handle
    return handle


def event(kind: str, document_id: Optional[int] = None, /, **fields) -> None:
    """One line of trace. Never raises: a broken trace must not kill a harvest.

    Both arguments are positional-only: an event's own fields are free-form
    and several of them are called `kind` or `status`, which would otherwise
    collide with the signature rather than land in the record.
    """
    if not ENABLED or _root is None or document_id is None:
        return
    try:
        record = {"t": kind, "doc": document_id}
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            _handle(document_id).write(line + "\n")
    except Exception as exc:                      # pragma: no cover - defensive
        log.debug("trace: %s dropped: %s", kind, exc)


def flush(document_id: Optional[int] = None) -> None:
    """Push what is buffered to disk, for one document or for all of them."""
    if not ENABLED or _root is None:
        return
    with _lock:
        targets = ([_files[document_id]] if document_id in _files
                   else list(_files.values()) if document_id is None else [])
        for handle in targets:
            try:
                handle.flush()
            except Exception:                     # pragma: no cover - defensive
                pass


def close() -> None:
    """Close every open trace. Safe to call twice."""
    with _lock:
        for handle in _files.values():
            try:
                handle.close()
            except Exception:                     # pragma: no cover - defensive
                pass
        _files.clear()
