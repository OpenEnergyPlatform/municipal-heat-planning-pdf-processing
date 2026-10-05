"""The graph a compiled spec describes, and where its values come from.

What is promised, sentence by sentence:

  * a value is written as the property of its node, as a literal of the
    property's datatype OR as the term chosen from the list;
  * a value that names a thing is a node of its own with that wording as
    its label AND the edge to it AND one node for one name however spelled;
  * a node is written only once something stands on it AND a link only
    between two nodes that are there AND a node that only links to one that
    is there is there too;
  * what the graph has no place for is left out and counted: a parameter
    with coordinates, an answer that is no term, a parameter without `kg`;
  * a property that allows fewer values than were read takes the ones of
    the best trust level AND writes none when those are still too many;
  * a spec that does not describe a graph is refused, block by block;
  * what is written is Turtle that loads;
  * the provenance is a file of its own beside the graph AND the graph is
    the same with and without it AND the switch turns it off;
  * every value has its reading (page, quote), an annotation per
    coordinate, and its trust level with the reasons;
  * every term the provenance uses is defined in its header;
  * the kwp writer leaves what it wrote AND the provenance of its values
    points at the nodes of its graph.
"""
import json
import logging
import sqlite3

import pytest

rdflib = pytest.importorskip("rdflib")
if not hasattr(rdflib, "Graph") or not hasattr(rdflib.Graph, "parse"):
    pytest.skip("rdflib is a stub here", allow_module_level=True)

from docpipe.extraction import fields, graph, identity, provenance  # noqa: E402
from docpipe.extraction import serialize  # noqa: E402
from docpipe.extraction.spec import load as load_spec  # noqa: E402
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL  # noqa: E402

EX = "https://graph.test/vocab#"
BASE = "https://graph.test/id/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
OA = "http://www.w3.org/ns/oa#"
PROV = "http://www.w3.org/ns/prov#"


def example(value, quote):
    return {"source": quote, "tuples": [{"value": value, "quote": quote}]}


def spec(**changes):
    raw = {
        "graph": {
            "base": BASE,
            "prefixes": {"ex": EX},
            "nodes": {"study": {"class": "ex:Study", "per": "document"},
                      "report": {"class": "ex:Report", "per": "document"},
                      "funder": {"class": "ex:Organisation",
                                 "per": "value"}},
            "links": [{"from": "study", "to": "report", "prefix": "ex",
                       "predicate": "hasReport", "label": "has report"}],
        },
        "parameters": [
            {"uri": "report_title", "label": "Title",
             "description": "The title of the report as its cover page states it.",
             "value_type": "text", "axes": {},
             "example": example("Net Zero", "The report Net Zero by 2050 sets out a pathway"),
             "kg": {"node": "report", "max": 1,
                    "property": {"prefix": "ex", "predicate": "title",
                                 "label": "title"}}},
            {"uri": "report_pages", "label": "Pages",
             "description": "How many pages the report has, counted to its last numbered page.",
             "value_type": "int", "unit_target": "pages",
             "units_accepted": {"pages": 1}, "axes": {},
             "example": {"source": "The report has 224 pages.", "tuples": [{
                 "value": 224, "unit_raw": "pages",
                 "quote": "The report has 224 pages."}]},
             "kg": {"node": "report",
                    "property": {"prefix": "ex", "predicate": "pages",
                                 "label": "pages",
                                 "datatype": "xsd:integer"}}},
            {"uri": "study_kind", "label": "Kind of study",
             "description": "What kind of study the document says it is, by its own words.",
             "value_type": "category", "axes": {},
             "vocabulary": {"ex:Scenario": ["scenario study"],
                            "ex:Review": ["review"]},
             "example": example("ex:Scenario", "This scenario study shows three pathways to 2050"),
             "kg": {"node": "study", "object": "term",
                    "property": {"prefix": "ex", "predicate": "kind",
                                 "label": "kind"}}},
            {"uri": "funder", "label": "Funder",
             "description": "The organisation that paid for the study, as the document names it.",
             "value_type": "text", "axes": {},
             "example": example("Acme Trust", "The work was funded by the Acme Trust"),
             "kg": {"node": "funder",
                    "property": {"prefix": "rdfs", "predicate": "label",
                                 "label": "label"},
                    "edge_from": {"node": "study", "prefix": "ex",
                                  "predicate": "fundedBy",
                                  "label": "funded by"}}},
        ],
    }
    for key, change in changes.items():
        change(raw) if callable(change) else raw.__setitem__(key, change)
    return raw


def row(parameter, value, quote=None, tier=TIER_TEXT, page=3, **more):
    made = {"kind": "tuple", "parameter": parameter, "value": value,
            "value_raw": str(value), "tier": tier,
            "quote": quote or f"the document says {value} here",
            "provenance": {"document_id": 1, "owner_kind": "section",
                           "owner_id": 12, "page": page,
                           "section_title": "Summary"}}
    made.update(more)
    return made


def triples(turtle):
    loaded = rdflib.Graph()
    loaded.parse(data=turtle, format="turtle")
    return {(str(s), str(p), str(o)) for s, p, o in loaded}


ROWS = [row("report_title", "Net Zero by 2050"),
        row("report_pages", 224.0),
        row("study_kind", "ex:Scenario"),
        row("funder", "Acme  Trust"), row("funder", "acme trust")]


# ------------------------------------------------------------- what is written

def test_the_spec_this_file_writes_from_is_a_spec():
    assert len(load_spec(spec()).parameters) == 4


def test_a_value_is_the_property_of_its_node():
    write = graph.make_serializer(spec())
    found = triples(write("iea 2021", ROWS))
    report, study = f"{BASE}report/iea%202021", f"{BASE}study/iea%202021"
    assert (report, RDF + "type", EX + "Report") in found
    assert (report, EX + "title", "Net Zero by 2050") in found
    assert (report, EX + "pages", "224") in found
    assert (study, EX + "kind", EX + "Scenario") in found
    loaded = rdflib.Graph().parse(data=write("b", ROWS), format="turtle")
    (pages,) = [o for _s, p, o in loaded if str(p) == EX + "pages"]
    assert str(pages.datatype) == XSD + "integer"
    (kind,) = [o for _s, p, o in loaded if str(p) == EX + "kind"]
    assert isinstance(kind, rdflib.URIRef)


def test_a_value_that_names_a_thing_is_a_node_with_its_wording():
    found = triples(graph.make_serializer(spec())("iea", ROWS))
    funder = f"{BASE}funder/acme-trust"
    assert (f"{BASE}study/iea", EX + "fundedBy", funder) in found
    assert (funder, RDF + "type", EX + "Organisation") in found
    labels = [o for s, p, o in found if s == funder and p == RDFS_LABEL]
    assert labels == ["Acme  Trust"]        # one node, the first spelling


def test_the_name_of_a_thing_is_written_under_the_parameters_property():
    """`kg.property` of a value that names a thing is where its name goes.
    The spec above says rdfs:label; one that says another gets another."""
    def named(raw):
        raw["parameters"][3]["kg"]["property"] = {
            "prefix": "ex", "predicate": "legalName", "label": "legal name"}

    found = triples(graph.make_serializer(spec(parameters=named))(
        "iea", ROWS))
    funder = f"{BASE}funder/acme-trust"
    assert (funder, EX + "legalName", "Acme  Trust") in found
    assert not [t for t in found if t[0] == funder and t[1] == RDFS_LABEL]


def test_a_thing_two_documents_name_is_one_node_labelled_once():
    write = graph.make_serializer(spec())
    first = write("a", [row("funder", "Acme Trust")])
    second = write("b", [row("funder", "ACME trust")])
    funder = f"{BASE}funder/acme-trust"
    assert f"<{funder}>\n" in first
    assert f"<{funder}>\n" not in second            # the node, once
    assert (f"{BASE}study/b", EX + "fundedBy", funder) in triples(second)


def test_a_link_stands_between_two_nodes_that_are_there():
    write = graph.make_serializer(spec())
    both = triples(write("a", ROWS))
    assert (f"{BASE}study/a", EX + "hasReport", f"{BASE}report/a") in both
    # only the report has a value: the study is there for the link's start
    only_report = triples(write("b", [row("report_pages", 10)]))
    assert (f"{BASE}study/b", EX + "hasReport", f"{BASE}report/b") \
        in only_report
    assert (f"{BASE}study/b", RDF + "type", EX + "Study") in only_report
    # only the study has a value: no report is claimed
    only_study = triples(write("c", [row("study_kind", "ex:Review")]))
    assert not [t for t in only_study if "report/c" in t[0] + t[2]]


def test_a_document_nothing_is_written_for_gives_nothing(caplog):
    write = graph.make_serializer(spec())
    assert write("a", []) is None
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.graph"):
        assert write("a", [row("unknown_parameter", 1)]) is None
    assert "not_in_graph" in caplog.text
    assert "a" not in write.claims


def _with_axis(raw):
    raw["parameters"][1]["axes"] = {"year": {"type": "int"}}
    raw["parameters"][1]["example"]["tuples"][0]["year"] = 2021


def test_what_the_graph_has_no_place_for_is_left_out_and_counted(caplog):
    write = graph.make_serializer(spec(axes=_with_axis))
    rows = [row("report_title", "Net Zero"),
            row("report_pages", 224, year=2021, year_state=fields.READ),
            row("study_kind", "out:unstated"),
            row("study_kind", "a review of sorts"),
            row("funder", "  ")]
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.graph"):
        found = triples(write("a", rows))
    assert not [t for t in found if t[1] in (EX + "pages", EX + "kind",
                                              EX + "fundedBy")]
    for counted in ("coordinates:report_pages", "not_a_term:study_kind': 2",
                    "unnamed:funder"):
        assert counted in caplog.text


def test_too_many_values_take_the_best_trust_level(caplog):
    write = graph.make_serializer(spec())
    rows = [row("report_title", "Net Zero by 2050"),
            row("report_title", "Net Zero", tier=TIER_VISUAL)]
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.graph"):
        found = triples(write("a", rows))
    titles = [o for _s, p, o in found if p == EX + "title"]
    assert titles == ["Net Zero by 2050"]
    assert "outranked:report_title': 1" in caplog.text


def test_too_many_values_of_one_level_write_none(caplog):
    write = graph.make_serializer(spec())
    rows = [row("report_title", "Net Zero by 2050"),
            row("report_title", "Net Zero"), row("report_pages", 224)]
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.graph"):
        found = triples(write("a", rows))
    assert not [t for t in found if t[1] == EX + "title"]
    assert "contested:report_title': 2" in caplog.text
    assert (f"{BASE}report/a", EX + "pages", "224") in found


def _one_funder(raw):
    raw["parameters"][3]["kg"]["max"] = 1


@pytest.mark.parametrize("rows, left_out, kept", [
    # two of one level: nothing decides, and neither is written
    ([row("funder", "Acme Trust"), row("funder", "Beta Foundation")],
     "contested:funder': 2", []),
    # the better level stays, with its node; the other leaves none
    ([row("funder", "Acme Trust"),
      row("funder", "Beta Foundation", tier=TIER_VISUAL)],
     "outranked:funder': 1", ["acme-trust"]),
])
def test_a_value_the_limit_took_out_leaves_no_node_behind(caplog, rows,
                                                         left_out, kept):
    write = graph.make_serializer(spec(parameters=_one_funder))
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.graph"):
        found = triples(write("a", rows + [row("report_pages", 224)]))
    assert left_out in caplog.text
    things = sorted({t[0].rsplit("/", 1)[1] for t in found
                     if t[0].startswith(f"{BASE}funder/")})
    assert things == kept
    edges = sorted(t[2].rsplit("/", 1)[1] for t in found
                   if t[1] == EX + "fundedBy")
    assert edges == kept


def test_one_value_read_twice_is_one_value():
    write = graph.make_serializer(spec())
    rows = [row("report_title", "Net Zero", quote="Net Zero, the report"),
            row("report_title", "Net Zero", quote="titled Net Zero")]
    found = triples(write("a", rows))
    assert [o for _s, p, o in found if p == EX + "title"] == ["Net Zero"]
    assert len(write.claims["a"]["values"]) == 2    # and both back it


def test_a_property_without_a_limit_takes_every_value():
    write = graph.make_serializer(spec())
    found = triples(write("a", [row("report_pages", 224),
                                row("report_pages", 230)]))
    assert sorted(o for _s, p, o in found if p == EX + "pages") \
        == ["224", "230"]


# ------------------------------------------------------------------- refusals

def _drop_graph(raw):
    del raw["graph"]


def _set(path, value):
    def change(raw):
        target = raw
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


@pytest.mark.parametrize("change, says", [
    (_drop_graph, "no `graph` block"),
    (_set(("graph", "base"), "https://graph.test/id"), "ends in / or #"),
    (_set(("graph", "base"), "not an iri/"), "must be an IRI"),
    (_set(("graph", "base"), "https://example.org/id/"), "placeholder"),
    (_set(("graph", "nodes"), {}), "names no node"),
    (_set(("graph", "nodes", "study", "class"), "foo:Study"),
     "graph.nodes.study.class"),
    (_set(("graph", "nodes", "study", "per"), "page"),
     "per must be document or value"),
    (_set(("graph", "links", 0, "to"), "nowhere"), "graph.links[0]"),
    (_set(("graph", "links", 0, "prefix"), "foo"), "graph.links[0]"),
    (_set(("parameters", 0, "kg", "node"), "nowhere"), "kg.node 'nowhere'"),
    (_set(("parameters", 0, "kg", "property", "prefix"), "foo"),
     "kg.property"),
    (_set(("parameters", 1, "kg", "property", "datatype"), "foo:int"),
     "datatype 'foo:int'"),
    (_set(("parameters", 3, "kg", "edge_from", "node"), "nowhere"),
     "kg.edge_from"),
    (_set(("parameters", 3, "kg", "edge_from", "node"), "funder"),
     "one of per document"),
    (_set(("parameters", 0, "kg", "node"), "funder"), "one per value"),
])
def test_a_spec_that_does_not_describe_a_graph_is_refused(change, says):
    with pytest.raises(graph.GraphError) as caught:
        graph.make_serializer(spec(change=change))
    assert says in str(caught.value)


@pytest.mark.parametrize("text", ['say "hello"', "a\\b", "line\nbreak",
                                  "tab\there", "Wärme – 50 %"])
def test_any_text_is_a_literal_that_loads(text):
    write = graph.make_serializer(spec())
    found = triples(write("a", [row("report_title", text)]))
    assert (f"{BASE}report/a", EX + "title", text) in found


# ----------------------------------------------------------------- provenance

def _harvest(tmp_path, name="iea", rows=ROWS, stamp=True):
    folder = tmp_path / "harvest"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in rows),
        encoding="utf-8")
    if stamp:
        (folder / f"{name}.stamp.json").write_text(json.dumps({
            "spec": "ab" * 32, "model": "the-model",
            "prompt/extraction/field": "v3",
            "producers": [{"pass": "harvest", "utc": "2026-10-01T10:00:00",
                           "model": "the-model"},
                          {"pass": "review", "utc": "2026-10-02T08:30:00",
                           "model": "the-model"}]}), encoding="utf-8")
    return folder


def _serialize(tmp_path, with_provenance=True, rows=ROWS):
    folder = _harvest(tmp_path, rows=rows)
    out = tmp_path / "out" / "graph.ttl"
    write = graph.make_serializer(spec())
    writer = provenance.Writer(write.base) if with_provenance else None
    serialize.run(folder, out, write, writer)
    return out


def test_the_provenance_is_a_file_of_its_own_and_the_graph_the_same(
        tmp_path):
    with_it = _serialize(tmp_path / "a")
    without = _serialize(tmp_path / "b", with_provenance=False)
    assert with_it.read_bytes() == without.read_bytes()
    beside = provenance.path_for(with_it)
    assert beside.name == "graph.prov.ttl" and beside.is_file()
    assert not provenance.path_for(without).exists()


@pytest.mark.parametrize("said, on", [(None, True), ("1", True), ("", True),
                                      ("0", False), ("false", False),
                                      ("off", False), ("no", False)])
def test_the_switch(monkeypatch, said, on):
    if said is None:
        monkeypatch.delenv(provenance.SWITCH, raising=False)
    else:
        monkeypatch.setenv(provenance.SWITCH, said)
    assert provenance.enabled() is on


def test_every_value_has_its_reading_with_page_and_quote(tmp_path):
    out = _serialize(tmp_path)
    found = rdflib.Graph().parse(provenance.path_for(out), format="turtle")
    name = identity.tuple_id("iea", ROWS[0])
    statement = rdflib.URIRef(f"{BASE}statement/iea/{name}")
    annotation = rdflib.URIRef(f"{BASE}prov/annotation/iea/{name}/value")
    assert (annotation, rdflib.URIRef(OA + "hasBody"), statement) in found
    # the statement is the triple the graph holds
    said = {str(p).rsplit("#", 1)[1]: str(o)
            for _s, p, o in found.triples((statement, None, None))}
    assert said["subject"] == f"{BASE}report/iea"
    assert said["predicate"] == EX + "title"
    assert said["object"] == "Net Zero by 2050"
    assert (statement, rdflib.URIRef(EX + "title"),
            None) not in found                  # and is not asserted twice
    quotes = set(found.query("""
        PREFIX oa: <http://www.w3.org/ns/oa#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?page ?exact ?kind ?title WHERE {
          ?a oa:hasTarget ?t . ?t oa:hasSource ?part ; oa:hasSelector ?s .
          ?s rdf:value ?page ; oa:refinedBy ?q . ?q oa:exact ?exact .
          ?part a ?kind ; dcterms:title ?title .
          FILTER(?a = <%s>) }""" % annotation))
    assert {tuple(map(str, line)) for line in quotes} == {
        ("page=3", ROWS[0]["quote"], "http://purl.org/spar/doco/Section",
         "Summary")}


def test_the_run_names_its_model_its_spec_and_what_it_generated(tmp_path):
    out = _serialize(tmp_path)
    found = rdflib.Graph().parse(provenance.path_for(out), format="turtle")
    run = rdflib.URIRef(f"{BASE}prov/run/iea")
    said = {}
    for _s, p, o in found.triples((run, None, None)):
        said.setdefault(str(p), []).append(str(o))
    assert said[PROV + "used"] == [f"{BASE}study/iea"]
    assert said[PROV + "wasAssociatedWith"] == [f"{BASE}prov/agent/the-model"]
    assert said[PROV + "startedAtTime"] == ["2026-10-01T10:00:00"]
    assert said[PROV + "endedAtTime"] == ["2026-10-02T08:30:00"]
    assert len(said[PROV + "generated"]) == 5
    vocabulary = f"{BASE}prov/vocabulary#"
    assert said[vocabulary + "specFingerprint"] == ["sha256:" + "ab" * 32]
    assert said[vocabulary + "promptHash"][0].startswith("sha256:")


def test_a_harvest_without_a_stamp_still_has_its_provenance(tmp_path):
    folder = _harvest(tmp_path, stamp=False)
    write = graph.make_serializer(spec())
    writer = provenance.Writer(write.base)
    serialize.run(folder, tmp_path / "graph.ttl", write, writer)
    found = rdflib.Graph().parse(tmp_path / "graph.prov.ttl",
                                 format="turtle")
    run = rdflib.URIRef(f"{BASE}prov/run/iea")
    assert (run, rdflib.URIRef(PROV + "used"), None) in found
    assert (run, rdflib.URIRef(PROV + "wasAssociatedWith"), None) \
        not in found


def _claims(rows, **value):
    return {"document": f"{BASE}plan/a", "values": [
        {"about": f"{BASE}value/{index}", "row": entry, **value}
        for index, entry in enumerate(rows)]}


def _prov(rows, vocabulary=None, transcribed=False, **value):
    writer = provenance.Writer(BASE, vocabulary)
    writer.add("a", _claims(rows, **value), transcribed=transcribed)
    text = writer.header() + "\n".join(writer.parts)
    return rdflib.Graph().parse(data=text, format="turtle"), writer


def test_a_document_name_stays_inside_its_comment():
    """Each document's part of the file begins with its name as a comment.
    A name with a line break in it does not end the comment early: what
    follows the break would be read as statements."""
    writer = provenance.Writer(BASE, None)
    writer.add("plan\n<urn:x> <urn:y> <urn:z> .",
               _claims([row("report_pages", 224)]))
    text = writer.header() + "\n".join(writer.parts)
    loaded = rdflib.Graph().parse(data=text, format="turtle")
    assert (rdflib.URIRef("urn:x"), rdflib.URIRef("urn:y"),
            rdflib.URIRef("urn:z")) not in loaded
    assert "# plan <urn:x> <urn:y> <urn:z> ." in text


def test_a_coordinate_has_an_annotation_of_its_own():
    reading = row("energy", 241.0, carrier="oeo:gas", carrier_raw="Erdgas",
                  carrier_state=fields.READ, carrier_source=["table", 44],
                  carrier_quote="| Erdgas | 241 |",
                  carrier_raw_foreign=True,
                  sector="out:total", sector_raw="Gesamt",
                  sector_state=fields.READ,
                  year=2030, year_state=fields.EXHAUSTED,
                  flags=["quote_repaired", "period:unstated",
                         "review:agree"])
    found, writer = _prov([reading], bodies={
        "carrier": "https://onto.test/gas"})
    name = identity.tuple_id("a", reading)
    ns = writer.namespace
    about = rdflib.URIRef(f"{BASE}value/0")

    def said(coordinate):
        node = rdflib.URIRef(
            f"{BASE}prov/annotation/a/{name}/{coordinate}")
        out = {}
        for _s, p, o in found.triples((node, None, None)):
            out.setdefault(str(p), []).append(o)
        return out

    carrier = said("carrier")
    assert carrier[ns + "about"] == [about]
    assert [str(o) for o in carrier[OA + "hasBody"]] \
        == ["https://onto.test/gas"]
    assert [str(o) for o in carrier[ns + "wording"]] == ["Erdgas"]
    assert [str(o) for o in carrier[ns + "readingState"]] == [ns + "read"]
    assert [o.toPython() for o in carrier[ns + "rawForeign"]] == [True]
    assert OA + "hasTarget" in carrier
    sector = said("sector")
    assert OA + "hasBody" not in sector             # a total is no class
    assert [str(o) for o in sector[ns + "outsideVocabulary"]] \
        == [ns + "total"]
    year = said("year")
    assert [str(o) for o in year[ns + "readingState"]] == [ns + "exhausted"]
    assert OA + "hasBody" not in year and OA + "hasTarget" not in year
    value = said("value")
    assert sorted(str(o) for o in value[ns + "readingNote"]) == [
        ns + "period_unstated", ns + "quote_repaired"]
    # the carrier's own passage is a part of the document too
    assert (rdflib.URIRef(f"{BASE}prov/part/a/table-44"),
            rdflib.URIRef(RDF + "type"),
            rdflib.URIRef("http://purl.org/spar/doco/Table")) in found
    review = rdflib.URIRef(f"{BASE}prov/review/a/{name}")
    assert (review, rdflib.URIRef(ns + "reviewOutcome"),
            rdflib.URIRef(ns + "agree")) in found


@pytest.mark.parametrize("change, transcribed, level, reasons, image", [
    ({}, False, "A", [], False),
    ({"tier": TIER_VISUAL}, False, "B", [], True),
    ({}, True, "B", ["page_transcribed"], False),
    ({"year": 2030, "year_state": fields.UNBACKED}, False, "C",
     ["unbacked"], False),
    ({"flags": ["computed", "review:disagree"]}, False, "C",
     ["computed", "disagree"], False),
])
def test_the_trust_of_a_value(change, transcribed, level, reasons, image):
    reading = row("energy", 241.0, **change)
    found, writer = _prov([reading], transcribed=transcribed)
    ns = writer.namespace
    node = rdflib.URIRef(
        f"{BASE}prov/trust/a/{identity.tuple_id('a', reading)}")
    assert (node, rdflib.URIRef(RDF + "type"),
            rdflib.URIRef(ns + "TrustAssessment")) in found
    assert [str(o) for o in found.objects(
        node, rdflib.URIRef(ns + "trustLevel"))] == [ns + level]
    assert sorted(str(o) for o in found.objects(
        node, rdflib.URIRef(ns + "trustReason"))) \
        == sorted(ns + reason for reason in reasons)
    assert [o.toPython() for o in found.objects(
        node, rdflib.URIRef(ns + "fromImage"))] == [image]
    derived = list(found.objects(node,
                                 rdflib.URIRef(PROV + "wasDerivedFrom")))
    assert len(derived) == (1 if "year" in change else 0)


def test_a_located_quote_has_its_rectangles():
    reading = row("energy", 241.0)
    reading["provenance"]["rects"] = [[10, 20, 110, 32.5], "not a box"]
    found, _writer = _prov([reading])
    values = {str(o) for o in found.objects(
        None, rdflib.URIRef(RDF + "value"))}
    assert values == {"page=3", "xywh=10,20,100,12.5"}


def test_every_term_the_provenance_uses_is_defined_in_its_header():
    reading = row("energy", 241.0, tier=TIER_VISUAL,
                  carrier="out:other", carrier_raw="Sonstige",
                  carrier_state=fields.SAID_UNSTATED,
                  year=None, year_state=fields.UNANSWERED,
                  sector=None, sector_state=fields.DERIVED,
                  flags=["quote_repaired", "not_located",
                         "review:unbacked"])
    found, writer = _prov([reading])
    ns = writer.namespace
    used = {str(term) for triple in found for term in triple
            if isinstance(term, rdflib.URIRef) and str(term).startswith(ns)}
    defined = {str(s) for s, _p, _o in found.triples(
        (None, rdflib.URIRef(RDF + "type"), None)) if str(s).startswith(ns)}
    assert used and used <= defined
    with pytest.raises(KeyError):
        writer.term("somethingNew")


def test_the_vocabulary_lives_where_the_writer_says():
    reading = row("energy", 241.0)
    _found, own = _prov([reading])
    assert own.namespace == f"{BASE}prov/vocabulary#"
    found, named = _prov([reading], vocabulary={
        "prefix": "mhpx", "iri": "https://purl.org/mhpo/prov/"})
    assert named.term("about") == "<https://purl.org/mhpo/prov/about>"
    assert "@prefix mhpx: <https://purl.org/mhpo/prov/> ." in named.header()
    with pytest.raises(ValueError):
        provenance.Writer(BASE, {"prefix": "prov", "iri": "https://x/"})
    with pytest.raises(ValueError):
        provenance.Writer("https://graph.test/id")


def test_nothing_collected_nothing_written(tmp_path, caplog):
    writer = provenance.Writer(BASE)
    writer.add("a", {"document": f"{BASE}plan/a", "values": []})
    assert writer.write(tmp_path / "graph.prov.ttl") is None
    assert not (tmp_path / "graph.prov.ttl").exists()


def test_a_provenance_file_of_an_earlier_graph_is_named(tmp_path, caplog):
    out = _serialize(tmp_path)
    beside = provenance.path_for(out)
    before = beside.read_bytes()
    write = graph.make_serializer(spec())
    with caplog.at_level(logging.WARNING,
                         logger="docpipe.extraction.serialize"):
        serialize.run(tmp_path / "harvest", out, write, None)
    assert "describes an earlier graph" in caplog.text
    assert beside.read_bytes() == before            # and is left alone


# ------------------------------------------------------------------------ kwp

def _kwp_database(tmp_path):
    db = tmp_path / "kwp.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                published TEXT, is_current INTEGER,
                                page_text_transcribed INTEGER);
        CREATE TABLE DocumentMeta (document INTEGER, municipality_ags TEXT);
        CREATE TABLE Municipalities (ags TEXT, name TEXT);
        INSERT INTO Documents VALUES (857, 'waermeplan_kassel_20240315.pdf',
                                      '2024-03-15', 1, 0);
        INSERT INTO DocumentMeta VALUES (857, '06611000');
        INSERT INTO Municipalities VALUES ('06611000', 'Kassel');
    """)
    conn.commit()
    conn.close()
    return db


def _kwp_row(**overrides):
    made = {"kind": "tuple", "parameter": "energy_consumption",
            "value": 241000, "value_raw": "241.000", "value_target": 241.0,
            "unit_raw": "kWh/a", "quote": "| Erdgas | 241.000 kWh/a |",
            "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
            "quantity_state": "read",
            "carrier": "OEO_00000292", "carrier_raw": "Erdgas",
            "carrier_state": "read",
            "sector": "out:total", "sector_raw": "Gesamt",
            "sector_state": "read", "year": 2030, "year_state": "read",
            "aggregation": "OEO_00140070", "aggregation_state": "derived",
            "scenario": "target", "scenario_state": "read",
            "spatial_scope": "municipality", "spatial_scope_state": "read",
            "tier": TIER_VISUAL,
            "provenance": {"document_id": 857, "owner_kind": "table",
                           "owner_id": 5, "page": 86}}
    made.update(overrides)
    return made


def test_the_kwp_writer_leaves_what_it_wrote(tmp_path):
    from profiles.kwp import kg
    name = "waermeplan_kassel_20240315"
    rows = [_kwp_row(), _kwp_row(year=None)]        # the second is left out
    write = kg.make_serializer(_kwp_database(tmp_path))
    turtle = write(name, rows)
    left = write.claims[name]
    assert left["document"] == f"{kg.BASE}heatplan/AGS_06611000_2024-03-15"
    assert left["transcribed"] is False
    (value,) = left["values"]
    assert f"<{value['about']}>" in turtle
    assert value["row"] is rows[0]
    assert value["id"] == identity.tuple_ids(name, rows)[0]
    assert value["bodies"] == {
        "quantity": kg.OEO + "OEO_00050016",
        "carrier": kg.OEO + "OEO_00000292",
        "aggregation": kg.OEO + "OEO_00140070",
        "year": kg.year_iri(2030),
        "scenario": f"{kg.BASE}targetscenario/AGS_06611000_2024-03-15",
        "spatial_scope": f"{kg.BASE}municipality/AGS_06611000"}
    assert kg.PROVENANCE["base"] == kg.BASE


def test_the_provenance_of_a_kwp_value_points_at_its_node(tmp_path):
    from profiles.kwp import kg
    name = "waermeplan_kassel_20240315"
    folder = _harvest(tmp_path, name=name, rows=[_kwp_row()])
    out = tmp_path / "graph.ttl"
    write = kg.make_serializer(_kwp_database(tmp_path))
    serialize.run(folder, out, write,
                  provenance.Writer(kg.PROVENANCE["base"], kg.PROVENANCE))
    data = rdflib.Graph().parse(out, format="turtle")
    found = rdflib.Graph().parse(provenance.path_for(out), format="turtle")
    mhpx = "https://purl.org/mhpo/prov/"
    values = {s for s, p, _o in data
              if str(p).endswith("OEO_00140178")}        # has number
    about = set(found.objects(None, rdflib.URIRef(mhpx + "about")))
    assert len(values) == 1 and about == values
    # nothing in the provenance starts from the value
    assert not list(found.triples((next(iter(values)), None, None)))
    sector = [s for s, _p, o in found.triples(
        (None, rdflib.URIRef(mhpx + "coordinate"), None)) if str(o) == "sector"]
    assert (sector[0], rdflib.URIRef(mhpx + "outsideVocabulary"),
            rdflib.URIRef(mhpx + "total")) in found
    levels = list(found.objects(None, rdflib.URIRef(mhpx + "trustLevel")))
    assert [str(level) for level in levels] == [mhpx + "B"]
