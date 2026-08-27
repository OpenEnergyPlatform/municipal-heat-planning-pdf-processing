"""The kwp extraction profile: spec, prompts, and the MHPKG serializer."""
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


@pytest.mark.parametrize("parameter", SPEC.parameters, ids=lambda p: p.uri)
def test_every_example_verifies_against_its_own_source(parameter):
    """The example doubles as the golden test: a spec whose own few-shot
    would be refused by verify_tuple teaches the model a refusable habit."""
    for raw in parameter.example["tuples"]:
        outcome = verify_tuple(dict(raw), parameter, parameter.example["source"])
        assert isinstance(outcome, Verified), getattr(outcome, "reason", outcome)


@pytest.mark.parametrize("parameter", NUMERIC, ids=lambda p: p.uri)
def test_the_examples_teach_exhaustive_extraction(parameter):
    """Every value cell in the example source has its tuple — a few-shot
    that extracts a subset teaches the model to under-harvest, and off-
    vocabulary columns are the lesson, not the exception."""
    import re as re_mod
    from docpipe.extraction.verify import canonical_number
    claimed = {canonical_number(t["value"]) for t in parameter.example["tuples"]}
    quoted_rows = {t["quote"] for t in parameter.example["tuples"]}
    for row in quoted_rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        for cell in cells[1:]:
            if re_mod.fullmatch(r"[\d.,]+", cell):
                assert canonical_number(cell) in claimed, f"{cell} has no tuple"
    outcomes = [verify_tuple(dict(t), parameter, parameter.example["source"])
                for t in parameter.example["tuples"]]
    flags = [f for o in outcomes for f in o.flags]
    assert flags, "the example must exercise the wording machinery at all"


def test_the_examples_show_both_mapping_and_refusing_to_map():
    """The two lessons the few-shot has to teach at once: a wording the class
    list does not contain still gets mapped when it clearly fits, and a label
    that fits no class stays empty instead of being forced into one."""
    flags = [f for parameter in SPEC.parameters
             for t in parameter.example["tuples"]
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
                                published TEXT, is_current INTEGER);
        CREATE TABLE DocumentMeta (document INTEGER, municipality_ags TEXT);
        CREATE TABLE Municipalities (ags TEXT, name TEXT);
        INSERT INTO Documents VALUES (857, 'waermeplan_kassel_20240315.pdf',
                                      '2024-03-15', 1);
        INSERT INTO DocumentMeta VALUES (857, '06611000');
        INSERT INTO Documents VALUES (858, 'waermeplan_kassel_alt.pdf',
                                      '2024-03-15', 0);
        INSERT INTO DocumentMeta VALUES (858, '06611000');
        INSERT INTO Municipalities VALUES ('06611000', 'Kassel');
    """)
    conn.commit()
    conn.close()
    return db


def _row(**overrides):
    row = {"kind": "tuple", "parameter": "energy_consumption", "value": 241000,
           "value_target": 241.0, "unit_raw": "kWh/a",
           "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
           "carrier": "OEO_00000292", "sector": None, "year": 2030,
           "scenario": "target", "spatial_scope": "municipality",
           "tier": "pdf_verified", "provenance": {"document_id": 857}}
    row.update(overrides)
    return row


def test_the_serializer_emits_only_the_target_scenario_slice(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(),
        _row(scenario="status_quo"),
        _row(spatial_scope="sub_area"),
        _row(quantity=None, quantity_raw="Endenergiebedarf"),
        _row(year=None),
    ])
    assert f"<{kg.BASE}heatplan/AGS_06611000_2024-03-15>" in ttl
    assert re.search(rf"{kg.BASE}value/{UUID5}", ttl)
    assert '"241.0"^^xsd:float' in ttl
    assert '"2030"^^xsd:integer' in ttl
    assert "oeo:OEO_00000523 oeo:OEO_00000292" in ttl
    assert ttl.count("a oeo:OEO_00050016") == 1, "the four skipped rows never arrive"
    assert "Kommunale Wärmeplanung Kassel 2024" in ttl


def test_a_carrier_oeo_does_not_call_a_carrier_is_counted_out(tmp_path):
    """`covers energy carrier` has range `energy carrier`, and district heating
    is a heat transfer, not one. The value is kept in the harvest and left out
    of the TTL rather than asserted against the range."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(carrier="OEO_00000132"),          # Fernwärme
        _row(carrier="OEO_00000139", value_target=5.0),   # Strom
        _row(),                                # Erdgas, the one that survives
    ])
    assert ttl.count("a oeo:OEO_00050016") == 1
    assert "OEO_00000132" not in ttl and "OEO_00000139" not in ttl


def test_a_value_conflict_on_one_coordinate_drops_every_claimant(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(), _row(value_target=242.0), _row(),
        _row(sector="OEO_00000214", value_target=99.0),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 1, "only the sectored value survives"
    assert '"99.0"^^xsd:float' in ttl and '"241.0"' not in ttl


def test_documents_without_target_tuples_or_identity_yield_none(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    assert serializer("waermeplan_kassel_20240315",
                      [_row(scenario="status_quo")]) is None
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


def test_one_heat_plan_comes_out_as_the_published_example(tmp_path):
    """The whole point of the pilot, as one assertion: feed the serializer what
    Kassel's plan says and the output is the schema repo's kassel_valid.ttl —
    every node, every predicate, both directions."""
    rows = [
        {"kind": "tuple", "parameter": "energy_consumption",
         "value": 241.0, "value_target": 241.0, "unit_raw": "MWh",
         "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
         "carrier": "OEO_00000292", "sector": "OEO_00000214", "year": 2030,
         "scenario": "target", "spatial_scope": "municipality",
         "provenance": {"document_id": 857}},
        {"kind": "tuple", "parameter": "planning_organisation",
         "value": "Kassel Wärme Ingenieurbüro GmbH",
         "quote": "Auftragnehmer: Kassel Wärme Ingenieurbüro GmbH",
         "provenance": {"document_id": 857}},
    ]
    ttl = kg.make_serializer(_database(tmp_path))(
        "waermeplan_kassel_20240315", rows)
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
