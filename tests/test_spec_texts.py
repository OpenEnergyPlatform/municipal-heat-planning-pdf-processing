"""The texts a model is shown beside a spec's fields stand in the spec (owner
decision 2026-11-10): what a document settles once (`plan_fields`), its other
works (`works`), and the fixed entries of a list closed per document
(`beside`). They are loaded strictly and are in no stamp key. So is the rule
that says which pairs of a document's frame are its own state and its target
(`plan_fields`, key `of`, owner decision 2026-11-10), which a pass over a
stored harvest takes the document's years by.

Each promise has a case that breaks it by construction beside the one that
keeps it. That a reader asks with these words is in test_addressed.py."""
import copy
import json
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner, topup
from docpipe.extraction.spec import SpecError, fingerprints, load

ROOT = Path(__file__).resolve().parent.parent
KWP = json.loads((ROOT / "profiles" / "kwp" / "extraction_spec.json")
                 .read_text(encoding="utf-8"))
SCENARIOS = json.loads((ROOT / "profiles" / "scenarios"
                        / "extraction_spec.json").read_text(encoding="utf-8"))


def changed(raw: dict, change) -> dict:
    out = copy.deepcopy(raw)
    change(out)
    return out


def region(raw: dict) -> dict:
    return next(p for p in raw["parameters"] if p["uri"] == "scenario_region")


# -- no stamp key ----------------------------------------------------------------

def test_the_texts_beside_the_fields_are_in_no_stamp_key():
    def bare(raw):
        raw.pop("plan_fields", None)
        raw.pop("works", None)
        for parameter in raw["parameters"]:
            parameter.pop("beside", None)
    for raw in (KWP, SCENARIOS):
        assert fingerprints(load(changed(raw, bare))) == fingerprints(
            load(raw))
    reworded = changed(SCENARIOS, lambda raw: (
        raw["works"]["fields"].update(study_acronym="Which line?"),
        raw["plan_fields"]["settings"].update(means="Something else."),
        region(raw)["beside"]["out:other"].append("elsewhere")))
    assert fingerprints(load(reworded)) == fingerprints(load(SCENARIOS))
    ruled = changed(KWP, lambda raw: raw["plan_fields"]["base_year"].update(
        of={"scenario": "trend"}))
    assert fingerprints(load(ruled)) == fingerprints(load(KWP))
    # the failure by construction: a spelling of a list a request shows does
    # move its key, so the comparison above can fail
    listed = changed(SCENARIOS, lambda raw: next(
        iter(raw["parameters"][14]["vocabulary"].values()))["spellings"]
        .append("another spelling"))
    assert fingerprints(load(listed)) != fingerprints(load(SCENARIOS))


# -- loaded strictly -------------------------------------------------------------

@pytest.mark.parametrize("change, where", [
    (lambda raw: raw["plan_fields"].update(
        mood={"name": "Mood", "means": "How the plan feels."}),
     "spec.plan_fields.mood"),
    (lambda raw: raw["plan_fields"]["settings"].pop("means"),
     "spec.plan_fields.settings.means"),
    (lambda raw: raw["plan_fields"]["settings"].update(sentence=" "),
     "spec.plan_fields.settings.sentence"),
    (lambda raw: raw["plan_fields"]["settings"].update(meaning="x"),
     "spec.plan_fields.settings"),
    (lambda raw: raw["works"]["fields"].update(no_such_field="Which line?"),
     "spec.works.fields.no_such_field"),
    (lambda raw: raw["works"]["fields"].update(study_acronym=""),
     "spec.works.fields.study_acronym"),
    (lambda raw: raw["works"].pop("name"), "spec.works.name"),
    (lambda raw: region(raw)["beside"].update(
        {"OEO_00000001": ["a class of the ontology"]}), "beside.OEO_00000001"),
    (lambda raw: raw["parameters"][14].update(
        beside={"out:other": ["something else"]}), "beside"),
])
def test_a_text_block_the_run_cannot_use_is_refused_by_name(change, where):
    with pytest.raises(SpecError, match=where):
        load(changed(SCENARIOS, change))


def test_the_blocks_reach_the_run_as_the_file_writes_them():
    spec = load(SCENARIOS)
    assert json.dumps(spec.plan_fields) == json.dumps(SCENARIOS["plan_fields"])
    assert json.dumps(spec.works) == json.dumps(SCENARIOS["works"])
    assert spec.by_uri["scenario_region"].beside == region(SCENARIOS)["beside"]
    assert runner.names_asked(spec)
    # the failure by construction: a spec without the blocks asks nothing of
    # the kind
    bare = load({"parameter_question": KWP["parameter_question"],
                 "unit_question": KWP["unit_question"],
                 "groups": KWP["groups"], "parameters": KWP["parameters"]})
    assert bare.plan_fields == {} and bare.works is None
    assert not runner.names_asked(bare)


# -- which pairs of the frame are a document's own state and its target ---------

@pytest.mark.parametrize("change, where", [
    # at a field that is no year of the document
    (lambda raw: raw["plan_fields"]["settings"].update(
        of={"scenario": "status_quo"}), "spec.plan_fields.settings"),
    (lambda raw: raw["plan_fields"]["base_year"].update(of={}),
     "spec.plan_fields.base_year.of"),
    (lambda raw: raw["plan_fields"]["base_year"].update(of="status_quo"),
     "spec.plan_fields.base_year.of"),
    # a coordinate that is none of the frame's, with an entry of its list
    (lambda raw: raw["plan_fields"]["base_year"].update(
        of={"carrier": "OEO_00000014"}),
     "spec.plan_fields.base_year.of.carrier"),
    # the frame's year, which has no list an entry could be of
    (lambda raw: raw["plan_fields"]["target_year"].update(
        of={"year": "2045"}), "spec.plan_fields.target_year.of.year"),
    # the entry by its label and not by its key: no pair would match it
    (lambda raw: raw["plan_fields"]["target_year"].update(
        of={"scenario": "Zielszenario"}),
     "spec.plan_fields.target_year.of.scenario"),
])
def test_a_rule_for_a_document_s_years_that_matches_no_pair_is_refused(
        change, where):
    load(KWP)
    with pytest.raises(SpecError, match=where):
        load(changed(KWP, change))


def stored(index: int, scenario: str, year: int) -> dict:
    """A stored row as the harvest wrote the pair *index* of the frame onto
    it."""
    return {"scenario": scenario, "scenario_window": ["frame", index],
            "year": year, "year_window": ["frame", index],
            "year_quote": f"im Jahr {year}", "year_source": ["section", 4]}


def test_a_pass_over_a_stored_harvest_takes_the_years_the_spec_s_rule_names():
    rows = [stored(0, "Bestand", 2022), stored(1, "Zielszenario", 2045),
            stored(2, "Trendszenario", 2040)]

    def years(raw) -> list:
        spec = load(raw)
        frame = fields.frame_slots(spec, ("scenario", "year"))
        return [(found["state"], found["year"])
                for found in topup.named_years_of(
                    rows, frame, runner.year_states_of(spec))]
    assert years(KWP) == [("base", 2022), ("target", 2045)]
    # the failures by construction: another rule takes other years, a state
    # without a rule has none, and a spec that says no rule has no years
    assert years(changed(KWP, lambda raw: raw["plan_fields"]["base_year"]
                         .update(of={"scenario": "trend"}))) == [
        ("base", 2040), ("target", 2045)]
    assert years(changed(KWP, lambda raw: raw["plan_fields"]["base_year"]
                         .pop("of"))) == [("target", 2045)]
    assert years(changed(KWP, lambda raw: [
        raw["plan_fields"][key].pop("of")
        for key in ("base_year", "target_year")])) == []
    assert runner.year_states_of(load(SCENARIOS)) == {"base": None,
                                                      "target": None}


# -- the fixed entries of a list closed per document ---------------------------------

def test_a_document_s_list_ends_with_the_entries_the_spec_puts_beside_it():
    spec = load(SCENARIOS)
    beside = region(SCENARIOS)["beside"]
    own = {"https://example.org/region/France": ["France"]}

    def listed(vocabularies) -> dict:
        filled = runner.fill_dynamic_axes(spec, vocabularies)
        return filled.by_uri["scenario_region"].vocabulary

    assert list(listed({"scenario_region": own}).items()) == (
        list(own.items()) + list(beside.items()))
    # A document that names no region still has a list to choose from.
    assert listed({"scenario_region": {}}) == beside
    # the failure by construction: a profile that closes no list for the
    # field leaves it without one, the entries beside it are not a list of
    # their own
    assert listed({"another_field": own}) is None
