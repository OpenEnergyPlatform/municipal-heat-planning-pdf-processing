"""The KWW source: PDF overrides, ags coercion, metadata, and the quality gate."""
# `str | None` in a signature is evaluated at import time before 3.10, and
# this file is collected by whatever python the developer has. The run itself
# is 3.11, which is exactly why nobody noticed: the file could not be
# collected at all on 3.9 and took the whole suite down with it.
from __future__ import annotations

import conftest

conftest.needs_real("fitz")

import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import pytest

from docpipe import store
from docpipe.profile import load_profile
from docpipe.ingest import pdf_quality
from docpipe.ingest import pipeline as ingest
from profiles.kwp import config, source as kwp

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
    """Core schema plus the kwp profile — the same tables the pipeline creates."""
    con = sqlite3.connect(":memory:")
    store.apply(con, load_profile("kwp"))
    return con


def _process(row, con, data_dir):
    """One Excel row through the source and the core's register step."""
    src = kwp.KwwSource(Path("unused.xlsx"))
    doc = src.document_for(row, con)
    ingest.register(doc, con, Path(data_dir))
    src.after_document(con, doc)


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
    monkeypatch.setattr(ingest, "download_pdf", _fake_download)
    monkeypatch.setattr(ingest, "get_num_pages", lambda fn, d: 10)
    for fn in set(config.PDF_OVERRIDES.values()):
        _pdf(tmp_path / fn, 6)
    return tmp_path


# --- PDF overrides -----------------------------------------------------------

def test_override_replaces_broken_link(no_network):
    con = _db()
    ags = next(iter(config.PDF_OVERRIDES))
    expected = config.PDF_OVERRIDES[ags]
    _process(_row(ags, "https://kww/broken/original.pdf"), con, no_network)
    fn = con.execute("SELECT d.filename FROM Documents d JOIN DocumentMeta m ON m.document = d.id "
                      "WHERE m.municipality_ags = ?", (ags,)).fetchone()
    assert fn[0] == expected


def test_non_override_uses_kww_link(no_network):
    con = _db()
    _process(_row(5555555, "https://kww/x/echterplan_2025.pdf"), con, no_network)
    fn = con.execute("SELECT d.filename FROM Documents d JOIN DocumentMeta m ON m.document = d.id "
                      "WHERE m.municipality_ags = 5555555").fetchone()
    assert fn[0] == "echterplan_2025.pdf"


def test_missing_override_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "get_num_pages", lambda fn, d: 10)
    con = _db()
    ags = next(iter(config.PDF_OVERRIDES))
    with pytest.raises(FileNotFoundError):
        _process(_row(ags, "https://kww/broken.pdf"), con, tmp_path)


# --- ags coercion ------------------------------------------------------------

def test_float_ags_stored_as_integer(no_network):
    """June's column is float64 (has NaN); ags must land as INTEGER, not REAL."""
    con = _db()
    _process(_row(9999999.0, "https://kww/x/p.pdf"), con, no_network)
    assert con.execute("SELECT typeof(ags) FROM Municipalities").fetchone()[0] == "integer"
    assert con.execute("SELECT typeof(municipality_ags) FROM DocumentMeta").fetchone()[0] == "integer"
    assert con.execute("SELECT typeof(ags) FROM MunicipalityMeta").fetchone()[0] == "integer"


def test_convoy_members_share_one_document(no_network):
    con = _db()
    selters = [a for a, f in config.PDF_OVERRIDES.items()
               if f == "waermeplan_selters_20250711.pdf"]
    assert len(selters) > 1
    for i, ags in enumerate(selters):
        _process(
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
    _process(
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
    _process(_row(2222222, "https://kww/x/p.pdf", **{"Landkreis": "Alt"}), con, no_network)
    _process(_row(2222222, "https://kww/x/p.pdf", **{"Landkreis": "Neu"}), con, no_network)
    assert con.execute("SELECT landkreis FROM MunicipalityMeta WHERE ags=2222222").fetchall() == [("Neu",)]


def test_coerce_types():
    assert kwp.coerce(float("nan"), "INTEGER") is None
    assert kwp.coerce(96326.0, "INTEGER") == 96326
    assert kwp.coerce("  x ", "TEXT") == "x"
    import pandas as pd
    assert kwp.coerce(pd.Timestamp("2024-07-01"), "DATE") == "2024-07-01"
    assert kwp.coerce(pd.NaT, "DATE") is None


# --- PDF quality gate --------------------------------------------------------

def test_gate_accepts_normal_german_text(tmp_path):
    ok, reason = pdf_quality.check(_pdf(tmp_path / "ok.pdf", 12))
    assert ok, reason


def test_gate_rejects_scan_without_text(tmp_path):
    ok, reason = pdf_quality.check(_pdf(tmp_path / "scan.pdf", 12, text=None))
    assert not ok and reason.startswith("NO_TEXT")


def test_gate_rejects_garbled_text(tmp_path):
    """Symbol soup on every page: enough characters to judge, and no letters."""
    p = _pdf(tmp_path / "garbled.pdf", 40, text=GARBLE, lines=8)
    ok, reason = pdf_quality.check(p)
    assert not ok and reason.startswith("BROKEN_ENCODING"), reason


ENGLISH_TEXT = ("The scenario reaches net-zero emissions by 2050 across all sectors. "
                "Final energy demand falls while electrification of heat accelerates.")
NUMBERS = "2018 2019 2020 | 1.2 3.4 -0.8 | 12.5 % 7.1 % 0.3 % | 1 204 3 517 8 012 |"


def test_a_statistical_annex_is_not_a_broken_glyph_map(tmp_path):
    """An outlook that is mostly tables reads as symbol soup in aggregate: the
    even sample lands in the annex and the letter ratio drops below the bar.
    A broken glyph map is broken on every page, so one page of ordinary prose
    acquits the document — this cost the AR6 corpus a readable 318-page report
    while the rule still said "and no umlauts", which only ever acquitted German.
    """
    import fitz
    doc = fitz.open()
    for i in range(60):
        page = doc.new_page()
        text = ENGLISH_TEXT if i % 12 == 0 else NUMBERS
        for ln in range(8):
            page.insert_text((50, 100 + ln * 20), text, fontsize=9)
    p = tmp_path / "outlook.pdf"
    doc.save(str(p)); doc.close()

    ok, reason = pdf_quality.check(p)

    assert ok, reason


def test_english_prose_passes_without_an_umlaut_in_sight(tmp_path):
    ok, reason = pdf_quality.check(_pdf(tmp_path / "paper.pdf", 12, text=ENGLISH_TEXT))
    assert ok, reason


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


def test_refuses_unusable_pdf(monkeypatch, tmp_path):
    """Garbled text raises UnusablePDF and leaves nothing in the DB."""
    con = _db()
    _pdf(tmp_path / "garbled.pdf", 40, text=GARBLE, lines=8)
    monkeypatch.setattr(ingest, "download_pdf", lambda url, d: "garbled.pdf")
    with pytest.raises(ingest.UnusablePDF):
        _process(_row(7654321, "https://kww/x/garbled.pdf"), con, tmp_path)
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM Municipalities").fetchone()[0] == 0


def test_a_scan_reaches_the_register_and_its_municipality_with_it(monkeypatch,
                                                                  tmp_path):
    """Grevesmühlen and Kronshagen: complete plans, no text layer, refused at
    the door. The municipality lost its plan AND its register row with it."""
    con = _db()
    _pdf(tmp_path / "scan.pdf", 12, text=None)
    monkeypatch.setattr(ingest, "download_pdf", lambda url, d: "scan.pdf")

    _process(_row(7654321, "https://kww/x/scan.pdf"), con, tmp_path)

    assert con.execute("SELECT filename FROM Documents").fetchall() ==         [("scan.pdf",)]
    assert con.execute("SELECT ags FROM Municipalities").fetchall() == [(7654321,)]


# ---------------------------------------------------------------------------
# the KWW export changes shape between releases
# ---------------------------------------------------------------------------
def test_a_column_the_export_dropped_is_not_written_as_null():
    """August 2026 shipped 24 columns instead of 35. Since the upsert writes
    every column it is handed, writing None would erase what an earlier export
    stored for every municipality in the register."""
    from profiles.kwp.source import extract_meta

    row = {"Bundesland lang": "Bayern", "Landkreis": "Kelheim"}   # the rest is gone
    meta = extract_meta(row)
    assert meta == {"bundesland_lang": "Bayern", "landkreis": "Kelheim"}
    assert "dienstleister" not in meta


def test_a_column_that_is_present_but_empty_still_clears_the_value():
    """Absent and empty are different: an empty cell is a real 'no value'."""
    import numpy as np

    from profiles.kwp.source import extract_meta

    assert extract_meta({"Landkreis": np.nan}) == {"landkreis": None}


def test_missing_columns_are_reported():
    import pandas as pd

    from profiles.kwp.source import missing_meta_columns

    frame = pd.DataFrame(columns=["Bundesland lang", "Landkreis"])
    absent = missing_meta_columns(frame)
    assert "Dienstleister" in absent
    assert "Landkreis" not in absent


def test_the_renamed_aktualitaet_column_is_read_as_a_date():
    import pandas as pd

    from profiles.kwp.source import extract_meta

    meta = extract_meta({"Aktualität": pd.Timestamp("2025-06-19")})
    assert meta == {"aktualitaet": "2025-06-19"}


# ---------------------------------------------------------------------------
# Convoy version grouping
# ---------------------------------------------------------------------------
def test_a_convoy_is_grouped_by_its_smallest_ags():
    from profiles.kwp.source import group_keys_by_filename

    rows = [_row(5555103, "https://k/Konvoi_VG.pdf"),
            _row(5555018, "https://k/Konvoi_VG.pdf"),
            _row(5555054, "https://k/Konvoi_VG.pdf")]
    assert group_keys_by_filename(rows) == {"konvoi_vg.pdf": "5555018"}


def test_the_row_order_does_not_decide_the_group():
    """The whole point: KWW may reorder the sheet between exports. If the key
    followed the first row, next year's edition would land in another group and
    both editions would stay current side by side."""
    from profiles.kwp.source import group_keys_by_filename

    rows = [_row(5555103, "https://k/A.pdf"), _row(5555018, "https://k/A.pdf")]
    assert group_keys_by_filename(rows) == group_keys_by_filename(rows[::-1])


def test_a_single_municipality_keeps_its_own_ags():
    from profiles.kwp.source import group_keys_by_filename

    assert group_keys_by_filename([_row(8325049, "https://k/Rottweil.pdf")]) \
        == {"rottweil.pdf": "8325049"}


def test_a_new_edition_of_a_convoy_shares_the_group_of_the_old_one():
    from profiles.kwp.source import group_keys_by_filename

    members = [5555103, 5555018, 5555054]
    old = group_keys_by_filename([_row(a, "https://k/Plan_2025.pdf") for a in members])
    new = group_keys_by_filename([_row(a, "https://k/Plan_2026.pdf") for a in members[::-1]])
    assert set(old.values()) == set(new.values()) == {"5555018"}


def test_the_override_filename_decides_the_grouping():
    """A hand-sourced replacement changes the file name, so the group has to be
    computed from the name the document is actually stored under."""
    from profiles.kwp.config import PDF_OVERRIDES
    from profiles.kwp.source import group_keys_by_filename

    ags = sorted(a for a, f in PDF_OVERRIDES.items()
                 if list(PDF_OVERRIDES.values()).count(f) > 1)[:2]
    rows = [_row(a, "https://kww/irrelevant_%d.pdf" % a) for a in ags]
    keys = group_keys_by_filename(rows)
    assert len(keys) == 1, "both rows must resolve to the one override file"
    assert list(keys.values()) == [str(min(ags))]


def test_two_municipalities_on_one_file_without_a_convoy_are_reported(caplog):
    """KWW has pasted one town's link into another town's row more than once.
    That is a register error, and it must not disappear into the grouping."""
    from profiles.kwp.source import group_keys_by_filename

    rows = [_row(4444007, "https://k/Oldenburg.pdf", name="Ort A"),
            _row(5555000, "https://k/Oldenburg.pdf", name="Ort B")]
    for r in rows:
        r["Konvoi ID"] = float("nan")

    with caplog.at_level("WARNING"):
        keys = group_keys_by_filename(rows)

    assert keys == {"oldenburg.pdf": "4444007"}
    assert "no convoy between them" in caplog.text
    assert "Ort A" in caplog.text


def test_a_real_convoy_is_not_reported(caplog):
    from profiles.kwp.source import group_keys_by_filename

    rows = [_row(5555018, "https://k/K.pdf"), _row(5555103, "https://k/K.pdf")]
    for r in rows:
        r["Konvoi ID"] = "RLP VG Musterhausen"

    with caplog.at_level("WARNING"):
        group_keys_by_filename(rows)
    assert "no convoy" not in caplog.text


def test_the_three_pasted_links_are_resolved_by_their_own_plans():
    """KWW gave Bühl Greding's link, Hessisch Oldendorf Oldenburg's and
    Weingarten (Baden) the Württemberg Weingarten's. Each now has its own file,
    so nobody is left holding another town's plan."""
    from profiles.kwp.config import PDF_OVERRIDES, SHARED_FILE_OWNERS
    from profiles.kwp.source import group_keys_by_filename

    wrong_link = {8216007: "https://k/Waermeplan_Greding_20251016.pdf",
                  3252007: "https://k/Waermeplan_Oldenburg_20251112.pdf",
                  8215090: "https://k/Waermeplan_Weingarten_20231113.pdf"}
    owners = {9576122: "waermeplan_greding_20251016.pdf",
              3403000: "waermeplan_oldenburg_20251112.pdf",
              8436082: "waermeplan_weingarten_20231113.pdf"}

    rows = [_row(a, link) for a, link in wrong_link.items()]
    rows += [_row(a, "https://k/" + fn) for a, fn in owners.items()]
    keys = group_keys_by_filename(rows)

    for ags in wrong_link:
        assert PDF_OVERRIDES[ags] in keys, "the victim has its own file"
        assert keys[PDF_OVERRIDES[ags]] == str(ags)
    for ags, fn in owners.items():
        assert keys[fn] == str(ags), "and the real owner keeps its plan"
    # the pin stays as a guard: it names the owner if the paste ever returns
    assert set(owners) <= set(SHARED_FILE_OWNERS.values())


def test_a_victim_without_a_plan_of_its_own_is_still_named(caplog):
    """These three each got their own file in the end. Hofstetten (Oberbayern)
    did not: its KWW row points at the Kinzigtal report and no plan of its own
    exists, so the entry is all that keeps the coverage honest. The convoy
    marking on the OTHER row is why nothing warned about it."""
    from profiles.kwp.config import SHARED_FILE_OWNERS
    from profiles.kwp.source import group_keys_by_filename

    shared = "waermeplan_hofstetten_20251101.pdf"
    assert SHARED_FILE_OWNERS[shared] == 8317046

    baden = _row(8317046, "https://k/Waermeplan_Hofstetten_20260401.pdf")
    baden["Konvoi ID"] = "BW Haslach im Kinzigtal"
    oberbayern = _row(9181124, "https://k/" + shared)
    oberbayern["Konvoi ID"] = float("nan")

    with caplog.at_level("WARNING"):
        keys = group_keys_by_filename([baden, oberbayern])
    # The override puts Baden on the shared file, so the owner rule decides it.
    assert keys[shared] == "8317046"
    assert "no convoy between them" not in caplog.text, (
        "one member's convoy id silences the warning for the whole file — the "
        "reason this pairing went unnoticed")
