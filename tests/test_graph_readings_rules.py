"""
Which reading the graph takes, and how it settles different numbers, are
rules of the graph file, read where the choice is made (owner decision
2026-11-11, readings.py).

The promises, each with a case that breaks it by construction:

1. `pick_one_order` says which checks choose between readings, in which
   order, AND the standard is the choice the graph always made.
2. `front_pages_rule` and `front_pages_extra` say which pages are front
   pages, AND `front_order` in which order the readings of a front field
   count.
3. `settle_order` says which decisions settle different numbers on one
   address and in which order, AND a decision left out is not made.
4. `corroborated_by_place` marks a number two passages print as confirmed,
   AND off it marks none.
5. The values reach the writer: the rule set in the graph file changes what
   a written graph holds, AND the standard gives today's graph.
"""
import json
from collections import Counter

import pytest

from docpipe import graphfile
import sqlite3

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from docpipe.extraction import graph as program
from docpipe.extraction import readings
from docpipe.profile import load_profile
from profiles.kwp import kg as kwp_kg
from test_graph_from_shapes import (PROSE, authors_of, serialized,
                                    written_by, PROFILE)  # noqa: F401

STANDARD_PICK = ["not_contained", "most_sources", "located", "longer"]
STANDARD_SETTLE = ["wording", "rounding", "trust", "contested"]


def read(value, rects=False):
    return {"value": value,
            "provenance": {"rects": [[0, 0, 1, 1]]} if rects else {}}


def number(value, *, subject="", place=None, flags=()):
    found = {"value": value, "value_target": float(value),
             "subject": subject, "quote": f"{value}", "tier": "text_located",
             "flags": list(flags)}
    if place:
        found["provenance"] = {"owner_kind": place[0], "owner_id": place[1]}
    return found


def settled(rows, *, order=STANDARD_SETTLE, keep_open=True,
            corroborate=True, wording=("subject",)):
    return readings.settle(
        "iri", rows, lambda row, label="": f"iri/{label or row['value']}",
        fold=lambda text: str(text).lower(), wording=wording,
        tolerance=0.02, order=order, corroborate=corroborate,
        keep_open=keep_open)


# -- 1: pick_one_order --

def test_a_reading_inside_another_never_wins_unless_the_rule_drops_the_check():
    rows = [read("Heat plan"), read("Heat plan"), read("Heat plan"),
            read("Heat plan of Kassel")]
    assert readings.pick_one(rows, STANDARD_PICK)[0] == "Heat plan of Kassel"
    # the failure by construction: without the check the running header,
    # read three times, outvotes the title
    assert readings.pick_one(rows, ["most_sources"])[0] == "Heat plan"


def test_the_checks_decide_in_the_order_the_rule_gives():
    rows = [read("aa"), read("aa"), read("bbbb")]
    assert readings.pick_one(rows, STANDARD_PICK) == ("aa", 1)
    assert readings.pick_one(rows, ["longer", "most_sources"]) == ("bbbb", 1)
    located = [read("one", rects=True), read("three")]
    assert readings.pick_one(located, STANDARD_PICK)[0] == "one"
    assert readings.pick_one(located, ["longer", "located"])[0] == "three"
    # no check left: the reading that came first
    assert readings.pick_one(rows, [])[0] == "aa"
    assert readings.pick_one([read("x"), read("yy"), read("yy")], [])[0] == "x"


# -- 2: the front pages --

def test_the_front_pages_follow_the_rules():
    titles = [{"provenance": {"page": 3}}]
    both = "first page and title page"
    assert readings.front_pages(titles, which=both, extra=0) == {1, 3}
    assert readings.front_pages(titles, which="first page", extra=0) == {1}
    assert readings.front_pages(titles, which="title page", extra=0) == {3}
    assert readings.front_pages([], which="title page", extra=0) == {1}
    # the failure by construction: the pages after each count with the
    # extra
    assert readings.front_pages(titles, which=both, extra=1) == {1, 2, 3, 4}


def test_the_readings_of_a_front_field_count_in_the_order_of_the_rule():
    on_front = {"value": "a", "provenance": {"page": 1}}
    elsewhere = {"value": "b", "provenance": {"page": 9}}
    looked = {"value": "c", "provenance": {"page": 9},
              "flags": ["catalogue"]}
    every = [elsewhere, on_front, looked]
    standard = ["front", "catalogue", "any"]
    assert readings.in_order(every, {1}, standard) == [on_front]
    assert readings.in_order(every, {1}, ["catalogue", "front"]) == [looked]
    assert readings.in_order([elsewhere], {1}, standard) == [elsewhere]
    assert readings.in_order([elsewhere], {1}, ["front"]) == []


# -- 3: settle_order --

def test_a_trust_difference_settles_unless_the_rule_leaves_trust_out():
    rows = [number(100), number(40, flags=["not_located"])]
    kept, lost, marks = settled(rows)
    assert [r["value"] for r in kept.values()] == [100]
    assert marks["iri"] == {"resolved": "trust"}
    # the failure by construction: without trust what is left is contested
    kept, lost, marks = settled(rows, order=["wording", "rounding",
                                             "contested"])
    assert sorted(r["value"] for r in kept.values()) == [40, 100]
    assert lost["conflict:open"] == 2 and not lost["conflict:trust"]


def test_contested_before_trust_keeps_both_numbers():
    rows = [number(100), number(40, flags=["not_located"])]
    kept, _lost, _marks = settled(rows, order=["contested", "trust"])
    assert len(kept) == 2
    # leaving them out where the graph keeps nothing open
    kept, lost, _marks = settled(rows, order=["contested", "trust"],
                                 keep_open=False)
    assert kept == {} and lost["conflict"] == 2


def test_a_rounded_number_loses_unless_the_rule_leaves_rounding_out():
    rows = [number(1000), number(1001)]
    kept, lost, marks = settled(rows)
    assert len(kept) == 1 and marks["iri"] == {"resolved": "rounding"}
    assert lost["conflict:rounding"] == 1
    kept, lost, marks = settled(rows, order=["wording", "trust",
                                             "contested"])
    assert len(kept) == 2 and lost["conflict:open"] == 2


def test_the_wording_splits_numbers_unless_the_rule_leaves_it_out():
    rows = [number(100, subject="Public"), number(40, subject="Private")]
    kept, lost, _marks = settled(rows)
    assert len(kept) == 2 and lost["split:wording"] == 1
    assert not lost["conflict:open"]
    kept, lost, _marks = settled(rows, order=["rounding", "trust",
                                              "contested"])
    assert lost["conflict:open"] == 2 and not lost["split:wording"]
    # wording after trust: the numbers stay apart only where trust does not
    # settle them
    graded = [number(100, subject="Public"),
              number(40, subject="Private", flags=["not_located"])]
    kept, _lost, _marks = settled(
        graded, order=["trust", "wording", "contested"])
    assert [r["value"] for r in kept.values()] == [100]
    kept, _lost, _marks = settled(graded)
    assert len(kept) == 2


def test_an_empty_order_settles_nothing():
    kept, lost, _marks = settled([number(100), number(40)], order=[],
                                 keep_open=True)
    assert kept == {} and lost == Counter({"conflict": 2})


# -- 4: corroborated_by_place --

def test_a_number_two_passages_print_is_confirmed_unless_the_rule_is_off():
    rows = [number(53, place=("table", 8)), number(53, place=("section", 7))]
    _kept, _lost, marks = settled(rows)
    assert marks["iri"]["corroborated"] is True
    # the failure by construction
    _kept, _lost, marks = settled(rows, corroborate=False)
    assert "iri" not in marks
    # one passage twice is no confirmation, with the rule on
    same = [number(53, place=("table", 8)), number(53, place=("table", 8))]
    assert "iri" not in settled(same)[2]


# -- 5: the values reach the writer --

def titled(*readings_):
    rows = []
    for value, page in readings_:
        rows.append({"parameter": "publication_title", "value": value,
                     "quote": value, "provenance": {"page": page}})
    return rows


def title_of(text):
    return "Net-zero EU" if '"Net-zero EU"' in text else (
        "Net-zero" if '"Net-zero"' in text else None)


@pytest.fixture
def graph_rules(tmp_path, monkeypatch):
    def lay(**values):
        file = tmp_path / "graph.json"
        file.write_text(json.dumps({"rules": values}), encoding="utf-8")
        monkeypatch.setenv(graphfile.ENV, str(file))
        graphfile.reset()
    yield lay
    monkeypatch.delenv(graphfile.ENV, raising=False)
    graphfile.reset()


def test_the_standard_values_stand_in_the_graph_files():
    graphfile.reset()
    for name in ("scenarios", "kwp"):
        got = graphfile.load(__import__("docpipe.profile", fromlist=["x"])
                             .load_profile(name)).rules
        assert got["pick_one_order"] == STANDARD_PICK
        assert got["settle_order"] == STANDARD_SETTLE
        assert got["corroborated_by_place"] is True
    assert got["settle_order"] == STANDARD_SETTLE


def test_the_title_rule_reaches_the_graph(graph_rules):
    rows = titled(("Net-zero", 1), ("Net-zero", 1), ("Net-zero EU", 1))
    graphfile.reset()
    assert title_of(serialized(rows)) == "Net-zero EU"
    graph_rules(pick_one_order=["most_sources"])
    assert title_of(serialized(rows)) == "Net-zero"


def test_the_front_rules_reach_the_graph(graph_rules):
    rows = written_by(("Ada Lovelace", 1), ("Grace Hopper", 12),
                      ("Alan Turing", 13))
    graphfile.reset()
    assert authors_of(serialized(rows)) == ["Ada Lovelace"]
    graph_rules(front_pages_extra=11)
    assert authors_of(serialized(rows)) == ["Ada Lovelace", "Grace Hopper"]
    graph_rules(front_order=["any"])
    assert authors_of(serialized(rows)) == [
        "Ada Lovelace", "Alan Turing", "Grace Hopper"]


# The settling rules reach the writer of the kwp graph, the one drawing with
# a box that settles numbers.
KWP = load_profile("kwp")
# the words of the value box for a confirmed number
KWP_CONFIRMED = kwp_kg.trust_prose()["corroborated"]
DEMAND = "Für das Jahr 2020 beträgt der Strombedarf 888.668 MWh."


def demand(value, owner):
    """A number of the plan with every coordinate read off *owner*."""
    row = {"kind": "tuple", "parameter": "energy_consumption",
           "quantity": "OEO_00050016", "value": value,
           "value_target": float(value), "unit": "MWh",
           "aggregation": "OEO_00140070", "carrier": "OEO_00000139",
           "scenario": "trend", "year": 2020,
           "spatial_scope": "municipality", "sector": None,
           "sector_state": "out_of_slice", "quote": DEMAND,
           "tier": "text_located", "flags": [],
           "provenance": {"owner_kind": owner[0], "owner_id": owner[1],
                          "page": 3}}
    for axis in ("unit", "parameter", "aggregation", "quantity", "carrier",
                 "scenario", "year", "spatial_scope"):
        row[f"{axis}_state"] = "read"
        row[f"{axis}_quote"] = DEMAND
    return row


@pytest.fixture
def kwp_graph(tmp_path):
    """(rows) -> the kwp graph of one plan and its trust lines, the plan
    known to a database that holds its date and its municipality."""
    db = tmp_path / "plans.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE Documents (id INTEGER, filename TEXT, "
                       "published TEXT, municipality_ags TEXT)")
    connection.execute("INSERT INTO Documents VALUES "
                       "(1, 'doc.pdf', '2024-12-11', '05116000')")
    connection.commit()
    connection.close()

    def write(rows):
        text = program.make_serializer(KWP, db)("doc", rows) or ""
        graph = Graph().parse(data=text, format="turtle")
        numbers = set(graph.subjects(RDF.type, URIRef(
            "https://openenergyplatform.org/ontology/oeo/OEO_00050016")))
        trusts = [line for line in text.splitlines()
                  if line.startswith("# Trust")]
        return numbers, trusts
    return write


def test_the_settle_order_reaches_the_graph(graph_rules, kwp_graph):
    rows = [demand(888668, ("section", 1)), demand(100, ("table", 2))]
    graphfile.reset()
    numbers, _trusts = kwp_graph(rows)
    assert len(numbers) == 2                    # both kept, contested
    graph_rules(settle_order=["contested"])
    assert len(kwp_graph(rows)[0]) == 2
    # the failure by construction: no decision, no number
    graph_rules(settle_order=[])
    assert kwp_graph(rows)[0] == set()


def test_the_confirmation_rule_reaches_both_graphs(graph_rules, kwp_graph):
    numbers = [demand(888668, ("section", 1)), demand(888668, ("table", 2))]
    names = written_by(("Ada Lovelace", 1), ("Ada Lovelace", 12))
    graphfile.reset()
    kept, trusts = kwp_graph(numbers)
    assert len(kept) == 1
    assert any(KWP_CONFIRMED in line for line in trusts)
    assert PROSE["corroborated"] in serialized(names)
    graph_rules(corroborated_by_place=False)
    kept, trusts = kwp_graph(numbers)
    assert len(kept) == 1
    assert not any(KWP_CONFIRMED in line for line in trusts)
    assert PROSE["corroborated"] not in serialized(names)
