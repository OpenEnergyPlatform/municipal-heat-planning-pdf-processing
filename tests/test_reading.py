"""A table is read as one unit and its numbers by their place: one row per
cell of a value row and a value column, the table row its quote, and a
number printed twice in a row in two columns; a coordinate is taken at its
row label before its column head before the whole table, and only through
the field check; a frame coordinate left open takes the survey's one tuple
of the passage, but not against a year the row read under its own head. A
cell that prints several numbers is split into them in the order it prints
them where the reply says how many its column prints, each place it names a
value a row of its own, an answer for one place holding there before the
answer for its column, and a cell that prints another count is not read; a
column the reply does not split reads one number per cell as before.

Every coordinate is answered: the grammar wants each coordinate of a value
in text and each coordinate of a table for the whole table, and a year can
be answered as not printed. What the check refuses of a reply is asked once
more with its reason, and what the second reply answers is taken, but never
over a coordinate read the first time, and never a third time; a reply the
check takes whole is asked once. A coordinate left out is asked for by name,
and one no reply answers ends unanswered. A request that asks the year shows
the plan's base and target years, numbers only, and a value whose passage
names its state by the plan's word takes the year of that state, and no
other. A table or figure is shown with the text of its section, the whole
section when it fits two pages and the part around its place when not, and a
coordinate quoted from that text is read and cites the section. A search is
listed once, also after a list of hits no search made.

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


def test_each_cell_of_a_value_row_and_column_is_a_row_quoted_by_its_line():
    grid = reading.grid_of(TABLE)
    rows, at, skipped = reading.table_rows(
        {"value_columns": [2, 3, 4], "value_rows": [2, 3]}, grid)
    assert [r.claim["value"] for r in rows] == [1200, 800, 2000, 27, 28, 27]
    assert rows[0].claim["quote"] == "| Erdgas | 1.200 | 800 | 2.000 |"
    assert skipped == 0


def test_a_number_printed_twice_in_a_row_keeps_its_own_column():
    grid = reading.grid_of(TABLE)
    rows, at, _ = reading.table_rows(
        {"value_columns": [2, 3, 4], "value_rows": [3]}, grid)
    twice = [at[r.label][1] for r in rows if r.claim["value"] == 27]
    assert twice == [2, 4]
    assert [r.claim.get("head") for r in rows if r.claim["value"] == 27] \
        != [None, None]


def test_a_row_outside_the_table_or_a_unit_row_gives_no_value():
    grid = reading.grid_of(TABLE)
    rows, _, skipped = reading.table_rows(
        {"value_columns": [2], "value_rows": [9]}, grid)
    assert rows == [] and skipped == 0
    rows, _, skipped = reading.table_rows(
        {"value_columns": [2], "value_rows": [1]}, grid)
    assert rows == [] and skipped == 1        # the 2 of CO2 is a name


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
    rows = merged({
        "value_columns": [2, 3], "value_rows": [2],
        "coordinates": {
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
                 "quote": "| Bilanz | Haushalte | GHD | gesamt |"}]}}})
    assert [r.claim["carrier"] for r in rows] == ["Erdgas"] * 2
    assert [r.claim["sector"] for r in rows] == ["Private Haushalte", "GHD"]
    assert rows[0].claim["carrier_window"] == ["own", 1] \
        or rows[0].claim["carrier_window"] == ("own", 1)


def test_a_coordinate_whose_quote_is_not_in_the_table_is_not_read():
    rows = merged({
        "value_columns": [2], "value_rows": [2],
        "coordinates": {"carrier": {"table": {
            "value": "Erdgas", "quote": "Erdgas wird hier nicht gedruckt"}}}})
    assert rows[0].claim.get("carrier_state") != "read"


# -- a cell that prints several numbers ----------------------------------------

SHARES = ("Tabelle 9: Emissionen mit Anteil\n"
          "| Träger | Haushalte und GHD | gesamt |\n"
          "| --- | --- | --- |\n"
          "| Erdgas | 1.200 (60 %) | 2.000 |\n"
          "| Heizöl | 800 | 1.000 |")
SHARES_HEAD = "| Träger | Haushalte und GHD | gesamt |"


def split(places, rows=(1,), numbers=2):
    return reading.table_rows(
        {"value_columns": [2, 3], "value_rows": list(rows),
         "cells": [{"column": 2, "numbers": numbers, "values": places}]},
        reading.grid_of(SHARES))


def test_a_cell_is_split_into_its_numbers_and_each_value_is_a_row_of_its_own():
    rows, at, skipped = split([1, 2])
    assert [r.claim["value"] for r in rows] == [1200, 60, 2000]
    assert [at[r.label][1:] for r in rows] == [(2, 1), (2, 2), (3, None)]
    assert {r.claim["quote"] for r in rows} == {
        "| Erdgas | 1.200 (60 %) | 2.000 |"}
    assert rows[0].claim["head"] == rows[1].claim["head"] and skipped == 0


def test_only_the_places_the_reply_names_are_read():
    assert [r.claim["value"] for r in split([2])[0]] == [60, 2000]
    assert [r.claim["value"] for r in split([1])[0]] == [1200, 2000]
    rows, _, skipped = split([3])       # no such place: the entry says nothing
    assert [r.claim["value"] for r in rows] == [2000] and skipped == 1


def test_a_cell_that_does_not_print_as_many_numbers_is_not_read():
    rows, _, skipped = split([1], rows=(1, 2))
    assert [r.claim["value"] for r in rows] == [1200, 2000, 1000]
    assert skipped == 1                 # "800" prints one number, not two


def test_a_column_the_reply_does_not_split_reads_one_number_per_cell():
    rows, at, skipped = reading.table_rows(
        {"value_columns": [2], "value_rows": [1, 2]},
        reading.grid_of(SHARES))
    assert [r.claim["value"] for r in rows] == [800]
    assert skipped == 1 and at[rows[0].label][2] is None


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


def test_an_answer_for_one_place_holds_there_before_its_whole_column():
    reply = {"value_columns": [2], "value_rows": [1],
             "cells": [{"column": 2, "numbers": 2, "values": [1, 2]}],
             "coordinates": {"sector": {"columns": [
                 {"column": 2, "value": "Private Haushalte",
                  "value_raw": "Haushalte", "quote": SHARES_HEAD},
                 {"column": 2, "part": 2, "value": "GHD",
                  "quote": SHARES_HEAD},
                 {"column": 2, "part": 3, "value": "GHD",
                  "quote": SHARES_HEAD}]}}}
    rows, at, _ = reading.table_rows(reply, reading.grid_of(SHARES))
    for _level, window, field_reply in reading.table_replies(
            reply, SLOTS["sector"], at):
        reading.merge_field(rows, [table(SHARES)], SLOTS["sector"],
                            field_reply, window=window)
    assert [r.claim["sector"] for r in rows] == ["Private Haushalte", "GHD"]


def test_a_refused_answer_for_one_place_is_asked_again_for_that_place():
    rows, at, _ = split([1, 2])
    failed = [("unit", reading.COLUMNS,
               {"row": label, "reason": "r", "why": "w"})
              for label in (rows[1].label, rows[2].label)]
    assert reading.table_corrections(failed, at) == [
        {"coordinate": "unit", "column": 2, "part": 2, "what": "r"},
        {"coordinate": "unit", "column": 3, "what": "r"}]


FRAME = [slot for slot in reading.slots_of(SPEC, EMISSION)
         if slot.name in ("scenario", "year")]
TUPLE = {"scenario": "Bestand", "scenario_raw": "im Jahr 2022",
         "scenario_quote": "im Jahr 2022", "scenario_source": ["table", 5],
         "year": 2022, "year_quote": "im Jahr 2022",
         "year_source": ["table", 5]}


def test_an_open_frame_takes_the_surveys_one_tuple_with_its_quote():
    grid = reading.grid_of(TABLE)
    rows, _, _ = reading.table_rows(
        {"value_columns": [2], "value_rows": [2]}, grid)
    taken = reading.inherit(rows, FRAME, [TUPLE], [TUPLE], [table()])
    assert taken == 2
    assert rows[0].claim["year"] == 2022
    assert rows[0].claim["year_quote"] == "im Jahr 2022"
    assert list(rows[0].claim["year_window"])[0] == "frame"


def test_two_tuples_or_a_year_of_its_own_take_nothing_from_the_survey():
    grid = reading.grid_of(TABLE)
    rows, _, _ = reading.table_rows(
        {"value_columns": [2], "value_rows": [2]}, grid)
    assert reading.inherit(rows, FRAME, [TUPLE, dict(TUPLE, year=2040)],
                           [], [table()]) == 0
    rows[0].claim.update(year=2040, year_state="read")
    assert reading.inherit(rows, FRAME, [TUPLE], [TUPLE], [table()]) == 0
    assert rows[0].claim["year"] == 2040
    assert rows[0].claim.get("scenario_state") != "read"


# -- every coordinate answered -------------------------------------------------

def value_grammar(labels=None):
    return reading.text_response_format(
        EMISSION, list(SLOTS.values()), labels)["json_schema"]["schema"]


def table_grammar():
    return reading.table_response_format(
        list(SLOTS.values()))["json_schema"]["schema"]


def everything(**given):
    """Every coordinate of an emission value: not printed but for *given*."""
    out = {name: {"value": UNSTATED} for name in SLOTS}
    out.update(given)
    return out


UNIT = {"value": "t CO2", "quote": "rund 300 t CO2"}
VALUE = {"value": 300, "quote": "rund 300 t CO2"}


def test_the_grammar_wants_every_coordinate_of_a_value_in_text():
    whole = {"values": [dict(VALUE, **everything(unit=UNIT))]}
    jsonschema.validate(whole, value_grammar())
    without_year = {"values": [{k: v for k, v in whole["values"][0].items()
                                if k != "year"}]}
    try:
        jsonschema.validate(without_year, value_grammar())
    except jsonschema.ValidationError:
        return
    raise AssertionError("a value without its year passed the grammar")


def test_the_grammar_wants_every_coordinate_of_a_table_for_the_whole_table():
    whole = {"value_columns": [2], "value_rows": [2],
             "coordinates": {name: {"table": {"value": UNSTATED}}
                             for name in SLOTS}}
    jsonschema.validate(whole, table_grammar())
    for broken in ({name: entry for name, entry in
                    whole["coordinates"].items() if name != "carrier"},
                   dict(whole["coordinates"], carrier={"rows": []})):
        try:
            jsonschema.validate(dict(whole, coordinates=broken),
                                table_grammar())
        except jsonschema.ValidationError:
            continue
        raise AssertionError("a table without its carrier passed the "
                             "grammar")


def test_the_table_grammar_takes_the_parts_of_a_cell_and_wants_them_whole():
    whole = {"value_columns": [2], "value_rows": [1],
             "cells": [{"column": 2, "numbers": 2, "values": [1]}],
             "coordinates": {name: {"table": {"value": UNSTATED}}
                             for name in SLOTS}}
    whole["coordinates"]["unit"] = {"table": {"value": UNSTATED}, "columns": [
        {"column": 2, "part": 1, "value": UNSTATED}]}
    jsonschema.validate(whole, table_grammar())
    try:
        jsonschema.validate(dict(whole, cells=[{"column": 2, "values": [1]}]),
                            table_grammar())
    except jsonschema.ValidationError:
        return
    raise AssertionError("a cells entry without its count passed the grammar")


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

def read_text(*replies):
    """What reading TEXT came to, and what each request was asked with."""
    calls = []

    def ask_text(source, parameter, slots, context, corrections=None):
        calls.append(corrections)
        return replies[min(len(calls), len(replies)) - 1]

    reader = reading.Reader(SPEC, None, ask_text, FRAME)
    read = reader.read(7, EMISSION, TEXT, [], [], {("section", 6): TEXT})
    return read, calls


def read_table(*replies):
    calls = []

    def ask_table(source, grid, parameter, slots, context, corrections=None):
        calls.append(corrections)
        return replies[min(len(calls), len(replies)) - 1]

    reader = reading.Reader(SPEC, ask_table, None, FRAME)
    read = reader.read(7, EMISSION, table(), [], [], {("table", 5): table()})
    return read, calls


WRONG_CARRIER = {"value": "Erdgas", "quote": "Erdgas steht hier nicht"}
RIGHT_CARRIER = {"value": "Erdgas", "quote": "300 t CO2 bei Erdgas"}


def test_a_coordinate_the_check_refuses_is_asked_again_with_its_reason():
    read, calls = read_text(
        {"values": [dict(VALUE, **everything(unit=UNIT,
                                             carrier=WRONG_CARRIER))]},
        {"values": [dict(VALUE, row="R1",
                         **everything(unit=UNIT, carrier=RIGHT_CARRIER))]})
    assert calls[0] is None and len(calls) == 2
    assert calls[1] == [{"row": "R1", "value": 300, "quote": "rund 300 t CO2",
                         "what": {"carrier": say("quote_not_in_source")}}]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"
    assert read.asked == 2


def test_a_number_its_quote_does_not_print_is_asked_again_and_replaced():
    read, calls = read_text(
        {"values": [dict(VALUE, value=300000, **everything(unit=UNIT))]},
        {"values": [dict(VALUE, row="R1", **everything(unit=UNIT))]})
    assert set(calls[1][0]["what"]) == {"value"}
    assert read.claims[0]["value"] == 300


def test_a_table_coordinate_the_check_refuses_is_asked_again_for_its_row():
    def reply(carrier_quote):
        coordinates = {name: {"table": {"value": UNSTATED}} for name in SLOTS}
        coordinates["unit"] = {"table": {
            "value": "t CO2", "quote": "| | in t CO2 | in t CO2 | in t CO2 |"}}
        coordinates["carrier"] = {
            "rows": [{"row": 2, "value": "Erdgas", "quote": carrier_quote}],
            "table": {"value": UNSTATED}}
        return {"value_columns": [2], "value_rows": [2],
                "coordinates": coordinates}

    read, calls = read_table(reply("| Erdgas steht nicht |"),
                             reply("| Erdgas | 1.200 | 800 | 2.000 |"))
    assert calls[1] == [{"coordinate": "carrier", "row": 2,
                         "what": say("quote_not_in_source")}]
    assert read.claims[0]["carrier_state"] == "read"


def test_a_reply_wrong_twice_is_not_asked_a_third_time():
    wrong = dict(VALUE, **everything(unit=UNIT, carrier=WRONG_CARRIER))
    read, calls = read_text({"values": [wrong]},
                            {"values": [dict(wrong, row="R1")]})
    assert len(calls) == 2
    assert read.claims[0]["carrier_state"] == "unbacked"


def test_a_reply_the_check_takes_whole_is_asked_once():
    read, calls = read_text(
        {"values": [dict(VALUE, **everything(unit=UNIT,
                                             carrier=RIGHT_CARRIER))]})
    assert calls == [None] and read.asked == 1


def test_a_coordinate_read_the_first_time_stays_as_read():
    first = dict(VALUE, **everything(carrier=RIGHT_CARRIER))
    del first["unit"]
    read, calls = read_text(
        {"values": [first]},
        {"values": [dict(VALUE, row="R1",
                         **everything(unit=UNIT, carrier={"value": UNSTATED}))]})
    assert set(calls[1][0]["what"]) == {"unit"}
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"
    assert claim["unit_state"] == "read"


def test_a_coordinate_left_out_is_asked_for_by_name_and_ends_unanswered():
    entry = dict(VALUE, **everything(unit=UNIT))
    del entry["year"]
    read, calls = read_text({"values": [entry]},
                            {"values": [dict(entry, row="R1")]})
    assert calls[1][0]["what"] == {"year": say("key_missing", key="year")}
    assert read.claims[0]["year_state"] == "unanswered"
    assert read.unanswered == 1


def test_a_reader_reads_a_table_as_one_request_and_text_value_by_value():
    asked = []

    def ask_table(source, grid, parameter, slots, context, corrections=None):
        asked.append(("table", context["known"]))
        coordinates = {name: {"table": {"value": UNSTATED}} for name in SLOTS}
        coordinates["unit"] = {"table": {
            "value": "t CO2", "quote": "| | in t CO2 | in t CO2 | in t CO2 |"}}
        return {"value_columns": [2, 3], "value_rows": [2],
                "coordinates": coordinates}

    def ask_text(source, parameter, slots, context, corrections=None):
        asked.append(("text", context["known"]))
        return {"values": [dict(VALUE, **everything(unit=UNIT))]}

    class Found:
        answers = {}

        def passages_of(self, parameter):
            return [("table", 5), ("section", 6)] \
                if parameter == "emission" else []

        def tuples_at(self, owner, group):
            return [TUPLE] if owner == ("table", 5) else []

    reader = reading.Reader(SPEC, ask_table, ask_text, FRAME)
    reads = reader(7, Found(), {("table", 5): table(), ("section", 6): TEXT})
    assert [kind for kind, _ in asked] == ["table", "text"]
    assert asked[0][1] == [{"scenario": "Bestand", "year": 2022}]
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
    assert reading.years_of(BASES, list(SLOTS.values()))         == {"base_years": [2022], "target_years": [2045]}
    assert reading.years_of(BASES, [SLOTS["carrier"]]) == {}
    shown = []

    def ask_text(source, parameter, slots, context, corrections=None):
        shown.append(reading.text_payload(source, parameter, slots, context,
                                          corrections))
        return {"values": [dict(VALUE, **everything(unit=UNIT))]}

    reader = reading.Reader(SPEC, None, ask_text, FRAME,
                            bases=lambda pairs: BASES)
    reader.read(7, EMISSION, TEXT, [], [], {("section", 6): TEXT})
    assert shown[0]["base_years"] == [2022]
    assert shown[0]["target_years"] == [2045]
    grid = reading.grid_of(TABLE)
    assert reading.table_payload(table(), grid, EMISSION, list(SLOTS.values()),
                                 {"known": [], "base_years": [2022]})[
        "base_years"] == [2022]


def read_by_word(year):
    text = Source("section", 6, "Im Bestand fielen rund 300 t CO2 an.",
                  {"document_id": 7, "section_title": "Bilanz"})
    reply = {"values": [dict(VALUE, **everything(unit=UNIT, year={
        "value": year, "value_raw": "Bestand",
        "quote": "Im Bestand fielen rund 300 t CO2"}))]}
    reader = reading.Reader(SPEC, None, lambda *args, **kw: reply, FRAME,
                            bases=lambda pairs: BASES)
    return reader.read(7, EMISSION, text, [], [],
                       {("section", 6): text}).claims[0]


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

    def ask_table(source, grid, parameter, slots, context, corrections=None):
        shown.append(reading.table_payload(source, grid, parameter, slots,
                                           context, corrections))
        coordinates = {name: {"table": {"value": UNSTATED}} for name in SLOTS}
        coordinates["unit"] = {"table": {
            "value": "t CO2", "quote": "| | in t CO2 | in t CO2 | in t CO2 |"}}
        coordinates["year"] = {"table": {
            "value": 2022, "quote": "die Emissionen im Jahr 2022"}}
        return {"value_columns": [2], "value_rows": [2],
                "coordinates": coordinates}

    reader = reading.Reader(SPEC, ask_table, None, FRAME)
    read = reader.read(7, EMISSION, placed(), [], [],
                       {("table", 5): placed(), ("section", 9): SECTION},
                       budget=4000)
    assert "Die folgende Tabelle" in shown[0]["around"]
    claim = read.claims[0]
    assert claim["year"] == 2022 and claim["year_state"] == "read"
    assert claim["year_source"] == ["section", 9]
    alone = reader.read(7, EMISSION, placed(), [], [],
                        {("table", 5): placed()}, budget=4000)
    assert alone.claims[0]["year_state"] == "unbacked"


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


def gathering(*replies, passages=PLAN):
    """What reading BARE came to, and what each request showed."""
    shows = []

    def ask_text(source, parameter, slots, context, corrections=None):
        shows.append(context)
        return replies[min(len(shows), len(replies)) - 1]

    reader = reading.Reader(SPEC, None, ask_text, FRAME)
    read = reader.read(7, EMISSION, BARE, [], [], passages, budget=4000)
    return read, shows


def bare(more=None, **given):
    reply = {"values": [dict(VALUE, **everything(unit=BARE_UNIT, **given))]}
    if more:
        reply["more"] = more
    return reply


YEAR_AFTER = {"value": 2030, "quote": "gelten für das Jahr 2030"}


def test_the_next_section_asked_for_is_shown_and_its_quote_is_read():
    read, shows = gathering(bare([{"get": "next"}]), bare(year=YEAR_AFTER))
    assert "more" not in shows[0]
    assert [m["text"] for m in shows[1]["more"]] == [AFTER.text]
    claim = read.claims[0]
    assert claim["year"] == 2030 and claim["year_state"] == "read"
    assert claim["year_source"] == ["section", 8]
    assert read.asked == 2 and read.fetched == 1


def test_a_quote_from_a_section_never_shown_is_not_read():
    read, shows = gathering(bare(year=YEAR_AFTER))
    assert read.claims[0]["year_state"] == "unbacked"


def test_a_table_or_figure_named_by_its_placeholder_is_shown_and_none_else():
    _read, shows = gathering(
        bare([{"get": "item", "id": "[p3_img1: Abbildung 4]"},
              {"get": "item", "id": "p9_img9"}]), bare())
    assert [m["kind"] for m in shows[1]["more"]] == ["figure"]
    assert shows[1]["not_found"] == [{"get": "item", "id": "p9_img9",
                                      "why": reading.UNKNOWN}]


def test_a_search_lists_its_hits_and_a_hit_asked_for_is_shown():
    read, shows = gathering(
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
    read, shows = gathering(bare([{"get": "next"}]),
                            bare([{"get": "next"}, {"get": "next"}]))
    assert len(shows) == 2 and read.asked == 2
    read, shows = gathering(bare([{"get": "item", "id": "p9_img9"}]))
    assert len(shows) == 1
    again = bare([{"get": "item", "id": "p3_img1"}])
    read, shows = gathering(again, again, bare())
    assert len(shows) == 2 and len(shows[1]["more"]) == 1


def test_a_request_that_no_longer_fits_leaves_the_reply_before_it():
    read, shows = gathering(bare([{"get": "next"}]), reading.CUT)
    assert len(shows) == 2 and not read.unread
    assert [claim["value"] for claim in read.claims] == [300]
    assert read.claims[0]["unit_state"] == "read"
