"""Tests for process_entry: PDF overrides + Gemeindeschlüssel coercion."""
import sqlite3
import types

import pytest

from scripts.fileprocessing import pipeline, config


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE OrganisationUnits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, state TEXT, UNIQUE(name, state)
        );
        CREATE TABLE Municipalities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, ags INTEGER NOT NULL UNIQUE,
            organisation_unit INTEGER NOT NULL,
            UNIQUE(name, ags, organisation_unit)
        );
        CREATE TABLE Documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organisation_unit INTEGER, filename TEXT NOT NULL UNIQUE,
            published TEXT, num_pages INTEGER, added TEXT,
            municipality_ags INTEGER, is_current INTEGER NOT NULL DEFAULT 1,
            supersedes INTEGER
        );
        """
    )
    return con


def _row(ags, link, name="Town", ou="OU", state="ST", published="2024-01-01"):
    # itertuples-like: attribute access, with the underscore-normalised names.
    return types.SimpleNamespace(
        Gemeindename=name, Gemeindeschlüssel=ags, Verbandsname=ou,
        Bundesland_lang=state, Link_Wärmeplan=link,
        Datum_der_Veröffentlichung=published,
    )


@pytest.fixture
def no_network(monkeypatch, tmp_path):
    """download → bare filename (no HTTP); page count fixed; override files present."""
    from urllib.parse import urlparse
    from pathlib import Path
    monkeypatch.setattr(pipeline, "download_pdf",
                        lambda url, d: Path(urlparse(str(url).lower()).path).name.lower())
    monkeypatch.setattr(pipeline, "get_num_pages", lambda fn, d: 10)
    for fn in set(config.PDF_OVERRIDES.values()):
        (tmp_path / fn).write_bytes(b"%PDF-1.4 stub")
    return tmp_path


def test_override_replaces_broken_link(no_network):
    con = _db()
    ags = next(iter(config.PDF_OVERRIDES))
    expected = config.PDF_OVERRIDES[ags]
    pipeline.process_entry(_row(ags, "https://kww/broken/original.pdf"), con, no_network)
    fn = con.execute("SELECT filename FROM Documents WHERE municipality_ags=?", (ags,)).fetchone()
    assert fn[0] == expected                       # local override, not the KWW link


def test_non_override_uses_kww_link(no_network):
    con = _db()
    pipeline.process_entry(_row(5555555, "https://kww/x/echterplan_2025.pdf"), con, no_network)
    fn = con.execute("SELECT filename FROM Documents WHERE municipality_ags=5555555").fetchone()
    assert fn[0] == "echterplan_2025.pdf"


def test_float_ags_stored_as_integer(no_network):
    """June's column is float64 (has NaN); ags must land as INTEGER, not REAL."""
    con = _db()
    pipeline.process_entry(_row(9999999.0, "https://kww/x/p.pdf"), con, no_network)
    assert con.execute("SELECT typeof(ags) FROM Municipalities").fetchone()[0] == "integer"
    assert con.execute(
        "SELECT typeof(municipality_ags) FROM Documents"
    ).fetchone()[0] == "integer"


def test_convoy_members_share_one_document(no_network):
    """Selters convoy: 9 member ags → one shared corrected PDF, one Document."""
    con = _db()
    selters = [a for a, f in config.PDF_OVERRIDES.items()
               if f == "waermeplan_selters_20250711.pdf"]
    assert len(selters) > 1
    for i, ags in enumerate(selters):
        pipeline.process_entry(_row(ags, "https://kww/broken.pdf", name=f"M{i}", ou="Selters VG"), con, no_network)
    docs = con.execute(
        "SELECT COUNT(*) FROM Documents WHERE filename='waermeplan_selters_20250711.pdf'"
    ).fetchone()[0]
    assert docs == 1                               # one plan
    assert con.execute("SELECT COUNT(*) FROM Municipalities").fetchone()[0] == len(selters)


def test_missing_override_file_raises(monkeypatch, tmp_path):
    """An override whose local file is absent is a hard error (never downloaded)."""
    monkeypatch.setattr(pipeline, "get_num_pages", lambda fn, d: 10)
    con = _db()
    ags = next(iter(config.PDF_OVERRIDES))
    with pytest.raises(FileNotFoundError):
        pipeline.process_entry(_row(ags, "https://kww/broken.pdf"), con, tmp_path)
