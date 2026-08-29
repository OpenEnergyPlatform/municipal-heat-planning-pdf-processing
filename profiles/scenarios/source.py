"""
source.py – Where the AR6 corpus comes from: pdf_index.json, the crawl over the
publications the AR6 scenario database cites.

One entry is one publication. Its PDF is staged by hand, and the scenarios it
documents become the link table.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from docpipe.ingest.models import Source, SourceDoc

from . import store
from .config import (
    AVAILABLE_STATUS,
    PDF_SUFFIX,
    PUBLICATION_META_FILE,
    PUBLISHED_DAY,
    SCENARIO_FILE,
)

log = logging.getLogger(__name__)


def has_local_pdf(entry: dict) -> bool:
    """Whether the crawl left a file for this entry. The rest is bibliography:
    a paywalled paper, or a citation of a whole journal volume."""
    return entry.get("status") == AVAILABLE_STATUS and bool(entry.get("path"))


def external_id_for(entry: dict) -> str:
    """A DOI identifies a paper. Agency reports, national roadmaps and working
    papers often have none, so the crawl's slug stands in."""
    return (entry.get("doi") or "").strip() or entry["slug"]


def filename_for(entry: dict) -> str:
    return entry["slug"] + PDF_SUFFIX


def extract_meta(entry: dict, publication_meta: dict) -> dict:
    """{db_column: value} for one entry's DocumentMeta row.

    publication_meta.json is the authority on title, year, venue and open
    access; the index fills in what it happens to carry. Whatever neither knows
    stays NULL — nothing is inferred from the DOI or read out of the PDF.
    """
    fetched = publication_meta.get(entry["slug"]) or {}
    year = fetched.get("year")
    return {
        "doi": entry.get("doi"),
        # The index carries a title for about half the entries, from the crawl's
        # own resolution step; it is the only title those have.
        "title": fetched.get("title") or entry.get("title"),
        "year": int(year) if year else None,
        "venue": fetched.get("venue"),
        "is_oa": _as_flag(fetched.get("is_oa", entry.get("is_oa"))),
        "scenario_count": len(entry.get("scenario_ids") or []),
    }


def published_for(year: Optional[int]) -> Optional[str]:
    return f"{year}{PUBLISHED_DAY}" if year else None


def _as_flag(value) -> Optional[int]:
    return None if value is None else int(bool(value))


def _optional_json(path: Path, default):
    """A sibling of the index that its own step of the crawl produces."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("%s is not there — the fields it carries stay unknown.", path.name)
        return default


class Ar6Source(Source):
    """The AR6 publication crawl as a document source."""

    def __init__(self, index_file: Path):
        self.index_file = Path(index_file)
        self._entries: Optional[list] = None
        self._scenario_names: dict = {}
        self._publication_meta: dict = {}

    def _load(self) -> list:
        if self._entries is not None:
            return self._entries
        entries = json.loads(self.index_file.read_text(encoding="utf-8"))
        self._entries = [e for e in entries if has_local_pdf(e)]
        skipped = len(entries) - len(self._entries)
        if skipped:
            log.info("%d of %d index entries have no local PDF — skipped.",
                     skipped, len(entries))
        folder = self.index_file.parent
        self._scenario_names = {int(s["id"]): s["name"]
                                for s in _optional_json(folder / SCENARIO_FILE, [])}
        self._publication_meta = _optional_json(folder / PUBLICATION_META_FILE, {})
        return self._entries

    def __len__(self) -> int:
        return len(self._load())

    def documents(self, connection: sqlite3.Connection):
        for entry in self._load():
            yield self.document_for(entry)

    def document_for(self, entry: dict) -> SourceDoc:
        self._load()
        meta = extract_meta(entry, self._publication_meta)
        external_id = external_id_for(entry)
        return SourceDoc(
            external_id=external_id,
            filename=filename_for(entry),
            # These files are staged into data/ar6/pdf/ by hand — half of them
            # took a login, a mirror or a browser to get at, and none of that
            # survives a re-fetch. url=None means "must already be there".
            url=None,
            # Each publication stands alone: a paper is not re-published the way
            # a heat plan is, so every one is its own version group.
            group_key=external_id,
            published=published_for(meta["year"]),
            meta=meta,
            payload={"scenario_ids": list(entry.get("scenario_ids") or [])},
        )

    def after_document(self, connection: sqlite3.Connection, doc: SourceDoc) -> None:
        document = store.document_id(doc.filename, connection)
        if document is None:
            return
        store.upsert_publication_meta(document, doc.meta, connection)
        for ar6_id in doc.payload["scenario_ids"]:
            scenario = store.upsert_scenario(
                ar6_id, self._scenario_names.get(ar6_id, str(ar6_id)), connection)
            store.link_scenario(document, scenario, connection)


# The source this profile contributes to `python -m scripts.fileprocessing`.
SOURCE = Ar6Source
