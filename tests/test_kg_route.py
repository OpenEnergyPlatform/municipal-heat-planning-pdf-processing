"""The graph route: a question becomes coordinates, the coordinates a query,
the query values with the trust line the serializer wrote above them.

The fixture is a TTL the REAL serializer writes. A checked-in string would
freeze the predicates, and the drift test could never fail.
"""
import json
import re

import pytest
from rdflib import RDF, URIRef

from docpipe.extraction import fields
from docpipe.inference import kg_route, llm_client
from docpipe.profile import load_profile
from profiles.kwp import inference, kg, vocabulary
from tests.test_kwp_extraction import (SPEC, _database, _database_corpus_format,
                                       _row)

UNSTATED = fields.UNSTATED
DOCUMENT = "waermeplan_kassel_20240315"


def asking(**answers):
    """An `ask` that answers by slot name and says UNSTATED to the rest."""
    def ask(task, slot):
        return answers.get(slot.name, UNSTATED)
    return ask


@pytest.fixture
def graph_fixture(tmp_path):
    """A TTL from the real serializer: one plan with three parts, a second
    plan the query must never reach.

    Rows must not share coordinates: the value IRI is a pure function of
    part, quantity, carrier, sector, year, aggregation and area, and two rows
    with the same ones are dropped as a conflict, both of them. The C row
    therefore has its own year, and one row carries a sector, or the sector
    test would pass on an empty fixture.
    """
    db = _database(tmp_path)
    serializer = kg.make_serializer(db)
    ttl = serializer(DOCUMENT, [
        _row(),                                            # 2030 Erdgas
        _row(carrier="OEO_00000132", value_target=88.0),   # 2030 Fernwaerme
        _row(sector="OEO_00000214", value_target=55.0),    # 2030 + a sector
        _row(scenario="status_quo", year=2022, value_target=300.0),
        _row(scenario="trend", value_target=250.0),
        _row(year=2040, value_target=7.0,                  # a C by construction
             flags=["quote_repaired"]),
    ])
    # The second plan must be document 1082: 858 shares AGS and date with
    # 857 and the serializer refuses it whole.
    ttl += "\n" + serializer("waermeplan_ohne_textebene",
                             [_row(value_target=999.0)])
    graph, comments = kg_route.load_graph_from_text(ttl)
    return db, ttl, graph, comments


@pytest.fixture
def hooks():
    return kg_route.hooks(load_profile("kwp"))


def _numbers(graph, plan, coordinates):
    text, bindings = kg.value_bindings(coordinates)
    query = kg.VALUE_QUERY.replace(kg_route.CONSTRAINTS_MARKER, text)
    rows = kg_route.run_query(graph, query, dict(bindings, PLAN=("iri", plan)))
    return sorted(float(row["number"]) for row in rows)


# --- the query against the graph -------------------------------------------

def test_the_query_names_only_predicates_the_serializer_writes(graph_fixture):
    """Interpolated from the P_* constants, so a hand-typed predicate here
    would be the one absent from the Turtle."""
    _db, ttl, _graph, _comments = graph_fixture
    named = set(re.findall(r"\b(?:rdfs|obo|oeo|mhpo|xsd):[A-Za-z_0-9]+",
                           kg.VALUE_QUERY))
    assert len(named) >= 7
    for name in sorted(named):
        assert name in ttl, name


def test_the_plan_and_the_scenario_bound_return_that_plans_target_values_only(
        graph_fixture):
    db, _ttl, graph, _comments = graph_fixture
    plan = kg.heatplan_iri(db, DOCUMENT)
    assert _numbers(graph, plan, {"scenario": "target"}) == [7.0, 55.0, 88.0,
                                                             241.0]
    everything = _numbers(graph, plan, {})
    assert 300.0 in everything and 250.0 in everything, "other parts, unbound"
    assert 999.0 not in everything, "the other plan, never"


def test_the_year_binds_as_a_plain_literal(graph_fixture):
    """The serializer writes the year node's label untyped, so an integer
    literal matches nothing."""
    db, _ttl, graph, _comments = graph_fixture
    plan = kg.heatplan_iri(db, DOCUMENT)
    text, bindings = kg.value_bindings({"year": 2030})
    assert bindings["YEAR"] == ("literal", "2030")
    query = kg.VALUE_QUERY.replace(kg_route.CONSTRAINTS_MARKER, text)
    plain = dict(bindings, PLAN=("iri", plan))
    assert len(kg_route.run_query(graph, query, plain)) == 4
    typed = dict(plain, YEAR=("literal", 2030))
    assert kg_route.run_query(graph, query, typed) == []


def test_carrier_and_sector_are_told_apart_by_the_iri_not_the_predicate(
        graph_fixture):
    db, _ttl, graph, _comments = graph_fixture
    assert kg.P_CARRIER == kg.P_SECTOR == kg.P_YEAR
    plan = kg.heatplan_iri(db, DOCUMENT)
    assert _numbers(graph, plan, {"scenario": "target",
                                  "sector": "OEO_00000214"}) == [55.0]
    assert _numbers(graph, plan, {"scenario": "target",
                                  "carrier": "OEO_00000132"}) == [88.0]


def test_the_year_node_never_comes_back_as_a_carrier(graph_fixture):
    db, _ttl, graph, _comments = graph_fixture
    plan = kg.heatplan_iri(db, DOCUMENT)
    text, bindings = kg.value_bindings({})
    rows = kg_route.run_query(
        graph, kg.VALUE_QUERY.replace(kg_route.CONSTRAINTS_MARKER, text),
        dict(bindings, PLAN=("iri", plan)))
    abouts = [about for row in rows for about in (row["abouts"] or "").split()]
    assert abouts, "carriers do come back"
    assert not [a for a in abouts if a.startswith(kg.BASE + "year/")]


def test_every_part_class_expands_to_an_iri_the_serializer_wrote(graph_fixture):
    """Two parts are mhpo: and one is oeo:, so one namespace for all three
    would bind IRIs no graph holds and the scenario filter would return
    nothing, silently."""
    _db, _ttl, graph, _comments = graph_fixture
    prefixes = set()
    for cls, _segment, _label in kg.PARTS.values():
        prefixes.add(cls.split(":")[0])
        assert (None, RDF.type, URIRef(kg.expand(cls))) in graph, cls
    assert prefixes == {"mhpo", "oeo"}
    assert kg.expand("mhpo:MHPO_00020007") == \
        "https://purl.org/mhpo/ontology/MHPO_00020007"
    with pytest.raises(KeyError):
        kg.expand("nix:MHPO_00020007")
    with pytest.raises(KeyError):
        kg.expand("MHPO_00020007")


# --- the trust line ---------------------------------------------------------

def test_the_trust_line_is_not_in_the_graph_and_is_recovered_from_the_text(
        graph_fixture):
    _db, ttl, graph, comments = graph_fixture
    assert not any(kg.TRUST_PROSE["level"].split(":")[0] in str(o)
                   for o in graph.objects())
    values = {str(s) for s in graph.subjects(URIRef(kg.expand(kg.P_NUMBER)),
                                             None)}
    assert len(values) == 7
    assert set(comments) == values
    # A blank line resets the buffer: a comment above a gap belongs to no
    # node, or the plan written after a value would inherit its badge.
    stray = "# a line about nothing\n\n<https://x.example/y>\n    a oeo:X .\n"
    assert kg_route.trust_comments(stray) == {}
    assert kg_route.trust_comments(stray.replace("\n\n", "\n")) == {
        "https://x.example/y": ["a line about nothing"]}


def test_a_c_level_value_shows_the_word_the_profile_reviews_with(graph_fixture):
    db, _ttl, graph, comments = graph_fixture
    plan = kg.heatplan_iri(db, DOCUMENT)
    text, bindings = kg.value_bindings({"year": 2040})
    [row] = kg_route.run_query(
        graph, kg.VALUE_QUERY.replace(kg_route.CONSTRAINTS_MARKER, text),
        dict(bindings, PLAN=("iri", plan)))
    badge = comments[row["value"]][-1]
    assert kg.TRUST_PROSE["review"] in badge
    assert kg_route.trust_level(badge, kg.TRUST_PROSE) == kg_route.LEVEL_C
    assert kg_route.trust_level("nothing here", kg.TRUST_PROSE) is None


def test_a_value_without_a_trust_line_falls_back_instead_of_rendering(
        graph_fixture, hooks):
    db, _ttl, graph, comments = graph_fixture
    ask = asking(parameter="Energieverbrauch", scenario="Zielszenario")
    whole = kg_route.answer_from_graph("q", hooks, graph, comments, db_path=db,
                                       document=DOCUMENT, ask=ask)
    assert whole["route"] == "kg" and len(whole["values"]) == 4
    # One returned value loses its comment block: the whole answer is
    # withheld, not rendered three-quarters badged.
    short = dict(comments)
    short.pop(whole["values"][0]["value"])
    outcome = kg_route.answer_from_graph("q", hooks, graph, short, db_path=db,
                                         document=DOCUMENT, ask=ask)
    assert (outcome["route"], outcome["reason"]) == ("rag", "no_trust")
    assert outcome["values"] == []


# --- from a question to coordinates -----------------------------------------

def test_the_answer_space_is_the_specs_own_list():
    """The dict handed to `ask` is the slot's own answerable(), UNSTATED
    included -- not a hand-written list and not the bare vocabulary."""
    seen = []

    def ask(task, slot):
        seen.append(slot)
        return "Energieverbrauch" if slot.name == "parameter" else UNSTATED

    assert kg_route.to_coordinates("q", SPEC, kg.COORDINATE_AXES, ask) == {}
    parameter = SPEC.by_uri["energy_consumption"]
    assert seen[0].answerable() == fields.parameter_slot(SPEC).answerable()
    expected = [s for s in fields.axis_slots(parameter)
                if s.name in kg.COORDINATE_AXES]
    assert [s.name for s in seen[1:]] == [s.name for s in expected]
    assert len(expected) == 5
    for slot, wanted in zip(seen[1:], expected):
        assert slot.answerable() == wanted.answerable()
        assert UNSTATED in slot.answerable()
        assert slot.answerable() != parameter.axes[slot.name].vocabulary


def test_a_synonym_resolves_through_the_axis_not_by_string_match():
    carrier = SPEC.by_uri["energy_consumption"].axes["carrier"]
    assert "Wärmenetz" in carrier.vocabulary["OEO_00000132"]
    assert carrier.vocabulary["OEO_00000132"][0] != "Wärmenetz"
    got = kg_route.to_coordinates(
        "q", SPEC, kg.COORDINATE_AXES,
        asking(parameter="Energieverbrauch", carrier="Wärmenetz"))
    assert got == {"carrier": "OEO_00000132"}
    got = kg_route.to_coordinates(
        "q", SPEC, kg.COORDINATE_AXES,
        asking(parameter="Energieverbrauch", carrier="Wärmenetze GmbH"))
    assert "carrier" not in got
    got = kg_route.to_coordinates(
        "q", SPEC, kg.COORDINATE_AXES,
        asking(parameter="Energieverbrauch", year="im Jahr 2030"))
    assert got == {"year": 2030}


def test_unstated_leaves_the_axis_unbound():
    got = kg_route.to_coordinates(
        "q", SPEC, kg.COORDINATE_AXES,
        asking(parameter="Energieverbrauch", scenario="Zielszenario",
               sector=UNSTATED))
    assert got == {"scenario": "target"}
    text, bindings = kg.value_bindings(got)
    assert "SECTOR" not in text and "SECTOR" not in bindings
    assert "out:" not in text and "out:" not in json.dumps(bindings)
    assert kg_route.to_coordinates("q", SPEC, kg.COORDINATE_AXES,
                                   asking()) == {}


def test_an_out_class_is_never_bound_as_a_coordinate():
    text, bindings = kg.value_bindings({"quantity": "out:potential",
                                        "carrier": "out:total",
                                        "scenario": "target"})
    assert set(bindings) == {"PART"}
    assert "out:" not in text and "out:" not in json.dumps(bindings)
    text, bindings = kg.value_bindings({"quantity": "OEO_00050016",
                                        "carrier": "OEO_00000292",
                                        "sector": "OEO_00000214",
                                        "year": 2030, "scenario": "target"})
    assert set(bindings) == {"PART", "QUANTITY", "CARRIER", "SECTOR", "YEAR"}
    assert bindings["QUANTITY"] == ("iri", kg.OEO + "OEO_00050016")


def test_heatplan_iri_is_the_one_the_serializer_minted(tmp_path):
    """Byte-identical for both stored date forms, dashed and YYYYMMDD: a
    second f-string in the app is where `_iso_date` bites."""
    for database in (_database, _database_corpus_format):
        db = database(tmp_path)
        ttl = kg.make_serializer(db)(DOCUMENT, [_row()])
        iri = kg.heatplan_iri(db, DOCUMENT)
        assert iri and f"<{iri}>\n    a {kg.CLS_HEATPLAN} ;" in ttl
        assert kg.heatplan_iri(db, DOCUMENT + ".pdf") == iri
        assert iri == kg.plan_iri("06611000", "2024-03-15")
        assert kg.heatplan_iri(db, "nirgends") is None


def test_a_class_is_shown_by_the_specs_own_spelling():
    assert kg.label_of(kg.OEO + "OEO_00000292") == "Erdgas"
    assert kg.label_of("oeo:OEO_00000214") == "Private Haushalte"
    pinned = vocabulary.load()["terms"]["OEO_00050008"]["label"]
    assert kg.label_of("OEO_00050008") == pinned != "OEO_00050008"
    assert kg.label_of("OEO_99999999") == "OEO_99999999"


# --- the route as a whole ---------------------------------------------------

def test_the_graph_answers_with_values_and_their_evidence(graph_fixture, hooks):
    db, _ttl, graph, comments = graph_fixture
    ask = asking(parameter="Energieverbrauch", scenario="Zielszenario",
                 year="2030")
    outcome = kg_route.answer_from_graph(
        "Endenergieverbrauch 2030 im Zielszenario?", hooks, graph, comments,
        db_path=db, document=DOCUMENT + ".pdf", ask=ask)
    assert outcome["route"] == "kg" and outcome["reason"] is None
    assert outcome["coordinates"] == {"scenario": "target", "year": 2030}
    assert sorted(float(v["number"]) for v in outcome["values"]) == [
        55.0, 88.0, 241.0]
    for value in outcome["values"]:
        assert kg_route.trust_level(value["trust"], hooks.prose) in \
            kg_route.LEVELS
        assert value["evidence"] and value["trust"] not in value["evidence"]
        assert value["partLabel"].startswith("Zielszenario")


def test_every_reason_the_route_gives_is_reached(graph_fixture, hooks):
    db, _ttl, graph, comments = graph_fixture
    said = asking(parameter="Energieverbrauch", scenario="Zielszenario")

    def reason(document, ask):
        out = kg_route.answer_from_graph("q", hooks, graph, comments,
                                         db_path=db, document=document, ask=ask)
        assert out["route"] == "rag" and out["values"] == []
        return out["reason"]

    assert reason("nirgends", said) == "no_plan"
    assert reason(None, said) == "no_plan"
    assert reason(DOCUMENT, asking()) == "no_coordinates"
    assert reason(DOCUMENT, asking(parameter="Energieverbrauch",
                                   carrier="Erdgas")) == "no_coordinates"
    assert reason(DOCUMENT, asking(parameter="Energieverbrauch",
                                   year="1999")) == "no_rows"


def test_the_kg_history_entry_does_not_trip_the_comparison_render(
        graph_fixture, hooks):
    """app.py dispatches a history entry carrying `rows` into the comparison
    render, so the route's dict must never have that key."""
    db, _ttl, graph, comments = graph_fixture
    for ask in (asking(parameter="Energieverbrauch", scenario="Zielszenario"),
                asking()):
        outcome = kg_route.answer_from_graph("q", hooks, graph, comments,
                                             db_path=db, document=DOCUMENT,
                                             ask=ask)
        assert set(outcome) == {"route", "reason", "values", "coordinates"}


def test_every_fallback_reason_has_a_sentence():
    assert kg_route.check_notes(inference.ROUTE_NOTES, "x") is \
        inference.ROUTE_NOTES
    short = dict(inference.ROUTE_NOTES)
    short.pop("no_rows")
    with pytest.raises(LookupError):
        kg_route.check_notes(short, "x")
    with pytest.raises(LookupError):
        kg_route.check_notes(dict(inference.ROUTE_NOTES, no_luck="…"), "x")


def test_the_route_is_absent_where_the_profile_has_no_kg_query(hooks):
    assert kg_route.hooks(load_profile("scenarios")) is None
    assert kg_route.hooks(None) is None
    assert hooks.query == kg.VALUE_QUERY
    assert hooks.axes == kg.COORDINATE_AXES
    assert hooks.prompt.id == kg_route.COORDINATE_PROMPT_ID
    assert hooks.notes is inference.ROUTE_NOTES
    assert hooks.label("OEO_00000292") == "Erdgas"


def test_no_oeo_class_is_both_a_carrier_and_a_sector():
    """The display splits `?abouts` by which spec list an IRI is in, so an
    overlap would show a value under the wrong axis."""
    for parameter in SPEC.parameters:
        if not parameter.is_numeric:
            continue
        carriers = {u for u in parameter.axes["carrier"].vocabulary
                    if kg.is_class(u)}
        sectors = {u for u in parameter.axes["sector"].vocabulary
                   if kg.is_class(u)}
        assert carriers and sectors
        assert not carriers & sectors, parameter.uri


def test_the_graph_loads_from_the_file_the_serializer_wrote(graph_fixture,
                                                            tmp_path):
    _db, ttl, graph, comments = graph_fixture
    path = tmp_path / "mhpkg.ttl"
    path.write_text(ttl, encoding="utf-8")
    loaded, loaded_comments = kg_route.load_graph(path)
    assert len(loaded) == len(graph) and loaded_comments == comments


# --- the one closed question to the model ------------------------------------

def test_choose_returns_a_key_of_the_list_or_nothing(monkeypatch, hooks):
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    calls = []

    def fake(messages, temperature):
        calls.append((messages, temperature))
        return {"answer": "Fernwärme"}

    monkeypatch.setattr(llm_client, "_chat_json", fake)
    assert llm_client.choose(hooks.prompt, "q", "f?", {"Fernwärme": []}) == \
        "Fernwärme"
    assert llm_client.choose(hooks.prompt, "q", "f?", {"Erdgas": []}) is None
    messages, temperature = calls[0]
    assert messages[0] == {"role": "system", "content": hooks.prompt.text}
    payload = json.loads(messages[1]["content"])
    assert payload == {"task": "q", "question": "f?", "options": {"Fernwärme": []}}
    assert temperature == 0
    monkeypatch.setattr(llm_client, "_chat_json",
                        lambda messages, temperature: {"answer": 2030})
    assert llm_client.choose(hooks.prompt, "q", "Jahr?", {}) == "2030"
    monkeypatch.setattr(llm_client, "_chat_json",
                        lambda messages, temperature: {"antwort": "x"})
    assert llm_client.choose(hooks.prompt, "q", "f?", {"x": []}) is None


def test_choose_asks_nothing_in_stub_mode(monkeypatch, hooks):
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", True)
    monkeypatch.setattr(llm_client, "_chat_json",
                        lambda *a, **k: pytest.fail("the endpoint was called"))
    assert llm_client.choose(hooks.prompt, "q", "f?", {"x": []}) is None
