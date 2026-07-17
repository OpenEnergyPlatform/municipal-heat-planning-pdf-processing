"""Tests for process_entry: PDF overrides, ags coercion, and KWW metadata."""
import sqlite3
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
    pipeline.database.ensure_municipality_meta_table(config.MUNICIPALITY_META_COLUMNS, con)
    return con


def _row(ags, link, name="Town", ou="OU", state="ST", published="2024-01-01", **meta):
    """A KWW row as a dict, keyed by the original Excel column names."""
    row = {
        "Gemeindename": name, "Gemeindeschlüssel": ags, "Verbandsname": ou,
        "Bundesland lang": state, "Link Wärmeplan": link,
        "Datum der Veröffentlichung": published,
    }
    row.update(meta)
    return row


@pytest.fixture
def no_network(monkeypatch, tmp_path):
    from urllib.parse import urlparse
    from pathlib import Path
    monkeypatch.setattr(pipeline, "download_pdf",
                        lambda url, d: Path(urlparse(str(url).lower()).path).name.lower())
    monkeypatch.setattr(pipeline, "get_num_pages", lambda fn, d: 10)
    for fn in set(config.PDF_OVERRIDES.values()):
        (tmp_path / fn).write_bytes(b"%PDF-1.4 stub")
    return tmp_path


# --- PDF overrides -----------------------------------------------------------

def test_override_replaces_broken_link(no_network):
    con = _db()
    ags = next(iter(config.PDF_OVERRIDES))
    expected = config.PDF_OVERRIDES[ags]
    pipeline.process_entry(_row(ags, "https://kww/broken/original.pdf"), con, no_network)
    fn = con.execute("SELECT filename FROM Documents WHERE municipality_ags=?", (ags,)).fetchone()
    assert fn[0] == expected


def test_non_override_uses_kww_link(no_network):
    con = _db()
    pipeline.process_entry(_row(5555555, "https://kww/x/echterplan_2025.pdf"), con, no_network)
    fn = con.execute("SELECT filename FROM Documents WHERE municipality_ags=5555555").fetchone()
    assert fn[0] == "echterplan_2025.pdf"


def test_missing_override_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "get_num_pages", lambda fn, d: 10)
    con = _db()
    ags = next(iter(config.PDF_OVERRIDES))
    with pytest.raises(FileNotFoundError):
        pipeline.process_entry(_row(ags, "https://kww/broken.pdf"), con, tmp_path)


# --- ags coercion ------------------------------------------------------------

def test_float_ags_stored_as_integer(no_network):
    """June's column is float64 (has NaN); ags must land as INTEGER, not REAL."""
    con = _db()
    pipeline.process_entry(_row(9999999.0, "https://kww/x/p.pdf"), con, no_network)
    assert con.execute("SELECT typeof(ags) FROM Municipalities").fetchone()[0] == "integer"
    assert con.execute("SELECT typeof(municipality_ags) FROM Documents").fetchone()[0] == "integer"
    assert con.execute("SELECT typeof(ags) FROM MunicipalityMeta").fetchone()[0] == "integer"


def test_convoy_members_share_one_document(no_network):
    con = _db()
    selters = [a for a, f in config.PDF_OVERRIDES.items()
               if f == "waermeplan_selters_20250711.pdf"]
    assert len(selters) > 1
    for i, ags in enumerate(selters):
        pipeline.process_entry(_row(ags, "https://kww/broken.pdf", name=f"M{i}", ou="Selters VG"), con, no_network)
    docs = con.execute(
        "SELECT COUNT(*) FROM Documents WHERE filename='waermeplan_selters_20250711.pdf'"
    ).fetchone()[0]
    assert docs == 1
    assert con.execute("SELECT COUNT(*) FROM Municipalities").fetchone()[0] == len(selters)
    # every convoy member still gets its own metadata row
    assert con.execute("SELECT COUNT(*) FROM MunicipalityMeta").fetchone()[0] == len(selters)


# --- KWW metadata ------------------------------------------------------------

def test_metadata_written_for_each_municipality(no_network):
    con = _db()
    pipeline.process_entry(
        _row(1234567, "https://kww/x/p.pdf",
             **{"Landkreis": "Kreis Test", "Einwohnendenzahl nach GVZ": 4321.0,
                "Verbandstyp": "verbandsfreie Gemeinde"}),
        con, no_network,
    )
    landkreis, einwohner, vtyp, typ = con.execute(
        "SELECT landkreis, einwohnendenzahl_gvz, verbandstyp, typeof(einwohnendenzahl_gvz) "
        "FROM MunicipalityMeta WHERE ags=1234567"
    ).fetchone()
    assert landkreis == "Kreis Test"
    assert einwohner == 4321                # float from Excel → INTEGER, lossless
    assert typ == "integer"
    assert vtyp == "verbandsfreie Gemeinde"


def test_metadata_upsert_refreshes_on_rerun(no_network):
    con = _db()
    pipeline.process_entry(_row(2222222, "https://kww/x/p.pdf", **{"Landkreis": "Alt"}), con, no_network)
    pipeline.process_entry(_row(2222222, "https://kww/x/p.pdf", **{"Landkreis": "Neu"}), con, no_network)
    rows = con.execute("SELECT landkreis FROM MunicipalityMeta WHERE ags=2222222").fetchall()
    assert rows == [("Neu",)]              # one row, latest value


def test_coerce_types():
    assert pipeline._coerce(float("nan"), "INTEGER") is None
    assert pipeline._coerce(96326.0, "INTEGER") == 96326
    assert pipeline._coerce("  x ", "TEXT") == "x"
    import pandas as pd
    assert pipeline._coerce(pd.Timestamp("2024-07-01"), "DATE") == "2024-07-01"
    assert pipeline._coerce(pd.NaT, "DATE") is None
