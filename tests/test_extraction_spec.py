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


def test_duplicate_parameter_uris_are_refused():
    bad = _minimal()
    bad["parameters"].append(bad["parameters"][0])
    with pytest.raises(SpecError, match=r"duplicate"):
        load(bad)


def test_a_missing_file_names_the_path(tmp_path):
    with pytest.raises(SpecError, match=r"not found"):
        load(tmp_path / "nope.json")
