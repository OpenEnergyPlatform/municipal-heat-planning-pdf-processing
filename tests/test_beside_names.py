"""The entries a coordinate of names takes beside them (spec `beside`, owner
decision 2026-11-07): the scenarios profile's "status quo" for a value of a
past or the current year, which belongs to no scenario, as KWP's closed list
has "Bestand", and its "several scenarios" for a value stated for several
scenarios that the text shown does not name one by one.

Promise: an axis of names may list out: entries beside its names AND only an
axis of names, AND only out: entries; a request shows them with their meaning
under the coordinate's kind, AND asks the wording beside the answer; an
answer that names the entry is read only where its wording, or else a
spelling, stands in its quote, AND it is kept as its out: key with that
wording; a name stays a name that its own quote must print, whatever wording
stands beside it; the naming takes no out: entry for a name; and the graph
hangs a row whose scenario is the entry on no scenario.

Each promise has a case that breaks it by construction beside the one that
keeps it.
"""
import copy
import json
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from docpipe.extraction import fields, naming, reading
from docpipe.extraction.pipeline import Row, Source, merge_field
from docpipe.extraction.spec import SpecError, load as load_spec
from docpipe.extraction.wording import say
from profiles.scenarios import kg
from test_graph_from_shapes import OEO, oekg

RAW = json.loads((Path(__file__).resolve().parent.parent / "profiles"
                  / "scenarios" / "extraction_spec.json")
                 .read_text(encoding="utf-8"))
SPEC = load_spec(copy.deepcopy(RAW))
YEAR = SPEC.by_uri["scenario_year"]
SLOT = next(slot for slot in fields.axis_slots(YEAR) if slot.name == "scenario")
STATUS_QUO = "out:status_quo"


def with_axis(**changed) -> dict:
    """The scenarios spec with the scenario axis of scenario_year changed."""
    raw = copy.deepcopy(RAW)
    axis = next(p for p in raw["parameters"]
                if p["uri"] == "scenario_year")["axes"]["scenario"]
    axis.update(changed)
    for key in [key for key, value in changed.items() if value is None]:
        axis.pop(key)
    return raw


def test_only_an_axis_of_names_takes_out_entries_beside_them():
    assert STATUS_QUO in YEAR.axes["scenario"].beside
    entry = {"label": "status quo", "definition": "Data of the past."}
    with pytest.raises(SpecError, match="axis of names"):
        load_spec(with_axis(merged=None, beside={"out:x": entry}))
    with pytest.raises(SpecError, match="out: entry"):
        load_spec(with_axis(beside={"status_quo": entry}))


def test_the_request_shows_the_entry_with_its_meaning_and_asks_its_wording():
    shown = reading.coordinate_shown(SLOT, unstated=False)
    assert shown["kind"] == fields.TEXT
    assert list(shown["options"]) == ["status quo", "several scenarios"]
    assert fields.UNSTATED not in shown["options"]
    schema = reading.answer_schema(SLOT, unstated=False)
    assert "value_raw" in schema["anyOf"][0]["properties"]
    # The failure by construction: an axis of names without entries shows
    # none and asks no wording.
    plain = next(slot for slot in fields.axis_slots(
        load_spec(with_axis(beside=None)).by_uri["scenario_year"])
        if slot.name == "scenario")
    assert "options" not in reading.coordinate_shown(plain)
    assert "value_raw" not in reading.answer_schema(plain)["anyOf"][0][
        "properties"]


PASSAGE = Source("section", 4, "Between 2005 and 2015, the annual reduction "
                 "of CO2 emissions in the EU28 was 1.7%. Historical data end "
                 "in 2015. The CurPol scenario reaches 2030.",
                 {"document_id": 7})


def merged(answer: dict) -> tuple:
    row = Row(label="R1", item_index=0, claim={"value": "2005"})
    got = merge_field([row], [PASSAGE], SLOT, {"answers": {"R1": answer}})
    return row.claim, got


def test_the_entry_is_read_where_its_wording_stands_in_its_quote():
    quote = "Between 2005 and 2015, the annual reduction of CO2 emissions"
    claim, got = merged({"value": "status quo",
                         "value_raw": "Between 2005 and 2015", "quote": quote})
    assert claim["scenario_state"] == fields.READ
    assert claim["scenario"] == STATUS_QUO
    assert claim["scenario_raw"] == "Between 2005 and 2015"
    # Without a wording a spelling of the entry stands in for it.
    claim, _ = merged({"value": "status quo",
                       "quote": "Historical data end in 2015."})
    assert claim["scenario_state"] == fields.READ
    # The failure by construction: a wording its quote does not print.
    claim, got = merged({"value": "status quo", "value_raw": "today",
                         "quote": quote})
    assert claim["scenario_state"] == fields.UNBACKED
    assert [f["why"] for f in got["failed"]] == ["answer_not_in_quote"]


def test_a_name_stays_a_name_its_own_quote_must_print():
    claim, _ = merged({"value": "CurPol", "value_raw": "the CurPol scenario",
                       "quote": "The CurPol scenario reaches 2030."})
    assert claim["scenario"] == "CurPol" and claim["scenario_raw"] == "CurPol"
    # The failure by construction: a wording beside a name vouches for
    # nothing but itself.
    claim, got = merged({"value": "NDC", "value_raw": "CurPol",
                         "quote": "The CurPol scenario reaches 2030."})
    assert claim["scenario_state"] == fields.UNBACKED
    assert got["failed"][0]["reason"].startswith(
        say("answer_not_in_quote_text", answer="NDC"))


def test_the_naming_takes_no_out_entry_for_a_name():
    rows = [{"parameter": "scenario_year", "value": "2005",
             "scenario": STATUS_QUO, "scenario_state": fields.READ,
             "scenario_quote": "Between 2005 and 2015",
             "scenario_source": ["section", 4]},
            {"parameter": "scenario_year", "value": "2030",
             "scenario": "CurPol", "scenario_state": fields.READ,
             "scenario_quote": "The CurPol scenario reaches 2030.",
             "scenario_source": ["section", 4]}]
    names = naming.names_of(rows, naming.merged_slots(SPEC))
    assert list(names["scenario"]) == ["CurPol"]


def test_the_graph_hangs_a_status_quo_row_on_no_scenario():
    rows = [{"parameter": "publication_title", "value": "A Study",
             "quote": "A Study"},
            {"parameter": "publication_author", "value": "Ada Lovelace",
             "quote": "Ada Lovelace"},
            {"parameter": "scenario_year", "value": "2005",
             "scenario": STATUS_QUO, "scenario_raw": "Between 2005 and 2015",
             "scenario_quote": "Between 2005 and 2015, the annual reduction",
             "quote": "Between 2005 and 2015, the annual reduction"},
            {"parameter": "scenario_year", "value": "2030",
             "scenario": "CurPol", "scenario_raw": "CurPol",
             "scenario_quote": "The CurPol scenario reaches 2030.",
             "quote": "The CurPol scenario reaches 2030."}]
    assert kg.scenario_names(rows[2]) == []
    assert kg.scenario_names(rows[3]) == ["CurPol"]
    # Also where no quote is kept to check a name against.
    bare = {"parameter": "scenario_year", "value": "2005",
            "scenario": STATUS_QUO}
    assert kg.scenario_names(bare) == []
    assert kg.scenario_names(dict(bare, scenario="CurPol")) == ["CurPol"]
    serializer = kg.make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    factsheets = set(graph.subjects(object=URIRef(OEO + "OEO_00000365")))
    years = {str(o)[:4] for o in graph.objects(
        predicate=URIRef(OEO + "OEO_00020440"))}
    assert len(factsheets) == 1 and years == {"2030"}
