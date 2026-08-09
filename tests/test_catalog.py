"""The generic catalog: what the picker shows when the core knows nothing."""
import sqlite3

import pytest

from docpipe.inference import catalog
from docpipe.profile import Facet, Profile


@pytest.fixture
def conn(kwp_db):
    db_path, con = kwp_db
    con.executescript("""
        INSERT INTO Documents (id, filename, published, is_current)
             VALUES (2, 'alt.pdf', '2023q4', 0);
        UPDATE Documents SET published = '20240708' WHERE id = 1;
    """)
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def test_current_documents_only_unless_asked(conn):
    cat = catalog.Catalog()
    assert [e.id for e in cat.entries(conn)] == [1]
    assert sorted(e.id for e in cat.entries(conn, include_superseded=True)) == [1, 2]


def test_generic_label_is_the_filename_and_the_date(conn):
    (entry,) = catalog.Catalog().entries(conn)
    assert entry.label == "doc · 2024-07-08 · (aktuell)"


@pytest.mark.parametrize("stored,shown", [
    ("20240708", "2024-07-08"), ("2023q4", "2023 Q4"), ("2023Q4", "2023 Q4"),
    ("", ""), (None, ""), ("irgendwas", "irgendwas"),
])
def test_published_tokens_are_printed_readably(stored, shown):
    assert catalog.format_published(stored) == shown


def test_core_offers_no_facets_even_when_the_profile_declares_them(conn):
    cat = catalog.Catalog(Profile(name="x", facets=(Facet("gemeinde", "Gemeinde"),)))
    entries = cat.entries(conn)
    # declared, but nothing fills it → not offered, rather than offered empty
    assert catalog.facet_options(entries, cat.facets) == {}


# ---------------------------------------------------------------------------
# facet options + filtering (pure)
# ---------------------------------------------------------------------------
def _entry(id_, **facets):
    return catalog.Entry(id=id_, label=str(id_), facets={k: list(v) for k, v in facets.items()})


FACETS = (Facet("ort", "Ort"), Facet("jahr", "Jahr"))
ENTRIES = [
    _entry(1, ort=["Aachen", "Bonn"], jahr=["2024"]),
    _entry(2, ort=["Celle"], jahr=["2023"]),
    _entry(3, ort=["bremen"], jahr=["2025"]),
]


def test_options_are_years_newest_first_and_names_alphabetical():
    options = catalog.facet_options(ENTRIES, FACETS)
    assert options["jahr"] == ["2025", "2024", "2023"]
    assert options["ort"] == ["Aachen", "Bonn", "bremen", "Celle"]   # case-insensitive


def test_no_filter_keeps_everything():
    assert catalog.apply_filters(ENTRIES, {"ort": [], "jahr": []}) == ENTRIES
    assert catalog.apply_filters(ENTRIES, None) == ENTRIES


def test_within_one_facet_the_values_are_alternatives():
    got = catalog.apply_filters(ENTRIES, {"ort": ["Celle", "bremen"]})
    assert [e.id for e in got] == [2, 3]


def test_across_facets_the_filters_must_all_hold():
    assert catalog.apply_filters(ENTRIES, {"ort": ["Aachen"], "jahr": ["2023"]}) == []
    got = catalog.apply_filters(ENTRIES, {"ort": ["Aachen"], "jahr": ["2024"]})
    assert [e.id for e in got] == [1]


def test_a_document_covering_several_values_matches_any_of_them():
    """A convoy plan lists every municipality it covers, not just its lead."""
    assert [e.id for e in catalog.apply_filters(ENTRIES, {"ort": ["Bonn"]})] == [1]


def test_a_document_without_the_value_drops_out_of_an_active_filter():
    entries = ENTRIES + [_entry(4, jahr=["2024"])]          # no ort at all
    assert [e.id for e in catalog.apply_filters(entries, {"ort": ["Aachen"]})] == [1]


# ---------------------------------------------------------------------------
# which catalog a profile gets
# ---------------------------------------------------------------------------
def test_without_a_profile_the_generic_catalog_is_used():
    assert type(catalog.load_catalog(None)) is catalog.Catalog


def test_a_profile_without_a_catalog_module_gets_the_generic_one():
    cat = catalog.load_catalog(Profile(name="kwp_less", home="does/not/exist"))
    assert type(cat) is catalog.Catalog


def test_the_kwp_profile_brings_its_own():
    from docpipe.profile import load_profile
    from profiles.kwp.catalog import KwpCatalog
    assert isinstance(catalog.load_catalog(load_profile("kwp")), KwpCatalog)


def test_a_catalog_that_is_not_one_is_refused(monkeypatch):
    profile = Profile(name="x")
    monkeypatch.setattr(type(profile), "component", lambda self, m, a: "kein Katalog")
    with pytest.raises(TypeError):
        catalog.load_catalog(profile)
