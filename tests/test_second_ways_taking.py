"""
The second ways of the taking area (plan section 7, items 12 and 14): a rule
set at a step, or overlaid, changes what the code does, and the standard
gives today's result.

Promises, one sentence each:
1. `sign_belongs` on: "-1.155" backs -1155 and "1.155" does not; off: the
   sign stays outside, so "1.155" backs -1155 as well as 1155.
2. `computed_from_inputs` on: a calculated number that its inputs do not make
   is refused; off: it counts when the code printed it.
3. `computed_same_once` on: two rows with one number are one statement; off:
   they are two.
4. `refused_keeps_quote` dropped: a refused coordinate carries no quote and
   no source; kept: it carries its quote, and its source where one was found,
   and its state still says it is not backed.
"""
import pytest

from docpipe import rules
from docpipe.extraction import fields, verify
from docpipe.extraction.pipeline import Row, Source, merge_field
from profiles.kwp import compute as kwp_compute

from test_addressed import SLOTS
from test_evidence import (PARAMETER, SOURCE as TABLE, claim, SPEC)
from conftest import step_node

TEXT = "Der Endenergieverbrauch liegt im Jahr 2030 bei 450 MWh."
SHOWN = Source("section", 1, TEXT)


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def at(**values):
    return rules.in_step(rules.stepped(step_node("find"), values))


def ask(answer):
    row = Row("R1", 0, {})
    got = merge_field([row], [SHOWN], SLOTS["year"],
                      {"answers": {"R1": answer}})
    return row, got


# -- 1. the sign --

def test_a_printed_sign_belongs_to_the_number_unless_the_rule_says_not():
    negative = {"value": -1155, "unit": "MWh"}
    signed, bare = "| Picher | -1.155 |", "| Picher | 1.155 |"
    assert verify.value_in_quote(negative, PARAMETER, signed)
    assert not verify.value_in_quote(negative, PARAMETER, bare)
    with at(sign_belongs="off"):
        assert verify.value_in_quote(negative, PARAMETER, signed)
        assert verify.value_in_quote(negative, PARAMETER, bare)
        positive = {"value": 1155, "unit": "MWh"}
        assert verify.value_in_quote(positive, PARAMETER, signed)
        assert verify.times_stated(negative, PARAMETER, bare) == 1
        assert not verify.value_in_quote(
            {"value": -1156, "unit": "MWh"}, PARAMETER, bare)
    assert not verify.value_in_quote(negative, PARAMETER, bare)


def test_the_sign_rule_holds_for_the_whole_value_check():
    quote = "| Erdgas | 2.463 | 40,8% |"
    source = "Einsparung\n" + quote
    raw = claim(value=-2463, quote=quote)
    assert isinstance(verify.verify_tuple(raw, PARAMETER, source,
                                          owner_kind="table"),
                      verify.Refusal)
    with rules.overlaid(sign_belongs="off"):
        assert isinstance(verify.verify_tuple(raw, PARAMETER, source,
                                              owner_kind="table"),
                          verify.Verified)


# -- 2. the calculated number --

def test_a_calculated_number_its_inputs_do_not_make_is_refused_unless_off():
    run = {"stdout": "647121189\n", "inputs": [1], "expected": 1.0}
    raw = claim(value=647121189, computed=True, compute=[run])
    got = verify.verify_tuple(raw, PARAMETER, TABLE, owner_kind="table")
    assert isinstance(got, verify.Refusal)
    assert "does not follow" in got.reason
    with at(computed_from_inputs="off"):
        got = verify.verify_tuple(raw, PARAMETER, TABLE, owner_kind="table")
        assert isinstance(got, verify.Verified)
        assert "computed" in got.flags
        # The output that printed it is still asked for.
        unprinted = dict(raw, compute=[dict(run, stdout="1\n")])
        assert isinstance(verify.verify_tuple(
            unprinted, PARAMETER, TABLE, owner_kind="table"),
            verify.Refusal)


# -- 3. the same calculated number --

def test_two_rows_with_one_number_are_one_statement_unless_the_rule_says_not():
    one = {"parameter": "energy_consumption", "value_target": 5.0}
    other = dict(one)
    assert kwp_compute.same(one, other, SPEC) is True
    with at(computed_same_once="off"):
        assert kwp_compute.same(one, other, SPEC) is False
    different = dict(one, value_target=9.0)
    assert kwp_compute.same(one, different, SPEC) is False


# -- 4. the refused coordinate --

def test_a_refused_coordinate_keeps_its_quote_and_source_where_the_rule_says():
    wrong = {"value": 2031, "quote": "im Jahr 2030 bei 450 MWh"}
    row, got = ask(wrong)
    assert row.claim["year_state"] == fields.UNBACKED
    assert "year_quote" not in row.claim and "year_source" not in row.claim
    with at(refused_keeps_quote="kept"):
        row, got = ask(wrong)
        assert row.claim["year_state"] == fields.UNBACKED
        assert row.claim["year_quote"] == wrong["quote"]
        assert row.claim["year_source"] == ["section", 1]
        assert got["failed"][0]["why"] == "answer_not_in_quote"
        # A quote that stands in no shown line has no source to keep.
        row, got = ask({"value": 2030, "quote": "nirgends gedruckt 2030"})
        assert row.claim["year_state"] == fields.UNBACKED
        assert row.claim["year_quote"] == "nirgends gedruckt 2030"
        assert "year_source" not in row.claim
        # A value that is read stays read.
        row, _ = ask({"value": 2030, "quote": "im Jahr 2030 bei 450 MWh"})
        assert row.claim["year_state"] == fields.READ


def test_the_value_that_loses_a_coordinate_keeps_its_quote_where_kept():
    base = claim(carrier="Unbekannt Stoff", carrier_state=fields.READ,
                 carrier_quote="so steht es", carrier_source=["table", 1],
                 carrier_window=["x", 1])
    out = verify.verify_tuple(base, PARAMETER, TABLE, owner_kind="table")
    if not isinstance(out, verify.Verified):
        pytest.skip("the claim is refused before its coordinates settle")
    assert "carrier_quote" not in out.tuple
    with at(refused_keeps_quote="kept"):
        out = verify.verify_tuple(base, PARAMETER, TABLE,
                                  owner_kind="table")
        assert out.tuple["carrier_state"] == fields.UNBACKED
        assert out.tuple["carrier_quote"] == "so steht es"
        assert out.tuple["carrier_source"] == ["table", 1]
        assert "carrier_window" not in out.tuple


# -- the declarations --

def test_the_rules_name_the_second_way_and_the_standard_is_today():
    standard = rules.default()
    assert standard["sign_belongs"] == "on"
    assert standard["refused_keeps_quote"] == "dropped"
    assert standard["computed_from_inputs"] == "on"
    for name, other in (("sign_belongs", "off"),
                        ("refused_keeps_quote", "kept"),
                        ("computed_from_inputs", "off")):
        assert rules.problem(name, other) is None, name
    assert rules.problem("sign_belongs", "sideways") is not None
