"""
store.py – The project's own table: publication metadata. The core never
touches it.

Author: Felix Vossel
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from docpipe.store import documents as core_documents


def document_id(filename: str, connection: sqlite3.Connection) -> Optional[int]:
    """The id the core gave this file, or None if it was never registered."""
    row = connection.execute(
        "SELECT id FROM Documents WHERE filename = ?", (filename,)).fetchone()
    return row[0] if row else None


def upsert_publication_meta(document: int, values: dict,
                            connection: sqlite3.Connection) -> None:
    """Refresh the publication's DocumentMeta row.

    The core writes it once, when the document is first registered. A re-run
    skips an already registered document, so this is the only path by which
    metadata that arrived after the first import (the OpenAlex fetch runs on its
    own schedule) reaches the corpus.
    """
    core_documents.upsert_document_meta(document, values, connection)
