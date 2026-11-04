"""A table's numbers are read by their place: one row per cell a reply names,
the table row its quote, a value named twice read once, and a number printed
twice in a row in two columns; a coordinate is taken at the value's cell
before its row label before its column head before the whole table, and only
through the field check; a frame coordinate left open takes the survey's one
tuple of the passage, but not against a year the row read under its own head.
A cell that prints several numbers is split into them in the order it prints
them, the value the place its entry names, an answer for one place holding
there before the answer for its column, an answer for a cell that names no
place holding for every value of the cell, and a cell that does not print
what its entry names is not read and counted.

A passage is read in requests of one task each (owner decision 2026-11-04):
the cells of a table or the values of a passage first, a value the check
refuses asked once more with its reason before anything else, then each
group of the spec in a request of its own, which shows its own coordinates,
where a plan prints them, and the cells or values it is about, the survey's
pairs and the plan's years only where it asks a frame coordinate, and whose
tools fetch for it alone.

A table longer than its budget is read in blocks of whole rows under its
title and head lines; the first part is asked first and the head rows it
names are shown with every later part, never read again; a part cut off is
asked again in halves, and a row still cut off, or a part not answered, is
lost on its own while the others are read; a table that fits is one request.

Every coordinate is answered: the grammar wants each coordinate of a group
for every value in text and for the whole table, and a year can be answered
as not printed. What the check refuses of a group's reply is asked once more
with its reason, and what the second reply answers is taken, but never over
a coordinate read the first time, and never a third time; a reply the check
takes whole is asked once. A coordinate left out is asked for by name, and
one no reply answers ends unanswered. A value whose passage names its state
by the plan's word takes the year of that state, and no other. A table or
figure is shown with the text of its section, the whole section when it fits
two pages and the part around its place when not, and a coordinate quoted
from that text is read and cites the section. A search is listed once, also
after a list of hits no search made. A cells reply names its cells last.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from dataclasses import replace
from pathlib import Path

import jsonschema

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import numbers_in_order
from docpipe.extraction.wording import say

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = {slot.name: slot for slot in reading.slots_of(SPEC, EMISSION)}
UNSTATED = fields.UNSTATED

TABLE = ("Tabelle 3: Treibhausgasemissionen der Stadt im Jahr 2022\n"
         "| Bilanz | Haushalte | GHD | gesamt |\n"
         "| --- | --- | --- | --- |\n"
         "| | in t CO2 | in t CO2 | in t CO2 |\n"
         "| Erdgas | 1.200 | 800 | 2.000 |\n"
         "| Heizöl | 27 | 28 | 27 |")
TEXT = Source("section", 6, "Im Jahr 2022 fielen rund 300 t CO2 bei Erdgas an.",
              {"document_id": 7, "section_title": "Bilanz"})


def table(text=TABLE):
    return Source("table", 5, text, {"document_id": 7, "page": 3,
                                     "section_title": "Bilanz"})


def test_a_table_gives_its_rows_cell_by_cell_and_text_gives_none():
    grid = reading.grid_of(TABLE)
    assert grid.columns == 4 and len(grid.body) == 3
    assert grid.body[1][1] == ["Erdgas", "1.200", "800", "2.000"]
    assert reading.grid_of("Ein Satz ohne Tabelle.") is None


def test_a_cell_gives_its_one_number_and_none_for_none_or_two():
    assert reading.cell_number("1.200") == 1200
    assert reading.cell_number("-1.155") == -1155
    assert reading.cell_number("40,8 %") == 40.8
    assert reading.cell_number("") is None
    assert reading.cell_number("1699/1989") is None
    assert reading.cell_number("in t CO2") is None


def cells(*named, **reply):
    """A table reply naming the values at *named*: (row, column), or (row,
    column, part, parts) for a cell that prints several numbers."""
    out = []
    for cell in named:
        entry = {"row": cell[0], "column": cell[1]}
        if len(cell) > 2:
            entry.update(part=cell[2], parts=cell[3])
        out.append(entry)
    return {"values": out, **reply}


def test_each_cell_named_is_a_row_quoted_by_its_line():
    grid = reading.grid_of(TABLE)
    rows, at, skipped = reading.table_rows(
        cells((2, 2), (2, 3), (2, 4), (3, 2), (3, 3), (3, 4)), grid)
    assert [r.claim["value"] for r in rows] == [1200, 800, 2000, 27, 28, 27]
    assert rows[0].claim["quote"] == "| Erdgas | 1.200 | 800 | 2.000 |"
    assert skipped == 0


def test_a_number_printed_twice_in_a_row_keeps_its_own_column():
    grid = reading.grid_of(TABLE)
    rows, at, _ = reading.table_rows(cells((3, 2), (3, 3), (3, 4)), grid)
    twice = [at[r.label][1] for r in rows if r.claim["value"] == 27]
    assert twice == [2, 4]
    assert [r.claim.get("head") for r in rows if r.claim["value"] == 27] \
        != [None, None]


def test_a_row_outside_the_table_or_a_unit_row_gives_no_value():
    grid = reading.grid_of(TABLE)
    rows, _, skipped = reading.table_rows(cells((9, 2)), grid)
    assert rows == [] and skipped == 1
    rows, _, skipped = reading.table_rows(cells((1, 2)), grid)
    assert rows == [] and skipped == 1        # the 2 of CO2 is a name


def test_a_value_named_twice_is_read_once():
    rows, _, skipped = reading.table_rows(cells((2, 3), (2, 3)),
                                          reading.grid_of(TABLE))
    assert [r.claim["value"] for r in rows] == [800] and skipped == 0


def merged(reply):
    grid = reading.grid_of(TABLE)
    rows, at, _ = reading.table_rows(reply, grid)
    for name in ("carrier", "sector", "unit"):
        for _level, window, field_reply in reading.table_replies(
                reply, SLOTS[name], at):
            reading.merge_field(rows, [table()], SLOTS[name], field_reply,
                                window=window)
    return rows


def test_a_row_label_wins_over_the_table_and_a_column_head_is_read():
    rows = merged(cells((2, 2), (2, 3), coordinates={
            "carrier": {"rows": [{"row": 2, "value": "Erdgas",
                                  "quote": "| Erdgas | 1.200 | 800 | 2.000 |"}],
                        "table": {"value": "Summe", "value_raw": "gesamt",
                                  "quote": "| Bilanz | Haushalte | GHD | "
                                           "gesamt |"}},
            "sector": {"columns": [
                {"column": 2, "value": "Private Haushalte",
                 "value_raw": "Haushalte",
                 "quote": "| Bilanz | Haushalte | GHD | gesamt |"},
                {"column": 3, "value": "GHD",
                 "quote": "| Bilanz | Haushalte | GHD | gesamt |"}]}}))
    assert [r.claim["carrier"] for r in rows] == ["Erdgas"] * 2
    assert [r.claim["sector"] for r in rows] == ["Private Haushalte", "GHD"]
    assert rows[0].claim["carrier_window"] == ["own", 1] \
        or rows[0].claim["carrier_window"] == ("own", 1)


def test_a_coordinate_whose_quote_is_not_in_the_table_is_not_read():
    rows = merged(cells((2, 2), coordinates={"carrier": {"table": {
        "value": "Erdgas", "quote": "Erdgas wird hier nicht gedruckt"}}}))
    assert rows[0].claim.get("carrier_state") != "read"


# -- a cell that prints several numbers ----------------------------------------

SHARES = ("Tabelle 9: Emissionen mit Anteil\n"
          "| Träger | Haushalte und GHD | gesamt |\n"
          "| --- | --- | --- |\n"
          "| Erdgas | 1.200 (60 %) | 2.000 |\n"
          "| Heizöl | 800 | 1.000 |")
SHARES_HEAD = "| Träger | Haushalte und GHD | gesamt |"


def shares(*named):
    return reading.table_rows(cells(*named), reading.grid_of(SHARES))


def test_a_cell_with_several_numbers_gives_each_value_it_names_a_row():
    rows, at, skipped = shares((1, 2, 1, 2), (1, 2, 2, 2), (1, 3))
    assert [r.claim["value"] for r in rows] == [1200, 60, 2000]
    assert [at[r.label][1:] for r in rows] == [(2, 1), (2, 2), (3, None)]
    assert {r.claim["quote"] for r in rows} == {
        "| Erdgas | 1.200 (60 %) | 2.000 |"}
    assert rows[0].claim["head"] == rows[1].claim["head"] and skipped == 0


def test_only_the_place_a_value_names_is_read():
    assert [r.claim["value"] for r in shares((1, 2, 2, 2))[0]] == [60]
    assert [r.claim["value"] for r in shares((1, 2, 1, 2))[0]] == [1200]


def test_a_cell_that_does_not_print_what_its_value_names_is_not_read():
    for named in ((1, 2, 1, 3),         # the cell prints two numbers, not 3
                  (2, 2, 1, 2),         # "800" prints one number, not two
                  (1, 2),               # one number named, two printed
                  (1, 2, 3, 2),         # no third place of two
                  (1, 3, 2, None)):     # a second place of one number
        rows, _, skipped = shares(named)
        assert rows == [] and skipped == 1, named
    rows, at, skipped = shares((2, 2))
    assert [r.claim["value"] for r in rows] == [800]
    assert skipped == 0 and at[rows[0].label][2] is None


def test_a_cell_reads_its_numbers_in_order_with_their_signs():
    assert reading.cell_numbers("566 MWh (-59 %)", 2) == [566, -59]
    assert reading.cell_numbers("500 kW<br>1.821 MWh/a<br>73%", 3) \
        == [500, 1821, 73]
    assert reading.cell_numbers("2020-2030", 2) == [2020, 2030]
    assert reading.cell_numbers("1.200 (60 %)", 3) is None
    assert reading.cell_numbers("1.200 (60 %)", 1) is None


def test_digits_grouped_by_a_space_are_read_as_the_count_asks():
    assert reading.cell_numbers("967 168%", 2) == [967, 168]
    assert reading.cell_numbers("1 234", 1) == [1234]
    assert reading.cell_numbers("1 234 (5 %)", 2) == [1234, 5]


def test_a_text_gives_its_numbers_in_the_order_it_prints_them():
    assert numbers_in_order("566 (-59 %) von 2020-2030") \
        == ["566", "-59", "2020", "2030"]
    assert numbers_in_order("967 168%") == ["967", "168"]
    assert numbers_in_order("967 168%", grouped=True) == ["967168"]


def sectors(reply):
    rows, at, _ = reading.table_rows(reply, reading.grid_of(SHARES))
    for _level, window, field_reply in reading.table_replies(
            reply, SLOTS["sector"], at):
        reading.merge_field(rows, [table(SHARES)], SLOTS["sector"],
                            field_reply, window=window)
    return [r.claim.get("sector") for r in rows]


HOUSEHOLDS = {"value": "Private Haushalte", "value_raw": "Haushalte",
              "quote": SHARES_HEAD}
SERVICES = {"value": "GHD", "quote": SHARES_HEAD}


def test_an_answer_for_one_place_holds_there_before_its_whole_column():
    assert sectors(cells((1, 2, 1, 2), (1, 2, 2, 2), coordinates={
        "sector": {"columns": [
            dict(HOUSEHOLDS, column=2), dict(SERVICES, column=2, part=2),
            dict(SERVICES, column=2, part=3)]}})) \
        == ["Private Haushalte", "GHD"]


def test_a_value_s_own_answer_holds_before_its_row_column_and_table():
    reply = cells((1, 2, 1, 2), (1, 2, 2, 2), coordinates={"sector": {
        "rows": [dict(HOUSEHOLDS, row=1)],
        "columns": [dict(HOUSEHOLDS, column=2)],
        "cells": [dict(SERVICES, row=1, column=2, part=2)],
        "table": HOUSEHOLDS}})
    assert sectors(reply) == ["Private Haushalte", "GHD"]
    # An answer for a cell that names no place holds for every value of it.
    reply["coordinates"]["sector"]["cells"] = [dict(SERVICES, row=1,
                                                    column=2)]
    assert sectors(reply) == ["GHD", "GHD"]
    del reply["coordinates"]["sector"]["cells"]
    assert sectors(reply) == ["Private Haushalte", "Private Haushalte"]


def test_a_refused_answer_is_asked_again_for_its_value_row_or_place():
    rows, at, _ = shares((1, 2, 1, 2), (1, 2, 2, 2), (1, 3))

    def asked(level, row):
        return reading.table_corrections(
            [("unit", level, {"row": row.label, "reason": "r", "why": "w"})],
            at)

    assert asked(reading.COLUMNS, rows[1]) == [
        {"coordinate": "unit", "column": 2, "part": 2, "what": "r"}]
    assert asked(reading.COLUMNS, rows[2]) == [
        {"coordinate": "unit", "column": 3, "what": "r"}]
    assert asked(reading.VALUES, rows[1]) == [
        {"coordinate": "unit", "row": 1, "column": 2, "part": 2, "what": "r"}]
    assert asked(reading.ROWS, rows[0]) == [
        {"coordinate": "unit", "row": 1, "what": "r"}]
    assert asked(reading.TABLE, rows[0]) == [
        {"coordinate": "unit", "what": "r"}]


FRAME = [slot for slot in reading.slots_of(SPEC, EMISSION)
         if slot.name in ("scenario", "year")]
TUPLE = {"scenario": "Bestand", "scenario_raw": "im Jahr 2022",
         "scenario_quote": "im Jahr 2022", "scenario_source": ["table", 5],
         "year": 2022, "year_quote": "im Jahr 2022",
         "year_source": ["table", 5]}


def test_an_open_frame_takes_the_surveys_one_tuple_with_its_quote():
    grid = reading.grid_of(TABLE)
    rows, _, _ = reading.table_rows(cells((2, 2)), grid)
    taken = reading.inherit(rows, FRAME, [TUPLE], [TUPLE], [table()])
    assert taken == 2
    assert rows[0].claim["year"] == 2022
    assert rows[0].claim["year_quote"] == "im Jahr 2022"
    assert list(rows[0].claim["year_window"])[0] == "frame"


def test_two_tuples_or_a_year_of_its_own_take_nothing_from_the_survey():
    grid = reading.grid_of(TABLE)
    rows, _, _ = reading.table_rows(cells((2, 2)), grid)
    assert reading.inherit(rows, FRAME, [TUPLE, dict(TUPLE, year=2040)],
                           [], [table()]) == 0
    rows[0].claim.update(year=2040, year_state="read")
    assert reading.inherit(rows, FRAME, [TUPLE], [TUPLE], [table()]) == 0
    assert rows[0].claim["year"] == 2040
    assert rows[0].claim.get("scenario_state") != "read"


# -- every coordinate answered -------------------------------------------------

GROUPS = reading.groups_of(SPEC, list(SLOTS.values()))
# The groups that ask a frame coordinate: they alone are shown the pairs.
FRAMED = {group.name for group, slots in GROUPS
          if {slot.name for slot in slots} & {slot.name for slot in FRAME}}


def value_grammar(labels=("R1",)):
    return reading.text_response_format(
        list(SLOTS.values()), list(labels))["json_schema"]["schema"]


def table_grammar():
    return reading.table_response_format(
        list(SLOTS.values()))["json_schema"]["schema"]


def cells_grammar():
    return reading.cells_response_format()["json_schema"]["schema"]


def rejected(instance, schema) -> bool:
    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError:
        return True
    return False


def everything(**given):
    """Every coordinate of an emission value: not printed but for *given*."""
    out = {name: {"value": UNSTATED} for name in SLOTS}
    out.update(given)
    return out


def entry(**given):
    """A group reply's entry for the one value of a passage, "R1"."""
    return {"row": "R1", **everything(**given)}


UNIT = {"value": "t CO2", "quote": "rund 300 t CO2"}
VALUE = {"value": 300, "quote": "rund 300 t CO2"}
EVERY = {name: {"table": {"value": UNSTATED}} for name in SLOTS}
TABLE_UNIT = {"table": {"value": "t CO2",
                        "quote": "| | in t CO2 | in t CO2 | in t CO2 |"}}


def test_the_grammar_wants_every_coordinate_of_a_value_in_text():
    assert not rejected({"values": [entry(unit=UNIT)]}, value_grammar())
    without_year = {k: v for k, v in entry(unit=UNIT).items() if k != "year"}
    assert rejected({"values": [without_year]}, value_grammar())
    assert rejected({"values": [dict(entry(unit=UNIT), row="R2")]},
                    value_grammar())


def test_the_grammar_wants_every_coordinate_of_a_table_for_the_whole_table():
    assert not rejected({"coordinates": EVERY}, table_grammar())
    for broken in ({name: one for name, one in EVERY.items()
                    if name != "carrier"},
                   dict(EVERY, carrier={"rows": []})):
        assert rejected({"coordinates": broken}, table_grammar()), broken


def test_the_cells_grammar_takes_a_value_by_its_cell_and_its_place():
    assert not rejected(cells((1, 2, 1, 2), head_rows=[1]), cells_grammar())
    for broken in ([{"row": 1}], [{"column": 2}],
                   [{"row": 1, "column": 2, "share": 1}]):
        assert rejected({"values": broken}, cells_grammar()), broken


def test_a_group_answers_for_a_single_value_by_its_cell_and_its_place():
    unit = {"table": {"value": UNSTATED},
            "cells": [{"row": 1, "column": 2, "part": 1, "value": UNSTATED}]}
    assert not rejected({"coordinates": dict(EVERY, unit=unit)},
                        table_grammar())
    for broken in ({"row": 1, "value": UNSTATED},
                   {"column": 2, "value": UNSTATED}):
        assert rejected({"coordinates": dict(EVERY, unit=dict(
            unit, cells=[broken]))}, table_grammar()), broken


def test_a_cells_reply_names_its_cells_last():
    # A server that does not hold a reply to its schema closed one object
    # short on large tables when the reply ended deep in its objects.
    assert list(cells_grammar()["properties"])[-1] == "values"
    assert cells_grammar()["required"] == ["values"]


def test_a_year_can_be_answered_as_not_printed_and_only_as_a_year():
    year = reading.answer_schema(SLOTS["year"])
    jsonschema.validate({"value": 2022}, year)
    jsonschema.validate({"value": UNSTATED}, year)
    try:
        jsonschema.validate({"value": "2022 bis 2030"}, year)
    except jsonschema.ValidationError:
        return
    raise AssertionError("a year as text passed the grammar")


# -- asked again with the reason -----------------------------------------------

def nth(given, calls, task):
    """The reply to the latest request of *task*: the n-th of *given* for
    its n-th request, the last one again after that."""
    n = sum(1 for asked, _ in calls if asked == task)
    return given[min(n, len(given)) - 1]


def read_text(*replies, values=({"values": [VALUE]},), source=TEXT, **kw):
    """What reading *source* came to, and each request as (task,
    corrections), the task "values" or the name of a group: the values
    requests answered by *values*, the requests of each group by
    *replies*."""
    calls = []

    def ask_values(shown, parameter, context, corrections):
        calls.append(("values", corrections))
        return nth(values, calls, "values")

    def ask_text(shown, parameter, group, slots, rows, context, corrections):
        calls.append((group.name, corrections))
        return nth(replies, calls, group.name)

    reader = reading.Reader(SPEC, None, None, ask_values, ask_text, FRAME,
                            **kw)
    read = reader.read(7, EMISSION, source, [], [],
                       {(source.owner_kind, source.owner_id): source})
    return read, calls


def read_table(*replies, named):
    """What reading TABLE came to, and each request as (task, corrections):
    the cells request answered by *named*, the requests of each group by
    *replies*."""
    calls = []

    def ask_cells(view, part, parameter, context):
        calls.append(("cells", None))
        return named

    def ask_table(view, part, parameter, group, slots, shown, context,
                  corrections):
        calls.append((group.name, corrections))
        return nth(replies, calls, group.name)

    reader = reading.Reader(SPEC, ask_cells, ask_table, None, None, FRAME)
    read = reader.read(7, EMISSION, table(), [], [], {("table", 5): table()})
    return read, calls


def asked_again(calls) -> list:
    return [(task, corrections) for task, corrections in calls
            if corrections is not None]


WRONG_CARRIER = {"value": "Erdgas", "quote": "Erdgas steht hier nicht"}
RIGHT_CARRIER = {"value": "Erdgas", "quote": "300 t CO2 bei Erdgas"}


def test_a_coordinate_the_check_refuses_is_asked_again_with_its_reason():
    read, calls = read_text(
        {"values": [entry(unit=UNIT, carrier=WRONG_CARRIER)]},
        {"values": [entry(unit=UNIT, carrier=RIGHT_CARRIER)]})
    assert asked_again(calls) == [("context", [
        {"row": "R1", "what": {"carrier": say("quote_not_in_source")}}])]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"
    assert read.asked == 1 + len(GROUPS) + 1


def test_a_value_the_check_refuses_is_asked_again_before_any_group():
    for wrong in (dict(VALUE, value=300000),            # its quote: not that
                  dict(VALUE, quote="rund 300 t CO2 im Jahr")):  # not there
        read, calls = read_text(
            {"values": [entry(unit=UNIT)]},
            values=({"values": [wrong]}, {"values": [dict(VALUE, row="R1")]}))
        assert [task for task, _ in calls[:2]] == ["values", "values"]
        assert [(c["row"], c["value"], c["quote"]) for c in calls[1][1]] \
            == [("R1", wrong["value"], wrong["quote"])]
        assert (read.claims[0]["value"], read.claims[0]["quote"]) \
            == (300, "rund 300 t CO2")
    _read, calls = read_text({"values": [entry(unit=UNIT)]})
    assert [task for task, _ in calls].count("values") == 1


def test_a_table_coordinate_the_check_refuses_is_asked_again_for_its_row():
    def reply(carrier_quote):
        return {"coordinates": dict(EVERY, unit=TABLE_UNIT, carrier={
            "rows": [{"row": 2, "value": "Erdgas", "quote": carrier_quote}],
            "table": {"value": UNSTATED}})}

    read, calls = read_table(reply("| Erdgas steht nicht |"),
                             reply("| Erdgas | 1.200 | 800 | 2.000 |"),
                             named=cells((2, 2)))
    assert asked_again(calls) == [("context", [
        {"coordinate": "carrier", "row": 2,
         "what": say("quote_not_in_source")}])]
    assert read.claims[0]["carrier_state"] == "read"


def test_a_reply_wrong_twice_is_not_asked_a_third_time():
    read, calls = read_text(
        {"values": [entry(unit=UNIT, carrier=WRONG_CARRIER)]})
    assert [task for task, _ in calls].count("context") == 2
    assert read.claims[0]["carrier_state"] == "unbacked"


def test_a_reply_the_check_takes_whole_is_asked_once():
    read, calls = read_text(
        {"values": [entry(unit=UNIT, carrier=RIGHT_CARRIER)]})
    assert calls == [("values", None)] + [(group.name, None)
                                          for group, _ in GROUPS]
    assert read.asked == 1 + len(GROUPS)


def test_a_coordinate_read_the_first_time_stays_as_read():
    first = entry(unit=UNIT, carrier=RIGHT_CARRIER)
    del first["sector"]
    read, calls = read_text(
        {"values": [first]},
        {"values": [entry(unit=UNIT, carrier={"value": UNSTATED})]})
    assert asked_again(calls) == [("context", [
        {"row": "R1", "what": {"sector": say("key_missing", key="sector")}}])]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"
    assert claim["sector_state"] == "unstated"


def test_a_coordinate_left_out_is_asked_for_by_name_and_ends_unanswered():
    left = entry(unit=UNIT)
    del left["year"]
    read, calls = read_text({"values": [left]})
    assert asked_again(calls) == [("frame", [
        {"row": "R1", "what": {"year": say("key_missing", key="year")}}])]
    assert read.claims[0]["year_state"] == "unanswered"
    assert read.unanswered == 1


# -- one task per request ------------------------------------------------------

class Found:
    answers: dict = {}

    def passages_of(self, parameter):
        return [("table", 5), ("section", 6)] \
            if parameter == "emission" else []

    def tuples_at(self, owner, group):
        return [TUPLE] if owner == ("table", 5) else []


def test_each_group_is_asked_alone_and_only_a_frame_group_sees_the_pairs():
    asked = []

    def ask_cells(view, part, parameter, context):
        asked.append(("cells", reading.cells_payload(view, part, parameter,
                                                     context)))
        return cells((2, 2), (2, 3))

    def ask_table(view, part, parameter, group, slots, shown, context,
                  corrections):
        asked.append(("table", reading.table_payload(
            view, part, parameter, slots, shown, group.where, context,
            corrections)))
        return {"coordinates": dict(EVERY, unit=TABLE_UNIT)}

    def ask_values(shown, parameter, context, corrections):
        asked.append(("values", reading.values_payload(shown, parameter,
                                                       context, corrections)))
        return {"values": [VALUE]}

    def ask_text(shown, parameter, group, slots, rows, context, corrections):
        asked.append(("text", reading.text_payload(
            shown, parameter, slots, rows, group.where, context,
            corrections)))
        return {"values": [entry(unit=UNIT)]}

    reader = reading.Reader(SPEC, ask_cells, ask_table, ask_values, ask_text,
                            FRAME)
    reads = reader(7, Found(), {("table", 5): table(), ("section", 6): TEXT})
    assert [task for task, _ in asked] == [
        "cells", *["table"] * len(GROUPS), "values", *["text"] * len(GROUPS)]
    groups = [(group.where, {slot.name for slot in slots})
              for group, slots in GROUPS]
    for task, payload in asked:
        framed = bool(set(payload.get("coordinates") or ())
                      & {slot.name for slot in FRAME})
        assert ("known" in payload) == framed, (task, payload)
    for task, about in (("table", [{"row": 2, "column": 2},
                                   {"row": 2, "column": 3}]),
                        ("text", [dict(VALUE, row="R1")])):
        payloads = [payload for asked_as, payload in asked
                    if asked_as == task]
        assert [(p["where"], set(p["coordinates"])) for p in payloads] \
            == groups
        assert all(p["values"] == about for p in payloads)
    assert next(payload["known"] for task, payload in asked
                if task == "table" and "known" in payload) \
        == [{"scenario": "Bestand", "year": 2022}]
    values = {c["value"]: c for r in reads for c in r.claims}
    assert set(values) == {1200, 800, 300}
    assert values[300]["unit"] == "t CO2" and values[300]["unit_state"] \
        == "read"
    assert values[1200]["year"] == 2022
    assert values[300]["year_state"] == "unstated"


# -- the plan's own years ------------------------------------------------------

BASES = [{"state": "base", "axis": "year", "year": 2022,
          "quote": "im Jahr 2022", "source": ["table", 5], "index": 0},
         {"state": "target", "axis": "year", "year": 2045,
          "quote": "bis zum Jahr 2045", "source": ["table", 5], "index": 1}]


def test_a_request_asking_the_year_shows_the_base_and_target_years():
    assert reading.years_of(BASES, list(SLOTS.values())) \
        == {"base_years": [2022], "target_years": [2045]}
    assert reading.years_of(BASES, [SLOTS["carrier"]]) == {}
    shown = {}

    def ask_text(source, parameter, group, slots, rows, context, corrections):
        shown[group.name] = reading.text_payload(
            source, parameter, slots, rows, group.where, context, corrections)
        return {"values": [entry(unit=UNIT)]}

    reader = reading.Reader(SPEC, None, None, lambda *a: {"values": [VALUE]},
                            ask_text, FRAME, bases=lambda pairs: BASES)
    reader.read(7, EMISSION, TEXT, [], [], {("section", 6): TEXT})
    assert {name: (payload.get("base_years"), payload.get("target_years"))
            for name, payload in shown.items()} \
        == {group.name: (([2022], [2045]) if group.name in FRAMED
                         else (None, None)) for group, _ in GROUPS}
    grid = reading.grid_of(TABLE)
    assert reading.table_payload(table(), grid, EMISSION, list(SLOTS.values()),
                                 [], "", {"known": [], "base_years": [2022]})[
        "base_years"] == [2022]


def read_by_word(year):
    text = Source("section", 6, "Im Bestand fielen rund 300 t CO2 an.",
                  {"document_id": 7, "section_title": "Bilanz"})
    read, _ = read_text({"values": [entry(unit=UNIT, year={
        "value": year, "value_raw": "Bestand",
        "quote": "Im Bestand fielen rund 300 t CO2"})]},
        source=text, bases=lambda pairs: BASES)
    return read.claims[0]


def test_a_value_named_by_the_plans_word_for_its_state_takes_that_year():
    claim = read_by_word(2022)
    assert claim["year"] == 2022 and claim["year_state"] == "read"
    assert claim["year_quote"] == "im Jahr 2022"
    assert claim["year_link_quote"] == "Im Bestand fielen rund 300 t CO2"


def test_a_year_named_by_the_word_but_not_of_the_plan_is_not_read():
    assert read_by_word(2019)["year_state"] == "unbacked"


# -- the text around a table ---------------------------------------------------

SECTION = Source("section", 9,
                 "Bilanz\nDie folgende Tabelle zeigt die Emissionen im Jahr "
                 "2022.\n[t5: Tabelle 3]\nDarunter steht ein Absatz.",
                 {"document_id": 7, "section_title": "Bilanz"})


def placed():
    return Source("table", 5, TABLE, {"document_id": 7,
                                      "section_title": "Bilanz",
                                      "parent_section": 9, "block_id": "t5"})


def test_a_table_is_shown_with_its_section_or_the_part_around_its_place():
    passages = {("section", 9): SECTION}
    assert reading.around_of(placed(), passages, 4000).text == SECTION.text
    long = replace(SECTION, text="x" * 5000 + "[t5: Tabelle 3]" + "y" * 5000)
    cut = reading.around_of(placed(), {("section", 9): long}, 1000).text
    assert len(cut) == 1000 and "[t5" in cut
    assert reading.around_of(table(), passages, 4000) is None
    assert reading.around_of(SECTION, passages, 4000) is None


def test_a_year_printed_in_the_text_around_a_table_is_read_from_there():
    shown = []

    def ask_cells(view, part, parameter, context):
        shown.append(reading.cells_payload(view, part, parameter, context))
        return cells((2, 2))

    def ask_table(view, part, parameter, group, slots, named, context,
                  corrections):
        shown.append(reading.table_payload(view, part, parameter, slots,
                                           named, group.where, context,
                                           corrections))
        return {"coordinates": dict(EVERY, unit=TABLE_UNIT, year={"table": {
            "value": 2022, "quote": "die Emissionen im Jahr 2022"}})}

    reader = reading.Reader(SPEC, ask_cells, ask_table, None, None, FRAME)
    read = reader.read(7, EMISSION, placed(), [], [],
                       {("table", 5): placed(), ("section", 9): SECTION},
                       budget=4000)
    assert len(shown) == 1 + len(GROUPS)
    assert all("Die folgende Tabelle" in payload["around"]
               for payload in shown)
    claim = read.claims[0]
    assert claim["year"] == 2022 and claim["year_state"] == "read"
    assert claim["year_source"] == ["section", 9]
    alone = reader.read(7, EMISSION, placed(), [], [],
                        {("table", 5): placed()}, budget=4000)
    assert alone.claims[0]["year_state"] == "unbacked"


# -- a table in parts ----------------------------------------------------------

LONG = "\n".join(["Tabelle 7: Endenergie je Träger im Jahr 2022",
                  "| Träger | 2022 | 2045 |",
                  "| --- | --- | --- |",
                  "| | in MWh | in MWh |"]
                 + [f"| Träger {n} | {n}.100 | {n}.200 |" for n in range(1, 9)])
UNIT_ROW = "| | in MWh | in MWh |"


def test_a_table_longer_than_its_budget_is_read_in_blocks_of_whole_rows():
    grid = reading.grid_of(LONG)
    assert reading.table_blocks(grid, None) == [list(range(1, 10))]
    assert reading.table_blocks(grid, len(LONG)) == [list(range(1, 10))]
    blocks = reading.table_blocks(grid, 150)
    assert len(blocks) > 2
    assert [n for block in blocks for n in block] == list(range(1, 10))
    for block in blocks:
        text = reading.part_of(grid, block).text
        assert text.startswith("Tabelle 7") and "| Träger | 2022 |" in text
        assert len(block) == 1 or len(text) <= 150


def read_long(answer, budget=150, tuples=()):
    """What reading LONG for EMISSION in parts came to, and each cells
    request: (rows to read, text shown, part)."""
    asked = []

    def ask_cells(view, part, parameter, context):
        asked.append((part.row_numbers(), view.text, context.get("part")))
        return answer(part)

    long = table(LONG)
    reader = reading.Reader(SPEC, ask_cells, lambda *a: {"coordinates": EVERY},
                            None, None, FRAME)
    return reader.read(7, EMISSION, long, list(tuples), list(tuples),
                       {("table", 5): long}, budget=budget), asked


def every_value(grid, head=(1,)):
    """Every value of column 2 in the rows of *grid*, the unit row too."""
    return cells(*[(r, 2) for r in grid.row_numbers()], (1, 2),
                 head_rows=list(head))


def test_the_first_part_names_the_head_rows_every_later_part_shows():
    read, asked = read_long(every_value)
    assert len(asked) > 2
    assert asked[0][2]["first"] and not any(p["first"] for _, _, p in asked[1:])
    assert all(UNIT_ROW in text and 1 not in rows
               for rows, text, _ in asked[1:])
    assert sorted(c["value"] for c in read.claims) \
        == [n * 1000 + 100 for n in range(1, 9)]       # the head row: no value
    assert read.skipped == len(asked) and read.lost == []
    _, asked = read_long(lambda grid: every_value(grid, head=()))
    assert not any(UNIT_ROW in text for _, text, _ in asked[1:])
    # The values of every part are rows of one reading: all take the frame.
    framed, _ = read_long(every_value, tuples=[TUPLE])
    assert [c.get("year") for c in framed.claims] == [2022] * 8


def test_a_part_cut_off_is_asked_again_in_halves_and_one_row_left_is_lost():
    read, asked = read_long(lambda grid: reading.CUT
                            if 5 in grid.row_numbers() else every_value(grid))
    assert sorted(c["value"] for c in read.claims) \
        == [n * 1000 + 100 for n in range(1, 9) if n != 4]   # row 5: Träger 4
    assert [rows for rows, _, _ in asked if 5 in rows][-1] == [5]
    assert read.lost == [reading.CUT] and not read.unread
    silent, asked = read_long(lambda grid: None
                              if 5 in grid.row_numbers() else every_value(grid))
    assert silent.lost == [reading.NO_ANSWER]
    assert len([rows for rows, _, _ in asked if 5 in rows]) == 1   # not halved
    every, _ = read_long(lambda grid: reading.CUT)
    assert every.unread and every.why == reading.CUT and every.lost == []


def test_a_table_that_fits_is_one_request_with_no_part():
    read, asked = read_long(every_value, budget=len(LONG))
    assert len(asked) == 1 and asked[0][2] is None
    assert len(read.claims) == 8


# -- asking for more of the plan -----------------------------------------------

BARE = Source("section", 6, "Bilanz\nEs fielen rund 300 t CO2 an.",
              {"document_id": 7, "section_title": "Bilanz"})
FIGURE = Source("figure", 30, "Abbildung 4\nBalken der Emissionen 2030",
                {"document_id": 7, "title": "Abbildung 4",
                 "parent_section": 6, "block_id": "p3_img1"})
AFTER = Source("section", 8, "Ausblick\nDie Werte gelten für das Jahr 2030.",
               {"document_id": 7, "section_title": "Ausblick"})
PLAN = {("section", 6): BARE, ("figure", 30): FIGURE, ("section", 8): AFTER}
BARE_UNIT = {"value": "t CO2", "quote": "rund 300 t CO2"}


def gathering(*replies, passages=PLAN, asks="year"):
    """What reading BARE came to, what each request of the group that asks
    *asks* showed, and what the requests of the other groups showed: the
    n-th request of that group answered by the n-th of *replies*, every
    other group at once."""
    shows, others = [], []

    def ask_text(source, parameter, group, slots, rows, context, corrections):
        if asks not in {slot.name for slot in slots}:
            others.append(context)
            return bare()
        shows.append(context)
        return replies[min(len(shows), len(replies)) - 1]

    reader = reading.Reader(SPEC, None, None, lambda *a: {"values": [VALUE]},
                            ask_text, FRAME)
    read = reader.read(7, EMISSION, BARE, [], [], passages, budget=4000)
    return read, shows, others


def bare(more=None, **given):
    reply = {"values": [entry(unit=BARE_UNIT, **given)]}
    if more:
        reply["more"] = more
    return reply


YEAR_AFTER = {"value": 2030, "quote": "gelten für das Jahr 2030"}


def test_the_next_section_asked_for_is_shown_and_its_quote_is_read():
    read, shows, others = gathering(bare([{"get": "next"}]),
                                    bare(year=YEAR_AFTER))
    assert "more" not in shows[0]
    assert [m["text"] for m in shows[1]["more"]] == [AFTER.text]
    # What one group fetched is shown to that group alone.
    assert others and not any("more" in context for context in others)
    claim = read.claims[0]
    assert claim["year"] == 2030 and claim["year_state"] == "read"
    assert claim["year_source"] == ["section", 8]
    assert len(shows) == 2 and read.fetched == 1


def test_a_quote_from_a_section_never_shown_is_not_read():
    read, _shows, _ = gathering(bare(year=YEAR_AFTER))
    assert read.claims[0]["year_state"] == "unbacked"


def test_a_table_or_figure_named_by_its_placeholder_is_shown_and_none_else():
    _read, shows, _ = gathering(
        bare([{"get": "item", "id": "[p3_img1: Abbildung 4]"},
              {"get": "item", "id": "p9_img9"}]), bare())
    assert [m["kind"] for m in shows[1]["more"]] == ["figure"]
    assert shows[1]["not_found"] == [{"get": "item", "id": "p9_img9",
                                      "why": reading.UNKNOWN}]


def test_a_search_lists_its_hits_and_a_hit_asked_for_is_shown():
    read, shows, _ = gathering(
        bare([{"get": "search", "pattern": r"Jahr 20\d\d"}]),
        bare([{"get": "hit", "id": "H1"}]), bare(year=YEAR_AFTER))
    listed = shows[1]["hits"][0]
    assert listed["total"] == 1 and listed["hits"][0]["id"] == "H1"
    assert "more" not in shows[1]
    assert [m["text"] for m in shows[2]["more"]] == [AFTER.text]
    assert read.claims[0]["year_state"] == "read"


def test_a_search_after_a_list_no_search_made_is_searched_once():
    gathered = reading.Gathered()
    gathered.list_hits([(("section", 6), "Bilanz", "Es fielen rund 300 t CO2")],
                       query="Emissionen")
    ask = [{"get": "search", "pattern": r"Jahr 20\d\d"}]
    assert gathered.fetch(ask, list(PLAN.values()), PLAN, None)
    assert not gathered.fetch(ask, list(PLAN.values()), PLAN, None)


def test_gathering_ends_when_a_round_brings_nothing_new():
    _read, shows, _ = gathering(bare([{"get": "next"}]),
                                bare([{"get": "next"}, {"get": "next"}]))
    assert len(shows) == 2
    _read, shows, _ = gathering(bare([{"get": "item", "id": "p9_img9"}]))
    assert len(shows) == 1
    again = bare([{"get": "item", "id": "p3_img1"}])
    _read, shows, _ = gathering(again, again, bare())
    assert len(shows) == 2 and len(shows[1]["more"]) == 1


def test_a_request_that_no_longer_fits_leaves_the_reply_before_it():
    read, shows, _ = gathering(bare([{"get": "next"}]), reading.CUT,
                               asks="unit")
    assert len(shows) == 2 and not read.unread
    assert [claim["value"] for claim in read.claims] == [300]
    assert read.claims[0]["unit_state"] == "read"
