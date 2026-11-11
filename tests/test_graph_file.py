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
7. (A value written under further predicates is no pass over the written
   graph any more: an arrow of the drawing writes each of them,
   test_sources_page.py.)
8. The provenance follows the graph: a node named anew is named anew there,
   AND a node left out takes every triple that names it out of it.
9. A setting of a graph rule wins over the file, as for every rule: the
   base its text, the evidence its flag; without them the file holds.
10. The OEKG body leaves out what the graph file leaves out: a class not
    written takes its items along, AND a value left out takes the item at
    fault, AND a bundle at fault is not sent, AND "stop" is said and leaves
    the body whole; a file that asks nothing leaves the body as it is.
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


# -- the provenance follows the graph ---------------------------------------

PROV = f"""@prefix prov: <http://www.w3.org/ns/prov#> .

<{EX}statement/1>
    prov:wasDerivedFrom <{EX}value/a> .

<{EX}statement/2>
    prov:wasDerivedFrom <{EX}org/x> .
"""


def test_the_provenance_follows_the_graph(written, tmp_path):
    pytest.importorskip("rdflib")
    prov = tmp_path / "graph.prov.ttl"
    prov.write_text(PROV, encoding="utf-8")
    kept = tmp_path / "other.prov.ttl"
    kept.write_text(PROV, encoding="utf-8")
    graphfile.finish(written, made(classes={
        "Org": {"written": False},
        "Value": {"address": {"folder": "number",
                              "key": ["ex:unit", "ex:number"]}}}), EX,
        follow=[prov])
    text = prov.read_text(encoding="utf-8")
    assert f"{EX}org/x" not in text and f"{EX}statement/2" not in text
    assert f"<{EX}value/a>" not in text and f"<{EX}number/" in text
    # the same new name in the graph and in its provenance
    graph_names = {str(s) for s in graph_of(written.read_text(
        encoding="utf-8")).subjects() if "/number/" in str(s)}
    prov_names = {str(o) for o in graph_of(text).objects()}
    assert prov_names <= graph_names
    # the failure by construction: a file not followed keeps the old names
    assert kept.read_text(encoding="utf-8") == PROV


# -- a setting of a graph rule wins over the file ------------------------------

def test_a_setting_of_a_graph_rule_wins_over_the_file(monkeypatch):
    profile = load_profile("scenarios")
    plain = graphfile.load(profile, environ={})
    said = graphfile.load(profile, environ={
        "OEKG_ID_BASE": "https://example.org/kg/", "OEKG_EVIDENCE": "1"})
    assert said.rules["base"] == "https://example.org/kg/"
    assert said.rules["evidence_as"] == "node"
    assert said.owners["rules/base"] == "environment"
    assert graphfile.load(profile, environ={"OEKG_EVIDENCE": "0"}) \
        .rules["evidence_as"] == "comment"
    # the failure by construction: without the settings the file holds
    assert plain.rules["base"] != "https://example.org/kg/"
    assert plain.rules["evidence_as"] == "comment"
    # and what the writers read follows the setting as it is now
    graphfile.reset()
    monkeypatch.setenv("OEKG_ID_BASE", "https://example.org/kg/")
    try:
        assert graphfile.get("base", "scenarios") == "https://example.org/kg/"
    finally:
        monkeypatch.delenv("OEKG_ID_BASE")
        graphfile.reset()
    assert graphfile.get("base", "scenarios") == plain.rules["base"]


# -- the OEKG body leaves out what the graph file leaves out ------------------

def test_the_oekg_body_leaves_out_what_the_graph_file_leaves_out():
    pytest.importorskip("pyshacl")
    from rdflib import Graph as RdfGraph
    from profiles.scenarios import kg, oekg_api
    shapes = RdfGraph().parse(data=f"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix oeo: <{kg.OEO_BASE}> .
@prefix dc: <http://purl.org/dc/terms/> .
oeo:ScenarioShape a sh:NodeShape ;
    sh:targetClass oeo:{kg.CLS_SCENARIO} ;
    sh:property [ sh:path dc:abstract ; sh:minCount 1 ] .
oeo:BundleShape a sh:NodeShape ;
    sh:targetClass oeo:{kg.CLS_BUNDLE} ;
    sh:property [ sh:path dc:abstract ; sh:minCount 1 ] .
""", format="turtle")
    payload = {"label": "Study", "acronym": "ST", "abstract": "What it is.",
               "study_reports": [{"label": "Paper", "authors": [
                   {"label": "A. Author"}, {"label": "B. Author"}]}],
               "scenarios": [{"label": "One", "acronym": "S1",
                              "abstract": "The first."},
                             {"label": "Two", "acronym": "S2"}]}
    at_fault = f"MinCount abstract {kg.CLS_SCENARIO}"
    body, done = oekg_api.graph_file_on(payload, made(classes={
        kg.CLS_AUTHOR: {"written": False}}), shapes, {})
    assert "authors" not in body["study_reports"][0]
    assert done["classes_left_out"] == {kg.CLS_AUTHOR: 2}
    body, done = oekg_api.graph_file_on(payload, made(constraints={
        at_fault: "leave_out_value"}), shapes, {})
    assert [one["acronym"] for one in body["scenarios"]] == ["S1"]
    assert body["study_reports"] == payload["study_reports"]
    without = {key: value for key, value in payload.items()
               if key != "abstract"}
    body, done = oekg_api.graph_file_on(without, made(constraints={
        f"MinCount abstract {kg.CLS_BUNDLE}": "leave_out_value"}), shapes, {})
    assert body is None
    body, done = oekg_api.graph_file_on(payload, made(constraints={
        at_fault: "stop"}), shapes, {})
    assert body == payload and done["stop"] == [{"constraint": at_fault}]
    # the failure by construction: a file that asks nothing leaves it whole
    body, done = oekg_api.graph_file_on(payload, made(), shapes, {})
    assert body == payload and not any(done.values())
