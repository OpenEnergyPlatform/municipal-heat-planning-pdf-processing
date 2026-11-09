"""The spec puts every coordinate in exactly one group, read in the reading,
and says which coordinates only a value's own passage or number can say
(owner decisions 2026-11-04 to 2026-11-08).

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import copy
import json
from pathlib import Path

import pytest

from docpipe.extraction.spec import SpecError, load as load_spec

RAW = json.loads((Path(__file__).resolve().parent.parent / "profiles" / "kwp"
                  / "extraction_spec.json").read_text(encoding="utf-8"))
SPEC = load_spec(RAW)


def with_groups(change) -> dict:
    raw = copy.deepcopy(RAW)
    change(raw["groups"])
    return raw


# -- the groups of the spec ----------------------------------------------------

def test_every_coordinate_of_the_spec_is_in_exactly_one_group():
    grouped = [c for group in SPEC.groups.values() for c in group.coordinates]
    assert len(grouped) == len(set(grouped))
    # Every group is read in the reading (owner decision 2026-11-07: each
    # value is asked its own scenario and year).
    assert {group.read_in for group in SPEC.groups.values()} == {"reading"}


def test_a_coordinate_in_no_group_is_refused():
    raw = with_groups(lambda g: g["context"]["coordinates"].remove("whole"))
    with pytest.raises(SpecError, match="whole"):
        load_spec(raw)


def test_a_coordinate_in_two_groups_is_refused():
    raw = with_groups(lambda g: g["number"]["coordinates"].append("year"))
    with pytest.raises(SpecError, match="already in group"):
        load_spec(raw)


def test_a_name_that_is_no_coordinate_is_refused():
    raw = with_groups(lambda g: g["context"]["coordinates"].append("colour"))
    with pytest.raises(SpecError, match="no coordinate"):
        load_spec(raw)


def test_a_group_read_by_no_step_is_refused():
    raw = with_groups(lambda g: g["frame"].update(read_in="search"))
    with pytest.raises(SpecError, match="read_in"):
        load_spec(raw)


def test_a_group_read_in_the_survey_is_refused():
    # Owner decisions 2026-11-08: the survey is gone, so a group it was to
    # read would be read by no step.
    raw = with_groups(lambda g: g["frame"].update(read_in="survey"))
    with pytest.raises(SpecError, match="read_in"):
        load_spec(raw)


def test_what_only_a_value_s_own_passage_or_number_says_is_of_its_group():
    # Owner decision 2026-11-06: what a number counts and how it is
    # aggregated only its own passage says, a word like "ca." only the
    # number itself; the combing does not look for them elsewhere.
    number, context = SPEC.groups["number"], SPEC.groups["context"]
    # And its unit, what the number is, and the beginning of a period it is
    # a mean over: read again beside it, never searched elsewhere (owner
    # decisions 2026-11-07).
    assert (number.own_passage, number.own_value) == (
        ("unit", "what", "subject"), ("qualifier",))
    # Which body made the plan, the municipality itself or another, only the
    # passage that names it says (owner decision 2026-11-07).
    assert context.own_passage == ("aggregation", "role")
    assert SPEC.groups["frame"].own_passage == ()
    raw = with_groups(lambda g: g["number"].update(own_passage=["year"]))
    with pytest.raises(SpecError, match="group's coordinates"):
        load_spec(raw)
    raw = with_groups(lambda g: g["number"].update(own_value=["subject"]))
    with pytest.raises(SpecError, match="not both"):
        load_spec(raw)
