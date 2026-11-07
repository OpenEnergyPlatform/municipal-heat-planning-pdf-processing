"""The check of a comb find (combing.py, owner decision 2026-11-07).

Promise: a find quoted from a passage other than the value's own and its
section gets one more request that asks whether that place speaks about the
value, AND a "no" takes the find out, so the search goes on, AND every request
after it says why, AND a "yes" keeps it; a find from the value's own passage
gets no such request, AND neither does one the check of its quote and answer
refuses anyway; a find given again is not asked about twice; and a reply that
answers neither "yes" nor "no" is asked once more, told why.

Each promise has a case that breaks it by construction beside the one that
keeps it.
"""
import json
from pathlib import Path

from docpipe.extraction import combing, fields, reading
from docpipe.extraction.pipeline import Batch, Source, WorkItem
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = [slot.name for slot in reading.slots_of(SPEC, EMISSION)]

OWN = Source("section", 6, "Bilanz\nEs fielen im Jahr 2022 rund 300 t CO2 an.",
             {"document_id": 7, "section_title": "Bilanz"})
SECTIONS = [Source("section", 100 + i,
                   f"S{i}\nDie Werte gelten für das Jahr {2000 + i}.", {})
            for i in range(20)]
PLAN = {("section", 6): OWN,
        **{(s.owner_kind, s.owner_id): s for s in SECTIONS}}
# What a reading that found the year unstated wrote to it.
SAID = {"year": "Die Emissionen gelten für das Jahr 2022."}


def year_open():
    """A value of OWN whose year alone is open."""
    out = {"source": "Q1", "value": 300, "quote": "rund 300 t CO2",
           "unit": "t CO2"}
    for name in SLOTS:
        out[f"{name}_state"] = fields.READ
    out["year_state"] = fields.SAID_UNSTATED
    return out


def year(value: int, quote: str) -> dict:
    return {"year": {"value": value, "quote": quote}}


def from_section(i: int) -> dict:
    return year(2000 + i, f"Die Werte gelten für das Jahr {2000 + i}.")


def comber(replies: list, verdicts: list, checked_too: bool = True):
    asked, checked = [], []

    def ask(payload, shape, document_id, source, group=None, example=None):
        asked.append(payload)
        return replies[min(len(asked), len(replies)) - 1]

    def check(payload, shape, document_id, source, group=None, example=None):
        checked.append(payload)
        return verdicts[min(len(checked), len(verdicts)) - 1]

    def rank(document_id, probes, exclude):
        return [s for s in SECTIONS if (s.owner_kind, s.owner_id) not in exclude]

    made = combing.Comber(SPEC, ask, rank, lambda claim, names: {},
                          check=check if checked_too else None)
    return made, asked, checked


def combed(made):
    batch = Batch(7, EMISSION, [WorkItem(7, EMISSION, OWN)])
    read = [reading.Read(batch, [year_open()], probes=[SAID])]
    (done,) = made(7, read, PLAN, [])
    return read[0].claims[0], done


def test_a_find_from_another_passage_is_checked_and_kept_on_yes():
    made, asked, checked = comber([from_section(3)], [{"about": "yes"}])
    value, done = combed(made)
    assert value["year"] == 2003 and value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 103]
    assert len(checked) == 1 and done.judged == 1 and done.turned == 0
    # The check shows the place the quote stands in and what was found.
    assert "2003" in checked[0]["place"]["text"]
    assert checked[0]["answer"]["value"] == 2003
    assert checked[0]["row"]["quote"] == "rund 300 t CO2"


def test_a_no_takes_the_find_out_and_the_search_goes_on_told_why():
    made, asked, checked = comber([from_section(3), from_section(17)],
                                  [{"about": "no"}, {"about": "yes"}])
    value, done = combed(made)
    assert value["year"] == 2017 and value["year_source"] == ["section", 117]
    assert done.turned == 1 and done.judged == 2 and done.listed == 1
    assert "corrections" not in asked[0]
    assert asked[1]["corrections"]["what"]["year"] == say(
        "not_about_value", answer=2003)
    # The failure by construction: without the check the first find stands.
    made, _, _ = comber([from_section(3)], [], checked_too=False)
    value, _ = combed(made)
    assert value["year"] == 2003 and value["year_state"] == fields.READ


def test_a_find_turned_and_given_again_is_not_asked_about_twice():
    made, asked, checked = comber([from_section(3)], [{"about": "no"}])
    value, done = combed(made)
    # Given in every reply, turned once and then left out: the plan is
    # listed to its end and the year is unstated.
    assert len(checked) == 1 and done.turned == 1
    assert value["year_state"] == fields.SAID_UNSTATED
    assert all(payload["corrections"]["what"]["year"]
               == say("not_about_value", answer=2003)
               for payload in asked[1:])


def test_a_find_from_the_value_s_own_passage_is_not_checked():
    own = year(2022, "Es fielen im Jahr 2022 rund 300 t CO2 an.")
    made, _, checked = comber([own], [{"about": "no"}])
    value, done = combed(made)
    assert checked == [] and done.judged == 0
    assert value["year"] == 2022 and value["year_source"] == ["section", 6]
    # The failure by construction: a find from another passage is checked.
    made, _, checked = comber([from_section(3)], [{"about": "yes"}])
    combed(made)
    assert len(checked) == 1


def test_a_find_the_check_of_quote_and_answer_refuses_is_not_checked():
    # The quote lacks its answer, or stands in nothing the request showed:
    # refused with their own corrections, never asked about.
    for wrong in (year(2005, "Die Werte gelten für das Jahr 2003."),
                  year(2003, "Die Emissionen gelten für 2022 und 2003.")):
        made, asked, checked = comber([wrong], [{"about": "no"}])
        value, done = combed(made)
        assert checked == [] and done.judged == 0
        told = [payload["corrections"]["what"]["year"] for payload in asked
                if payload.get("corrections")]
        assert told and say("not_about_value",
                            answer=wrong["year"]["value"]) not in told
        assert value["year_state"] != fields.READ


def test_an_answer_that_is_neither_yes_nor_no_is_asked_again_told_why():
    made, _, checked = comber([from_section(3)],
                              [{"about": "maybe"}, {"about": "yes"}])
    value, done = combed(made)
    assert len(checked) == 2 and done.judged == 2
    assert "corrections" not in checked[0]
    assert checked[1]["corrections"] == {"what": {"about": say(
        "verdict_not_an_option", given="maybe")}}
    assert value["year"] == 2003 and value["year_state"] == fields.READ
    # Neither answer twice: no verdict, the find stands as before the check.
    made, _, checked = comber([from_section(3)],
                              [{"about": "maybe"}, {"about": "perhaps"}])
    value, done = combed(made)
    assert len(checked) == 2 and done.turned == 0
    assert value["year"] == 2003


def test_the_check_answers_one_of_two_words():
    schema = combing.check_response_format()["json_schema"]["schema"]
    assert schema["properties"]["about"]["enum"] == ["yes", "no"]
    assert schema["required"] == ["about"]
    assert combing.check_example() == {"about": "yes"}


def test_a_long_place_is_shown_around_its_quote():
    text = "x" * 500 + " Die Werte gelten für das Jahr 2003. " + "y" * 500
    shown = combing.place_text(text, "Die Werte gelten für das Jahr 2003.", 100)
    assert len(shown) == 100 and "Die Werte gelten für das Jahr 2003." in shown
    assert combing.place_text("kurz", "kurz", 100) == "kurz"
