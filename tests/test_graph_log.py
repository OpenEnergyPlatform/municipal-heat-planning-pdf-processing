"""The line a document leaves in the log says what it lacks that the shapes
require AND what it left out.

1. A written node whose class the shapes give a required property it does
   not say is named in the line, per box; a node that says it is not.
2. An out: answer on a row no node of its own carries is counted by its
   answer in the line; the line keeps "left out {...}" last, one line per
   document (`scripts/harvest_compare.py` parses it).
3. A profile without shapes reports no missing ones.

Each with a document that breaks it by construction.
"""
import logging
from types import SimpleNamespace

from docpipe.extraction import graph as program
from docpipe.extraction.bricks import registry

PREFIXES = {"oeo": "http://x/oeo/", "ex": "http://x/ex/"}
DRAWING = {
    "prefixes": PREFIXES,
    "boxes": [{"id": "report", "count": "per_document",
               "class": "oeo:C1", "address": {"name": "r"}}],
    "arrows": [
        {"from": "title", "to": "report", "property": "ex:P_title"},
        {"from": "date", "to": "report", "property": "ex:P_date"}]}
SPEC = SimpleNamespace(by_uri={"title": 1, "date": 1})


def writer(required):
    return program.Writer(program.Drawing(DRAWING), spec=SPEC, rules={},
                          bricks=registry(), required=required)


def line_of(caplog, document, rows, required):
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=program.log.name):
        assert writer(required).write(document, rows) is not None
    lines = [one.getMessage() for one in caplog.records
             if one.getMessage().startswith(f"graph: {document}: ")]
    assert len(lines) == 1
    return lines[0]


def row(parameter, value, **more):
    return {"parameter": parameter, "value": value, **more}


NEEDED = {"C1": {"P_title", "P_date"}}


def test_a_node_without_a_required_property_is_named(caplog):
    said = line_of(caplog, "a", [row("title", "T")], NEEDED)
    assert "missing required {'report': ['P_date']}" in said
    assert "P_title" not in said


def test_a_node_with_every_required_property_is_not(caplog):
    said = line_of(caplog, "b", [row("title", "T"), row("date", "D")],
                   NEEDED)
    assert "missing required" not in said
    assert "wrote {'report': 1}" in said


def test_without_shapes_nothing_is_missing(caplog):
    said = line_of(caplog, "c", [row("title", "T")], {})
    assert "missing required" not in said


def test_an_out_answer_is_counted_and_left_out_stays_last(caplog):
    rows = [row("title", "T"), row("other", "x", value_uri="out:family")]
    said = line_of(caplog, "d", rows, NEEDED)
    assert "not in the graph by choice {'out:family': 1}" in said
    assert said.endswith("left out {}")
    clean = line_of(caplog, "e", [row("title", "T")], NEEDED)
    assert "by choice" not in clean
