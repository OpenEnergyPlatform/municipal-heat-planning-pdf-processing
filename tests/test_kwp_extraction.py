"""The kwp extraction profile: spec, prompts, and the MHPKG serializer."""
import logging
import re
import sqlite3

import pytest

from docpipe.extraction.queries import expand
from docpipe.extraction.spec import load
from docpipe.extraction.verify import Verified, verify_tuple
from docpipe.profile import load_profile
from profiles.kwp import kg
from profiles.kwp.extraction import SPEC_PATH

SPEC = load(SPEC_PATH)
UUID5 = r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


# --- spec ------------------------------------------------------------------

NUMERIC = [p for p in SPEC.parameters if p.is_numeric]


def test_the_class_is_the_models_choice_not_a_table_of_german_spellings():
    """Two parameters, split by unit family, and inside each the model picks
    the OEO class from the list with the ontology's definitions in front of it.
    Mirjam's three classes are in there, plus the one a BISKO balance actually
    reports: OEO_00340066 is CO2 alone, while the plans overwhelmingly print
    Treibhausgase in CO2 equivalents, which OEO has as OEO_00140083."""
    assert [p.uri for p in SPEC.parameters] == [
        "energy_consumption", "emission", "planning_organisation"]
    classes = {uri for p in NUMERIC for uri in p.axes["quantity"].vocabulary}
    assert {c for c in classes if not c.startswith("out:")} == {
        "OEO_00050016", "OEO_00050018", "OEO_00340066", "OEO_00140083"}
    # The list also names what the graph does NOT take, as choices rather than
    # prose. Without them the model picks the nearest class anyway: the first
    # run put Kassel's "CO2-Abscheidung" in as a CO2 emission and Bremen's
    # cumulative twenty-year sum beside its annual values.
    for needed in ("out:cumulative", "out:avoided", "out:captured"):
        assert needed in classes, needed
    for needed in ("out:potential", "out:generation", "out:share"):
        assert needed in classes, needed
    for parameter in NUMERIC:
        assert not parameter.axes["quantity"].required,             "a number that fits no class keeps its wording and is counted"


def example_tuples(parameter):
    """The example's tuples as the model is asked to write them back.

    The spec writes the coordinates that every tuple in the example shares
    once, under `defaults`, because that is the contract the prompt teaches —
    ten of a tuple's fifteen keys are identical down a table's column and
    rewriting them is half the answer. Everything downstream sees whole
    tuples, so the tests do here what the runner does on the wire.
    """
    from docpipe.extraction.runner import expand_defaults
    return expand_defaults(parameter.example.get("defaults"),
                           parameter.example["tuples"])


@pytest.mark.parametrize("parameter", SPEC.parameters, ids=lambda p: p.uri)
def test_every_example_verifies_against_its_own_source(parameter):
    """The example doubles as the golden test: a spec whose own few-shot
    would be refused by verify_tuple teaches the model a refusable habit."""
    for raw in example_tuples(parameter):
        outcome = verify_tuple(dict(raw), parameter, parameter.example["source"])
        assert isinstance(outcome, Verified), getattr(outcome, "reason", outcome)


@pytest.mark.parametrize("parameter", NUMERIC, ids=lambda p: p.uri)
def test_the_examples_teach_exhaustive_extraction(parameter):
    """Every value cell in the example source has its tuple — a few-shot
    that extracts a subset teaches the model to under-harvest, and off-
    vocabulary columns are the lesson, not the exception."""
    import re as re_mod
    from docpipe.extraction.verify import canonical_number
    claimed = {canonical_number(t["value"]) for t in example_tuples(parameter)}
    quoted_rows = {t["quote"] for t in example_tuples(parameter)}
    for row in quoted_rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        for cell in cells[1:]:
            if re_mod.fullmatch(r"[\d.,]+", cell):
                assert canonical_number(cell) in claimed, f"{cell} has no tuple"
    outcomes = [verify_tuple(dict(t), parameter, parameter.example["source"])
                for t in example_tuples(parameter)]
    flags = [f for o in outcomes for f in o.flags]
    assert flags, "the example must exercise the wording machinery at all"


def test_the_examples_show_both_mapping_and_refusing_to_map():
    """The two lessons the few-shot has to teach at once: a wording the class
    list does not contain still gets mapped when it clearly fits, and a label
    that fits no class stays empty instead of being forced into one."""
    flags = [f for parameter in SPEC.parameters
             for t in example_tuples(parameter)
             for f in verify_tuple(dict(t), parameter,
                                   parameter.example["source"]).flags]
    assert any(f.startswith("mapped:") for f in flags)
    assert any(f.startswith("unmapped:") for f in flags)


# --- prompts ---------------------------------------------------------------

def _profile():
    return load_profile("kwp")


def test_query_templates_expand_for_every_parameter():
    from docpipe import prompts
    prompt = prompts.load("extraction/queries", _profile())
    templates = [line for line in prompt.text.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
    assert templates
    for parameter in SPEC.parameters:
        probes = expand(templates, parameter)
        if parameter.is_numeric:
            assert len(probes) > len(templates), "the carrier axis must fan out"
        assert len(set(probes)) == len(probes)
        assert not any("{" in p for p in probes)


def test_the_harvest_prompt_states_the_contract():
    from docpipe import prompts
    prompt = prompts.load("extraction/harvest", _profile())
    assert prompt.meta.get("max_tokens")
    for needle in ('"tuples"', '"quote"', '"unit_raw"', '"quantity"',
                   '"carrier_raw"', 'classes'):
        assert needle in prompt.text, f"prompt never names {needle}"


# --- IRI minting against the published reference ---------------------------

def test_value_minting_matches_the_schema_repo_reference():
    """mint_slice.py's exact coordinate string must yield its exact UUID —
    proves the whole uuid5 chain, namespace derivation included. Their
    kassel_valid.ttl carries a878a3a1-… instead, which mint_slice.py cannot
    produce from any plausible coordinate variant: a stale hand-typed UUID
    on the schema side, reported, not reproduced."""
    heatplan = f"{kg.BASE}heatplan/AGS_06611000_2024-03-15"
    coordinates = "|".join([heatplan, f"{kg.OEO}OEO_00050016",
                            f"{kg.OEO}OEO_00000292", "2030",
                            f"{kg.OEO}OEO_00140070"])
    assert kg.mint("value", coordinates).endswith(
        "78153046-c4c2-5cae-a61c-56c70e57e5a5")


def test_normalise_and_organisation_minting_match_the_reference():
    for label in ("Kassel Wärme Ingenieurbüro",
                  "  kassel   wärme  ingenieurbüro  ",
                  "Kassel Wärme Ingenieurbüro GmbH"):
        assert kg.mint("organisation", kg.normalise(label)).endswith(
            "2d4f4ae8-ea0f-575c-9a76-8dcf377042af"), label
    stripped = kg.mint("organisation", kg.normalise("Kassel Warme Ingenieurburo"))
    assert not stripped.endswith("2d4f4ae8-ea0f-575c-9a76-8dcf377042af")


# --- serializer -------------------------------------------------------------

def _database(tmp_path):
    db = tmp_path / "kwp.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                published TEXT, is_current INTEGER,
                                page_text_transcribed INTEGER);
        CREATE TABLE DocumentMeta (document INTEGER, municipality_ags TEXT);
        CREATE TABLE Municipalities (ags TEXT, name TEXT);
        INSERT INTO Documents VALUES (857, 'waermeplan_kassel_20240315.pdf',
                                      '2024-03-15', 1, 0);
        INSERT INTO DocumentMeta VALUES (857, '06611000');
        INSERT INTO Documents VALUES (858, 'waermeplan_kassel_alt.pdf',
                                      '2024-03-15', 0, 0);
        INSERT INTO DocumentMeta VALUES (858, '06611000');
        -- A plan with no PDF text layer: every page read by a model.
        INSERT INTO Documents VALUES (1082, 'waermeplan_ohne_textebene.pdf',
                                      '2025-09-01', 1, 96);
        INSERT INTO DocumentMeta VALUES (1082, '13074053');
        INSERT INTO Municipalities VALUES ('06611000', 'Kassel');
        INSERT INTO Municipalities VALUES ('13074053', 'Grevesmühlen');
    """)
    conn.commit()
    conn.close()
    return db


def _row(**overrides):
    row = {"kind": "tuple", "parameter": "energy_consumption", "value": 241000,
           "value_target": 241.0, "unit_raw": "kWh/a",
           "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
           "carrier": "OEO_00000292", "sector": None, "year": 2030,
           # Explicit, because it used to be absent and a default filled it:
           # every row of every test here was written into the graph as an
           # annual sum without one line saying so.
           "aggregation": "OEO_00140070", "aggregation_state": "derived",
           "aggregation_raw": "kWh/a",
           "scenario": "target", "spatial_scope": "municipality",
           "tier": "visual_source", "provenance": {"document_id": 857}}
    row.update(overrides)
    return row


def test_every_plan_part_the_ontology_names_is_serialized(tmp_path):
    """A plan has more parts than its target scenario, and only that one was
    ever written. Everything else the harvest read was collected, verified
    and dropped at the gate: on Kassel 45 tuples for the scenario alone, 25
    of them a stock take the law asks for in WPG paragraph 15.
    """
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(),
        _row(scenario="status_quo", year=2022),
        _row(scenario="trend", year=2035),
        _row(spatial_scope="sub_area"),
        _row(quantity=None, quantity_raw="Endenergiebedarf"),
        _row(year=None),
    ])
    assert f"<{kg.BASE}heatplan/AGS_06611000_2024-03-15>" in ttl
    assert re.search(rf"{kg.BASE}value/{UUID5}", ttl)
    assert ttl.count("a oeo:OEO_00050016") == 3, "target, inventory and trend"
    assert "Kommunale Wärmeplanung Kassel 2024" in ttl

    # One node per part that really has a value, with the class the ontology
    # gives it, and one has-part edge from the plan to each.
    for segment, cls, label in (
            ("targetscenario", "mhpo:MHPO_00020007", "Zielszenario"),
            ("inventory", "mhpo:MHPO_00020005", "Bestandsanalyse"),
            ("referencescenario", "oeo:OEO_00020314", "Trendszenario")):
        iri = f"{kg.BASE}{segment}/AGS_06611000_2024-03-15"
        assert f"<{iri}>" in ttl, segment
        assert f"a {cls} ;" in ttl, cls
        assert f'"{label} Kassel 2024"' in ttl
        assert ttl.count(f"<{iri}>") == 2, "named as a part and as a node"

    # And a value of one part is not a value of another: the same coordinates
    # under two scenarios are two nodes, which is what the conflict guard
    # would otherwise drop as one contested identity.
    values = set(re.findall(rf"{kg.BASE}value/({UUID5})", ttl))
    assert len(values) == 3


def test_a_part_with_no_value_is_neither_a_node_nor_a_has_part_edge(tmp_path):
    """The plan does not stop having an inventory because we could not read
    one. The graph must not say we read it."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [_row()])
    assert "inventory/AGS_06611000" not in ttl
    assert "referencescenario/AGS_06611000" not in ttl
    assert ttl.count("targetscenario/AGS_06611000_2024-03-15") == 2


def test_a_row_whose_scenario_stayed_unread_is_counted_not_guessed(tmp_path,
                                                                   caplog):
    """Two different findings that used to be one number: a scenario the
    graph has no node for, and a scenario nobody read. The second is a
    coordinate the sweep never closed, and it is the sweep that answers."""
    serializer = kg.make_serializer(_database(tmp_path))
    with caplog.at_level(logging.INFO, logger="profiles.kwp.kg"):
        serializer("waermeplan_kassel_20240315", [
            _row(), _row(scenario=None), _row(scenario="out:variant")])
    line = next(r.getMessage() for r in caplog.records if "skipped" in
                r.getMessage())
    assert "scenario_unread': 1" in line
    assert "scenario:out:variant': 1" in line


def test_a_carrier_oeo_does_not_call_a_carrier_loses_its_edge_not_its_value(tmp_path):
    """`covers energy carrier` has range `energy carrier`, and district heating
    is a heat transfer, not one. So the edge is left out — but the value is a
    properly evidenced consumption with its year, unit, sector and
    aggregation, and dropping the whole row over one relation the TBox does
    not allow yet cost 51 of 244 value nodes in the pilot."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(carrier="OEO_00000132"),          # Fernwärme
        _row(carrier="OEO_00000139", value_target=5.0),   # Strom
        _row(),                                # Erdgas, a carrier OEO allows
    ])
    assert ttl.count("a oeo:OEO_00050016") == 3, "every value stands"
    assert ttl.count("oeo:OEO_00000523") == 1, "only Erdgas may claim a carrier"
    assert "oeo:OEO_00000523 oeo:OEO_00000132" not in ttl
    assert "oeo:OEO_00000523 oeo:OEO_00000139" not in ttl


def test_a_value_conflict_on_one_coordinate_drops_every_claimant(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(), _row(value_target=242.0), _row(),
        _row(sector="OEO_00000214", value_target=99.0),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 1, "only the sectored value survives"
    assert '"99.0"^^xsd:float' in ttl and '"241.0"' not in ttl


def test_documents_without_serializable_tuples_or_identity_yield_none(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    # A scenario the graph has no node for is still nothing to serialize.
    assert serializer("waermeplan_kassel_20240315",
                      [_row(scenario="out:variant")]) is None
    assert serializer("unknown_plan", [_row()]) is None


def test_a_second_document_claiming_the_same_identity_is_refused(tmp_path):
    """A stale duplicate harvest (register-link rename) mints the same value
    IRIs; merging it would put two magnitudes on one node."""
    serializer = kg.make_serializer(_database(tmp_path))
    assert serializer("waermeplan_kassel_20240315", [_row()]) is not None
    assert serializer("waermeplan_kassel_alt",
                      [_row(value_target=999.0,
                            provenance={"document_id": 858})]) is None


def test_the_prefix_block_is_emitted_once_per_run(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    first = serializer("waermeplan_kassel_20240315", [_row()])
    second = serializer("waermeplan_kassel_20240315", [_row()])
    assert first.startswith("@prefix rdfs:")
    assert "@prefix" not in second


# --- the date the corpus actually stores -------------------------------------

def _database_corpus_format(tmp_path):
    """Like _database, but with `published` as INGEST writes it: YYYYMMDD.

    The fixture above writes the dashed form, which no row of the real corpus
    has. That divergence let the serializer pass its tests while producing an
    empty graph for all 1079 documents.
    """
    db = tmp_path / "kwp_corpus.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                published TEXT, is_current INTEGER);
        CREATE TABLE DocumentMeta (document INTEGER, municipality_ags TEXT);
        CREATE TABLE Municipalities (ags TEXT, name TEXT);
        INSERT INTO Documents VALUES (857, 'waermeplan_kassel_20240315.pdf',
                                      '20240315', 1);
        INSERT INTO DocumentMeta VALUES (857, '06611000');
        INSERT INTO Municipalities VALUES ('06611000', 'Kassel');
    """)
    conn.commit()
    conn.close()
    return db


def test_the_corpus_date_format_serializes_at_all(tmp_path):
    serializer = kg.make_serializer(_database_corpus_format(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [_row()])
    assert ttl, "an empty graph is what the whole corpus produced"
    assert "06611000" in ttl


def test_both_date_spellings_mint_the_same_iris(tmp_path):
    """The dashed form is what mint_slice.py was verified against, so the
    conversion must land on it exactly — a different spelling would mint a
    different heat plan and quietly fork the graph."""
    dashed = kg.make_serializer(_database(tmp_path))(
        "waermeplan_kassel_20240315", [_row()])
    plain = kg.make_serializer(_database_corpus_format(tmp_path))(
        "waermeplan_kassel_20240315", [_row()])
    assert plain == dashed


def test_the_date_converter_takes_both_and_refuses_neither_silently():
    assert kg._iso_date("20240315") == "2024-03-15"
    assert kg._iso_date("2024-03-15") == "2024-03-15"
    assert kg._iso_date("2024-03-15T00:00:00") == "2024-03-15"
    assert kg._iso_date(None) == ""
    assert kg._iso_date("Fruehjahr") == "Fruehjahr", "left for the guard to reject"


# --- the acceptance test: is the output kassel_valid.ttl? -------------------

# https://github.com/OpenEnergyPlatform/oekg/blob/production/mhpkg/schema/
#   examples/kassel_valid.ttl — the shape one heat plan has to come out as.
# Its own value IRI is left out of the comparison: that node is hand-typed
# upstream (a878a3a1-…), and mint_slice.py's coordinate string yields
# 78153046-… instead, which the minting test above pins.
KASSEL_VALID = """
heatplan/AGS_06611000_2024-03-15 | a | mhpo:MHPO_00020003
heatplan/AGS_06611000_2024-03-15 | rdfs:label | "Kommunale Wärmeplanung Kassel 2024"
heatplan/AGS_06611000_2024-03-15 | oeo:OEO_00390096 | "2024-03-15"^^xsd:date
heatplan/AGS_06611000_2024-03-15 | oeo:OEO_00000510 | organisation/2d4f4ae8-ea0f-575c-9a76-8dcf377042af
heatplan/AGS_06611000_2024-03-15 | obo:BFO_0000051 | targetscenario/AGS_06611000_2024-03-15
targetscenario/AGS_06611000_2024-03-15 | a | mhpo:MHPO_00020007
targetscenario/AGS_06611000_2024-03-15 | rdfs:label | "Zielszenario Kassel 2024"
VALUE | a | oeo:OEO_00050016
VALUE | oeo:OEO_00140178 | "241.0"^^xsd:float
VALUE | oeo:OEO_00040010 | oeo:OEO_00050008
VALUE | oeo:OEO_00000523 | oeo:OEO_00000292
VALUE | oeo:OEO_00000505 | oeo:OEO_00000214
VALUE | oeo:OEO_00020440 | "2030"^^xsd:integer
VALUE | oeo:OEO_00390023 | oeo:OEO_00140070
organisation/2d4f4ae8-ea0f-575c-9a76-8dcf377042af | a | oeo:OEO_00030022
organisation/2d4f4ae8-ea0f-575c-9a76-8dcf377042af | rdfs:label | "Kassel Wärme Ingenieurbüro"
municipality/AGS_06611000 | a | mhpo:MHPO_00020017
municipality/AGS_06611000 | rdfs:label | "Gemeindegebiet Kassel"
"""


def _triples(ttl: str) -> set:
    """Turtle to a set of `subject | predicate | object`, IRIs shortened.

    A small subset is enough here: no blank nodes, no nesting, `;` and `,` as
    the only abbreviations.
    """
    body = re.sub(r"(?m)^\s*(#.*|@prefix.*)$", "", ttl)
    out = set()
    for statement in body.split(" .\n"):
        statement = statement.strip().rstrip(".").strip()
        if not statement:
            continue
        subject, _, rest = statement.partition("\n")
        subject = _short(subject.strip())
        for clause in rest.split(";"):
            clause = clause.strip()
            if not clause:
                continue
            predicate, _, objects = clause.partition(" ")
            for obj in objects.split(","):
                out.add(f"{subject} | {predicate.strip()} | "
                        f"{_short(obj.strip())}")
    return out


def _short(term: str) -> str:
    term = term.strip().strip("<>")
    if term.startswith(kg.BASE):
        rest = term[len(kg.BASE):]
        return "VALUE" if rest.startswith("value/") else rest
    return term


# The plan behind the published example: one energy value and the office
# that wrote it. Module level, so the schema test can serialize the same
# plan instead of keeping a second copy of it.
KASSEL_ROWS = [
    {"kind": "tuple", "parameter": "energy_consumption",
     "value": 241.0, "value_target": 241.0, "unit_raw": "MWh",
     "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
     "carrier": "OEO_00000292", "sector": "OEO_00000214", "year": 2030,
     # The example carries `has aggregation type integral` and the
     # serializer no longer invents it: a value whose aggregation nothing
     # decided is counted, not written down as a year's sum.
     "aggregation": "OEO_00140070", "aggregation_state": "derived",
     "aggregation_raw": "MWh",
     "scenario": "target", "spatial_scope": "municipality",
     "provenance": {"document_id": 857}},
    {"kind": "tuple", "parameter": "planning_organisation",
     "value": "Kassel Wärme Ingenieurbüro GmbH",
     "quote": "Auftragnehmer: Kassel Wärme Ingenieurbüro GmbH",
     "provenance": {"document_id": 857}},
]


def one_plan_turtle(tmp_path):
    """The Turtle the serializer writes for the published example."""
    return kg.make_serializer(_database(tmp_path))(
        "waermeplan_kassel_20240315", KASSEL_ROWS)


def test_one_heat_plan_comes_out_as_the_published_example(tmp_path):
    """The whole point of the pilot, as one assertion: feed the serializer what
    Kassel's plan says and the output is the schema repo's kassel_valid.ttl —
    every node, every predicate, both directions."""
    ttl = one_plan_turtle(tmp_path)
    ours = _triples(ttl)
    # The value node's IRI is ours to mint, so its identity is compared as
    # VALUE; that the scenario points at it is asserted separately.
    ours = {t for t in ours
            if not t.startswith("targetscenario/AGS_06611000_2024-03-15 | "
                                "oeo:OEO_00140002")}
    theirs = {line.strip() for line in KASSEL_VALID.strip().splitlines()}
    assert ours == theirs, (
        f"\nfehlt : {sorted(theirs - ours)}\nzuviel: {sorted(ours - theirs)}")
    assert re.search(rf"oeo:OEO_00140002 <{kg.BASE}value/{UUID5}>", ttl)


# --- what the model chooses, and what the graph does with it ---------------

def test_a_captured_or_cumulative_amount_is_a_choice_not_a_class(tmp_path):
    """The two failures of the first run, as one test. Both are real readings
    with real quotes, and neither is an emission the plan causes."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(quantity="out:captured", quantity_raw="CO₂-Abscheidung",
             value=95000, value_target=95000.0),
        _row(quantity="out:cumulative", quantity_raw="Kumulierte THG-Emissionen",
             value=12400000, value_target=12400000.0),
        _row(),
    ])
    assert ttl.count("mhpkg/value/") == 2, "one value node, referenced twice"
    assert "95000" not in ttl and "12400000" not in ttl


def test_the_aggregation_is_the_models_choice(tmp_path):
    """OEO has five aggregation types and the serializer used to assert
    `integral` for all of them, so a peak load went in as an annual sum."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(aggregation="OEO_00140073", quantity_raw="Spitzenlast"),
    ])
    assert "oeo:OEO_00390023 oeo:OEO_00140073" in ttl


def test_two_sub_areas_are_two_values_not_one(tmp_path):
    """One plan carries four gas tables, one per heat-network area, all at the
    same carrier and year. Without the area in the coordinates they collide
    onto one node and the conflict guard drops every one of them."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(spatial_scope="sub_area", spatial_scope_raw="Quartier Nordstadt",
             value=64000, value_target=64000.0),
        _row(spatial_scope="sub_area", spatial_scope_raw="Quartier Süd",
             value=9100, value_target=9100.0),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 2
    assert '"64000.0"^^xsd:float' in ttl and '"9100.0"^^xsd:float' in ttl
    assert ttl.count(f"a mhpo:{kg.CLS_PLAN_AREA}") == 2
    assert "Quartier Nordstadt" in ttl and "Quartier Süd" in ttl
    assert f"obo:{kg.P_PART_OF} <{kg.BASE}municipality/AGS_06611000>" in ttl


def test_an_unnamed_sub_area_is_counted_out(tmp_path):
    """Two unnamed sub-areas are one node and one of them is silently lost."""
    serializer = kg.make_serializer(_database(tmp_path))
    assert serializer("waermeplan_kassel_20240315", [
        _row(spatial_scope="sub_area", spatial_scope_raw=None)]) is None


def test_every_value_carries_where_it_was_read(tmp_path):
    """The prototype's evidence: a comment, because the shapes are sh:closed
    and an extra triple on a value node invalidates it."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(quote="| Erdgas | 241 |",
             provenance={"document_id": 857, "page": 84, "owner_kind": "table",
                         "title": "Endenergie im Zielszenario"}),
    ])
    assert "# Endenergieverbrauch" in ttl
    assert "„| Erdgas | 241 |“" in ttl
    assert "Seite 84" in ttl and "Tabelle" in ttl


def test_the_unit_is_chosen_from_the_list_and_the_wording_is_evidence():
    """units_accepted is a closed list, so the unit is a choice. The
    document's spelling rides along as evidence and is never looked up."""
    from docpipe.extraction.verify import verify_tuple, Verified

    parameter = {p.uri: p for p in SPEC.parameters}["emission"]
    source = "Die Emissionen sinken bis 2045 auf 4.041 t CO₂ eq/a."
    out = verify_tuple({"value": 4041, "unit": "t CO2eq/a",
                        "unit_raw": "t CO₂ eq/a",
                        "quantity": "carbon dioxide equivalent quantity value",
                        "quantity_raw": "Emissionen", "aggregation": "integral",
                        "year": 2045, "scenario": "Zielszenario",
                        "spatial_scope": "Gemeindegebiet",
                        "quote": source}, parameter, source)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["unit"] == "t CO2eq/a"
    assert out.tuple["unit_raw"] == "t CO₂ eq/a"
    assert out.tuple["value_target"] == 4041.0
    assert out.tuple["scenario"] == "target"
    assert out.tuple["spatial_scope"] == "municipality"


def test_a_deliberate_non_class_never_becomes_an_oeo_iri(tmp_path):
    """The axes hold entries that say what a row IS when no class fits — a
    sum, a residual, a sector the source calls unknown. Written as
    `oeo:out:total` they mint an IRI that does not exist, and a corpus run
    put those into 2.2 MB of graph before anyone looked."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(sector="out:total", value_target=1.0),
        _row(sector="unknown", value_target=2.0),
        _row(carrier="out:other", value_target=3.0),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 3, "the values themselves stand"
    for bad in ("oeo:out:total", "oeo:unknown", "oeo:out:other"):
        assert bad not in ttl, f"{bad} is not a class"
    assert "OEO_00000505" not in ttl, "no sector edge for a non-class"


# The axes kg.py turns into edges. scenario and spatial_scope are read as
# filters and never written, so their keys are free-form.
EDGE_AXES = ("carrier", "sector", "aggregation")


def test_every_entry_that_becomes_an_edge_is_a_class_or_is_left_out():
    """A vocabulary key on an edge axis is either a real OEO class or one
    kg.py leaves out. An entry that is neither gets serialized as an invented
    IRI, which is exactly how `oeo:out:total` reached 2.2 MB of graph."""
    for parameter in SPEC.parameters:
        for name in EDGE_AXES:
            axis = parameter.axes.get(name)
            for uri in ((axis.vocabulary if axis else None) or {}):
                marked = uri.startswith(kg.NOT_IN_GRAPH) or uri == "unknown"
                assert kg.is_class(uri) or marked, (
                    f"{parameter.uri}.{name}: {uri!r} is neither a class nor "
                    f"a marked non-class, so it would be written as one")


def test_one_fact_said_twice_about_the_plan_area_is_one_node(tmp_path):
    """The promise: two passages stating the same figure for the whole plan
    area are one node, and two named sub-areas stay two.

    Bad Segeberg states its 2,272 t of 2040 on pages 71, 72 and 73 and calls
    the place "Waermesektor", "Projektgebiet" and "Stadtgebiet". With the
    wording in the coordinate those became three indistinguishable nodes, and
    129 of 1,294 nodes over twenty plans were repeats of that shape.

    The other clause, that two named sub-areas stay two nodes, is held by
    test_two_sub_areas_are_two_values_not_one."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(spatial_scope_raw="Stadtgebiet", quote="241 MWh im Stadtgebiet"),
        _row(spatial_scope_raw="Projektgebiet", quote="241 MWh im Projektgebiet"),
        _row(spatial_scope_raw="gesamte Stadt", quote="insgesamt 241 MWh"),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 1, (
        "three wordings for one place are one place")
    assert ttl.count('"241.0"^^xsd:float') == 1


def test_a_real_contradiction_about_the_plan_area_is_still_dropped(tmp_path):
    """Merging must not turn a contradiction into a coin toss. Same place,
    same coordinate, two magnitudes: still a human question."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(spatial_scope_raw="Stadtgebiet", value_target=241.0),
        _row(spatial_scope_raw="Projektgebiet", value_target=999.0),
        _row(sector="OEO_00000214", value_target=5.0),
    ])
    assert '"241.0"' not in ttl and '"999.0"' not in ttl, (
        "one place cannot hold two different numbers for one coordinate")
    assert '"5.0"^^xsd:float' in ttl, "and the untouched value survives"


def test_a_conflict_counts_every_claimant_and_a_repeat_counts_as_one(tmp_path, caplog):
    """The promise: the conflict count is the number of tuples that left the
    graph, and a second reading of the same number is counted as a repeat.

    Counting only the later claimant made every report short by one per
    contested identity. Measured over Kassel: the log said 217 where 317
    tuples were lost across 100 identities, so every estimate built on it was
    optimistic by exactly those 100.
    """
    serializer = kg.make_serializer(_database(tmp_path))
    with caplog.at_level(logging.INFO, logger="profiles.kwp.kg"):
        ttl = serializer("waermeplan_kassel_20240315", [
            _row(), _row(), _row(value_target=242.0)])
    assert ttl is None, "a contested identity keeps nothing"
    line = " ".join(r.getMessage() for r in caplog.records)
    assert "'conflict': 2" in line, "both claimants, not just the second"
    assert "'duplicate': 1" in line, "and the repeat is not swallowed"


def test_a_repeat_alone_still_serializes_one_node(tmp_path, caplog):
    """The other half: two passages that agree are one node and no loss."""
    serializer = kg.make_serializer(_database(tmp_path))
    with caplog.at_level(logging.INFO, logger="profiles.kwp.kg"):
        ttl = serializer("waermeplan_kassel_20240315", [_row(), _row()])
    assert ttl.count("a oeo:OEO_00050016") == 1
    line = " ".join(r.getMessage() for r in caplog.records)
    assert "'conflict'" not in line
    assert "'duplicate': 1" in line


def test_the_units_of_the_two_numeric_parameters_share_no_spelling():
    """The promise the derivation rests on: no unit belongs to two numeric
    parameters, so the unit alone says which parameter a row is.

    The spec says it in prose ("the unit separates the two parameters") and
    nothing held it to it. If it stopped being true the derivation would pick
    the first parameter silently, which is the guess-written-down-as-a-reading
    this stage exists to prevent. Nine energy spellings against forty-two
    emission spellings today, no overlap.
    """
    from docpipe.extraction import fields
    numeric = [p for p in SPEC.parameters if p.is_numeric]
    assert len(numeric) >= 2
    for i, first in enumerate(numeric):
        for second in numeric[i + 1:]:
            shared = {u for u in first.units_accepted
                      if second.unit_factor(u) is not None}
            assert not shared, (
                f"{first.label} and {second.label} share {sorted(shared)}, so "
                f"the unit no longer settles the parameter")
    for parameter in numeric:
        for unit in parameter.units_accepted:
            got = fields.derive_parameter(SPEC, {"value": 1, "unit": unit})
            assert got is parameter, f"{unit!r} did not settle on {parameter.label}"


def test_a_value_whose_aggregation_nothing_decided_is_counted_not_summed(
        tmp_path, caplog):
    """The promise: no node without an aggregation, and the evidence says how
    the aggregation was arrived at.

    `row.get("aggregation") or AGGREGATION_INTEGRAL` wrote a year's sum for
    every row that carried none, which is a claim about the value that nothing
    in the document made: a peak load written down as an annual total is wrong
    in a way no reader of the graph can see. It never showed in a test because
    the test helper never omitted the key.
    """
    serializer = kg.make_serializer(_database(tmp_path))
    row = _row()
    row.pop("aggregation")
    row.pop("aggregation_state")
    with caplog.at_level(logging.INFO, logger="profiles.kwp.kg"):
        assert serializer("waermeplan_kassel_20240315", [row]) is None
    assert "'aggregation_missing': 1" in " ".join(
        r.getMessage() for r in caplog.records)


def test_the_evidence_says_whether_the_aggregation_was_read_or_derived(tmp_path):
    """Derived is not a weaker reading than read, it is a different one, and a
    reader of the graph has to be able to tell them apart."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [_row()])
    assert "# Aggregation: OEO_00140070 (aus der Einheit kWh/a)" in ttl

    second = tmp_path / "second"
    second.mkdir()
    ttl = kg.make_serializer(_database(second))(
        "waermeplan_kassel_20240315",
        [_row(aggregation="OEO_00140073", aggregation_state="read",
              aggregation_raw="Spitzenlast")])
    assert "# Aggregation: OEO_00140073 „Spitzenlast“" in ttl
    assert "aus der Einheit" not in ttl


# --- the questions, after the Kassel read-through --------------------------

def test_the_two_quantity_questions_are_not_the_same_text():
    """The emission question was a copy of the energy one, down to the
    sentence about Nutzwaerme. So the decision between CO2 and CO2eq -- the
    only thing that question has to settle -- was made on a text about heat
    demand: Kassel came back with 193 tuples as CO2 and 1 as CO2eq, in a plan
    whose own methods sentence says every figure is in CO2 equivalents."""
    energy, emission = SPEC.parameters[0], SPEC.parameters[1]
    energy_q = energy.axes["quantity"].question
    emission_q = emission.axes["quantity"].question
    assert energy_q != emission_q
    assert "Nutzwärme" in energy_q and "Nutzwärme" not in emission_q
    assert "CO2-Äquivalenten" in emission_q
    assert "Methodiksatz schlägt die Kopfzeile" in emission_q
    # And the energy question states the definition the ontology gives, not a
    # German word list: demand and consumption are the same class.
    assert "an Endverbraucher gelieferte" in energy_q
    assert "Endenergiebedarf" in energy_q and "Wärmebedarf" in energy_q


def test_a_region_is_not_a_sector_and_a_table_without_one_says_so():
    """Measured on Kassel table 17: 39 rows answered "out:total" with the
    wording "Gesamtstadt", which is where the value stands and not what
    consumes it. Five contested identities and four wrong nodes came of it,
    and 39 more tuples took the header of a NEIGHBOURING table."""
    for parameter in NUMERIC:
        question = parameter.axes["sector"].question
        assert "GEBIET ist kein Sektor" in question
        for word in ("Gesamtstadt", "Stadtgebiet", "Plangebiet"):
            assert word in question, word
        assert "keine Sektorspalte" in question
        assert "out:unstated" in question
        # The aliases the corpus writes and the list did not hold.
        table = parameter.axes["sector"].label_to_uri()
        assert table["wohnen"] == "OEO_00000214"
        assert table["wohngebäude"] == "OEO_00000214"
        assert table["ghd/kommune"] == "OEO_00000405"
        assert table["wirtschaftlich genutzte gebäude"] == "OEO_00000405"


def test_gesamtstadt_is_not_a_wording_for_the_sum_over_sectors():
    """The same finding where the code can see it: "Gesamtstadt" names no
    spelling of out:total, so a row answered out:total on that wording is
    counted instead of passing as if the table had said Summe."""
    from docpipe.extraction import fields
    from docpipe.extraction.pipeline import wording_names_option
    slot = next(s for s in fields.axis_slots(SPEC.parameters[0])
                if s.name == "sector")
    assert not wording_names_option(slot, "Summe", "Gesamtstadt")
    assert not wording_names_option(slot, "Summe", "Stadtgebiet")
    assert wording_names_option(slot, "Summe", "Summe")
    assert wording_names_option(slot, "Summe", "Gesamt")


def test_the_year_question_names_where_to_look_and_in_which_order():
    """71 percent of Kassel's table tuples carried a foreign year, and the
    question said only that the year "stands in the column head, the table
    title, the caption or the section heading" -- four places, no order, and
    nothing about whose table."""
    for parameter in NUMERIC:
        question = parameter.axes["year"].question
        for step in ("(1) die Kopfzelle", "(2) der Titel", "(3) der Satz",
                     "(4) die Überschrift"):
            assert step in question, step
        assert "ANDEREN Tabelle gilt nicht" in question
        # A period is a convention, and one the graph has to be told about.
        assert "LETZTE Jahr in value" in question
        assert "Zeitraum wörtlich in value_raw" in question
        assert question.startswith("Für welches Kalenderjahr"), (
            "the aggregation is an integral over that year, so the question "
            "asks for the year it is integrated over")


def test_the_scenario_question_can_recognise_a_stock_take():
    """Kassel's inventory chapter never writes "Bestandsanalyse": it writes
    "welche Energieträger dafür bislang eingesetzt werden". 69 tuples from
    its two inventory tables came back as target-scenario values."""
    for parameter in NUMERIC:
        question = parameter.axes["scenario"].question
        for word in ("Bilanzjahr", "Ausgangslage", "bislang", "derzeit",
                     "Jahr vor der Erstellung"):
            assert word in question, word
        assert "bislang eingesetzt werden" in question, (
            "the sentence measured on Kassel 349424, verbatim")
        assert "eigenen Namen gibt" in question, (
            "a target scenario under a variant name is still the target")
        # A variant beside the scenario is its own answer: two variants of one
        # coordinate both answered "Zielszenario" are two values on one
        # identity, which the serializer can only drop as a conflict.
        assert "out:variant" in parameter.axes["scenario"].vocabulary


def test_query_templates_cover_every_part_a_plan_has():
    """The search found the target scenario and nothing else. Measured on
    Kassel: the appendix section lay in 123 field windows, the inventory
    chapter in 44, the target chapter in none, and 244 of 552 scenario
    answers were read off an appendix title."""
    from docpipe import prompts
    prompt = prompts.load("extraction/queries", _profile())
    templates = [line for line in prompt.text.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
    for part in ("Bestandsanalyse", "Zielszenario", "Trendszenario",
                 "Potenzialanalyse", "Methodik"):
        assert any(part in t for t in templates), part
    # Each one is a probe of its own, not a word bolted onto another.
    probes = expand(templates, SPEC.parameters[1])
    assert sum("Bestandsanalyse" in p for p in probes) == 1
    assert sum("CO2-Äquivalente" in p for p in probes) == 1


def test_the_anchor_prompt_asks_for_the_two_sentences_that_were_missing():
    """An anchor is what retrieval searches with, and it only ever wrote
    sentences about the quantity. The sentence that dates an inventory and
    the sentence that says a plan counts in CO2 equivalents never looked like
    the quantity, so nothing ever searched for them."""
    from docpipe import prompts
    text = prompts.load("extraction/anchors", _profile()).text
    assert "bislang eingesetzt werden" in text
    assert "CO2-Äquivalenten angegeben" in text


def test_the_spec_and_the_serializer_name_the_same_plan_parts():
    """The spec's kg block is what the JSON schema publishes; kg.PARTS is
    what is written. Two lists of the same thing drift, so this reads one
    against the other."""
    scenario = SPEC.parameters[0].axes["scenario"]
    mapped = scenario.kg["map"]
    assert set(mapped) == set(scenario.vocabulary), (
        "every scenario the model may choose says what it becomes")
    for key, (cls, _segment, _label) in kg.PARTS.items():
        assert cls.split(":")[-1] in mapped[key], (key, mapped[key])
    for key, where in mapped.items():
        if key not in kg.PARTS:
            assert "not serialized" in where, key


def test_the_same_coordinates_under_two_scenarios_are_two_values(tmp_path):
    """A trend 2030 and a target 2030 of the same carrier, sector and unit
    are two different statements about the plan. Minted off the heat plan
    they are one identity with two magnitudes, which the conflict guard can
    only drop -- both of them, loudly, as a contested reading."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(value_target=241.0),
        _row(scenario="trend", value_target=298.0),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 2, "neither is dropped"
    assert '"241.0"^^xsd:float' in ttl and '"298.0"^^xsd:float' in ttl
    assert len(set(re.findall(rf"{kg.BASE}value/({UUID5})", ttl))) == 2, (
        "two nodes, because the part they hang under is part of the identity")


def test_the_same_value_is_a_from_a_pdf_and_b_from_a_transcribed_plan(tmp_path):
    """Eleven plans of the corpus have no PDF text layer: a model read their
    pages, everything downstream ran unchanged, and the section text a quote
    is verified against is itself a reading. Two identical values differ only
    in which plan they came out of, and the graph says so."""
    serializer = kg.make_serializer(_database(tmp_path))
    with_text = serializer("waermeplan_kassel_20240315",
                           [_row(tier="text_located")])
    assert "# Vertrauen: A" in with_text

    transcribed = serializer("waermeplan_ohne_textebene",
                             [_row(tier="text_located",
                                   provenance={"document_id": 1082})])
    assert "# Vertrauen: B · page_transcribed" in transcribed
    assert "Vertrauen: A" not in transcribed


def test_the_graph_says_which_values_want_looking_at(tmp_path):
    """A reader of the Turtle sees the number and the level next to it, and a
    C names what is wrong with it. Without that a carrier read off another
    table is presented as a fact.

    The carrier and not the year, because the spec holds only the carrier and
    the sector to the row's own source. The year may stand a page away, so a
    year cited from elsewhere is the rule working as written -- reporting it
    would put a warning on readings that broke nothing.
    """
    serializer = kg.make_serializer(_database(tmp_path))
    own = _row(provenance={"document_id": 857, "owner_kind": "table",
                           "owner_id": 87457, "parent_section": 349525},
               carrier_state="read", carrier_source=["table", 87517])
    ttl = serializer("waermeplan_kassel_20240315", [own])
    assert "# Vertrauen: C" in ttl
    assert "nonlocal:carrier" in ttl
    assert "Prüfung empfohlen" in ttl


def test_a_coordinate_the_spec_lets_read_a_page_away_is_no_warning(tmp_path):
    """The same shape on the year, which the spec sets to "local". The
    harvest already refused what broke that rule; a second, stricter judge in
    the serializer would mark 370 of Kassel's 455 year readings as doubtful
    for doing what they were told."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(provenance={"document_id": 857, "owner_kind": "table",
                         "owner_id": 87457, "parent_section": 349525},
             year_state="read", year_source=["table", 87517]),
    ])
    assert "nonlocal:year" not in ttl
    assert "# Vertrauen: B" in ttl, "out of a table image, and nothing else"


def test_the_spellings_the_corpus_writes_are_in_the_lists():
    """From the KWW parameter list: words German heat plans really use that
    ours did not hold. "Nahwärme" is the one that matters most -- a plan
    writes it as often as Fernwärme, and without it the reading resolved to
    nothing."""
    energy = SPEC.parameters[0]
    carrier = energy.axes["carrier"].label_to_uri()
    assert carrier["nahwärme"] == "OEO_00000132"
    assert carrier["hackschnitzel"] == carrier["brennholz"] == "OEO_00000449"
    assert carrier["heizungsstrom"] == "OEO_00000139"
    assert carrier["h2"] == "OEO_00000220"
    assert carrier["umgebungswärme"] == "OEO_00000056"

    sector = energy.axes["sector"].label_to_uri()
    assert sector["verarbeitendes gewerbe"] == "OEO_00000227"
    assert sector["haushaltssektor"] == "OEO_00000214"

    scenario = energy.axes["scenario"].label_to_uri()
    for word in ("basisjahr", "ist-zustandsanalyse", "erstellungsjahr"):
        assert scenario[word] == "status_quo", word

    # An emission factor is a property of a carrier and not a quantity of
    # emitted gas, and three spellings of it now leave the graph as one.
    emission = SPEC.parameters[1].axes["quantity"].label_to_uri()
    for word in ("emissionsfaktor", "co2-faktor", "spezifische emissionen"):
        assert emission[word] == "out:factor", word


def test_every_option_the_graph_does_not_take_says_what_it_excludes():
    """An out:* entry is a correct answer and the model has to be able to
    pick it on purpose. It can only do that if the entry says what it is."""
    for parameter in NUMERIC:
        for name, axis in parameter.axes.items():
            for uri in axis.vocabulary or {}:
                if uri.startswith("out:"):
                    assert axis.definitions.get(uri), f"{parameter.uri}.{name}.{uri}"
