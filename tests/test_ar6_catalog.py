"""The AR6 catalog: how a publication is labelled, filtered and described."""
import sqlite3

import pytest

from docpipe import store
from docpipe.inference import catalog as core
from docpipe.profile import load_profile
from profiles.ar6.catalog import Ar6Catalog


@pytest.fixture
def conn():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    store.apply(con, load_profile("ar6"))
    con.executescript("""
        INSERT INTO Documents (id, filename, external_id, group_key, published)
             VALUES (1, '10.1088_1748-9326_aab53e.pdf', '10.1088/1748-9326/aab53e',
                     '10.1088/1748-9326/aab53e', '20180101');
        INSERT INTO DocumentMeta (document, doi, title, year, venue, is_oa, scenario_count)
             VALUES (1, '10.1088/1748-9326/aab53e', 'Enhancing global climate policy ambition',
                     2018, 'Environmental Research Letters', 1, 2);
        INSERT INTO Scenarios (id, ar6_id, name)
             VALUES (1, 8, 'ADVANCE_2020_Med2C'), (2, 9, 'ADVANCE_2020_WB2C');
        INSERT INTO DocumentScenarios (document, scenario) VALUES (1, 1), (1, 2);
    """)
    con.commit()
    return con


@pytest.fixture
def cat():
    return core.load_catalog(load_profile("ar6"))


def _add(con, doc_id, filename, meta=None):
    con.execute("INSERT INTO Documents (id, filename, external_id) VALUES (?, ?, ?)",
                (doc_id, filename, filename))
    if meta is not None:
        con.execute("INSERT INTO DocumentMeta (document, doi, title, year) "
                    "VALUES (?, ?, ?, ?)", (doc_id, *meta))
    con.commit()


def test_the_ar6_profile_selects_this_catalog(cat):
    assert isinstance(cat, Ar6Catalog)
    assert cat.document_noun == "Publikation"


def test_entry_carries_label_and_facets(conn, cat):
    (entry,) = cat.entries(conn)
    assert entry.label == "Enhancing global climate policy ambition · 2018"
    assert entry.facets["year"] == ["2018"]
    assert entry.facets["venue"] == ["Environmental Research Letters"]
    assert entry.facets["scenario"] == ["ADVANCE_2020_Med2C", "ADVANCE_2020_WB2C"]


def test_the_declared_facets_are_all_offered(conn, cat):
    options = core.facet_options(cat.entries(conn), cat.facets)
    assert set(options) == {"year", "venue", "scenario"}


def test_a_publication_is_findable_under_every_scenario_it_documents(conn, cat):
    entries = cat.entries(conn)
    assert core.apply_filters(entries, {"scenario": ["ADVANCE_2020_WB2C"]})
    assert core.apply_filters(entries, {"scenario": ["EN_NPi2020_900"]}) == []


def test_the_detail_names_the_venue_and_the_scenario_count(conn, cat):
    (entry,) = cat.entries(conn)
    ((heading, lines),) = entry.detail
    assert "Publikation" in heading
    assert lines == ["Erschienen in: Environmental Research Letters",
                     "Dokumentierte AR6-Szenarien: 2"]


# --- what the corpus looks like before the metadata fetch caught up ----------

def test_the_label_falls_back_to_the_doi_when_the_title_is_unknown(conn, cat):
    _add(conn, 2, "10.1_b.pdf", meta=("10.1/b", None, None))
    labels = {e.id: e.label for e in cat.entries(conn)}
    assert labels[2] == "10.1/b"


def test_the_label_falls_back_to_the_slug_when_there_is_no_doi_either(conn, cat):
    """An agency report imported before publication_meta.json existed: no title,
    no DOI, and the crawl slug is all that is left."""
    _add(conn, 3, "https_www.iea.org_reports_etp-2020.pdf")
    labels = {e.id: e.label for e in cat.entries(conn)}
    assert labels[3] == "https_www.iea.org_reports_etp-2020"


def test_a_corpus_without_publication_metadata_still_offers_its_scenarios(conn, cat):
    conn.execute("UPDATE DocumentMeta SET title = NULL, year = NULL, venue = NULL")
    conn.commit()
    options = core.facet_options(cat.entries(conn), cat.facets)
    assert set(options) == {"scenario"}     # empty facets are not offered at all
    (entry,) = cat.entries(conn)
    assert entry.label == "10.1088/1748-9326/aab53e"
