"""A table is read as one unit and its numbers by their place: one row per
cell of a value row and a value column, the table row its quote, and a
number printed twice in a row in two columns; a coordinate is taken at its
row label before its column head before the whole table, and only through
the field check; a frame coordinate left open takes the survey's one tuple
of the passage, but not against a year the row read under its own head.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = {slot.name: slot for slot in reading.slots_of(SPEC, EMISSION)}

TABLE = ("Tabelle 3: Treibhausgasemissionen der Stadt im Jahr 2022\n"
         "| Bilanz | Haushalte | GHD | gesamt |\n"
         "| --- | --- | --- | --- |\n"
         "| | in t CO2 | in t CO2 | in t CO2 |\n"
         "| Erdgas | 1.200 | 800 | 2.000 |\n"
         "| Heizöl | 27 | 28 | 27 |")


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
        for window, field_reply in reading.table_replies(reply, SLOTS[name],
                                                         at):
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


def test_a_reader_reads_a_table_as_one_request_and_text_value_by_value():
    asked = []

    def ask_table(source, grid, parameter, slots, known):
        asked.append(("table", known))
        return {"value_columns": [2, 3], "value_rows": [2],
                "coordinates": {}}

    def ask_text(source, parameter, slots, known):
        asked.append(("text", known))
        return {"values": [{"value": 300, "quote": "rund 300 t CO2",
                            "unit": {"value": "t CO2",
                                     "quote": "rund 300 t CO2"}}]}

    text = Source("section", 6, "Im Jahr fielen rund 300 t CO2 an.",
                  {"document_id": 7, "section_title": "Bilanz"})

    class Found:
        answers = {}

        def passages_of(self, parameter):
            return [("table", 5), ("section", 6)] \
                if parameter == "emission" else []

        def tuples_at(self, owner, group):
            return [TUPLE] if owner == ("table", 5) else []

    reader = reading.Reader(SPEC, ask_table, ask_text, FRAME)
    reads = reader(7, Found(), {("table", 5): table(), ("section", 6): text})
    assert [kind for kind, _ in asked] == ["table", "text"]
    assert asked[0][1] == [{"scenario": "Bestand", "year": 2022}]
    values = {c["value"]: c for r in reads for c in r.claims}
    assert set(values) == {1200, 800, 300}
    assert values[300]["unit"] == "t CO2" and values[300]["unit_state"] \
        == "read"
    assert values[1200]["year"] == 2022
