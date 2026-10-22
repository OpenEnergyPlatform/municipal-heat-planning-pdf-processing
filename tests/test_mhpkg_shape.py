"""The graph takes its terms from the MHPKG schema the last refresh pulled;
the strict graph holds only what the schema's shapes take; an optional
coordinate is read from the value's own passage alone."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import runner
from profiles.kwp import kg, mhpkg

SCHEMA = {
    "prefixes": {"oeo": "https://openenergyplatform.org/ontology/oeo/"},
    "slots": {"has_part": {"slot_uri": "obo:BFO_0000051"},
              "refers_to_energy_carrier": {"slot_uri": "oeo:OEO_00370001",
                                           "range": "CarrierEnum",
                                           "required": True},
              "refers_to_sector": {"slot_uri": "oeo:OEO_00020519",
                                   "range": "SectorEnum", "required": True},
              "covers_parameter": {"slot_uri": "mhpo:MHPO_0002028"}},
    "classes": {"Plan": {"class_uri": "mhpo:MHPO_00020003",
                         "slots": ["has_part"]},
                "Part": {"class_uri": "mhpo:MHPO_00020007",
                         "slots": ["covers_parameter"],
                         "slot_usage": {"covers_parameter": {"any_of": [
                             {"range": "Use"}, {"range": "Emission"}]}}},
                "Use": {"class_uri": "oeo:OEO_00050016",
                        "slots": ["refers_to_energy_carrier",
                                  "refers_to_sector"]},
                "Emission": {"class_uri": "oeo:OEO_00340065",
                             "slots": ["refers_to_energy_carrier",
                                       "refers_to_sector"],
                             "slot_usage": {"refers_to_energy_carrier": {
                                 "required": False}}}},
    "enums": {"CarrierEnum": {"permissible_values": {
                  "gas": {"meaning": "oeo:OEO_00000292"}}},
              "SectorEnum": {"permissible_values": {
                  "households": {"meaning": "oeo:OEO_00000214"}}}},
}
SHAPE = mhpkg.Shape(SCHEMA)


# -- reading the schema ---------------------------------------------------------

def test_a_class_uses_a_slot_as_its_slot_usage_says():
    assert SHAPE.required("Use") == {"refers_to_energy_carrier",
                                     "refers_to_sector"}
    assert SHAPE.required("Emission") == {"refers_to_sector"}
    assert SHAPE.value_classes("Part", "covers_parameter") == ["Use",
                                                               "Emission"]


def test_a_closed_slot_admits_its_list_and_nothing_else():
    assert SHAPE.admits("Use", "refers_to_energy_carrier", "oeo:OEO_00000292")
    assert not SHAPE.admits("Use", "refers_to_energy_carrier",
                            "oeo:OEO_00000132")
    assert SHAPE.admits("Plan", "has_part", "oeo:anything")   # no enum


def test_the_spec_names_slots_and_reads_the_schema_s_terms():
    spec = {"parameters": [{"axes": {"carrier": {"kg": {
        "role": "edge", "schema_slot": "refers_to_energy_carrier"}}},
        "kg": {"map": {"target": {"schema_class": "Part"}}}}]}
    got = mhpkg.resolve(spec, SHAPE)
    block = got["parameters"][0]["axes"]["carrier"]["kg"]
    assert (block["prefix"], block["predicate"]) == ("oeo", "OEO_00370001")
    assert got["parameters"][0]["kg"]["map"]["target"]["class"] \
        == "MHPO_00020007"
    assert "predicate" not in spec["parameters"][0]["axes"]["carrier"]["kg"]


def test_an_unknown_slot_stops_the_reading_rather_than_guessing():
    with pytest.raises(KeyError):
        mhpkg.resolve({"kg": {"schema_slot": "refers_to_planet"}}, SHAPE)


def test_terms_the_pin_lacks_are_named_not_refused():
    terms = {"OEO_00370001": {}, "OEO_00050016": {}, "OEO_00340065": {},
             "OEO_00000292": {}, "OEO_00000214": {}, "MHPO_00020003": {},
             "MHPO_00020007": {}}
    assert mhpkg.missing_terms(SHAPE, terms) == ["mhpo:MHPO_0002028",
                                                 "oeo:OEO_00020519"]


# -- the graph the profile writes -------------------------------------------------

def row(**over):
    return {"parameter": "energy_consumption", "quantity": "OEO_00050016",
            "scenario": "target", "spatial_scope": "municipality",
            "carrier": "OEO_00000292", "sector": "OEO_00000214",
            "year": 2030, "aggregation": "OEO_00140070",
            "value_target": 241.0, **over}


def test_the_graph_writes_the_schema_s_predicates():
    assert kg.P_CARRIER == kg.SHAPE.slot("refers_to_energy_carrier")
    assert kg.P_HAS_QUANTITY_VALUE == kg.SHAPE.slot("covers_parameter")
    assert kg.CLS_HEATPLAN == kg.SHAPE.cls("MunicipalHeatPlan")


def test_a_total_sector_is_the_schema_s_parent_and_a_total_carrier_none():
    assert kg.written(row(sector="out:total"), "sector") == "OEO_00000128"
    assert kg.written(row(carrier="out:total"), "carrier") is None
    assert kg.written(row(), "carrier") == "OEO_00000292"


def test_a_value_without_technology_keeps_its_iri():
    plain = kg._value_iri("plan", row())
    assert kg._value_iri("plan", row(technology=None)) == plain
    assert kg._value_iri("plan", row(technology="OEO_00020486")) != plain
    assert kg._value_iri("plan", row(technology="out:total")) == plain


def test_a_share_has_no_aggregation_field_in_its_identity():
    share = row(parameter="share", quantity="OEO_00140127",
                aggregation=None)
    assert kg._value_iri("plan", share) == kg.mint("value", "|".join([
        "plan", kg.OEO + "OEO_00140127", kg.OEO + "OEO_00000292",
        kg.OEO + "OEO_00000214", "2030", "", ""]))


def test_the_strict_graph_takes_what_the_schema_s_lists_hold():
    assert kg.strict_refusal(row()) is None


@pytest.mark.parametrize("over, why", [
    ({"carrier": "OEO_00000132"}, "off_list:refers_to_energy_carrier"),
    ({"sector": "OEO_00000405"}, "off_list:refers_to_sector"),
    ({"carrier": "out:total"}, "missing:refers_to_energy_carrier"),
    ({"scenario": "trend"}, "class"),
    ({"spatial_scope": "sub_area"}, "area"),
    ({"quantity": "OEO_00050018"}, "class"),
])
def test_the_strict_graph_leaves_out_what_its_shapes_refuse(over, why):
    assert kg.strict_refusal(row(**over)) == why


def test_an_emission_needs_no_carrier_in_the_strict_graph():
    emission = row(parameter="emission", quantity="OEO_00340066",
                   carrier=None, sector=None)
    assert kg.schema_class_of(emission) == "GreenhouseGasEmissionValue"
    assert kg.strict_refusal(emission) is None


# -- an optional coordinate is read where the value stands ---------------------------

def test_a_share_of_zero_reads_the_own_passage_alone():
    budget = runner.window_budget(0)
    assert budget["retrieval"] == budget["rest"] == 0
    assert budget["own"] == runner.FIELD_ATTEMPTS
    assert runner.window_budget(1.0)["retrieval"] > 0


def test_a_share_named_for_the_parameter_wins_over_the_axis():
    sweeper = runner.make_sweeper(lambda *a, **k: None, search_share={
        "emission.carrier": 0, "carrier": 0.5})
    carrier = [SimpleNamespace(name="carrier")]
    assert sweeper.budget_of(carrier, "emission")["rest"] == 0
    assert sweeper.budget_of(carrier, "energy_consumption")["rest"] > 0
