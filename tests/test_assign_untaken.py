"""
Each number of a table or figure that no field's question took is asked which
field of the list that reads numbers it is, or none (owner decision
2026-11-17, from the literature on reading numbers: find every number first,
then ask each one no question took); where a field is named the number goes
on as a find of that field, so that its coordinates and checks are those of
every value.

The promises, each with a case that breaks it by construction:

1. A cell of a table no value took is asked once, AND a field named makes it
   a value of that field at the address of its line and cell, with the words
   as printed and its line as the quote.
2. 0 makes no value, AND the rule `ask_untaken` off asks nothing.
3. A cell a value took is not asked, AND a taken cell stays the value of the
   field that took it.
4. An answer outside the list is asked again with its reason
   (`not_an_option`), AND never becomes a value.
5. A figure's line of numbers is asked once for each number it prints other
   than a year, AND a line a value stands at is not asked.
6. The numbers asked, named and none are counted for the document, AND the
   run's statistic adds them.
7. The request shows the number's line with its table's title and head, the
   fields that read numbers numbered from 1, AND no field that reads no
   number.
8. A profile without the prompt `assign` asks nothing, AND the three
   profiles' flows and prompts hold the step.
"""
import json
from pathlib import Path

import pytest

from docpipe import rules
from docpipe.extraction import addressed, stats, trace
from docpipe.extraction.addressed import Asks, Counts, Plan
from docpipe.extraction.spec import load as load_spec

from test_addressed import (CAPTION, ENERGY, FIGURE, SPEC, TABLE, TEXT,
                            Model, plan_of, reader_of)

ROOT = Path(__file__).resolve().parent.parent
ONE = {"entry": 1}
NONE = {"entry": 0}


class AssignModel(Model):
    """The model of the addressed tests with the `assign` request, answered
    by *assign (payload, noted)*."""
    def __init__(self, assign=lambda p, n: ONE, **replies):
        super().__init__(**replies)
        self.replies["assign"] = assign

    def asks(self, check: bool = True) -> Asks:
        got = super().asks(check)

        def assign(payload, document_id, /, *, shape, example, **noted):
            self.calls.append(("assign", payload, noted))
            self.examples.append(("assign", example))
            return self.replies["assign"](payload, noted)
        got.assign = assign
        return got


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    with rules.overlaid(find_again_below=0):
        yield
    rules.reset()


def read(model, *sources, plan=None, counts=None, **overlay):
    with rules.overlaid(**overlay):
        reads = reader_of(model)(plan or plan_of(*sources), [ENERGY],
                                 counts=counts)
    return [c for r in reads for c in r.claims]


def cells_of(claims):
    return sorted((c["at"]["line"], c["at"].get("cell")) for c in claims)


def test_a_cell_no_value_took_is_asked_once_and_becomes_a_value_of_the_field():
    model = AssignModel()
    claims = read(model, TABLE, TEXT)
    # The table's four numbers: 1.200, 27, "800 / 750" (its first) and 12;
    # the text has none counted.
    assert [n["value"] for _, n in model.of("assign")] == [
        "1.200", "27", "800", "12"]
    assert cells_of(claims) == [(3, 2), (3, 3), (4, 2), (4, 3)]
    first = next(c for c in claims if c["at"]["line"] == 3
                 and c["at"]["cell"] == 2)
    assert first["value"] == 1200 and first["value_raw"] == "1.200"
    assert first["at"]["owner"] == ["table", 3]
    assert first["quote"].endswith("| Rathaus | 1.200 | 27 |")
    assert first["head"] == "Erdgas MWh/a"
    # The break by construction: no field named, no value.
    assert not read(AssignModel(assign=lambda p, n: NONE), TABLE, TEXT)


def test_none_makes_no_value_and_the_rule_off_asks_nothing():
    model = AssignModel(assign=lambda p, n: NONE)
    assert not read(model, TABLE) and len(model.of("assign")) == 4
    off = AssignModel()
    assert not read(off, TABLE, ask_untaken=False) and not off.of("assign")
    # The break by construction: with the rule on the same model asks and
    # makes values.
    on = AssignModel()
    assert read(on, TABLE) and on.of("assign")


def test_a_cell_a_value_took_is_not_asked():
    def find(payload, noted):
        if payload["passage"]["kind"] != "table":
            return {"found": []}
        return {"found": [{"at": "3.2", "words": "1.200"}]}
    model = AssignModel(find=find)
    claims = read(model, TABLE)
    assert [n["value"] for _, n in model.of("assign")] == ["27", "800", "12"]
    assert cells_of(claims) == [(3, 2), (3, 3), (4, 2), (4, 3)]
    # The break by construction: a find at another cell leaves the cell
    # asked.
    other = AssignModel(find=lambda p, n: {"found": [
        {"at": "3.3", "words": "27"}]} if p["passage"]["kind"] == "table"
        else {"found": []})
    read(other, TABLE)
    assert "1.200" in [n["value"] for _, n in other.of("assign")]
    assert "27" not in [n["value"] for _, n in other.of("assign")]


def test_an_answer_outside_the_list_is_asked_again_and_never_a_value():
    model = AssignModel(assign=lambda p, n: {"entry": 7},
                        follow=lambda p, n: {"entry": 7})
    claims = read(model, TABLE)
    assert not claims
    follows = [(p, n) for p, n in model.of("follow")
               if n["asked"] == "assign"]
    assert len(follows) == 4
    said = json.dumps(follows[0][0]["what"], ensure_ascii=False)
    assert "7" in said
    # The reason is the one a list request gives, no new one.
    assert addressed.NOT_AN_OPTION == "not_an_option"
    # The break by construction: the follow-up that names a field of the
    # list makes the value.
    fixed = AssignModel(assign=lambda p, n: {"entry": 7},
                        follow=lambda p, n: ONE)
    assert read(fixed, TABLE)


def figure_plan(*numbers):
    return Plan(7, [FIGURE], {5: {"caption": CAPTION,
                                  "numbers": list(numbers)}})


def test_a_figure_line_is_asked_for_each_number_other_than_a_year():
    model = AssignModel()
    claims = read(model, plan=figure_plan(
        "Erdgas 2021: 1.200 MWh und Heizöl: 27 MWh"))
    assert [n["value"] for _, n in model.of("assign")] == ["1.200", "27"]
    assert sorted(c["value_raw"] for c in claims) == ["1.200", "27"]
    # The break by construction: a line with one number is asked once, and
    # a line a value stands at is not asked.
    one = AssignModel()
    read(one, plan=figure_plan("Erdgas: 1.200 MWh"))
    assert len(one.of("assign")) == 1

    def find(payload, noted):
        return {"found": [{"at": "2", "words": "1.200"}]} \
            if payload["passage"]["kind"] == "figure" else {"found": []}
    taken = AssignModel(find=find)
    read(taken, plan=figure_plan("Erdgas: 1.200 MWh"))
    assert not taken.of("assign")


def test_the_numbers_asked_named_and_none_are_counted_and_added():
    answers = iter([ONE, NONE, ONE, NONE])
    model = AssignModel(assign=lambda p, n: next(answers))
    counts = Counts()
    read(model, TABLE, counts=counts)
    assert dict(counts.assigned) == {"asked": 4, "named": 2, "none": 2}
    # The break by construction: with the rule off nothing is counted.
    off = Counts()
    read(AssignModel(), TABLE, counts=off, ask_untaken=False)
    assert not off.assigned


def test_the_statistic_adds_the_documents_numbers_asked(tmp_path):
    for name, asked, named, none in (("a", 4, 3, 1), ("b", 2, 0, 2)):
        path = tmp_path / f"{name}{trace.PLAIN}"
        path.write_text(json.dumps({"t": "assigned", "asked": asked,
                                    "named": named, "none": none}) + "\n",
                        encoding="utf-8")
    got = stats.from_traces([tmp_path])["numbers_assigned"]
    assert got == {"documents": 2, "asked": 6, "named": 3, "none": 3}
    # The break by construction: a trace without the event adds nothing.
    assert stats.from_traces([tmp_path / "none"])["numbers_assigned"] == {
        "documents": 0, "asked": 0, "named": 0, "none": 0}


def test_the_request_shows_the_line_its_head_and_the_numbered_fields():
    model = AssignModel(assign=lambda p, n: NONE)
    read(model, TABLE)
    payload, noted = model.of("assign")[0]
    assert payload["value"] == {"words": "1.200", "at": "3.2"}
    lines = payload["passage"]["lines"]
    assert any("Erdgas MWh/a" in line for line in lines)
    assert any("| Rathaus | 1.200 | 27 |" in line for line in lines)
    assert payload["passage"]["title"].startswith("Tabelle 4")
    assert len(payload["list"]) == 1
    assert payload["list"][0].startswith("1 Energieverbrauch")
    assert ("assign", {"entry": 1}) in model.examples
    assert noted["value"] == "1.200"
    # The break by construction: a spec whose only field reads no number
    # offers no list and asks nothing.
    words = load_spec({
        "coordinates": {"order": ["year"], "own_passage": ["year"]},
        "parameters": [{"uri": "name", "label": "Name",
                        "description": "Der Name der Gemeinde, für die der "
                                       "Plan aufgestellt wurde, wie er ihn "
                                       "druckt.",
                        "value_type": "text",
                        "axes": {"year": {"type": "int", "question":
                                          "Für welches Jahr gilt diese "
                                          "Angabe?"}},
                        "example": {"source": "Die Stadt Musterstadt legt "
                                              "ihren Plan vor.",
                                    "tuples": [{"value": "Musterstadt",
                                                "quote": "Die Stadt "
                                                         "Musterstadt legt"
                                                }]}}]})
    plain = AssignModel()
    with rules.overlaid():
        reader_of(plain, words)(plan_of(TABLE), [words.by_uri["name"]])
    assert not plain.of("assign")


def test_a_profile_without_the_prompt_asks_nothing_and_every_profile_has_it():
    model = AssignModel()
    reader = reader_of(model)
    reader.asks.assign = None
    assert not [c for r in reader(plan_of(TABLE), [ENERGY])
                for c in r.claims]
    assert not model.of("assign")
    assert "assign" in addressed.OPTIONAL and "assign" in addressed.KINDS
    for place in ("docpipe/builtin/default", "profiles/kwp",
                  "profiles/scenarios"):
        text = (ROOT / place / "prompts" / "extraction" / "assign.md"
                ).read_text(encoding="utf-8")
        assert "{{example}}" in text and "`" not in text.replace(
            "No Backticks", "")
        flow = json.loads((ROOT / place / "flow.json").read_text(
            encoding="utf-8"))
        ids = [s.get("id") for s in flow["flow"]]
        assert ids.index("in_pieces") < ids.index("untaken_numbers") \
            < ids.index("values")
        frame = flow["flow"][ids.index("untaken_numbers")]
        assert frame["each"] == "list" and frame["list"] == "untaken"
        assert frame["steps"][0]["preset"] == "assign"
