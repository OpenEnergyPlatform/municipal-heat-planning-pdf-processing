"""
The rules of taking an answer, checking it, folding it, its states and its
trust (`docpipe/ruleset/taking.py`): the value of the rule decides, read at
the time of use (owner, 2026-11-11: "alles soll anpassbar sein").

Each promise has a case that breaks it by construction beside the one that
keeps it: a rule set with `rules.overlaid` or at a step changes what the
code does, AND today's standard gives today's result, AND a way that does
not exist yet is refused.
"""
import json
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import (compute, fields, found, lookup, pipeline,
                                schema, spec as spec_module, trust, verify)
from docpipe.extraction.pipeline import Row, Source, merge_field

from test_addressed import ENERGY, SLOTS, SPEC

TEXT = ("Der Endenergieverbrauch liegt im Jahr 2030 bei 450 MWh und im "
        "Basisjahr 2022 bei 500 MWh.")
SOURCE = Source("section", 1, TEXT)
OTHER = Source("section", 2, "Ein ganz anderer Absatz ohne jede Zahl.")


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def year_row():
    return Row("R1", 0, {})


def ask_year(answer, sources=(SOURCE,), row=None):
    row = row or year_row()
    got = merge_field([row], list(sources), SLOTS["year"],
                      {"answers": {"R1": answer}})
    return row, got


GOOD = {"value": 2030, "quote": "im Jahr 2030 bei 450 MWh"}


def state(row, name="year"):
    return row.claim.get(f"{name}_state")


# -- the two checks every answer passes ---------------------------------------

def test_check_quote_shown_decides_if_a_quote_must_stand_in_a_shown_line():
    elsewhere = {"value": 2030, "quote": "im Jahr 2030 steht hier nirgends"}
    row, got = ask_year(elsewhere)
    assert state(row) == fields.UNBACKED
    assert got["failed"][0]["why"] == "quote_not_in_source"
    with rules.overlaid(check_quote_shown=False):
        row, got = ask_year(elsewhere)
        assert state(row) == fields.READ
        assert row.claim["year_source"] == ["section", 1]   # the first shown
    row, _ = ask_year(GOOD)
    assert state(row) == fields.READ                        # the standard


def test_check_quote_shown_holds_for_a_value_and_a_step_may_switch_it():
    raw = {"value": 450, "unit": "MWh", "quote": "dies steht nirgends 450"}
    parameter = ENERGY
    assert verify.value_refused(raw, parameter, TEXT) == verify.QUOTE_NOT_FOUND
    node = {"id": "x", "box": "find"}
    values = {"check_quote_shown": False}
    with rules.in_step(rules.stepped(node, values)):
        assert verify.value_refused(raw, parameter, TEXT) is None
    assert verify.value_refused(raw, parameter, TEXT) == verify.QUOTE_NOT_FOUND


def test_check_answer_in_quote_decides_if_the_answer_must_be_in_its_quote():
    not_there = {"value": 2031, "quote": "im Jahr 2030 bei 450 MWh"}
    row, got = ask_year(not_there)
    assert state(row) == fields.UNBACKED
    assert got["failed"][0]["why"] == "answer_not_in_quote"
    with rules.overlaid(check_answer_in_quote=False):
        row, _ = ask_year(not_there)
        assert state(row) == fields.READ
        raw = {"value": 999, "unit": "MWh", "quote": "im Jahr 2030 bei 450"}
        assert verify.value_refused(
            raw, ENERGY, TEXT) is None
    assert verify.value_refused(
        {"value": 999, "unit": "MWh", "quote": "im Jahr 2030 bei 450"},
        ENERGY, TEXT) is not None


def test_a_way_that_does_not_exist_yet_is_not_allowed():
    for name, other in (("check_accepts", "accepts"),
                        ("keep_unlisted_unit", "refused")):
        assert rules.problem(name, other) is not None, name
        assert rules.problem(name, rules.default()[name]) is None, name


# -- numbers and years --------------------------------------------------------

def test_thousands_spaces_say_which_spaces_group_the_digits():
    assert "45000" in verify.numbers_in("rund 45 000 MWh")
    assert verify.canonical_number("45 000") == "45000"
    with rules.overlaid(thousands_spaces=""):
        assert "45000" not in verify.numbers_in("rund 45 000 MWh")
        assert verify.canonical_number("45 000") is None
    with rules.overlaid(thousands_spaces=" "):
        assert "45000" in verify.numbers_in("rund 45 000 MWh")
        assert "45000" not in verify.numbers_in("rund 45 000 MWh")


def test_year_as_digit_run_decides_how_a_year_stands_in_its_quote():
    quote = "Es sind 2.022 MWh"
    assert not pipeline.answer_in_quote(SLOTS["year"], 2022, None, quote)
    with rules.overlaid(year_as_digit_run=False):
        assert pipeline.answer_in_quote(SLOTS["year"], 2022, None, quote)
    assert pipeline.answer_in_quote(SLOTS["year"], 2022, None,
                                    "Stand 31.12.2022")


def test_number_axis_whole_only_decides_whether_a_year_may_have_decimals():
    assert pipeline._wrong_type(SLOTS["year"], 2045.5) is not None
    with rules.overlaid(number_axis_whole_only=False):
        assert pipeline._wrong_type(SLOTS["year"], 2045.5) is None
        assert pipeline._wrong_type(SLOTS["year"], "2030-2045") is not None
    assert pipeline._wrong_type(SLOTS["year"], 2045) is None


def test_plan_year_states_say_which_states_a_word_may_mean_and_in_what_order():
    pairs = [{"year": 2022, "year_quote": "Basisjahr 2022 und mehr",
              "year_source": ["section", 1], "scenario": "Bestand"},
             {"year": 2045, "year_quote": "Zieljahr 2045 und mehr",
              "year_source": ["section", 1], "scenario": "Ziel"}]
    axes = [fields.Slot(name="year", kind=fields.NUMBER),
            fields.Slot(name="scenario", kind=fields.TEXT)]
    states = {"base": {"scenario": "Bestand"}, "target": {"scenario": "Ziel"}}

    def years():
        return [(e["state"], e["year"])
                for e in pipeline.named_years(pairs, axes, states)]
    assert years() == [("base", 2022), ("target", 2045)]
    with rules.overlaid(plan_year_states=["target", "base"]):
        assert years() == [("target", 2045), ("base", 2022)]
    with rules.overlaid(plan_year_states=["target"]):
        assert years() == [("target", 2045)]


def test_flag_missing_period_decides_whether_a_missing_period_is_flagged():
    raw = {"value": 450, "unit": "MWh", "unit_raw": "MWh", "year": 2030,
           "quote": "im Jahr 2030 bei 450 MWh"}
    flags = verify.verify_tuple(dict(raw), ENERGY, TEXT).flags
    assert "period:unstated" in flags
    with rules.overlaid(flag_missing_period=False):
        flags = verify.verify_tuple(dict(raw), ENERGY, TEXT).flags
        assert "period:unstated" not in flags
    assert "period:unstated" not in verify.verify_tuple(
        {**raw, "unit": "MWh/a", "unit_raw": "MWh/a"}, ENERGY, TEXT).flags


def test_read_off_figures_decides_if_a_drawn_number_is_read_off_the_image():
    raw = {"read_off": True, "reading": "the bar stands at about 450"}
    assert verify.read_off(raw, "figure")
    assert not verify.read_off(raw, "table")
    with rules.overlaid(read_off_figures=False):
        assert not verify.read_off(raw, "figure")
    node = {"id": "x", "box": "coord"}
    with rules.in_step(rules.stepped(node, {"read_off_figures": False})):
        assert not verify.read_off(raw, "figure")
    assert verify.read_off(raw, "figure")


# -- lists and wording --------------------------------------------------------

def choice_slot():
    return SLOTS["carrier"]


def test_answer_in_quote_spellings_decides_whether_a_synonym_backs_a_choice():
    slot = choice_slot()
    option = next(o for o in slot.options if o.synonyms)
    spelling = option.synonyms[0]
    quote = f"Verbrauch von {spelling} im Jahr"
    assert pipeline.answer_in_quote(slot, option.label, None, quote)
    with rules.overlaid(answer_in_quote_spellings=False):
        assert not pipeline.answer_in_quote(slot, option.label, None, quote)
        assert pipeline.answer_in_quote(slot, option.label, None,
                                        f"Verbrauch von {option.label}")


def test_longest_entry_wins_decides_whether_a_longer_entry_shadows_a_shorter():
    short = SimpleNamespace(label="MWh", synonyms=())
    long = SimpleNamespace(label="MWh/a", synonyms=())
    slot = SimpleNamespace(options=(short, long))
    assert not pipeline.stands_in(slot, short, "mwh", "450 mwh/a")
    with rules.overlaid(longest_entry_wins=False):
        assert pipeline.stands_in(slot, short, "mwh", "450 mwh/a")
    assert pipeline.stands_in(slot, short, "mwh", "450 mwh")


def test_mark_foreign_wording_decides_whether_a_foreign_wording_is_marked():
    slot = choice_slot()
    option = next(o for o in slot.options if o.label == "Erdgas")
    quote = "Der Verbrauch von Kohle und Strom liegt hoch."
    answer = {"value": option.label, "value_raw": "Kohle", "quote": quote}
    source = Source("section", 1, quote)

    def read():
        row = Row("R1", 0, {})
        merge_field([row], [source], slot, {"answers": {"R1": answer}})
        return row
    assert read().claim["carrier_state"] == fields.READ
    assert read().claim.get("carrier_raw_foreign") is True
    with rules.overlaid(mark_foreign_wording=False):
        assert read().claim["carrier_state"] == fields.READ
        assert not read().claim.get("carrier_raw_foreign")


# -- not stated, a later answer, route ---------------------------------------

def test_unstated_needs_no_quote_decides_whether_not_stated_needs_a_line():
    answer = {"value": fields.UNSTATED}
    row, _ = ask_year(answer)
    assert state(row) == fields.SAID_UNSTATED
    with rules.overlaid(unstated_needs_no_quote=False):
        row, got = ask_year(answer)
        assert state(row) == fields.UNBACKED
        assert got["failed"][0]["why"] == "quote_not_in_source"
        row, _ = ask_year({"value": fields.UNSTATED,
                           "quote": "im Jahr 2030 bei 450 MWh"})
        assert state(row) == fields.SAID_UNSTATED


def test_reading_wins_decides_which_of_two_backed_answers_a_coordinate_keeps():
    later = {"value": 2022, "quote": "im Basisjahr 2022 bei 500 MWh"}
    row, _ = ask_year(GOOD)
    merge_field([row], [SOURCE], SLOTS["year"], {"answers": {"R1": later}})
    assert row.claim["year"] == 2030                       # the first wins
    with rules.overlaid(reading_wins="later_backed"):
        row, _ = ask_year(GOOD)
        merge_field([row], [SOURCE], SLOTS["year"], {"answers": {"R1": later}})
        assert row.claim["year"] == 2022
        assert row.claim["year_quote"] == later["quote"]
        # a later answer that is not backed changes nothing
        bad = {"value": 2031, "quote": "im Jahr 2030 bei 450 MWh"}
        merge_field([row], [SOURCE], SLOTS["year"], {"answers": {"R1": bad}})
        assert row.claim["year"] == 2022
        assert state(row) == fields.READ


def test_route_claims_by_decides_whether_the_quote_or_the_label_settles_it():
    batch = pipeline.Batch(1, None, [pipeline.WorkItem(1, None, SOURCE),
                                     pipeline.WorkItem(1, None, OTHER)])
    claim = {"value": 1, "source": "Q2", "quote": "im Jahr 2030 bei 450 MWh"}
    routed, _ = pipeline.route_claims(batch, [claim])
    assert [len(r) for r in routed] == [1, 0]               # the quote
    with rules.overlaid(route_claims_by="label_first"):
        routed, _ = pipeline.route_claims(batch, [claim])
        assert [len(r) for r in routed] == [0, 1]           # the label


# -- states -------------------------------------------------------------------

def test_state_rules_say_which_state_a_skipped_coordinate_ends_in():
    row = year_row()
    assert pipeline.mark_unanswered([row], [SLOTS["year"]]) == 1
    assert state(row) == fields.UNANSWERED
    with rules.overlaid(state_rules={**rules.default()["state_rules"],
                                     "skipped": "exhausted"}):
        row = year_row()
        pipeline.mark_unanswered([row], [SLOTS["year"]])
        assert state(row) == fields.EXHAUSTED
    with rules.overlaid(state_rules={**rules.default()["state_rules"],
                                     "skipped": "later"}):
        with pytest.raises(rules.RuleError, match="later"):
            fields.state_for("skipped")
    with rules.overlaid(state_rules={"refused": "unbacked"}):
        with pytest.raises(rules.RuleError, match="skipped"):
            fields.state_for("skipped")


def test_state_rules_say_which_state_a_field_without_a_value_ends_in():
    states = trust.parameter_states(SPEC, [], [], harvested=0)
    assert {s["state"] for s in states} == {fields.SAID_UNSTATED}
    changed = {**rules.default()["state_rules"],
               "parameter_silent": "exhausted"}
    with rules.overlaid(state_rules=changed):
        states = trust.parameter_states(SPEC, [], [], harvested=0)
        assert {s["state"] for s in states} == {fields.EXHAUSTED}


def test_open_states_are_one_collection_read_when_asked():
    from docpipe.extraction import conditions, stats, topup
    for place in (fields.OPEN, conditions.OPEN, topup.OPEN, stats.OPEN):
        assert "unbacked" in place and "read" not in place
        assert list(place) == ["exhausted", "unanswered", "unbacked"]
    with rules.overlaid(open_states=["exhausted"]):
        for place in (fields.OPEN, conditions.OPEN, topup.OPEN, stats.OPEN):
            assert "unbacked" not in place and "exhausted" in place
            assert len(place) == 1


def test_derive_from_unit_decides_whether_the_unit_sets_a_coordinate():
    slot = fields.Slot(name="aggregation", kind=fields.CHOICE,
                       derive={"from": "unit", "value": "x"})
    parameter = SimpleNamespace(
        unit_factor=lambda unit: 1, target_of=lambda unit: "MWh",
        unit_target="MWh")
    claim = {"unit": "MWh", "unit_state": fields.READ}
    assert fields.derives(slot, claim, parameter)
    with rules.overlaid(derive_from_unit="ask_only"):
        assert not fields.derives(slot, claim, parameter)


def test_parameter_from_unit_decides_whether_the_unit_names_the_parameter():
    claim = {"value": 450, "unit": "MWh"}
    assert fields.derive_parameter(SPEC, claim) is ENERGY
    with rules.overlaid(parameter_from_unit=False):
        assert fields.derive_parameter(SPEC, claim) is None
        assert fields.parameter_undecidable(SPEC, {"value": 1}) is False
    assert fields.parameter_undecidable(SPEC, {"value": 1}) is True


# -- calculation --------------------------------------------------------------

def test_the_rounding_of_a_calculated_number_is_a_share_of_its_last_place():
    assert verify.printed_rounding(116.1) == pytest.approx(0.05)
    with rules.overlaid(computed_rounding_half_units=1.0):
        assert verify.printed_rounding(116.1) == pytest.approx(0.1)
    raw = {"value": 116.1, "compute": [{"inputs": [1], "expected": 116.14}]}
    assert verify.computed_from_inputs(raw)
    with rules.overlaid(computed_rounding_half_units=0.0):
        assert not verify.computed_from_inputs(raw)


def test_the_float_noise_of_a_calculated_number_is_a_share_of_the_larger():
    raw = {"value": 100.0, "compute": [{"inputs": [1], "expected": 100.6}]}
    assert not verify.computed_from_inputs(raw)
    with rules.overlaid(computed_float_noise=0.01):
        assert verify.computed_from_inputs(raw)


def test_compute_used_if_none_decides_which_numbers_a_row_names():
    question = SimpleNamespace(numbers=["a", "b"])
    answer = {"used": []}
    labels = ["n1", "n2"]
    original = compute.labels
    compute.labels = lambda question: labels
    try:
        assert compute.used_numbers(question, answer) == ["a", "b"]
        with rules.overlaid(compute_used_if_none="none"):
            assert compute.used_numbers(question, answer) == []
        assert compute.used_numbers(question, {"used": ["n2"]}) == ["b"]
    finally:
        compute.labels = original


# -- lookup -------------------------------------------------------------------

def sec(i, text, page=None):
    return Source("section", i, text, {"page": page} if page else {})


def test_pattern_hit_chars_say_how_much_stands_around_a_hit():
    far = "x" * 500 + " needle " + "y" * 500
    plain = lookup.matching([sec(1, far)], "needle", 10_000).hits[0]["line"]
    assert len(plain) < 2 * 60 + 20
    with rules.overlaid(pattern_hit_chars=10):
        short = lookup.matching([sec(1, far)], "needle",
                                10_000).hits[0]["line"]
    assert len(short) < len(plain) and "needle" in short


def test_pattern_timeout_s_is_how_long_one_passage_may_be_tried():
    bomb = [sec(1, "a" * 60 + "b")]
    with rules.overlaid(pattern_timeout_s=0.01):
        assert lookup.matching(bomb, "(a|aa)+$", 10_000).fault == "timeout"
    ok = [sec(1, "a" * 20)]
    assert lookup.matching(ok, "(a|aa)+$", 10_000).fault is None


def test_fetch_next_is_how_many_sections_one_ask_brings():
    docs = [sec(i, f"text {i}") for i in range(1, 6)]
    assert [s.owner_id for s in lookup.fetch_run(docs, ("section", 1),
                                                 True)] == [2]
    with rules.overlaid(fetch_next=3):
        assert [s.owner_id for s in lookup.fetch_run(
            docs, ("section", 1), True)] == [2, 3, 4]
        assert [s.owner_id for s in lookup.fetch_run(
            docs, ("section", 3), False)] == [2, 1]
        assert lookup.fetch_run(docs, ("section", 5), True) == []


def test_compute_fetch_pages_is_how_many_pages_a_fetched_passage_is_cut_to():
    docs = [sec(1, "x" * 1000, 1), sec(2, "y" * 1000, 2)]
    assert lookup.two_pages(docs, 2) == 2000
    with rules.overlaid(compute_fetch_pages=1):
        assert lookup.two_pages(docs, 2) == 1000
    assert lookup.two_pages(docs, 2, span=3) == 3000


def test_table_continues_pages_is_how_far_back_a_table_looks():
    head = "| a | b |\n|---|---|\n"
    first = Source("table", 1, "Tabelle\n" + head + "| 1 | 2 |",
                   {"page": 3})
    second = Source("table", 2, "| 3 | 4 |", {"page": 5})

    def marked():
        return "table_before" in (lookup.continued(
            [first, second])[1].provenance or {})
    assert not marked()
    with rules.overlaid(table_continues_pages=2):
        assert marked()
    near = Source("table", 2, "| 3 | 4 |", {"page": 4})
    assert "table_before" in lookup.continued([first, near])[1].provenance
    with rules.overlaid(table_continues_pages=0):
        assert "table_before" not in lookup.continued(
            [first, near])[1].provenance


# -- documents ----------------------------------------------------------------

def test_found_stale_fallback_decides_what_a_run_does_with_a_lost_place(
        tmp_path):
    from test_found_places import HEADING, TABLE, found_in, harvest, \
        stored_tuple, READ_IN_HEADING
    harvest(tmp_path / "a", stored_tuple(**READ_IN_HEADING))
    known = found_in(tmp_path / "a", holds=(TABLE,))
    assert known.passages(7) == []                        # planned in full
    stopped = found_in(tmp_path / "a", holds=(TABLE,))
    with rules.overlaid(found_stale_fallback="stop"):
        with pytest.raises(RuntimeError, match="found_stale_fallback"):
            stopped.passages(7)
    whole = found_in(tmp_path / "a", holds=(TABLE, HEADING))
    with rules.overlaid(found_stale_fallback="stop"):
        assert whole.passages(7)


def test_stale_keys_say_which_kinds_of_questions_make_a_document_stale():
    every = spec_module.fingerprints(SPEC)
    assert {key.split("/")[0] for key in every} == {
        "slot", "parameter", "axis"}
    with rules.overlaid(stale_keys=["axis"]):
        only = spec_module.fingerprints(SPEC)
    assert {key.split("/")[0] for key in only} == {"axis"}
    assert all(only[key] == every[key] for key in only)
    with rules.overlaid(stale_keys=[]):
        assert spec_module.fingerprints(SPEC) == {}


def test_the_harvest_schema_fixes_no_quote_length_and_has_a_trace_rule():
    harvest = json.dumps(schema.build(SPEC)["harvest"])
    assert '"minLength": 8' not in harvest
    trace = schema.build(SPEC)["trace"]
    assert '"maxLength": 300' in json.dumps(trace)
    with rules.overlaid(trace_quote_chars=120):
        assert '"maxLength": 120' in json.dumps(schema.build(SPEC)["trace"])


def test_quote_min_chars_is_not_fixed_in_the_schema_but_held_by_the_check():
    short = {"value": 2030, "quote": "Jahr 2030"}
    row, got = ask_year(short)
    assert state(row) == fields.READ                        # 9 characters
    with rules.overlaid(quote_min_chars=10):
        row, got = ask_year(short)
        assert got["failed"][0]["why"] == "quote_too_short"
    assert '"minLength": 10' not in json.dumps(schema.build(SPEC)["harvest"])


def test_drop_repeats_and_repeat_key_decide_what_a_repeated_row_is():
    def report():
        base = {"value": 1, "quote": "q", "provenance": {"page": 1}}
        other = {"value": 1, "quote": "q", "provenance": {"page": 2}}
        return pipeline.DocumentReport(1, [base, other])
    one = report()
    assert pipeline.drop_repeats(one) == 1
    with rules.overlaid(drop_repeats=False):
        none = report()
        assert pipeline.drop_repeats(none) == 0 and len(none.tuples) == 2
    with rules.overlaid(repeat_key=[]):
        every = report()
        assert pipeline.drop_repeats(every) == 0


# -- trust --------------------------------------------------------------------

def row(**more):
    found = {"parameter": "energy", "value": 1, "unit": "MWh", "quote": "q",
             "tier": "text_located", "flags": [], "year": 2030,
             "year_state": "read", "carrier_state": "read",
             "carrier": "x", "unit_state": "read",
             "parameter_state": "derived"}
    found.update(more)
    return found


def test_trust_reason_levels_say_which_level_a_reason_gives():
    assert trust.trust(row(carrier_state="unbacked"))["level"] == "D"
    levels = {**rules.default()["trust_reason_levels"], "unbacked": "C"}
    with rules.overlaid(trust_reason_levels=levels):
        assert trust.trust(row(carrier_state="unbacked"))["level"] == "C"
    only = {"exhausted": "C"}
    with rules.overlaid(trust_reason_levels=only):
        # unbacked is no reason there at all
        assert trust.trust(row(carrier_state="unbacked"))["level"] == "A"
        assert trust.trust(row(carrier_state="unbacked"))["reasons"] == []
    bad = {"unbacked": "Z"}
    with rules.overlaid(trust_reason_levels=bad):
        with pytest.raises(rules.RuleError, match="unbacked"):
            trust.trust(row(carrier_state="unbacked"))


def test_the_levels_of_flags_and_a_conflict_come_from_the_same_table():
    assert trust.trust(row(flags=["read_off"]))["level"] == "C"
    assert trust.trust(row(), conflict=True)["level"] == "D"
    levels = {**rules.default()["trust_reason_levels"], "read_off": "D",
              "conflict": "B"}
    with rules.overlaid(trust_reason_levels=levels):
        assert trust.trust(row(flags=["read_off"]))["level"] == "D"
        assert trust.trust(row(), conflict=True)["level"] == "B"


def test_trust_image_cap_is_the_best_level_of_an_image():
    image = row(tier="visual_source")
    assert trust.trust(image)["level"] == "B"
    assert trust.trust(row(), transcribed=True)["level"] == "B"
    with rules.overlaid(trust_image_cap="C"):
        assert trust.trust(image)["level"] == "C"
        assert trust.trust(row())["level"] == "A"
    with rules.overlaid(trust_image_cap="A"):
        assert trust.trust(image)["level"] == "A"


def test_review_levels_say_which_levels_a_person_looks_at():
    verdict = trust.trust(row(carrier_state="exhausted"))
    assert ("review", {}) in trust.marks(verdict)
    with rules.overlaid(review_levels=["D"]):
        assert ("review", {}) not in trust.marks(verdict)
        assert trust.REVIEW_LEVELS == ("D",)
    assert trust.OPEN_STATES == ("exhausted", "unanswered")


def test_evidence_tiers_say_how_well_a_kind_of_place_backs_a_value():
    parameter = ENERGY
    raw = {"value": 450, "unit": "MWh", "unit_raw": "MWh", "year": 2030,
           "quote": "im Jahr 2030 bei 450 MWh"}
    assert verify.verify_tuple(dict(raw), parameter, TEXT,
                               owner_kind="table").tier == "visual_source"
    assert verify.verify_tuple(dict(raw), parameter, TEXT).tier == \
        "text_located"
    tiers = {"section": "text_located", "table": "text_located",
             "figure": "visual_source"}
    with rules.overlaid(evidence_tiers=tiers):
        assert verify.verify_tuple(dict(raw), parameter, TEXT,
                                   owner_kind="table").tier == "text_located"
    with rules.overlaid(evidence_tiers={"section": "text_located"}):
        assert verify.verify_tuple(dict(raw), parameter, TEXT,
                                   owner_kind="figure").tier == \
            "visual_source"
    with rules.overlaid(evidence_tiers={"section": "gold"}):
        with pytest.raises(ValueError, match="gold"):
            verify.verify_tuple(dict(raw), parameter, TEXT)


# -- today's standards --------------------------------------------------------

def test_every_rule_of_taking_has_its_standard_and_its_decision_is_named():
    from docpipe.ruleset import taking
    standard = rules.default()
    for one in taking.RULES:
        assert one.name in standard.values, one.name
        assert rules.problem(one.name, standard[one.name]) is None, one.name
    decided = {one.name: one.decided for one in taking.RULES if one.decided}
    assert decided["outside_list"] == "2026-09-11"
    assert decided["answer_in_quote_spellings"] == "2026-09-13"
    assert decided["refused_keeps_quote"] == "2026-09-12"
    assert decided["sign_belongs"] == "2026-11-01"
    assert decided["computed_from_inputs"] == "2026-11-03"
    assert standard["thousands_spaces"] == "   "
    assert standard["repeat_key"] == ["provenance"]


def test_what_is_made_from_a_rule_is_made_again_for_a_step_that_sets_it():
    node = {"id": "x", "box": "coord"}
    text = "rund 45 000 MWh"
    assert "45000" in verify.numbers_in(text)
    with rules.in_step(rules.stepped(node, {"thousands_spaces": ""})):
        assert "45000" not in verify.numbers_in(text)
    assert "45000" in verify.numbers_in(text)
    with rules.in_step(rules.stepped(node, {"minus_signs": "~"})):
        assert "-5" not in verify.numbers_in("Wert -5 GWh")
        assert "-5" in verify.numbers_in("Wert ~5 GWh")
    assert "-5" in verify.numbers_in("Wert -5 GWh")
