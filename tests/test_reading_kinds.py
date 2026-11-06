"""Every parameter is read like text, a table too: its rounds name each value
with a quote, a name in a table as a number in a section, AND only a number
in a table writes the head of its column; a value quoted where no passage
shown prints it is asked again with the reason. A category parameter's
request shows its entries, without the answer that the passage does not say
it, AND its grammar takes for a value exactly one entry, or "" where the
model is unsure and writes the wording into value_raw, never a spelling of
an entry, another word or that answer; a text parameter is shown no list and
takes any wording.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import jsonschema
import pytest

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say


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
    """Each values request reading *parameter* in TABLE, as (whether its
    grammar asks a head, the corrections it carried), and what the reading
    came to: the n-th request answered by the n-th of *replies*, the last
    one again after that."""
    asked = []

    def ask_values(source, parameter, context, read, corrections=None):
        asked.append((reading.with_head_asked(parameter, source),
                      corrections))
        return replies[min(len(asked), len(replies)) - 1]

    read = reading.Reader(KWP, ask_values, lambda *a, **k: {}, FRAME).read(
        7, parameter, TABLE, [], [], {("table", 5): TABLE})
    return asked, read


def test_a_table_is_read_by_name_and_only_a_number_writes_its_head():
    asked, read = asked_for(EMISSION, {
        "value": 27, "quote": "| Heizöl | 27 |", "head": "t CO2"},
        {"value": None})
    assert [head for head, _ in asked] == [True, True]
    assert [c["value"] for c in read.claims] == [27]
    asked, read = asked_for(PLANNER, NAMED, {"value": None})
    assert [head for head, _ in asked] == [False, False]
    assert [c["value"] for c in read.claims] == [NAMED["value"]]


def test_a_wording_in_a_table_is_quoted_from_the_table_or_asked_again():
    asked, read = asked_for(PLANNER, NAMED, {"value": None})
    assert [corrections for _, corrections in asked] == [None, None]
    assert [claim["quote"] for claim in read.claims] == [NAMED["quote"]]
    asked, read = asked_for(PLANNER, ELSEWHERE, NAMED,
                            {"value": None})
    assert asked[1][1] == [dict(ELSEWHERE, what=say("quote_not_in_passage"))]
    assert [claim["quote"] for claim in read.claims] == [NAMED["quote"]]


PASSAGE = Source("section", 2, "Emissions follow the common reporting format.",
                 {"document_id": 7, "section_title": "Methods"})


def test_a_category_request_shows_its_entries_and_a_text_request_no_list():
    shown = reading.values_payload(PASSAGE, DIVISION, {}, [])["parameter"]
    assert set(shown["value_classes"]) == ENTRIES
    assert "value_classes" not in reading.values_payload(
        PASSAGE, TITLE, {}, [])["parameter"]


def grammar(parameter):
    return reading.values_response_format(parameter)["json_schema"][
        "schema"]


def one(value, **given):
    return {"value": value, "quote": PASSAGE.text, **given}


def test_a_category_value_is_one_entry_or_left_open_and_nothing_else():
    entry, spelling = next(labels for labels in DIVISION.vocabulary.values()
                           if len(labels) > 1)[:2]
    jsonschema.validate(one(entry, value_raw=spelling), grammar(DIVISION))
    jsonschema.validate(one("", value_raw=spelling), grammar(DIVISION))
    for wrong in (spelling, "Common Reporting Format", fields.UNSTATED):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(one(wrong), grammar(DIVISION))
    jsonschema.validate(one("Common Reporting Format"), grammar(TITLE))
