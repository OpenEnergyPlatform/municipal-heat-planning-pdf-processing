"""A table is read as a table: the rows of its text, the cell of a number in
its row and the head of its column (what the review shows of a stored value),
and the harvest file's room for them. Each promise has a case that breaks it
by construction beside the one that keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from docpipe.extraction import fields, pipeline, runner, schema, stats
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
PARAMETER = SPEC.by_uri["energy_consumption"]
SLOTS = {slot.name: slot for slot in fields.axis_slots(PARAMETER)}
YEAR, SCENARIO, CARRIER = SLOTS["year"], SLOTS["scenario"], SLOTS["carrier"]

WOHNEN, GEWERBE = "| Wohnen | 120 | 80 |", "| Gewerbe | 40 | 80 |"
BOTH_ROWS = f"{WOHNEN}\n{GEWERBE}"


# -- a quote is one row ------------------------------------------------------


def test_the_rule_under_a_head_is_no_row():
    assert pipeline.printed_lines("| a | b |\n| --- | --- |\n| 1 | 2 |") == [
        "| a | b |", "| 1 | 2 |"]


def test_the_cell_of_a_number_is_counted_in_the_row_that_prints_it():
    assert pipeline.cell_index(BOTH_ROWS, 40) == (2, 3)


def test_a_number_on_two_rows_names_no_cell():
    assert pipeline.cell_index(BOTH_ROWS, 80) is None


# -- a number keeps the head of its column -----------------------------------


def test_the_harvest_file_may_carry_a_head():
    assert "head" in schema._tuple_schema(SPEC, PARAMETER)["properties"]


# -- a number printed twice takes its column from its place ------------------

YEARS = ("| Energieträger | 2022 | 2030 | 2045 |\n| --- | --- | --- | --- |\n"
         "| Abfall | 27% | 28% | 27% |\n")
ABFALL = "| Abfall | 27% | 28% | 27% |"


def test_a_field_request_shows_a_repeated_number_the_head_of_its_place():
    source = SimpleNamespace(owner_kind="table", owner_id=1, text=YEARS)
    assert runner.cell_facts(27, ABFALL, source, "2045") == {"head": "2045"}
    assert runner.cell_facts(27, ABFALL, source) == {}


# -- a head that prints a year of the plan is the year of its column ---------


def test_a_year_read_off_its_head_fits_the_harvest_file():
    window = schema._tuple_schema(SPEC, PARAMETER)["properties"]["year_window"]
    jsonschema.validate(["head", 3], window)


# -- what prints a frame -----------------------------------------------------


# -- the frame of a table is read once ---------------------------------------


def test_the_statistics_count_the_rows_that_took_their_table(tmp_path):
    trace = tmp_path / "plan.trace.jsonl"
    trace.write_text(json.dumps({"t": "sweep", "via_table": 2}) + "\n",
                     encoding="utf-8")
    assert stats.from_traces([tmp_path])[
        "coordinates_taken_from_their_table"] == 2
