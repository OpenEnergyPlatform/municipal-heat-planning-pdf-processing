"""What a request shows of a list entry and of a parameter (owner decisions
2026-11-05, ticket 26): an entry shows its gloss, one line in the profile's
language, where the spec writes one, AND its definition where it does not,
AND a gloss without a definition is refused. A group shows the parameter's
brief unless its spec entry says "definition": "full", AND any other word
there is refused. The fingerprint of an axis moves with a gloss, AND that of
a parameter with its brief, since both reach the model.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import copy
import json
from pathlib import Path

import pytest

from docpipe.extraction import reading
from docpipe.extraction.spec import (SpecError, axis_fingerprint,
                                     load as load_spec,
                                     parameter_fingerprint)

RAW = json.loads((Path(__file__).resolve().parent.parent / "profiles" / "kwp"
                  / "extraction_spec.json").read_text(encoding="utf-8"))
SPEC = load_spec(RAW)
CO2 = "OEO_00340066"


def emission(raw):
    return next(p for p in raw["parameters"] if p["uri"] == "emission")


def quantity_entry(raw):
    return emission(raw)["axes"]["quantity"]["vocabulary"][CO2]


def shown(spec):
    """What a request shows of the CO2 entry of emission's quantity list."""
    parameter = spec.by_uri["emission"]
    slot = next(s for s in reading.slots_of(spec, parameter)
                if s.name == "quantity")
    entry = quantity_entry(RAW)
    return slot.answerable()[entry["label"]]


def test_an_entry_shows_its_gloss_and_without_one_its_definition():
    entry = quantity_entry(RAW)
    assert entry["gloss"] and entry["definition"]
    assert shown(SPEC)["means"] == entry["gloss"]
    # the failure by construction: without the gloss the definition shows
    raw = copy.deepcopy(RAW)
    del quantity_entry(raw)["gloss"]
    assert shown(load_spec(raw))["means"] == entry["definition"]


def test_a_gloss_needs_a_definition_and_some_words():
    for change in (lambda e: e.pop("definition"),
                   lambda e: e.update(gloss="  ")):
        raw = copy.deepcopy(RAW)
        change(quantity_entry(raw))
        with pytest.raises(SpecError):
            load_spec(raw)


def test_a_group_shows_the_brief_unless_it_says_full_and_nothing_else():
    assert {name for name, group in SPEC.groups.items()
            if group.full_definition} == {"context"}
    for word, full in (("full", True), ("brief", False)):
        raw = copy.deepcopy(RAW)
        raw["groups"]["number"]["definition"] = word
        assert load_spec(raw).groups["number"].full_definition is full
    # the failures by construction: another word, or an empty brief
    raw = copy.deepcopy(RAW)
    raw["groups"]["number"]["definition"] = "short"
    with pytest.raises(SpecError):
        load_spec(raw)
    raw = copy.deepcopy(RAW)
    emission(raw)["brief"] = " "
    with pytest.raises(SpecError):
        load_spec(raw)


def test_the_fingerprints_move_with_a_gloss_and_a_brief():
    raw = copy.deepcopy(RAW)
    quantity_entry(raw)["gloss"] = "Eine andere Zeile."
    emission(raw)["brief"] = "Ein anderer Absatz."
    other = load_spec(raw)
    before, after = SPEC.by_uri["emission"], other.by_uri["emission"]
    assert axis_fingerprint(before.axes["quantity"]) \
        != axis_fingerprint(after.axes["quantity"])
    assert parameter_fingerprint(before) != parameter_fingerprint(after)
    # the failure by construction: an axis the change does not touch keeps
    # its fingerprint
    assert axis_fingerprint(before.axes["sector"]) \
        == axis_fingerprint(after.axes["sector"])
