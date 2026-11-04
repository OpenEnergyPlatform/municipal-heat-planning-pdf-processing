"""Numbers are read by their cell, everything else is named with a quote: a
table is read cell by cell for a parameter whose values are numbers, AND for
any other parameter the text request names its values, quoted from the
table and asked again where the table does not hold the quote. A category
parameter's request shows its entries, without the answer that the passage
does not say it, AND its grammar takes for a value exactly one entry, or ""
where the model is unsure and writes the wording into value_raw, never a
spelling of an entry, another word or that answer; a text parameter is shown
no list and takes any wording.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import jsonschema
import pytest

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Source, row_label
from docpipe.extraction.spec import load as load_spec


def spec_of(profile):
    return load_spec(json.loads(
        (Path(__file__).resolve().parent.parent / "profiles" / profile
         / "extraction_spec.json").read_text(encoding="utf-8")))


KWP = spec_of("kwp")
EMISSION = KWP.by_uri["emission"]
PLANNER = KWP.by_uri["planning_organisation"]
FRAME = [slot for group in KWP.groups_read_in("survey")
         for slot in fields.frame_slots(KWP, group.coordinates)]

SCENARIOS = spec_of("scenarios")
DIVISION = SCENARIOS.by_uri["study_sector_division"]
TITLE = SCENARIOS.by_uri["publication_title"]
ENTRIES = {labels[0] for labels in DIVISION.vocabulary.values()}

TABLE = Source("table", 5,
               "Tabelle 2: Emissionen 2022, erstellt von der Klimaschutzagentur"
               " Nord\n"
               "| Träger | t CO2 |\n"
               "| --- | --- |\n"
               "| Erdgas | 1.200 |\n"
               "| Heizöl | 27 |",
               {"document_id": 7, "page": 3, "section_title": "Bilanz"})
NAMED = {"value": "Klimaschutzagentur Nord",
         "quote": "erstellt von der Klimaschutzagentur Nord"}
ELSEWHERE = dict(NAMED, quote="Die Klimaschutzagentur Nord hat erstellt")


def asked_for(parameter, *replies):
    """Which request read *parameter* in TABLE, each text request with the
    corrections it carried, and what the reading came to."""
    asked = []

    def ask_table(source, grid, parameter, slots, context, corrections=None):
        asked.append(("table", corrections))
        return {"values": [],
                "coordinates": {slot.name: {"table": {"value": fields.UNSTATED}}
                                for slot in slots}}

    def ask_text(source, parameter, slots, context, corrections=None):
        asked.append(("text", corrections))
        return replies[min(len(asked), len(replies)) - 1]

    read = reading.Reader(KWP, ask_table, ask_text, FRAME).read(
        7, parameter, TABLE, [], [], {("table", 5): TABLE})
    return asked, read


def test_a_table_is_read_by_its_cells_for_numbers_and_by_name_otherwise():
    assert [kind for kind, _ in asked_for(EMISSION)[0]] == ["table"]
    assert [kind for kind, _ in asked_for(PLANNER, {"values": []})[0]] \
        == ["text"]


def test_a_wording_in_a_table_is_quoted_from_the_table_or_asked_again():
    asked, read = asked_for(PLANNER, {"values": [NAMED]})
    assert len(asked) == 1
    assert [claim["quote"] for claim in read.claims] == [NAMED["quote"]]
    asked, read = asked_for(PLANNER, {"values": [ELSEWHERE]},
                            {"values": [dict(NAMED, row=row_label(0))]})
    assert len(asked) == 2 and "value" in asked[1][1][0]["what"]
    assert [claim["quote"] for claim in read.claims] == [NAMED["quote"]]


PASSAGE = Source("section", 2, "Emissions follow the common reporting format.",
                 {"document_id": 7, "section_title": "Methods"})


def test_a_category_request_shows_its_entries_and_a_text_request_no_list():
    shown = reading.text_payload(PASSAGE, DIVISION, [], {})["parameter"]
    assert set(shown["value_classes"]) == ENTRIES
    assert "value_classes" not in reading.text_payload(
        PASSAGE, TITLE, [], {})["parameter"]


def grammar(parameter):
    return reading.text_response_format(parameter, [])["json_schema"][
        "schema"]


def one(value, **given):
    return {"values": [{"value": value, "quote": PASSAGE.text, **given}]}


def test_a_category_value_is_one_entry_or_left_open_and_nothing_else():
    entry, spelling = next(labels for labels in DIVISION.vocabulary.values()
                           if len(labels) > 1)[:2]
    jsonschema.validate(one(entry, value_raw=spelling), grammar(DIVISION))
    jsonschema.validate(one("", value_raw=spelling), grammar(DIVISION))
    for wrong in (spelling, "Common Reporting Format", fields.UNSTATED):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(one(wrong), grammar(DIVISION))
    jsonschema.validate(one("Common Reporting Format"), grammar(TITLE))
