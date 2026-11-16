"""
test_shapes_one_of.py: what the shapes demand of a node as a whole, and what
a drawing writes by itself, as the OEKG's shapes say them since a bundle
needs a name or an acronym and its scenarios may be IAM scenarios.

The promises, each with a case that breaks it by construction:

1. An sh:or on a node whose alternatives each name one property with
   sh:minCount is read as a group one of which is demanded, AND an sh:or of
   another form, an sh:and, sh:xone or sh:not on the node is noted as not
   read.
2. The graph's log names such a group as "a or b" where a node says none
   of its properties, AND names nothing where the node says one.
3. Holding the spec to the shapes, an entry of the shapes' list the drawing
   writes on every node by itself is not missing from the spec, AND an entry
   it does not write still is; the dry run of the OEKG's interface says the
   same.

Author: Felix Vossel
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

rdflib = pytest.importorskip("rdflib")

from docpipe import graphfile                                   # noqa: E402
from docpipe.compile import draft, shapes                        # noqa: E402
from docpipe.extraction import graph as program                  # noqa: E402
from docpipe.profile import load_profile                         # noqa: E402

OEO = "https://openenergyplatform.org/ontology/oeo/"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
ACRONYM = "http://purl.org/dc/terms/acronym"
HEAD = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dc: <http://purl.org/dc/terms/> .
@prefix oeo: <https://openenergyplatform.org/ontology/oeo/> .
@prefix ex: <http://example.org/> .
"""


def bundle(node: str) -> str:
    """A bundle's shape with a name and an acronym, at most one each, and
    *node* said of the node itself."""
    return HEAD + f"""ex:StudyShape a sh:NodeShape ;
  sh:targetClass oeo:OEO_00020227 ;
  sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                sh:maxCount 1 ] ;
  sh:property [ sh:path dc:acronym ; sh:datatype xsd:string ;
                sh:maxCount 1 ] ;
  sh:property [ sh:path oeo:OEO_00390079 ; sh:in ( oeo:OEO_1 ) ;
                sh:minCount 1 ] ;
  {node} .
"""


EITHER = ("sh:or ( [ sh:path rdfs:label ; sh:minCount 1 ] "
          "[ sh:path dc:acronym ; sh:minCount 1 ] )")


def read(text: str) -> list:
    graph = rdflib.Graph(bind_namespaces="none")
    graph.parse(data=text, format="turtle")
    return shapes.shapes_of(graph)


# 1 -----------------------------------------------------------------------

def test_an_or_of_properties_on_a_node_is_one_group_one_of_which_is_needed():
    (study,) = read(bundle(EITHER))
    assert study.one_of == [[ACRONYM, LABEL]]
    assert study.notes == []
    assert {prop.path: prop.min_count for prop in study.properties
            if prop.path in (LABEL, ACRONYM)} == {LABEL: None, ACRONYM: None}
    # the failure by construction: an alternative without a minimum, one
    # that says more than its property, and the other logical words
    for node in ("sh:or ( [ sh:path rdfs:label ] "
                 "[ sh:path dc:acronym ; sh:minCount 1 ] )",
                 "sh:or ( [ sh:path rdfs:label ; sh:minCount 1 ; "
                 "sh:datatype xsd:string ] "
                 "[ sh:path dc:acronym ; sh:minCount 1 ] )",
                 "sh:xone ( [ sh:path rdfs:label ; sh:minCount 1 ] "
                 "[ sh:path dc:acronym ; sh:minCount 1 ] )",
                 "sh:not [ sh:path rdfs:label ; sh:minCount 1 ]"):
        (study,) = read(bundle(node))
        assert study.one_of == [], node
        assert [note for note in study.notes if "not read" in note], node


# 2 -----------------------------------------------------------------------

def required_of(tmp_path, monkeypatch, text: str) -> dict:
    """`required_by_class` over a shapes file of *text*."""
    from docpipe.editor import sourcespage
    path = tmp_path / "shapes.ttl"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(sourcespage, "shape_files", lambda profile: [path])
    return program.required_by_class(None)


def lacking(required: dict, says: list) -> dict:
    """What the log names for one bundle node that says *says*."""
    node = SimpleNamespace()
    box = {"id": "bundle", "class": "oeo:OEO_00020227"}
    writer = SimpleNamespace(
        drawing=SimpleNamespace(boxes=[box], written=lambda box_id: True),
        required=required,
        _class_of=lambda doc, box, node: box["class"])
    doc = SimpleNamespace(nodes={"bundle": [node]})
    entries = {id(node): [SimpleNamespace(predicate=one) for one in says]}
    return program.Writer.lacking(writer, doc, entries)


def test_the_log_names_both_where_a_bundle_has_neither_name_nor_acronym(
        tmp_path, monkeypatch):
    required = required_of(tmp_path, monkeypatch, bundle(EITHER))
    assert required == {"OEO_00020227": {"OEO_00390079",
                                         ("acronym", "label")}}
    assert lacking(required, ["oeo:OEO_00390079"]) == {
        "bundle": ["acronym or label"]}
    assert lacking(required, []) == {
        "bundle": ["OEO_00390079", "acronym or label"]}
    # either of them is enough
    assert lacking(required, ["oeo:OEO_00390079", "rdfs:label"]) == {}
    assert lacking(required, ["oeo:OEO_00390079", "dc:acronym"]) == {}
    # the failure by construction: read without the group, nothing names
    # the bundle that has neither
    plain = required_of(tmp_path, monkeypatch, bundle("sh:deactivated false"))
    assert lacking(plain, ["oeo:OEO_00390079"]) == {}


# 3 -----------------------------------------------------------------------

SCENARIOS = load_profile("scenarios")
SPEC = json.loads(Path(SCENARIOS.component("extraction", "SPEC_PATH"))
                  .read_text(encoding="utf-8"))
GRAPH = graphfile.load(SCENARIOS)
IAM = "OEO_00020517"
STRAY = "OEO_99999999"


def offered() -> list:
    """The local names of the scenario types the spec offers."""
    from docpipe.extraction.spec import expanded
    field = next(one for one in expanded(SPEC)["parameters"]
                 if one["uri"] == "scenario_type")
    return [draft.local(key) for key in field["vocabulary"]
            if not str(key).startswith("out:")]


def factsheet(*extra: str) -> str:
    """The scenario factsheet's shape: the types the spec offers and
    *extra* in the list of its scenario types."""
    listed = " ".join(f"oeo:{one}" for one in offered() + list(extra))
    return HEAD + f"""ex:ScenarioShape a sh:NodeShape ;
  sh:targetClass oeo:OEO_00000365 ;
  sh:property [ sh:path oeo:OEO_00390073 ; sh:in ( {listed} ) ] .
"""


def missing(rules) -> list:
    rows = draft.differences(read(factsheet(IAM, STRAY)), SPEC,
                             drawing=GRAPH.map, rules=rules)
    return sorted(draft.local(entry) for row in rows
                  if row["kind"] == "list_missing"
                  and row["path"] == "OEO_00390073"
                  for entry in row["entries"])


def test_a_type_the_drawing_writes_itself_is_not_missing_from_the_spec():
    assert IAM in GRAPH.rules["scenario_types_always"]
    assert draft.written_itself(GRAPH.map, GRAPH.rules)[
        ("OEO_00000365", "OEO_00390073")] == {IAM}
    assert missing(GRAPH.rules) == [STRAY]
    # the failure by construction: without the rules that say what the
    # drawing writes, the IAM scenario is missing again
    assert missing(None) == [IAM, STRAY]


def test_the_dry_run_of_the_interface_does_not_miss_it_either():
    from profiles.scenarios import oekg_api
    graph = rdflib.Graph(bind_namespaces="none")
    graph.parse(data=factsheet(IAM, STRAY), format="turtle")
    lines = [line for line in oekg_api.list_problems(graph)
             if line.startswith("scenario_type:")]
    assert lines == [f"scenario_type: the shapes list {STRAY}, which the "
                     f"spec does not offer"]
