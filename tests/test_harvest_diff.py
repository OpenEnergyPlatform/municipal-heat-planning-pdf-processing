"""Two harvests held against each other, without a decision about either.

What is promised, in one sentence: `docpipe evaluate NEW --diff OLD` pairs
the rows of two harvests by the identity `compare` uses, AND counts per
parameter and per field the rows that are the same, changed, gone and new,
AND counts how the states of the coordinates moved, AND how the trust
levels moved, AND lists the largest changes, no more than were asked for,
with both readings side by side, AND exits 0 unless a ceiling was given and
is passed, AND refuses what it cannot count (a flag that needs the
decisions, a directory without a harvest, a ceiling over nothing) instead
of printing zeros.

Every clause has a test, and each test has a case built to break it.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe.extraction import evaluate, fields, gold
from docpipe.extraction.evaluate import CHANGED, GONE, NEW, SAME
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL
from tests.test_entry_points import PROBE

ROOT = Path(__file__).resolve().parent.parent

P = "https://x/energy_consumption"
Q = "https://x/emissions"
KOHLE = "| Kohle | 0 | 0 |"


def row(value=241.0, quote="| Erdgas | 241 |", parameter=P, year=2040,
        carrier="gas", tier=TIER_TEXT, unit="GWh/a", **more):
    made = {"kind": "tuple", "parameter": parameter, "value": value,
            "value_raw": str(value), "unit": unit, "tier": tier,
            "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": "table",
                           "owner_id": 7},
            "year": year, "year_state": fields.READ,
            "carrier": carrier, "carrier_state": fields.READ}
    made.update(more)
    return made


def numbered(count, **more):
    """*count* rows of different quotes."""
    return [row(value=float(index), quote=f"| Zeile {index} | {index} |",
                **more) for index in range(count)]


def real(**more):
    """A row as a run writes it: the parameter and the unit are coordinates
    too, each with a state of its own."""
    return row(parameter_state=fields.READ, unit_state=fields.READ, **more)


def tally(same=0, changed=0, gone=0, new=0):
    return {SAME: same, CHANGED: changed, GONE: gone, NEW: new}


# -------------------------------------------------- the identity of a row

def test_the_same_harvest_against_itself_is_all_the_same():
    harvest = {"a": numbered(3), "b": numbered(2, parameter=Q)}
    got = evaluate.diff(harvest, harvest)
    assert got["rows"] == tally(same=5)
    assert got["differing"] == 0 and got["largest"] == []
    assert got["transitions"]["moved"] == 0 and got["levels"]["moved"] == 0
    assert got["documents"] == {"both": 2, "gone": 0, "new": 0, "changed": 0}


def test_a_row_whose_unit_or_year_changed_is_read_differently_not_gone():
    now = {"a": [row(year=2030), row(value=5.0, quote="| Strom | 5 |",
                                     unit="MWh/a")]}
    before = {"a": [row(year=2040), row(value=5.0, quote="| Strom | 5 |")]}
    got = evaluate.diff(now, before)
    assert got["rows"] == tally(changed=2)
    assert got["fields"]["year"] == tally(same=1, changed=1)
    assert got["fields"]["unit"] == tally(same=1, changed=1)


def test_a_row_whose_quote_or_written_value_changed_is_gone_and_another_new():
    """The name of a row is made of the quote and the value as written.
    Another quote or another written value is another row, and nothing
    here pairs them back: that would be a second identity."""
    before = {"a": [row(), row(value=5.0, quote="| Strom | 5 |")]}
    now = {"a": [row(quote="| Erdgas | 241 | (Tabelle 3)"),
                 row(value=6.0, quote="| Strom | 5 |")]}
    got = evaluate.diff(now, before)
    assert got["rows"] == tally(gone=2, new=2)


CASES = {
    "twins both ways": (
        {"a": [row(value=0.0, quote=KOHLE, year=2030),
               row(value=0.0, quote=KOHLE, year=2040)]},
        {"a": [row(value=0.0, quote=KOHLE, year=2030)]}),
    "twins, one read with another year": (
        {"a": [row(value=0.0, quote=KOHLE, year=2030),
               row(value=0.0, quote=KOHLE, year=2045)]},
        {"a": [row(value=0.0, quote=KOHLE, year=2030),
               row(value=0.0, quote=KOHLE, year=2040)]}),
    "a twin gone": (
        {"a": [row(value=0.0, quote=KOHLE, year=2030)]},
        {"a": [row(value=0.0, quote=KOHLE, year=2030),
               row(value=0.0, quote=KOHLE, year=2040)]}),
    "another document": (
        {"a": numbered(2), "c": numbered(1)},
        {"a": numbered(2), "b": numbered(3)}),
    "everything moved": (
        {"a": numbered(3, year=2030)}, {"a": numbered(3, year=2040)}),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_rows_are_paired_by_the_identity_compare_uses(case):
    """`compare` is what `docpipe evaluate --baseline` counts with. A second
    way of pairing rows would put the same two harvests into two answers."""
    now, before = CASES[case]
    paired = evaluate.compare(now, before, gold.Gold())
    got = evaluate.diff(now, before)["rows"]
    assert got[SAME] + got[CHANGED] == paired["kept"]
    assert got[CHANGED] == paired["changed"]
    undecided = lambda side: sum(  # noqa: E731
        side[name] for name in ("correct", "wrong", "undecided"))
    assert got[NEW] == undecided(paired["gained"])
    assert got[GONE] == undecided(paired["lost"])


def test_the_pairs_hold_every_row_once():
    now, before = CASES["twins, one read with another year"]
    pairs = list(evaluate.pair_rows(now, before))
    assert sorted(kind for kind, *_ in pairs) == [CHANGED, SAME]
    ours = [pair[2] for pair in pairs]
    theirs = [pair[3] for pair in pairs]
    assert sorted(entry["year"] for entry in ours) == [2030, 2045]
    assert sorted(entry["year"] for entry in theirs) == [2030, 2040]


def test_every_row_is_counted_once_in_what_it_counts():
    now = {"a": numbered(5), "c": numbered(2, parameter=Q)}
    before = {"a": numbered(4)[:3] + [row(value=9.0, quote="| X | 9 |")],
              "b": numbered(2, parameter=Q)}
    got = evaluate.diff(now, before)
    rows = got["rows"]
    assert rows[SAME] + rows[CHANGED] + rows[NEW] == got["harvest"]["rows"] \
        == 7
    assert rows[SAME] + rows[CHANGED] + rows[GONE] == got["baseline"]["rows"] \
        == 6
    assert sum(sum(entry["rows"].values())
               for entry in got["parameters"].values()) == sum(rows.values())


# ------------------------------------ per parameter, per field, per document

def test_rows_are_told_apart_by_parameter():
    now = {"a": [row(year=2030), row(parameter=Q, value=3.0, quote="| CO2 |")]}
    before = {"a": [row(year=2040), row(parameter=Q, value=3.0,
                                        quote="| CO2 |")]}
    got = evaluate.diff(now, before)["parameters"]
    assert got[P]["rows"] == tally(changed=1)
    assert got[Q]["rows"] == tally(same=1)


def test_a_field_is_counted_where_it_changed_and_nowhere_else():
    now = {"a": [row(year=2030),
                 row(parameter=Q, value=3.0, quote="| CO2 |")]}
    before = {"a": [row(year=2040),
                    row(parameter=Q, value=3.0, quote="| CO2 |")]}
    got = evaluate.diff(now, before)
    assert got["parameters"][P]["fields"]["year"] == tally(changed=1)
    assert got["parameters"][P]["fields"]["value"] == tally(same=1)
    assert got["parameters"][P]["fields"]["carrier"] == tally(same=1)
    # the other parameter's year is not the changed one
    assert got["parameters"][Q]["fields"]["year"] == tally(same=1)
    assert got["fields"]["year"] == tally(same=1, changed=1)


def test_the_fields_of_a_gone_row_are_gone_and_those_of_a_new_row_are_new():
    now = {"a": [row(value=7.0, quote="| Neu | 7 |", unit=None)]}
    before = {"a": [row()]}
    got = evaluate.diff(now, before)
    assert got["fields"]["unit"] == tally(gone=1)    # the new row has none
    assert got["fields"]["value"] == tally(gone=1, new=1)
    assert got["fields"]["carrier"] == tally(gone=1, new=1)


def test_a_row_is_counted_once_under_each_field_it_carries_however_named():
    """A numeric row names its unit twice, as the unit of its value and as
    the coordinate behind unit_state, and is still one row with one unit.
    Counted from `fields_of` as it stands, a gone or new row said 'unit'
    twice."""
    now = {"a": [real(value=7.0, quote="| Neu | 7 |")]}
    before = {"a": [real()]}
    got = evaluate.diff(now, before)
    assert got["rows"] == tally(gone=1, new=1)
    for field, counted in got["fields"].items():
        assert counted == tally(gone=1, new=1), field
    assert got["parameters"][P]["fields"]["unit"] == tally(gone=1, new=1)
    paired = evaluate.diff({"a": [real(unit="MWh/a")]}, {"a": [real()]})
    assert paired["fields"]["unit"] == tally(changed=1)
    assert paired["fields"]["value"] == tally(same=1)
    assert paired["parameters"][P]["fields"]["unit"] == tally(changed=1)


def test_a_value_the_parser_read_again_differently_is_a_changed_value():
    """Same quote, same written value: the parsed number is what moved."""
    now = {"a": [row(value=241.0, value_raw="241")]}
    before = {"a": [row(value=24.1, value_raw="241")]}
    got = evaluate.diff(now, before)
    assert got["fields"]["value"] == tally(changed=1)
    assert got["rows"] == tally(changed=1)


def test_documents_are_counted_in_both_and_in_one():
    now = {"a": numbered(2), "new": numbered(1), "empty": []}
    before = {"a": numbered(2, year=2030), "old": numbered(4), "empty": []}
    got = evaluate.diff(now, before)
    assert got["documents"] == {"both": 2, "gone": 1, "new": 1, "changed": 1}
    assert (got["baseline"]["documents"], got["harvest"]["documents"]) \
        == (3, 3)


def test_a_document_is_changed_when_only_a_state_or_a_level_moved():
    """A re-check moves states and leaves every row reading as it did. No
    row is read differently, and the document is still not the one the
    baseline holds."""
    before = {"a": [row()], "b": [row()], "c": [row()]}
    now = {"a": [row(year_state=fields.UNBACKED)],      # a state moved
           "b": [row(tier=TIER_VISUAL)],                # a level moved
           "c": [row()]}                                # nothing moved
    got = evaluate.diff(now, before)
    assert got["rows"] == tally(same=3)
    assert got["documents"] == {"both": 3, "gone": 0, "new": 0, "changed": 2}
    assert "2 of them with a row that reads differently, moved in a state " \
        "or a level, is gone or is new" in evaluate.render_diff(got)


# ------------------------------------------------------ states of coordinates

def test_a_coordinate_that_went_from_read_to_unbacked_is_a_move():
    now = {"a": [row(year_state=fields.UNBACKED)]}
    before = {"a": [row()]}
    got = evaluate.diff(now, before)["transitions"]
    assert got["moves"] == {"read>unbacked": 1}
    assert got["by_coordinate"] == {"year": {"read>unbacked": 1}}
    assert (got["coordinates"], got["kept"], got["moved"]) == (2, 1, 1)
    # the answer stands, so the row still reads the same: the move is the
    # only thing that tells the two apart
    assert evaluate.diff(now, before)["rows"] == tally(same=1)


def test_a_coordinate_that_kept_its_state_is_not_a_move():
    harvest = {"a": [row(year_state=fields.EXHAUSTED)]}
    got = evaluate.diff(harvest, harvest)["transitions"]
    assert got["moves"] == {} and got["moved"] == 0
    assert (got["coordinates"], got["kept"]) == (2, 2)


def test_moves_are_counted_by_coordinate_and_by_kind():
    now = {"a": [
        row(year_state=fields.UNBACKED, carrier_state=fields.EXHAUSTED),
        row(value=5.0, quote="| Strom | 5 |", year_state=fields.UNBACKED),
        row(value=6.0, quote="| Holz | 6 |")]}
    before = {"a": [row(), row(value=5.0, quote="| Strom | 5 |"),
                    row(value=6.0, quote="| Holz | 6 |")]}
    got = evaluate.diff(now, before)["transitions"]
    assert got["by_coordinate"] == {
        "year": {"read>unbacked": 2}, "carrier": {"read>exhausted": 1}}
    assert got["moves"] == {"read>unbacked": 2, "read>exhausted": 1}
    assert (got["coordinates"], got["kept"], got["moved"]) == (6, 3, 3)


def test_a_coordinate_one_side_does_not_carry_has_no_state_there():
    now = {"a": [row()]}
    before_row = row()
    del before_row["carrier"], before_row["carrier_state"]
    got = evaluate.diff(now, {"a": [before_row]})
    assert got["transitions"]["moves"] == {"(none)>read": 1}
    assert got["rows"] == tally(changed=1)


def test_only_the_rows_both_harvests_carry_have_a_move():
    """A row that is gone or new has no other side to move from."""
    now = {"a": [row(value=9.0, quote="| Neu | 9 |",
                     year_state=fields.UNBACKED)]}
    before = {"a": [row(year_state=fields.EXHAUSTED)]}
    got = evaluate.diff(now, before)["transitions"]
    assert got["coordinates"] == 0 and got["moves"] == {}


# --------------------------------------------------------------- trust levels

def test_a_row_that_became_a_c_is_a_level_move():
    now = {"a": [row(year_state=fields.EXHAUSTED),
                 row(value=5.0, quote="| Strom | 5 |", tier=TIER_VISUAL)]}
    before = {"a": [row(), row(value=5.0, quote="| Strom | 5 |")]}
    got = evaluate.diff(now, before)["levels"]
    assert got["moves"] == {"A>B": 1, "A>C": 1}
    assert (got["rows"], got["kept"], got["moved"]) == (2, 0, 2)


def test_a_row_that_kept_its_level_is_not_a_move():
    harvest = {"a": [
        row(), row(value=5.0, quote="| S | 5 |", tier=TIER_VISUAL),
        row(value=6.0, quote="| H | 6 |", carrier_state=fields.EXHAUSTED)]}
    got = evaluate.diff(harvest, harvest)["levels"]
    assert got["moves"] == {} and got["kept"] == 3


def test_gone_and_new_rows_are_counted_by_their_level_and_move_nowhere():
    now = {"a": [row(value=1.0, quote="| N | 1 |"),
                 row(value=2.0, quote="| M | 2 |", tier=TIER_VISUAL),
                 row(value=3.0, quote="| O | 3 |",
                     year_state=fields.UNBACKED)]}
    before = {"a": [row(value=9.0, quote="| G | 9 |",
                        carrier_state=fields.EXHAUSTED)]}
    got = evaluate.diff(now, before)["levels"]
    assert got["new"] == {"A": 1, "B": 1, "C": 1}
    assert got["gone"] == {"A": 0, "B": 0, "C": 1}
    assert (got["rows"], got["moves"]) == (0, {})


def test_a_transcribed_document_is_level_b_on_both_sides():
    """The harvest of a document whose pages a model transcribed is a B at
    best, in the baseline as in this one: that is not a move, and it is
    what separates the levels of the two counts."""
    harvest = {"scan": [row()], "text": [row()]}
    plain = evaluate.diff(harvest, harvest)["levels"]
    held = evaluate.diff(harvest, harvest, transcribed={"scan"})["levels"]
    assert plain["kept"] == held["kept"] == 2 and held["moved"] == 0
    only_before = evaluate.diff({"scan": []}, {"scan": [row()]},
                                transcribed={"scan"})["levels"]
    assert only_before["gone"] == {"A": 0, "B": 1, "C": 0}
    assert evaluate.diff({"scan": []}, {"scan": [row()]})["levels"]["gone"] \
        == {"A": 1, "B": 0, "C": 0}


def test_the_report_says_how_many_documents_it_took_as_transcribed():
    """Without a database no document is known as transcribed and every
    text row is an A. The numbers hold on that, so the report says it."""
    harvest = {"scan": [row()], "text": [row()]}
    held = evaluate.diff(harvest, harvest, transcribed={"scan", "elsewhere"})
    # a document neither harvest carries is not one the levels were put on
    assert held["levels"]["transcribed"] == 1
    assert "1 document(s) of the two harvests were transcribed by a " \
        "model" in evaluate.render_diff(held)
    plain = evaluate.diff(harvest, harvest)
    assert plain["levels"]["transcribed"] == 0
    said = evaluate.render_diff(plain)
    assert "no document of the two harvests is known as transcribed" in said
    assert "were transcribed by a model" not in said


def test_the_level_is_the_one_evaluate_counts_with():
    gave_up = row(carrier_state=fields.EXHAUSTED)
    assert evaluate._level(row(), "text", {"scan"}) == "A"
    assert evaluate._level(row(), "scan", {"scan"}) == "B"
    # the transcription caps a level at B and never lifts a C
    assert evaluate._level(gave_up, "scan", {"scan"}) == "C"


# ----------------------------------------------------------- largest changes

def three_sizes():
    """One row that differs in 1 thing, one in 2 and one in 3."""
    before = {"a": [row(value=1.0, quote="| A | 1 |"),
                    row(value=2.0, quote="| B | 2 |"),
                    row(value=3.0, quote="| C | 3 |")]}
    now = {"a": [
        row(value=1.0, quote="| A | 1 |", year=2030),
        row(value=2.0, quote="| B | 2 |", year=2030, carrier="oil"),
        row(value=3.0, quote="| C | 3 |", year=2030, carrier="oil",
            year_state=fields.UNBACKED)]}
    return now, before


def test_the_largest_changes_come_first_with_both_readings():
    now, before = three_sizes()
    got = evaluate.diff(now, before)
    assert got["differing"] == 3
    assert [found["size"] for found in got["largest"]] == [4, 2, 1]
    first = got["largest"][0]
    assert first["changes"] == ["carrier", "year", "year_state", "level"]
    assert first["baseline"]["coordinates"]["year"] == {
        "answer": 2040, "state": "read"}
    assert first["harvest"]["coordinates"]["year"] == {
        "answer": 2030, "state": "unbacked"}
    assert (first["baseline"]["level"], first["harvest"]["level"]) \
        == ("A", "C")
    assert first["baseline"]["value"] == first["harvest"]["value"] == 3.0
    assert first["document"] == "a" and first["parameter"] == P


def test_a_change_names_its_row_by_the_quote_both_readings_stand_on():
    """A tuple name is a hash. What lets a person find the row is the
    passage it quotes."""
    now, before = three_sizes()
    got = evaluate.diff(now, before)["largest"]
    assert [found["quote"] for found in got] \
        == ["| C | 3 |", "| B | 2 |", "| A | 1 |"]
    said = evaluate.render_diff(evaluate.diff(now, before, top=1))
    assert "       quote     | C | 3 |" in said
    assert "| B | 2 |" not in said


def test_a_long_quote_is_cut_in_the_report_and_whole_in_the_data():
    long = "| Erdgas | 241 |" + " Spalte" * 40
    got = evaluate.diff({"a": [row(quote=long, year=2030)]},
                        {"a": [row(quote=long)]})
    assert got["largest"][0]["quote"] == long
    line = next(text for text in evaluate.render_diff(got).splitlines()
                if text.startswith("       quote"))
    assert line.endswith("...") and long not in line
    assert len(line) == len("       quote     ") + 100
    assert evaluate._head("| a |\n   b ", 100) == "| a | b"


@pytest.mark.parametrize("top, shown", [(0, 0), (1, 1), (2, 2), (3, 3),
                                        (99, 3)])
def test_no_more_than_were_asked_for_are_listed(top, shown):
    now, before = three_sizes()
    got = evaluate.diff(now, before, top=top)
    assert len(got["largest"]) == shown
    assert got["differing"] == 3        # what was left out is still counted
    assert [found["size"] for found in got["largest"]] \
        == [4, 2, 1][:shown]


def test_a_row_that_did_not_change_is_not_a_change():
    now, before = three_sizes()
    now["a"].append(row(value=4.0, quote="| D | 4 |"))
    before["a"].append(row(value=4.0, quote="| D | 4 |"))
    got = evaluate.diff(now, before, top=99)
    assert got["differing"] == 3
    assert all(found["tuple"] != gold.row_key("a", now["a"][3])[1]
               for found in got["largest"])


def test_a_row_that_only_changed_its_level_is_a_change():
    now = {"a": [row(tier=TIER_VISUAL)]}
    got = evaluate.diff(now, {"a": [row()]})
    assert got["rows"] == tally(same=1)
    assert got["differing"] == 1
    assert got["largest"][0]["changes"] == ["level"]


def test_equal_changes_come_in_an_order_that_is_the_same_every_time():
    before = {"b": [row()], "a": [row()]}
    now = {"b": [row(year=2030)], "a": [row(year=2030)]}
    first = evaluate.diff(now, before)["largest"]
    again = evaluate.diff({"a": now["a"], "b": now["b"]},
                          {"a": before["a"], "b": before["b"]})["largest"]
    assert [found["document"] for found in first] == ["a", "b"]
    assert first == again


# ----------------------------------------------------------------- the report

def test_the_report_says_when_no_row_differs():
    harvest = {"a": numbered(2)}
    said = evaluate.render_diff(evaluate.diff(harvest, harvest))
    assert "no row both harvests carry differs" in said
    assert "2 same      0 changed      0 gone      0 new" in said
    assert "       baseline  " not in said


def test_the_report_puts_both_readings_of_a_change_side_by_side():
    now, before = three_sizes()
    said = evaluate.render_diff(evaluate.diff(now, before, top=1))
    assert "largest changes: 1 of the 3 row(s)" in said
    assert "(4 difference(s): carrier, year, year_state, level)" in said
    assert ("       baseline  3.0 GWh/a   carrier=gas (read)   "
            "year=2040 (read)   level A") in said
    assert ("       harvest   3.0 GWh/a   carrier=oil (read)   "
            "year=2030 (unbacked)   level C") in said
    assert said.count("       harvest   ") == 1


# ------------------------------------------------------------------- ceilings

def counted(**rows):
    """A report that holds only the counts a ceiling reads."""
    base = rows.pop("base")
    return {"baseline": {"rows": base}, "rows": tally(**rows)}


@pytest.mark.parametrize("changed, ceiling, over", [
    (1, 0.25, False), (2, 0.25, False), (2, 0.2, True), (3, 0.25, True),
    (0, 0.0, False), (1, 0.0, True)])
def test_a_ceiling_on_the_changed_rows_is_exceeded_above_its_share(
        changed, ceiling, over):
    report = counted(base=8, changed=changed)
    short = evaluate.moved_too_far(report, ceiling, None)
    assert bool(short) is over
    if over:
        assert "row(s) are changed" in short[0]
        assert "the baseline's 8" in short[0]


def test_a_ceiling_on_the_gone_rows_is_not_one_on_the_changed_rows():
    report = counted(base=8, changed=6, gone=1)
    assert evaluate.moved_too_far(report, None, 0.2) == []
    assert evaluate.moved_too_far(report, 0.2, None) != []
    assert evaluate.moved_too_far(report, None, None) == []
    assert len(evaluate.moved_too_far(report, 0.1, 0.1)) == 2


def test_a_ceiling_over_a_baseline_without_rows_is_exceeded():
    short = evaluate.moved_too_far(counted(base=0), 0.5, None)
    assert short and "not known" in short[0]
    assert evaluate.moved_too_far(counted(base=0), None, None) == []


# ---------------------------------------------------------------- the command

def harvest_dir(tmp_path, name, rows, directory):
    folder = tmp_path / directory
    folder.mkdir(exist_ok=True)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in rows]
    lines.append(json.dumps({"kind": "refusal", "parameter": P}))
    lines.append(json.dumps({"kind": "summary", "tuples": len(rows)}))
    (folder / f"{name}.jsonl").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")
    return folder


@pytest.fixture
def pair(tmp_path):
    """Two harvests of one document: of four rows two read the same, one
    reads differently, one is gone from the baseline and one is new."""
    before = harvest_dir(tmp_path, "a", [
        row(), row(value=2.0, quote="| B | 2 |"),
        row(value=3.0, quote="| C | 3 |"),
        row(value=4.0, quote="| D | 4 |")], "before")
    now = harvest_dir(tmp_path, "a", [
        row(year=2030), row(value=2.0, quote="| B | 2 |"),
        row(value=3.0, quote="| C | 3 |"),
        row(value=5.0, quote="| E | 5 |")], "now")
    return now, before


def run(now, before, *more):
    return evaluate.main([str(now), "--diff", str(before), *more])


def test_the_command_needs_no_decisions(pair, capsys):
    now, before = pair
    assert not (now.parent / gold.FILE_NAME).exists()
    assert run(now, before) == 0
    printed = capsys.readouterr().out
    assert "baseline  1 document(s), 4 row(s)" in printed
    assert "harvest   1 document(s), 4 row(s)" in printed
    assert "all" in printed and "2 same" in printed
    assert "1 changed" in printed and "1 gone" in printed


def test_the_decisions_beside_the_harvest_are_not_read(pair):
    """Not needed, so not opened: a file there that is no decision file
    does not make a comparison fail."""
    now, before = pair
    (now.parent / gold.FILE_NAME).write_text("{not json\n", encoding="utf-8")
    assert run(now, before) == 0


def test_without_the_flag_a_baseline_still_needs_decisions(pair):
    now, before = pair
    with pytest.raises(SystemExit) as caught:
        evaluate.main([str(now), "--baseline", str(before)])
    assert gold.FILE_NAME in str(caught.value)


def test_a_comparison_exits_0_however_much_changed(tmp_path, capsys):
    before = harvest_dir(tmp_path, "a", numbered(4), "before")
    now = harvest_dir(tmp_path, "a", numbered(4, year=2030), "now")
    assert run(now, before) == 0
    assert "4 changed" in capsys.readouterr().out
    other = harvest_dir(tmp_path, "a", numbered(4, parameter=Q), "other")
    assert run(other, before) == 0


@pytest.mark.parametrize("flag, ceiling, code", [
    ("--max-changed", "0.25", 0), ("--max-changed", "0.2", 1),
    ("--max-gone", "0.25", 0), ("--max-gone", "0.2", 1)])
def test_a_ceiling_ends_the_comparison_with_1_when_it_is_passed(
        pair, capsys, flag, ceiling, code):
    now, before = pair
    assert run(now, before, flag, ceiling) == code
    err = capsys.readouterr().err
    assert ("the ceiling is" in err) is bool(code)


def test_a_ceiling_over_a_baseline_without_rows_ends_with_1(tmp_path, capsys):
    before = harvest_dir(tmp_path, "a", [], "before")
    now = harvest_dir(tmp_path, "a", numbered(2), "now")
    assert run(now, before) == 0
    assert run(now, before, "--max-gone", "0.5") == 1
    assert "not known" in capsys.readouterr().err


def test_the_largest_changes_are_limited_by_the_flag(tmp_path, capsys):
    before = harvest_dir(tmp_path, "a", numbered(5), "before")
    now = harvest_dir(tmp_path, "a", numbered(5, year=2030), "now")
    assert run(now, before, "--top", "2") == 0
    printed = capsys.readouterr().out
    assert "largest changes: 2 of the 5 row(s)" in printed
    assert "baseline  " in printed and "level A" in printed
    assert printed.count("       harvest   ") == 2
    run(now, before, "--top", "0")
    printed = capsys.readouterr().out
    assert "largest changes: 0 of the 5 row(s)" in printed
    assert "       harvest   " not in printed


def test_the_report_is_written_as_it_is_counted(pair, tmp_path):
    now, before = pair
    out = tmp_path / "report" / "diff.json"
    assert run(now, before, "--json", str(out), "--top", "1") == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    counted = evaluate.diff(
        gold.harvest(now), gold.harvest(before), top=1)
    assert written == json.loads(json.dumps(counted))
    assert written["rows"] == tally(same=2, changed=1, gone=1, new=1)


def test_every_number_says_what_it_counts(pair, capsys):
    now, before = pair
    run(now, before)
    lines = capsys.readouterr().out.splitlines()
    said = " ".join(lines)
    for unit in ("document(s)", "row(s)", "coordinate(s)"):
        assert unit in said
    states = next(line for line in lines if line.startswith("coordinate "))
    assert "coordinate(s) of the rows both harvests carry" in states


def test_two_parameters_that_differ_only_at_the_end_are_two_lines(
        tmp_path, capsys):
    """A name too long for its column is cut at the front: what tells
    parameters apart is the last part of their address."""
    stem = "https://example.org/a/very/long/path/of/parameters/"
    first, second = stem + "energy_consumption", stem + "energy_production"
    before = harvest_dir(tmp_path, "a", [
        row(parameter=first), row(parameter=second, quote="| P | 1 |")],
        "before")
    now = harvest_dir(tmp_path, "a", [
        row(parameter=first, year=2030),
        row(parameter=second, quote="| P | 1 |")], "now")
    run(now, before)
    lines = capsys.readouterr().out.splitlines()
    assert any(line.strip().startswith("...") and "energy_consumption"
               in line and "1 changed" in line for line in lines)
    assert any("energy_production" in line and "1 same" in line
               for line in lines)


def test_a_trace_beside_the_harvest_is_not_a_document(pair, capsys):
    now, before = pair
    for folder in (now, before):
        (folder / "a.trace.jsonl").write_text(
            json.dumps({"t": "rows", "ms": 3}) + "\n", encoding="utf-8")
    run(now, before)
    assert "baseline  1 document(s)" in capsys.readouterr().out


def test_the_database_names_the_documents_a_model_transcribed(
        pair, tmp_path, capsys):
    now, before = pair
    database = tmp_path / "c.db"
    conn = sqlite3.connect(database)
    conn.execute('CREATE TABLE "Documents" ("id" INTEGER PRIMARY KEY, '
                 '"filename" TEXT, "page_text_transcribed" INTEGER)')
    conn.execute('INSERT INTO "Documents" VALUES (1, \'a.pdf\', 2)')
    conn.commit()
    conn.close()
    out = tmp_path / "with.json"
    assert run(now, before, "--db", str(database), "--json", str(out)) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["levels"]["gone"] \
        == {"A": 0, "B": 1, "C": 0}
    assert json.loads(out.read_text(encoding="utf-8"))["levels"][
        "transcribed"] == 1
    out = tmp_path / "without.json"
    assert run(now, before, "--json", str(out)) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["levels"]["gone"] \
        == {"A": 1, "B": 0, "C": 0}
    assert json.loads(out.read_text(encoding="utf-8"))["levels"][
        "transcribed"] == 0


def _docpipe(tmp_path, *words):
    """`docpipe evaluate words`, as a user runs it, in a process of its own
    with the libraries a laptop lacks stubbed."""
    child = {key: value for key, value in os.environ.items()
             if not key.startswith(("DOCPIPE_", "LLM_"))}
    child.update(PYTHONPATH=str(ROOT),
                 DOCPIPE_USAGE_DB=str(tmp_path / "usage.db"))
    return subprocess.run(
        [sys.executable, "-c", PROBE, "docpipe", "evaluate", *words],
        cwd=str(tmp_path), env=child, capture_output=True, text=True)


def test_docpipe_evaluate_takes_the_flag(pair, tmp_path):
    now, before = pair
    shown = _docpipe(tmp_path, str(now), "--diff", str(before))
    assert shown.returncode == 0, shown.stderr[-1500:]
    assert "baseline  1 document(s), 4 row(s)" in shown.stdout
    assert "Traceback" not in shown.stderr
    assert "RuntimeWarning" not in shown.stderr
    over = _docpipe(tmp_path, str(now), "--diff", str(before),
                    "--max-changed", "0.1")
    assert over.returncode == 1
    assert "the ceiling is 0.1" in over.stderr


# ------------------------------------------------------------------- refusals

@pytest.mark.parametrize("more", [
    ["--gold", "gold.jsonl"], ["--baseline", "."],
    ["--min-precision", "0.5"], ["--min-recall", "0.5"]])
def test_what_needs_the_decisions_is_refused_beside_the_flag(pair, more):
    now, before = pair
    with pytest.raises(SystemExit) as caught:
        run(now, before, *more)
    assert more[0] in str(caught.value)
    assert "--diff" in str(caught.value)


@pytest.mark.parametrize("more", [
    ["--top", "3"], ["--max-changed", "0.5"], ["--max-gone", "0.5"]])
def test_what_belongs_to_the_comparison_is_refused_without_it(pair, more):
    now, _before = pair
    with pytest.raises(SystemExit) as caught:
        evaluate.main([str(now), *more])
    assert more[0] in str(caught.value) and "--diff" in str(caught.value)


@pytest.mark.parametrize("flag, given", [
    ("--max-changed", "1.5"), ("--max-gone", "-0.1"),
    ("--max-changed", "nan"), ("--max-gone", "most"), ("--top", "-1"),
    ("--top", "many")])
def test_a_ceiling_or_a_limit_that_is_not_one_is_refused(pair, flag, given):
    now, before = pair
    with pytest.raises(SystemExit) as caught:
        run(now, before, flag, given)
    assert caught.value.code == 2


def test_a_directory_that_is_not_there_is_refused(pair, tmp_path):
    now, before = pair
    with pytest.raises(SystemExit) as caught:
        run(now, tmp_path / "nowhere")
    assert "not a directory" in str(caught.value)
    with pytest.raises(SystemExit) as caught:
        run(tmp_path / "nowhere", before)
    assert "not a directory" in str(caught.value)


def test_a_directory_without_a_harvest_is_not_a_harvest_without_rows(
        pair, tmp_path):
    """Nothing to compare against would read as every row new."""
    now, before = pair
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "a.trace.jsonl").write_text("{}\n", encoding="utf-8")
    for named in ((now, empty), (empty, before)):
        with pytest.raises(SystemExit) as caught:
            run(*named)
        assert str(empty) in str(caught.value)
        assert "no harvest file" in str(caught.value)
