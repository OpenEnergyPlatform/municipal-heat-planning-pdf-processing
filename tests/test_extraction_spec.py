"""The extraction spec is the contract everything downstream leans on.

A wrong spec must die at load time naming its field — not three GPU hours
into a batch, and never by silently extracting on a guessed vocabulary.
"""
import pytest

from docpipe.extraction.spec import Spec, SpecError, load


def _minimal():
    return {"parameters": [{
        "uri": "OEO_00050016",
        "label": "final energy consumption value",
        "description": "Endenergieverbrauch: die vom Endverbraucher bezogene "
                       "Energiemenge je Träger, Sektor und Jahr.",
        "unit_target": "OEO_00050008",
        "units_accepted": {"kWh/a": 0.001, "MWh/a": 1.0, "GWh/a": 1000.0},
        "axes": {
            "carrier": {"vocabulary": {"OEO_00000292": ["Erdgas", "Gas"]}},
            "year": {"type": "int", "required": True},
            "scenario": {"enum": ["status_quo", "trend", "target", "unknown"]},
        },
        "example": {
            "source": "| Erdgas | 126.656.132 | 520.465.057 | 1.036.767.833 | kWh/a |",
            "tuples": [{"value": 126656132, "unit_raw": "kWh/a",
                        "carrier": "OEO_00000292"}],
        },
    }]}


def test_a_valid_spec_loads_and_indexes_by_uri():
    spec = load(_minimal())
    assert isinstance(spec, Spec)
    assert "OEO_00050016" in spec.by_uri
    axis = spec.by_uri["OEO_00050016"].axes["carrier"]
    assert axis.label_to_uri()["erdgas"] == "OEO_00000292"


def test_a_stub_description_is_refused():
    """The description becomes the model's definition of the parameter."""
    bad = _minimal()
    bad["parameters"][0]["description"] = "Endenergie."
    with pytest.raises(SpecError, match=r"description"):
        load(bad)


def test_an_empty_vocabulary_is_refused():
    bad = _minimal()
    bad["parameters"][0]["axes"]["carrier"]["vocabulary"] = {}
    with pytest.raises(SpecError, match=r"axes\.carrier"):
        load(bad)


def test_one_label_may_not_map_to_two_uris():
    """An ambiguous label would make every later match a coin toss."""
    bad = _minimal()
    bad["parameters"][0]["axes"]["carrier"]["vocabulary"]["OEO_99999999"] = ["erdgas"]
    with pytest.raises(SpecError, match=r"already maps"):
        load(bad)


def test_an_axis_is_exactly_one_kind():
    bad = _minimal()
    bad["parameters"][0]["axes"]["carrier"]["type"] = "int"
    with pytest.raises(SpecError, match=r"exactly one"):
        load(bad)


def test_the_example_is_mandatory():
    """It is the prompt's few-shot and the runner's golden test."""
    bad = _minimal()
    del bad["parameters"][0]["example"]
    with pytest.raises(SpecError, match=r"example"):
        load(bad)


def test_an_example_tuple_with_a_foreign_unit_is_refused():
    bad = _minimal()
    bad["parameters"][0]["example"]["tuples"][0]["unit_raw"] = "PJ"
    with pytest.raises(SpecError, match=r"units_accepted"):
        load(bad)


def test_two_spellings_that_normalise_alike_may_not_carry_two_factors():
    """The guard sat in the branch where units is always empty, so it never ran.

    A numeric parameter is the only kind that carries units, so this is where
    the check belongs: "kWh / a" and "kWh/a" are one spelling to the verifier,
    and letting them carry 0.001 and 1000.0 would multiply a value by a million
    depending on which one the document happened to print.
    """
    bad = _minimal()
    bad["parameters"][0]["units_accepted"]["kWh / a"] = 1000.0
    with pytest.raises(SpecError, match=r"same spelling to the verifier"):
        load(bad)


def test_two_spellings_of_one_unit_are_the_point_and_still_load():
    ok = _minimal()
    ok["parameters"][0]["units_accepted"]["kWh / a"] = 0.001
    assert "kWh / a" in load(ok).by_uri["OEO_00050016"].units_accepted


def test_duplicate_parameter_uris_are_refused():
    bad = _minimal()
    bad["parameters"].append(bad["parameters"][0])
    with pytest.raises(SpecError, match=r"duplicate"):
        load(bad)


def test_a_missing_file_names_the_path(tmp_path):
    with pytest.raises(SpecError, match=r"not found"):
        load(tmp_path / "nope.json")


def test_a_subscript_two_is_the_same_spelling_as_the_digit():
    """A plan prints "CO₂-Emissionen" with U+2082; every spec, schema and
    ontology writes it with the digit. Casefold alone leaves the two strings
    different, so 132 of Kassel's 204 emission readings were recorded as the
    model's own judgement call over one character — and a reply that answers
    with the document's spelling resolves to no class at all.
    """
    from docpipe.extraction.spec import fold_label
    raw = _minimal()
    axes = raw["parameters"][0]["axes"]
    axes["carrier"] = {"vocabulary": {"OEO_00340066": ["CO2-Emissionen"]}}
    axis = load(raw).parameters[0].axes["carrier"]
    table = axis.label_to_uri()
    assert table[fold_label("CO₂-Emissionen")] == "OEO_00340066"
    assert table[fold_label("co2-emissionen")] == "OEO_00340066"
    # It folds the two spellings and nothing else: a label that differs in a
    # real character stays a different label.
    assert fold_label("CO2 Emissionen") not in table
    assert fold_label("CO2-Emissionen je Kopf") not in table


def test_two_spellings_of_one_label_may_not_map_to_two_classes():
    """The same fold, on the guard side: "CO₂-Emissionen" under one class and
    "CO2-Emissionen" under another is the coin toss the load-time check
    exists to refuse, and casefold alone let it through."""
    raw = _minimal()
    raw["parameters"][0]["axes"]["carrier"] = {"vocabulary": {
        "OEO_00340066": ["CO2-Emissionen"],
        "OEO_00140083": ["CO₂-Emissionen"]}}
    with pytest.raises(SpecError) as excinfo:
        load(raw)
    assert "already maps to" in str(excinfo.value)
