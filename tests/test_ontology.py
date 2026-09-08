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
    assert len(kwp) >= 56 and len(scenarios) >= 32
    # In a kg block, as a value.
    assert "BFO_0000051" in kwp and "BFO_0000051" in scenarios
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
# The builder itself
# ---------------------------------------------------------------------------

TINY = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .
@prefix mhpo: <https://openenergyplatform.org/ontology/mhpo/> .

<https://openenergyplatform.org/ontology/oeo/> a owl:Ontology ;
    owl:versionIRI <https://openenergyplatform.org/ontology/oeo/releases/9.9.9/oeo.owl> .

oeo:OEO_00020039 a owl:Class ; rdfs:label "energy carrier" .
oeo:OEO_00000292 a owl:Class ; rdfs:label "natural gas" ;
    rdfs:subClassOf oeo:OEO_00020039 ;
    obo:IAO_0000115 "Natural gas is a gas mixture." .
oeo:OEO_00000510 a owl:ObjectProperty ; rdfs:label "has organisation" .
oeo:OEO_00390096 a owl:DatatypeProperty ; rdfs:label "has publication date" .
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


def test_a_built_snapshot_names_the_families_it_can_speak_for(tmp_path):
    """Written by the builder, not carried forward: a snapshot that forgets
    this reverts silently to answering for families it never read, and the
    checked-in files would not show it."""
    spec = {"parameters": [{"uri": "p", "kg": {"class": "OEO_00000292"}}]}
    built = _build_tiny(tmp_path, spec)
    assert built["pin"]["families"] == ["MHPO", "OEO"]
    assert built["pin"]["oeo_version_iri"].endswith("/9.9.9/oeo.owl")
    # A term of a family it DID read, and one it did not.
    covered = {"parameters": [{"uri": "p", "kg": {"class": "OEO_99999999"}}]}
    assert ontology.term_problems(covered, built)
    outside = {"parameters": [{"uri": "p", "kg": {"class": "UO_0000111"}}]}
    assert ontology.term_problems(outside, built) == []
    assert set(ontology.uncovered(outside, built)) == {"UO"}
