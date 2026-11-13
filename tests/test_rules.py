"""
The rules a run follows stand in files of the profile (docpipe/rules.py,
owner 2026-11-10: "Alle Regeln etc. sollen auch immer über die GUI
Editierbar sein").

The promises, each with a case that breaks it by construction:

1. The code knows no value: every rule of the core stands in the default
   profile's file, AND a file naming a rule the code does not know is
   refused, AND one leaving a rule of the core out is.
2. A rule set in a file reaches the run: a quote of 7 characters is too
   short with the rule at 8 and long enough with it at 7, AND a profile that
   says nothing of a rule reads the default's, AND a setting wins over the
   file and says so.
3. A profile's own rules are its own: the scenario profile's rules are not
   rules of KWP, AND its code reads them where another profile is the
   ambient one.
4. What a profile writes is laid over what it extends rule by rule: KWP's
   decimal comma, the default's point for the scenarios.
"""
import json

import pytest

from docpipe import rules
from docpipe.extraction import verify
from docpipe.profile import load_profile

from test_addressed import ENERGY


def test_every_rule_of_the_core_stands_in_the_default_file():
    raw = rules.DEFAULT.read_text(encoding="utf-8")
    said = rules.parse(raw, rules.DEFAULT, needed=tuple(rules.BY_NAME))
    assert set(said) == set(rules.BY_NAME)
    # the failures by construction: a rule the code does not know, one left
    # out
    data = json.loads(raw)
    data["rules"]["quote_min_char"] = 8
    with pytest.raises(rules.RuleError, match="quote_min_chars"):
        rules.parse(json.dumps(data), "x", needed=tuple(rules.BY_NAME))
    data = json.loads(raw)
    del data["rules"]["decimal_mark"]
    with pytest.raises(rules.RuleError, match="names no decimal_mark"):
        rules.parse(json.dumps(data), "x", needed=tuple(rules.BY_NAME))


def test_a_value_of_the_wrong_kind_or_out_of_bounds_is_refused():
    assert rules.problem("quote_min_chars", 0) is not None
    assert rules.problem("quote_min_chars", True) is not None
    assert rules.problem("decimal_mark", ";") is not None
    assert rules.problem("year_range", [2100, 1900]) is not None
    assert rules.problem("fetches", ["next", "elsewhere"]) is not None
    assert rules.problem("compute_shown", {"table": -1}) is not None
    assert rules.problem("quote_min_chars", 8) is None
    assert rules.problem("year_range", None) is None


PARAMETER = ENERGY


def test_a_rule_set_in_a_file_reaches_the_run():
    raw = {"value": 1200, "value_raw": "1.200", "quote": "1.200 W"}
    with rules.overlaid(quote_min_chars=8):
        assert verify.value_refused(raw, PARAMETER, "Es sind 1.200 W.") \
            == verify.QUOTE_TOO_SHORT
    with rules.overlaid(quote_min_chars=7):
        assert verify.value_refused(raw, PARAMETER, "Es sind 1.200 W.") \
            is None


def test_a_profile_reads_what_it_sets_and_the_default_s_for_the_rest(
        monkeypatch):
    kwp = rules.load(load_profile("kwp"), environ={})
    scenarios = rules.load(load_profile("scenarios"), environ={})
    assert kwp["decimal_mark"] == "," and scenarios["decimal_mark"] == "."
    assert kwp.owners["decimal_mark"] == "rules.json of kwp"
    assert scenarios.owners["decimal_mark"] == "rules.json of default"
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    assert verify.canonical_number("3,251") == "3.251"
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    assert verify.canonical_number("3,251") == "3251"


def test_a_setting_wins_over_the_file_and_says_so():
    taken = rules.load(load_profile("kwp"),
                       environ={"EXTRACT_RETRY_WAIT": "4"})
    assert taken["retry_wait_s"] == 4.0
    assert taken.owners["retry_wait_s"] == "environment"
    plain = rules.load(load_profile("kwp"), environ={})
    assert plain["retry_wait_s"] == 2
    with pytest.raises(rules.RuleError, match="EXTRACT_RETRY_WAIT"):
        rules.load(load_profile("kwp"), environ={"EXTRACT_RETRY_WAIT": "x"})


def test_a_profile_s_own_rules_are_its_own(monkeypatch):
    assert "world_labels" in rules.registry(load_profile("scenarios"))
    assert "world_labels" not in rules.registry(load_profile("kwp"))
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    with pytest.raises(rules.RuleError):
        rules.get("world_labels")
    assert "global" in rules.get("world_labels", "scenarios")


def test_the_file_is_written_in_one_form():
    text = rules.DEFAULT.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert rules.dump(json.loads(text)["rules"]) == text
    # a character nobody sees is written as its code
    assert "\\u00ad" in text
