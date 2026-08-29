"""The AR6 source: what identifies a publication, and how its scenarios are linked."""
import json
import sqlite3

import pytest

from docpipe import store
from docpipe.ingest import pipeline as ingest
from docpipe.profile import load_profile
from profiles.scenarios import source as ar6


def _entry(slug, **kw):
    """One pdf_index.json entry: a fetched PDF for a publication without a DOI."""
    entry = {"slug": slug, "doi": None, "kind": "url", "status": "pdf",
             "path": f"pdfs/{slug}.pdf", "is_oa": None, "scenario_ids": []}
    entry.update(kw)
    return entry


def _paper(doi, **kw):
    return _entry(doi.replace("/", "_"), doi=doi, kind="doi", **kw)


def _crawl(tmp_path, entries, scenarios=(), publication_meta=None):
    """A crawl directory around `entries`. publication_meta.json is written only
    when asked: the OpenAlex fetch runs on its own schedule."""
    (tmp_path / "pdf_index.json").write_text(json.dumps(entries), encoding="utf-8")
    (tmp_path / "ar6_scenarios.json").write_text(
        json.dumps([{"id": i, "name": n} for i, n in scenarios]), encoding="utf-8")
    if publication_meta is not None:
        (tmp_path / "publication_meta.json").write_text(
            json.dumps(publication_meta), encoding="utf-8")
    return ar6.Ar6Source(tmp_path / "pdf_index.json")


def _db():
    """Core schema plus the ar6 profile — the same tables the pipeline creates."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    store.apply(con, load_profile("scenarios"))
    return con


def _register(con, doc):
    """The Documents row the core writes once the PDF has passed its gate — and,
    like the core, nothing at all for a document that is already there."""
    con.execute(
        "INSERT INTO Documents (filename, external_id, group_key, published) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(filename) DO NOTHING",
        (doc.filename, doc.external_id, doc.group_key, doc.published))


def _import(src, con):
    """A whole run: register every document, then let the source write its rows."""
    for doc in src.documents(con):
        _register(con, doc)
        src.after_document(con, doc)


# --- identity ----------------------------------------------------------------

def test_a_doi_identifies_a_publication(tmp_path):
    src = _crawl(tmp_path, [_paper("10.1088/1748-9326/aab53e")])
    (doc,) = src.documents(_db())
    assert doc.external_id == "10.1088/1748-9326/aab53e"
    assert doc.filename == "10.1088_1748-9326_aab53e.pdf"


def test_an_entry_without_a_doi_falls_back_to_its_slug(tmp_path):
    """Agency reports and national roadmaps have no DOI; the crawl slug is the
    only stable name they have."""
    src = _crawl(tmp_path, [_entry("https_www.iea.org_reports_etp-2020")])
    (doc,) = src.documents(_db())
    assert doc.external_id == "https_www.iea.org_reports_etp-2020"
    assert doc.filename == "https_www.iea.org_reports_etp-2020.pdf"


def test_every_publication_is_its_own_version_group(tmp_path):
    """Unlike a re-published heat plan, a paper has no successor."""
    src = _crawl(tmp_path, [_paper("10.1/a"), _paper("10.1/b")])
    keys = [doc.group_key for doc in src.documents(_db())]
    assert keys == ["10.1/a", "10.1/b"]


# --- what is not in the corpus ----------------------------------------------

@pytest.mark.parametrize("status", ["closed", "kein_dokument"])
def test_an_entry_without_a_local_pdf_is_skipped(tmp_path, status):
    src = _crawl(tmp_path, [_paper("10.1/have"),
                            _entry("nothing", status=status, path=None)])
    assert len(src) == 1
    assert [d.external_id for d in src.documents(_db())] == ["10.1/have"]


def test_the_skipped_entries_are_counted_once_not_named_one_by_one(tmp_path, caplog):
    src = _crawl(tmp_path, [_paper("10.1/have")]
                 + [_entry(f"gone{i}", status="closed", path=None) for i in range(5)])
    with caplog.at_level("INFO"):
        list(src.documents(_db()))
    lines = [r for r in caplog.records if "no local PDF" in r.getMessage()]
    assert len(lines) == 1
    assert "5 of 6" in lines[0].getMessage()


def test_a_pdf_that_was_not_staged_is_never_downloaded(tmp_path, monkeypatch):
    """These files came out of logins, mirrors and a browser; a re-fetch would
    get an HTML landing page. The missing file has to be reported, not fetched."""
    def _no(*args, **kwargs):
        raise AssertionError("the AR6 profile must never download")
    monkeypatch.setattr(ingest, "download_pdf", _no)
    src = _crawl(tmp_path, [_paper("10.1/missing")])
    con = _db()
    (doc,) = src.documents(con)
    assert doc.url is None
    with pytest.raises(FileNotFoundError):
        ingest.register(doc, con, tmp_path / "empty")


# --- publication metadata ----------------------------------------------------

def test_openalex_metadata_becomes_the_document_meta(tmp_path):
    src = _crawl(
        tmp_path, [_paper("10.1/a", scenario_ids=[1, 2])],
        publication_meta={"10.1_a": {"title": "Enhancing ambition", "year": 2018,
                                     "venue": "Environmental Research Letters",
                                     "is_oa": True, "authors": []}})
    (doc,) = src.documents(_db())
    assert doc.meta == {"doi": "10.1/a", "title": "Enhancing ambition", "year": 2018,
                        "venue": "Environmental Research Letters", "is_oa": 1,
                        "scenario_count": 2}
    assert doc.published == "20180101"


def test_without_the_openalex_file_the_fields_are_simply_unknown(tmp_path):
    """publication_meta.json is fetched separately and may not exist yet."""
    src = _crawl(tmp_path, [_paper("10.1/a", is_oa=True)])
    (doc,) = src.documents(_db())
    assert doc.meta["title"] is None
    assert doc.meta["year"] is None and doc.meta["venue"] is None
    assert doc.meta["is_oa"] == 1          # this one the index itself knows
    assert doc.published is None


def test_a_title_the_index_resolved_itself_is_kept(tmp_path):
    """About half the entries carry a title from the crawl's own resolution
    step, and for the ones OpenAlex cannot match it is the only one there is."""
    src = _crawl(tmp_path, [_entry("gfei-working-paper-20", title="Prospects for fuel efficiency")],
                 publication_meta={"gfei-working-paper-20": {"title": None, "year": None}})
    (doc,) = src.documents(_db())
    assert doc.meta["title"] == "Prospects for fuel efficiency"


# --- scenarios ---------------------------------------------------------------

def test_a_publication_with_many_scenarios_is_counted_and_linked(tmp_path):
    ids = list(range(1, 147))
    src = _crawl(tmp_path, [_paper("10.1038/s41558-021-01215-2", scenario_ids=ids)],
                 scenarios=[(i, f"SSP_{i}") for i in ids])
    con = _db()
    _import(src, con)
    assert con.execute("SELECT scenario_count FROM DocumentMeta").fetchone()[0] == 146
    assert con.execute("SELECT COUNT(*) FROM DocumentScenarios").fetchone()[0] == 146
    assert con.execute("SELECT COUNT(*) FROM Scenarios").fetchone()[0] == 146


def test_one_scenario_documented_by_two_publications_stays_one_row(tmp_path):
    src = _crawl(tmp_path, [_paper("10.1/a", scenario_ids=[8]),
                            _paper("10.1/b", scenario_ids=[8, 9])],
                 scenarios=[(8, "ADVANCE_2020_Med2C"), (9, "ADVANCE_2020_WB2C")])
    con = _db()
    _import(src, con)
    assert con.execute("SELECT COUNT(*) FROM Scenarios").fetchone()[0] == 2
    assert con.execute(
        "SELECT COUNT(*) FROM DocumentScenarios ds JOIN Scenarios s ON s.id = ds.scenario "
        "WHERE s.ar6_id = 8").fetchone()[0] == 2


def test_a_scenario_the_list_does_not_name_is_still_linked(tmp_path):
    src = _crawl(tmp_path, [_paper("10.1/a", scenario_ids=[4711])])
    con = _db()
    _import(src, con)
    assert con.execute("SELECT name FROM Scenarios").fetchone()[0] == "4711"


# --- re-runs -----------------------------------------------------------------

def test_a_second_import_refreshes_instead_of_duplicating(tmp_path):
    """The pipeline calls after_document again for a document it already has,
    so the links must not pile up and the UNIQUE on ar6_id must not trip."""
    src = _crawl(tmp_path, [_paper("10.1/a", scenario_ids=[8, 9])],
                 scenarios=[(8, "ADVANCE_2020_Med2C"), (9, "ADVANCE_2020_WB2C")])
    con = _db()
    _import(src, con)
    for doc in src.documents(con):          # the file is registered by now
        src.after_document(con, doc)

    assert con.execute("SELECT COUNT(*) FROM DocumentScenarios").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM Scenarios").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 1


def test_metadata_that_arrives_later_reaches_an_imported_corpus(tmp_path):
    """The corpus is imported before OpenAlex answered; the second run has to
    fill the title in, because the core skips the document itself."""
    con = _db()
    _import(_crawl(tmp_path, [_paper("10.1/a")]), con)
    assert con.execute("SELECT title FROM DocumentMeta").fetchone()[0] is None

    later = _crawl(tmp_path, [_paper("10.1/a")],
                   publication_meta={"10.1_a": {"title": "Late arrival", "year": 2021,
                                                "venue": "Nature Climate Change",
                                                "is_oa": False}})
    for doc in later.documents(con):
        later.after_document(con, doc)
    title, year, is_oa = con.execute(
        "SELECT title, year, is_oa FROM DocumentMeta").fetchone()
    assert (title, year, is_oa) == ("Late arrival", 2021, 0)


def test_a_renamed_scenario_is_updated_not_duplicated(tmp_path):
    src = _crawl(tmp_path, [_paper("10.1/a", scenario_ids=[8])], scenarios=[(8, "Alt")])
    con = _db()
    _import(src, con)
    _import(_crawl(tmp_path, [_paper("10.1/a", scenario_ids=[8])],
                   scenarios=[(8, "Neu")]), con)
    assert [tuple(r) for r in con.execute("SELECT ar6_id, name FROM Scenarios")] \
        == [(8, "Neu")]


# --- the progress bar --------------------------------------------------------

def test_the_source_knows_how_long_it_is(tmp_path):
    src = _crawl(tmp_path, [_paper("10.1/a"), _paper("10.1/b"),
                            _entry("x", status="closed", path=None)])
    assert len(src) == 2
