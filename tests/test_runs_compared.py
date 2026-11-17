"""Disagreement across runs kept in the graph (owner decision 2026-11-17, from
the literature on run-to-run noise): `--also-harvest DIR` reads the rows of
further harvests and compares them with this run's numbers, without a model
request and without writing any of them.

Promises, each with a case that breaks it by construction:
- a number another harvest reads differently at the same node beyond the
  rounding rule makes the node contested in the full graph (marked, with the
  other run's number) and absent from the strict graph; a number that differs
  by rounding only, or the same number, is one node and not contested;
- the same number at the same place under another coordinate (another year)
  makes the node contested by coordinates, and the log counts the key "year";
- a row only the other harvest has adds no node and counts as without
  counterpart; no row of another run is ever written;
- the other harvest's rows are read from its directory and marked with its
  name in `run`;
- without the option the graph is today's: same nodes, same text, no log line.
"""
import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from docpipe import graphfile
from docpipe.extraction import acrossruns, readings
from docpipe.extraction import graph as program
from docpipe.extraction.bricks import Brick
from docpipe.profile import load_profile
from test_graph_readings_rules import demand

KWP = load_profile("kwp")
VALUE = "https://openenergyplatform.org/ontology/oeo/OEO_00050016"
MARK = "Contested across runs"
AT = Brick("at", "address", "", "", "",
           lambda call: call.row["at"]
           + (f"/{call.label}" if call.label else ""))


@pytest.fixture
def write(tmp_path):
    """(rows, others={run: rows}, strict=False) -> (value nodes, text)."""
    db = tmp_path / "plans.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE Documents (id INTEGER, filename TEXT, "
                       "published TEXT, municipality_ags TEXT)")
    connection.execute("INSERT INTO Documents VALUES "
                       "(1, 'doc.pdf', '2024-12-11', '05116000')")
    connection.commit()
    connection.close()
    graphfile.reset()

    def run(rows, others=None, strict=False):
        runs = {name: {"doc": [dict(row, run=name) for row in found]}
                for name, found in (others or {}).items()}
        serializer = program.make_serializer(
            KWP, db, strict=strict, other_runs=runs or None)
        text = serializer("doc", rows) or ""
        nodes = set(Graph().parse(data=text, format="turtle").subjects(
            RDF.type, URIRef(VALUE))) if text else set()
        serializer.writer.log_across_runs()
        return nodes, text
    return run


def other(value, owner=("section", 1), year=2020):
    return dict(demand(value, owner), year=year)


def counted(caplog):
    """The dict a graph log line gives for "across runs" or the total."""
    for record in caplog.records:
        text = record.getMessage()
        if text.startswith("graph: across"):
            return eval(text.split(": ", 2)[2])
    return None


def test_another_number_at_the_node_is_contested_in_full_and_out_of_strict(
        write, caplog):
    here = [demand(888668, ("section", 1))]
    there = {"run2": [demand(100, ("table", 2))]}
    caplog.set_level(logging.INFO)
    nodes, text = write(here, there)
    plain, _ = write(here)
    assert len(nodes) == len(plain) == 1          # the other row adds no node
    assert MARK in text and "run run2 reads 100 at this node" in text
    assert counted(caplog)["contested by number"] == 1
    # the failure by construction: the same graph without the option says
    # nothing of it
    assert MARK not in write(here)[1]


def numbers(here, there, *, strict=False, **rules):
    """[(value, marks)] of one place of the graph as the writer settles the
    numbers with the graph rules of kwp, against the rows of run2."""
    found = dict(graphfile.load(KWP).rules, **rules)
    writer = program.Writer(
        program.Drawing({"prefixes": {}, "boxes": [], "arrows": []}),
        spec=SimpleNamespace(), rules=found, bricks={"at": AT}, strict=strict,
        other_runs={"run2": {"d": [dict(row, run="run2") for row in there]}}
        if there is not None else None)
    doc = program.Document(writer, "d", here, None)
    doc.admitted["v"] = here
    got = writer._numbers(doc, {"id": "v", "of": "p", "address": {
        "brick": "at"}, "settle": {}})
    return [(node.rows[0]["value"], node.data["marks"]) for node in got]


def row(value, place=1):
    return {"parameter": "p", "value": value, "value_target": float(value),
            "at": "a", "quote": f"{value}", "tier": "text_located",
            "provenance": {"owner_kind": "section", "owner_id": place}}


def test_a_node_the_runs_contest_is_marked_in_full_and_left_out_of_strict():
    here, there = [row(100)], [row(300, 2)]
    (value, marks), = numbers(here, there)
    assert value == 100 and marks["conflict"] is True
    assert marks["across_runs"] == ["run run2 reads 300 at this node"]
    assert numbers(here, there, strict=True) == []
    # the rule that leaves contested numbers out of the full graph does so
    # for these too
    assert numbers(here, there, contested_in_full=False) == []
    # the failure by construction: no other run, or an agreeing one, leaves
    # the node as it was, in both graphs
    for agreeing in (None, [row(100, 2)]):
        assert numbers(here, agreeing) == [(100, {})]
        assert numbers(here, agreeing, strict=True) == [(100, {})]


def test_the_same_number_or_a_rounding_of_it_is_one_node_not_contested(
        write, caplog):
    here = [demand(888668, ("section", 1))]
    caplog.set_level(logging.INFO)
    for there in ([demand(888668, ("table", 2))],
                  [demand(888700, ("table", 2))]):
        caplog.clear()
        nodes, text = write(here, {"run2": there})
        assert len(nodes) == 1 and MARK not in text
        found = counted(caplog)
        assert found["nodes agreeing"] == 1
        assert not any(key.startswith("contested") for key in found)
    # the failure by construction: a number beyond the rounding rule
    assert MARK in write(here, {"run2": [demand(888668 * 2,
                                                ("table", 2))]})[1]


def test_the_same_number_at_the_same_place_under_another_year_is_contested(
        write, caplog):
    here = [demand(888668, ("section", 1))]
    caplog.set_level(logging.INFO)
    nodes, text = write(here, {"run2": [other(888668, year=2030)]})
    assert len(nodes) == 1                         # no node for 2030
    assert MARK in text and "another year" in text
    found = counted(caplog)
    assert found["contested by coordinates"] == 1
    assert found["contested by coordinates: year"] == 1
    # the failure by construction: the same row at another place is no
    # evidence about this one, so it contests nothing
    caplog.clear()
    _nodes, text = write(here, {"run2": [other(888668, ("table", 9), 2030)]})
    assert MARK not in text
    assert counted(caplog)["rows without counterpart"] == 1


def test_a_row_only_the_other_harvest_has_adds_nothing(write, caplog):
    here = [demand(888668, ("section", 1))]
    caplog.set_level(logging.INFO)
    nodes, text = write(here, {"run2": [other(5, ("table", 4), 2035)]})
    assert nodes == write(here)[0]
    assert "2035" not in text and MARK not in text
    assert counted(caplog) == {"rows without counterpart": 1,
                               "nodes without counterpart": 1}


def test_without_the_option_the_graph_is_todays(write, caplog):
    here = [demand(888668, ("section", 1)), demand(100, ("table", 2))]
    caplog.set_level(logging.INFO)
    nodes, text = write(here)
    again, empty = write(here, {})
    assert (nodes, text) == (again, empty)
    assert MARK not in text and counted(caplog) is None
    assert not any("across runs" in r.getMessage() for r in caplog.records)
    # the failure by construction: an option that names a run adds the log
    # line, and only that
    caplog.clear()
    assert write(here, {"run2": [demand(5, ("table", 3))]})[1] == text
    assert counted(caplog) is not None


def test_the_harvests_are_read_from_their_directories_and_marked(tmp_path):
    rows = [demand(7, ("section", 1))]
    for name in ("one", "two"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "doc.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n"
            + json.dumps({"kind": "summary"}) + "\n", encoding="utf-8")
    runs = acrossruns.read_runs([tmp_path / "one", tmp_path / "two",
                                 tmp_path / "one"])
    assert list(runs) == ["one", "two", "one#2"]
    assert all(row["run"] == name for name, found in runs.items()
               for row in found["doc"])
    assert len(runs["one"]["doc"]) == 1           # the summary is no row
    assert acrossruns.read_runs(None) == {}


def test_the_rounding_comparison_is_the_one_settle_makes():
    assert readings.rounds_together(98, 100, tolerance=0.05)
    assert not readings.rounds_together(98, 100, tolerance=0.01)
    # a drawn number gets the drawn tolerance
    assert readings.rounds_together(90, 100, tolerance=0.01,
                                    drawn_tolerance=0.2, drawn=True)
    assert not readings.rounds_together(90, 100, tolerance=0.01,
                                        drawn_tolerance=0.2, drawn=False)


def test_a_place_is_a_passage_and_a_line_where_the_row_has_one():
    a = dict(demand(1, ("table", 2)), at={"line": 3, "cell": 2})
    b = dict(a, at={"line": 4, "cell": 2}, quote="other words")
    assert acrossruns.place_key(a) != acrossruns.place_key(b)
    # without `at` the quote decides, and no passage is no place
    c, d = demand(1, ("table", 2)), dict(demand(1, ("table", 2)),
                                         quote="other words")
    assert acrossruns.place_key(c) != acrossruns.place_key(d)
    assert acrossruns.place_key({"quote": "x"}) is None
