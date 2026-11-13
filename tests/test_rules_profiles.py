"""
The rules the two profiles apply while they read and write (profiles/
scenarios: vocabulary, extraction, completion, graph file; profiles/kwp:
extraction, graph file): each switched changes what the profile's code does
AND the standard gives today's result (owner, 2026-11-11: "alles soll
anpassbar sein"). A rule with `decided` has the owner's decision as its
standard.
"""
import json
from types import SimpleNamespace

import pytest

from docpipe import graphfile, rules
from docpipe.extraction import contract
from docpipe.extraction import graph as program
from docpipe.extraction.bricks import Brick
from docpipe.profile import load_profile
from profiles.kwp import extraction as kwp_extraction
from profiles.scenarios import completion, extraction, vocabulary

from test_graph_from_shapes import (OEO, authors_of, described, serialized,
                                    written_by)
from test_graph_readings_rules import number
from test_region_groups import (CODES, EPPA_SOUTH, MODELS, PLACES, REGION,
                                REGIONS, offered)

SCENARIOS = load_profile("scenarios")
KWP = load_profile("kwp")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for env in rules.ENVS + (graphfile.ENV, "OEKG_EVIDENCE"):
        monkeypatch.delenv(env, raising=False)
    rules.reset()
    graphfile.reset()
    yield
    rules.reset()
    graphfile.reset()


@pytest.fixture
def graph_rules(tmp_path, monkeypatch):
    """Lay values over the rules of the graph file for the writer."""
    def lay(**values):
        file = tmp_path / "graph.json"
        file.write_text(json.dumps({"rules": values}), encoding="utf-8")
        monkeypatch.setenv(graphfile.ENV, str(file))
        graphfile.reset()
    return lay


def standard(profile, name):
    return rules.load(profile, environ={})[name]


# -- scenarios: vocabulary ----------------------------------------------------

BANKS = [("EUU", "European Union", ["France", "Spain"]),
         ("OED", "OECD members", ["Spain"])]
WITH_UK = {**REGIONS, REGION + "UnitedKingdom": ["United Kingdom"]}


def groups_of(regions=WITH_UK):
    return vocabulary.aggregates([], [], regions, banks=BANKS)


def test_country_groups_add_the_groups_no_source_lists():
    row, = standard(SCENARIOS, "country_groups")  # decided 2026-11-04
    assert (row["key"], row["union"], row["joined"]) == (
        "aggregate:EU28", "aggregate:worldbank:EUU", "United Kingdom")
    groups, _ = groups_of()
    assert set(groups["aggregate:EU28"]["members"]) == {
        REGION + "France", REGION + "Spain", REGION + "UnitedKingdom"}
    assert groups["aggregate:EU28"]["labels"] == ["EU28", "EU-28", "EU 28"]
    with rules.overlaid(country_groups=[]):
        assert "aggregate:EU28" not in groups_of()[0]
    own = {"key": "aggregate:Spanish", "labels": "Spanish|Hispanic",
           "union": "aggregate:worldbank:OED", "joined": "France",
           "source": "mine"}
    with rules.overlaid(country_groups=[own]):
        groups, _ = groups_of()
        assert set(groups["aggregate:Spanish"]["members"]) == {
            REGION + "Spain", REGION + "France"}
        assert groups["aggregate:Spanish"]["labels"] == ["Spanish",
                                                         "Hispanic"]
        assert "aggregate:EU28" not in groups
    # a group whose base is no group is counted, never guessed
    broken = {**own, "union": "aggregate:worldbank:NONE"}
    with rules.overlaid(country_groups=[broken]):
        groups, missing = groups_of()
        assert "aggregate:Spanish" not in groups
        assert missing["group Spanish"] == 1


def test_short_forms_are_other_ways_a_paper_writes_a_world_bank_group():
    assert standard(SCENARIOS, "short_forms") == {   # decided 2026-11-04
        "EUU": ["EU"], "OED": ["OECD"]}
    groups, _ = groups_of()
    assert groups["aggregate:worldbank:EUU"]["labels"] == [
        "European Union", "EU"]
    with rules.overlaid(short_forms={}):
        groups, _ = groups_of()
        assert groups["aggregate:worldbank:EUU"]["labels"] == [
            "European Union"]
    with rules.overlaid(short_forms={"EUU": ["Union", "EU-27"]}):
        groups, _ = groups_of()
        assert groups["aggregate:worldbank:EUU"]["labels"] == [
            "European Union", "Union", "EU-27"]
        assert groups["aggregate:worldbank:OED"]["labels"] == [
            "OECD members"]


def members_of(names):
    groups, missing = vocabulary.aggregates([], [], PLACES,
                                            banks=[("T", "Test", names)])
    return (groups.get("aggregate:worldbank:T") or {}).get("members",
                                                           []), missing


def test_name_abbreviations_are_written_out_before_a_member_is_looked_up():
    assert standard(SCENARIOS, "name_abbreviations")["st."] == "saint"
    found, _ = members_of(["St. Lucia"])
    assert found == [REGION + "SaintLucia"]
    with rules.overlaid(name_abbreviations={}):
        found, missing = members_of(["St. Lucia"])
        assert found == [] and missing["member St. Lucia"] == 1
    with rules.overlaid(name_abbreviations={"st.": "sao tome and"}):
        assert members_of(["St. Principe"])[0] == [
            REGION + "SaoTomeAndPrincipe"]


def test_world_labels_are_the_ways_the_whole_world_is_written():
    standard_labels = standard(SCENARIOS, "world_labels")
    assert "global" in standard_labels and "World" in standard_labels
    world = groups_of()[0][vocabulary.WORLD]
    assert world["labels"] == standard_labels
    with rules.overlaid(world_labels=["Welt"]):
        assert groups_of()[0][vocabulary.WORLD]["labels"] == ["Welt"]


# -- scenarios: which regions a document is offered ---------------------------

def test_acronym_most_chars_say_how_long_a_name_in_capitals_is_matched_so():
    assert standard(SCENARIOS, "acronym_most_chars") == 4
    text = "Please give us more time, said the thus tired author."
    assert not extraction._mentioned(text, ["US"])       # capitals only
    assert extraction._mentioned("The US grows.", ["US"])
    with rules.overlaid(acronym_most_chars=1):
        assert extraction._mentioned(text, ["US"])       # a word like any
    with rules.overlaid(acronym_most_chars=0):
        assert extraction._mentioned(text, ["US"])
    assert not extraction._mentioned(text, ["US"])


def test_model_region_needs_model_decides_whether_the_model_must_be_named(
        monkeypatch):
    # decided 2026-11-07
    assert standard(SCENARIOS, "model_region_needs_model") is True
    families = MODELS[:2]                                  # EPPA only
    assert EPPA_SOUTH not in offered(monkeypatch, "SOU leads.", families,
                                     CODES)
    with rules.overlaid(model_region_needs_model=False):
        assert EPPA_SOUTH in offered(monkeypatch, "SOU leads.", families,
                                     CODES)
    # a paper that names the model is offered it either way
    assert EPPA_SOUTH in offered(monkeypatch, "EPPA: SOU leads.", families,
                                 CODES)
    with rules.overlaid(model_region_needs_model=False):
        assert EPPA_SOUTH in offered(monkeypatch, "EPPA: SOU leads.",
                                     families, CODES)
    assert EPPA_SOUTH not in offered(monkeypatch, "SOU leads.", families,
                                     CODES)


# -- scenarios: the catalogue -------------------------------------------------

def test_catalogue_address_is_where_the_catalogue_is_asked(monkeypatch):
    asked = []
    monkeypatch.setattr(completion, "_get",
                        lambda url: asked.append(url) or {"results": []})
    assert standard(SCENARIOS, "catalogue_address") == \
        "https://api.openalex.org/works"  # decided 2026-11-04
    completion.search_hits("A title")
    assert asked[-1].startswith("https://api.openalex.org/works?")
    with rules.overlaid(catalogue_address="https://catalogue.example/w"):
        completion.search_hits("A title")
        assert asked[-1].startswith("https://catalogue.example/w?")
        completion.by_doi("10.1/x")
        assert asked[-1].startswith("https://catalogue.example/w/doi:10.1/x")
    completion.by_doi("10.1/x")
    assert asked[-1].startswith("https://api.openalex.org/works/doi:")


# -- both: the language of the labels and of the contract text ----------------

@pytest.mark.parametrize("name, language, module", [
    ("kwp", "de", kwp_extraction), ("scenarios", "en", extraction)])
def test_the_language_of_the_labels_and_the_contract_follows_the_rules(
        monkeypatch, name, language, module):
    monkeypatch.setenv("DOCPIPE_PROFILE", name)       # the profile of the run
    rules.reset()
    profile = load_profile(name)
    other = "en" if language == "de" else "de"
    assert standard(profile, "alt_label_language") == language
    assert standard(profile, "contract_language") == language
    assert profile.require("extraction", "ALT_LABEL_LANGUAGE") == language
    assert contract.language_of(profile) == language
    with rules.overlaid(alt_label_language=other, contract_language=other):
        assert module.ALT_LABEL_LANGUAGE == other
        assert profile.require("extraction", "ALT_LABEL_LANGUAGE") == other
        assert contract.language_of(profile) == other
    assert module.CONTRACT_LANGUAGE == language
    # a language the core has no templates in is refused
    assert rules.problem("contract_language", "fr",
                         rules.registry(profile)) is not None


# -- kwp: the full graph keeps what still disagrees ---------------------------

AT = Brick("at", "address", "", "", "",
           lambda call: call.row["at"]
           + (f"/{call.label}" if call.label else ""))


def numbers_written(*values, strict=False):
    """The numbers of one place of the graph, as the writer settles them
    with the graph rules of kwp: [(value, marks)]."""
    found = graphfile.load(KWP).rules
    writer = program.Writer(program.Drawing({"prefixes": {}, "boxes": [],
                                             "arrows": []}),
                            spec=SimpleNamespace(), rules=found,
                            bricks={"at": AT}, strict=strict)
    rows = [{**number(value), "at": "a"} for value in values]
    doc = program.Document(writer, "d", rows, None)
    doc.admitted["v"] = rows
    got = writer._numbers(doc, {"id": "v", "address": {"brick": "at"},
                                "settle": {}})
    return [(node.rows[0]["value"], node.data["marks"]) for node in got]


def test_contested_in_full_keeps_numbers_that_still_disagree_as_contested(
        graph_rules):
    # decided 2026-11-02
    assert graphfile.load(KWP).rules["contested_in_full"] is True
    assert numbers_written(100, 300) == [(100, {"conflict": True}),
                                         (300, {"conflict": True})]
    graph_rules(contested_in_full=False)
    assert numbers_written(100, 300) == []                  # left out as well
    graph_rules()
    # the strict graph leaves them out either way
    assert numbers_written(100, 300, strict=True) == []
    graph_rules(contested_in_full=False)
    assert numbers_written(100, 300, strict=True) == []
    # a number nothing contradicts is written whatever the rule says
    assert numbers_written(100) == [(100, {})]


# -- scenarios: what the graph writes -----------------------------------------

def test_scenario_types_always_are_the_types_every_scenario_carries(
        graph_rules):
    assert graphfile.load(SCENARIOS).rules["scenario_types_always"] == [
        "OEO_00020517"]                               # decided 2026-11-04
    iam = "OEO_00020517"
    names = {REGION + "Germany": "Germany", OEO + iam: "IAM scenario"}
    _, texts = described(names, ("a", [REGION + "Germany"]))
    assert iam in "".join(texts)
    graph_rules(scenario_types_always=[])
    _, texts = described(names, ("a", [REGION + "Germany"]))
    assert iam not in "".join(texts)
    graph_rules(scenario_types_always=["OEO_00000001"])
    _, texts = described({REGION + "Germany": "Germany"},
                         ("a", [REGION + "Germany"]))
    assert "OEO_00000001" in "".join(texts) and iam not in "".join(texts)


def test_evidence_as_says_where_the_place_of_a_value_goes(graph_rules):
    rows = written_by(("Ada Lovelace", 1))
    assert graphfile.load(SCENARIOS).rules["evidence_as"] == "comment"
    comment = serialized(rows)
    assert "oekgprov:quote" not in comment
    assert "# " in comment and "Ada Lovelace" in comment
    graph_rules(evidence_as="node")
    node = serialized(written_by(("Ada Lovelace", 1)))
    assert "oekgprov:quote" in node
    graph_rules(evidence_as="comment")
    assert "oekgprov:quote" not in serialized(written_by(("Ada Lovelace", 1)))


def test_front_first_fields_name_the_fields_a_front_page_reading_wins(
        graph_rules):
    fields = graphfile.load(SCENARIOS).rules["front_first_fields"]
    assert "publication_author" in fields                # decided 2026-11-05

    def rows():
        return written_by(("Ada Lovelace", 1), ("Grace Hopper", 12),
                          ("Alan Turing", 13))
    assert authors_of(serialized(rows())) == ["Ada Lovelace"]
    graph_rules(front_first_fields=[f for f in fields
                                    if f != "publication_author"])
    assert authors_of(serialized(rows())) == [
        "Ada Lovelace", "Alan Turing", "Grace Hopper"]
    graph_rules(front_first_fields=fields)
    assert authors_of(serialized(rows())) == ["Ada Lovelace"]
