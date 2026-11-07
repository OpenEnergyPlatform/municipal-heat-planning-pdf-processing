"""The KWP spec asks for no more than the ontology and the graph demand
(owner decision 2026-11-07).

- Every closed list of the spec offers each class the ontology puts under its
  root, AND each such entry carries the ontology's own definition.
- The unit sets the aggregation only where the plan names no span of years;
  a value whose span the plan names is asked, in the harvest AND in a top-up.
- A value the full graph can hold is written there, without an aggregation
  and without an area where the plan states neither, AND a class the schema
  does not hold stays out of the strict graph.
- An energy in joule is converted into MWh.
- The plan's own municipality as the body that made the plan is the
  municipality node, AND no organisation is minted for it.
"""
import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import fields, spec as spec_module, topup
from docpipe.extraction.fields import READ
from profiles.kwp import kg, vocabulary

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "profiles" / "kwp" / "extraction_spec.json"
RAW = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
SPEC = spec_module.load(RAW)
SNAPSHOT = vocabulary.load()

# axis -> the snapshot set whose every member the axis must offer
ROOTS = {"carrier": "energy_carrier", "sector": "sector",
         "technology": "heat_generation_technology"}


def missing_classes(raw: dict) -> list:
    """(parameter, axis, class) the ontology has under the axis' root and
    the axis does not offer."""
    out = []
    for parameter in raw["parameters"]:
        for axis, root in ROOTS.items():
            offered = ((parameter.get("axes") or {}).get(axis) or {}) \
                .get("vocabulary")
            if offered is None:
                continue
            out += [(parameter["uri"], axis, uri)
                    for uri in SNAPSHOT["sets"][root] if uri not in offered]
    return out


def foreign_definitions(raw: dict) -> list:
    """(parameter, axis, class) whose definition is not the ontology's."""
    terms = SNAPSHOT["terms"]
    out = []
    for parameter in raw["parameters"]:
        for axis in ROOTS:
            offered = ((parameter.get("axes") or {}).get(axis) or {}) \
                .get("vocabulary") or {}
            for uri, entry in offered.items():
                own = (terms.get(uri) or {}).get("definition")
                if own and isinstance(entry, dict) \
                        and entry.get("definition") != own:
                    out.append((parameter["uri"], axis, uri))
    return out


def test_every_list_offers_every_class_under_its_root():
    assert missing_classes(RAW) == []


def test_a_list_short_of_one_class_is_found():
    short = copy.deepcopy(RAW)
    carriers = short["parameters"][0]["axes"]["carrier"]["vocabulary"]
    del carriers["OEO_00010242"]                       # diesel fuel
    assert missing_classes(short) == [
        ("energy_consumption", "carrier", "OEO_00010242")]


def test_every_entry_carries_the_ontology_s_definition():
    assert foreign_definitions(RAW) == []


def test_a_definition_of_our_own_is_found():
    rewritten = copy.deepcopy(RAW)
    carriers = rewritten["parameters"][0]["axes"]["carrier"]["vocabulary"]
    carriers["OEO_00010242"]["definition"] = "Kraftstoff für Dieselmotoren."
    assert foreign_definitions(rewritten) == [
        ("energy_consumption", "carrier", "OEO_00010242")]


# -- the aggregation the unit sets ------------------------------------------------

def parameter(uri: str):
    return next(p for p in SPEC.parameters if p.uri == uri)


def aggregation_slot(uri: str):
    axis = parameter(uri).axes["aggregation"]
    return SimpleNamespace(name="aggregation", derive=axis.derive)


def claim(**over):
    return {"unit": "MWh/a", "unit_state": READ, **over}


def test_an_annual_amount_takes_its_aggregation_from_the_unit():
    assert fields.derives(aggregation_slot("energy_consumption"), claim(),
                           parameter("energy_consumption"))


def test_a_mean_over_a_span_of_years_is_asked():
    over_years = claim(period_start=2019, period_start_state=READ)
    for uri in ("energy_consumption", "emission"):
        unit = "MWh/a" if uri == "energy_consumption" else "t CO2/a"
        assert not fields.derives(aggregation_slot(uri),
                                   {**over_years, "unit": unit},
                                   parameter(uri))


def test_a_unit_the_list_does_not_hold_sets_nothing():
    assert not fields.derives(aggregation_slot("energy_consumption"),
                               claim(unit=None),
                               parameter("energy_consumption"))


def test_a_top_up_derives_the_annual_amount_and_asks_the_mean():
    annual, mean = claim(), claim(period_start=2019, period_start_state=READ)
    decided, asked = topup.split_derived(
        [annual, mean], aggregation_slot("energy_consumption"),
        parameter("energy_consumption"))
    assert decided == [annual] and asked == [mean]


def test_unless_read_must_name_an_axis_of_the_parameter():
    broken = copy.deepcopy(RAW)
    broken["parameters"][0]["axes"]["aggregation"]["derive"][
        "unless_read"] = "no_such_axis"
    with pytest.raises(spec_module.SpecError):
        spec_module.load(broken)


# -- units --------------------------------------------------------------------------

def test_an_energy_in_joule_is_converted_into_mwh():
    amount = parameter("energy_consumption")
    assert amount.unit_factor("GJ") * 3.6 == pytest.approx(1.0)
    assert amount.unit_factor("TJ") * 0.0036 == pytest.approx(1.0)
    assert amount.unit_factor("PJ/a") == pytest.approx(277777.7777777778)


# -- the graph ------------------------------------------------------------------------

def database(tmp_path: Path) -> Path:
    path = tmp_path / "kwp.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS Documents (id INTEGER PRIMARY "
                 "KEY, filename TEXT, published TEXT, municipality_ags TEXT)")
    conn.execute("INSERT OR IGNORE INTO Documents VALUES (1, 'plan.pdf', "
                 "'2024-11-07', '09999999')")
    conn.commit()
    conn.close()
    return path


def value(**over):
    return {"parameter": "energy_consumption", "quantity": "OEO_00050016",
            "scenario": "status_quo", "spatial_scope": "municipality",
            "carrier": "OEO_00000292", "sector": "OEO_00000214",
            "year": 2022, "aggregation": "OEO_00140070", "unit": "MWh/a",
            "value": 241.0, "value_target": 241.0, "quote": "241 MWh/a",
            **over}


def graph(tmp_path, rows, strict=False):
    serializer = kg.make_serializer(database(tmp_path), strict=strict)
    return serializer("plan", rows) or ""


def test_a_power_without_aggregation_reaches_the_full_graph(tmp_path):
    power = value(parameter="heat_load", quantity="OEO_00010157",
                  unit="MW", aggregation=None, value=1.6, value_target=1.6,
                  quote="BHKW 1,6 MW")
    assert "1.6" in graph(tmp_path, [power])


def test_a_value_whose_area_the_plan_does_not_say_reaches_the_full_graph(
        tmp_path):
    assert "241.0" in graph(tmp_path, [value(spatial_scope=None)])


def test_a_class_outside_the_schema_is_full_graph_only(tmp_path):
    diesel = value(carrier="OEO_00010242")
    assert kg.strict_refusal(diesel) == "off_list:refers_to_energy_carrier"
    assert "OEO_00010242" in graph(tmp_path, [diesel])
    assert "OEO_00010242" not in graph(tmp_path, [diesel, value()],
                                       strict=True)


def organisation(name: str, role: str):
    return {"parameter": kg.ORGANISATION, "value": name, kg.ROLE: role,
            "quote": f"Auftraggeber: {name}"}


def test_the_municipality_as_maker_is_the_municipality_node(tmp_path):
    out = graph(tmp_path, [value(), organisation("Stadt Musterhausen",
                                                 "municipality")])
    municipality = f"<{kg.BASE}municipality/AGS_09999999>"
    assert f"{kg.P_ORGANISATION} {municipality}" in out
    assert kg.mint("organisation", kg.normalise("Stadt Musterhausen")) not in out


def test_an_office_is_minted_as_an_organisation(tmp_path):
    out = graph(tmp_path, [value(), organisation("Zebau", "planner")])
    assert kg.mint("organisation", kg.normalise("Zebau")) in out
    assert f"<{kg.BASE}municipality/AGS_09999999> ;" not in out.split(
        str(kg.P_ORGANISATION), 1)[-1].split(".", 1)[0]
