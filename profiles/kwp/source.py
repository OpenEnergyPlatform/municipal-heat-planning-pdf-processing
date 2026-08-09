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
from .config import (
    EXCEL_SHEET,
    MUNICIPALITY_META_COLUMNS,
    PDF_OVERRIDES,
    SHARED_FILE_OWNERS,
)

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


def _warn_about_missing_columns(frame, excel_file) -> None:
    absent = missing_meta_columns(frame)
    if absent:
        log.warning(
            "%s carries %d of %d metadata columns; missing: %s. Their stored "
            "values are kept, not overwritten.",
            Path(excel_file).name, len(MUNICIPALITY_META_COLUMNS) - len(absent),
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


def filename_for(row: dict) -> str:
    """The local file name a register row resolves to (override or KWW link)."""
    ags = int(row["Gemeindeschlüssel"])
    override = PDF_OVERRIDES.get(ags)
    link = override if override else str(row["Link Wärmeplan"]).strip()
    return Path(urlparse(link.lower()).path).name.lower()


def group_keys_by_filename(rows: list) -> dict:
    """
    {filename: group_key} with the group key being the SMALLEST ags among the
    municipalities that share the file.

    A convoy plan is one document for many municipalities, and the group key is
    what makes a re-published plan a new version of the old one rather than a
    second current document. Taking the ags of whichever row happened to come
    first would tie that to KWW's row order: reorder the sheet and next year's
    edition lands in a different group, so both editions stay "current" side by
    side. The smallest ags of the group is a property of the group itself.

    Where the sharing is a register error rather than a convoy, SHARED_FILE_OWNERS
    names the municipality the document really belongs to — read off the document.
    The smallest ags would pick the wrong one there; it did in all three known
    cases.
    """
    members: dict = {}
    for row in rows:
        members.setdefault(filename_for(row), []).append(row)
    _warn_about_shared_files(members)
    return {name: str(SHARED_FILE_OWNERS.get(
                name, min(int(r["Gemeindeschlüssel"]) for r in rs)))
            for name, rs in members.items()}


def _warn_about_shared_files(members: dict) -> None:
    """
    Several municipalities on one file are normal — that is what a convoy is.
    Several municipalities on one file with NO convoy marking between them is a
    register error: KWW pasted one town's link into another town's row, and the
    corpus then hands one municipality the other's plan.
    """
    for name, rows in sorted(members.items()):
        if len(rows) < 2:
            continue
        ids = {str(r.get("Konvoi ID")) for r in rows} - {"nan", "None", ""}
        if ids:
            continue
        log.warning(
            "%s is shared by %d municipalities with no convoy between them "
            "(%s) — one of them is pointing at the other's plan.",
            name, len(rows),
            ", ".join("%s %s" % (int(r["Gemeindeschlüssel"]), r["Gemeindename"])
                      for r in rows),
        )


class KwwSource(Source):
    """The KWW register as a document source."""

    def __init__(self, excel_file: Path):
        self.excel_file = Path(excel_file)
        self._rows = None
        self._group_keys: dict = {}

    def _load(self):
        if self._rows is None:
            self._rows = load_and_filter_excel(self.excel_file).to_dict("records")
            self._group_keys = group_keys_by_filename(self._rows)
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
        filename = filename_for(row)

        orga_id = store.update_organisation_unit(row["Verbandsname"], state, connection)
        return SourceDoc(
            external_id=filename,
            filename=filename,
            url=None if override else link,
            # Re-published plans are versions of each other. For a convoy the key
            # is the group's smallest ags, not this row's (group_keys_by_filename).
            # The map comes from the whole sheet, which documents() has loaded;
            # a single row on its own can only speak for itself.
            group_key=self._group_keys.get(filename, str(ags)),
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
