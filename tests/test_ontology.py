"""The ontology snapshot, and the walk that decides what gets checked.

Every acceptance claim about a spec's identifiers rests on `spec_terms`
finding them. The version this replaces looked in three named places, matched
bare identifiers only, and returned ZERO for the scenarios spec — which reads
exactly like a spec with nothing wrong. So the walk is the first thing here.

No model, no ontology file, no rdflib: everything below runs against the two
checked-in snapshots, which is what lets these run on the cluster.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import ontology                                   # noqa: E402

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _spec(profile):
    return json.loads((PROFILES / profile / "extraction_spec.json")
                      .read_text(encoding="utf-8"))


def _snapshot(profile):
    return ontology.load(PROFILES / profile / "vocabulary.json")


# ---------------------------------------------------------------------------
# What counts as an identifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("OEO_00000510", "OEO_00000510"),
    ("https://openenergyplatform.org/ontology/oeo/OEO_00020309",
     "OEO_00020309"),
    ("http://purl.obolibrary.org/obo/BFO_0000050", "BFO_0000050"),
    ("obo:IAO_0000115#frag", None),
    ("out:not_in_list", None),
    ("out:potential", None),
    ("status_quo", None),
    ("abstract", None),
    # Prose that happens to name one. The plan's own note says "OEO files this
    # under dc:description instead of IAO_0000115" -- a sentence, not a term.
    ("OEO files this under dc:description instead of IAO_0000115.", None),
    (None, None),
    (42, None),
])
def test_an_identifier_is_recognised_in_either_spelling(value, expected):
    """kwp writes them bare, scenarios writes them as IRIs. Holding one of the
    two to the ontology and not the other is how a profile ends up with
    nothing checked at all."""
    assert ontology.identifier(value) == expected


def test_the_walk_finds_what_the_named_places_missed():
    """Measured: over the kwp spec the old three-place walk found 42 and this
    one finds 56; over the scenarios spec the old one found 0 and this one
    finds 32. The difference is the `kg` blocks, whose identifiers are
    predicates, and vocabulary KEYS spelled as full IRIs."""
    kwp = ontology.spec_terms(_spec("kwp"))
    scenarios = ontology.spec_terms(_spec("scenarios"))
    # 56 while three axes named three predicates; they name one now.
    assert len(kwp) >= 55 and len(scenarios) >= 32
    # In a kg block, as a value.
    assert "BFO_0000051" in kwp and "BFO_0000051" in scenarios
    assert "IAO_0000136" in kwp
    # As a vocabulary key spelled as an IRI.
    assert "OEO_00020309" in scenarios
    # And every one says where it was found.
    for named in (kwp, scenarios):
        for uri, wheres in named.items():
            assert wheres and all(isinstance(w, str) and w for w in wheres), uri


def test_the_walk_leaves_the_profiles_own_words_alone():
    """`out:` entries and axis keys like `status_quo` are the profile's own
    and neither is the ontology's to confirm."""
    named = ontology.spec_terms(_spec("kwp"))
    assert not [u for u in named if u.startswith("out:")]
    assert "status_quo" not in named and "target" not in named


# ---------------------------------------------------------------------------
# What the snapshots say
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", ["kwp", "scenarios"])
def test_the_checked_in_snapshot_answers_its_own_spec(profile):
    """The point of the file: run on a machine with no ontology and no rdflib
    and still be able to say whether the spec is written against the pin."""
    import importlib
    module = importlib.import_module(f"profiles.{profile}.vocabulary")
    assert module.check(_spec(profile), _snapshot(profile)) == []


@pytest.mark.parametrize("profile", ["kwp", "scenarios"])
def test_the_snapshot_says_which_ontology_and_which_families(profile):
    snapshot = _snapshot(profile)
    pin = snapshot["pin"]
    assert pin["oeo_version_iri"].endswith("/2.13.0/oeo.owl")
    assert len(pin["oeo_sha256"]) == 64
    # The families it can speak for at all. Without this a term of an
    # ontology no file here covers reads as a term the ontology does not have.
    assert "OEO" in pin["families"] and "MHPO" not in pin["families"]


def test_a_family_no_file_covers_is_named_and_not_called_an_error():
    """kwp's spec names six MHPO classes and MHPO ships only as OWL functional
    syntax, which rdflib does not read. Reporting them as missing would be a
    false error that teaches everyone to ignore the real ones; reporting
    nothing would let the gap grow."""
    spec, snapshot = _spec("kwp"), _snapshot("kwp")
    assert set(ontology.uncovered(spec, snapshot)) == {"MHPO"}
    assert len(ontology.uncovered(spec, snapshot)["MHPO"]) >= 6
    assert not [p for p in ontology.term_problems(spec, snapshot)
                if "MHPO" in p]


def test_a_term_of_a_covered_family_that_is_gone_is_an_error():
    """The other side of it: silence about MHPO must not become silence about
    OEO. A snapshot that covers a family owes an answer for every term of it.
    """
    spec, snapshot = _spec("kwp"), _snapshot("kwp")
    broken = json.loads(json.dumps(spec))
    broken["parameters"][0]["axes"]["carrier"]["vocabulary"]["OEO_99999999"] \
        = ["nichts"]
    problems = ontology.term_problems(broken, snapshot)
    assert any("OEO_99999999" in p and "not in the pinned ontology" in p
               for p in problems), problems


def test_a_class_written_where_a_predicate_belongs_is_reported():
    """A `kg` block says what a coordinate becomes in the graph. A class in
    the predicate slot emits Turtle that parses and asserts nonsense, and only
    an index that carries the kind can see it."""
    spec, snapshot = _spec("scenarios"), _snapshot("scenarios")
    assert ontology.kind_problems(spec, snapshot) == []
    broken = json.loads(json.dumps(spec))
    for parameter in broken["parameters"]:
        block = (parameter.get("kg") or {}).get("edge_from")
        if block:
            block["predicate"] = "OEO_00000364"      # scenario, a class
            break
    problems = ontology.kind_problems(broken, snapshot)
    assert any("is a class, not a property" in p for p in problems), problems


def test_the_scenarios_snapshot_pins_the_regions_it_offers():
    """The 249 study regions are individuals the OEKG mints, not terms of an
    ontology release, so they are pinned by their own list. `document_regions`
    filters that list per document: one silently disappearing would stop being
    offered for every publication that names it, and nothing else would say
    so."""
    from profiles.scenarios import vocabulary
    snapshot = _snapshot("scenarios")
    assert snapshot["pin"]["regions_count"] == 249
    assert len(snapshot["regions"]) == 249
    assert vocabulary.region_problems(snapshot) == []
    # A region the pin has and the file lost.
    lost = vocabulary.region_problems(snapshot,
                                      regions=snapshot["regions"][:-1])
    assert len(lost) == 1 and "was pinned and is gone" in lost[0], lost
    # And one the file grew without a rebuild.
    grown = vocabulary.region_problems(
        snapshot, regions=snapshot["regions"] + ["oekg/region/Atlantis"])
    assert len(grown) == 1 and "is new since the pin" in grown[0], grown


# ---------------------------------------------------------------------------
# What the ontology allows to be SAID
# ---------------------------------------------------------------------------

# A hand-built snapshot, so the shape of a failure is readable here rather
# than inferred from a real one. `value` is a continuant, `study` an
# occurrent, and the two are disjoint -- which is the real relation between
# OEO's quantity values and the domain of its `covers` predicates.
TOY = {
    "pin": {"families": ["BFO", "OEO"]},
    "disjoint": [["BFO_0000002", "BFO_0000003"]],
    "terms": {
        "BFO_0000002": {"kind": "class", "label": "continuant", "parents": []},
        "BFO_0000003": {"kind": "class", "label": "occurrent", "parents": []},
        "OEO_0000001": {"kind": "class", "label": "quantity value",
                        "parents": ["BFO_0000002"]},
        "OEO_0000002": {"kind": "class", "label": "energy consumption value",
                        "parents": ["OEO_0000001"]},
        "OEO_0000003": {"kind": "class", "label": "study",
                        "parents": ["BFO_0000003"]},
        "OEO_0000004": {"kind": "class", "label": "energy carrier",
                        "parents": ["BFO_0000002"]},
        "OEO_0000005": {"kind": "class", "label": "natural gas",
                        "parents": ["OEO_0000004"]},
        "OEO_0000006": {"kind": "class", "label": "sector",
                        "parents": ["BFO_0000002"]},
        "OEO_0000100": {"kind": "object_property", "label": "covers carrier",
                        "parents": [], "domain": ["OEO_0000003"],
                        "range": ["OEO_0000004"]},
        "OEO_0000101": {"kind": "object_property", "label": "is about",
                        "parents": [], "domain": ["OEO_0000001"],
                        "range": []},
        "OEO_0000102": {"kind": "data_property", "label": "has year",
                        "parents": [], "domain": ["OEO_0000001"],
                        "range": ["xsd:dateTime"]},
    },
}


def test_a_subject_the_predicates_domain_excludes_is_reported():
    """The check the profile did not have. `rdfs:domain` does not REFUSE a
    subject, it TYPES it, so a wrong domain fails nowhere and quietly asserts
    that our value nodes are something else."""
    edges = [{"where": "p.carrier", "subject": "OEO_0000002",
              "predicate": "OEO_0000100", "object": "OEO_0000005"}]
    problems = ontology.edge_problems(edges, TOY)
    assert len(problems) == 1, problems
    assert "OEO_0000003 (study)" in problems[0]
    assert "OEO_0000002" in problems[0]


def test_a_domain_the_subject_can_never_satisfy_says_so_in_other_words():
    """Not in the ontology's mouth and unsatisfiable are different findings:
    one emits a wrong triple, the other emits a graph no reasoner can hold.
    A report that spells them the same way ranks them the same way."""
    edges = [{"where": "p.carrier", "subject": "OEO_0000002",
              "predicate": "OEO_0000100"}]
    assert "disjoint" in ontology.edge_problems(edges, TOY)[0]
    # The same shape, one class higher up, where nothing is disjoint.
    close = json.loads(json.dumps(TOY))
    close["disjoint"] = []
    assert "disjoint" not in ontology.edge_problems(edges, close)[0]


def test_a_subject_under_the_domain_is_not_reported():
    """The check has to hold its tongue for the triples that are right, or it
    is a list nobody reads."""
    edges = [{"where": "p.about", "subject": "OEO_0000002",
              "predicate": "OEO_0000101", "object": "OEO_0000005"}]
    assert ontology.edge_problems(edges, TOY) == []


def test_an_object_outside_the_range_is_reported():
    edges = [{"where": "p.carrier", "subject": "OEO_0000003",
              "predicate": "OEO_0000100", "object": "OEO_0000006"}]
    problems = ontology.edge_problems(edges, TOY)
    assert len(problems) == 1 and "OEO_0000006" in problems[0]


def test_a_literal_written_with_another_datatype_is_reported():
    """Measured on the real spec: the year is written `xsd:integer` under a
    property whose declared range is `xsd:dateTime`, which is not a wrong
    label but an ill-typed literal."""
    edges = [{"where": "p.year", "subject": "OEO_0000002",
              "predicate": "OEO_0000102", "datatype": "xsd:integer"}]
    problems = ontology.edge_problems(edges, TOY)
    assert len(problems) == 1 and "xsd:dateTime" in problems[0]
    right = [{"where": "p.year", "subject": "OEO_0000002",
              "predicate": "OEO_0000102", "datatype": "xsd:dateTime"}]
    assert ontology.edge_problems(right, TOY) == []


def test_one_shape_is_one_line():
    """A domain complaint does not depend on the object, and the carrier axis
    offers forty of them. Repeated once per option it buries every other
    finding in the report."""
    edges = [{"where": "p.carrier", "subject": "OEO_0000002",
              "predicate": "OEO_0000100", "object": obj}
             for obj in ("OEO_0000005", "OEO_0000004")]
    assert len(ontology.edge_problems(edges, TOY)) == 1


def test_an_edge_that_says_why_it_is_written_anyway_is_not_a_problem():
    """Not every disagreement is ours to settle. The OEKG mints a uuid on
    every node it holds and `has uuid` is domained on `report or factsheet`,
    so one of our nodes is neither and the triple goes out regardless. The
    reason rides on the declaration rather than in a suppression list, so a
    SECOND divergence cannot hide behind the first: it is a new edge with no
    reason on it, and it fails."""
    edge = {"where": "kg.py", "subject": "OEO_0000002",
            "predicate": "OEO_0000100", "object": "OEO_0000005"}
    assert ontology.edge_problems([edge], TOY)
    assert ontology.edge_problems(
        [dict(edge, accepted="the OEKG writes it on every node")], TOY) == []
    # An empty reason is not a reason.
    assert ontology.edge_problems([dict(edge, accepted=None)], TOY)


def test_a_family_the_snapshot_does_not_cover_is_not_judged_here_either():
    """kwp hangs its value nodes off MHPO classes and MHPO is not in the
    snapshot. Guessing that a domain excludes them would be the same false
    alarm `uncovered` exists to prevent."""
    edges = [{"where": "kg.py plan", "subject": "MHPO_00020003",
              "predicate": "OEO_0000100", "object": "OEO_0000005"}]
    assert ontology.edge_problems(edges, TOY) == []


@pytest.mark.parametrize("profile,least", [("kwp", 100), ("scenarios", 15)])
def test_the_edges_come_out_of_the_spec_and_not_out_of_a_list(profile, least):
    """Both grammars: kwp hangs predicates off a value node whose class comes
    from an axis, scenarios hangs them off named nodes. A derivation that
    reads only one of them checks only one profile."""
    edges = ontology.spec_edges(_spec(profile))
    assert len(edges) >= least, len(edges)
    assert all(e["predicate"] for e in edges)
    assert all(e["where"] for e in edges)
    # Every subject that is named is a class of this profile's own spec.
    named = ontology.spec_terms(_spec(profile))
    assert {e["subject"] for e in edges if e["subject"]} <= set(named)


def test_an_option_the_spec_declares_edgeless_writes_no_triple():
    """An axis may say that one of its options gets no edge, and then that
    option must not be held to the predicate's range -- the report would say
    exactly what the declaration is there to state, once per option, in the
    profile that got it right. No shipped axis declares one today: the nine
    carriers that used to be edgeless keep their edge since the predicate
    became `is about`, which has no range to fall outside of."""
    spec = json.loads(json.dumps(_spec("kwp")))
    axis = spec["parameters"][0]["axes"]["carrier"]
    where = f"{spec['parameters'][0]['uri']}.carrier.kg"
    offered = sorted(axis["vocabulary"])[0]

    def objects():
        return {e["object"] for e in ontology.spec_edges(spec)
                if e["where"] == where}

    assert offered in objects()
    axis["kg"]["no_edge_for"] = {offered: "declared edgeless"}
    assert offered not in objects()


def test_a_minted_object_node_is_held_to_the_range_by_its_class():
    """The year is a node now, not a literal, and the axis names the class
    that node carries. Without reading it the edge would be checked against
    the axis' options, which are years and not ontology terms."""
    edges = [e for e in ontology.spec_edges(_spec("kwp"))
             if e["where"].endswith("year.kg")]
    assert edges and {e["object"] for e in edges} == {"OEO_00030033"}


@pytest.mark.parametrize("profile", ["kwp", "scenarios"])
def test_the_snapshot_carries_what_a_predicate_may_be_said_of(profile):
    """Without the domain and the range in the file the check above cannot
    run on the cluster, where there is no ontology and no rdflib."""
    snapshot = _snapshot(profile)
    properties = [t for t in snapshot["terms"].values()
                  if t["kind"].endswith("property")]
    assert properties
    assert all("domain" in t and "range" in t for t in properties)
    assert any(t["domain"] for t in properties)


def test_the_parent_chain_reaches_the_top_of_the_ontology():
    """One generation of parents is not enough to ask whether a subject is
    UNDER a domain: the domain is usually several steps up and is named
    nowhere in the spec, so without the closure it is not in the file."""
    snapshot = _snapshot("kwp")
    above = ontology.ancestors("OEO_00050016", snapshot)
    assert {"OEO_00000350", "IAO_0000030", "BFO_0000002"} <= above, above
    # And a class that is only ever a domain is in the file as well:
    # `is about` is domained on information content entity, which no list of
    # this profile offers.
    assert "IAO_0000030" in snapshot["terms"]
    assert ["BFO_0000002", "BFO_0000003"] in snapshot["disjoint"]


# ---------------------------------------------------------------------------
# The builder itself
# ---------------------------------------------------------------------------

TINY = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .
@prefix mhpo: <https://openenergyplatform.org/ontology/mhpo/> .

<https://openenergyplatform.org/ontology/oeo/> a owl:Ontology ;
    owl:versionIRI <https://openenergyplatform.org/ontology/oeo/releases/9.9.9/oeo.owl> .

obo:BFO_0000002 a owl:Class ; rdfs:label "continuant" ;
    owl:disjointWith obo:BFO_0000003 .
obo:BFO_0000003 a owl:Class ; rdfs:label "occurrent" .
oeo:OEO_00020039 a owl:Class ; rdfs:label "energy carrier" ;
    rdfs:subClassOf obo:BFO_0000002 .
oeo:OEO_00000292 a owl:Class ; rdfs:label "natural gas" ;
    rdfs:subClassOf oeo:OEO_00020039 ;
    obo:IAO_0000115 "Natural gas is a gas mixture." .
oeo:OEO_00020011 a owl:Class ; rdfs:label "study" ;
    rdfs:subClassOf obo:BFO_0000003 .
oeo:OEO_00000510 a owl:ObjectProperty ; rdfs:label "has organisation" ;
    rdfs:domain oeo:OEO_00020011 ; rdfs:range oeo:OEO_00020039 .
oeo:OEO_00390096 a owl:DatatypeProperty ; rdfs:label "has publication date" ;
    rdfs:range xsd:dateTime .
mhpo:MHPO_00020003 a owl:Class ; rdfs:label "municipal heat plan" .
"""


def _build_tiny(tmp_path, spec):
    pytest.importorskip("rdflib")   # absent on the cluster; the rest is not
    closure = tmp_path / "tiny.ttl"
    closure.write_text(TINY, encoding="utf-8")
    sets = {"energy_carrier": ("class", "https://openenergyplatform.org/"
                                        "ontology/oeo/OEO_00020039")}
    return ontology.build(closure, sets, spec,
                          base="https://openenergyplatform.org/ontology/oeo/")


def test_the_snapshot_carries_properties_and_not_only_classes(tmp_path):
    """A `kg` block names predicates and a predicate is an owl:ObjectProperty.
    An index over classes and individuals alone calls every one of them a term
    the ontology does not have -- which is why the scenarios profile, whose
    identifiers are mostly predicates, could not have a snapshot at all."""
    spec = {"parameters": [{"uri": "p", "kg": {
        "class": "OEO_00000292",
        "edge_from": {"predicate": "OEO_00000510"},
        "date": {"predicate": "OEO_00390096"}}}]}
    built = _build_tiny(tmp_path, spec)
    kinds = {k: v["kind"] for k, v in built["terms"].items()}
    assert kinds["OEO_00000292"] == "class"
    assert kinds["OEO_00000510"] == "object_property"
    assert kinds["OEO_00390096"] == "data_property"
    # And the kind is what lets the check tell them apart.
    assert ontology.kind_problems(spec, built) == []
    swapped = json.loads(json.dumps(spec))
    swapped["parameters"][0]["kg"]["edge_from"]["predicate"] = "OEO_00000292"
    assert any("is a class, not a property" in p
               for p in ontology.kind_problems(swapped, built))


def test_a_built_snapshot_carries_what_the_edge_check_needs(tmp_path):
    """Four things the checked-in files have and only the builder can put
    there, so a test that reads the files cannot notice their absence:
    a property's domain and range, a datatype range spelled apart from an
    ontology term, the parent chain closed to the top, and the classes that
    exclude each other. Without them `edge_problems` runs and finds nothing,
    which is the failure it exists to prevent."""
    spec = {"parameters": [{"uri": "p", "kg": {
        "class": "OEO_00000292",
        "edge_from": {"predicate": "OEO_00000510"},
        "date": {"predicate": "OEO_00390096"}}}]}
    built = _build_tiny(tmp_path, spec)
    assert built["terms"]["OEO_00000510"]["domain"] == ["OEO_00020011"]
    assert built["terms"]["OEO_00000510"]["range"] == ["OEO_00020039"]
    # `dateTime` alone would read like an ontology term and be looked for as
    # one; the range check tells classes and datatypes apart by this prefix.
    assert built["terms"]["OEO_00390096"]["range"] == ["xsd:dateTime"]
    # The domain class is named nowhere in the spec, and the chain above the
    # subject is two steps long. One generation of parents reaches neither.
    assert "OEO_00020011" in built["terms"]
    assert ontology.ancestors("OEO_00000292", built) == {"OEO_00020039",
                                                         "BFO_0000002"}
    assert ["BFO_0000002", "BFO_0000003"] in built["disjoint"]
    # And with all four, the check can say the strong thing.
    problems = ontology.edge_problems(
        [{"where": "p", "subject": "OEO_00000292",
          "predicate": "OEO_00000510", "object": "OEO_00000292"},
         {"where": "p.date", "subject": "OEO_00000292",
          "predicate": "OEO_00390096", "datatype": "xsd:date"}], built)
    assert len(problems) == 2, problems
    assert "disjoint" in problems[0]
    assert "xsd:dateTime" in problems[1]


def test_a_built_snapshot_names_the_families_it_can_speak_for(tmp_path):
    """Written by the builder, not carried forward: a snapshot that forgets
    this reverts silently to answering for families it never read, and the
    checked-in files would not show it."""
    spec = {"parameters": [{"uri": "p", "kg": {"class": "OEO_00000292"}}]}
    built = _build_tiny(tmp_path, spec)
    assert built["pin"]["families"] == ["BFO", "MHPO", "OEO"]
    assert built["pin"]["oeo_version_iri"].endswith("/9.9.9/oeo.owl")
    # A term of a family it DID read, and one it did not.
    covered = {"parameters": [{"uri": "p", "kg": {"class": "OEO_99999999"}}]}
    assert ontology.term_problems(covered, built)
    outside = {"parameters": [{"uri": "p", "kg": {"class": "UO_0000111"}}]}
    assert ontology.term_problems(outside, built) == []
    assert set(ontology.uncovered(outside, built)) == {"UO"}
