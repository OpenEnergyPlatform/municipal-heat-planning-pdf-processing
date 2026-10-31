"""A value's level says how far the run stands behind it: A and B read, C with
a coordinate nobody read, D with something against what was read. A
contradiction is two numbers for one thing, every coordinate of it read."""
from docpipe.extraction import provenance, review, schema, trust
from docpipe.inference import kg_route
from docpipe.serve.values import Values


def row(number=1, *, tier="text_located", flags=(), **states):
    found = {"parameter": "energy_consumption", "value": number, "unit": "GWh",
             "quote": f"Zitat {number}", "tier": tier, "flags": list(flags),
             "parameter_state": "derived", "unit_state": "read",
             "carrier": "OEO_1", "carrier_state": "read",
             "year": 2030, "year_state": "read"}
    for key, state in states.items():
        found[f"{key}_state"] = state
        found[key] = None
    return found


def level(found, **kwargs):
    return trust.trust(found, **kwargs)["level"]


def test_a_value_read_from_the_text_with_all_coordinates_is_an_a():
    assert level(row()) == "A"


def test_a_value_read_from_an_image_is_a_b():
    assert level(row(tier="visual_source")) == "B"


def test_a_transcribed_page_caps_at_b():
    assert level(row(), transcribed=True) == "B"


def test_a_coordinate_nobody_read_makes_a_c():
    assert level(row(carrier="exhausted")) == "C"
    assert level(row(carrier="unanswered")) == "C"


def test_a_coordinate_the_document_does_not_say_is_no_doubt():
    assert level(row(carrier="unstated")) == "A"


def test_what_speaks_against_the_reading_makes_a_d():
    assert level(row(carrier="unbacked")) == "D"
    assert level(row(flags=["quote_repaired"])) == "D"
    assert level(row(flags=["computed"])) == "D"
    assert level(row(flags=["not_located"])) == "D"
    assert level(row(flags=["review:disagree"])) == "D"
    assert level(row(), conflict=True) == "D"


def test_open_and_in_doubt_at_once_is_a_d():
    assert level(row(carrier="exhausted", flags=["quote_repaired"])) == "D"


def test_every_level_is_counted_in_the_summary_line():
    summary = trust.document_summary(1, [row(), row(carrier="exhausted"),
                                         row(carrier="unbacked")], [])
    assert summary["levels"] == {"A": 1, "B": 0, "C": 1, "D": 1}


def test_both_levels_below_b_ask_for_a_person():
    prose = {"level": "{level}", "image_origin": "", "image_origin_named": "",
             "corroborated": "", "reasons": "{reasons}", "review": "REVIEW"}
    for found in (row(carrier="exhausted"), row(carrier="unbacked")):
        assert "REVIEW" in trust.render(trust.trust(found), prose, join=" ")
    assert "REVIEW" not in trust.render(trust.trust(row()), prose, join=" ")


def test_both_levels_below_b_get_a_second_reading():
    rows = [row(), row(carrier="exhausted"), row(carrier="unbacked")]
    assert review.rows_to_review(rows) == rows[1:]


def test_the_schema_the_vocabulary_and_the_graph_route_know_every_level():
    assert schema.TRUST_LEVELS == trust.LEVELS
    assert set(trust.LEVELS) <= set(schema.TRUST_LEVEL_DOC)
    assert provenance.SCHEMES["TrustLevel"] == trust.LEVELS
    assert set(trust.LEVELS) <= set(provenance.CONCEPTS)
    prose = {"level": "Trust: {level}"}
    assert kg_route.trust_level("Trust: D · review", prose) == "D"


def test_two_numbers_for_one_thing_contradict_each_other():
    assert len(Values._contested([row(1), row(2)])) == 2


def test_one_number_read_twice_is_no_contradiction():
    assert Values._contested([row(1), row(1)]) == set()


def test_one_number_in_two_units_is_no_contradiction():
    left = dict(row(241), unit="GWh", value_target=241000)
    right = dict(row(241000), unit="MWh", value_target=241000)
    assert Values._contested([left, right]) == set()


def test_two_numbers_in_two_units_contradict_each_other():
    left = dict(row(5), unit="GWh", value_target=5000)
    right = dict(row(9000), unit="MWh", value_target=9000)
    assert len(Values._contested([left, right])) == 2


def test_two_rows_that_lack_a_coordinate_are_not_one_thing():
    for state in ("exhausted", "unanswered", "out_of_slice"):
        rows = [row(1, carrier=state), row(2, carrier=state)]
        assert Values._contested(rows) == set(), state


def test_different_coordinates_are_not_one_thing():
    other = dict(row(2), carrier="OEO_2")
    assert Values._contested([row(1), other]) == set()


def test_two_names_are_no_contradiction():
    left = {"parameter": "planning_organisation", "value": "Büro A",
            "parameter_state": "derived"}
    right = dict(left, value="Büro B")
    assert Values._contested([left, right]) == set()


def test_a_contradiction_reaches_the_served_level():
    store = Values({"plan": [row(1), row(2)]})
    assert {value["level"] for value in store} == {"D"}
    assert all("conflict" in value["reasons"] for value in store)
