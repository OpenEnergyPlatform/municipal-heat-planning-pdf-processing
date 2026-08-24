"""The KWP catalog: which municipalities a plan covers, and how it is labelled."""
import sqlite3

import pytest

from docpipe.inference import catalog as core
from docpipe.profile import load_profile
from profiles.kwp.catalog import (
    KwpCatalog, _covered_names, _konvoi_lead, document_label, municipality_coverage,
)


@pytest.fixture
def conn(kwp_db):
    db_path, con = kwp_db
    con.executescript("""
        INSERT INTO OrganisationUnits (id, name, state) VALUES (1, 'Landkreis X', 'BW');
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (1, 'Musterstadt', 12345, 1);
        UPDATE Documents SET published = '20240101', is_current = 1,
            group_key = '12345' WHERE id = 1;
        INSERT INTO DocumentMeta (document, organisation_unit, municipality_ags)
            VALUES (1, 1, 12345);
        INSERT INTO MunicipalityMeta (ags, bundesland_lang, jahr_veroeffentlichung)
            VALUES (12345, 'Baden-Württemberg', 2024);
    """)
    con.commit()
    con.row_factory = sqlite3.Row
    return con


@pytest.fixture
def cat():
    return core.load_catalog(load_profile("kwp"))


def test_the_kwp_profile_selects_this_catalog(cat):
    assert isinstance(cat, KwpCatalog)
    assert cat.document_noun == "Wärmeplan"


def test_entry_carries_label_and_facets(conn, cat):
    (entry,) = cat.entries(conn)
    assert "Musterstadt" in entry.label and "(aktuell)" in entry.label
    assert entry.facets["gemeinde"] == ["Musterstadt"]     # single-doc OU → its member
    assert entry.facets["bundesland_lang"] == ["Baden-Württemberg"]
    assert entry.facets["jahr"] == ["2024"]                # from Documents.published


def test_the_declared_facets_are_all_offered(conn, cat):
    options = core.facet_options(cat.entries(conn), cat.facets)
    assert set(options) == {"gemeinde", "bundesland_lang", "jahr"}


def test_filtering_by_bundesland_uses_the_kww_metadata(conn, cat):
    entries = cat.entries(conn)
    assert core.apply_filters(entries, {"bundesland_lang": ["Baden-Württemberg"]})
    assert core.apply_filters(entries, {"bundesland_lang": ["Sachsen"]}) == []


def test_a_corpus_without_kww_metadata_simply_offers_no_bundesland(conn, cat):
    conn.execute("DELETE FROM MunicipalityMeta")
    conn.commit()
    options = core.facet_options(cat.entries(conn), cat.facets)
    assert "bundesland_lang" not in options
    assert "gemeinde" in options


def test_a_convoy_lists_its_members_as_detail(conn, cat):
    conn.executescript("""
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (2, 'Nachbardorf', 12346, 1);
        UPDATE Documents SET filename = 'waermeplan_konvoi_musterstadt_20240101.pdf'
            WHERE id = 1;
    """)
    conn.commit()
    (entry,) = cat.entries(conn)
    assert entry.facets["gemeinde"] == ["Musterstadt", "Nachbardorf"]
    ((heading, lines),) = entry.detail
    assert "2" in heading and lines == ["Musterstadt", "Nachbardorf"]
    # and the plan is findable under EITHER municipality
    assert core.apply_filters([entry], {"gemeinde": ["Nachbardorf"]})


def _doc_row(**kw):
    base = {"municipality_name": "Gemmrigheim", "organisation_unit_name": None,
            "published": "20260401", "is_current": 1,
            "filename": "waermeplan_konvoi_hessigheim_20260401.pdf"}
    base.update(kw)
    return base


def test_konvoi_lead_parsing():
    assert _konvoi_lead("waermeplan_konvoi_hessigheim_20260401.pdf") == "Hessigheim"
    assert _konvoi_lead("waermeplan_denzlingen_konvoi_2024q2.pdf") == "Denzlingen"
    assert _konvoi_lead("waermeplan__asperg_et_al_konvoi_2024q2.pdf") == "Asperg Et Al"
    assert _konvoi_lead("waermeplan_by6_konvoi_250327.pdf") == "By6"


def test_document_label_convoy_uses_ou_and_count():
    # a convoy covering 4 municipalities is labelled by its unit + count + Konvoi,
    # NOT by one arbitrary member up front.
    label = document_label(
        _doc_row(organisation_unit_name="GVV Besigheim"),
        covered=["Gemmrigheim", "Hessigheim", "Mundelsheim", "Walheim"],
    )
    assert "GVV Besigheim" in label
    assert "4 Gemeinden" in label
    assert "Konvoi" in label
    assert not label.startswith("Gemmrigheim")


def test_document_label_single_municipality_has_no_convoy_tag():
    label = document_label(
        _doc_row(filename="waermeplan_flensburg_20240701.pdf",
                 municipality_name="Flensburg"),
        covered=["Flensburg"],
    )
    assert "Konvoi" not in label
    assert "Flensburg" in label


# ---------------------------------------------------------------------------
# the coverage rule (pure)
# ---------------------------------------------------------------------------
def test_covered_names_single_doc_ou_covers_all_members():
    members = {1: "A", 2: "B", 3: "C"}
    assert _covered_names(1, "A", True, 1, {1}, members) == ["A", "B", "C"]


def test_covered_names_standalone_in_multidoc_ou_covers_only_self():
    members = {1: "A", 2: "B"}
    assert _covered_names(1, "A", False, 2, {1, 2}, members) == ["A"]


def test_covered_names_konvoi_mops_up_unclaimed_members():
    members = {10: "Besigheim", 11: "Gemmrigheim", 12: "Hessigheim",
               13: "Mundelsheim", 14: "Walheim"}
    # OU has 2 plans: Besigheim's own (ags 10) + this convoy (own ags 11).
    got = _covered_names(11, "Gemmrigheim", True, 2, {10, 11}, members)
    assert got == ["Gemmrigheim", "Hessigheim", "Mundelsheim", "Walheim"]
    assert "Besigheim" not in got          # kept by its own standalone plan


def test_coverage_is_computed_over_the_documents_shown(conn):
    docs = KwpCatalog().rows(conn)
    assert municipality_coverage(conn, docs)[1] == ["Musterstadt"]


# ---------------------------------------------------------------------------
# coverage from the register, which is where it actually lives
# ---------------------------------------------------------------------------
def test_the_register_decides_who_a_convoy_covers(conn):
    """The KWW export has one row per municipality carrying that
    municipality's plan link. Several rows on one link is the convoy, and the
    members need not share an organisation unit - deriving membership from
    the unit instead loses exactly those."""
    conn.executescript("""
        UPDATE Documents SET filename = 'waermeplan_konvoi_x_20240101.pdf'
            WHERE id = 1;
        UPDATE MunicipalityMeta SET link_waermeplan =
            'https://kww.de/waermeplan_konvoi_X_20240101.pdf' WHERE ags = 12345;
        INSERT INTO OrganisationUnits (id, name, state) VALUES (2, 'Kreis Y', 'BW');
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (2, 'Nachbardorf', 12346, 2);
        INSERT INTO MunicipalityMeta (ags, link_waermeplan)
            VALUES (12346, 'https://kww.de/waermeplan_konvoi_x_20240101.pdf');
    """)
    conn.commit()
    docs = KwpCatalog().rows(conn)
    assert municipality_coverage(conn, docs)[1] == ["Musterstadt", "Nachbardorf"]


def test_a_hand_sourced_pdf_is_matched_by_its_override_name(conn):
    """Where the KWW link is dead we substitute a file by hand. Coverage has
    to follow the same substitution, or those plans lose their members."""
    from profiles.kwp.config import PDF_OVERRIDES
    ags, filename = next(iter(PDF_OVERRIDES.items()))
    conn.executescript(f"""
        UPDATE Documents SET filename = '{filename}' WHERE id = 1;
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (3, 'Ersatzstadt', {ags}, 1);
        INSERT INTO MunicipalityMeta (ags, link_waermeplan)
            VALUES ({ags}, 'https://kww.de/tot.pdf');
    """)
    conn.commit()
    docs = KwpCatalog().rows(conn)
    assert municipality_coverage(conn, docs)[1] == ["Ersatzstadt"]


def test_without_register_links_the_unit_rule_still_answers(conn):
    """A corpus imported without the KWW metadata still has to fill the
    picker, so the old derivation stays as the fallback."""
    conn.execute("UPDATE MunicipalityMeta SET link_waermeplan = NULL")
    conn.commit()
    docs = KwpCatalog().rows(conn)
    assert municipality_coverage(conn, docs)[1] == ["Musterstadt"]


def test_a_pasted_link_does_not_hand_a_plan_to_another_municipality(conn):
    """Two rows on one file is a convoy only when the file really covers both.
    KWW also pastes one town's link into another town's row: the register then
    said a Kinzigtal report covers Hofstetten in Oberbayern, 600 km away and
    not named in it once. SHARED_FILE_OWNERS settles those, and coverage has to
    read it or the picker repeats the claim."""
    from profiles.kwp.config import SHARED_FILE_OWNERS

    filename, owner = next(iter(SHARED_FILE_OWNERS.items()))
    conn.executescript(f"""
        UPDATE Documents SET filename = '{filename}' WHERE id = 1;
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (4, 'Eigentuemerin', {owner}, 1);
        INSERT INTO MunicipalityMeta (ags, link_waermeplan)
            VALUES ({owner}, 'https://kww.de/{filename}');
        INSERT INTO Municipalities (id, name, ags, organisation_unit)
            VALUES (5, 'Fremde Gemeinde', 9999999, 1);
        INSERT INTO MunicipalityMeta (ags, link_waermeplan)
            VALUES (9999999, 'https://kww.de/{filename}');
    """)
    conn.commit()
    docs = KwpCatalog().rows(conn)
    assert municipality_coverage(conn, docs)[1] == ["Eigentuemerin"]
