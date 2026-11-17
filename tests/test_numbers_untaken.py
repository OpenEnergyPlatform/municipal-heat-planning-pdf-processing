"""
The run counts the numbers of a document's tables and figures that no value
took (owner decision 2026-11-17, from the literature on reading numbers:
find every number first, then see which no question took). Counted only:
nothing is asked or left out for it.

The promises, each with a case that breaks it by construction:

1. A number is a cell of a table's row or a line of a figure's numbers that
   prints a number other than a year, AND a title, a head or a year is none.
2. A value takes the cell its address names, AND without a cell the numbers
   of its line that print its words, AND a figure's line it stands at.
3. The run's statistic adds the counts of each document per kind and lists
   the documents with the most untaken numbers first.
4. The events the run writes for it, "untaken" and "assigned" (the step
   that asks those numbers), are records the published trace schema takes,
   AND a record with a key the schema does not name is refused.
"""
import json

import jsonschema
import pytest

from docpipe.extraction import addressed, schema, stats, trace
from docpipe.extraction.addressed import Plan
from docpipe.extraction.units import Line

from test_addressed import CAPTION, FIGURE, NUMBERS, TABLE, TEXT, plan_of


def line_of(plan, owner, words):
    return next(line.number for line in plan.passages[owner].lines
                if words in line.text)


def test_a_number_is_a_cell_or_a_figure_line_other_than_a_year():
    assert addressed.printed_numbers(Line(3, "| Rathaus | 1.200 | 27 |",
                                          ("Rathaus", "1.200", "27"),
                                          "body")) \
        == [(2, "1.200"), (3, "27")]
    assert addressed.printed_numbers(Line(3, "| 2020 | 1.200 |",
                                          ("2020", "1.200"), "body")) \
        == [(2, "1.200")]
    assert addressed.printed_numbers(Line(2, "| Gebäude | 2020 | 2030 |",
                                          ("Gebäude", "2020", "2030"),
                                          "head")) == []
    assert addressed.printed_numbers(Line(4, "Erdgas: 1.200 MWh", (),
                                          "number")) \
        == [(None, "Erdgas: 1.200 MWh")]
    assert addressed.printed_numbers(Line(1, "Tabelle 4: Verbrauch 2021", (),
                                          "title")) == []


def test_a_value_takes_its_cell_or_its_words_in_its_line():
    plan = plan_of(TABLE, TEXT)
    rathaus = line_of(plan, ("table", 3), "Rathaus")
    schule = line_of(plan, ("table", 3), "Schule")
    # Four numbers: 1.200 and 27, "800 / 750" and 12; the text has none
    # counted, it is no table.
    none = addressed.numbers_untaken(plan, [])
    assert none == {"kinds": {"table": {"passages": 1, "numbers": 4,
                                        "untaken": 4}},
                    "passages": [["table", 3, 4, 4]]}
    got = addressed.numbers_untaken(plan, [
        {"at": {"owner": ["table", 3], "line": rathaus, "cell": 2}},
        {"at": {"owner": ["table", 3], "line": schule},
         "value_raw": "750"}])
    assert got["kinds"]["table"]["untaken"] == 2
    assert got["passages"] == [["table", 3, 2, 4]]
    # The break by construction: a value of another passage takes nothing
    # here, and words its line does not print take nothing either.
    got = addressed.numbers_untaken(plan, [
        {"at": {"owner": ["table", 9], "line": rathaus, "cell": 2}},
        {"at": {"owner": ["table", 3], "line": schule},
         "value_raw": "999"}])
    assert got["kinds"]["table"]["untaken"] == 4


def test_a_figure_s_number_is_taken_by_a_value_at_its_line():
    plan = Plan(7, [FIGURE], {5: {"caption": CAPTION, "numbers": NUMBERS}})
    gas = line_of(plan, ("figure", 5), "Erdgas")
    got = addressed.numbers_untaken(plan, [
        {"at": {"owner": ["figure", 5], "line": gas}, "value_raw": "1.200"}])
    assert got["kinds"]["figure"] == {"passages": 1, "numbers": 2,
                                      "untaken": 1}


def test_the_statistic_adds_the_documents_and_lists_the_most_first(
        tmp_path):
    for name, untaken in (("a", 1), ("b", 5)):
        path = tmp_path / f"{name}{trace.PLAIN}"
        path.write_text(json.dumps({
            "t": "untaken", "kinds": {
                "table": {"passages": 2, "numbers": 10,
                          "untaken": untaken}},
            "passages": [["table", 3, untaken, 10]]}) + "\n",
            encoding="utf-8")
    got = stats.from_traces([tmp_path])["numbers_untaken"]
    assert got["by_kind"] == {"table": {"passages": 4, "numbers": 20,
                                        "untaken": 6}}
    assert [d["document"] for d in got["by_document"]] == ["b", "a"]
    assert got["by_document"][0]["table_untaken"] == 5


def test_the_trace_schema_takes_the_events_of_the_untaken_numbers():
    record_schema = schema.trace_schema()
    untaken = {"t": "untaken", "doc": 7, "scope": None,
               **addressed.numbers_untaken(plan_of(TABLE, TEXT), [])}
    assigned = {"t": "assigned", "doc": 7, "scope": None, "asked": 4,
                "named": 1, "none": 3}
    for record in (untaken, assigned):
        jsonschema.validate(record, record_schema)
    # The break by construction: a key the schema does not name.
    for record in (untaken, assigned):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**record, "guessed": 1}, record_schema)
