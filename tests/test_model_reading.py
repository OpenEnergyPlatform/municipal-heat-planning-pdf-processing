"""What a field request hands the model about the number it asks for."""
import json
from types import SimpleNamespace

from docpipe.extraction import fields, pipeline, runner
from docpipe.extraction.spec import load as load_spec
from profiles.kwp import extraction as kwp, kg

TABLE = ("| Sektor | Erdgas | Wärmenetze |\n| --- | --- | --- |\n"
         "| Wohnen | 120 | 80 |\n")
QUOTE = "| Wohnen | 120 | 80 |"


def table_source(text=TABLE, kind="table"):
    return SimpleNamespace(owner_kind=kind, owner_id=1, text=text,
                           provenance={})


def test_a_number_is_told_the_head_of_its_own_column():
    facts = runner.cell_facts(80, QUOTE, table_source())
    assert (facts["column"], facts["head"]) == (3, "Wärmenetze")


def test_every_head_line_of_a_column_counts_once():
    text = "| A | Bedarf |\n| B | 2030 |\n| --- | --- |\n| x | 1 |\n"
    assert pipeline.column_head(text, 2, 2) == "Bedarf / 2030"


def test_a_head_of_another_width_says_nothing():
    text = "| Sektor | Gesamt |\n| --- | --- |\n| Wohnen | 120 | 80 |\n"
    assert pipeline.column_head(text, 3, 3) is None


def test_a_table_without_a_rule_line_says_nothing():
    assert pipeline.column_head("| a | b |\n| 1 | 2 |\n", 2, 2) is None


def test_a_number_outside_a_table_passage_gets_no_head():
    source = table_source(kind="section")
    assert "head" not in runner.cell_facts(80, QUOTE, source)


def test_the_same_number_in_two_cells_names_no_column():
    assert runner.cell_facts(80, "| Wohnen | 80 | 80 |", table_source()) == {}


def test_a_read_year_without_wording_is_known_to_the_axes_behind_it():
    claim = {"year_state": fields.READ, "year": 2030}
    assert runner.row_context(claim) == {"year": "2030"}


def test_an_asked_coordinate_is_not_known():
    claim = {"year_state": fields.READ, "year": 2030}
    assert runner.row_context(claim, {"year"}) == {}


def test_the_year_is_asked_before_the_scenario_and_closes_no_row():
    assert list(kwp.SLICE) == ["quantity", "year"]
    year = SimpleNamespace(options=None)
    assert runner.keeps_row(year, 2040, kwp.SLICE["year"])


def test_the_gate_still_closes_a_quantity_outside_the_graph():
    quantity = SimpleNamespace(options=None)
    assert not runner.keeps_row(quantity, "out:share",
                                kwp.SLICE["quantity"])


SPEC = load_spec(json.loads(kwp.SPEC_PATH.read_text(encoding="utf-8")))


def quantity_slots():
    """{parameter uri: its quantity slot, with the spec's options}."""
    return {parameter.uri: slot for parameter in SPEC.parameters
            for slot in fields.axis_slots(parameter) if slot.name == "quantity"}


def label_in(slot, uri):
    return next(option.label for option in slot.options if option.uri == uri)


def test_a_potential_is_read_on_every_axis():
    for uri in ("energy_consumption", "heat_load"):
        slot = quantity_slots()[uri]
        assert runner.keeps_row(slot, label_in(slot, "OEO_00140058"),
                                kwp.SLICE["quantity"])


def test_a_quantity_without_a_class_is_read_on_every_axis():
    slots = quantity_slots()
    for entry in kwp.READ_IN_FULL:
        holding = [slot for slot in slots.values()
                   if entry in {option.uri for option in slot.options}]
        assert holding, entry
        for slot in holding:
            assert runner.keeps_row(slot, label_in(slot, entry),
                                    kwp.SLICE["quantity"])


def test_every_other_out_entry_still_closes_its_row():
    for slot in quantity_slots().values():
        for option in slot.options:
            if option.uri.startswith("out:") \
                    and option.uri not in kwp.READ_IN_FULL:
                assert not runner.keeps_row(slot, option.label,
                                            kwp.SLICE["quantity"]), option.uri


def building_row():
    """A row the unit question read as a number of buildings."""
    return SimpleNamespace(label="R1", claim={
        "value": 68, "unit": "Gebäude", "unit_raw": "Anzahl Gebäude",
        "unit_quote": "| | Anzahl Gebäude: | 68 |",
        "quote": "| | Anzahl Gebäude: | 68 |"})


def test_a_number_of_buildings_is_a_building_count():
    row = building_row()
    assert fields.derive_parameter(SPEC, row.claim).uri == "building_count"
    slots = {slot.name: slot
             for slot in fields.axis_slots(SPEC.by_uri["building_count"])}
    for name in ("quantity", "aggregation"):
        fields.apply_derived([row], slots[name])
    assert (row.claim["quantity"], row.claim["aggregation"]) == (
        "MHPO_00030021", "OEO_00140069")
    assert runner.keeps_row(slots["quantity"], row.claim["quantity"],
                            kwp.SLICE["quantity"])


def test_a_building_count_is_written_as_mhpos_class_in_the_count_unit():
    row = {"parameter": "building_count", "quantity": "MHPO_00030021"}
    assert kg.typed_as(row) == "mhpo:MHPO_00030021"
    assert kg.unit_of(row) == "UO_0000189"
    _lines, bindings = kg.value_bindings({"quantity": "MHPO_00030021"})
    assert bindings["QUANTITY"] == ("iri", kg.PREFIX_IRI["mhpo"]
                                    + "MHPO_00030021")


def test_a_value_is_written_in_its_parameters_unit():
    targets = {parameter["uri"]: parameter.get("unit_target")
               for parameter in json.loads(kwp.SPEC_PATH.read_text(
                   encoding="utf-8"))["parameters"]}
    energy = kg.unit_of({"parameter": "energy_consumption",
                         "quantity": "OEO_00140058"})
    power = kg.unit_of({"parameter": "heat_load", "quantity": "OEO_00140058"})
    assert (energy, power) == (targets["energy_consumption"],
                               targets["heat_load"])
    assert energy != power
    assert kg.unit_of({"parameter": "energy_consumption",
                       "quantity": "out:useful_energy"}) is None


def share_row(value, whole):
    return {"quantity": "OEO_00140127", "year": 2045, "value": value,
            "value_target": float(value), "whole": whole,
            "quote": f"| Zeile | {value} |", "scenario": "target",
            "tier": "text_located", "flags": []}


def test_the_whole_of_a_share_splits_two_numbers_into_two_nodes():
    rows = [share_row(41, "Wärmebedarf"), share_row(30, "Emissionen")]
    kept, _lost, _marks = kg.settle(kg._value_iri("part", rows[0]), rows,
                                    "part", keep_open=True)
    assert sorted(r["whole"] for r in kept.values()) == ["Emissionen",
                                                         "Wärmebedarf"]
