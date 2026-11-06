"""A plan's base and target years are asked once per plan (owner decision
2026-11-06): the request lists first the passages the survey found a pair of
either state in, else the plan's first passages; a year counts only with a
quote the request showed that prints it, AND one that does not is told once
by its state and taken when the second reply backs it; a pair of a single
page is no year of the plan.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

from docpipe.extraction import fields, years
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
FRAME = fields.frame_slots(SPEC, ("scenario", "year"))
STATES = {"base": {"scenario": "status_quo"}, "target": {"scenario": "target"}}

STAND = Source("section", 1, "Bestandsanalyse\nDas Basisjahr ist das Jahr "
               "2022.", {"section_title": "Bestandsanalyse", "page": 15})
ZIEL = Source("section", 2, "Zielszenario\nDie Stadt will bis 2040 "
              "klimaneutral sein.", {"section_title": "Zielszenario",
                                     "page": 60})
SHEET = Source("table", 3, "Steckbrief Gebiet 4\n| Bedarf Bestand | Bedarf "
               "2040 |\n| --- | --- |\n| 12 | 9 |",
               {"title": "Steckbrief Gebiet 4", "page": 90})
PLAN = {("section", 1): STAND, ("section", 2): ZIEL, ("table", 3): SHEET}
# The pair a profile sheet gave the survey: "Bestand 2040".
SHEET_PAIR = {"scenario": "Bestand", "scenario_quote": "Bedarf Bestand",
              "scenario_source": ["table", 3], "year": 2040,
              "year_quote": "Bedarf 2040", "year_source": ["table", 3]}
BASE = {"value": 2022, "quote": "Das Basisjahr ist das Jahr 2022"}
TARGET = {"value": 2040, "quote": "bis 2040 klimaneutral"}


def asker(*replies):
    asked = []

    def ask(payload, document_id, corrections=0):
        asked.append(payload)
        return replies[min(len(asked), len(replies)) - 1]
    return years.PlanYears(ask, FRAME, STATES), asked


def test_the_plan_s_years_are_read_with_a_quote_that_prints_them():
    # The sheet names no year of the plan; the next passages are listed.
    plan, asked = asker({"base_years": [], "target_years": []},
                        {"base_years": [BASE], "target_years": [TARGET]})
    got = plan(7, PLAN, [SHEET_PAIR])
    assert [(y["state"], y["year"], y["source"]) for y in got] == [
        ("base", 2022, ["section", 1]), ("target", 2040, ["section", 2])]
    # The survey's pair of a single page is where the search starts, never
    # a year of the plan.
    assert [hit["title"] for hit in asked[0]["hits"][0]["hits"]] == [
        "Steckbrief Gebiet 4"]
    assert len(asked) == 2 and len(asked[1]["hits"]) == 2
    assert not any(y["state"] == "base" and y["year"] == 2040 for y in got)
    # Without a pair the request starts at the plan's first passages.
    plan, asked = asker({"base_years": [BASE], "target_years": [TARGET]})
    assert len(plan(7, PLAN, [])) == 2 and len(asked) == 1
    assert [hit["title"] for hit in asked[0]["hits"][0]["hits"]] == [
        "Bestandsanalyse", "Zielszenario", "Steckbrief Gebiet 4"]


def test_a_year_its_quote_does_not_print_is_told_once_by_its_state():
    wrong = {"value": 2021, "quote": BASE["quote"]}
    plan, asked = asker({"base_years": [wrong], "target_years": [TARGET]},
                        {"base_years": [BASE], "target_years": [TARGET]})
    got = plan(7, PLAN, [])
    assert [c["state"] for c in asked[1]["corrections"]] == ["base_years"]
    assert sorted((y["state"], y["year"]) for y in got) == [
        ("base", 2022), ("target", 2040)]
    # Told once: what the second reply still gets wrong is no year.
    plan, asked = asker({"base_years": [wrong], "target_years": []})
    assert plan(7, PLAN, []) == [] and len(asked) == 2


def test_a_quote_from_nothing_the_request_showed_is_no_year():
    unseen = {"value": 2045, "quote": "Ziel ist das Jahr 2045"}
    plan, _ = asker({"base_years": [], "target_years": [unseen]})
    assert plan(7, PLAN, []) == []
