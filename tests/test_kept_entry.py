"""A value is a value of its parameter only with the entry it must have
(owner decisions 2026-11-07: the kind of a year, the work of a publication's
value), each promise with a case that breaks it by construction.

1. The graph takes a value only with every such entry read as that entry: a
   value of another work, a year that is no scenario year and a year whose
   kind stayed open stay out of it.
2. A spec whose entry to keep is no entry of its list is refused.

That the reading asks nothing after a coordinate that reads a value as
another entry is the reading's own promise (`tests/test_addressed.py`).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import Graph, URIRef

from docpipe.extraction import fields, graph as program
from docpipe.extraction.bricks import Call
from docpipe.extraction.spec import SpecError, load as load_spec
from docpipe.profile import load_profile
from test_graph_from_shapes import OEO, empty_db

SPEC_PATH = (Path(__file__).resolve().parent.parent / "profiles"
             / "scenarios" / "extraction_spec.json")
SPEC = load_spec(json.loads(SPEC_PATH.read_text(encoding="utf-8")))
THIS = "work:this_publication"
SCENARIO_YEAR = OEO + "OEO_00020097"


def harvest(other_year_kind):
    own = {"work": THIS, "work_state": fields.READ}
    return [
        {"parameter": "publication_title", "value": "A Study",
         "quote": "A Study", **own},
        {"parameter": "publication_author", "value": "Ada Lovelace",
         "quote": "Ada Lovelace", **own},
        {"parameter": "publication_author", "value": "Bob Other",
         "quote": "Developed by: Bob Other", "work": "out:another_work",
         "work_state": fields.READ},
        {"parameter": "scenario_year", "value": "2030", "scenario": "CurPol",
         "scenario_raw": "CurPol", "quote": "CurPol reaches 2030.",
         "scenario_quote": "CurPol reaches 2030.",
         "year_kind": SCENARIO_YEAR, "year_kind_state": fields.READ},
        {"parameter": "scenario_year", "value": "2018", "scenario": "CurPol",
         "scenario_raw": "CurPol", "quote": "CurPol, published 2018.",
         "scenario_quote": "CurPol, published 2018.",
         "year_kind": other_year_kind, "year_kind_state": fields.READ},
        {"parameter": "scenario_year", "value": "2040", "scenario": "CurPol",
         "scenario_raw": "CurPol", "quote": "CurPol in 2040.",
         "scenario_quote": "CurPol in 2040.",
         "year_kind_state": fields.UNANSWERED},
    ]


def held_back(row):
    """Why the drawing's `kept_coordinates` brick refuses *row*, else None."""
    kept = program.registry(load_profile("scenarios"))["kept_coordinates"]
    return kept.run(Call(doc=SimpleNamespace(spec=SPEC), row=row))


def graph_of(rows):
    serializer = program.make_serializer(load_profile("scenarios"),
                                         empty_db())
    text = serializer("doc", rows)
    graph = Graph().parse(data=text, format="turtle")
    years = {str(o)[:4] for o in graph.objects(
        predicate=URIRef(OEO + "OEO_00020440"))}
    return text, years


def test_the_graph_takes_only_values_read_with_the_entry_they_must_have():
    rows = harvest("out:other_year")
    text, years = graph_of(rows)
    assert years == {"2030"}
    assert "Ada Lovelace" in text and "Bob Other" not in text
    assert held_back(rows[2]) == "work:out:another_work"
    assert held_back(rows[5]) == f"year_kind:{fields.UNANSWERED}"
    assert held_back(rows[1]) is None
    # The same harvest with 2018 read as a scenario year: it is taken.
    _text, years = graph_of(harvest(SCENARIO_YEAR))
    assert years == {"2030", "2018"}


def test_a_spec_whose_entry_to_keep_is_none_of_its_list_is_refused():
    raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    year = next(p for p in raw["parameters"] if p["uri"] == "scenario_year")
    year["axes"]["year_kind"]["keep"] = "out:no_such_entry"
    with pytest.raises(SpecError):
        load_spec(raw)
