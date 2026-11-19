"""
holes.py: What an earlier stage left without content in the documents a run
reads (owner request 2026-11-19).

Stage 5 can leave a table or figure without content; the merge writes those
into the document and the database keeps them beside it (Documents.holes,
`docpipe.visuals.holes`). A run reads them with the documents
(`runner.note_documents`). In such a document a value whose search found
nothing is no finding about the document: what it would have been read from
may stand in what has no content. So its search ends in the state of
`unstated_with_holes`, and a field with no value in that of
`parameter_with_holes` (rule `state_rules`, both "exhausted" by default: a
finding about the run). The stamp records the holes, and one filled since
makes the document work again (`runner.holes_filled`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
import threading

# {document id: [{"id", "kind", "page", "why"}]} of the run's database.
_BY_ID: dict = {}
_LOCK = threading.Lock()


def parse(text) -> list:
    """The holes the database keeps for a document (Documents.holes, JSON),
    as a list; [] for none, NULL or anything unreadable."""
    if not text:
        return []
    try:
        found = json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return []
    return [h for h in found if isinstance(h, dict)] \
        if isinstance(found, list) else []


def note(document_id, found: list) -> None:
    """Record the holes of one document of the run's database."""
    with _LOCK:
        if found:
            _BY_ID[document_id] = list(found)
        else:
            _BY_ID.pop(document_id, None)


def clear() -> None:
    with _LOCK:
        _BY_ID.clear()


def of(document_id) -> list:
    """The holes of the document, [] where it has none or none is known."""
    with _LOCK:
        return list(_BY_ID.get(document_id) or ())


def ids(found) -> set:
    """The ids of the items of *found* (holes as recorded)."""
    return {h.get("id") for h in found or () if isinstance(h, dict)
            and h.get("id") is not None}
