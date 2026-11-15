"""The blocks a spec is made of (owner request 2026-11-14, wish 4b): a value
type with its settings, a dimension derived under a condition, a field of
the whole document that says what it is, and a field's own check. Each
promise is held by a case that keeps it and one that breaks it on
purpose."""
import copy
import dataclasses

import pytest

from docpipe.extraction import addressed, fields, reading, runner, spec, verify
from docpipe.extraction.addressed import Reader
from docpipe.extraction.pipeline import Row, Source

from test_addressed import Model, in_order, plan_of

FIELD = {
    "uri": "share", "label": "Anteil",
    "description": "Ein Anteil der Wärme, den der Plan für seine Gemeinde "
                   "nennt, je Energieträger und Jahr.",
    "value_type": "percent",
    "axes": {"year": {"type": "int", "question": "Für welches Jahr?"},
             "kind": {"question": "Welche Art?", "vocabulary": {
                 "a": {"label": "Bestand", "spellings": [],
                       "definition": "Was heute steht."},
                 "b": {"label": "Ziel", "spellings": [],
                       "definition": "Was es werden soll."}}}},
    "example": {"source": "Im Jahr 2022 lag der Anteil der Fernwärme bei "
                          "zwölf Prozent der Wärme.",
                "tuples": [{"value": 12, "quote": "bei zwölf Prozent"}]}}
PERCENT = {"answer": "number", "units": False, "in_quote": "words"}


def spec_of(field=None, **more):
    return spec.load({"value_types": {"percent": PERCENT},
                      "parameters": [field or FIELD], **more})


# -- a value type ---------------------------------------------------------------

def test_a_value_type_of_the_spec_s_own_gives_its_field_its_settings():
    share = spec_of().by_uri["share"]
    assert share.is_numeric and not share.has_units and not share.converts
    assert not share.number_in_quote and not share.is_entry
    built = spec.BUILTIN_TYPES
    assert spec_of(dict(FIELD, value_type="text", example={
        **FIELD["example"], "tuples": [{"value": "zwölf",
                                         "quote": "bei zwölf Prozent"}]}
    )).by_uri["share"].kind == built["text"]


@pytest.mark.parametrize("own, said", [
    ({"float": {"answer": "number"}}, "built-in"),
    ({"x": {"answer": "words", "units": True}}, "number only"),
    ({"x": {"answer": "number", "converts": True}}, "one of its units"),
    ({"x": {"answer": "entry", "in_quote": "number"}}, "one of"),
    ({"x": {"answer": "maybe"}}, "one of"),
])
def test_a_value_type_that_cannot_be_is_refused(own, said):
    with pytest.raises(spec.SpecError, match=said):
        spec.load({"value_types": own, "parameters": [FIELD]})


def test_a_number_without_units_asks_no_unit_and_carries_none():
    share = spec_of().by_uri["share"]
    assert [s.name for s in reading.slots_of(spec_of(), share)] \
        == ["year", "kind"]
    with pytest.raises(spec.SpecError, match="carries no unit"):
        spec_of(dict(FIELD, unit_target="UO_1"))
    resolved, refused = verify._check_value({"value": 12}, share, [])
    assert refused is None and "value_target" not in resolved


def test_a_number_its_type_does_not_convert_keeps_its_unit_only():
    own = {"answer": "number", "units": True, "converts": False}
    field = dict(FIELD, value_type="kept", unit_target="UO_1",
                 units_accepted={"%": {"factor": 0.01,
                                       "names_period": False}})
    share = spec.load({"value_types": {"kept": own},
                       "parameters": [field]}).by_uri["share"]
    resolved, _ = verify._check_value({"value": 12, "unit": "%"}, share, [])
    assert resolved == {"unit": "%"}
    converted = dataclasses.replace(share, kind=spec.BUILTIN_TYPES["float"])
    resolved, _ = verify._check_value({"value": 12, "unit": "%"},
                                      converted, [])
    assert resolved["value_target"] == 0.12


def test_a_number_found_by_its_words_stands_in_its_quote_by_them():
    share = spec_of().by_uri["share"]
    said = {"value": 12, "value_raw": "zwölf"}
    assert verify.value_in_quote(said, share, "bei zwölf Prozent")
    assert not verify.value_in_quote(said, share, "bei 12 Prozent")
    by_number = dataclasses.replace(share, kind=spec.BUILTIN_TYPES["float"])
    assert verify.value_in_quote(said, by_number, "bei 12 Prozent")


def test_a_built_in_type_leaves_the_fingerprint_and_an_own_one_moves_it():
    plain = spec.parameter_fingerprint(spec_of(dict(
        FIELD, value_type="text", example={**FIELD["example"], "tuples": [
            {"value": "zwölf", "quote": "bei zwölf Prozent"}]})
    ).by_uri["share"])
    share = spec_of().by_uri["share"]
    first = spec.parameter_fingerprint(share)
    other = dataclasses.replace(share, kind=dataclasses.replace(
        share.kind, in_quote="number"))
    assert first != spec.parameter_fingerprint(other) and plain != first
    checked = dataclasses.replace(share, checks=({"name": "x"},))
    assert spec.parameter_fingerprint(checked) != first


# -- a dimension derived under a condition ------------------------------------------

DERIVED = {"if": {"all": [{"of": "reading", "is": "value", "op": "more",
                           "value": 50}]}, "value": "b"}


def derived_spec():
    field = copy.deepcopy(FIELD)
    field["axes"]["kind"]["derive"] = DERIVED
    return spec_of(field)


def test_a_dimension_is_derived_where_its_condition_holds_and_nothing_read_it():
    share = derived_spec().by_uri["share"]
    slot = next(s for s in fields.axis_slots(share) if s.name == "kind")
    big, small = {"value": 80, "quote": "80 Prozent"}, {"value": 20}
    assert fields.derives(slot, big, share)
    assert not fields.derives(slot, small, share)
    assert not fields.derives(slot, {**big, "kind_state": fields.READ},
                              share)
    rows = [Row("A", 0, big)]
    assert fields.apply_derived(rows, slot) == 1
    assert big["kind"] == "b" and big["kind_state"] == fields.DERIVED
    assert big["kind_quote"] == "80 Prozent" and "kind_raw" not in big


@pytest.mark.parametrize("condition", [
    {"all": [{"of": "quote", "is": "length", "op": "less", "value": 3}]},
    {"all": [{"of": "reading", "is": "value", "op": "listed"}]},
])
def test_a_derive_whose_condition_is_not_about_the_reading_alone_is_refused(
        condition):
    field = copy.deepcopy(FIELD)
    field["axes"]["kind"]["derive"] = {"if": condition, "value": "b"}
    with pytest.raises(spec.SpecError, match="derive"):
        spec_of(field)


# -- a field of the whole document ----------------------------------------------------

def test_a_field_of_the_whole_document_says_what_it_is_under_any_key():
    loaded = spec_of(plan_fields={
        "reference": {"name": "Bezugsjahr", "means": "Das Jahr.",
                      "kind": "year", "state": "base"},
        "settings": {"name": "Festlegungen", "means": "Was gilt."}})
    assert loaded.plan_field_of("year", "base")[0] == "reference"
    assert loaded.plan_field_of("settings")[0] == "settings"
    assert loaded.plan_field_of("year", "target") is None


@pytest.mark.parametrize("fields_, said", [
    ({"elsewhere": {"name": "x", "means": "y"}}, "says what it is"),
    ({"base_year": {"name": "x", "means": "y"},
      "again": {"name": "x", "means": "y", "kind": "year",
                "state": "base"}}, "says what base_year says"),
    ({"y": {"name": "x", "means": "y", "kind": "year"}}, "state"),
])
def test_a_field_of_the_whole_document_that_is_unclear_is_refused(fields_,
                                                                  said):
    with pytest.raises(spec.SpecError, match=said):
        spec_of(plan_fields=fields_)


def test_the_years_of_a_state_are_read_off_the_field_of_its_kind():
    groups = {"frame": {"coordinates": ["kind", "year"], "read_in": "reading",
                        "where": "Der Titel.", "pair": ["kind", "year"]}}
    loaded = spec_of(groups=groups, plan_fields={
        "reference": {"name": "Bezugsjahr", "means": "Das Jahr.",
                      "kind": "year", "state": "base", "of": {"kind": "a"}}})
    assert runner.year_states_of(loaded) == {"base": {"kind": "a"},
                                             "target": None}


# -- a field's own check -----------------------------------------------------------------

CHECK = {"name": "kurz", "refuse": {"all": [
    {"of": "quote", "is": "length", "op": "less", "value": 20}]},
    "sentence": "Quote the whole line."}
SHORT = Source("section", 40, "Erdgas: 300 MWh.", {"document_id": 7,
                                                   "page": 2})
LONGER = Source("section", 41, "Der Verbrauch an Erdgas betrug 300 MWh.",
                {"document_id": 7, "page": 2})


@pytest.mark.parametrize("check, said", [
    ({**CHECK, "sentence": ""}, "sentence"),
    ({**CHECK, "refuse": {"all": [{"of": "nothing", "is": "x"}]}}, "refuse"),
    ({**CHECK, "also": 1}, "no key"),
])
def test_a_check_without_its_parts_is_refused(check, said):
    with pytest.raises(spec.SpecError, match=said):
        spec_of(dict(FIELD, checks=[check]))


def checked_read(source, checks) -> tuple:
    from test_addressed import ENERGY, SPEC
    energy = dataclasses.replace(ENERGY, checks=tuple(checks))
    model = Model(find=lambda p, n: {"found": [{"at": "1", "words": "300"}]})
    counts = addressed.Counts()
    claims = [c for r in Reader(SPEC, model.asks(), in_order)(
        plan_of(source), [energy], counts=counts) for c in r.claims]
    return claims, model, counts


def test_a_field_s_own_check_refuses_its_value_and_asks_it_again():
    claims, model, counts = checked_read(SHORT, [CHECK])
    assert counts.failed["check:kurz"] >= 1
    assert any("Quote the whole line." in str(p) for k, p, n in model.calls
               if k == "follow")
    assert not [c for c in claims if c.get("value") == 300
                and c.get("value_state", "read") == "read"
                and c.get("quote") == "Erdgas: 300 MWh."]
    # the failure by construction: the same line without the check is read
    claims, _model, counts = checked_read(SHORT, [])
    assert [c for c in claims if c.get("value") == 300]
    assert "check:kurz" not in counts.failed


def test_a_field_s_own_check_lets_a_value_it_does_not_refuse_hold():
    claims, _model, counts = checked_read(LONGER, [CHECK])
    assert [c for c in claims if c.get("value") == 300]
    assert "check:kurz" not in counts.failed


# -- the kind of value of a field in a condition --------------------------------

def kind_is(*names):
    return {"all": [{"of": "field", "is": "kind", "op": "one_of",
                     "value": list(names)}]}


def test_a_condition_about_the_kind_of_value_takes_the_spec_s_own_types():
    from docpipe.extraction import conditions
    check = {**CHECK, "refuse": kind_is("percent")}
    assert spec_of(dict(FIELD, checks=[check])).by_uri["share"].checks
    with pytest.raises(spec.SpecError, match="one of"):
        spec_of(dict(FIELD, checks=[{**CHECK, "refuse": kind_is("prozent")}]))
    field = next(s for s in conditions.catalogue(added={
        "value_types": ("float", "percent")}) if s["name"] == "field")
    kind = next(p for p in field["props"] if p["name"] == "kind")
    assert kind["choices"] == ["float", "percent"]
    assert kind["added_by"] == "value_types"


def test_where_no_spec_is_known_the_kind_of_value_is_any_name():
    from docpipe.extraction import conditions
    assert conditions.problems(kind_is("percent")) == []
    assert conditions.problems(kind_is("")) != []
    with conditions.added({"value_types": tuple(spec.BUILTIN_TYPES)}):
        assert conditions.problems(kind_is("percent")) != []
        assert conditions.problems(kind_is("float")) == []
    assert conditions.problems(kind_is("percent")) == []


def test_the_run_compares_the_kind_of_value_by_the_type_s_name():
    from docpipe.extraction import conditions
    facts = conditions.Facts(lambda subject, prop: {
        ("field", "kind"): "percent"}[(subject, prop)])
    assert conditions.holds(kind_is("percent"), facts)
    assert not conditions.holds(kind_is("float"), facts)
