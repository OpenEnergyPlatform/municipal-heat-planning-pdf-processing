from docpipe.extraction import gold


def test_a_unit_read_as_a_coordinate_is_one_field():
    row = {"parameter": "energy_consumption", "value": 604000, "unit": "MWh",
           "unit_state": "read", "sector_state": "read", "sector": "households",
           "year_state": "read", "year": 2020}
    assert gold.fields_of(row) == ["value", "unit", "sector", "year"]


def test_a_unit_only_read_as_a_coordinate_is_still_a_field():
    row = {"parameter": "energy_consumption", "value": 604000, "unit": None,
           "unit_state": "unstated"}
    assert gold.fields_of(row) == ["value", "unit"]
