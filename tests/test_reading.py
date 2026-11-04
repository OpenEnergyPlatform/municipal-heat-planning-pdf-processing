"""A table is read as one unit and its numbers by their place: one row per
cell of a value row and a value column, the table row its quote, and a
number printed twice in a row in two columns; a coordinate is taken at its
row label before its column head before the whole table, and only through
the field check; a frame coordinate left open takes the survey's one tuple
of the passage, but not against a year the row read under its own head.

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
coordinate quoted from that text is read and cites the section.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from dataclasses import replace
from pathlib import Path

import jsonschema

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
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
