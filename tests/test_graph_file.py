"""
How a harvest becomes the graph stands in a file of the profile
(docpipe/graphfile.py; owner 2026-11-10: "sodass man steuern kann, wie die
Ernte in den Graphen aufgenommen wird und welche constraints erfüllt sein
müssen").

The promises, each with a case that breaks it by construction:

1. With the file as the profiles have it, the written graph is the
   writer's byte for byte, AND every rule a writer reads stands in it.
2. A class that is not written has no node, AND no triple names one, AND
   the writer's comments on the other nodes stay.
3. A changed address rule names the nodes of its class anew from the values
   it names, AND every triple follows, AND the count says how many.
4. "leave out" takes exactly the nodes with the violation out of the graph,
   AND a paper's leaving out takes every node of its document.
5. "stop" shuts the gate for a violation of its constraint.
6. A rule the file sets reaches the writer: the rounding a number's
   readings are one statement within is the file's.
"""
import json

import pytest

from docpipe import graphfile
from docpipe.profile import load_profile

EX = "https://example.org/id/"
TEXT = f"""@prefix ex: <https://example.org/o/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<{EX}plan/1>
    a ex:Plan ;
    rdfs:label "Plan one" ;
    ex:has <{EX}value/a> ,
        <{EX}value/b> ,
        <{EX}org/x> .

<{EX}value/a>
    a ex:Value ;
    # "1.200 MWh", p. 3
    ex:number 1200 ;
    ex:unit ex:MWh .

<{EX}value/b>
    a ex:Value ;
    # "800 MWh", p. 4
    ex:unit ex:MWh .

<{EX}org/x>
    a ex:Org ;
    rdfs:label "Stadtwerke" .
"""
SHAPES = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/o/> .

ex:ValueShape a sh:NodeShape ;
    sh:targetClass ex:Value ;
    sh:property [ sh:path ex:number ; sh:minCount 1 ] .
"""


def graph_of(text):
    from rdflib import Graph
    return Graph().parse(data=text, format="turtle")


def made(**said) -> graphfile.Graph:
    return graphfile.Graph(classes=said.get("classes", {}),
                           constraints=said.get("constraints", {}),
                           rules=said.get("rules", {}))


@pytest.fixture
def written(tmp_path):
    path = tmp_path / "graph.ttl"
    path.write_text(TEXT, encoding="utf-8")
    return path


def test_the_profiles_files_leave_the_graph_as_the_writer_wrote_it(
        written):
    for name in ("kwp", "scenarios"):
        profile = load_profile(name)
        file = graphfile.load(profile, environ={})
        assert not file.acts()
        assert set(graphfile.declared(profile)) <= set(file.rules)
    before = written.read_bytes()
    report = graphfile.finish(written, made(), EX)
    assert written.read_bytes() == before and report["readdressed"] == 0
    # the failure by construction: a file that names no rule its writer
    # reads is refused
    with pytest.raises(graphfile.GraphError, match="rounding_tolerance"):
        graphfile.parse(json.dumps({"rules": {"rounding_tolerance": "a"}}),
                        "x", graphfile.declared(load_profile("kwp")))


def test_a_class_not_written_has_no_node_and_no_triple_names_one(written):
    pytest.importorskip("rdflib")
    report = graphfile.finish(written, made(classes={
        "Org": {"written": False}}), EX)
    text = written.read_text(encoding="utf-8")
    assert report["classes_left_out"] == {"Org": 1}
    assert f"{EX}org/x" not in text
    assert '# "1.200 MWh", p. 3' in text
    graph = graph_of(text)
    assert len(graph) == len(graph_of(TEXT)) - 3
    # the failure by construction: the other classes keep every node
    assert {str(s) for s in graph.subjects()} == {
        f"{EX}plan/1", f"{EX}value/a", f"{EX}value/b"}


def test_an_address_rule_names_the_nodes_anew_and_counts_them(written):
    pytest.importorskip("rdflib")
    rule = {"folder": "number", "key": ["ex:unit"]}
    report = graphfile.finish(written, made(classes={
        "Value": {"address": rule}}), EX)
    text = written.read_text(encoding="utf-8")
    assert report["readdressed"] == 2
    assert f"<{EX}value/a>" not in text and f"{EX}number/" in text
    graph = graph_of(text)
    # both values print the same unit, so the rule makes them one node:
    # what a key that names too little does, seen before it is saved
    assert len({str(s) for s in graph.subjects() if "/number/" in str(s)}) \
        == 1
    # three triples were the same once both are one node: type, unit, has
    assert len(graph_of(TEXT)) == len(graph) + 3
    # the failure by construction: a rule over the number tells them apart
    written.write_text(TEXT, encoding="utf-8")
    graphfile.finish(written, made(classes={"Value": {"address": {
        "folder": "number", "key": ["ex:unit", "ex:number"]}}}), EX)
    assert len({str(s) for s in graph_of(written.read_text(
        encoding="utf-8")).subjects() if "/number/" in str(s)}) == 2


def test_leave_out_takes_exactly_the_nodes_with_the_violation(written,
                                                              tmp_path):
    pytest.importorskip("pyshacl")
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text(SHAPES, encoding="utf-8")
    key = "MinCount number Value"
    assert [one for one, _node in graphfile.violations(TEXT, [shapes])] \
        == [key]
    report = graphfile.finish(written, made(constraints={
        key: "leave_out_value"}), EX, [shapes])
    subjects = {str(s) for s in graph_of(written.read_text(
        encoding="utf-8")).subjects()}
    assert [one["node"] for one in report["left_out"]] == [f"{EX}value/b"]
    assert subjects == {f"{EX}plan/1", f"{EX}value/a", f"{EX}org/x"}
    # a paper's leaving out takes every node of its document
    written.write_text(TEXT, encoding="utf-8")
    index = {"one.pdf": [f"{EX}plan/1", f"{EX}value/a", f"{EX}value/b",
                         f"{EX}org/x"]}
    graphfile.finish(written, made(constraints={key: "leave_out_paper"}),
                     EX, [shapes], index=index)
    assert not graph_of(written.read_text(encoding="utf-8"))
    # the failure by construction: "report" leaves the graph as it is
    written.write_text(TEXT, encoding="utf-8")
    graphfile.finish(written, made(constraints={key: "report"}), EX,
                     [shapes])
    assert written.read_text(encoding="utf-8") == TEXT


def test_stop_shuts_the_gate_for_its_constraint(written, tmp_path,
                                                monkeypatch):
    pytest.importorskip("pyshacl")
    from docpipe.extraction import gate
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text(SHAPES, encoding="utf-8")
    profile = load_profile("kwp")
    monkeypatch.setattr(gate, "_stopping", gate._stopping)
    monkeypatch.setattr(graphfile, "load", lambda *a, **k: made(
        constraints={"MinCount number Value": "stop"}))
    monkeypatch.setattr("docpipe.extraction.serialize.profile_context",
                        lambda profile: [])
    said = gate._stopping(written, profile, [shapes])
    assert said == ["the graph file stops a job for MinCount number Value: "
                    "1 node(s)"]
    # the failure by construction: without "stop" the gate stays open
    monkeypatch.setattr(graphfile, "load", lambda *a, **k: made())
    assert gate._stopping(written, profile, [shapes]) == []


def test_a_rule_the_file_sets_reaches_the_writer(tmp_path, monkeypatch):
    from profiles.kwp import compute
    file = tmp_path / "graph.json"
    data = {"rules": {"rounding_tolerance": 0.0}}
    file.write_text(json.dumps(data), encoding="utf-8")
    rounded = ({"value_target": 1_626_000.0}, {"value_target": 1_600_000.0})
    graphfile.reset()
    assert graphfile.get("rounding_tolerance", "kwp") == 0.02
    assert compute.same_number(*rounded)
    monkeypatch.setenv(graphfile.ENV, str(file))
    try:
        assert graphfile.get("rounding_tolerance", "kwp") == 0.0
        assert graphfile.load(load_profile("kwp")).owners[
            "rules/rounding_tolerance"] == graphfile.ENV
        # the failure by construction: at 0 a rounded number is another
        assert not compute.same_number(*rounded)
    finally:
        monkeypatch.delenv(graphfile.ENV)
        graphfile.reset()
