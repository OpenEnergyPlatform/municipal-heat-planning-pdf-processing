"""The option lists, held against the ontology they claim to come from.

Every closed list the model picks from names OEO terms, and each of those was
a hand-typed identifier next to a hand-typed German label. Nothing checked
that the identifier exists, that the term is still there, or that a carrier is
a carrier — and the ontology moves.

The snapshot is checked in; the 3.9 MB closure it was built from is not. So
these tests run against the snapshot, which is what every later check runs
against too.

No model, no GPU, no ontology file.
"""
import json
from pathlib import Path

import pytest

from profiles.kwp import vocabulary

SPEC_RAW = json.loads(vocabulary.SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot():
    return vocabulary.load()


def test_the_snapshot_names_the_ontology_it_was_built_from(snapshot):
    """"Which ontology is this spec written against" has to have an answer,
    or a list that drifted and a list that did not look the same."""
    pin = snapshot["pin"]
    assert pin["oeo_version_iri"].endswith("/releases/2.13.0/oeo.owl")
    assert len(pin["oeo_sha256"]) == 64
    assert int(pin["oeo_version_iri"].split("/releases/")[1].split("/")[0]
               .split(".")[0]) >= 2


def test_the_sets_are_the_ontologys_own_and_not_a_hand_list(snapshot):
    """A list is only checkable against a set, and the set has to be the
    ontology's: "district heat is not an energy carrier" is a fact of the
    closure and not an opinion of this profile."""
    sets = snapshot["sets"]
    assert len(sets["energy_carrier"]) == 124
    assert len(sets["sector"]) == 15
    assert sets["aggregation_type"] == ["OEO_00140069", "OEO_00140070",
                                        "OEO_00140071", "OEO_00140072",
                                        "OEO_00140073"]
    assert "OEO_00000292" in sets["energy_carrier"], "natural gas"
    assert "OEO_00000132" not in sets["energy_carrier"], "district heat"
    assert "OEO_00050008" in sets["energy_unit"], "megawatt-hour"
    assert "OEO_00010137" in sets["mass_unit"], "metric ton"
    for uri in ("OEO_00050016", "OEO_00050018", "OEO_00340066",
                "OEO_00140083"):
        assert uri in sets["quantity_value"], uri


def test_the_spec_passes_the_pinned_ontology(snapshot):
    assert vocabulary.check(SPEC_RAW, snapshot) == []


def test_every_identifier_of_a_covered_family_is_a_term_of_the_snapshot(
        snapshot):
    """Of a COVERED family. The walk used to look in three named places and
    missed the identifiers inside `kg` blocks; widened, it finds six MHPO
    classes as well, and MHPO ships only as OWL functional syntax, which
    rdflib does not read. Calling those "not in the pinned ontology" would be
    a false error, so they are a named gap instead."""
    from docpipe import ontology
    named = vocabulary.spec_terms(SPEC_RAW)
    assert len(named) >= 55, len(named)
    families = set(snapshot["pin"]["families"])
    for uri in named:
        if uri.split("_")[0] not in families:
            continue
        assert uri in snapshot["terms"], uri
        assert snapshot["terms"][uri]["label"], uri
    # And the gap is stated rather than passed over.
    assert set(ontology.uncovered(SPEC_RAW, snapshot)) == {"MHPO"}


def test_the_snapshot_carries_what_kind_of_thing_each_term_is(snapshot):
    """A `kg` block names PREDICATES. An index over classes and individuals
    alone reports every one of them as missing, which is why this profile's
    kg identifiers were never checked and the other profile had no snapshot at
    all."""
    kinds = {t["kind"] for t in snapshot["terms"].values()}
    assert "object_property" in kinds and "class" in kinds
    assert snapshot["terms"]["OEO_00000510"]["kind"] == "object_property"
    assert snapshot["terms"]["OEO_00030022"]["kind"] == "class"


@pytest.mark.parametrize("what,damage", [
    ("missing", "is not in the pinned ontology"),
    ("deprecated", "is deprecated"),
    ("carrier_undeclared", "is not declared in kg.outside_root"),
    ("carrier_over_declared", "does not belong in outside_root"),
    ("wrong_set", "is not a sector"),
])
def test_a_spec_the_ontology_disagrees_with_is_named(snapshot, what, damage):
    """Five ways a list can be wrong about the ontology, each named. A check
    that cannot fail is a check that says nothing."""
    spec = json.loads(json.dumps(SPEC_RAW))
    energy = spec["parameters"][0]
    if what == "missing":
        energy["axes"]["carrier"]["vocabulary"]["OEO_09999999"] = ["Erfundenes"]
    elif what == "deprecated":
        gone = next(uri for uri, term in snapshot["terms"].items()
                    if term["deprecated"])
        energy["axes"]["carrier"]["vocabulary"][gone] = ["Veraltetes"]
    elif what == "carrier_undeclared":
        # A real class, a real heat source, and nobody decided about it.
        energy["axes"]["carrier"]["vocabulary"]["OEO_00000350"] = ["Irgendwas"]
    elif what == "carrier_over_declared":
        energy["axes"]["carrier"]["kg"]["outside_root"]["OEO_00000292"] \
            = "gas"
    else:
        energy["axes"]["sector"]["vocabulary"]["OEO_00000292"] = ["Erdgas"]
    problems = vocabulary.check(spec, snapshot)
    assert any(damage in p for p in problems), problems


def test_a_corpus_label_is_listed_and_not_refused(snapshot):
    """The first label is what the model is offered, and it is meant to be
    the word a heat plan writes: a plan says "Private Haushalte", OEO says
    "household sector", and offering the ontology's word would ask the model
    to translate before it reads. Listed, because the same shape hides a real
    defect -- a specific German word on a generic class."""
    foreign = vocabulary.foreign_labels(SPEC_RAW, snapshot)
    offered = {uri: label for _where, uri, label, _own in foreign}
    assert offered["OEO_00000214"] == "Private Haushalte"
    assert "OEO_00000292" not in offered, "Erdgas IS the term's German label"
    assert 10 <= len(offered) <= 25, (
        "a list this long is worth a look; this one is a review item, not a "
        "runaway")


# The closure is 3.9 MB and belongs to the ontology repository, so it is not
# in here and the builder cannot be run against it in a test. This is the
# shape it has to get right, hand-written: a class under a root by assertion,
# and one under it only through the conjuncts of an equivalentClass.
TINY = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .

oeo:OEO_00020039 a owl:Class ; rdfs:label "energy carrier" .
oeo:OEO_00000292 a owl:Class ; rdfs:label "natural gas" ;
    rdfs:subClassOf oeo:OEO_00020039 ;
    obo:IAO_0000118 "Erdgas" ;
    obo:IAO_0000115 "Natural gas is a gas mixture." .
oeo:OEO_00000332 a owl:Class ; rdfs:label "biogenic solid fuel" ;
    owl:equivalentClass [ a owl:Class ; owl:intersectionOf (
        oeo:OEO_00020039 oeo:OEO_00000999 ) ] .
oeo:OEO_00000999 a owl:Class ; rdfs:label "biogenic" .
oeo:OEO_00000132 a owl:Class ; rdfs:label "district heat" .
"""


def test_a_class_that_is_a_carrier_only_by_equivalence_is_still_one(tmp_path):
    """OEO says "a biogenic solid fuel is an energy carrier AND biogenic" with
    an equivalentClass intersection, not with subClassOf. Reading only the
    asserted parents puts thirteen carriers the schema already accepts
    outside their own root, and every one of them would then be reported as
    an undeclared non-carrier."""
    pytest.importorskip("rdflib")   # absent on the cluster; the rest is not
    closure = tmp_path / "tiny.ttl"
    closure.write_text(TINY, encoding="utf-8")
    built = vocabulary.build(closure)
    carriers = set(built["sets"]["energy_carrier"])
    assert "OEO_00000292" in carriers, "asserted subClassOf"
    assert "OEO_00000332" in carriers, "a conjunct of an equivalentClass"
    assert "OEO_00000132" not in carriers, "district heat is under nothing"
    assert built["terms"]["OEO_00000292"]["alt_labels"] == ["Erdgas"]
    assert built["terms"]["OEO_00000292"]["definition"].startswith("Natural")
    assert built["pin"]["oeo_sha256"]
