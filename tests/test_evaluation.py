"""Decisions people made about a harvest, and what is counted against them.

What is promised, sentence by sentence:

  * a decision is appended as one line AND never rewrites an earlier one
    AND a line that is not a decision is refused with its line number;
  * a decision is found again by a row that says the same thing AND not by
    one of another document, another quote, another value or another
    parameter AND it does not care which passage id the row points at;
  * a later decision about the same content replaces the earlier one;
  * a field holds one thing: other content found correct there makes this
    content wrong AND a named right content settles it AND other content
    found wrong says nothing about this one;
  * a row is wrong as soon as one field is AND correct only once every
    field was decided AND undecided otherwise;
  * what nobody decided is in no share;
  * precision is split by field, parameter, level and origin;
  * recall is counted only over documents read whole AND a value the gold
    names as missing counts as found once a row carries it AND a carried
    value that is wrong is not found;
  * the queue holds only rows with an open field AND is in the same order
    every time AND that order does not follow the documents;
  * the interval is Wilson's;
  * against a baseline a lost correct row is told from a lost wrong one;
  * a floor fails when the share is below it AND when it cannot be counted.
"""
import json

import pytest

from docpipe import cli
from docpipe.extraction import evaluate, fields, gold
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL

P = "https://x/energy_consumption"
Q = "https://x/emissions"


def row(value=241.0, quote="| Erdgas | 241 |", parameter=P, year=2040,
        carrier="gas", tier=TIER_TEXT, owner=7, unit="GWh/a", **more):
    made = {"kind": "tuple", "parameter": parameter, "value": value,
            "value_raw": str(value), "unit": unit, "tier": tier,
            "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": "table",
                           "owner_id": owner},
            "year": year, "year_state": fields.READ,
            "carrier": carrier, "carrier_state": fields.READ}
    made.update(more)
    return made


def decide_all(path, document, a_row, verdict=gold.CORRECT, **wrong):
    for field in gold.fields_of(a_row):
        gold.decide(path, document, a_row, field,
                    wrong.get(field, verdict), by="t", at="2026-10-05")


@pytest.fixture
def path(tmp_path):
    return tmp_path / "gold.jsonl"


# ------------------------------------------------------------------ the file

def test_a_decision_is_one_appended_line(path):
    gold.decide(path, "a", row(), "value", gold.CORRECT, by="t", at="now")
    first = path.read_bytes()
    gold.decide(path, "a", row(), "year", gold.WRONG, expected=2030,
                by="t", at="now", note="column header")
    assert path.read_bytes().startswith(first)
    lines = [json.loads(line) for line in
             path.read_text(encoding="utf-8").splitlines()]
    assert [line["field"] for line in lines] == ["value", "year"]
    assert lines[1] == {
        "kind": "verdict", "document": "a", "tuple": lines[0]["tuple"],
        "parameter": P, "field": "year", "shown": 2040, "verdict": "wrong",
        "row": {"unit": "GWh/a", "year": 2040, "carrier": "gas"},
        "expected": 2030, "by": "t", "at": "now", "note": "column header"}


def test_a_file_that_is_not_there_holds_no_decision(path):
    assert gold.read(path) == []
    assert gold.Gold.load(path).verdict("a", row(), "value") is None


@pytest.mark.parametrize("line, says", [
    ("{not json", "not JSON"),
    ('["verdict"]', "an object"),
    ('{"kind": "opinion", "document": "a"}', "kind is 'opinion'"),
    ('{"kind": "checked"}', "no document"),
    ('{"kind": "verdict", "document": "a", "tuple": "t", "field": "value", '
     '"verdict": "maybe"}', "verdict is 'maybe'"),
    ('{"kind": "verdict", "document": "a", "verdict": "correct"}',
     "names a tuple and a field"),
    ('{"kind": "missing", "document": "a", "parameter": "p"}',
     "names its parameter and the value"),
])
def test_a_line_that_is_not_a_decision_is_refused_with_its_number(
        path, line, says):
    gold.mark_checked(path, "a")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    with pytest.raises(ValueError) as caught:
        gold.read(path)
    assert says in str(caught.value)
    assert f"{path}:2:" in str(caught.value)


def test_a_field_the_row_does_not_have_cannot_be_decided(path):
    with pytest.raises(ValueError) as caught:
        gold.decide(path, "a", row(), "sector", gold.CORRECT)
    assert "sector" in str(caught.value)
    assert not path.exists()


def test_a_verdict_other_than_the_two_is_not_written(path):
    with pytest.raises(ValueError):
        gold.decide(path, "a", row(), "value", "probably")
    assert not path.exists()


def test_the_fields_of_a_row():
    assert gold.fields_of(row()) == ["value", "unit", "carrier", "year"]
    assert gold.fields_of(row(unit=None)) == ["value", "carrier", "year"]


# ------------------------------------------------------- finding a row again

def test_a_decision_is_found_by_a_row_that_says_the_same(path):
    gold.decide(path, "a", row(), "value", gold.CORRECT)
    held = gold.Gold.load(path)
    assert held.verdict("a", row(), "value") == gold.CORRECT
    # the passage id is a counter and moves with every build
    assert held.verdict("a", row(owner=991), "value") == gold.CORRECT
    assert held.verdict("a", row(quote="|  Erdgas |  241 |"),
                        "value") == gold.CORRECT


@pytest.mark.parametrize("other", [
    {"quote": "| Strom | 241 |"}, {"value": 242.0}, {"parameter": Q},
])
def test_and_not_by_another_row(path, other):
    gold.decide(path, "a", row(), "value", gold.CORRECT)
    held = gold.Gold.load(path)
    assert held.verdict("a", row(**other), "value") is None


def test_nor_by_the_same_row_of_another_document(path):
    gold.decide(path, "a", row(), "value", gold.CORRECT)
    assert gold.Gold.load(path).verdict("b", row(), "value") is None


def test_a_later_decision_about_the_same_content_replaces_the_earlier(path):
    gold.decide(path, "a", row(), "year", gold.CORRECT)
    gold.decide(path, "a", row(), "year", gold.WRONG)
    assert gold.Gold.load(path).verdict("a", row(), "year") == gold.WRONG
    assert len(gold.read(path)) == 2            # and both are still there


def test_a_field_holds_one_thing(path):
    gold.decide(path, "a", row(year=2040), "year", gold.CORRECT)
    held = gold.Gold.load(path)
    assert held.verdict("a", row(year=2040), "year") == gold.CORRECT
    assert held.verdict("a", row(year=2030), "year") == gold.WRONG


def test_a_named_right_content_settles_the_field(path):
    gold.decide(path, "a", row(year=2040), "year", gold.WRONG, expected=2030)
    held = gold.Gold.load(path)
    assert held.verdict("a", row(year=2040), "year") == gold.WRONG
    assert held.verdict("a", row(year=2030), "year") == gold.CORRECT
    assert held.verdict("a", row(year=2025), "year") == gold.WRONG


def test_other_content_found_wrong_says_nothing_about_this_one(path):
    gold.decide(path, "a", row(year=2040), "year", gold.WRONG)
    held = gold.Gold.load(path)
    assert held.verdict("a", row(year=2030), "year") is None


def test_the_last_named_right_content_is_the_one_that_counts(path):
    gold.decide(path, "a", row(year=2040), "year", gold.WRONG, expected=2030)
    gold.decide(path, "a", row(year=2030), "year", gold.WRONG, expected=2035)
    held = gold.Gold.load(path)
    assert held.verdict("a", row(year=2035), "year") == gold.CORRECT
    assert held.verdict("a", row(year=2030), "year") == gold.WRONG
    assert held.verdict("a", row(year=2025), "year") == gold.WRONG


# ---------------------------------------------------- two rows of one name

KOHLE = "| Kohle | 0 | 0 |"


def twins():
    """One table row that prints the same number under two years: one
    quote and one value, read twice."""
    return (row(value=0.0, quote=KOHLE, year=2030),
            row(value=0.0, quote=KOHLE, year=2040))


def all_fields(held, document, a_row, rows):
    return {held.verdict(document, a_row, name, rows)
            for name in gold.fields_of(a_row)}


def test_a_decision_about_one_row_is_not_about_the_row_beside_it(path):
    first, second = twins()
    both = [first, second]
    assert gold.row_key("a", first) == gold.row_key("a", second)
    assert gold.row_name("a", first) != gold.row_name("a", second)
    decide_all(path, "a", first)
    held = gold.Gold.load(path)
    assert all_fields(held, "a", first, both) == {gold.CORRECT}
    assert all_fields(held, "a", second, both) == {None}
    # so it is still asked, and counted as not decided
    assert [entry[1]["year"]
            for entry in gold.queue({"a": both}, held)] == [2040]
    counted = evaluate.evaluate({"a": both}, held)["rows"]
    assert (counted["correct"], counted["wrong"], counted["undecided"]) \
        == (1, 0, 1)


def test_each_of_two_rows_of_one_name_keeps_its_own_decision(path):
    first, second = twins()
    both = [first, second]
    decide_all(path, "a", first)
    decide_all(path, "a", second, value=gold.WRONG)     # the same content
    held = gold.Gold.load(path)
    assert held.verdict("a", first, "value", both) == gold.CORRECT
    assert held.verdict("a", second, "value", both) == gold.WRONG
    assert gold.queue({"a": both}, held) == []


def test_a_row_read_again_with_another_year_takes_its_decisions_over(path):
    """It is the one row the decisions can be about: its value was found
    correct and stays so, its year is held against what was said."""
    first, second = twins()
    decide_all(path, "a", first)
    decide_all(path, "a", second)
    held = gold.Gold.load(path)
    again = row(value=0.0, quote=KOHLE, year=2045)       # was 2040
    later = [first, again]
    assert all_fields(held, "a", first, later) == {gold.CORRECT}
    assert held.verdict("a", again, "value", later) == gold.CORRECT
    assert held.verdict("a", again, "year", later) == gold.WRONG
    # and nothing of the row that still stands beside it
    assert held.verdict("a", again, "carrier", later) == gold.CORRECT


def test_two_rows_nobody_decided_take_nothing_over(path):
    """A decision on a row that is gone could be about either of them: a
    guess between two is no decision."""
    first, _second = twins()
    decide_all(path, "a", first)
    held = gold.Gold.load(path)
    later = [row(value=0.0, quote=KOHLE, year=2035),
             row(value=0.0, quote=KOHLE, year=2045)]
    for each in later:
        assert all_fields(held, "a", each, later) == {None}
    assert len(gold.queue({"a": later}, held)) == 2


def test_two_rows_of_one_name_are_two_rows_in_a_comparison(path):
    first, second = twins()
    decide_all(path, "a", second)
    held = gold.Gold.load(path)
    got = evaluate.compare({"a": [first, second]}, {"a": [first]}, held)
    assert (got["kept"], got["changed"]) == (1, 0)
    assert got["gained"]["correct"] == 1
    got = evaluate.compare({"a": [first]}, {"a": [first, second]}, held)
    assert (got["kept"], got["changed"]) == (1, 0)
    assert got["lost"]["correct"] == 1
    # one of them read with another year: kept, and read differently
    third = row(value=0.0, quote=KOHLE, year=2045)
    got = evaluate.compare({"a": [first, third]}, {"a": [first, second]},
                           held)
    assert (got["kept"], got["changed"]) == (2, 1)
    assert got["gained"]["correct"] + got["gained"]["undecided"] == 0


@pytest.mark.parametrize("left, right, equal", [
    (241, 241.0, True), (241, 242, False), ("a  b", "a b", True),
    ("a", "b", False), (None, None, True), (None, 0, False),
    (True, 1, False), ("2040", 2040, True), ("2040", 2041, False),
    ([1, 2], [1, 2], True),
])
def test_what_says_the_same(left, right, equal):
    assert gold.same(left, right) is equal


# ----------------------------------------------------------------- precision

def test_a_row_from_its_fields():
    c, w = gold.CORRECT, gold.WRONG
    assert evaluate.row_verdict({"value": c, "year": c}) == c
    assert evaluate.row_verdict({"value": c, "year": w}) == w
    assert evaluate.row_verdict({"value": w, "year": None}) == w
    assert evaluate.row_verdict({"value": c, "year": None}) is None
    assert evaluate.row_verdict({}) is None


def test_what_nobody_decided_is_in_no_share(path):
    good, bad, open_row = row(), row(value=5.0, quote="| Strom | 5,0 |"), \
        row(value=9.0, quote="| Kohle | 9,0 |")
    decide_all(path, "a", good)
    decide_all(path, "a", bad, year=gold.WRONG)
    report = evaluate.evaluate({"a": [good, bad, open_row]},
                               gold.Gold.load(path))
    assert report["rows"] == {
        "correct": 1, "wrong": 1, "undecided": 1, "precision": 0.5,
        "interval": list(evaluate.wilson(1, 2))}
    assert report["fields"]["year"]["wrong"] == 1
    assert report["fields"]["value"]["correct"] == 2
    assert report["fields"]["value"]["undecided"] == 1
    assert report["fields"]["value"]["precision"] == 1.0


def test_nothing_decided_no_precision(path):
    report = evaluate.evaluate({"a": [row()]}, gold.Gold())
    assert report["rows"]["precision"] is None
    assert report["rows"]["interval"] is None
    assert report["rows"]["undecided"] == 1


def test_precision_is_split_by_parameter_level_and_origin(path):
    text = row()
    image = row(value=5.0, quote="| Strom | 5,0 |", tier=TIER_VISUAL)
    gave_up = row(value=9.0, quote="| Kohle | 9,0 |", parameter=Q,
                  year_state=fields.EXHAUSTED)
    transcribed = row(value=3.0, quote="| Holz | 3,0 |")
    decide_all(path, "a", text)
    decide_all(path, "a", image, value=gold.WRONG)
    decide_all(path, "a", gave_up)
    decide_all(path, "scan", transcribed)
    report = evaluate.evaluate(
        {"a": [text, image, gave_up], "scan": [transcribed]},
        gold.Gold.load(path), transcribed={"scan"})
    assert report["documents"] == 2
    levels = report["levels"]
    assert (levels["A"]["correct"], levels["A"]["wrong"]) == (1, 0)
    assert (levels["B"]["correct"], levels["B"]["wrong"]) == (1, 1)
    assert (levels["C"]["correct"], levels["C"]["wrong"]) == (1, 0)
    assert report["tiers"][str(TIER_VISUAL)]["wrong"] == 1
    assert report["tiers"][str(TIER_TEXT)]["correct"] == 3
    assert report["parameters"][P]["rows"]["wrong"] == 1
    assert report["parameters"][Q]["rows"]["precision"] == 1.0
    assert report["parameters"][P]["fields"]["value"]["wrong"] == 1


# -------------------------------------------------------------------- recall

def test_recall_is_counted_only_over_documents_read_whole(path):
    found = row()
    decide_all(path, "a", found)
    decide_all(path, "b", found)
    gold.add_missing(path, "a", P, 88.0, unit="GWh/a",
                     quote="Der Bedarf liegt bei 88 GWh")
    gold.add_missing(path, "b", P, 77.0)
    gold.mark_checked(path, "a", P)
    report = evaluate.evaluate({"a": [found], "b": [found]},
                               gold.Gold.load(path))
    assert report["recall"] == {
        "documents": 1, "found": 1, "missed": 1, "undecided": 0,
        "recall": 0.5, "interval": list(evaluate.wilson(1, 2))}
    assert report["parameters"][P]["recall"]["missed"] == 1


def test_no_document_read_whole_no_recall(path):
    decide_all(path, "a", row())
    gold.add_missing(path, "a", P, 88.0)
    report = evaluate.evaluate({"a": [row()]}, gold.Gold.load(path))
    assert report["recall"]["documents"] == 0
    assert report["recall"]["recall"] is None
    assert report["recall_by_parameter"] == {}


def test_a_document_read_whole_for_every_parameter(path):
    decide_all(path, "a", row())
    decide_all(path, "a", row(parameter=Q))
    gold.mark_checked(path, "a")
    report = evaluate.evaluate({"a": [row(), row(parameter=Q)]},
                               gold.Gold.load(path))
    assert report["recall"]["found"] == 2
    assert set(report["recall_by_parameter"]) == {P, Q}


def test_a_missing_value_counts_as_found_once_a_row_carries_it(path):
    gold.add_missing(path, "a", P, 88.0, unit="GWh/a",
                     coordinates={"year": 2030})
    gold.mark_checked(path, "a", P)
    held = gold.Gold.load(path)
    lacking = evaluate.evaluate({"a": []}, held)
    assert (lacking["recall"]["found"], lacking["recall"]["missed"]) == (0, 1)
    carried = row(value=88.0, quote="bei 88 GWh", year=2030)
    now = evaluate.evaluate({"a": [carried]}, held)
    assert (now["recall"]["found"], now["recall"]["missed"]) == (1, 0)
    # the same number for another year is not that value
    other = evaluate.evaluate({"a": [row(value=88.0, quote="bei 88 GWh",
                                         year=2045)]}, held)
    assert (other["recall"]["found"], other["recall"]["missed"]) == (0, 1)
    assert other["recall"]["undecided"] == 1


@pytest.mark.parametrize("change, covered", [
    ({}, True), ({"value": 89.0}, False), ({"unit": "MWh/a"}, False),
    ({"parameter": Q}, False), ({"carrier": "coal"}, False),
])
def test_what_makes_a_row_the_missing_value(change, covered):
    fact = {"parameter": P, "value": 88, "unit": "GWh/a",
            "coordinates": {"carrier": "gas"}}
    made = row(value=88.0)
    made.update(change)
    assert gold.covers(fact, made) is covered


def test_a_value_the_harvest_read_twice_is_found_once(path):
    first, again = row(), row(quote="Erdgas: 241 GWh/a im Jahr 2040")
    other_year = row(quote="| Erdgas | 241 | (2030)", year=2030)
    for entry in (first, again, other_year):
        decide_all(path, "a", entry)
    gold.add_missing(path, "a", P, 88.0)
    gold.mark_checked(path, "a", P)
    report = evaluate.evaluate({"a": [first, again, other_year]},
                               gold.Gold.load(path))
    # two things are stated and found (2040 and 2030), one is missed
    assert (report["recall"]["found"], report["recall"]["missed"]) == (2, 1)
    assert report["rows"]["correct"] == 3           # precision counts rows


def test_a_carried_value_that_is_wrong_is_not_found(path):
    wrong = row()
    gold.decide(path, "a", wrong, "value", gold.WRONG)
    gold.mark_checked(path, "a", P)
    report = evaluate.evaluate({"a": [wrong]}, gold.Gold.load(path))
    assert report["recall"]["found"] == 0
    assert report["recall"]["recall"] is None       # nothing stated is known


def test_the_right_number_under_the_wrong_year_is_not_a_found_value(path):
    """Recall counts a row as precision does. A row with one wrong field
    is not what the document states, and the value it should have been is
    missed once, not found and missed."""
    carried = row(year=2040)
    decide_all(path, "a", carried, year=gold.WRONG)
    gold.mark_checked(path, "a", P)
    report = evaluate.evaluate({"a": [carried]}, gold.Gold.load(path))
    assert report["rows"]["wrong"] == 1
    assert report["recall"]["found"] == 0
    gold.add_missing(path, "a", P, 241.0, unit="GWh/a",
                     coordinates={"year": 2030})
    report = evaluate.evaluate({"a": [carried]}, gold.Gold.load(path))
    assert (report["recall"]["found"], report["recall"]["missed"]) == (0, 1)
    assert report["recall"]["recall"] == 0.0


def test_a_row_with_an_open_field_is_neither_found_nor_missed(path):
    carried = row()
    gold.decide(path, "a", carried, "value", gold.CORRECT)   # year is open
    gold.mark_checked(path, "a", P)
    report = evaluate.evaluate({"a": [carried]}, gold.Gold.load(path))
    assert (report["recall"]["found"], report["recall"]["undecided"]) \
        == (0, 1)


def test_the_same_stated_value_written_down_twice_is_missed_once(path):
    for note in (None, "again"):
        gold.add_missing(path, "a", P, 88.0, unit="GWh/a",
                         coordinates={"year": 2030}, note=note)
    gold.add_missing(path, "a", P, 88.0, unit="GWh/a",
                     coordinates={"year": 2040})    # another year: another
    gold.mark_checked(path, "a", P)
    held = gold.Gold.load(path)
    assert len(gold.read(path)) == 4                # the file keeps each line
    assert [fact["coordinates"]["year"]
            for fact in held.missing_for("a", P)] == [2030, 2040]
    assert held.missing_for("a", P)[0]["note"] == "again"   # the last one
    assert evaluate.evaluate({"a": []}, held)["recall"]["missed"] == 2


# --------------------------------------------------------------------- queue

def _many(count):
    return [row(value=float(index), quote=f"| Zeile {index} | {index} |")
            for index in range(count)]


def test_the_queue_holds_only_rows_with_an_open_field(path):
    rows = _many(4)
    decide_all(path, "a", rows[0])
    gold.decide(path, "a", rows[1], "value", gold.CORRECT)   # year is open
    held = gold.Gold.load(path)
    queued = [entry[1]["value"] for entry in gold.queue({"a": rows}, held)]
    assert sorted(queued) == [1.0, 2.0, 3.0]


def test_the_queue_is_in_the_same_order_every_time_and_not_by_document():
    harvest = {"a": _many(20), "b": _many(20)}
    first = gold.queue(harvest, gold.Gold())
    again = gold.queue({"b": harvest["b"], "a": harvest["a"]}, gold.Gold())
    assert [(d, r["value"]) for d, r in first] \
        == [(d, r["value"]) for d, r in again]
    documents = [document for document, _row in first]
    assert documents != sorted(documents)           # the two are mixed
    assert len(gold.queue(harvest, gold.Gold(), limit=5)) == 5
    assert gold.queue(harvest, gold.Gold(), limit=5) == first[:5]


def test_the_queue_of_one_parameter():
    harvest = {"a": [row(), row(parameter=Q)]}
    queued = gold.queue(harvest, gold.Gold(), parameters=[Q])
    assert [entry[1]["parameter"] for entry in queued] == [Q]


# ------------------------------------------------------------------ interval

def test_the_interval_is_wilsons():
    low, high = evaluate.wilson(38, 40)
    assert (round(low, 3), round(high, 3)) == (0.835, 0.986)
    low, high = evaluate.wilson(0, 10)
    assert low == 0.0 and round(high, 3) == 0.278
    low, high = evaluate.wilson(10, 10)
    assert round(low, 3) == 0.722 and high == 1.0
    assert evaluate.wilson(0, 0) is None


# ------------------------------------------------------------------ baseline

def test_against_a_baseline_a_lost_correct_row_is_told_from_a_lost_wrong_one(
        path):
    kept, good, bad, new = (row(), row(value=5.0, quote="| Strom | 5,0 |"),
                            row(value=9.0, quote="| Kohle | 9,0 |"),
                            row(value=3.0, quote="| Holz | 3,0 |"))
    gold.decide(path, "a", good, "value", gold.CORRECT)
    gold.decide(path, "a", bad, "value", gold.WRONG)
    moved = dict(kept, year=2030)
    got = evaluate.compare({"a": [moved, new]}, {"a": [kept, good, bad]},
                           gold.Gold.load(path))
    assert got["kept"] == 1 and got["changed"] == 1
    assert (got["lost"]["correct"], got["lost"]["wrong"],
            got["lost"]["undecided"]) == (1, 1, 0)
    assert got["gained"]["undecided"] == 1


def test_the_same_harvest_against_itself():
    harvest = {"a": _many(3)}
    got = evaluate.compare(harvest, harvest, gold.Gold())
    assert got["kept"] == 3 and got["changed"] == 0
    assert got["gained"]["undecided"] == got["lost"]["undecided"] == 0


# ---------------------------------------------------------------- the command

def _harvest(tmp_path, name, rows, directory="harvest"):
    folder = tmp_path / directory
    folder.mkdir(exist_ok=True)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in rows]
    lines.append(json.dumps({"kind": "refusal", "parameter": P}))
    (folder / f"{name}.jsonl").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")
    return folder


def test_the_command_counts_and_writes_the_report(tmp_path, capsys):
    good, bad = row(), row(value=5.0, quote="| Strom | 5,0 |")
    folder = _harvest(tmp_path, "a", [good, bad])
    path = tmp_path / gold.FILE_NAME            # beside the harvest: default
    decide_all(path, "a", good)
    decide_all(path, "a", bad, value=gold.WRONG)
    out = tmp_path / "report" / "evaluation.json"
    assert evaluate.main([str(folder), "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "1 document(s)" in printed
    assert "no document is marked as read whole" in printed
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["rows"]["precision"] == 0.5
    assert P in report["parameters"]


def test_the_command_holds_a_baseline_beside_it(tmp_path, capsys):
    good = row()
    folder = _harvest(tmp_path, "a", [good])
    before = _harvest(tmp_path, "a", [], directory="before")
    path = tmp_path / gold.FILE_NAME
    decide_all(path, "a", good)
    assert evaluate.main([str(folder), "--baseline", str(before)]) == 0
    printed = capsys.readouterr().out
    assert "against the baseline" in printed
    assert "gained 1: 1 correct" in printed


@pytest.mark.parametrize("named", [".", "../harvest"])
def test_the_decisions_are_looked_for_beside_the_harvest_however_it_is_named(
        tmp_path, capsys, monkeypatch, named):
    """`.` has no name to stand beside and `..` has its own: the file is
    beside the directory that was meant, not beside its spelling."""
    good = row()
    folder = _harvest(tmp_path, "a", [good])
    decide_all(tmp_path / gold.FILE_NAME, "a", good)
    monkeypatch.chdir(folder)
    assert evaluate.main([named]) == 0
    assert "1 document(s)" in capsys.readouterr().out


def test_the_report_counts_found_and_missed_once_a_document_was_read_whole(
        tmp_path, capsys):
    found = row()
    folder = _harvest(tmp_path, "a", [found])
    path = tmp_path / gold.FILE_NAME
    decide_all(path, "a", found)
    gold.add_missing(path, "a", P, 88.0)
    gold.mark_checked(path, "a", P)
    assert evaluate.main([str(folder)]) == 0
    printed = capsys.readouterr().out
    assert "no document is marked as read whole" not in printed
    said = [line for line in printed.splitlines() if " missed " in line]
    assert len(said) == 2                   # all, and the one parameter
    for line in said:
        assert "50.0%" in line
        assert "1 found" in line and "1 missed" in line
        assert line.endswith("in 1 document(s)")


@pytest.mark.parametrize("floor, code", [("0.4", 0), ("0.5", 0), ("0.6", 1)])
def test_a_floor_fails_when_the_share_is_below_it(tmp_path, capsys, floor,
                                                  code):
    good, bad = row(), row(value=5.0, quote="| Strom | 5,0 |")
    folder = _harvest(tmp_path, "a", [good, bad])
    path = tmp_path / gold.FILE_NAME
    decide_all(path, "a", good)
    decide_all(path, "a", bad, value=gold.WRONG)
    assert evaluate.main([str(folder), "--min-precision", floor]) == code
    assert ("the floor is" in capsys.readouterr().err) is bool(code)


def test_a_floor_fails_when_the_share_cannot_be_counted(tmp_path, capsys):
    folder = _harvest(tmp_path, "a", [row()])
    gold.mark_checked(tmp_path / gold.FILE_NAME, "elsewhere")
    assert evaluate.main([str(folder), "--min-precision", "0.1"]) == 1
    assert "precision is not known" in capsys.readouterr().err
    assert evaluate.main([str(folder), "--min-recall", "0.1"]) == 1
    assert "recall is not known" in capsys.readouterr().err
    assert evaluate.main([str(folder)]) == 0


def test_without_decisions_there_is_nothing_to_count(tmp_path):
    folder = _harvest(tmp_path, "a", [row()])
    with pytest.raises(SystemExit) as caught:
        evaluate.main([str(folder)])
    assert gold.FILE_NAME in str(caught.value)
    with pytest.raises(SystemExit) as caught:
        evaluate.main([str(tmp_path / "nowhere")])
    assert "not a directory" in str(caught.value)


def test_docpipe_evaluate_is_a_command():
    assert cli.STAGES["evaluate"][0] == "docpipe.extraction.evaluate"
