"""The spec names every coordinate once in the order of the questions, says
which coordinates only a value's own passage or number states and which are
the frame, and writes what several fields ask alike once as a shared
dimension that each of them asks exactly as its own copy.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import copy
import json
from pathlib import Path

import pytest

from docpipe.extraction import reading
from docpipe.extraction.spec import (SHARED, SpecError, axes_of, expanded,
                                     fingerprints, load as load_spec)

ROOT = Path(__file__).resolve().parent.parent
RAW = {name: json.loads((ROOT / "profiles" / name / "extraction_spec.json")
                        .read_text(encoding="utf-8"))
       for name in ("kwp", "scenarios")}
SPEC = {name: load_spec(raw) for name, raw in RAW.items()}


def changed(change, name: str = "kwp") -> dict:
    raw = copy.deepcopy(RAW[name])
    change(raw)
    return raw


def coordinates_of(spec) -> set:
    known = {name for parameter in spec.parameters for name in parameter.axes}
    if spec.unit_question and any(p.has_units for p in spec.parameters):
        known.add("unit")
    return known


# -- the order of the questions --------------------------------------------------

@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_every_coordinate_of_the_spec_is_in_the_order_once(name):
    order = SPEC[name].coordinates.order
    assert len(order) == len(set(order))
    assert set(order) == coordinates_of(SPEC[name])


def test_a_coordinate_missing_from_the_order_is_refused():
    raw = changed(lambda r: r["coordinates"]["order"].remove("whole"))
    with pytest.raises(SpecError, match="not in the order: whole"):
        load_spec(raw)


def test_a_coordinate_named_twice_is_refused():
    raw = changed(lambda r: r["coordinates"]["order"].append("year"))
    with pytest.raises(SpecError, match="named twice"):
        load_spec(raw)


def test_a_name_that_is_no_coordinate_is_refused():
    raw = changed(lambda r: r["coordinates"]["order"].append("colour"))
    with pytest.raises(SpecError, match="no coordinate"):
        load_spec(raw)


def test_a_value_is_asked_its_coordinates_in_the_order_of_the_spec():
    spec = SPEC["kwp"]
    field = spec.by_uri["energy_consumption"]
    asked = [slot.name for slot in reading.in_order(
        spec, reading.slots_of(spec, field))]
    order = list(spec.coordinates.order)
    assert asked == sorted(asked, key=order.index)
    assert asked[0] == "unit"
    # the failure by construction: the order turned round turns the
    # questions round
    turned = load_spec(changed(
        lambda r: r["coordinates"].update(order=r["coordinates"]["order"][::-1])))
    again = [slot.name for slot in reading.in_order(
        turned, reading.slots_of(turned, turned.by_uri["energy_consumption"]))]
    assert again == asked[::-1]


def test_a_spec_written_with_blocks_is_refused_and_told_what_replaces_them():
    raw = changed(lambda r: r.update(groups={"number": {
        "coordinates": ["unit"], "read_in": "reading", "where": "x"}}))
    with pytest.raises(SpecError, match="coordinates.order"):
        load_spec(raw)


# -- what is read otherwise than the rest ---------------------------------------------

def test_what_only_a_value_s_own_passage_or_number_says_and_the_frame():
    # Owner decisions 2026-11-06 and 2026-11-07: what a number is and counts,
    # how it is aggregated and who made the plan only their own passage says,
    # a word like "ca." only the number itself; scenario and year are the
    # frame the base and target years date a value by.
    c = SPEC["kwp"].coordinates
    assert c.own_passage == ("unit", "what", "subject", "aggregation", "role")
    assert c.own_value == ("qualifier",)
    assert c.frame == ("scenario", "year")


def test_a_mark_on_no_coordinate_of_the_order_is_refused():
    raw = changed(lambda r: r["coordinates"].update(own_passage=["colour"]))
    with pytest.raises(SpecError, match="coordinates of the order"):
        load_spec(raw)


def test_own_passage_and_own_value_exclude_each_other():
    raw = changed(lambda r: r["coordinates"].update(
        own_value=["qualifier", "subject"]))
    with pytest.raises(SpecError, match="not both"):
        load_spec(raw)


# -- the shared dimensions ------------------------------------------------------------

@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_shared_dimension_is_asked_as_the_field_s_own_copy(name):
    raw = RAW[name]
    assert raw.get("shared_axes")
    written_out = expanded(raw)
    assert "shared_axes" not in written_out
    assert all(axis != SHARED for p in written_out["parameters"]
               for axis in p["axes"].values())
    # The same questions, the same lists: every fingerprint of the stamp.
    assert fingerprints(load_spec(written_out)) == fingerprints(SPEC[name])
    for p, q in zip(raw["parameters"], written_out["parameters"]):
        assert axes_of(raw, p) == q["axes"]


def test_a_changed_shared_dimension_changes_every_field_that_asks_it_only():
    raw = changed(lambda r: r["shared_axes"]["sector"].update(
        question="Für welchen Sektor gilt diese Zahl?"))
    before, after = fingerprints(SPEC["kwp"]), fingerprints(load_spec(raw))
    moved = {key for key in before if before[key] != after.get(key)}
    asking = {p["uri"] for p in RAW["kwp"]["parameters"]
              if p.get("axes", {}).get("sector") == SHARED}
    assert moved == {f"axis/{uri}/sector" for uri in asking} and asking


def test_a_field_s_own_dimension_beside_a_shared_one_of_its_name_stays_its_own():
    raw = RAW["kwp"]
    owners = [p for p in raw["parameters"]
              if isinstance(p.get("axes", {}).get("aggregation"), dict)]
    assert owners, "some field keeps its own aggregation"
    for p in owners:
        assert axes_of(raw, p)["aggregation"] is p["axes"]["aggregation"]
        assert p["axes"]["aggregation"] != raw["shared_axes"]["aggregation"]


def test_a_shared_dimension_no_field_has_is_refused():
    raw = changed(lambda r: r["shared_axes"].update(colour={"type": "text"}))
    with pytest.raises(SpecError, match="no field asks colour"):
        load_spec(raw)


def test_a_field_naming_a_shared_dimension_the_spec_lacks_is_refused():
    raw = changed(lambda r: r["parameters"][0]["axes"].update(colour=SHARED))
    with pytest.raises(SpecError, match="has no 'colour'"):
        load_spec(raw)
