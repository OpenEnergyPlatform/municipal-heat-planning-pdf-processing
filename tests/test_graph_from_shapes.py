"""A writer takes its paths, cardinalities and classes from the shapes it is
held to, follows a property the shapes renamed, and stops on one they
dropped; the gate shuts on a writer that does not build and on a kind of
violation the last graph did not have. A node the scenarios graph points at
without minting it is described once per file by its own source, a region by
the class its edge requires and LCC's English short name, an OEO term by its
release label, without a language tag, AND one its source does not name
carries no label of ours. A region is the LCC country of its own name, else
the one whose short name is among its labels, AND one that finds none or two
stays unnamed."""
import sqlite3
import tempfile
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from docpipe.extraction import fields, gate
from docpipe.extraction.shapemodel import Model, SchemaError
from profiles.scenarios import completion, kg, vocabulary

OEO = "https://openenergyplatform.org/ontology/oeo/"


def own(rows: list) -> list:
    """*rows* as the reading leaves values of this publication: every
    coordinate with an entry a value must have (`fields.kept`) read as that
    entry, by its key as the harvest keeps it, where the row says nothing of
    it."""
    for row in rows:
        parameter = kg.SPEC.by_uri.get(row.get("parameter"))
        for slot in fields.axis_slots(parameter) if parameter else ():
            if slot.keep and f"{slot.name}_state" not in row:
                row[slot.name] = slot.keep
                row[f"{slot.name}_state"] = fields.READ
    return rows


def empty_db() -> Path:
    """A database with no table: no document in it had pages a model read."""
    path = Path(tempfile.mkdtemp()) / "empty.db"
    sqlite3.connect(path).close()
    return path


def make_serializer(db, *args, **kwargs):
    """`kg.make_serializer` over rows of this publication (`own`); a database
    that does not exist stands for one that has nothing to say (`empty_db`),
    since the graph reads which documents had pages a model read from it."""
    inner = kg.make_serializer(db if Path(db).exists() else empty_db(),
                               *args, **kwargs)

    def serializer(name, rows):
        inner.decisions = serializer.decisions
        return inner(name, own(rows))
    serializer.decisions = {}
    return serializer


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
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    uuid = URIRef(OEO + "OEO_00390095")
    region = URIRef(OEO + "OEO_00020220")
    bundle = next(graph.subjects(predicate=None,
                                 object=URIRef(OEO + "OEO_00020227")))
    assert (None, region, None) in graph
    assert not list(graph.objects(bundle, uuid))
    assert len(list(graph.subject_objects(uuid))) == 2


def test_a_node_two_documents_describe_keeps_the_first_value_of_a_single_path():
    def rows(title, author, abstract):
        return [{"parameter": "publication_title", "value": title,
                 "quote": title},
                {"parameter": "publication_author", "value": author,
                 "quote": author},
                {"parameter": "study_project_name", "value": "ENGAGE",
                 "quote": "the ENGAGE project"},
                {"parameter": "publication_abstract", "value": abstract,
                 "quote": abstract}]
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    first = serializer("a", rows("Paper A", "Sergey Paltsev", "Abstract A"))
    second = serializer("b", rows("Paper B", "SERGEY PALTSEV", "Abstract B"))
    graph = Graph().parse(data=first + "\n" + second, format="turtle")
    label = URIRef("http://www.w3.org/2000/01/rdf-schema#label")
    author = next(graph.objects(predicate=URIRef(OEO + "OEO_00000506")))
    assert [str(o) for o in graph.objects(author, label)] == ["Sergey Paltsev"]
    bundle = next(graph.subjects(predicate=None,
                                 object=URIRef(OEO + "OEO_00020227")))
    abstract = URIRef("http://purl.org/dc/terms/abstract")
    assert [str(o) for o in graph.objects(bundle, abstract)] == ["Abstract A"]
    # Both reports are their own nodes and keep their own titles.
    reports = set(graph.subjects(predicate=None,
                                 object=URIRef(OEO + "OEO_00020012")))
    assert {str(graph.value(r, label)) for r in reports} == {"Paper A",
                                                             "Paper B"}


# Promise: a bundle is labelled with the study name the document prints, AND
# where it prints none the bundle carries no label, never the report's title
# (owner decision 2026-11-07); two such papers stay two bundles in the upload
# body, which then names no label.
def bundle_labels(rows):
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    label = URIRef("http://www.w3.org/2000/01/rdf-schema#label")
    bundle = next(graph.subjects(predicate=None,
                                 object=URIRef(OEO + "OEO_00020227")))
    return [str(o) for o in graph.objects(bundle, label)]


def test_a_bundle_is_labelled_only_by_the_study_name_the_document_prints():
    title = {"parameter": "publication_title", "value": "Net-zero EU",
             "quote": "Net-zero EU"}
    named = {"parameter": "study_project_name", "value": "ENGAGE",
             "quote": "the ENGAGE project"}
    assert bundle_labels([title, named]) == ["ENGAGE"]
    # the failure by construction: no study name, and the title stays the
    # report's
    assert bundle_labels([title]) == []


def test_papers_without_a_study_name_stay_apart_and_name_no_bundle_label():
    from profiles.scenarios import oekg_api

    def study(doc, title):
        return {"document": doc,
                "bundle": {"key": title, "label": None, "acronym": None,
                           "abstract": None, "organisations": [],
                           "funders": [], "tags": {}},
                "report": {"label": title, "authors": [],
                           "publication_date": None, "doi": None},
                "scenarios": []}
    merged = oekg_api.merge([study("a", "Paper A"), study("b", "Paper B")])
    assert len(merged) == 2
    assert all("label" not in oekg_api.body(one, {}) for one in merged)


# Promise: a title, date or DOI read on page 1 or on the first page the title
# was read on goes before one read anywhere else, AND without such a row the
# value most rows read still wins (owner decision 2026-11-05).
def dated(*years_on_pages, title_page=1):
    rows = [{"parameter": "publication_title", "value": "Net-zero EU",
             "quote": "Net-zero EU", "provenance": {"page": title_page}},
            {"parameter": "publication_author", "value": "Ioannis Tsiropoulos",
             "quote": "Ioannis Tsiropoulos",
             "provenance": {"page": title_page}}]
    return rows + [{"parameter": "publication_date", "value": year,
                    "quote": f"Published {year}", "provenance": {"page": page}}
                   for year, page in years_on_pages]


def year_in_graph(rows):
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    return [str(o)[:4] for o in
            graph.objects(predicate=URIRef(OEO + "OEO_00390096"))]


def test_a_year_on_the_first_page_goes_before_years_read_more_often_later():
    review = [("2018", 11), ("2018", 12), ("2018", 13), ("2018", 15)]
    assert year_in_graph(dated(("2020", 1), *review)) == ["2020"]
    # the failure by construction: no year on a front page, the most read wins
    assert year_in_graph(dated(("2020", 7), *review)) == ["2018"]


def test_behind_a_cover_the_page_the_title_was_read_on_is_a_front_page():
    rows = dated(("2019", 2), ("2017", 9), ("2017", 10), title_page=2)
    assert year_in_graph(rows) == ["2019"]


# Promise: where no front page gives a date, a DOI or an author, the value
# looked up in the catalogue goes before a reading anywhere else, AND a
# reading on a front page goes before the catalogue's, though the row looked
# up keeps the page of the reading it was found with; an author taken keeps
# every reading of the name as its evidence (owner decisions 2026-11-05).
def looked_up(parameter, value, page=1):
    anchor = {"parameter": "publication_title", "value": "Net-zero EU",
              "quote": "Net-zero EU", "provenance": {"page": page}}
    found = {"id": "https://openalex.org/W1", "publication_date": "2020-03-01",
             "authorships": [{"author": {"display_name": value}}]}
    return completion.row_of(anchor, parameter, value, found,
                             (completion.BY_TITLE, "Net-zero EU"), [])


def test_a_looked_up_year_goes_before_years_read_off_the_front_pages():
    review = [("2018", 11), ("2018", 12), ("2018", 13)]
    rows = dated(*review) + [looked_up("publication_date", "2020")]
    assert year_in_graph(rows) == ["2020"]
    # the failure by construction: without the record the rest decides
    assert year_in_graph(dated(*review)) == ["2018"]


def test_a_year_a_front_page_prints_goes_before_a_looked_up_one():
    # Two rows looked up on the title's page would outvote the one reading
    # there, were their page taken for where their value stands.
    record = looked_up("publication_date", "2020")
    assert year_in_graph(dated(("2019", 1)) + [record, dict(record)]) == [
        "2019"]


def authors_of(text):
    graph = Graph().parse(data=text, format="turtle")
    label = URIRef("http://www.w3.org/2000/01/rdf-schema#label")
    return sorted(str(graph.value(author, label)) for author in
                  graph.objects(predicate=URIRef(OEO + "OEO_00000506")))


def written_by(*names_on_pages):
    rows = [{"parameter": "publication_title", "value": "Net-zero EU",
             "quote": "Net-zero EU", "provenance": {"page": 1}}]
    return rows + [{"parameter": "publication_author", "value": name,
                    "quote": name,
                    "provenance": {"page": page, "owner_kind": "section",
                                   "owner_id": page}}
                   for name, page in names_on_pages]


def serialized(rows):
    return make_serializer(Path("no-such.db"), model=oekg())("doc", rows)


def test_the_authors_a_front_page_names_go_before_those_of_other_works():
    rows = written_by(("Ada Lovelace", 1), ("Grace Hopper", 12),
                      ("Alan Turing", 13))
    assert authors_of(serialized(rows)) == ["Ada Lovelace"]
    # the failure by construction: no author on a front page, every one counts
    rows = written_by(("Grace Hopper", 12), ("Alan Turing", 13))
    assert authors_of(serialized(rows)) == ["Alan Turing", "Grace Hopper"]


def test_authors_looked_up_go_before_authors_read_off_the_front_pages():
    rows = written_by(("Grace Hopper", 12)) + [
        looked_up("publication_author", "Ada Lovelace")]
    assert authors_of(serialized(rows)) == ["Ada Lovelace"]


def test_an_author_taken_keeps_every_reading_of_the_name_as_evidence():
    mark = kg.TRUST_PROSE["corroborated"]

    def confirmed(rows):
        return sum(mark in line for line in serialized(rows).splitlines())
    rows = written_by(("Ada Lovelace", 1), ("Ada Lovelace", 12),
                      ("Grace Hopper", 12))
    assert authors_of(serialized(rows)) == ["Ada Lovelace"]
    assert confirmed(rows) == 2
    # the failure by construction: read once, the name confirms nothing
    assert confirmed(written_by(("Ada Lovelace", 1), ("Grace Hopper", 12))) == 0


# Promise: a value is marked confirmed where its readings come from two
# different passages, AND two readings of one passage confirm nothing,
# whatever their quotes (owner decision 2026-11-05, as kwp's settle).
def confirmed_lines(*readings):
    rows = [{"parameter": "publication_title", "value": "Net-zero EU",
             "quote": quote,
             "provenance": {"page": 1, "owner_kind": kind, "owner_id": owner}}
            for kind, owner, quote in readings]
    rows.append({"parameter": "publication_author",
                 "value": "Ioannis Tsiropoulos", "quote": "Ioannis Tsiropoulos",
                 "provenance": {"page": 1, "owner_kind": "section",
                                "owner_id": 1}})
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    mark = kg.TRUST_PROSE["corroborated"]
    return sum(mark in line for line in serializer("doc", rows).splitlines())


def test_a_value_two_passages_print_is_confirmed_one_passage_read_twice_not():
    assert confirmed_lines(("section", 1, "Net-zero EU"),
                           ("table", 7, "Net-zero EU")) == 2
    # the failure by construction: one passage, two different quotes of it
    assert confirmed_lines(("section", 1, "Net-zero EU"),
                           ("section", 1, "Net-zero EU by 2050")) == 0


def test_a_referenced_node_is_checked_as_the_target_graph_holds_it():
    from docpipe.ontology import with_context
    oekg_ = "https://openenergyplatform.org/ontology/oekg/"
    graph = Graph().parse(data=f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <{oekg_}s> <{OEO}OEO_00020220> <{oekg_}region/China> ,
                                       <{oekg_}region/Atlantis> ;
                   <{OEO}OEO_00000506> <{oekg_}author> .
        <{oekg_}author> rdfs:label "Ada Lovelace" .""", format="turtle")
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    label = "http://www.w3.org/2000/01/rdf-schema#label"
    context = [(f"{oekg_}region/China", rdf_type, f"{OEO}OEO_00020032"),
               (f"{oekg_}region/China", label, "China"),
               (f"{oekg_}author", label, "Somebody else"),
               (f"{oekg_}region/Germany", label, "Germany")]
    assert with_context(graph, context) == 2
    china = URIRef(f"{oekg_}region/China")
    assert (china, URIRef(rdf_type), URIRef(f"{OEO}OEO_00020032")) in graph
    assert [str(o) for o in graph.objects(china, URIRef(label))] == ["China"]
    # The graph's own description stands alone; what the target lacks
    # stays bare, for the shapes to find.
    assert [str(o) for o in graph.objects(URIRef(f"{oekg_}author"),
                                          URIRef(label))] == ["Ada Lovelace"]
    assert not list(graph.predicate_objects(URIRef(f"{oekg_}region/Atlantis")))
    assert not list(graph.predicate_objects(URIRef(f"{oekg_}region/Germany")))


REGION = "https://openenergyplatform.org/ontology/oekg/region/"
LABEL = URIRef("http://www.w3.org/2000/01/rdf-schema#label")


def described(names, *documents):
    """The graph and the texts of *documents*, [(name, [region IRI])], each
    a study with one scenario, written with *names*."""
    serializer = make_serializer(Path("no-such.db"), model=oekg(),
                                    groups={}, names=names)
    texts = []
    for name, regions in documents:
        rows = [{"parameter": "publication_title", "value": f"Study {name}",
                 "quote": f"Study {name}"},
                {"parameter": "scenario_label", "value": "NDC",
                 "value_uri": "NDC", "value_raw": "NDC",
                 "quote": "the NDC scenario"}]
        rows += [{"parameter": "scenario_region", "value": iri,
                  "value_uri": iri, "value_raw": "there", "scenario": "NDC",
                  "scenario_raw": "NDC", "quote": "NDC covers there"}
                 for iri in regions]
        texts.append(serializer(name, rows))
    return Graph().parse(data="\n".join(texts), format="turtle"), texts


def test_a_node_the_graph_points_at_is_described_once_by_its_own_source():
    iam = OEO + kg.IAM_SCENARIO
    names = {REGION + "Germany": "Germany",
             iam: "integrated assessment modeling scenario"}
    graph, texts = described(names, ("a", [REGION + "Germany"]),
                             ("b", [REGION + "Germany", REGION + "Atlantis"]))
    germany = URIRef(REGION + "Germany")
    labels = list(graph.objects(germany, LABEL))
    assert labels == [Literal("Germany")]
    assert labels[0].language is None and labels[0].datatype is None
    rdf_type = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    assert (germany, rdf_type, URIRef(OEO + "OEO_00020032")) in graph
    assert list(graph.objects(URIRef(iam), LABEL)) == [
        Literal("integrated assessment modeling scenario")]
    # The second study cites both again and describes neither.
    assert f"<{REGION}Germany>\n" in texts[0]
    assert f"<{REGION}Germany>\n" not in texts[1]
    assert f"<{iam}>\n" not in texts[1]
    # A region the names lack is still the class its edge requires, and
    # carries no label of ours.
    atlantis = URIRef(REGION + "Atlantis")
    assert (atlantis, rdf_type, URIRef(OEO + "OEO_00020032")) in graph
    assert not list(graph.objects(atlantis, LABEL))


LCC = "https://www.omg.org/spec/LCC/Countries/"
LCC_FILE = f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:cr="{LCC}CountryRepresentation/">
""" + "".join(
    f"""  <rdf:Description rdf:about="{LCC}ISO3166-1-CountryCodes/{local}">
    <cr:hasEnglishShortName xml:lang="en">{name}</cr:hasEnglishShortName>
  </rdf:Description>
""" for local, name in (("Germany", "Germany"),
                        ("NorthMacedonia", "North Macedonia"),
                        ("Niger", "Niger (the)"), ("Nigeria", "Nigeria"))
) + "</rdf:RDF>\n"


def test_a_region_is_named_by_its_lcc_country_and_never_guessed(tmp_path):
    path = tmp_path / "lcc.rdf"
    path.write_text(LCC_FILE, encoding="utf-8")
    named, unnamed = vocabulary.region_names(path, {
        REGION + "Germany": ["Germany"],
        REGION + "Macedonia": ["Macedonia", "North Macedonia"],
        REGION + "Atlantis": ["Atlantis"],
        REGION + "Sahel": ["Niger (the)", "Nigeria"]})
    assert named == {REGION + "Germany": "Germany",
                     REGION + "Macedonia": "North Macedonia"}
    assert unnamed == [REGION + "Atlantis", REGION + "Sahel"]


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


# Promise: a region the list does not carry is a study region node of its
# own, labelled with the name the document prints, AND one with no printed
# name reaches no node (owner decision 2026-11-07).
def regions_of(raw):
    rows = [{"parameter": "publication_title", "value": "A Study",
             "quote": "A Study"},
            {"parameter": "scenario_label", "value": "NDC", "value_uri": "NDC",
             "value_raw": "NDC", "quote": "the NDC scenario"},
            {"parameter": "scenario_region", "value": "several regions",
             "value_uri": "out:multiregion", "value_raw": raw,
             "scenario": "NDC", "scenario_raw": "NDC",
             "quote": "NDC for OECD Europe"}]
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    label = URIRef("http://www.w3.org/2000/01/rdf-schema#label")
    return [str(graph.value(node, label)) for node in
            graph.objects(predicate=URIRef(OEO + "OEO_00020220"))]


def test_a_region_the_list_lacks_is_its_own_node_named_as_printed():
    assert regions_of("OECD Europe") == ["OECD Europe"]
    # the failure by construction: no printed name, no region
    assert regions_of("") == []


# Promise: a scenario's acronym is the short name the naming marked among its
# names, AND without one it is the scenario's name (owner decision
# 2026-11-07).
def acronyms_of(short_marked):
    rows = [{"parameter": "publication_title", "value": "A Study",
             "quote": "A Study"},
            {"parameter": "scenario_label", "value": "Distributed Generation",
             "quote": "Distributed Generation",
             "value_means": ["Distributed Generation"]},
            {"parameter": "scenario_label", "value": "ENTSO-E DG",
             "quote": "ENTSO-E DG", "value_means": ["Distributed Generation"],
             **({"value_short": True} if short_marked else {})}]
    serializer = make_serializer(Path("no-such.db"), model=oekg())
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    return [str(o) for o in graph.objects(
        predicate=URIRef("http://purl.org/dc/terms/acronym"))]


def test_the_printed_short_name_is_the_acronym_of_its_scenario():
    assert acronyms_of(True) == ["ENTSO-E DG"]
    # the failure by construction: no short name, the name is the acronym
    assert acronyms_of(False) == ["Distributed Generation"]
