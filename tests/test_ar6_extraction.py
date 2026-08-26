"""The ar6 extraction stage: spec, prompts and the OEKG serializer.

What is asserted here is what the OEKG shapes demand and what the licence
argument demands. The shapes are sh:closed, so a triple they do not name
invalidates the node; and every value must be able to point at the passage it
was read in, which is why nothing here is taken from DocumentMeta.
"""
import logging
from pathlib import Path

import pytest

from docpipe.extraction.spec import load

SPEC_PATH = Path("profiles/ar6/extraction_spec.json")


@pytest.fixture(scope="module")
def spec():
    return load(SPEC_PATH)


def _rows(**overrides):
    base = {
        "publication_title": ["Global Energy and Climate Outlook 2023"],
        "publication_author": ["Keramidas, K.", "Fosse, F."],
        "publication_date": ["2023"],
        "publication_doi": ["10.2760/58255"],
        "publication_abstract": ["This report presents the results."],
        "study_organisation": ["Joint Research Centre"],
        "study_funder": ["Horizon 2020"],
        "study_project_name": ["Enabling Ambitious Climate Policy Assessment"],
        "study_acronym": ["ENGAGE"],
    }
    base.update(overrides)
    return [{"parameter": k, "value": v, "quote": "x", "provenance": {}}
            for k, values in base.items() for v in values]


def _ttl(rows, name="geco_2023"):
    from profiles.ar6 import kg
    return kg.make_serializer(Path("no-such.db"))(name, rows)


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------

def test_every_field_is_text_because_none_of_them_is_a_measurement(spec):
    """The shapes ask for a title, an author, a DOI. None of those has a unit,
    and calling them numbers would have meant inventing one."""
    assert [p.value_type for p in spec.parameters] == ["text"] * 9
    assert all(not p.units_accepted and p.unit_target is None
               for p in spec.parameters)


def test_a_metadata_field_carries_no_axes(spec):
    """A title does not vary along carrier, sector or year. The core used to
    demand a non-empty axes object from every parameter."""
    assert all(p.axes == {} for p in spec.parameters)


def test_the_spec_covers_exactly_the_fields_the_shapes_ask_of_us(spec):
    # Scenario-scope fields are deliberately absent: see the spec's _comment
    # and the open questions. They need a value to belong to a scenario.
    assert {p.uri for p in spec.parameters} == {
        "publication_title", "publication_author", "publication_date",
        "publication_doi", "publication_abstract", "study_organisation",
        "study_funder", "study_project_name", "study_acronym"}


def test_every_example_would_survive_its_own_verifier(spec):
    """The example is the prompt's few-shot. If its own value is not in its own
    quote, the prompt teaches exactly the mistake the verifier refuses."""
    from docpipe.extraction.verify import verify_tuple, Refusal

    for parameter in spec.parameters:
        source = parameter.example["source"]
        for claim in parameter.example["tuples"]:
            outcome = verify_tuple(dict(claim), parameter, source,
                                   owner_kind="section")
            assert not isinstance(outcome, Refusal), \
                f"{parameter.uri}: {getattr(outcome, 'reason', '')}"


def test_the_probes_expand_without_a_vocabulary_axis(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "ar6")
    from docpipe import prompts
    from docpipe.extraction.queries import expand

    text = prompts.load("extraction/queries").text
    templates = [l for l in text.splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
    probes = expand(templates, load(SPEC_PATH).parameters[0])
    assert probes and all("{" not in p for p in probes)


# ---------------------------------------------------------------------------
# The serializer
# ---------------------------------------------------------------------------

def test_the_graph_carries_both_nodes_the_shapes_target():
    ttl = _ttl(_rows())
    assert "a oeo:OEO_00020012 ;" in ttl        # study report
    assert "a oeo:OEO_00020227 ;" in ttl        # scenario bundle
    assert "obo:BFO_0000051 <" in ttl           # bundle has part report


def test_nothing_the_closed_shapes_do_not_name_is_emitted():
    """sh:closed true. The quote, its page and its rectangles are evidence and
    stay in the JSONL — a provenance triple here would invalidate the node."""
    ttl = _ttl(_rows())
    allowed = {"a", "rdfs:label", "dc:acronym", "dc:abstract",
               "oeo:OEO_00390095", "oeo:OEO_00000506", "oeo:OEO_00390096",
               "oeo:OEO_00390098", "oeo:OEO_00000510", "oeo:OEO_00000509",
               "obo:BFO_0000051"}
    # Predicates sit at four spaces; a further object of the same predicate
    # is continued at eight and is not a predicate line.
    used = {line.split()[0] for line in ttl.splitlines()
            if line.startswith("    ") and not line.startswith("        ")
            and line.strip()}
    assert used <= allowed, used - allowed


def test_two_spellings_of_one_author_become_one_node():
    ttl = _ttl(_rows(publication_author=["Keramidas, K.", "keramidas, k.",
                                         "Fosse, F."]))
    assert ttl.count("a oeo:OEO_00000064 ;") == 2


def test_the_iri_is_a_pure_function_of_the_name():
    """Two runs over one document must mint byte-identical IRIs, or every
    re-run doubles the graph."""
    assert _ttl(_rows()) == _ttl(_rows())


def test_the_reading_the_most_sources_agree_on_wins():
    """maxCount 1 is a property of the whole harvest, so it cannot be settled
    by the verifier, which sees one claim at a time."""
    rows = _rows(publication_title=["Der volle Titel", "Der volle Titel",
                                    "Der volle"])
    ttl = _ttl(rows)
    assert 'rdfs:label "Der volle Titel" ;' in ttl
    assert '"Der volle" ;' not in ttl


def test_a_document_without_a_title_is_skipped_not_half_emitted():
    rows = [r for r in _rows() if r["parameter"] != "publication_title"]
    assert _ttl(rows) is None


def test_a_missing_required_field_is_named_in_the_log(caplog):
    rows = [r for r in _rows() if r["parameter"] != "publication_author"]
    with caplog.at_level(logging.INFO, logger="profiles.ar6.kg"):
        _ttl(rows)
    assert "MISSING REQUIRED" in caplog.text
    assert "publication_author" in caplog.text


def test_a_multiline_abstract_stays_valid_turtle():
    ttl = _ttl(_rows(publication_abstract=['Er sagte "ja"\nund ging.']))
    assert 'dc:abstract """Er sagte \\"ja\\"\nund ging."""' in ttl


def test_the_year_becomes_a_datetime_and_says_so_where_it_guessed():
    from profiles.ar6 import kg
    assert kg._publication_date("2023") == "2023-01-01T00:00:00"
    assert kg._publication_date("ohne Jahr") == ""


def test_the_crawl_is_the_cross_check_not_the_source(tmp_path, caplog):
    """DocumentMeta must never supply a value — it comes with the crawl's
    licence. A disagreement is worth a line, not a substitution."""
    import sqlite3
    from profiles.ar6 import kg

    db = tmp_path / "ar6.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE DocumentMeta (document INTEGER, title TEXT, year INTEGER,"
        " doi TEXT);"
        "INSERT INTO Documents VALUES (1, 'geco_2023.pdf');"
        "INSERT INTO DocumentMeta VALUES (1, 'Ein ganz anderer Titel', 2023,"
        " '10.2760/58255');")
    conn.commit()
    conn.close()

    with caplog.at_level(logging.WARNING, logger="profiles.ar6.kg"):
        ttl = kg.make_serializer(db)("geco_2023", _rows())
    assert "Ein ganz anderer Titel" in caplog.text, "the disagreement is logged"
    assert "Ein ganz anderer Titel" not in ttl, "and never enters the graph"
    assert 'rdfs:label "Global Energy and Climate Outlook 2023" ;' in ttl
