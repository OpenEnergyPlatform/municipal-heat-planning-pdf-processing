"""The scenarios extraction stage: spec, prompts and the OEKG serializer.

What is asserted here is what the OEKG shapes demand and what the licence
argument demands. The shapes are sh:closed, so a triple they do not name
invalidates the node; and every value must be able to point at the passage it
was read in, which is why nothing here is taken from DocumentMeta.
"""
import json
import logging
import re
from pathlib import Path

import pytest

from docpipe.extraction.spec import load

SPEC_PATH = Path("profiles/scenarios/extraction_spec.json")
ROWS_PROMPT = Path("profiles/scenarios/prompts/extraction/rows.md")


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


def _ttl(rows, name="geco_2023", known=None):
    from profiles.scenarios import kg
    if known is None:
        return kg.make_serializer(Path("no-such.db"))(name, rows)
    import unittest.mock
    with unittest.mock.patch.object(kg, "_known_scenarios",
                                    lambda conn, n: known):
        with unittest.mock.patch("sqlite3.connect"):
            return kg.make_serializer(Path("no-such.db"))(name, rows)


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------

def test_no_field_is_a_measurement(spec):
    """The shapes ask for a title, an author, a DOI. None of those has a unit,
    and calling them numbers would have meant inventing one."""
    assert {p.value_type for p in spec.parameters} == {"text", "category"}
    assert all(not p.units_accepted and p.unit_target is None
               for p in spec.parameters)


def test_a_field_with_a_finite_answer_set_is_a_choice_not_a_wording(spec):
    """Three fields have a list of correct answers, so the model picks from it
    instead of writing one. Two of the lists are only closed once a document is
    named, which is what vocabulary_dynamic marks."""
    by_uri = {p.uri: p for p in spec.parameters}
    assert by_uri["scenario_label"].vocabulary_dynamic
    assert by_uri["scenario_region"].vocabulary_dynamic
    # The scenario types are the same 17 classes for the whole corpus, so that
    # list sits in the spec and is checked against the shapes below.
    assert by_uri["scenario_type"].vocabulary
    assert not by_uri["scenario_type"].vocabulary_dynamic


def test_a_document_field_carries_no_axes_and_a_scenario_field_carries_one(spec):
    """A title does not vary along anything — the core used to demand a
    non-empty axes object from every parameter. A scenario's region does vary:
    along which scenario it belongs to."""
    by_uri = {p.uri: p for p in spec.parameters}
    assert by_uri["publication_title"].axes == {}
    for key in ("scenario_type", "scenario_abstract", "scenario_region",
                "scenario_year"):
        axis = by_uri[key].axes["scenario"]
        assert axis.dynamic, key
        # Not required: the AR6 names are run identifiers and the documents
        # write prose, so refusing what the model cannot map would delete the
        # one measurement that says how far apart the two vocabularies are.
        assert not axis.required, key


def test_the_spec_covers_exactly_the_fields_the_shapes_ask_of_us(spec):
    assert {p.uri for p in spec.parameters} == {
        "publication_title", "publication_author", "publication_date",
        "publication_doi", "publication_abstract", "study_organisation",
        "study_funder", "study_project_name", "study_acronym",
        "scenario_label", "scenario_type", "scenario_abstract",
        "scenario_region", "scenario_year"}


def test_the_scenario_types_are_the_ones_the_shapes_accept(spec):
    """`has scenario type` is sh:in with 17 classes in
    oekg_shapes_commentsMS_20260817.ttl. A class outside that list makes the
    node invalid, so the list is copied, not summarised."""
    by_uri = {p.uri: p for p in spec.parameters}
    shapes = {
        "OEO_00000364", "OEO_00020247", "OEO_00020248", "OEO_00020309",
        "OEO_00020310", "OEO_00020311", "OEO_00020312", "OEO_00020314",
        "OEO_00020317", "OEO_00020321", "OEO_00020345", "OEO_00020411",
        "OEO_00020412", "OEO_00030007", "OEO_00030008", "OEO_00030009",
        "OEO_00030010"}
    from profiles.scenarios import kg

    vocabulary = by_uri["scenario_type"].vocabulary
    assert {u.rsplit("/", 1)[-1] for u in vocabulary
            if kg.in_graph(u)} == shapes
    # and the entries that are not classes say so in their key, which is the
    # one thing that keeps them out of the graph
    assert [u for u in vocabulary if not kg.in_graph(u)] == ["out:not_in_list"]


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


def test_every_example_in_the_rows_prompt_holds_its_own_quote():
    """The few-shots are what the model imitates, and this path shows it no
    others: the quantities payload of a document plan carries label and
    description and no example at all. So an example whose value is not in its
    own quote teaches the mistake the verifier refuses, and a set of examples
    that only ever shows a name teaches that a whole line is not wanted. The
    second is what happened: 54 of 164 publications were shown their own title
    page and named everything on it except the title."""
    from docpipe.extraction.verify import flat

    text = ROWS_PROMPT.read_text(encoding="utf-8")
    claims = [claim for line in text.splitlines()
              if line.strip().startswith('{"tuples"')
              for claim in json.loads(line.strip())["tuples"]]
    assert claims, "the prompt shows no example any more"
    for claim in claims:
        # A choice answer is exempt from the value rule and not from this one:
        # "value_raw" is what the document writes, so it stands in the quote.
        shown = claim.get("value_raw") or claim["value"]
        assert flat(shown) in flat(claim["quote"]), claim
    assert max(len(claim["value"]) for claim in claims) > 30,         "no example shows a value longer than a name, and a title is a line"


def test_the_rows_prompt_calls_the_front_page_what_it_is():
    """Three sentences carry the fix, and each one answers a measured reason
    the title stayed unnamed: the heading is quotable at all, the front page
    is exempt from "an empty list is the normal case", and it is not one of
    the citations rule 4 forbids."""
    text = ROWS_PROMPT.read_text(encoding="utf-8")
    for satz in ("steht am Anfang ihres \"text\" und ist zitierbar",
                 "Eine Quelle ist davon ausgenommen: die Vorderseite",
                 "Die Vorderseite ist keine solche Stelle"):
        assert satz in text, satz
    # And the counterweight. "The heading IS the title" is a licence, and the
    # three shapes it must not be given for are the ones the corpus really
    # holds: ten of the titleless documents carry their author list as the
    # heading of section 1, and seven carry a genus word.
    assert "Der Titel ist die Zeile ÜBER den Namen" in text
    for gegenprobe in ("Quellenverzeichnis", "schon die Autorenliste ist",
                       "Gattungswort"):
        assert gegenprobe in text, gegenprobe


def test_the_rows_prompt_may_answer_as_long_as_the_batch_was_sized_for():
    """How many sources a request reads and how much may be written about them
    are set in two files, and the run mixes them: fit_batch_sources sizes the
    batch from extraction/harvest's ceiling (runner.py hardwires
    HARVEST_PROMPT_ID) while the field-wise path answers under
    extraction/rows. A lower ceiling here means the batch is deliberately
    sized for a reply the prompt forbids -- 43 replies were cut off at it in
    the corpus run of 2026-08-31."""
    import re as regex

    def ceiling(path):
        head = Path(path).read_text(encoding="utf-8").split("---")[1]
        return int(regex.search(r"max_tokens:\s*(\d+)", head).group(1))

    assert ceiling(ROWS_PROMPT) >= ceiling(
        "profiles/scenarios/prompts/extraction/harvest.md")


def test_the_probes_expand_without_a_vocabulary_axis(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
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


def _promised():
    """Every predicate the spec's kg blocks promise, qualified.

    Read out of the spec rather than typed here, because typing it here is
    what made the graph vocabulary exist in three places at once: the module
    constants, the f-strings that had no constant, and this list. A list that
    is maintained by hand beside the thing it checks agrees with it by
    accident.
    """
    import profiles.scenarios.kg as kg
    out = set()
    for parameter in kg._SPEC["parameters"]:
        block = parameter.get("kg") or {}
        for key in ("property", "also", "edge_from"):
            if block.get(key):
                out.add(kg._name(block[key]))
        for axis in (parameter.get("axes") or {}).values():
            link = ((axis.get("kg") or {}).get("linked_by"))
            if link:
                out.add(kg._name(link))
    return out


# Behind no harvested value, so promised by no parameter: rdf:type and the
# uuid every OEKG node carries. Named, so that "the spec did not promise it"
# stays a finding and does not quietly grow a third member.
STRUCTURAL = {"a", "oeo:OEO_00390095"}


def _predicates_in(ttl):
    """Predicates sit at four spaces; a further object of the same predicate
    is continued at eight and is not a predicate line. A comment carries the
    passage and is not a triple at all — that is the point of writing the
    evidence as one when the shapes are closed."""
    return {line.split()[0] for line in ttl.splitlines()
            if line.startswith("    ") and not line.startswith("        ")
            and line.strip() and not line.lstrip().startswith("#")}


def test_nothing_the_closed_shapes_do_not_name_is_emitted(monkeypatch):
    """With OEKG_EVIDENCE=0 the graph is exactly what the closed shapes allow.
    That switch exists because whether they stay closed is still being decided
    — see the module docstring."""
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", False)
    allowed = _promised() | STRUCTURAL
    assert len(allowed) == 14, sorted(allowed)
    used = _predicates_in(_ttl(_rows()))
    assert used <= allowed, used - allowed


def test_every_predicate_the_spec_promises_is_one_the_serializer_writes(
        monkeypatch):
    """The direction the drift actually runs. A `kg` block is a promise to a
    reader of the published schema, and a promise nobody keeps is worse than
    silence: the block would describe a graph that is not being written, and
    the JSON schema publishes it as `x-kg`.

    Needs a row for every parameter, so the two that `_scenario_rows` leaves
    without a resolvable target are given one here: a region and a type are
    only serialized when the model picked an entry off the list, which is what
    `value_uri` records.
    """
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", False)
    where = {"page": 9, "owner_kind": "section", "owner_id": 9}
    rows = _scenario_rows() + [
        {"parameter": "scenario_region", "value": "Germany",
         "value_uri": "https://openenergyplatform.org/ontology/oekg/region/Germany",
         "scenario": "CurPol", "tier": "text_located",
         "quote": "CurPol also covers Germany", "provenance": where},
        {"parameter": "scenario_type", "value": "with existing measures",
         "value_uri": "https://openenergyplatform.org/ontology/oeo/OEO_00020311",
         "scenario": "CurPol", "tier": "text_located",
         "quote": "CurPol is a with existing measures scenario",
         "provenance": where},
    ]
    written = _predicates_in(_ttl(rows))
    assert _promised() - written == set(), _promised() - written
    assert written - (_promised() | STRUCTURAL) == set()


def test_a_closed_shape_run_still_says_where_every_value_was_read(monkeypatch):
    """Switching the evidence off used to mean the graph forgot the passage,
    which gives up the reason the metadata is read from the PDF at all."""
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", False)
    rows = [dict(r, quote="Keramidas, K., Fosse, F., Diaz Vazquez, A.",
                 tier="text_located", provenance={"page": 3,
                                                  "owner_kind": "section"})
            for r in _rows()]
    ttl = _ttl(rows)
    assert "# “Keramidas, K., Fosse, F., Diaz Vazquez, A.”" in ttl
    assert "# geco_2023.pdf, p. 3, section, text_located" in ttl
    body = ttl.split("@prefix")[-1].split(chr(10), 1)[1]
    assert "oekgprov:" not in body, "no evidence triple, only the comment"


def test_a_quote_with_a_line_break_cannot_break_the_comment(monkeypatch):
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", False)
    rows = [dict(r, quote="a title\nsplit over\ntwo lines",
                 provenance={})
            for r in _rows()]
    ttl = _ttl(rows)
    for line in ttl.splitlines():
        assert not (line.strip() and line.lstrip().startswith("split over"))
    assert "# “a title split over two lines”" in ttl


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
    with caplog.at_level(logging.INFO, logger="profiles.scenarios.kg"):
        _ttl(rows)
    assert "MISSING REQUIRED" in caplog.text
    assert "publication_author" in caplog.text


def test_a_multiline_abstract_stays_valid_turtle():
    ttl = _ttl(_rows(publication_abstract=['Er sagte "ja"\nund ging.']))
    assert 'dc:abstract """Er sagte \\"ja\\"\nund ging."""' in ttl


def test_the_year_becomes_a_datetime_and_says_so_where_it_guessed():
    from profiles.scenarios import kg
    assert kg._publication_date("2023") == "2023-01-01T00:00:00"
    assert kg._publication_date("ohne Jahr") == ""


def test_the_crawl_is_the_cross_check_not_the_source(tmp_path, caplog):
    """DocumentMeta must never supply a value — it comes with the crawl's
    licence. A disagreement is worth a line, not a substitution."""
    import sqlite3
    from profiles.scenarios import kg

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

    with caplog.at_level(logging.WARNING, logger="profiles.scenarios.kg"):
        ttl = kg.make_serializer(db)("geco_2023", _rows())
    assert "Ein ganz anderer Titel" in caplog.text, "the disagreement is logged"
    assert "Ein ganz anderer Titel" not in ttl, "and never enters the graph"
    assert 'rdfs:label "Global Energy and Climate Outlook 2023" ;' in ttl


# ---------------------------------------------------------------------------
# Scenario scope and evidence
# ---------------------------------------------------------------------------

def _scenario_rows():
    return _rows() + [
        {"parameter": "scenario_label", "value": "CurPol",
         "quote": "the Current Policies scenario (CurPol)", "tier": "text_located",
         "provenance": {"page": 9, "owner_kind": "section", "owner_id": 9}},
        {"parameter": "scenario_region", "value": "EU27", "scenario": "CurPol",
         "quote": "CurPol covers the EU27", "tier": "text_located",
         "provenance": {"page": 9, "owner_kind": "section", "owner_id": 9}},
        {"parameter": "scenario_year", "value": "2050", "scenario": "CurPol",
         "quote": "CurPol results for 2050", "tier": "text_located",
         "provenance": {"page": 9, "owner_kind": "section", "owner_id": 9}},
        {"parameter": "scenario_abstract",
         "value": "assumes no additional policies", "scenario": "CurPol",
         "quote": "CurPol assumes no additional policies", "tier": "text_located",
         "provenance": {"page": 9, "owner_kind": "section", "owner_id": 9}},
    ]


def test_a_scenario_becomes_its_own_factsheet_hung_off_the_bundle():
    ttl = _ttl(_scenario_rows())
    assert "a oeo:OEO_00000365 ;" in ttl                    # scenario factsheet
    assert ttl.count("obo:BFO_0000051 <") == 2, "the report and the scenario"
    assert 'rdfs:label "CurPol" ;' in ttl
    assert 'dc:acronym "CurPol" ;' in ttl                   # Mirjam: both same
    assert "oeo:OEO_00390073 oeo:OEO_00020517 ;" in ttl     # IAM scenario type


def test_a_scenario_value_lands_on_the_scenario_it_names():
    """The `scenario` axis is the whole point of the scenario scope: one
    publication documents up to 146 of them, so a region with no scenario is a
    region nobody can place."""
    rows = _scenario_rows() + [
        {"parameter": "scenario_year", "value": "2070", "scenario": "NDC-LTT",
         "quote": "NDC-LTT runs to 2070", "tier": "text_located",
         "provenance": {"page": 10, "owner_kind": "section", "owner_id": 10}}]
    ttl = _ttl(rows)
    assert ttl.count("a oeo:OEO_00000365 ;") == 2
    curpol = ttl.split('dc:acronym "CurPol"')[1].split(" .")[0]
    assert '"2050-01-01T00:00:00"^^xsd:dateTime' in curpol
    assert '"2070-01-01T00:00:00"' not in curpol, "the other scenario's year"


def test_a_scenario_name_the_ar6_list_does_not_know_is_counted(tmp_path, caplog):
    import sqlite3
    from profiles.scenarios import kg

    db = tmp_path / "ar6.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE DocumentMeta (document INTEGER, title TEXT, year INTEGER,"
        " doi TEXT);"
        "CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,"
        " name TEXT);"
        "CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);"
        "INSERT INTO Documents VALUES (1, 'geco_2023.pdf');"
        "INSERT INTO Scenarios VALUES (1, 42, 'NDC-LTT');"
        "INSERT INTO DocumentScenarios VALUES (1, 1);")
    conn.commit()
    conn.close()

    with caplog.at_level(logging.INFO, logger="profiles.scenarios.kg"):
        ttl = kg.make_serializer(db)("geco_2023", _scenario_rows())
    assert "not in the AR6 list" in caplog.text and "CurPol" in caplog.text
    assert ttl is not None, "an unknown name is counted, not dropped"


def test_the_ar6_spelling_labels_the_node_the_pdf_spelling_stays_the_acronym():
    """The AR6 database name is the identity the rest of the corpus links
    against, so it labels the node. What the PDF actually printed is not
    thrown away — it stays as the acronym."""
    import sqlite3
    import tempfile
    from profiles.scenarios import kg

    rows = [r for r in _scenario_rows() if r["parameter"] != "scenario_label"]
    rows.append({"parameter": "scenario_label", "value": "CURPOL",
                 "quote": "the Current Policies scenario (CURPOL)",
                 "tier": "text_located",
                 "provenance": {"page": 9, "owner_kind": "section",
                                "owner_id": 9}})

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ar6.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
            "CREATE TABLE DocumentMeta (document INTEGER, title TEXT,"
            " year INTEGER, doi TEXT);"
            "CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,"
            " name TEXT);"
            "CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);"
            "INSERT INTO Documents VALUES (1, 'geco_2023.pdf');"
            "INSERT INTO Scenarios VALUES (1, 42, 'CurPol');"
            "INSERT INTO DocumentScenarios VALUES (1, 1);")
        conn.commit()
        conn.close()
        ttl = kg.make_serializer(db)("geco_2023", rows)

    assert 'rdfs:label "CurPol" ;' in ttl, "the AR6 spelling labels the node"
    assert 'dc:acronym "CURPOL" ;' in ttl, "the PDF spelling is kept"


def test_every_value_can_name_the_passage_it_came_from(monkeypatch):
    """The licence argument: the graph carries what the crawl could not give
    it — the quote, the page and the rectangles on that page. As triples only
    on request, because the shapes are closed; by default as comments."""
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", True)
    ttl = _ttl(_scenario_rows())
    assert "a oekgprov:ExtractionEvidence ;" in ttl
    assert 'oekgprov:quote "CurPol covers the EU27"' in ttl or \
           'oekgprov:quote "the Current Policies scenario (CurPol)"' in ttl
    assert 'oekgprov:page "9"^^xsd:integer' in ttl
    assert "oekgprov:hasEvidence <" in ttl


def test_the_evidence_iri_is_stable_across_runs(monkeypatch):
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", True)
    assert _ttl(_scenario_rows()) == _ttl(_scenario_rows())


def test_the_evidence_can_be_switched_off_for_a_closed_shape_run(monkeypatch):
    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "EVIDENCE", False)
    ttl = _ttl(_scenario_rows())
    body = ttl.split("@prefix")[-1].split(chr(10), 1)[1]
    assert "oekgprov:" not in body, "no evidence triple, only the comment"


# ---------------------------------------------------------------------------
# The lists that are only closed once a document is named
# ---------------------------------------------------------------------------

def _at(seq, i):
    return seq[i] if i < len(seq) else None


def _corpus_db(sections=(), tables=(), figures=(), scenarios=(),
               table_captions=(), figure_captions=()):
    """A document with text in all three places a harvest can quote from."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               content TEXT);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             markdown TEXT, caption TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             description TEXT, caption TEXT);
        CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,
                                name TEXT);
        CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);
        INSERT INTO Documents VALUES (1, 'a.pdf'), (2, 'b.pdf');
        INSERT INTO Sections VALUES (1, 1, ''), (2, 2, '');
    """)
    for i, text in enumerate(sections):
        conn.execute("INSERT INTO Sections VALUES (?, 1, ?)", (10 + i, text))
    for i, text in enumerate(tables):
        conn.execute("INSERT INTO Tables VALUES (?, 1, ?, ?)",
                     (10 + i, text, _at(table_captions, i)))
    for i, text in enumerate(figures):
        conn.execute("INSERT INTO Images VALUES (?, 1, ?, ?)",
                     (10 + i, text, _at(figure_captions, i)))
    for i, (doc, name) in enumerate(scenarios):
        conn.execute("INSERT INTO Scenarios VALUES (?, ?, ?)", (10 + i, 900 + i, name))
        conn.execute("INSERT INTO DocumentScenarios VALUES (?, ?)", (doc, 10 + i))
    conn.commit()
    return conn


def test_the_scenario_list_is_this_publications_own():
    """One publication documents up to 146 of the corpus's 1389 scenarios. The
    model is asked to pick from its own, not from all of them."""
    from profiles.scenarios import extraction

    conn = _corpus_db(scenarios=[(1, "EN_NPi2100"), (1, "EN_INDCi2030_300f"),
                                 (2, "SSP2_BASE")])
    assert extraction.document_scenarios(conn, 1) == {
        "EN_NPi2100": ["EN_NPi2100"],
        "EN_INDCi2030_300f": ["EN_INDCi2030_300f"]}
    assert extraction.document_scenarios(conn, 2) == {"SSP2_BASE": ["SSP2_BASE"]}


def test_the_region_list_is_narrowed_to_what_the_document_names():
    """249 study regions is a long list to put in front of every request. The
    narrowing is safe because a claim has to quote its source verbatim, so a
    country the document never writes could never have been answered."""
    from profiles.scenarios import extraction

    conn = _corpus_db(sections=["The scenario covers Germany and Poland."],
                      tables=["| Country | 2030 |\n| France | 12 |"],
                      figures=["Emissions in Japan by sector"])
    regions = extraction.document_regions(conn, 1)
    names = {labels[0] for labels in regions.values()}
    assert {"Germany", "Poland", "France", "Japan"} <= names
    assert "Uzbekistan" not in names


def test_a_two_letter_country_is_matched_as_a_word():
    """'US' hides inside 'thus' and 'UK' inside 'Ukraine'. A false entry in the
    list only wastes a line of prompt, but it is still wrong."""
    from profiles.scenarios import extraction

    hidden = _corpus_db(sections=["Thus the trend continues in Ukraine."])
    assert "United States of America" not in {
        v[0] for v in extraction.document_regions(hidden, 1).values()}

    named = _corpus_db(sections=["Emissions in the US fall after 2030."])
    assert "United States of America" in {
        v[0] for v in extraction.document_regions(named, 1).values()}


def test_every_region_class_name_is_a_name_a_publication_would_write():
    """labels[0] is two things at once: the class name the model is told to
    copy character for character, and the rdfs:label kg.py would attach. An
    ISO long form is neither — no paper writes "Macedonia (the former Yugoslav
    Republic of)", and stamping it onto the OEKG's own individual asserts a
    name retired in 2019."""
    from profiles.scenarios import extraction

    for iri, labels in extraction._regions().items():
        name = labels[0]
        assert name == name.strip() and name
        assert "(" not in name and ")" not in name, iri
        assert "," not in name, iri
        assert name.isascii() or any(label.isascii() for label in labels[1:]),             f"{iri}: no spelling a plain keyboard can produce"


def test_the_two_congos_and_the_two_koreas_are_each_offered_under_their_own_name():
    """"Congo" alone is Brazzaville, a different country from the DRC, and the
    list used to offer the DRC only as "Congo Democratic Republic Of"."""
    from profiles.scenarios import extraction

    conn = _corpus_db(sections=["We model the Democratic Republic of the Congo "
                                "and South Korea to 2050."])
    names = {labels[0] for labels in extraction.document_regions(conn, 1).values()}
    assert "Democratic Republic of the Congo" in names
    assert "South Korea" in names


def test_a_country_named_only_in_a_caption_is_still_offered():
    """The harvest quotes a caption as readily as a cell. A region the
    narrowing never saw is one the model has no class for, so it answers with
    a wording — and a wording is what puts a duplicate country in the graph."""
    from profiles.scenarios import extraction

    conn = _corpus_db(tables=["| year | value |"],
                      table_captions=["Table 3: Emissions in India by sector"],
                      figures=["a stacked bar chart"],
                      figure_captions=["Figure 2: Primary energy in Brazil"])
    names = {labels[0] for labels in extraction.document_regions(conn, 1).values()}
    assert {"India", "Brazil"} <= names


def test_an_acronym_is_matched_with_its_capitals():
    """"US" casefolds onto the English pronoun, and these papers are English."""
    from profiles.scenarios import extraction

    pronoun = _corpus_db(sections=["The model gives us robust results."])
    assert "United States of America" not in {
        v[0] for v in extraction.document_regions(pronoun, 1).values()}


def test_document_axes_feeds_both_the_coordinate_and_the_value():
    """The scenario is a coordinate on other fields and the value of
    scenario_label. One list, both places."""
    from profiles.scenarios import extraction

    conn = _corpus_db(sections=["A study of Norway."],
                      scenarios=[(1, "EN_NPi2100")])
    axes = extraction.document_axes(conn, 1)
    assert axes["scenario"]["EN_NPi2100"] == ["EN_NPi2100"]
    assert axes["scenario_label"] == axes["scenario"]
    assert "Norway" in {v[0] for v in axes["scenario_region"].values()}
    runs = [k for k in axes["scenario"] if not k.startswith(extraction.NOT_IN_GRAPH)]
    assert runs == ["EN_NPi2100"], "the out: entries are the only additions"


def test_every_list_offers_a_way_to_say_none_of_these_fit():
    """A closed list without an escape hatch does not stop a wrong answer, it
    only makes the wrong answer look like a valid one. The corpus proves the
    need: the OEKG has 249 countries and no aggregate, and an AR6 scenario is
    usually global."""
    from profiles.scenarios import extraction

    bare = _corpus_db(sections=["A model description with no country in it."])
    axes = extraction.document_axes(bare, 1)
    assert set(axes) == {"scenario", "scenario_label", "scenario_region"}
    assert "out:global" in axes["scenario_region"]
    assert "out:family" in axes["scenario"]
    # and the lists exist even where the narrowing found nothing at all
    assert not [k for k in axes["scenario"]
                if not k.startswith(extraction.NOT_IN_GRAPH)]


def test_the_out_entries_are_short_enough_to_be_retyped_without_a_slip():
    """The model is shown labels[0] and told to copy it character for
    character, and a value that is not retyped exactly arrives as an unmapped
    wording — which is the thing these entries exist to prevent. So the answer
    token is short and the explanation is an alternate; value_to_uri() maps
    every label, so both resolve."""
    from profiles.scenarios import extraction

    for vocabulary in (extraction.REGION_OUT, extraction.SCENARIO_OUT):
        for key, labels in vocabulary.items():
            assert key.startswith(extraction.NOT_IN_GRAPH)
            assert labels[0] and len(labels[0]) <= 20, key
            assert len(labels) > 1, f"{key} has no explanation to fall back on"


def test_the_prompt_quotes_the_out_entries_exactly_as_the_list_spells_them():
    """A sentinel printed in the prompt in a spelling the vocabulary does not
    hold is worse than no sentinel: the model copies the prompt, the exact
    lookup misses, and the gloss itself is published as a scenario name or a
    region name. Both halves are checked — every entry is named, and the
    paragraph that names them quotes nothing else."""
    from pathlib import Path

    from profiles.scenarios import extraction

    prompt = Path("profiles/scenarios/prompts/extraction/harvest.md").read_text(
        encoding="utf-8")
    known = {label.casefold()
             for vocabulary in (extraction.REGION_OUT, extraction.SCENARIO_OUT)
             for labels in vocabulary.values() for label in labels}
    for vocabulary in (extraction.REGION_OUT, extraction.SCENARIO_OUT):
        for key, labels in vocabulary.items():
            assert f'"{labels[0]}"' in prompt, f"{key} is not named in the prompt"

    paragraph = [line for line in prompt.splitlines()
                 if "KEINE Klasse sind" in line]
    assert paragraph, "the paragraph that introduces the entries moved"
    for quoted in re.findall(r'"([^"]+)"', paragraph[0]):
        assert quoted.casefold() in known, f"{quoted!r} is in no vocabulary"


def test_filling_turns_the_markers_into_a_real_choice(spec):
    from docpipe.extraction.runner import fill_dynamic_axes

    filled = fill_dynamic_axes(spec, {
        "scenario": {"EN_NPi2100": ["EN_NPi2100"]},
        "scenario_label": {"EN_NPi2100": ["EN_NPi2100"]},
        "scenario_region": {"x/Norway": ["Norway"]}})
    by_uri = {p.uri: p for p in filled.parameters}
    assert by_uri["scenario_label"].value_to_uri() == {"en_npi2100": "EN_NPi2100"}
    assert by_uri["scenario_region"].value_to_uri() == {"norway": "x/Norway"}
    assert by_uri["scenario_year"].axes["scenario"].vocabulary == {
        "EN_NPi2100": ["EN_NPi2100"]}
    # Untouched: the spec object the run started from is reused per document.
    assert {p.uri: p.vocabulary for p in spec.parameters}["scenario_label"] is None


def test_a_wording_the_list_does_not_hold_survives_with_a_flag(spec):
    """The model is told to leave the class out rather than force one. If that
    answer were refused, the mapping gap would be invisible."""
    from docpipe.extraction.verify import verify_tuple, Refusal

    parameter = {p.uri: p for p in spec.parameters}["scenario_region"]
    quote = "The pathway is computed for the whole of Sub-Saharan Africa."
    outcome = verify_tuple({"value_raw": "Sub-Saharan Africa", "quote": quote},
                           parameter, quote, owner_kind="section")
    assert not isinstance(outcome, Refusal)
    assert outcome.tuple["value_raw"] == "Sub-Saharan Africa"
    assert outcome.tuple["value_uri"] is None
    assert "unmapped:value:Sub-Saharan Africa" in outcome.flags


# ---------------------------------------------------------------------------
# What the serializer does with a choice
# ---------------------------------------------------------------------------

def test_the_individuals_live_where_the_oekg_puts_them():
    """Read off the running graph, not guessed: a study report sits under
    publication/, a factsheet under scenario/, a region under region/, and a
    bundle, author or organisation directly under the base."""
    from profiles.scenarios import kg

    base = "https://openenergyplatform.org/ontology/oekg/"
    assert kg.mint("studyreport", "x").startswith(base + "publication/")
    assert kg.mint("scenariofactsheet", "x").startswith(base + "scenario/")
    assert kg.mint("studyregion", "x").startswith(base + "region/")
    for collection in ("scenariobundle", "author", "organisation", "funder"):
        rest = kg.mint(collection, "x")[len(base):]
        assert "/" not in rest, collection


def test_a_scenario_is_identified_by_the_ar6_run_and_labelled_by_the_document():
    """The run identifier is what links to the AR6 database; the wording is
    what a reader recognises. The factsheet carries both."""
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the CurPol scenario", "provenance": {}},
        {"parameter": "scenario_year", "value": "2050",
         "scenario": "EN_NPi2100", "scenario_raw": "CurPol",
         "quote": "CurPol runs to 2050", "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert "dc:acronym \"CurPol\"" in ttl
    assert "\"EN_NPi2100\"" in ttl
    # One factsheet, not two: the year row and the label row name the same run.
    assert ttl.count("a oeo:OEO_00000365") == 1
    assert "2050-01-01T00:00:00" in ttl


def test_a_scenario_the_model_could_not_place_is_still_serialized():
    """Refusing it would lose the value AND the measurement of how often the
    run identifiers and the documents' wording fail to meet."""
    rows = _rows() + [
        {"parameter": "scenario_year", "value": "2050", "scenario": None,
         "scenario_raw": "unser 1,5-Grad-Pfad",
         "quote": "unser 1,5-Grad-Pfad bis 2050", "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert "unser 1,5-Grad-Pfad" in ttl
    assert ttl.count("a oeo:OEO_00000365") == 1


def test_a_region_is_referenced_by_its_existing_oekg_iri():
    """oekg/region/Germany already exists. Minting a second IRI for the same
    country would put a duplicate country in the graph."""
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the CurPol scenario", "provenance": {}},
        {"parameter": "scenario_region", "value": "Germany",
         "value_uri": "https://openenergyplatform.org/ontology/oekg/region/Germany",
         "value_raw": "Deutschland", "scenario": "EN_NPi2100",
         "scenario_raw": "CurPol", "quote": "CurPol betrachtet Deutschland",
         "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert ("oeo:OEO_00020220 <https://openenergyplatform.org/ontology/oekg/"
            "region/Germany>") in ttl
    # and referenced is ALL it is: the individual is the OEKG's, it already
    # carries its type and its label over there, and writing ours on top would
    # put a second label on a node this harvest did not create.
    assert "region/Germany>" + chr(10) not in ttl, "no node block of our own"
    assert "OEO_00020032" not in ttl


def test_a_global_scenario_does_not_mint_a_region():
    """out:global is a true answer and not a study region. Minting it would put
    a region called "global" next to the OEKG's 249 countries, and the next run
    would point at it as if it were one."""
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the CurPol scenario", "provenance": {}},
        {"parameter": "scenario_region", "value": "global — die ganze Welt",
         "value_uri": "out:global", "value_raw": "worldwide",
         "scenario": "EN_NPi2100", "scenario_raw": "CurPol",
         "quote": "CurPol covers worldwide emissions", "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert "OEO_00020220" not in ttl, "no has-study-region link at all"
    assert "OEO_00020032" not in ttl, "and no study region node"


def test_a_family_is_a_wording_and_never_an_identity():
    """"NPi" fits EN_NPi2020_300f, _400 and _3000. The model says so by
    choosing out:family, and what survives is the document's own wording — not
    the out: entry's label, which is a description of a problem."""
    rows = _rows() + [
        {"parameter": "scenario_label",
         "value": "eine Szenario-Familie, kein einzelner Lauf",
         "value_uri": "out:family", "value_raw": "NPi",
         "quote": "the NPi scenario", "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert 'rdfs:label "NPi" ;' in ttl
    assert "Familie" not in ttl
    assert "a oeo:OEO_00000365 ;" in ttl, "the scenario is still a factsheet"


def test_no_out_entry_ever_reaches_the_turtle():
    """One guard, checked on every field that can carry a choice: an out: entry
    is countable, never quotable as an IRI, a type or a label."""
    from profiles.scenarios import extraction

    rows = _rows()
    for key in extraction.SCENARIO_OUT:
        rows.append({"parameter": "scenario_label", "value": "egal",
                     "value_uri": key, "value_raw": key.split(":")[1],
                     "quote": "q", "provenance": {}})
    for key in extraction.REGION_OUT:
        rows.append({"parameter": "scenario_region", "value": "egal",
                     "value_uri": key, "value_raw": "wording",
                     "scenario": "out:family", "scenario_raw": "NPi",
                     "quote": "q", "provenance": {}})
    ttl = _ttl(rows)
    # In the triples, not in the file: a flag comment legitimately records
    # WHICH out: entry was chosen, and the pilot's TTL carries 238 of those.
    triples = [line for line in ttl.splitlines()
               if not line.lstrip().startswith("#")]
    assert extraction.NOT_IN_GRAPH not in chr(10).join(triples)


def test_what_the_graph_does_not_take_is_counted_by_what_was_chosen(caplog):
    """The number is the finding: a corpus that is 80% out:global is telling us
    the OEKG region list is missing its aggregates."""
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol", "quote": "q",
         "provenance": {}},
        {"parameter": "scenario_region", "value": "egal",
         "value_uri": "out:global", "value_raw": "worldwide",
         "scenario": "EN_NPi2100", "scenario_raw": "CurPol", "quote": "q",
         "provenance": {}},
    ]
    with caplog.at_level(logging.INFO):
        _ttl(rows)
    assert "not in the graph by choice" in caplog.text
    assert "'out:global': 1" in caplog.text


def test_a_region_the_list_did_not_hold_mints_nothing_and_is_counted(caplog):
    """The wording used to become a node under oekg/region/ next to the 249
    real ones, typed and labelled as if it were one of them. It is a finding,
    and a finding belongs in the count, not in the graph."""
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the CurPol scenario", "provenance": {}},
        {"parameter": "scenario_region", "value": "Sub-Saharan Africa",
         "value_uri": None, "value_raw": "Sub-Saharan Africa",
         "scenario": "EN_NPi2100", "scenario_raw": "CurPol",
         "quote": "CurPol covers Sub-Saharan Africa", "provenance": {}},
    ]
    with caplog.at_level(logging.INFO):
        ttl = _ttl(rows)
    assert "OEO_00020220" not in ttl, "no study region link"
    assert "OEO_00020032" not in ttl, "and no region node of our own"
    assert "'unmapped:scenario_region': 1" in caplog.text


def test_a_scenario_type_the_list_does_not_cover_is_no_type_triple():
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the CurPol scenario", "provenance": {}},
        {"parameter": "scenario_type", "value": "keine dieser Arten",
         "value_uri": "out:not_in_list", "value_raw": "a stylised sensitivity run",
         "scenario": "EN_NPi2100", "scenario_raw": "CurPol",
         "quote": "CurPol is a stylised sensitivity run", "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert "out:" not in ttl
    # the blanket IAM annotation is the only scenario type left on the node
    assert ttl.count("oeo:OEO_00390073") == 1


def test_one_scenario_stays_one_factsheet_when_only_some_rows_resolve_it():
    """The prompt tells the model to leave the link empty when it is unsure,
    and it is sure on the sentence that introduces the scenario and unsure on
    the caption three pages later. That produced two factsheets: the linked one
    empty, the unlinked one holding every value."""
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the Current Policies scenario (CurPol)", "provenance": {}},
        {"parameter": "scenario_year", "value": "2050", "scenario": None,
         "scenario_raw": "CurPol", "quote": "CurPol results for 2050",
         "provenance": {}},
    ]
    ttl = _ttl(rows, known={"en_npi2100": "EN_NPi2100"})
    assert ttl.count("a oeo:OEO_00000365") == 1
    assert "2050-01-01T00:00:00" in ttl


def test_a_wording_that_is_not_in_its_own_quote_names_nothing():
    """A run identifier the model maps onto a description does not have to
    stand in the text — that mapping is the job. A string presented as the
    document's own name for something does."""
    rows = _rows() + [
        {"parameter": "scenario_year", "value": "2050",
         "scenario_raw": "EN_INDCi2030_1000f-NDC",
         "quote": "Results are reported for 2050 under the central pathway.",
         "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert "a oeo:OEO_00000365" not in ttl
    assert "EN_INDCi2030_1000f-NDC" not in ttl


def test_a_running_header_does_not_outvote_the_located_title_page():
    """The header stands on every page and is harvested from each of them, so
    it wins on count — and the truncation then becomes the document's IRI,
    stably, on every re-run."""
    from profiles.scenarios import kg

    full = "Global Energy and Climate Outlook 2023: a world in transition"
    rows = [{"parameter": "publication_title", "value": "Global Energy and "
             "Climate Outlook 2023", "quote": "x", "provenance": {}}
            for _ in range(3)]
    rows.append({"parameter": "publication_title", "value": full, "quote": "x",
                 "provenance": {"rects": [[1, 2, 3, 4]]}})
    assert kg._pick_one(rows)[0] == full


def test_the_absorbed_spelling_keeps_its_passage():
    """"Oeko-Institut" and "Oeko-Institut e.V." are one node — and the page
    where the second spelling stands used to vanish from the file with it."""
    rows = _rows(study_organisation=["Oeko-Institut e.V.", "Oeko-Institut"])
    rows = [dict(r, quote=f"quote for {r['value']}") if
            r["parameter"] == "study_organisation" else r for r in rows]
    ttl = _ttl(rows)
    assert ttl.count("a oeo:OEO_00030022 ;") == 1, "one organisation"
    assert ttl.count("quote for Oeko-Institut") == 2,         "both passages, not just the winning spelling's"


def test_two_documents_that_mint_one_subject_say_so(caplog):
    """A preprint and its journal version share a title, so they share a study
    report IRI — and the shapes allow one label and one date on it."""
    from pathlib import Path

    from profiles.scenarios import kg

    serialize = kg.make_serializer(Path("no-such.db"))
    with caplog.at_level(logging.WARNING):
        serialize("preprint", _rows(publication_date=["2021"]))
        serialize("journal", _rows(publication_date=["2022"]))
    assert "one subject, two documents" in caplog.text


def test_the_scenario_types_the_model_chose_reach_the_graph():
    rows = _rows() + [
        {"parameter": "scenario_label", "value": "EN_NPi2100",
         "value_uri": "EN_NPi2100", "value_raw": "CurPol",
         "quote": "the CurPol scenario", "provenance": {}},
        {"parameter": "scenario_type", "value": "with existing measures scenario",
         "value_uri": "https://openenergyplatform.org/ontology/oeo/OEO_00020311",
         "value_raw": "adopted and implemented", "scenario": "EN_NPi2100",
         "scenario_raw": "CurPol", "quote": "policies adopted and implemented",
         "provenance": {}},
    ]
    ttl = _ttl(rows)
    assert ("oeo:OEO_00390073 <https://openenergyplatform.org/ontology/oeo/"
            "OEO_00020311>") in ttl
    # Mirjam's blanket IAM annotation stays alongside it.
    assert "oeo:OEO_00390073 oeo:OEO_00020517" in ttl


def test_the_list_settles_what_the_model_gave_up_on():
    """An out: entry is a claim ABOUT THE LIST — "no single run fits" — and the
    list is right there to be read. Measured on the corpus run: 1171 refusals
    whose wording their own list resolved without a guess, one document
    refusing "BaU" against a list whose only entry is "BaU"."""
    from profiles.scenarios import kg

    known = {kg.normalise("BaU"): "BaU"}
    row = {"parameter": "scenario_label", "value_uri": "out:not_documented",
           "value_raw": "BaU", "quote": "the BaU scenario"}
    assert kg.scenario_key(row, known) == ("BaU", "BaU")

    longer = {kg.normalise("EN_NPi2020_400"): "EN_NPi2020_400"}
    row = {"parameter": "scenario_label", "value_uri": "out:family",
           "value_raw": "NPi2020_400", "quote": "the NPi2020_400 run"}
    assert kg.scenario_key(row, longer)[0] == "EN_NPi2020_400"


def test_a_short_wording_links_only_on_an_exact_name():
    """"NPi" is three characters and sits inside a dozen run names. A
    containment hit that short is a coincidence, not a reading."""
    from profiles.scenarios import kg

    known = {kg.normalise(n): n for n in
             ("EN_NPi2020_400", "EN_NPi2020_1000", "EN_NPi2020_3000")}
    assert kg.resolve_wording("NPi", known) is None
    assert kg.resolve_wording("EN_NPi2020_400", known) == "EN_NPi2020_400"


def test_the_guard_still_wins_where_several_runs_fit():
    """resolve_wording is the mirror of ambiguous(), not its replacement."""
    from profiles.scenarios import kg

    known = {kg.normalise(n): n for n in
             ("EN_NPi2020_400", "EN_NPi2020_1000")}
    assert kg.resolve_wording("NPi2020", known) is None
    row = {"parameter": "scenario_label", "value_uri": "out:family",
           "value_raw": "NPi2020", "quote": "the NPi2020 family"}
    assert kg.scenario_key(row, known) == ("NPi2020", "NPi2020")


def test_a_scenario_wording_that_fits_several_runs_links_to_none():
    """The pilot document names 146 AR6 runs and the paper writes "NPi". The
    database has EN_NPi2020_300f, _400 and _3000 — three runs, one family. A
    model handed the list picks one anyway; that is a guess dressed as a link,
    so the wording survives alone and the factsheet stays unlinked."""
    from profiles.scenarios import kg

    known = {kg.normalise(n): n for n in
             ("EN_NPi2020_300f", "EN_NPi2020_400", "EN_NPi2020_3000")}
    assert kg.ambiguous("NPi", known)
    assert not kg.ambiguous("EN_NPi2020_400", known), "an exact name is not a family"

    row = {"parameter": "scenario_label", "value_uri": "EN_NPi2020_400",
           "value_raw": "NPi"}
    assert kg.scenario_key(row, known) == ("NPi", "NPi")
    assert kg.scenario_key(row, None) == ("EN_NPi2020_400", "NPi"), \
        "without the list there is nothing to call ambiguous"


def test_every_parameter_says_which_node_it_lands_on(spec):
    """A block whose `node` is not a node of this graph describes nothing. The
    fourteen were silent until this commit, and the preflight could not see it:
    its check reads the axes, and thirteen of the fourteen have none."""
    import profiles.scenarios.kg as kg
    for parameter in kg._SPEC["parameters"]:
        block = parameter.get("kg") or {}
        assert block, parameter["uri"]
        assert block.get("node") in kg.COLLECTIONS, (parameter["uri"],
                                                     block.get("node"))
        assert "property" in block, parameter["uri"]


def test_a_prefix_no_header_declares_would_not_parse(spec):
    """`dcterms:abstract` instead of `dc:abstract` writes a Turtle file no
    reader can load, and it would look right in the diff. The header is the
    only place that decides, so every block is held to it."""
    import profiles.scenarios.kg as kg
    used = set()
    for parameter in kg._SPEC["parameters"]:
        block = parameter.get("kg") or {}
        for key in ("property", "also", "edge_from"):
            if block.get(key):
                used.add(block[key]["prefix"])
        for axis in (parameter.get("axes") or {}).values():
            link = (axis.get("kg") or {}).get("linked_by")
            if link:
                used.add(link["prefix"])
    assert used == {"rdfs", "dc", "oeo", "obo"}, used
    for prefix in used:
        assert f"@prefix {prefix}:" in kg.PREFIXES


def test_the_four_scenario_axes_name_one_and_the_same_factsheet():
    """They are four questions about the same node, so a block that drifts on
    one of them puts one parameter's values on a node of its own. The class is
    cross-checked against the parameter that mints the factsheet, which is a
    different block in a different place."""
    import profiles.scenarios.kg as kg
    blocks = [(p["uri"], p["axes"]["scenario"]["kg"])
              for p in kg._SPEC["parameters"]
              if "scenario" in (p.get("axes") or {})]
    assert [uri for uri, _b in blocks] == list(kg.SCENARIO_FIELDS)
    assert len(blocks) == 4
    assert all(b == blocks[0][1] for _u, b in blocks)
    assert blocks[0][1]["role"] == "parent"
    assert blocks[0][1]["class"] == kg.CLS_SCENARIO
    assert blocks[0][1]["node"] == "scenariofactsheet"
    # And the edge it names is really written, on the bundle.
    ttl = _ttl(_scenario_rows())
    predicate = kg._name(blocks[0][1]["linked_by"])
    assert f"    {predicate} <" in ttl


def test_the_serializer_dies_at_import_if_the_spec_stops_saying_it(spec):
    """The constants are reads, not literals with a comment beside them. A
    parameter whose block loses its predicate must stop the serializer where
    it is noticed, not write a graph with an empty predicate in it."""
    import pytest as _pytest

    import profiles.scenarios.kg as kg
    with _pytest.raises(KeyError):
        kg._property("publication_title", "no_such_key")
    with _pytest.raises(KeyError):
        kg._name({"predicate": "OEO_00000506"})          # no prefix
    with _pytest.raises(KeyError):
        kg._name({"prefix": "dcterms", "predicate": "abstract"})
    with _pytest.raises(KeyError):
        kg._class("publication_date")                    # mints no node
    with _pytest.raises(KeyError):
        kg._kg("no_such_parameter")


def test_a_parameter_that_says_nothing_stops_the_serializer(monkeypatch):
    """Every parameter carries a block today, so the refusal never fires on
    this spec -- and a refusal that cannot fire is one nobody has run. The
    fifteenth parameter is the case: read as an empty block it would mint a
    node with no predicate and the graph would be short one field with no line
    anywhere saying so."""
    import pytest as _pytest

    import profiles.scenarios.kg as kg
    monkeypatch.setattr(kg, "_SPEC", {"parameters": [
        {"uri": "publication_venue", "label": "Wo erschienen"}]})
    with _pytest.raises(KeyError, match="says nothing about the graph"):
        kg._kg("publication_venue")


def test_the_preflight_names_a_parameter_that_says_nothing():
    """The same question the serializer asks, asked in the job prolog where
    pytest does not run."""
    from scripts import preflight_profiles as pre

    assert pre.silent_parameters({"parameters": [
        {"uri": "a", "kg": {"node": "studyreport"}},
        {"uri": "b"}]}) == ["b"]
    assert pre.silent_parameters({"parameters": []}) == []
