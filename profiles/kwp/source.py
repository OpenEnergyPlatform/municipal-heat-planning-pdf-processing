"""
source.py – Where heat plans come from: the KWW "Status quo KWP" sheet.

One Excel row is one municipality. Several rows can point at the same PDF (a
convoy plan), so the document is registered once while every row still gets its
municipality and its metadata.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from docpipe.ingest.models import Source, SourceDoc

from . import store
from .config import EXCEL_SHEET, MUNICIPALITY_META_COLUMNS, PDF_OVERRIDES

log = logging.getLogger(__name__)


def load_and_filter_excel(excel_file: Path) -> pd.DataFrame:
    """
    Completed Wärmepläne ("Stand in der KWP" == "abgeschlossen") that have a PDF
    link. Original KWW column names are kept (rows are consumed as dicts).
    """
    kww_data = pd.read_excel(excel_file, sheet_name=EXCEL_SHEET)
    _warn_about_missing_columns(kww_data, excel_file)
    return kww_data[
        (kww_data["Stand in der KWP"] == "abgeschlossen") &
        (kww_data["Link Wärmeplan"].str.lower().str.contains(".pdf", na=False))
    ]


def _warn_about_missing_columns(frame, excel_file: Path) -> None:
    absent = missing_meta_columns(frame)
    if absent:
        log.warning(
            "%s carries %d of %d metadata columns; missing: %s. Their stored "
            "values are kept, not overwritten.",
            excel_file.name, len(MUNICIPALITY_META_COLUMNS) - len(absent),
            len(MUNICIPALITY_META_COLUMNS), ", ".join(absent),
        )


def coerce(value: Any, sqltype: str):
    """Excel cell → a SQLite-storable value (NaN/NaT → None) for the given type."""
    if pd.isna(value):
        return None
    if sqltype == "INTEGER":
        return int(value)
    if sqltype == "DATE":
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    return str(value).strip()


def extract_meta(row: dict) -> dict:
    """
    {db_column: coerced value} for the metadata columns of one Excel row.

    Columns the sheet does not carry are LEFT OUT rather than written as NULL.
    The KWW export drops and renames columns between releases — August 2026 came
    with 24 instead of 35 — and since the upsert writes every column it is
    handed, a missing one would quietly erase what an earlier export stored for
    every municipality in the register.
    """
    return {db: coerce(row[excel], sqltype)
            for excel, db, sqltype in MUNICIPALITY_META_COLUMNS
            if excel in row}


def missing_meta_columns(frame) -> list:
    """The metadata columns this export does not carry (their values are kept)."""
    return [excel for excel, _db, _t in MUNICIPALITY_META_COLUMNS
            if excel not in frame.columns]


class KwwSource(Source):
    """The KWW register as a document source."""

    def __init__(self, excel_file: Path):
        self.excel_file = Path(excel_file)
        self._rows = None

    def _load(self):
        if self._rows is None:
            self._rows = load_and_filter_excel(self.excel_file).to_dict("records")
        return self._rows

    def __len__(self):
        return len(self._load())

    def documents(self, connection: sqlite3.Connection):
        for row in self._load():
            yield self.document_for(row, connection)

    def document_for(self, row: dict, connection: sqlite3.Connection) -> SourceDoc:
        # Excel gives float when the column has any NaN
        ags = int(row["Gemeindeschlüssel"])
        state = row["Bundesland lang"]
        published = pd.Timestamp(row["Datum der Veröffentlichung"]).strftime("%Y%m%d")

        # A hand-sourced replacement for a broken KWW link (PDF_OVERRIDES) is a
        # local filename that must already be in the data dir — never downloaded.
        override = PDF_OVERRIDES.get(ags)
        link = override if override else str(row["Link Wärmeplan"]).strip()
        filename = Path(urlparse(link.lower()).path).name.lower()

        orga_id = store.update_organisation_unit(row["Verbandsname"], state, connection)
        return SourceDoc(
            external_id=filename,
            filename=filename,
            url=None if override else link,
            # re-published plans of one municipality are versions of each other
            group_key=str(ags),
            published=published,
            meta={"organisation_unit": orga_id, "municipality_ags": ags},
            payload={"row": row, "ags": ags, "orga_id": orga_id},
        )

    def after_document(self, connection: sqlite3.Connection, doc: SourceDoc) -> None:
        row, ags, orga_id = doc.payload["row"], doc.payload["ags"], doc.payload["orga_id"]
        store.add_municipality(row["Gemeindename"], ags, orga_id, connection)
        store.upsert_municipality_meta(ags, extract_meta(row), connection)


def backfill_meta(excel_file: Path, db_file: Path) -> int:
    """
    Backfill MunicipalityMeta for municipalities ALREADY in the DB, from
    `excel_file`, matched by ags. Additive and minimal-invasive: only writes
    MunicipalityMeta — no downloads, no changes to Documents/Sections/
    Embeddings. Returns the number of rows written.

    Reads the full sheet (unfiltered) so a municipality's metadata is found even
    if its own row would not pass the completed-plan import filter.
    """
    kww_data = pd.read_excel(excel_file, sheet_name=EXCEL_SHEET)
    _warn_about_missing_columns(kww_data, excel_file)
    with sqlite3.connect(db_file) as connection:
        store.ensure_municipality_meta_table(MUNICIPALITY_META_COLUMNS, connection)
        existing = {r[0] for r in connection.execute("SELECT ags FROM Municipalities")}
        written = 0
        for row in kww_data.to_dict("records"):
            ags = row.get("Gemeindeschlüssel")
            if pd.isna(ags) or int(ags) not in existing:
                continue
            store.upsert_municipality_meta(int(ags), extract_meta(row), connection)
            written += 1
        connection.commit()
    return written


# The source this profile contributes to `python -m scripts.fileprocessing`.
SOURCE = KwwSource
