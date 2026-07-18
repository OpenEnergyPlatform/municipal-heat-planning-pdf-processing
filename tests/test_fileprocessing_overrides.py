"""Tests for process_entry: PDF overrides, ags coercion, KWW metadata, quality gate."""
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import pytest

from scripts.fileprocessing import pipeline, config, pdf_quality

GOOD_TEXT = ("Die kommunale Waermeplanung der Gemeinde beschreibt die Ziele bis 2045. "
             "Betrachtet werden Waermenetze, Grosswaermepumpen, Speicher und Sanierung.")
GARBLE = '!" # $%  &"% \' (%\'  )$* \'% \'%%+ % ,* \'  ++,, \' %-..%$  /-. \'  & ,  \' 0$ %+'


def _pdf(path: Path, pages: int, text: str | None = GOOD_TEXT, lines: int = 3) -> Path:
    """Build a real PDF: `text` repeated on every page, or image-less blank pages."""
    import fitz
    doc = fitz.open()
    for _ in range(pages):
        pg = doc.new_page()
        if text:
            for ln in range(lines):
                pg.insert_text((50, 100 + ln * 20), text, fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


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
    """Downloads write a real, text-bearing PDF; override targets exist on disk."""
    def _fake_download(url, d):
        fn = Path(urlparse(str(url).lower()).path).name.lower()
        _pdf(Path(d) / fn, 6)
        return fn
    monkeypatch.setattr(pipeline, "download_pdf", _fake_download)
    monkeypatch.setattr(pipeline, "get_num_pages", lambda fn, d: 10)
    for fn in set(config.PDF_OVERRIDES.values()):
        _pdf(tmp_path / fn, 6)
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
        pipeline.process_entry(
            _row(ags, "https://kww/broken.pdf", name=f"M{i}", ou="Selters VG"), con, no_network)
    docs = con.execute(
        "SELECT COUNT(*) FROM Documents WHERE filename='waermeplan_selters_20250711.pdf'"
    ).fetchone()[0]
    assert docs == 1
    assert con.execute("SELECT COUNT(*) FROM Municipalities").fetchone()[0] == len(selters)
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
    assert con.execute("SELECT landkreis FROM MunicipalityMeta WHERE ags=2222222").fetchall() == [("Neu",)]


def test_coerce_types():
    assert pipeline._coerce(float("nan"), "INTEGER") is None
    assert pipeline._coerce(96326.0, "INTEGER") == 96326
    assert pipeline._coerce("  x ", "TEXT") == "x"
    import pandas as pd
    assert pipeline._coerce(pd.Timestamp("2024-07-01"), "DATE") == "2024-07-01"
    assert pipeline._coerce(pd.NaT, "DATE") is None


# --- PDF quality gate --------------------------------------------------------

def test_gate_accepts_normal_german_text(tmp_path):
    ok, reason = pdf_quality.check(_pdf(tmp_path / "ok.pdf", 12))
    assert ok, reason


def test_gate_rejects_scan_without_text(tmp_path):
    ok, reason = pdf_quality.check(_pdf(tmp_path / "scan.pdf", 12, text=None))
    assert not ok and reason.startswith("NO_TEXT")


def test_gate_rejects_garbled_text(tmp_path):
    """Symbol soup: enough characters to judge, but no letters and no umlauts."""
    p = _pdf(tmp_path / "garbled.pdf", 40, text=GARBLE, lines=8)
    ok, reason = pdf_quality.check(p)
    assert not ok and reason.startswith("BROKEN_ENCODING"), reason


def test_gate_rejects_unreadable_file(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4 truncated garbage")
    ok, reason = pdf_quality.check(p)
    assert not ok and reason.startswith("UNREADABLE")


def test_gate_samples_across_the_document(tmp_path):
    """A text cover page must not mask a scanned body (pages are sampled evenly)."""
    import fitz
    doc = fitz.open()
    for i in range(60):
        pg = doc.new_page()
        if i < 2:                                  # only the first two pages carry text
            for ln in range(3):
                pg.insert_text((50, 100 + ln * 20), GOOD_TEXT, fontsize=9)
    p = tmp_path / "cover_only.pdf"
    doc.save(str(p)); doc.close()
    ok, reason = pdf_quality.check(p)
    assert not ok and reason.startswith("NO_TEXT"), reason


def test_process_entry_refuses_unusable_pdf(monkeypatch, tmp_path):
    """A scan raises UnusablePDF and leaves nothing in the DB."""
    con = _db()
    _pdf(tmp_path / "scan.pdf", 12, text=None)
    monkeypatch.setattr(pipeline, "download_pdf", lambda url, d: "scan.pdf")
    with pytest.raises(pipeline.UnusablePDF):
        pipeline.process_entry(_row(7654321, "https://kww/x/scan.pdf"), con, tmp_path)
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM Municipalities").fetchone()[0] == 0
