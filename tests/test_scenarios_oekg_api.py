"""The dry run of the OEKG scenario-bundle API.

The platform refuses a whole bundle for one missing value, mints every
identifier itself and takes no key it does not know. What is asserted here
is that a harvest turns into the body the platform documents, that the two
checks say what the platform would say, and that nothing is ever sent.

The schema and the shapes below are stand-ins written for these tests; the
real ones are pulled by `--refresh` and are not in the repository. The
shapes mirror the real file where the model can go wrong: the bundle, the
report and the factsheet are closed, a region and every node a reference
mints are held to exactly one label, and the scenario types are a list.
"""
import json
import logging
import sqlite3
from pathlib import Path

import pytest

from docpipe import upstream
from profiles.scenarios import kg, oekg_api

OEO = kg.OEO_BASE
OBO = "http://purl.obolibrary.org/obo/"
DC = "http://purl.org/dc/terms/"
REGION = "https://openenergyplatform.org/ontology/oekg/region/Germany"
POLICY = OEO + "OEO_00020247"
IAM = OEO + kg.IAM_SCENARIO
UNLISTED = OEO + "OEO_00099999"

REFERENCE = {"type": "object", "required": ["label"],
             "properties": {"iri": {"type": "string", "nullable": True},
                            "label": {"type": "string"}}}
OPENAPI = {"components": {"schemas": {
    "NodeReference": REFERENCE,
    "StudyReport": {"type": "object",
                    "required": ["authors", "label", "publication_date"],
                    "properties": {
                        "label": {"type": "string"},
                        "doi": {"type": "string", "nullable": True},
                        "publication_date": {"type": "string"},
                        "authors": {"type": "array", "items": {
                            "$ref": "#/components/schemas/NodeReference"}}}},
    "NestedScenario": {"type": "object", "required": ["acronym", "label"],
                       "properties": {
                           "label": {"type": "string"},
                           "acronym": {"type": "string"},
                           "abstract": {"type": "string", "nullable": True},
                           "scenario_types": {"type": "array",
                                              "items": {"type": "string"}},
                           "study_regions": {"type": "array", "items": {
                               "$ref": "#/components/schemas/NodeReference"}},
                           "years": {"type": "array",
                                     "items": {"type": "string"}}}},
    "ScenarioBundleCreate": {"type": "object", "required": ["acronym", "label"],
                             "properties": {
                                 "label": {"type": "string"},
                                 "acronym": {"type": "string"},
                                 "abstract": {"type": "string", "nullable": True},
                                 "organisations": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/NodeReference"}},
                                 "funders": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/NodeReference"}},
                                 "scenarios": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/NestedScenario"}},
                                 "study_reports": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/StudyReport"}}}},
}}}

SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
@prefix dc: <http://purl.org/dc/terms/> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix oeo: <https://openenergyplatform.org/ontology/oeo/> .

ex:StudyShape a sh:NodeShape ;
    sh:targetClass oeo:OEO_00020227 ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type ) ;
    sh:property [ sh:path oeo:OEO_00390071 ] ;
    sh:property [ sh:path obo:BFO_0000051 ;
                  sh:or ( [ sh:class oeo:OEO_00020012 ]
                          [ sh:class oeo:OEO_00000365 ] ) ] ;
    sh:property [ sh:path oeo:OEO_00000510 ; sh:class oeo:OEO_00030022 ] ;
    sh:property [ sh:path oeo:OEO_00000509 ; sh:class oeo:OEO_00090001 ] ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path dc:acronym ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path dc:abstract ; sh:datatype xsd:string ;
                  sh:maxCount 1 ] .

ex:PublicationShape a sh:NodeShape ;
    sh:targetClass oeo:OEO_00020012 ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type ) ;
    sh:property [ sh:path oeo:OEO_00390095 ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path oeo:OEO_00000506 ; sh:class oeo:OEO_00000064 ;
                  sh:minCount 1 ] ;
    sh:property [ sh:path oeo:OEO_00390096 ; sh:datatype xsd:dateTime ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path oeo:OEO_00390098 ; sh:datatype xsd:string ;
                  sh:maxCount 1 ] .

ex:ScenarioShape a sh:NodeShape ;
    sh:targetClass oeo:OEO_00000365 ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type ) ;
    sh:property [ sh:path dc:acronym ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path dc:abstract ; sh:datatype xsd:string ;
                  sh:maxCount 1 ] ;
    sh:property [ sh:path oeo:OEO_00390095 ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path oeo:OEO_00020440 ; sh:datatype xsd:dateTime ] ;
    sh:property [ sh:path oeo:OEO_00020220 ; sh:class oeo:OEO_00020032 ] ;
    sh:property [ sh:path oeo:OEO_00390073 ; sh:minCount 1 ;
                  sh:in ( oeo:OEO_00020247 ) ] .

ex:RegionShape a sh:NodeShape ;
    sh:targetObjectsOf oeo:OEO_00020220 ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type ) ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                  sh:minCount 1 ] .

ex:CommonShape a sh:NodeShape ;
    sh:targetObjectsOf oeo:OEO_00000506 ;
    sh:targetObjectsOf oeo:OEO_00000510 ;
    sh:targetObjectsOf oeo:OEO_00000509 ;
    sh:targetObjectsOf oeo:OEO_00390073 ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type rdfs:subClassOf ) ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] .
"""
# The bundle tag the real shapes demand and no body carries.
TAGGED = SHAPES + """
ex:TagShape a sh:NodeShape ;
    sh:targetClass oeo:OEO_00020227 ;
    sh:property [ sh:path oeo:OEO_00390071 ; sh:minCount 1 ] .
"""
# Shapes whose list takes the IAM annotation, so a body can be ready.
LENIENT = SHAPES.replace("sh:in ( oeo:OEO_00020247 )",
                         f"sh:in ( oeo:OEO_00020247 oeo:{kg.IAM_SCENARIO} )")

KNOWN = {REGION: "Germany", POLICY: "target driven scenario",
         OEO + "OEO_00390071": "has study descriptor tag",
         OEO + "OEO_00020227": "scenario bundle"}
# The two things every body is refused for under SHAPES: the IAM annotation
# is on no list, and the class behind it has no label over there.
IAM_ONLY = {("OEO_00000365", f"In on OEO_00390073: {kg.IAM_SCENARIO}"),
            (kg.IAM_SCENARIO, "MinCount on label")}


def _rows(scenarios=("CurPol",), kind=POLICY, **overrides):
    base = {
        "publication_title": ["Global Energy and Climate Outlook 2023"],
        "publication_author": ["Keramidas, K.", "Fosse, F."],
        "publication_date": ["2023"],
        "publication_doi": ["10.2760/58255"],
        "publication_abstract": ["This report presents the results."],
        "study_organisation": ["Joint Research Centre"],
        "study_funder": ["Horizon 2020"],
        "study_project_name": ["Enabling Ambitious Climate Policy Assessment"],
        "study_acronym": ["ENGAGE"],
    }
    base.update(overrides)
    rows = [{"parameter": k, "value": v, "quote": "x", "provenance": {},
             "tier": "text_located"}
            for k, values in base.items() for v in values]
    for name in scenarios:
        rows += [
            {"parameter": "scenario_label", "value": name,
             "quote": f"the {name} scenario", "provenance": {}},
            {"parameter": "scenario_type", "value": "a type",
             "value_uri": kind, "scenario": name,
             "quote": f"{name} is of a type", "provenance": {}},
            {"parameter": "scenario_region", "value": "Germany",
             "value_uri": REGION, "scenario": name,
             "quote": f"{name} covers Germany", "provenance": {}},
            {"parameter": "scenario_year", "value": "2050", "scenario": name,
             "quote": f"{name} results for 2050", "provenance": {}},
            {"parameter": "scenario_abstract",
             "value": "assumes no additional policies", "scenario": name,
             "quote": f"{name} assumes no additional policies",
             "provenance": {}},
        ]
    return rows


def _db(tmp_path, runs=()) -> Path:
    """A corpus database holding the AR6 runs of `geco_2023`."""
    db = tmp_path / "ar6.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE DocumentMeta (document INTEGER, title TEXT,"
        " year INTEGER, doi TEXT);"
        "CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,"
        " name TEXT);"
        "CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);"
        "INSERT INTO Documents VALUES (1, 'geco_2023.pdf');")
    for number, run in enumerate(runs, 1):
        conn.execute("INSERT INTO Scenarios VALUES (?, ?, ?)",
                     (number, number, run))
        conn.execute("INSERT INTO DocumentScenarios VALUES (1, ?)", (number,))
    conn.commit()
    conn.close()
    return db


def _study(rows=None, db=Path("no-such.db")):
    return kg.make_study_reader(db)("geco_2023", _rows() if rows is None else rows)


def _body(**overrides):
    return oekg_api.body(_study(_rows(**overrides)), KNOWN)


def _shapes(text=SHAPES):
    rdflib = pytest.importorskip("rdflib")
    return rdflib.Graph().parse(data=text, format="turtle")


def _refusals(payload, shapes=SHAPES) -> set:
    pytest.importorskip("pyshacl")
    return {(p["where"], p["what"]) for p in oekg_api.shape_problems(
        oekg_api.graph(payload, KNOWN), _shapes(shapes), KNOWN)}


def _harvest(tmp_path, documents: dict) -> Path:
    out = tmp_path / "harvest"
    out.mkdir()
    for name, rows in documents.items():
        (out / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(dict(row, kind="tuple")) for row in rows),
            encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# One reading, two writers
# ---------------------------------------------------------------------------

def test_the_study_says_what_the_turtle_says(tmp_path):
    """The body is built from the reading the Turtle is written from, so a
    value in one is the value in the other. With an AR6 list the factsheet's
    label and its acronym are two strings, and each must land on its own."""
    db = _db(tmp_path, runs=["CurPol"])
    rows = _rows(scenarios=["CURPOL"])
    ttl = kg.make_serializer(db)("geco_2023", rows)
    study = _study(rows, db)

    assert study["report"]["label"] == "Global Energy and Climate Outlook 2023"
    assert f'rdfs:label "{study["report"]["label"]}" ;' in ttl
    assert study["bundle"]["acronym"] == "ENGAGE"
    assert 'dc:acronym "ENGAGE" ;' in ttl
    assert study["bundle"]["abstract"] == "This report presents the results."
    assert 'dc:abstract "This report presents the results." ;' in ttl
    assert study["report"]["publication_date"] == "2023-01-01T00:00:00"
    assert '"2023-01-01T00:00:00"^^xsd:dateTime' in ttl
    assert study["report"]["doi"] == "10.2760/58255"
    assert study["report"]["authors"] == ["Keramidas, K.", "Fosse, F."]
    assert study["bundle"]["organisations"] == ["Joint Research Centre"]
    assert study["bundle"]["funders"] == ["Horizon 2020"]

    scenario, = study["scenarios"]
    assert scenario["label"] == "CurPol", "the AR6 spelling"
    assert scenario["acronym"] == "CURPOL", "the document's spelling"
    assert 'rdfs:label "CurPol" ;' in ttl and 'dc:acronym "CURPOL" ;' in ttl
    assert scenario["abstract"] == "assumes no additional policies"
    assert 'dc:abstract "assumes no additional policies" ;' in ttl
    assert scenario["types"] == [POLICY, IAM]
    assert f"<{POLICY}>" in ttl and f"oeo:{kg.IAM_SCENARIO}" in ttl
    assert scenario["regions"] == [REGION] and f"<{REGION}>" in ttl
    assert scenario["years"] == ["2050-01-01T00:00:00"]
    assert '"2050-01-01T00:00:00"^^xsd:dateTime' in ttl


def test_without_a_project_name_the_title_labels_the_bundle():
    study = _study(_rows(study_project_name=[]))
    assert study["bundle"]["label"] == "Global Energy and Climate Outlook 2023"
    assert oekg_api.body(study, KNOWN)["label"] == study["bundle"]["label"]


def test_a_document_without_a_title_has_no_study():
    assert _study(_rows(publication_title=[])) is None


def test_the_turtle_is_what_it_was_and_starts_with_its_header_once():
    """The split left the serializer's own promise alone: the header on the
    first document it writes, on no later one."""
    serializer = kg.make_serializer(Path("no-such.db"))
    first = serializer("geco_2023", _rows())
    second = serializer("another", _rows(publication_title=["Another Title"],
                                         study_project_name=[]))
    assert first.startswith(kg.PREFIXES)
    assert "@prefix" not in second


# ---------------------------------------------------------------------------
# The body
# ---------------------------------------------------------------------------

def test_the_body_carries_the_bundle_its_report_and_its_scenarios():
    payload = _body()
    assert payload == {
        "label": "Enabling Ambitious Climate Policy Assessment",
        "acronym": "ENGAGE",
        "abstract": "This report presents the results.",
        "organisations": [{"label": "Joint Research Centre"}],
        "funders": [{"label": "Horizon 2020"}],
        "study_reports": [{
            "label": "Global Energy and Climate Outlook 2023",
            "doi": "10.2760/58255",
            "publication_date": "2023-01-01T00:00:00",
            "authors": [{"label": "Keramidas, K."}, {"label": "Fosse, F."}]}],
        "scenarios": [{
            "label": "CurPol", "acronym": "CurPol",
            "abstract": "assumes no additional policies",
            "scenario_types": [POLICY, IAM],
            "study_regions": [{"iri": REGION, "label": "Germany"}],
            "years": ["2050-01-01T00:00:00"]}],
    }


def test_the_body_names_no_identifier_of_ours():
    """The server mints every identifier and refuses a `uid`. The IRIs the
    Turtle mints are ours and must not travel."""
    text = json.dumps(_body())
    assert "uid" not in text and "uuid" not in text
    assert kg.BASE + "publication/" not in text
    assert kg.BASE + "scenario/" not in text


def test_a_value_the_harvest_lacks_is_a_key_the_body_lacks():
    payload = _body(study_acronym=[], publication_author=[],
                    publication_date=[], study_funder=[],
                    publication_abstract=[])
    assert not {"acronym", "funders", "abstract"} & set(payload)
    report, = payload["study_reports"]
    assert "authors" not in report and "publication_date" not in report
    assert "null" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# The request schema
# ---------------------------------------------------------------------------

def test_a_complete_body_passes_the_schema():
    assert oekg_api.schema_problems(_body(), OPENAPI) == []


def test_the_schema_names_every_required_key_that_is_missing():
    problems = oekg_api.schema_problems(
        _body(study_acronym=[], publication_author=[], publication_date=[]),
        OPENAPI)
    found = {(p["where"], p["what"]) for p in problems}
    assert found == {
        ("body", "'acronym' is a required property"),
        ("study_reports[]", "'authors' is a required property"),
        ("study_reports[]", "'publication_date' is a required property")}
    assert all(p["check"] == "schema" for p in problems)


def test_a_key_the_api_does_not_know_is_reported():
    """The platform refuses an unknown key; the schema alone would let it
    pass. This is also how a renamed field upstream becomes visible."""
    payload = _body()
    payload["uid"] = "a5127883"
    payload["scenarios"][0]["regions"] = []
    payload["study_reports"][0]["authors"][0]["name"] = "x"
    found = {(p["where"], p["what"])
             for p in oekg_api.schema_problems(payload, OPENAPI)}
    assert found == {
        ("body", "'uid' is not a key of the API"),
        ("scenarios[]", "'regions' is not a key of the API"),
        ("study_reports[].authors[]", "'name' is not a key of the API")}


def test_a_null_the_api_allows_is_not_a_refusal():
    """OpenAPI 3.0 says `nullable: true`, which JSON Schema does not know.
    A null on such a key is accepted over there, a null elsewhere is not."""
    payload = _body()
    payload["abstract"] = None
    payload["study_reports"][0]["doi"] = None
    payload["scenarios"][0]["study_regions"][0]["iri"] = None
    assert oekg_api.schema_problems(payload, OPENAPI) == []

    payload["label"] = None
    payload["abstract"] = 5
    found = {(p["where"], p["what"])
             for p in oekg_api.schema_problems(payload, OPENAPI)}
    assert ("label", "None is not of type 'string'") in found
    assert [what for where, what in found if where == "abstract"]


# ---------------------------------------------------------------------------
# The model of the server and the shapes
# ---------------------------------------------------------------------------

def test_every_value_of_the_body_is_a_triple_the_shapes_name():
    """`graph()` promises the bundle as the platform would hold it. Each
    value is looked up under the path the shapes use for it, written out
    here from the shapes and not taken from the module."""
    pytest.importorskip("rdflib")
    from rdflib import RDF, RDFS, XSD, Literal, URIRef
    graph = oekg_api.graph(_body(), KNOWN)

    def oeo(local):
        return URIRef(OEO + local)

    def labelled(subject, predicate, cls):
        """{label} of the nodes `predicate` reaches, each of class `cls`."""
        targets = list(graph.objects(subject, predicate))
        assert all((t, RDF.type, oeo(cls)) in graph for t in targets)
        return {str(graph.value(t, RDFS.label)) for t in targets}

    bundle, = graph.subjects(RDF.type, oeo("OEO_00020227"))
    assert graph.value(bundle, RDFS.label) == Literal(
        "Enabling Ambitious Climate Policy Assessment")
    assert graph.value(bundle, URIRef(DC + "acronym")) == Literal("ENGAGE")
    assert graph.value(bundle, URIRef(DC + "abstract")) == Literal(
        "This report presents the results.")
    assert labelled(bundle, oeo("OEO_00000510"), "OEO_00030022") == {
        "Joint Research Centre"}
    assert labelled(bundle, oeo("OEO_00000509"), "OEO_00090001") == {
        "Horizon 2020"}
    assert not list(graph.objects(bundle, oeo("OEO_00390095"))), (
        "the closed bundle shape names no uuid")

    report, = graph.subjects(RDF.type, oeo("OEO_00020012"))
    scenario, = graph.subjects(RDF.type, oeo("OEO_00000365"))
    assert set(graph.objects(bundle, URIRef(OBO + "BFO_0000051"))) == {
        report, scenario}
    assert graph.value(report, RDFS.label) == Literal(
        "Global Energy and Climate Outlook 2023")
    assert graph.value(report, oeo("OEO_00390098")) == Literal("10.2760/58255")
    assert graph.value(report, oeo("OEO_00390096")) == Literal(
        "2023-01-01T00:00:00", datatype=XSD.dateTime)
    assert len(list(graph.objects(report, oeo("OEO_00390095")))) == 1
    assert labelled(report, oeo("OEO_00000506"), "OEO_00000064") == {
        "Keramidas, K.", "Fosse, F."}

    assert graph.value(scenario, RDFS.label) == Literal("CurPol")
    assert graph.value(scenario, URIRef(DC + "acronym")) == Literal("CurPol")
    assert graph.value(scenario, URIRef(DC + "abstract")) == Literal(
        "assumes no additional policies")
    assert len(list(graph.objects(scenario, oeo("OEO_00390095")))) == 1
    assert set(graph.objects(scenario, oeo("OEO_00390073"))) == {
        URIRef(POLICY), URIRef(IAM)}
    assert graph.value(URIRef(POLICY), RDFS.label) == Literal("target driven scenario")
    assert graph.value(URIRef(IAM), RDFS.label) is None, "not in the release"
    assert labelled(scenario, oeo("OEO_00020220"), "OEO_00020032") == {"Germany"}
    assert graph.value(scenario, oeo("OEO_00020440")) == Literal(
        "2050-01-01T00:00:00", datatype=XSD.dateTime)


def test_a_complete_body_is_refused_for_the_iam_annotation_and_nothing_else():
    """Closed shapes over every node the model writes. A triple too many, a
    label or a class too few, a missing uuid or a broken has-part link each
    add a refusal, and then this set is no longer the whole of it."""
    assert _refusals(_body()) == IAM_ONLY


def test_the_shapes_name_what_the_bundle_lacks():
    found = _refusals(_body(study_acronym=[], publication_date=[],
                            publication_author=[]), TAGGED)
    assert found - IAM_ONLY == {
        ("scenario bundle (OEO_00020227)", "MinCount on acronym"),
        ("scenario bundle (OEO_00020227)",
         "MinCount on has study descriptor tag (OEO_00390071)"),
        ("OEO_00020012", "MinCount on OEO_00390096"),
        ("OEO_00020012", "MinCount on OEO_00000506")}


def test_a_scenario_type_outside_the_list_is_named_with_its_entry():
    found = _refusals(_body(kind=UNLISTED))
    assert ("OEO_00000365", "In on OEO_00390073: OEO_00099999") in found
    assert ("OEO_00099999", "MinCount on label") in found, (
        "a node without a class is named itself")


def test_the_model_refuses_a_key_it_does_not_cover():
    """The API takes descriptors, sectors and more, which `body` never
    writes. A body that carried one would be judged as if it did not, so the
    model stops instead of answering."""
    pytest.importorskip("rdflib")
    for where, key in (("body", "descriptors"),
                       ("scenarios", "interacting_regions"),
                       ("study_reports", "reference")):
        payload = _body()
        target = payload if where == "body" else payload[where][0]
        target[key] = []
        with pytest.raises(ValueError, match=key):
            oekg_api.graph(payload, KNOWN)


# ---------------------------------------------------------------------------
# Findings about the harvest: the acronym, the shared bundle
# ---------------------------------------------------------------------------

def _entry(name, acronym, label=None):
    payload = {"label": label or name}
    if acronym:
        payload["acronym"] = acronym
    return {"document": name, "body": payload, "problems": []}


def test_an_acronym_two_documents_share_is_reported_on_both():
    entries = [_entry("a", "ENGAGE"), _entry("b", "engage "), _entry("c", "X"),
               _entry("d", None)]
    oekg_api.acronym_problems(entries)
    assert [len(e["problems"]) for e in entries] == [1, 1, 0, 0]
    assert entries[0]["problems"][0]["message"] == "b"


def test_an_acronym_the_platform_holds_is_reported():
    entries = [_entry("a", "IEA-WEO"), _entry("b", "NEW")]
    oekg_api.acronym_problems(entries, {"IEA-WEO": "World Energy Outlook"})
    assert entries[0]["problems"][0]["what"] == "acronym already on the platform"
    assert entries[1]["problems"] == []


def test_documents_that_make_one_bundle_are_reported_on_each():
    """The Turtle mints a bundle from its label, so these are one node
    there. As requests they would be two bundles of one study."""
    entries = [_entry("a", None, "CD-LINKS"), _entry("b", None, "cd-links"),
               _entry("c", None, "NAVIGATE")]
    oekg_api.shared_problems(entries)
    assert [len(e["problems"]) for e in entries] == [1, 1, 0]
    assert entries[1]["problems"][0] == {
        "check": "bundle", "where": "body",
        "what": "bundle label shared by more than one document of this harvest",
        "message": "a"}


def test_the_platform_list_is_read_page_by_page_and_only_read(monkeypatch):
    """`--live` is the one place the run talks to the platform. It follows
    `next` to the end, no call carries a body, and a bundle listed without
    an acronym is not an acronym."""
    pages = {
        oekg_api.LIST_URL + "?page_size=200": {
            "next": "https://example.org/page2",
            "results": [{"acronym": "IEA-WEO", "label": "World Energy Outlook"},
                        {"acronym": None, "label": "unnamed"},
                        {"label": "no key at all"}]},
        "https://example.org/page2": {
            "next": None, "results": [{"acronym": "NGFS", "label": "NGFS"},
                                      {"acronym": "", "label": "empty"}]},
    }
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return json.dumps(pages[url]).encode()

    monkeypatch.setattr(upstream, "_get", get)
    assert oekg_api.platform_acronyms() == {
        "IEA-WEO": "World Energy Outlook", "NGFS": "NGFS"}
    assert [url for url, _ in calls] == list(pages)
    assert all(not kwargs for _, kwargs in calls), "a GET: no data, no token"


def test_an_answer_that_is_not_the_list_is_an_upstream_error(monkeypatch):
    monkeypatch.setattr(upstream, "_get",
                        lambda url, **kwargs: b"<html>maintenance</html>")
    with pytest.raises(upstream.UpstreamError, match="not a bundle list"):
        oekg_api.platform_acronyms()


# ---------------------------------------------------------------------------
# The sources
# ---------------------------------------------------------------------------

def test_the_sources_name_the_commit_they_were_reviewed_at():
    """Both files decide what the platform accepts. Each names the commit it
    was read at, so every run can say whether upstream moved."""
    for source in oekg_api.SOURCES.values():
        assert source["kind"] == "repo_files"
        assert len(source["reviewed"]) == 40


def test_a_refresh_writes_its_own_lock_and_leaves_the_profiles_alone(
        tmp_path, monkeypatch):
    """A harvest run refreshes the profile's vocabulary under the profile's
    lock. This lock is another file, so neither refresh takes the other's
    sources away."""
    profile_lock = upstream.lock_path("scenarios", tmp_path)
    profile_lock.write_text('{"sources": {"oeo": {}}}', encoding="utf-8")
    shapes = tmp_path / "oekg_shapes.ttl"
    shapes.write_text(SHAPES, encoding="utf-8")

    def fetch(sources, cache):
        assert sources is oekg_api.SOURCES
        return {"oekg_shapes": {"kind": "repo_files", "version": "abc",
                                "files": [{"path": str(shapes)}]}}

    monkeypatch.setattr(upstream, "fetch", fetch)
    oekg_api.refresh(tmp_path)

    assert oekg_api.LOCK != "scenarios"
    assert upstream.lock_path(oekg_api.LOCK, tmp_path).is_file()
    assert profile_lock.read_text(encoding="utf-8") == '{"sources": {"oeo": {}}}'
    assert oekg_api._locked("oekg_shapes", tmp_path) == shapes
    assert oekg_api._locked("oep_api", tmp_path) is None, "not in this lock"
    shapes.unlink()
    assert oekg_api._locked("oekg_shapes", tmp_path) is None, "the file is gone"


def test_the_labels_come_from_the_checked_in_files_and_the_cached_closure(
        tmp_path):
    """Regions and the snapshot's terms without any refresh; the properties
    the shapes name only from the closure a vocabulary refresh left."""
    pytest.importorskip("rdflib")
    without = oekg_api.labels(tmp_path)
    assert without[REGION] == "Germany"
    assert without[POLICY] == "target driven scenario"
    assert OEO + "OEO_00390071" not in without

    closure = tmp_path / "oeo-closure.owl"
    closure.write_text(
        '<?xml version="1.0"?>\n'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
        '         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">\n'
        f' <rdf:Description rdf:about="{OEO}OEO_00390071">\n'
        '  <rdfs:label>has study descriptor tag</rdfs:label>\n'
        ' </rdf:Description>\n'
        f' <rdf:Description rdf:about="{POLICY}">\n'
        '  <rdfs:label>another spelling</rdfs:label>\n'
        ' </rdf:Description>\n'
        '</rdf:RDF>\n', encoding="utf-8")
    upstream.lock_path("scenarios", tmp_path).write_text(json.dumps(
        {"sources": {"oeo": {"files": [{"path": str(closure)}]}}}),
        encoding="utf-8")
    known = oekg_api.labels(tmp_path)
    assert known[OEO + "OEO_00390071"] == "has study descriptor tag"
    assert known[POLICY] == "target driven scenario", "the snapshot's label stands"


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

E2E_KNOWN = dict(KNOWN, **{IAM: "IAM scenario"})


def _run(tmp_path, monkeypatch, documents, *extra, shapes=LENIENT):
    pytest.importorskip("pyshacl")
    yaml = pytest.importorskip("yaml")
    monkeypatch.setattr(oekg_api, "labels", lambda: E2E_KNOWN)
    harvest = _harvest(tmp_path, documents)
    openapi = tmp_path / "openapi.yaml"
    openapi.write_text(yaml.safe_dump(OPENAPI), encoding="utf-8")
    shapes_path = tmp_path / "shapes.ttl"
    shapes_path.write_text(shapes, encoding="utf-8")
    written = tmp_path / "bodies.jsonl"
    code = oekg_api.main([str(harvest), str(_db(tmp_path)),
                          "--openapi", str(openapi), "--shapes", str(shapes_path),
                          "--write", str(written), *extra])
    entries = ([json.loads(line) for line in
                written.read_text(encoding="utf-8").splitlines()]
               if written.is_file() else None)
    return code, entries


DOCUMENTS = {
    "complete": _rows(),
    # Two scenarios that fail the same way: one finding about one paper.
    "no_acronym": _rows(scenarios=("A1", "B1"), kind=UNLISTED,
                        study_acronym=[], study_project_name=[],
                        publication_title=["Another Outlook"]),
    "untitled": _rows(publication_title=[]),
}


def test_the_run_reports_per_document_and_sends_nothing(tmp_path, monkeypatch,
                                                         capsys):
    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("the dry run opened a connection")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    code, entries = _run(tmp_path, monkeypatch, DOCUMENTS)
    out = capsys.readouterr().out
    assert code == 0
    assert "nothing was sent" in out
    assert "2 document(s) carry a study, 1 do not" in out
    assert "1 would be created as they are, 1 would be refused" in out
    assert "refused by the request schema (documents)" in out
    assert "     1  body: 'acronym' is a required property" in out
    assert "refused by the shapes (documents)" in out
    assert "     1  scenario bundle (OEO_00020227): MinCount on acronym" in out
    assert "     1  OEO_00000365: In on OEO_00390073: OEO_00099999" in out, (
        "two factsheets of one document are one document")
    assert "acronyms were not compared" in out
    assert "2 bundles" in out and "3 scenarios" in out and "4 authors" in out

    assert [e["document"] for e in entries] == ["complete", "no_acronym"]
    assert all(e["method"] == "POST" and e["path"] == oekg_api.PATH
               for e in entries)
    assert entries[0]["problems"] == [], "the complete one is ready"
    assert {p["check"] for p in entries[1]["problems"]} == {"schema", "shape"}
    assert len([p for p in entries[1]["problems"]
                if p["what"].startswith("In on")]) == 2, (
        "the file keeps every node; the report counts the document")


def test_live_compares_the_acronyms_and_says_how_many(tmp_path, monkeypatch,
                                                      capsys):
    monkeypatch.setattr(upstream, "_get", lambda url, **kwargs: json.dumps(
        {"next": None, "results": [{"acronym": "engage", "label": "ENGAGE"},
                                   {"acronym": "NGFS", "label": "NGFS"}]}).encode())
    code, entries = _run(tmp_path, monkeypatch, DOCUMENTS, "--live")
    out = capsys.readouterr().out
    assert code == 0
    assert "     1  body: acronym already on the platform" in out
    assert "compared with the 2 acronym(s) the platform lists" in out
    assert "0 would be created as they are, 2 would be refused" in out
    assert entries[0]["problems"][0]["message"] == "'engage': ENGAGE"


def test_two_documents_of_one_study_are_not_ready(tmp_path, monkeypatch, capsys):
    documents = {"paper_a": _rows(),
                 "paper_b": _rows(publication_title=["A Second Paper"],
                                  study_acronym=["OTHER"])}
    code, _entries = _run(tmp_path, monkeypatch, documents)
    out = capsys.readouterr().out
    assert code == 0
    assert "one study, several documents (documents)" in out
    assert "     2  body: bundle label shared by more than one document" in out
    assert "0 would be created as they are, 2 would be refused" in out


def test_the_run_leaves_the_readings_log_level_alone(tmp_path, monkeypatch,
                                                     capsys):
    """What the reading warns about decides the bodies, and other tests in
    this process read that logger."""
    logger = logging.getLogger(kg.__name__)
    # Set here, not read: an earlier run in this process would otherwise
    # have left the very level this test is looking for.
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    _run(tmp_path, monkeypatch, DOCUMENTS)
    capsys.readouterr()
    assert logger.level == logging.NOTSET


@pytest.mark.parametrize("case", ["no harvest directory", "empty harvest",
                                  "no database", "no openapi file",
                                  "no sources", "list is not a list"])
def test_a_run_that_cannot_be_made_exits_2_and_writes_nothing(
        case, tmp_path, monkeypatch, capsys):
    """Exit 0 is a report. A wrong path must not read as a harvest with
    nothing to refuse."""
    yaml = pytest.importorskip("yaml")
    pytest.importorskip("pyshacl")
    monkeypatch.setattr(oekg_api, "labels", lambda: KNOWN)
    harvest = _harvest(tmp_path, {} if case == "empty harvest"
                       else {"complete": _rows()})
    db = _db(tmp_path)
    openapi = tmp_path / "openapi.yaml"
    openapi.write_text(yaml.safe_dump(OPENAPI), encoding="utf-8")
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text(SHAPES, encoding="utf-8")
    written = tmp_path / "bodies.jsonl"
    argv = [str(harvest), str(db), "--openapi", str(openapi),
            "--shapes", str(shapes), "--write", str(written)]
    if case == "no harvest directory":
        argv[0] = str(tmp_path / "typo")
    elif case == "no database":
        argv[1] = str(tmp_path / "typo.db")
    elif case == "no openapi file":
        argv[3] = str(tmp_path / "typo.yaml")
    elif case == "no sources":
        argv = argv[:2] + argv[6:]
        monkeypatch.setattr(oekg_api, "_locked", lambda name: None)
    elif case == "list is not a list":
        argv.append("--live")
        monkeypatch.setattr(upstream, "_get", lambda url, **kwargs: b"<html>")

    assert oekg_api.main(argv) == 2
    out = capsys.readouterr().out
    assert "dry run" not in out, "no report"
    assert out.strip(), "and a line that says why"
    assert not written.exists()


def test_every_run_says_whether_upstream_moved(tmp_path, monkeypatch, capsys):
    """The shapes come from the branch head. A verdict against shapes that
    moved past the reviewed commit is a verdict about another validator."""
    pytest.importorskip("pyshacl")
    yaml = pytest.importorskip("yaml")
    monkeypatch.setattr(oekg_api, "labels", lambda: KNOWN)
    openapi = tmp_path / "openapi.yaml"
    openapi.write_text(yaml.safe_dump(OPENAPI), encoding="utf-8")
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text(SHAPES, encoding="utf-8")
    paths = {"oep_api": openapi, "oekg_shapes": shapes}
    monkeypatch.setattr(oekg_api, "_locked", lambda name: paths[name])
    monkeypatch.setattr(oekg_api, "_records", lambda: {
        "oekg_shapes": {"kind": "repo_files", "version": "abc",
                        "reviewed": "b" * 40,
                        "changed_since_reviewed": ["oekg/shapes/oekg_shapes.ttl"],
                        "compare": "https://example.org/compare"},
        "oep_api": {"kind": "repo_files", "version": "def",
                    "reviewed": "3" * 40, "changed_since_reviewed": []}})
    harvest = _harvest(tmp_path, {"complete": _rows()})
    assert oekg_api.main([str(harvest), str(_db(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "oekg_shapes: repo_files abc, 1 file(s) changed since reviewed" in out
    assert "oep_api: repo_files def, unchanged since reviewed 3333333" in out
