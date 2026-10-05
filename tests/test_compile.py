"""From the shapes of a graph to an extraction spec.

Promised: a draft says what the shapes and the ontology say (the node, the
property, the closed list with the ontology's labels, other names and
definitions, the datatype, the counts) AND nothing they do not say, which
it lists instead; a draft is a spec exactly when that list is empty; an
example reaches a spec only as a proposal that carries its own evidence AND
that a person accepted; and holding a hand-written spec against the shapes
reports and changes nothing.
"""
import copy
import json
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("rdflib")

from docpipe.compile import cli, draft, examples, shapes  # noqa: E402
from docpipe.compile.terms import Terms  # noqa: E402
from docpipe.extraction import spec as spec_module  # noqa: E402

SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dc: <http://purl.org/dc/terms/> .
@prefix ex: <http://example.org/shapes/> .
@prefix v: <http://example.org/vocab/> .

ex:ReportShape a sh:NodeShape ;
    sh:targetClass v:Report ;
    sh:property [ sh:path dc:title ; sh:datatype xsd:string ;
                  sh:minCount 1 ; sh:maxCount 1 ;
                  sh:name "title" ;
                  sh:description "The title of the report as printed on its cover page." ] ;
    sh:property [ sh:path v:hasTopic ; sh:minCount 1 ;
                  sh:in ( v:Housing v:Transport v:Energy ) ] ;
    sh:property [ sh:path v:status ; sh:in ( "draft" "final" ) ] ;
    sh:property [ sh:path v:publishedBy ; sh:class v:Organisation ] ;
    sh:property [ sh:path v:coversRegion ; sh:class v:Region ] ;
    sh:property [ sh:path v:hasPart ;
                  sh:or ( [ sh:class v:Chapter ] ) ] ;
    sh:property [ sh:path v:staff ; sh:datatype xsd:integer ] ;
    sh:property [ sh:path v:issued ; sh:datatype xsd:dateTime ;
                  sh:maxCount 1 ] ;
    sh:property [ sh:path ( v:a v:b ) ; sh:datatype xsd:string ] .

ex:ChapterShape a sh:NodeShape ;
    sh:targetClass v:Chapter ;
    sh:property [ sh:path dc:title ; sh:datatype xsd:string ] .

ex:LooseShape a sh:NodeShape ;
    sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ] .
"""

ONTOLOGY = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix v: <http://example.org/vocab/> .

v:hasTopic rdfs:label "has topic" ;
    skos:definition "Relates a report to the subject area it is mainly about." .
v:publishedBy rdfs:label "published by"@en , "herausgegeben von"@de ;
    skos:definition "Relates a report to the organisation that published it." .
v:staff rdfs:label "number of staff" .
v:Housing rdfs:label "housing" ; skos:altLabel "dwellings" , "homes" ;
    skos:definition "Buildings and units people live in." .
v:Transport rdfs:label "transport" .
v:Organisation rdfs:label "organisation" .
v:Region rdfs:label "region" .
v:North rdf:type v:Region ; rdfs:label "North" .
v:South rdf:type v:Coast ; rdfs:label "South" .
v:Coast rdfs:subClassOf v:Region .
"""


@pytest.fixture
def files(tmp_path):
    one, two = tmp_path / "shapes.ttl", tmp_path / "onto.ttl"
    one.write_text(SHAPES, encoding="utf-8")
    two.write_text(ONTOLOGY, encoding="utf-8")
    return one, two


@pytest.fixture
def drafted(files):
    found, prefixes = shapes.read([files[0]])
    return draft.draft(found, prefixes, Terms.read([files[1]]),
                       sources=("shapes.ttl",))


def _by_uri(raw):
    return {parameter["uri"]: parameter for parameter in raw["parameters"]}


# -- reading the shapes -------------------------------------------------------

def test_a_shape_is_read_as_it_is_written(files):
    found, prefixes = shapes.read([files[0]])
    by_name = {shape.name: shape for shape in found}
    assert set(by_name) == {"report", "chapter", "loose"}
    report = by_name["report"]
    assert report.target_class == "http://example.org/vocab/Report"
    props = {prop.path.rsplit("/", 1)[-1]: prop for prop in report.properties}
    assert (props["title"].datatype.endswith("#string"),
            props["title"].min_count, props["title"].max_count,
            props["title"].name) == (True, 1, 1, "title")
    assert props["hasTopic"].choices_are_terms
    assert len(props["hasTopic"].choices) == 3
    assert props["status"].choices == ["draft", "final"]
    assert not props["status"].choices_are_terms
    assert props["publishedBy"].classes == [
        "http://example.org/vocab/Organisation"]
    assert props["hasPart"].classes == ["http://example.org/vocab/Chapter"]
    # a path that is no single property is said, and not read as one
    assert len(report.properties) == 8
    assert any("no single property" in note for note in report.notes)
    # the file's own prefix, not a renamed one
    assert prefixes["dc"] == "http://purl.org/dc/terms/"
    assert by_name["loose"].target_class is None


# -- the draft ----------------------------------------------------------------

def test_a_closed_list_carries_the_ontology_s_own_words(drafted):
    topic = _by_uri(drafted)["report_has_topic"]
    assert topic["value_type"] == "category" and topic["label"] == "has topic"
    assert topic["description"].startswith("has topic: Relates a report")
    assert topic["vocabulary"]["http://example.org/vocab/Housing"] == {
        "label": "housing", "spellings": ["dwellings", "homes"],
        "definition": "Buildings and units people live in."}
    # no label in the files: the identifier, and nothing invented
    assert topic["vocabulary"]["http://example.org/vocab/Energy"] == {
        "label": "Energy"}
    assert topic["kg"] == {
        "node": "report", "object": "term", "min": 1,
        "property": {"prefix": "v", "predicate": "hasTopic",
                     "label": "has topic"}}
    status = _by_uri(drafted)["report_status"]
    assert status["vocabulary"] == {"draft": ["draft"], "final": ["final"]}
    assert status["kg"]["object"] == "literal"


def test_a_class_is_a_list_where_the_ontology_names_its_members(drafted):
    region = _by_uri(drafted)["report_coversregion"]
    assert region["value_type"] == "category"
    assert sorted(entry["label"] for entry in
                  region["vocabulary"].values()) == ["North", "South"]
    # nobody names an organisation: a node of its own, labelled by wording
    publisher = _by_uri(drafted)["report_published_by"]
    assert publisher["value_type"] == "text"
    assert publisher["kg"] == {
        "node": "organisation",
        "property": {"prefix": "rdfs", "predicate": "label",
                     "label": "label"},
        "edge_from": {"node": "report", "prefix": "v",
                      "predicate": "publishedBy", "label": "published by"}}
    assert drafted["graph"]["nodes"]["organisation"] == {
        "class": "v:Organisation", "per": "value"}


def test_a_property_between_two_nodes_is_structure_and_asks_nothing(drafted):
    assert not any("part" in uri for uri in _by_uri(drafted))
    assert drafted["graph"]["links"] == [
        {"from": "report", "to": "chapter", "prefix": "v",
         "predicate": "hasPart", "label": "hasPart"}]
    assert drafted["graph"]["nodes"]["report"] == {
        "class": "v:Report", "per": "document"}
    assert set(drafted["graph"]["nodes"]) == {"report", "chapter",
                                              "organisation"}
    assert any("loose" in note and "left out" in note
               for note in drafted["_notes"])


def test_a_datatype_decides_the_kind_of_value(drafted):
    by_uri = _by_uri(drafted)
    title = by_uri["report_title"]
    assert title["value_type"] == "text"
    assert title["kg"]["property"] == {
        "prefix": "dc", "predicate": "title", "label": "title",
        "datatype": "xsd:string"}
    assert (title["kg"]["min"], title["kg"]["max"]) == (1, 1)
    staff = by_uri["report_number_of_staff"]
    assert staff["value_type"] == "int"
    assert staff["unit_target"] is None and staff["units_accepted"] == {}
    issued = by_uri["report_issued"]
    assert issued["value_type"] == "text"
    assert issued["kg"]["property"]["datatype"] == "xsd:dateTime"
    # two shapes carry dc:title, and each parameter has a name of its own
    assert "chapter_title" in by_uri
    assert len(by_uri) == len(drafted["parameters"])


def test_the_labels_follow_the_language_asked_for(files):
    found, prefixes = shapes.read([files[0]])
    german = draft.draft(found, prefixes, Terms.read([files[1]], "de"))
    assert "report_herausgegeben_von" in _by_uri(german)


def test_a_draft_says_what_it_lacks_and_is_a_spec_when_it_lacks_nothing(
        drafted):
    open_points = draft.todo(drafted)
    assert any(line.startswith("graph.base:") for line in open_points)
    assert any(line.startswith("report_issued.label:")
               for line in open_points)        # nobody names v:issued
    assert any(line.startswith("report_status.description:")
               for line in open_points)
    assert any(line.startswith("report_number_of_staff.unit_target")
               for line in open_points)
    assert any("report_has_topic.vocabulary: 1 entry has no label" in line
               for line in open_points)
    assert sum(".example: missing" in line for line in open_points) == len(
        drafted["parameters"])
    with pytest.raises(spec_module.SpecError):
        spec_module.load(draft.finished(drafted))

    done = copy.deepcopy(drafted)
    done["graph"]["base"] = "https://data.example.org/id/"
    for parameter in done["parameters"]:
        parameter["_drafted"] = {"label_from_ontology": True}
        parameter["description"] = (f"{parameter['label']}: what the "
                                    f"report states about it, in full.")
        numeric = parameter["value_type"] in ("int", "float")
        if numeric:
            parameter["unit_target"] = "persons"
            parameter["units_accepted"] = {"persons": 1}
        for iri, entry in (parameter.get("vocabulary") or {}).items():
            if isinstance(entry, dict) and entry["label"] == "Energy":
                entry["label"] = "energy"
        value = 12 if numeric else (
            next(iter(parameter["vocabulary"].values()))
            if "vocabulary" in parameter else "Annual report")
        if isinstance(value, dict):
            value = value["label"]
        elif isinstance(value, list):
            value = value[0]
        parameter["example"] = {
            "source": f"The annual report states {value} on its first page.",
            "tuples": [{"value": value, **({"unit": "persons"}
                                           if numeric else {}),
                        "quote": f"states {value} on its first page"}]}
    assert draft.todo(done) == []
    loaded = spec_module.load(draft.finished(done))
    assert len(loaded.parameters) == len(done["parameters"])
    assert "_drafted" not in json.dumps(draft.finished(done))
    assert "_notes" not in draft.finished(done)


def test_a_class_may_be_a_prefixed_name_or_an_iri_and_never_a_bare_word():
    spec_module._validate_kg_ids("p", {"class": "schema:Person"})
    spec_module._validate_kg_ids("p", {"class": "https://schema.org/Person"})
    spec_module._validate_kg_ids("p", {"class": "OEO_00030022"})
    for bad in ("Person", "OEO_00030022 organisation", "schema: Person"):
        with pytest.raises(spec_module.SpecError):
            spec_module._validate_kg_ids("p", {"class": bad})


# -- an existing spec against the shapes --------------------------------------

def _hand_written():
    return {"parameters": [
        {"uri": "topic", "vocabulary": {
            "http://example.org/vocab/Housing": {"label": "homes"},
            "http://example.org/vocab/Transport": ["transport"],
            "http://example.org/vocab/Water": ["water"],
            "out:not_in_list": ["none of these"]},
         "kg": {"node": "report", "class": "v:Report",
                "property": {"prefix": "v", "predicate": "hasTopic"}}},
        {"uri": "title", "kg": {"node": "report", "property": {
            "prefix": "dc", "predicate": "title"}}},
        {"uri": "chapter_heading", "kg": {"property": {
            "prefix": "dc", "predicate": "title"}}},
        {"uri": "budget", "kg": {"node": "report", "property": {
            "prefix": "v", "predicate": "budget"}}},
        {"uri": "note"},
    ]}


def test_the_differences_are_reported_and_nothing_is_changed(files):
    found, _prefixes = shapes.read([files[0]])
    spec_raw = _hand_written()
    before = copy.deepcopy(spec_raw)
    rows = draft.differences(found, spec_raw, Terms.read([files[1]]))
    assert spec_raw == before
    by_kind: dict = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)
    assert [(r["parameter"], r["detail"]) for r in by_kind["list_missing"]] \
        == [("topic", "1 entry of the shapes' list not in the spec: Energy")]
    # the profile's own "none of these" is no term the shapes should have
    assert [r["detail"] for r in by_kind["list_extra"]] == [
        "1 entry of the spec not in the shapes' list: Water"]
    assert [(r["parameter"], r["path"]) for r in by_kind["label"]] == [
        ("topic", "Housing")]
    assert [r["parameter"] for r in by_kind["not_in_shapes"]] == ["budget"]
    assert [r["parameter"] for r in by_kind["no_graph_block"]] == ["note"]
    # dc:title stands on two nodes: settled by the node's class where the
    # spec names it anywhere, and said to be open where it does not
    assert ("title", "title") in [(r["parameter"], r["path"])
                                  for r in by_kind["cardinality"]]
    assert [r["parameter"] for r in by_kind["ambiguous"]] == [
        "chapter_heading"]
    unasked = {r["path"] for r in by_kind["not_asked"]}
    assert {"status", "publishedBy", "staff"} <= unasked
    assert "hasTopic" not in unasked and "title" not in unasked


def test_a_spec_drafted_from_the_shapes_differs_from_them_in_nothing(files):
    """The comparison reads the format the compiler writes: a node's class
    in the `graph` block, the links there, and min and max in `kg`."""
    found, prefixes = shapes.read([files[0]])
    terms = Terms.read([files[1]])
    drafted = draft.finished(draft.draft(found, prefixes, terms))
    assert draft.differences(found, drafted, terms) == []

    # and each of the three is still seen where the spec says otherwise
    limited = next(parameter for parameter in drafted["parameters"]
                   if "max" in parameter["kg"])
    limited["kg"]["max"] += 1
    link = drafted["graph"]["links"].pop()
    for node in drafted["graph"]["nodes"].values():
        node.pop("class")
    rows = draft.differences(found, drafted, terms)
    kinds = {row["kind"] for row in rows}
    assert {"cardinality", "not_asked", "ambiguous"} <= kinds
    said = next(row for row in rows if row["kind"] == "cardinality"
                and row["parameter"] == limited["uri"])
    assert "the spec says min" in said["detail"]
    assert link["predicate"] in {row["path"] for row in rows
                                 if row["kind"] == "not_asked"}


# -- proposals ----------------------------------------------------------------

PASSAGE = ("The annual report was prepared by Riverside Housing Association "
           "in 2023.\nIt employs 3,251 people across the region.")
TEXT = {"uri": "publisher", "label": "publisher", "value_type": "text",
        "description": "The organisation that prepared and published the "
                       "report."}
NUMBER = {"uri": "staff", "label": "staff", "value_type": "int",
          "description": "How many people the organisation employs in "
                         "total.",
          "unit_target": "persons", "units_accepted": {"persons": 1}}


def test_a_proposal_is_kept_only_with_its_own_evidence():
    good = {"value": "Riverside Housing Association",
            "quote": "prepared by Riverside Housing Association in 2023"}
    kept, dropped = examples.checked([
        good,
        {"value": "Riverside", "quote": "written by the Riverside group"},
        {"value": "2023", "quote": "in 2023"},
        {"value": "Northern Homes", "quote": "It employs 3,251 people"},
        "not a tuple",
    ], PASSAGE, TEXT)
    assert kept == [good]
    assert [why for _raw, why in dropped] == [
        examples.NOT_IN_PASSAGE, examples.TOO_SHORT, examples.NOT_IN_QUOTE,
        examples.NOT_A_TUPLE]
    # the wording decides, not the name it was filed under
    kept, _ = examples.checked([{
        "value": "housing association", "value_raw": "Housing Association",
        "quote": "Riverside Housing Association in 2023"}], PASSAGE, TEXT)
    assert len(kept) == 1


def test_a_number_is_held_to_its_digits_as_the_corpus_writes_them(
        monkeypatch):
    from docpipe.extraction import verify
    monkeypatch.setattr(verify, "_marks", {})
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    quote = "It employs 3,251 people across the region."
    kept, dropped = examples.checked(
        [{"value": 3251, "unit": "persons", "quote": quote},
         {"value": 3.251, "unit": "persons", "quote": quote}], PASSAGE,
        NUMBER)
    assert [row["value"] for row in kept] == [3251]
    assert [why for _raw, why in dropped] == [examples.NOT_IN_QUOTE]


def test_proposals_come_from_passages_and_wait_for_a_person():
    spec_raw = {"parameters": [dict(TEXT), dict(NUMBER),
                               {**TEXT, "uri": "has_one",
                                "example": {"source": "x", "tuples": []}}]}
    asked = []

    def find(parameter):
        return [{"document": "a.pdf", "where": ["section", 1],
                 "text": "too short"},
                {"document": "a.pdf", "where": ["section", 2],
                 "text": PASSAGE},
                {"document": "b.pdf", "where": ["section", 9],
                 "text": PASSAGE + " And more of the same text follows."},
                {"document": "c.pdf", "where": ["section", 4],
                 "text": PASSAGE}]

    def ask(parameter, passage):
        asked.append((parameter["uri"], passage))
        if parameter["uri"] == "staff":
            return {"tuples": [{"value": 99, "quote": "employs 3,251 people"}]}
        return {"tuples": [{"value": "Riverside Housing Association",
                            "value_raw": None,
                            "quote": "prepared by Riverside Housing "
                                     "Association in 2023"}]}

    review = examples.propose(spec_raw, find, ask, per_parameter=2)
    assert set(review["parameters"]) == {"publisher", "staff"}
    publisher = review["parameters"]["publisher"]
    assert len(publisher["proposals"]) == 2          # and no third passage
    assert publisher["passages_read"] == 2
    first = publisher["proposals"][0]
    assert first["accept"] is False and first["document"] == "a.pdf"
    assert first["tuples"] == [{
        "value": "Riverside Housing Association",
        "quote": "prepared by Riverside Housing Association in 2023"}]
    assert first["source"] == PASSAGE       # short: shown whole
    staff = review["parameters"]["staff"]
    assert staff["proposals"] == []
    assert staff["dropped"] == {examples.NOT_IN_QUOTE: 3}
    assert all(passage != "too short" for _uri, passage in asked)


@pytest.mark.parametrize("reply, counted", [
    (None, "reply:not_served"),
    ("cut_off", "reply:cut_off"),
    ({"tuples": {"value": 1}}, "reply:wrong_shape"),
    ({"other": []}, "reply:wrong_shape"),
])
def test_a_request_without_a_readable_reply_is_no_passage_that_was_read(
        reply, counted):
    """What came back is counted under its cause, and the passage is not
    counted as read. An empty list is an answer: nothing is stated there."""
    def find(parameter):
        return [{"document": "a.pdf", "where": ["section", 2],
                 "text": PASSAGE}] * 3

    review = examples.propose({"parameters": [dict(TEXT)]}, find,
                              lambda parameter, passage: reply)
    entry = review["parameters"]["publisher"]
    assert (entry["passages_read"], entry["dropped"], entry["proposals"]) \
        == (0, {counted: 3}, [])
    review = examples.propose({"parameters": [dict(TEXT)]}, find,
                              lambda parameter, passage: {"tuples": []})
    entry = review["parameters"]["publisher"]
    assert (entry["passages_read"], entry["dropped"]) == (3, {})
    # an item of the list that is no tuple is counted too
    review = examples.propose({"parameters": [dict(TEXT)]}, find,
                              lambda parameter, passage: {"tuples": ["x"]})
    assert review["parameters"]["publisher"]["dropped"] == {
        examples.NOT_A_TUPLE: 3}


def test_what_is_proposed_can_be_applied():
    """An example shows a part of its passage. A tuple whose quote is not
    in that part is not proposed, because it would be refused on apply."""
    first = "The report was prepared by Riverside Housing Association."
    far = "It was published by Northern Homes Group in 2023."
    filler = "\n".join(f"Line {i} of an annex about other things entirely."
                       for i in range(80))
    passage = first + "\n" + filler + "\n" + far
    assert len(passage) > examples.SNIPPET_MAX + len(far)
    broken = "published by Northern\nHomes Group"   # other spacing

    def ask(parameter, text):
        return {"tuples": [
            {"value": "Riverside Housing Association",
             "quote": "prepared by Riverside Housing Association"},
            {"value": "Northern Homes Group",
             "quote": "published by Northern Homes Group in 2023"}]}

    spec_raw = {"parameters": [dict(TEXT)]}
    review = examples.propose(spec_raw, lambda parameter: [
        {"document": "a.pdf", "where": ["section", 1], "text": passage}], ask)
    entry = review["parameters"]["publisher"]
    (proposal,) = entry["proposals"]
    assert [t["value"] for t in proposal["tuples"]] == [
        "Riverside Housing Association"]
    assert entry["dropped"] == {examples.NOT_SHOWN: 1}
    assert len(proposal["source"]) <= examples.SNIPPET_MAX
    proposal["accept"] = True
    _done, applied, problems = examples.apply(spec_raw, review)
    assert (applied, problems) == (["publisher"], [])

    # a quote the passage carries with other spacing, beyond what is shown
    review = examples.propose(spec_raw, lambda parameter: [
        {"document": "a.pdf", "where": ["section", 1],
         "text": passage.replace("Northern Homes", "Northern  Homes")}],
        lambda parameter, text: {"tuples": [{
            "value": "Northern Homes Group", "quote": broken}]})
    entry = review["parameters"]["publisher"]
    assert entry["proposals"] == []
    assert entry["dropped"] == {examples.NOT_SHOWN: 1}


def test_the_best_passage_of_each_document_is_asked_before_any_second():
    assert examples.by_rank([["a1", "a2"], ["b1"], [], ["d1", "d2", "d3"]]) \
        == ["a1", "b1", "d1", "a2", "d2", "d3"]
    assert examples.by_rank([]) == [] and examples.by_rank([[]]) == []


class _Reply:
    def __init__(self, content, finish="stop"):
        self.choices = [NS(message=NS(content=content,
                                      reasoning_content=None),
                           finish_reason=finish)]
        self.usage = None


class _Client:
    def __init__(self, replies):
        self.replies, self.asked = list(replies), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.asked.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Reply(reply)


PROMPT = NS(text="Propose an example.", meta={"max_tokens": 200})
GOOD = json.dumps({"tuples": [{"value": "x", "quote": "the x of it"}]})


def test_a_reply_that_is_not_the_object_is_asked_again_with_its_cause(
        monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    client = _Client(["```json\n" + GOOD + "\n```", GOOD])
    got = cli.ask_for_example(client, PROMPT, dict(TEXT), PASSAGE)
    assert got == json.loads(GOOD)              # read, not cut out of fences
    first, second = client.asked
    assert len(first["messages"]) == 2 and len(second["messages"]) == 4
    assert second["messages"][2] == {"role": "assistant",
                                     "content": "```json\n" + GOOD + "\n```"}
    assert second["messages"][3]["role"] == "user"
    assert second["messages"][3]["content"].strip()
    from docpipe.llm_preflight import request_extras
    for asked in client.asked:                  # as every request of a run
        assert asked["extra_body"] == request_extras()


@pytest.mark.parametrize("replies, cause", [
    (["no json here", "still none"], "no_object"),
    (['{"tuples": "many"}', '{"tuples": 3}'], "missing_key"),
    ([RuntimeError("down"), RuntimeError("down")], "not_served"),
    (["", ""], "empty"),
])
def test_a_request_that_gets_no_object_says_why(monkeypatch, replies, cause):
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    client = _Client(replies)
    assert cli.ask_for_example(client, PROMPT, dict(TEXT), PASSAGE) == cause
    assert len(client.asked) == cli.ASK_ATTEMPTS


def test_an_example_shows_the_lines_around_its_quote_and_not_the_rest():
    far = "\n".join(f"Line {i} of a long annex that is about other things."
                    for i in range(40))
    row = "| Housing | 3,251 | 2023 |"
    passage = f"{far}\n| Topic | Staff | Year |\n{row}\n{far}"
    shown = examples.snippet(passage, [row])
    assert row in shown and "| Topic | Staff | Year |" in shown
    assert len(shown) < len(passage) / 3
    assert all(line in passage.split("\n") for line in shown.split("\n"))
    # a quote that cannot be placed letter for letter: the passage's start
    assert examples.snippet(passage, ["not in here"]) == passage[
        :examples.SNIPPET_MAX]


def test_only_what_a_person_accepted_reaches_the_spec():
    spec_raw = {"parameters": [dict(TEXT), dict(NUMBER)]}
    proposal = {"accept": False, "source": PASSAGE.split("\n")[0],
                "tuples": [{"value": "Riverside Housing Association",
                            "quote": "prepared by Riverside Housing "
                                     "Association in 2023"}]}
    review = {"parameters": {"publisher": {"proposals": [
        proposal, dict(proposal)]}}}
    done, applied, problems = examples.apply(spec_raw, review)
    assert (applied, problems) == ([], [])
    assert "example" not in done["parameters"][0]

    review["parameters"]["publisher"]["proposals"][0]["accept"] = True
    done, applied, problems = examples.apply(spec_raw, review)
    assert applied == ["publisher"] and not problems
    assert done["parameters"][0]["example"] == {
        "source": proposal["source"], "tuples": proposal["tuples"]}
    assert "example" not in spec_raw["parameters"][0]   # the input is kept

    review["parameters"]["publisher"]["proposals"][1]["accept"] = True
    done, applied, problems = examples.apply(spec_raw, review)
    assert "2 proposals are accepted" in problems[0] and done is spec_raw


def test_an_accepted_example_that_was_edited_past_its_evidence_is_refused():
    spec_raw = {"parameters": [dict(TEXT)]}
    review = {"parameters": {
        "publisher": {"proposals": [{
            "accept": True, "source": PASSAGE,
            "tuples": [{"value": "Northern Homes",
                        "quote": "prepared by Riverside Housing "
                                 "Association in 2023"}]}]},
        "gone": {"proposals": [{"accept": True, "source": PASSAGE,
                                "tuples": []}]}}}
    done, applied, problems = examples.apply(spec_raw, review)
    assert applied == [] and done is spec_raw
    assert any(examples.NOT_IN_QUOTE in line for line in problems)
    assert any("gone: the spec has no such parameter" in line
               for line in problems)


def test_the_request_shows_the_parameter_and_names_its_reply():
    shown = examples.payload({**TEXT, "vocabulary": {
        "u1": {"label": "housing", "definition": "homes", "spellings": []},
        "u2": ["transport", "traffic"]}}, PASSAGE)
    assert shown["passage"] == PASSAGE
    assert shown["parameter"]["options"] == {
        "housing": {"definition": "homes"}, "transport": ["traffic"]}
    assert examples.payload(NUMBER, PASSAGE)["parameter"][
        "units_accepted"] == ["persons"]
    name, shape = examples.reply_shape(numeric=True)
    item = shape["properties"]["tuples"]["items"]
    assert name == "example_reply" and "unit" in item["properties"]
    assert item["properties"]["value"] == {"type": "number"}
    assert "unit" not in examples.reply_shape(False)[1]["properties"][
        "tuples"]["items"]["properties"]


# -- the command --------------------------------------------------------------

def test_the_command_drafts_checks_and_writes_a_spec_only_when_done(
        files, tmp_path, capsys):
    out = tmp_path / "draft.json"
    assert cli.main(["spec", "--shapes", str(files[0]), "--ontology",
                     str(files[1]), "--out", str(out),
                     "--base", "https://data.example.org/id/"]) == 0
    assert "point(s) open" in capsys.readouterr().out
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["graph"]["base"] == "https://data.example.org/id/"
    assert cli.main(["check", str(out)]) == 1
    listed = capsys.readouterr().out
    assert "report_title.example: missing" in listed

    # one accepted example is carried over; the spec is not written yet
    review = examples.review_path(out)
    assert review.name == "draft." + examples.REVIEW_FILE
    review.write_text(json.dumps({"parameters": {"report_title": {
        "proposals": [{"accept": True,
                       "source": "Annual Report 2023 of the Riverside "
                                 "Housing Association",
                       "tuples": [{"value": "Annual Report 2023",
                                   "quote": "Annual Report 2023 of the "
                                            "Riverside"}]}]}}}),
        encoding="utf-8")
    final = tmp_path / "extraction_spec.json"
    assert cli.main(["apply", str(out), "--out", str(final)]) == 1
    said = capsys.readouterr().out
    assert "1 example(s) carried over" in said and "not written" in said
    assert not final.exists()
    assert "example" in _by_uri(json.loads(out.read_text(
        encoding="utf-8")))["report_title"]


def test_the_examples_step_writes_proposals_beside_the_draft_and_leaves_it(
        tmp_path, monkeypatch, capsys):
    draft_path = tmp_path / "draft.json"
    text = json.dumps({"parameters": [dict(TEXT), dict(NUMBER)]})
    draft_path.write_text(text, encoding="utf-8")

    def find(parameter):
        return [{"document": "a.pdf", "where": ["section", 2],
                 "text": PASSAGE}]

    def ask(parameter, passage):
        if parameter["uri"] == "staff":
            return None                     # a request that was not served
        return {"tuples": [{"value": "Riverside Housing Association",
                            "quote": "prepared by Riverside Housing "
                                     "Association in 2023"}]}

    monkeypatch.setattr(cli, "resolve_profile", lambda args: object())
    monkeypatch.setattr(cli, "_corpus", lambda args, profile: (find, ask))
    assert cli.main(["examples", str(draft_path)]) == 0
    assert "proposals for 1 of 2 parameter(s)" in capsys.readouterr().out
    held = examples.review_path(draft_path)
    review = json.loads(held.read_text(encoding="utf-8"))
    assert set(review["parameters"]) == {"publisher", "staff"}
    kept = review["parameters"]["publisher"]["proposals"]
    assert len(kept) == 1 and kept[0]["accept"] is False
    assert review["parameters"]["staff"]["proposals"] == []
    assert review["parameters"]["staff"]["dropped"] == {
        "reply:not_served": 1}

    # what a person accepted is kept by a second run, and not asked again
    review["parameters"]["publisher"]["proposals"][0]["accept"] = True
    review["parameters"]["publisher"]["note"] = "mine"
    held.write_text(json.dumps(review), encoding="utf-8")
    asked = []
    monkeypatch.setattr(cli, "_corpus", lambda args, profile: (
        find, lambda parameter, passage: asked.append(parameter["uri"])))
    assert cli.main(["examples", str(draft_path)]) == 0
    assert asked == ["staff"]
    again = json.loads(held.read_text(encoding="utf-8"))
    assert again["parameters"]["publisher"] == review["parameters"][
        "publisher"]
    assert "proposals for 0 of 1 parameter(s)" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_corpus", lambda args, profile: (find, ask))
    # the draft is a person's to change: proposing touches no byte of it
    assert draft_path.read_text(encoding="utf-8") == text
    # and the review goes where it was told to
    elsewhere = tmp_path / "sub.json"
    assert cli.main(["examples", str(draft_path), "--review",
                     str(elsewhere), "--only", "staff"]) == 0
    assert set(json.loads(elsewhere.read_text(encoding="utf-8"))[
        "parameters"]) == {"staff"}


def test_the_examples_step_asks_no_corpus_without_a_reason_or_a_profile(
        tmp_path, monkeypatch, capsys):
    def no_corpus(args, profile):
        raise AssertionError("a corpus was opened")

    monkeypatch.setattr(cli, "_corpus", no_corpus)
    done = tmp_path / "done.json"
    done.write_text(json.dumps({"parameters": [
        {**TEXT, "example": {"source": "x", "tuples": []}}]}),
        encoding="utf-8")
    assert cli.main(["examples", str(done)]) == 0
    assert "every parameter has an example" in capsys.readouterr().out
    assert not examples.review_path(done).exists()

    lacking = tmp_path / "lacking.json"
    lacking.write_text(json.dumps({"parameters": [dict(TEXT)]}),
                       encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_profile", lambda args: None)
    with pytest.raises(SystemExit) as caught:
        cli.main(["examples", str(lacking)])
    assert "--profile" in str(caught.value)
    assert not examples.review_path(lacking).exists()


def test_examples_are_applied_with_the_profile_they_were_proposed_with(
        tmp_path, monkeypatch):
    """A number is held to its quote the way the profile's documents write
    one. Applied without that profile, "3,251" would be read as 3.251 and
    the accepted example refused for a reason that is not its own."""
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps({"parameters": [dict(NUMBER)]}),
                          encoding="utf-8")
    examples.review_path(draft_path).write_text(json.dumps({
        "profile": "default", "parameters": {"staff": {"proposals": [{
            "accept": True, "source": PASSAGE,
            "tuples": [{"value": 3251, "unit": "persons",
                        "quote": "It employs 3,251 people"}]}]}}}),
        encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_profile", lambda args: None)
    with pytest.raises(SystemExit) as caught:
        cli.main(["apply", str(draft_path)])
    assert "--profile default" in str(caught.value)
    monkeypatch.setattr(cli, "resolve_profile", lambda args: NS(name="kwp"))
    with pytest.raises(SystemExit):
        cli.main(["apply", str(draft_path)])
    assert "example" not in json.loads(draft_path.read_text(
        encoding="utf-8"))["parameters"][0]


def test_the_command_reports_differences_and_touches_no_file(files, tmp_path,
                                                             capsys):
    spec_path = tmp_path / "spec.json"
    text = json.dumps(_hand_written())
    spec_path.write_text(text, encoding="utf-8")
    report = tmp_path / "diff.json"
    assert cli.main(["diff", "--shapes", str(files[0]), "--ontology",
                     str(files[1]), "--spec", str(spec_path),
                     "--json", str(report)]) == 0
    said = capsys.readouterr().out
    assert "list_missing (1)" in said and "nothing was changed" in said
    assert spec_path.read_text(encoding="utf-8") == text
    assert len(json.loads(report.read_text(encoding="utf-8"))[
        "differences"]) >= 8
    with pytest.raises(SystemExit):
        cli.main(["diff", "--shapes", str(tmp_path / "missing.ttl"),
                  "--spec", str(spec_path)])
