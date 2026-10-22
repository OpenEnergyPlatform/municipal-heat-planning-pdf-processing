"""A writer takes its paths, cardinalities and classes from the shapes it is
held to, follows a property the shapes renamed, and stops on one they
dropped; the gate shuts on a writer that does not build and on a kind of
violation the last graph did not have."""
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from docpipe.extraction import gate
from docpipe.extraction.shapemodel import Model, SchemaError
from profiles.scenarios import kg

OEO = "https://openenergyplatform.org/ontology/oeo/"
HEAD = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dc: <http://purl.org/dc/terms/> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix oeo: <https://openenergyplatform.org/ontology/oeo/> .
@prefix ex: <http://example.org/> .
"""


def shape(name: str, target: str, *properties: str) -> str:
    body = " ;\n".join(f"  sh:property [ {p} ]" for p in properties)
    return f"ex:{name} a sh:NodeShape ; sh:targetClass {target} ;\n{body} .\n"


VALUE = shape(
    "Value", "oeo:OEO_00050016",
    "sh:path oeo:OEO_00000523 ; sh:in ( oeo:OEO_00000292 oeo:OEO_00000211 )"
    " ; sh:maxCount 1",
    "sh:path oeo:OEO_00000505 ; sh:in ( oeo:OEO_00000214 ) ; sh:minCount 1",
    "sh:path oeo:OEO_00140178 ; sh:datatype xsd:float")


def test_a_slot_is_found_by_its_list_its_datatype_and_its_class():
    model = Model.parse(HEAD + VALUE + shape(
        "Part", "oeo:OEO_99", "sh:path oeo:OEO_00140002 ; "
        "sh:or ( [ sh:class oeo:OEO_00050016 ] )"))
    carrier = model.slot(OEO + "OEO_00050016",
                         members={OEO + "OEO_00000292", OEO + "OEO_00000132"})
    assert carrier.path == OEO + "OEO_00000523" and carrier.single
    assert model.slot(OEO + "OEO_00050016", members={OEO + "OEO_00000214"}
                      ).required
    assert model.slot(OEO + "OEO_00050016",
                      datatype="http://www.w3.org/2001/XMLSchema#float"
                      ).path == OEO + "OEO_00140178"
    assert model.slot(OEO + "OEO_99", to_class=OEO + "OEO_00050016"
                      ).path == OEO + "OEO_00140002"


def test_a_renamed_property_is_followed_by_its_list():
    renamed = VALUE.replace("oeo:OEO_00000523", "oeo:OEO_00370001")
    model = Model.parse(HEAD + renamed)
    assert model.slot(OEO + "OEO_00050016",
                      members={OEO + "OEO_00000292"}).path \
        == OEO + "OEO_00370001"


def test_no_answer_and_two_answers_are_errors_not_defaults():
    model = Model.parse(HEAD + VALUE)
    with pytest.raises(SchemaError):
        model.slot(OEO + "OEO_00050016", members={OEO + "OEO_00000132"})
    with pytest.raises(SchemaError):
        model.slot(OEO + "OEO_00050016", path=OEO + "OEO_00000523",
                   datatype="http://www.w3.org/2001/XMLSchema#float")
    twice = HEAD + shape(
        "Two", "oeo:OEO_1", "sh:path oeo:OEO_2 ; sh:datatype xsd:string",
        "sh:path oeo:OEO_3 ; sh:datatype xsd:string")
    with pytest.raises(SchemaError):
        Model.parse(twice).slot(OEO + "OEO_1",
                                datatype="http://www.w3.org/2001/XMLSchema"
                                         "#string")


def test_a_class_without_a_shape_is_held_to_the_nearest_one_above_it():
    above = {OEO + "OEO_00340066": [OEO + "OEO_00050016"]}
    model = Model.parse(HEAD + VALUE,
                        ancestors=lambda iri: above.get(iri, []))
    assert model.shaped(OEO + "OEO_00340066") == OEO + "OEO_00050016"
    assert model.shaped(OEO + "OEO_00010157") is None


# -- scenarios ----------------------------------------------------------------

STRING = "sh:datatype xsd:string"


def oekg(report_uuid=True, bundle_uuid=False, region="oeo:OEO_00020220"):
    """The OEKG shapes, cut to what the scenarios serializer writes."""
    uuid = f"sh:path oeo:OEO_00390095 ; {STRING} ; sh:minCount 1 ; " \
           f"sh:maxCount 1"
    report = [f"sh:path rdfs:label ; {STRING} ; sh:minCount 1 ; "
              f"sh:maxCount 1",
              "sh:path oeo:OEO_00000506 ; sh:class oeo:OEO_00000064 ; "
              "sh:minCount 1",
              "sh:path oeo:OEO_00390096 ; sh:datatype xsd:dateTime ; "
              "sh:minCount 1 ; sh:maxCount 1",
              f"sh:path oeo:OEO_00390098 ; {STRING} ; sh:maxCount 1"]
    bundle = [f"sh:path rdfs:label ; {STRING} ; sh:minCount 1 ; "
              f"sh:maxCount 1",
              f"sh:path dc:acronym ; {STRING} ; sh:minCount 1 ; "
              f"sh:maxCount 1",
              f"sh:path dc:abstract ; {STRING} ; sh:maxCount 1",
              "sh:path oeo:OEO_00000510 ; sh:class oeo:OEO_00030022",
              "sh:path oeo:OEO_00000509 ; sh:class oeo:OEO_00090001",
              "sh:path obo:BFO_0000051 ; sh:or ( [ sh:class oeo:OEO_00020012 ]"
              " [ sh:class oeo:OEO_00000365 ] )"] + [
              f"sh:path oeo:{p} ; sh:in ( oeo:OEO_1 ) ; sh:minCount 1"
              for p in ("OEO_00390071", "OEO_00390079", "OEO_00020439",
                        "OEO_00020438")]
    factsheet = [f"sh:path rdfs:label ; {STRING} ; sh:maxCount 1",
                 f"sh:path dc:acronym ; {STRING} ; sh:maxCount 1",
                 f"sh:path dc:abstract ; {STRING} ; sh:maxCount 1",
                 "sh:path oeo:OEO_00390073 ; sh:in ( oeo:OEO_00000364 )",
                 f"sh:path {region} ; sh:class oeo:OEO_00020032",
                 "sh:path oeo:OEO_00020440 ; sh:datatype xsd:dateTime", uuid]
    return Model.parse(HEAD
                       + shape("Report", "oeo:OEO_00020012",
                               *(report + [uuid] * report_uuid))
                       + shape("Bundle", "oeo:OEO_00020227",
                               *(bundle + [uuid] * bundle_uuid))
                       + shape("Scenario", "oeo:OEO_00000365", *factsheet))


def test_scenarios_reads_what_occurs_once_and_what_must_occur_off_the_shapes():
    bound = kg.bind(oekg())
    assert "publication_doi" in bound.single
    assert "publication_author" not in bound.single
    assert {"publication_title", "publication_author",
            "study_acronym"} <= set(bound.required)
    assert "publication_doi" not in bound.required
    assert bound.uuid_on == {"studyreport", "scenariofactsheet"}
    assert bound.author == "OEO_00000064"


def test_scenarios_stops_on_a_path_the_shapes_dropped():
    with pytest.raises(SchemaError):
        kg.bind(oekg(region="oeo:OEO_00010378"))


def test_the_scenarios_graph_parses_and_carries_the_shapes_paths():
    rows = [{"parameter": "publication_title", "value": "A Study",
             "quote": "A Study"},
            {"parameter": "publication_author", "value": "Ada Lovelace",
             "quote": "Ada Lovelace"},
            {"parameter": "scenario_label", "value": "NDC", "value_uri": "NDC",
             "value_raw": "NDC", "quote": "the NDC scenario"},
            {"parameter": "scenario_region", "value": "Germany",
             "value_uri": "https://openenergyplatform.org/ontology/oekg/"
                          "region/Germany",
             "scenario": "NDC", "scenario_raw": "NDC", "quote": "NDC Germany"}]
    serializer = kg.make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    uuid = URIRef(OEO + "OEO_00390095")
    region = URIRef(OEO + "OEO_00020220")
    bundle = next(graph.subjects(predicate=None,
                                 object=URIRef(OEO + "OEO_00020227")))
    assert (None, region, None) in graph
    assert not list(graph.objects(bundle, uuid))
    assert len(list(graph.subject_objects(uuid))) == 2


# -- the gate -----------------------------------------------------------------

def test_a_kind_of_violation_the_last_graph_lacked_is_new():
    before = {"kinds": {"MinCount p value": 4}}
    assert gate.new_kinds({"kinds": {"MinCount p value": 9}}, before) == []
    assert gate.new_kinds({"kinds": {"MinCount p value": 1,
                                     "Closed q value": 1}}, before) \
        == ["Closed q value"]


class _Profile:
    name = "stub"

    def component(self, module, attr):
        def broken(db):
            raise SchemaError("the shape of X has no property with path Y")
        return broken if (module, attr) == ("kg", "make_serializer") else None


def test_the_gate_shuts_on_a_serializer_that_does_not_build():
    reasons = gate.check(Path("h"), Path("db"), Path("out.ttl"),
                         profile=_Profile())
    assert reasons and "does not build" in reasons[0]
