"""The dry run of the OEKG scenario-bundle API.

The platform refuses a whole bundle for one missing value, mints every
identifier itself and takes no key it does not know. What is asserted here
is that a harvest turns into the body the platform documents, that the two
checks say what the platform would say, and that nothing is ever sent.

The schema and the shapes below are stand-ins written for these tests; the
real ones are pulled by `--refresh` and are not in the repository. The
shapes mirror the real file where the model can go wrong: the bundle, the
report and the factsheet are closed, a region and every node a reference
mints or a list names are held to exactly one label, and the tags and the
scenario types are lists. Those lists are the spec's own, so the spec and
the stand-in agree until a test makes them differ.
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
POLICY = OEO + "OEO_00020247"        # target driven scenario
IAM = OEO + kg.IAM_SCENARIO
UNLISTED = OEO + "OEO_00099999"
PATHWAY = OEO + "OEO_00010212"       # decarbonisation pathway
DIVISION = OEO + "OEO_00000242"      # CRF sectors (IPCC 2006)
TRANSPORT = OEO + "OEO_00000422"     # transport sector
INDUSTRY = OEO + "OEO_00000227"      # industry sector
PHOTOVOLTAIC = OEO + "OEO_00010428"  # photovoltaic technology
TAGS = {"study_descriptor": PATHWAY, "study_sector_division": DIVISION,
        "study_sector": TRANSPORT, "study_technology": PHOTOVOLTAIC}

REFERENCE = {"type": "object", "required": ["label"],
             "properties": {"iri": {"type": "string", "nullable": True},
                            "label": {"type": "string"}}}
IRIS = {"type": "array", "items": {"type": "string"}}
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
                           "scenario_types": IRIS,
                           "study_regions": {"type": "array", "items": {
                               "$ref": "#/components/schemas/NodeReference"}},
                           "years": {"type": "array",
                                     "items": {"type": "string"}}}},
    "ScenarioBundleCreate": {"type": "object", "required": ["acronym", "label"],
                             "properties": {
                                 "label": {"type": "string"},
                                 "acronym": {"type": "string"},
                                 "abstract": {"type": "string", "nullable": True},
                                 "descriptors": IRIS, "sector_divisions": IRIS,
                                 "sectors": IRIS, "technologies": IRIS,
                                 "energy_carriers": IRIS,
                                 "organisations": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/NodeReference"}},
                                 "funders": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/NodeReference"}},
                                 "scenarios": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/NestedScenario"}},
                                 "study_reports": {"type": "array", "items": {
                                     "$ref": "#/components/schemas/StudyReport"}}}},
}}}


def _listed(uri: str) -> list:
    """The entries the spec offers for one parameter that are real classes."""
    parameter, = [p for p in kg._SPEC["parameters"] if p["uri"] == uri]
    return [iri for iri in parameter["vocabulary"] if kg.in_graph(iri)]


def _shapes_text(lists=None) -> str:
    lists = lists or {uri: _listed(uri)
                      for uri in ("scenario_type",) + kg.BUNDLE_TAGS}

    def allowed(uri):
        return " ".join(f"<{iri}>" for iri in lists[uri])

    return f"""
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
    sh:property [ sh:path oeo:OEO_00390071 ; sh:minCount 1 ;
                  sh:in ( {allowed("study_descriptor")} ) ] ;
    sh:property [ sh:path oeo:OEO_00390079 ; sh:minCount 1 ;
                  sh:in ( {allowed("study_sector_division")} ) ] ;
    sh:property [ sh:path oeo:OEO_00020439 ; sh:minCount 1 ;
                  sh:in ( {allowed("study_sector")} ) ] ;
    sh:property [ sh:path oeo:OEO_00020438 ; sh:minCount 1 ;
                  sh:in ( {allowed("study_technology")} ) ] ;
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
                  sh:in ( {allowed("scenario_type")} ) ] .

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
    sh:targetObjectsOf oeo:OEO_00390071 ;
    sh:targetObjectsOf oeo:OEO_00390079 ;
    sh:targetObjectsOf oeo:OEO_00020439 ;
    sh:targetObjectsOf oeo:OEO_00020438 ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type rdfs:subClassOf ) ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ] .
"""


SHAPES = _shapes_text()

KNOWN = {REGION: "Germany", POLICY: "target driven scenario",
         PATHWAY: "decarbonisation pathway",
         DIVISION: "CRF sectors (IPCC 2006)", TRANSPORT: "transport sector",
         PHOTOVOLTAIC: "photovoltaic technology",
         OEO + "OEO_00390071": "has study descriptor tag",
         OEO + "OEO_00020227": "scenario bundle"}


def _rows(scenarios=("CurPol",), kind=POLICY, tags=TAGS, **overrides):
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
    rows += [{"parameter": key, "value": "an entry", "value_uri": iri,
              "quote": "the study covers an entry", "provenance": {}}
             for key, iri in (tags or {}).items()]
    for name in scenarios:
        rows += [
            {"parameter": "scenario_label", "value": name,
             "quote": f"the {name} scenario", "provenance": {}},
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
        if kind:
            rows.append({"parameter": "scenario_type", "value": "a type",
                         "value_uri": kind, "scenario": name,
                         "quote": f"{name} is of a type", "provenance": {}})
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


def _study(rows=None, db=Path("no-such.db"), name="geco_2023"):
    return kg.make_study_reader(db)(name, _rows() if rows is None else rows)


def _bundles(documents: dict) -> list:
    """The harvest of these documents, merged and named as a run does it."""
    bundles = oekg_api.merge([_study(rows, name=name)
                              for name, rows in documents.items()])
    oekg_api.form_acronyms(bundles)
    return bundles


def _body(**overrides):
    bundle, = _bundles({"geco_2023": _rows(**overrides)})
    return oekg_api.body(bundle, KNOWN)


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
    assert study["bundle"]["tags"] == {key: [iri] for key, iri in TAGS.items()}
    for key, iri in TAGS.items():
        assert f"{kg._property(key)} <{iri}> ;" in ttl

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
    assert _body(study_project_name=[])["label"] == study["bundle"]["label"]


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


def test_the_api_names_every_tag_the_turtle_writes():
    """A fifth tag in the spec that the body has no key for would be
    harvested, written to the Turtle and never sent."""
    assert set(oekg_api.TAG_KEYS) == set(kg.BUNDLE_TAGS)


# ---------------------------------------------------------------------------
# One bundle per project
# ---------------------------------------------------------------------------

def _paper(title, year, **overrides):
    fields = {"publication_title": [title], "publication_date": [year],
              "scenarios": (f"S{year}",)}
    fields.update(overrides)
    return _rows(**fields)


def test_two_papers_of_one_project_are_one_bundle_and_the_oldest_leads():
    """As in the Turtle, which mints the bundle from its label. The body of
    each paper alone would make two bundles of one study."""
    bundle, = _bundles({
        "b_2021": _paper("The Later Paper", "2021",
                         study_project_name=["ENGAGE PROJECT"],
                         publication_abstract=["The later abstract."],
                         study_organisation=["PIK", "Joint Research Centre"],
                         tags={"study_sector": TRANSPORT,
                               "study_technology": PHOTOVOLTAIC}),
        "a_2019": _paper("The Earlier Paper", "2019",
                         study_project_name=["Engage Project"],
                         publication_abstract=["The earlier abstract."],
                         tags={"study_sector": TRANSPORT,
                               "study_descriptor": PATHWAY}),
    })
    assert bundle["documents"] == ["a_2019", "b_2021"]
    payload = oekg_api.body(bundle, KNOWN)
    assert payload["label"] == "Engage Project", "the oldest paper's spelling"
    assert payload["abstract"] == "The earlier abstract."
    assert payload["acronym"] == "ENGAGE" and bundle["formed"] == []
    assert payload["organisations"] == [{"label": "Joint Research Centre"},
                                        {"label": "PIK"}]
    assert [r["label"] for r in payload["study_reports"]] == [
        "The Earlier Paper", "The Later Paper"]
    assert [s["label"] for s in payload["scenarios"]] == ["S2019", "S2021"]
    assert payload["sectors"] == [TRANSPORT], "one sector, said twice"
    assert payload["descriptors"] == [PATHWAY]
    assert payload["technologies"] == [PHOTOVOLTAIC]


def test_the_acronym_most_papers_give_names_the_bundle():
    """Not the leading paper's: one paper that writes the acronym its own
    way would otherwise rename the project the others agree on."""
    bundle, = _bundles({
        "a_2019": _paper("Paper A", "2019", study_acronym=["Engage-X"]),
        "b_2020": _paper("Paper B", "2020", study_acronym=["ENGAGE"]),
        "c_2021": _paper("Paper C", "2021", study_acronym=["ENGAGE"]),
    })
    assert bundle["documents"] == ["a_2019", "b_2020", "c_2021"]
    assert bundle["bundle"]["acronym"] == "ENGAGE"
    assert bundle["formed"] == []


def test_two_spellings_of_one_organisation_are_one_reference():
    """Each paper writes its institute its own way. Sent as two references,
    the platform would hold one organisation twice."""
    bundle, = _bundles({
        "a_2019": _paper("Paper A", "2019",
                         study_organisation=["Joint Research Centre"],
                         study_funder=["Horizon 2020"]),
        "b_2021": _paper("Paper B", "2021",
                         study_organisation=["JOINT RESEARCH CENTRE", "PIK"],
                         study_funder=["horizon 2020"]),
    })
    payload = oekg_api.body(bundle, KNOWN)
    assert payload["organisations"] == [{"label": "Joint Research Centre"},
                                        {"label": "PIK"}]
    assert payload["funders"] == [{"label": "Horizon 2020"}]


def test_every_entry_of_a_tag_reaches_the_body():
    """A study covers more than one sector. Each entry the model picked is
    one the bundle is tagged with, in the reading and in the body."""
    rows = _rows() + [{"parameter": "study_sector", "value": "an entry",
                       "value_uri": INDUSTRY, "provenance": {},
                       "quote": "the study covers another entry"}]
    assert _study(rows)["bundle"]["tags"]["study_sector"] == [TRANSPORT,
                                                              INDUSTRY]
    bundle, = _bundles({"geco_2023": rows})
    assert oekg_api.body(bundle, KNOWN)["sectors"] == [TRANSPORT, INDUSTRY]


def test_an_acronym_does_not_join_two_projects():
    """A paper thanks two projects, and a harvest then pairs one project's
    name with the other's acronym. Joined on the acronym, unrelated papers
    would chain into one bundle. They stay two and are reported."""
    bundles = _bundles({
        "a": _paper("Paper A", "2020", study_project_name=["CD-LINKS"],
                    study_acronym=["ENGAGE"]),
        "b": _paper("Paper B", "2021", study_project_name=["ENGAGE project"],
                    study_acronym=["ENGAGE"]),
    })
    assert [b["documents"] for b in bundles] == [["a"], ["b"]]
    entries = [{"documents": b["documents"], "problems": [],
                "body": oekg_api.body(b, KNOWN)} for b in bundles]
    oekg_api.acronym_problems(entries)
    assert [p["what"] for e in entries for p in e["problems"]] == [
        "acronym used by more than one bundle of this harvest"] * 2
    assert entries[0]["problems"][0]["message"] == "b"


# ---------------------------------------------------------------------------
# The acronym nobody read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, surname", [
    ("Keramidas, K.", "Keramidas"), ("Keywan Riahi", "Riahi"),
    ("K. Riahi", "Riahi"), ("Riahi K", "Riahi"),
    ("Keywan Riahi1,2*", "Riahi"), ("Detlef P. van Vuuren", "Vuuren"),
    ("van Vuuren, D.P.", "Vuuren"), ("Müller-Casseres, E.", "Müller-Casseres"),
    ("Li, M", "Li"), ("K. R.", ""), ("", ""),
    ("Brian C. O'Neill", "ONeill"), ("Patrick O\u2019Rourke", "ORourke"),
    ("Benigna Boza\u2010Kiss", "Boza-Kiss"),
    ("Mark Roelfsema et al.", "Roelfsema"),
    ("La Rovere et al. 2018", "Rovere"), ("John Smith Jr.", "Smith"),
    ("WU, JING", "WU"), ("Riahi KR", "Riahi"), ("J.M.", "")])
def test_the_family_name_of_an_author_as_documents_write_it(name, surname):
    assert oekg_api._surname(name) == surname


def test_a_bundle_of_two_papers_is_named_after_the_one_that_leads():
    """The formed name is the only way to find the bundle again. Taken from
    whichever paper came last, it would change when a third one joins."""
    bundle, = _bundles({
        "b_2021": _paper("The Later Paper", "2021", study_acronym=[],
                         study_project_name=["Project P"],
                         publication_author=["Elmar Kriegler"]),
        "a_2019": _paper("The Earlier Paper", "2019", study_acronym=[],
                         study_project_name=["Project P"],
                         publication_author=["Keywan Riahi"]),
    })
    assert bundle["documents"] == ["a_2019", "b_2021"]
    assert bundle["bundle"]["acronym"] == "Riahi-2019"
    assert bundle["formed"] == ["acronym"]


def test_a_bundle_no_document_names_is_named_after_author_and_year():
    """The platform demands an acronym and finds a bundle by nothing else.
    The name is made here and not read, so the bundle says so."""
    bundles = _bundles({
        "c": _paper("Paper C", "2021", study_acronym=[], study_project_name=[],
                    publication_author=["Keywan Riahi", "Elmar Kriegler"]),
        "a": _paper("Paper A", "2021", study_acronym=[], study_project_name=[],
                    publication_author=["Riahi, K."]),
        "b": _paper("Paper B", "2020", study_acronym=["RIAHI-2021"],
                    study_project_name=[]),
        "d": _paper("Paper D", "2021", study_acronym=[], study_project_name=[],
                    publication_author=[]),
        "e": _paper("Paper E", "2021", study_acronym=[], study_project_name=[],
                    publication_date=[]),
    })
    named = {b["documents"][0]: (b["bundle"]["acronym"], b["formed"])
             for b in bundles}
    assert named["b"] == ("RIAHI-2021", []), "read, and left alone"
    assert named["a"] == ("Riahi-2021-2", ["acronym"]), (
        "the read one is taken, whatever its case; first document first")
    assert named["c"] == ("Riahi-2021-3", ["acronym"])
    assert named["d"] == (None, []), "no author, no name"
    assert named["e"] == (None, []), "no date, no name"
    assert "acronym" not in oekg_api.body(
        [b for b in bundles if b["documents"] == ["d"]][0], KNOWN)


def test_the_formed_names_are_the_same_on_every_run():
    """The acronym is the only way to find the bundle again, so a second run
    over the same harvest must not hand the numbers out differently."""
    documents = {name: _paper(f"Paper {name}", "2021", study_acronym=[],
                              study_project_name=[],
                              publication_author=["Riahi, K."])
                 for name in ("z", "m", "a")}
    first = {b["documents"][0]: b["bundle"]["acronym"]
             for b in _bundles(documents)}
    again = {b["documents"][0]: b["bundle"]["acronym"]
             for b in _bundles(dict(reversed(list(documents.items()))))}
    assert first == again == {"a": "Riahi-2021", "m": "Riahi-2021-2",
                              "z": "Riahi-2021-3"}


# ---------------------------------------------------------------------------
# The body
# ---------------------------------------------------------------------------

def test_the_body_carries_the_bundle_its_report_and_its_scenarios():
    assert _body() == {
        "label": "Enabling Ambitious Climate Policy Assessment",
        "acronym": "ENGAGE",
        "abstract": "This report presents the results.",
        "organisations": [{"label": "Joint Research Centre"}],
        "funders": [{"label": "Horizon 2020"}],
        "descriptors": [PATHWAY], "sector_divisions": [DIVISION],
        "sectors": [TRANSPORT], "technologies": [PHOTOVOLTAIC],
        "study_reports": [{
            "label": "Global Energy and Climate Outlook 2023",
            "doi": "10.2760/58255",
            "publication_date": "2023-01-01T00:00:00",
            "authors": [{"label": "Keramidas, K."}, {"label": "Fosse, F."}]}],
        "scenarios": [{
            "label": "CurPol", "acronym": "CurPol",
            "abstract": "assumes no additional policies",
            "scenario_types": [POLICY],
            "study_regions": [{"iri": REGION, "label": "Germany"}],
            "years": ["2050-01-01T00:00:00"]}],
    }


def test_the_iam_annotation_stays_in_the_turtle_and_out_of_the_body():
    """The Turtle types every factsheet an IAM scenario. The platform's list
    does not hold that class and refuses a create for it. A factsheet with
    no other type then has none, and is refused for that instead."""
    assert IAM in _study()["scenarios"][0]["types"]
    assert IAM not in json.dumps(_body())
    scenario, = _body(kind=None)["scenarios"]
    assert "scenario_types" not in scenario
    assert ("OEO_00000365", "MinCount on OEO_00390073") in _refusals(
        _body(kind=None))


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
                    publication_abstract=[], tags=None)
    assert not {"acronym", "funders", "abstract", "descriptors",
                "sector_divisions", "sectors", "technologies"} & set(payload)
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
    for path, iri in (("OEO_00390071", PATHWAY), ("OEO_00390079", DIVISION),
                      ("OEO_00020439", TRANSPORT),
                      ("OEO_00020438", PHOTOVOLTAIC)):
        assert list(graph.objects(bundle, oeo(path))) == [URIRef(iri)]
        assert graph.value(URIRef(iri), RDFS.label) == Literal(KNOWN[iri])

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
    assert set(graph.objects(scenario, oeo("OEO_00390073"))) == {URIRef(POLICY)}
    assert graph.value(URIRef(POLICY), RDFS.label) == Literal(
        "target driven scenario")
    assert labelled(scenario, oeo("OEO_00020220"), "OEO_00020032") == {"Germany"}
    assert graph.value(scenario, oeo("OEO_00020440")) == Literal(
        "2050-01-01T00:00:00", datatype=XSD.dateTime)


def test_a_complete_body_is_refused_for_nothing():
    """Closed shapes over every node the model writes. A triple too many, a
    label or a class too few, a missing uuid or a broken has-part link each
    add a refusal, and then this set is no longer empty."""
    assert _refusals(_body()) == set()


def test_the_shapes_name_what_the_bundle_lacks():
    found = _refusals(_body(study_acronym=[], publication_date=[],
                            publication_author=[],
                            tags={"study_sector": TRANSPORT}))
    assert found == {
        ("scenario bundle (OEO_00020227)", "MinCount on acronym"),
        ("scenario bundle (OEO_00020227)",
         "MinCount on has study descriptor tag (OEO_00390071)"),
        ("scenario bundle (OEO_00020227)", "MinCount on OEO_00390079"),
        ("scenario bundle (OEO_00020227)", "MinCount on OEO_00020438"),
        ("OEO_00020012", "MinCount on OEO_00390096"),
        ("OEO_00020012", "MinCount on OEO_00000506")}


def test_an_entry_outside_a_list_is_named_and_so_is_its_missing_label():
    found = _refusals(_body(kind=UNLISTED))
    assert ("OEO_00000365", "In on OEO_00390073: OEO_00099999") in found
    assert ("OEO_00099999", "MinCount on label") in found, (
        "a node without a class is named itself")
    found = _refusals(_body(tags=dict(TAGS, study_sector=UNLISTED)))
    assert ("scenario bundle (OEO_00020227)",
            "In on OEO_00020439: OEO_00099999") in found


def test_the_model_refuses_a_key_it_does_not_cover():
    """The API takes energy carriers, contacts and more, which `body` never
    writes. A body that carried one would be judged as if it did not, so the
    model stops instead of answering."""
    pytest.importorskip("rdflib")
    for where, key in (("body", "energy_carriers"),
                       ("scenarios", "interacting_regions"),
                       ("study_reports", "reference")):
        payload = _body()
        target = payload if where == "body" else payload[where][0]
        target[key] = []
        with pytest.raises(ValueError, match=key):
            oekg_api.graph(payload, KNOWN)


def test_a_list_of_the_spec_that_left_the_shapes_list_is_reported():
    """The model picks from a list the spec copied from the shapes. A class
    the shapes dropped would be harvested and then refused, and one they
    gained could never be chosen."""
    assert oekg_api.list_problems(_shapes()) == []

    lists = {uri: _listed(uri) for uri in ("scenario_type",) + kg.BUNDLE_TAGS}
    lists["study_technology"] = [iri for iri in lists["study_technology"]
                                 if iri != PHOTOVOLTAIC]
    lists["scenario_type"] = lists["scenario_type"] + [UNLISTED]
    assert oekg_api.list_problems(_shapes(_shapes_text(lists))) == [
        "study_technology: the spec offers OEO_00010428, which the shapes do "
        "not list",
        "scenario_type: the shapes list OEO_00099999, which the spec does "
        "not offer"]


# ---------------------------------------------------------------------------
# The acronym on the platform
# ---------------------------------------------------------------------------

def _entry(name, acronym):
    payload = {"label": name}
    if acronym:
        payload["acronym"] = acronym
    return {"documents": [name], "body": payload, "problems": []}


def test_an_acronym_two_bundles_share_is_reported_on_both():
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
    """Regions and the snapshot's terms without any refresh; a property the
    shapes name and the spec does not only from the closure a vocabulary
    refresh left."""
    pytest.importorskip("rdflib")
    carrier = OEO + "OEO_00020432"       # covers energy carrier (shortcut)
    without = oekg_api.labels(tmp_path)
    assert without[REGION] == "Germany"
    assert without[POLICY] == "target driven scenario"
    assert without[TRANSPORT] == "transport sector", "a tag is in the snapshot"
    assert carrier not in without

    closure = tmp_path / "oeo-closure.owl"
    closure.write_text(
        '<?xml version="1.0"?>\n'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
        '         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">\n'
        f' <rdf:Description rdf:about="{carrier}">\n'
        '  <rdfs:label>covers energy carrier (shortcut)</rdfs:label>\n'
        ' </rdf:Description>\n'
        f' <rdf:Description rdf:about="{POLICY}">\n'
        '  <rdfs:label>another spelling</rdfs:label>\n'
        ' </rdf:Description>\n'
        '</rdf:RDF>\n', encoding="utf-8")
    upstream.lock_path("scenarios", tmp_path).write_text(json.dumps(
        {"sources": {"oeo": {"files": [{"path": str(closure)}]}}}),
        encoding="utf-8")
    known = oekg_api.labels(tmp_path)
    assert known[carrier] == "covers energy carrier (shortcut)"
    assert known[POLICY] == "target driven scenario", "the snapshot's stands"


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def _run(tmp_path, monkeypatch, documents, *extra, shapes=SHAPES):
    pytest.importorskip("pyshacl")
    yaml = pytest.importorskip("yaml")
    monkeypatch.setattr(oekg_api, "labels", lambda: KNOWN)
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
    # Nobody to name it after, and two scenarios that fail the same way: one
    # finding about one bundle.
    "unnamed": _rows(scenarios=("A1", "B1"), kind=UNLISTED,
                     study_acronym=[], study_project_name=[],
                     publication_author=[],
                     publication_title=["Another Outlook"]),
    "formed": _rows(study_acronym=[], study_project_name=[],
                    publication_title=["A Third Outlook"]),
    "untitled": _rows(publication_title=[]),
}


def test_the_run_reports_per_bundle_and_sends_nothing(tmp_path, monkeypatch,
                                                       capsys):
    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("the dry run opened a connection")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    code, entries = _run(tmp_path, monkeypatch, DOCUMENTS)
    out = capsys.readouterr().out
    assert code == 0
    assert "nothing was sent" in out
    assert "3 document(s) carry a study, 1 do not" in out
    assert "3 bundle(s), 0 of them from more than one document" in out
    assert "1 acronym(s) formed from the first author and the year" in out
    assert "2 bundle(s) would be created as they are, 1 would be refused" in out
    assert "refused by the request schema (bundles)" in out
    assert "     1  body: 'acronym' is a required property" in out
    assert "refused by the shapes (bundles)" in out
    assert "     1  scenario bundle (OEO_00020227): MinCount on acronym" in out
    assert "     1  OEO_00000365: In on OEO_00390073: OEO_00099999" in out, (
        "two factsheets of one bundle are one bundle")
    assert "the spec's lists against the shapes'" not in out
    assert "acronyms were not compared" in out
    assert "3 bundles" in out and "4 scenarios" in out and "4 authors" in out
    assert "3 sectors" in out and "3 sector divisions" in out

    by_document = {e["documents"][0]: e for e in entries}
    assert set(by_document) == {"complete", "unnamed", "formed"}
    assert all(e["method"] == "POST" and e["path"] == oekg_api.PATH
               for e in entries)
    assert by_document["complete"]["problems"] == []
    assert by_document["complete"]["formed"] == []
    assert by_document["formed"]["problems"] == []
    assert by_document["formed"]["formed"] == ["acronym"]
    assert by_document["formed"]["body"]["acronym"] == "Keramidas-2023"
    refused = by_document["unnamed"]["problems"]
    assert {p["check"] for p in refused} == {"schema", "shape"}
    assert len([p for p in refused if p["what"].startswith("In on")]) == 2, (
        "the file keeps every node; the report counts the bundle")


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
    assert "1 bundle(s) would be created as they are, 2 would be refused" in out
    taken, = [e for e in entries if e["documents"] == ["complete"]]
    assert taken["problems"][0]["message"] == "'engage': ENGAGE"


def test_two_documents_of_one_project_are_one_request(tmp_path, monkeypatch,
                                                      capsys):
    documents = {"paper_b": _paper("A Second Paper", "2022"),
                 "paper_a": _paper("A First Paper", "2021")}
    code, entries = _run(tmp_path, monkeypatch, documents)
    out = capsys.readouterr().out
    assert code == 0
    assert "2 document(s) carry a study, 0 do not" in out
    assert "1 bundle(s), 1 of them from more than one document" in out
    assert "1 bundle(s) would be created as they are, 0 would be refused" in out
    entry, = entries
    assert entry["documents"] == ["paper_a", "paper_b"]
    assert len(entry["body"]["study_reports"]) == 2
    assert "1 bundles" in out and "2 study reports" in out


def test_the_run_says_where_the_specs_lists_left_the_shapes(tmp_path,
                                                             monkeypatch, capsys):
    lists = {uri: _listed(uri) for uri in ("scenario_type",) + kg.BUNDLE_TAGS}
    lists["study_technology"] = [iri for iri in lists["study_technology"]
                                 if iri != PHOTOVOLTAIC]
    code, entries = _run(tmp_path, monkeypatch, {"complete": _rows()},
                         shapes=_shapes_text(lists))
    out = capsys.readouterr().out
    assert code == 0
    assert "the spec's lists against the shapes'" in out
    assert "study_technology: the spec offers OEO_00010428" in out
    assert "0 bundle(s) would be created as they are, 1 would be refused" in out
    assert [p["what"] for p in entries[0]["problems"]] == [
        "In on OEO_00020438: photovoltaic technology (OEO_00010428)"]


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
