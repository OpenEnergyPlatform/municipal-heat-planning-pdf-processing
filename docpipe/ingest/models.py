"""
models.py: What a profile hands the ingest step.

The core knows a document by four things: what to call it, where to get it, who
it is, and which other documents are versions of it. Everything else is the
profile's business and travels in `meta` (written to DocumentMeta) or `payload`
(never inspected by the core).

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class UnusablePDF(Exception):
    """A source PDF has no usable text layer — it is not registered."""


@dataclass
class SourceDoc:
    # the profile's stable identity (heat plans: the file name, papers: the DOI)
    external_id: str
    filename: str
    # where to fetch it; None means it must already lie in the data directory
    url: Optional[str] = None
    group_key: Optional[str] = None
    published: Optional[str] = None
    meta: dict = field(default_factory=dict)      # -> DocumentMeta columns
    payload: dict = field(default_factory=dict)   # opaque to the core


class Source:
    """A profile's document source.

    `documents` receives the open connection because a profile usually has to
    write its own rows (an organisation, a municipality) before it can name the
    document's metadata. `after_document` runs once per yielded document that
    was accepted — a rejected PDF must not leave project rows behind.
    """

    def documents(self, connection):
        raise NotImplementedError

    def after_document(self, connection, doc: SourceDoc) -> None:
        pass

    def __len__(self):
        """Optional: number of documents, for the progress bar."""
        raise TypeError
