"""The unit of a number, as far as the shapes and the ontology say it.

Promised: the compiler names the unit family an ontology gives a quantity's
class, and the units of that family, in the draft AND in `docpipe compile
check`, as a suggestion that decides nothing (the author still writes
`unit_target`, `units_accepted` and the factors, and the finished spec carries
none of it); the units a shape itself lists hang on its number instead of
becoming a category parameter of their own; and a class that has no unit
statement at all gets no suggestion, in a line that reads as it did before.
"""
import json

import pytest

pytest.importorskip("rdflib")

from docpipe.compile import cli, draft, shapes  # noqa: E402
from docpipe.compile.terms import Terms, says_unit  # noqa: E402

PREFIXES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix oeo: <http://openenergyplatform.org/ontology/oeo/> .
@prefix ex: <http://example.org/shapes/> .
@prefix v: <http://example.org/vocab/> .
"""

ONTOLOGY = PREFIXES + """
oeo:OEO_00040010 a owl:ObjectProperty ; rdfs:label "has unit" .

v:EnergyUnit rdfs:label "energy unit" .
v:KWh rdfs:subClassOf v:EnergyUnit ; rdfs:label "kilowatt hour" ;
    skos:altLabel "kWh" .
v:MWh rdfs:subClassOf v:EnergyUnit ; rdfs:label "megawatt hour" ;
    skos:altLabel "MWh" .
v:Joule a v:EnergyUnit ; rdfs:label "joule" .
v:MassUnit rdfs:label "mass unit" .
v:Tonne rdfs:subClassOf v:MassUnit ; rdfs:label "tonne" ; skos:altLabel "t" .

v:EnergyValue rdfs:label "energy value" ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty oeo:OEO_00040010 ;
                      owl:someValuesFrom v:EnergyUnit ] .
v:FinalEnergyValue rdfs:label "final energy value" ;
    rdfs:subClassOf v:EnergyValue .
v:EmissionValue rdfs:label "emission value" ;
    owl:equivalentClass [ owl:intersectionOf ( v:Quantity
        [ a owl:Restriction ; owl:onProperty oeo:OEO_00040010 ;
          owl:someValuesFrom v:MassUnit ] ) ] .
v:Cost rdfs:label "cost" .
v:Stray rdfs:label "stray" ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty v:hasColour ;
                      owl:someValuesFrom v:Colour ] .
"""

SHAPES = PREFIXES + """
ex:FinalEnergyShape a sh:NodeShape ; sh:targetClass v:FinalEnergyValue ;
    sh:property [ sh:path v:numericValue ; sh:datatype xsd:decimal ;
                  sh:name "amount" ;
                  sh:description "The amount of final energy the plan states." ] ;
    sh:property [ sh:path oeo:OEO_00040010 ; sh:in ( v:KWh v:MWh ) ] ;
    sh:property [ sh:path v:status ; sh:in ( "draft" "final" ) ] .

ex:EmissionShape a sh:NodeShape ; sh:targetClass v:EmissionValue ;
    sh:property [ sh:path v:numericValue ; sh:datatype xsd:decimal ;
                  sh:name "amount" ;
                  sh:description "The amount of emissions the plan states." ] .

ex:CostShape a sh:NodeShape ; sh:targetClass v:Cost ;
    sh:property [ sh:path v:numericValue ; sh:datatype xsd:decimal ;
                  sh:name "amount" ;
                  sh:description "The cost the plan states for the measure." ] .

ex:StrayShape a sh:NodeShape ; sh:targetClass v:Stray ;
    sh:property [ sh:path v:numericValue ; sh:datatype xsd:decimal ;
                  sh:name "amount" ;
                  sh:description "The amount the plan states for the stray." ] .

ex:HolderShape a sh:NodeShape ; sh:targetClass v:Holder ;
    sh:property [ sh:path oeo:OEO_00040010 ; sh:in ( v:KWh v:MWh ) ] .
"""

OPEN_LINE = ("unit_target, units_accepted: name the unit the number is kept "
             "in and the units a document may state it in, each with its "
             "factor and, unless the number is a rate (integrated: false), "
             "whether it names a period (names_period)")


@pytest.fixture
def files(tmp_path):
    one, two = tmp_path / "shapes.ttl", tmp_path / "onto.ttl"
    one.write_text(SHAPES, encoding="utf-8")
    two.write_text(ONTOLOGY, encoding="utf-8")
    return one, two


@pytest.fixture
def drafted(files):
    found, prefixes = shapes.read([files[0]])
    return draft.draft(found, prefixes, Terms.read([files[1]]))


def _by_uri(raw):
    return {parameter["uri"]: parameter for parameter in raw["parameters"]}


def _line(raw, name):
    """The open point of one number's unit, or None."""
    wanted = f"{name}.{OPEN_LINE.split(':')[0]}:"
    return next((line for line in draft.todo(raw)
                 if line.startswith(wanted)), None)


# ---- what the ontology says about a class -------------------------------------

def test_a_class_has_the_unit_family_its_own_statement_or_the_one_above_gives(
        files):
    terms = Terms.read([files[1]])
    name = "http://example.org/vocab/"
    assert terms.unit_families(name + "EnergyValue") == [
        {"family": name + "EnergyUnit", "stated_on": name + "EnergyValue"}]
    # no statement of its own: the nearest one above is taken, and said
    assert terms.unit_families(name + "FinalEnergyValue") == [
        {"family": name + "EnergyUnit", "stated_on": name + "EnergyValue"}]
    # inside an intersection that defines the class
    assert terms.unit_families(name + "EmissionValue") == [
        {"family": name + "MassUnit", "stated_on": name + "EmissionValue"}]
    # the units: a class below the family, and a named thing of the family
    assert terms.units(name + "EnergyUnit") == [
        name + "Joule", name + "KWh", name + "MWh"]


def test_a_class_that_says_nothing_about_a_unit_has_no_family(files):
    terms = Terms.read([files[1]])
    name = "http://example.org/vocab/"
    # no statement at all, and one about another property: none of them is
    # read as a unit
    assert terms.unit_families(name + "Cost") == []
    assert terms.unit_families(name + "Stray") == []
    assert terms.unit_families(name + "NotInTheFiles") == []
    assert Terms().unit_families(name + "EnergyValue") == []
    assert Terms().units(name + "EnergyUnit") == []
    # the property is what is read: named, another one is read in its place
    assert terms.unit_families(name + "Stray", ("hasColour",)) == [
        {"family": name + "Colour", "stated_on": name + "Stray"}]
    assert terms.unit_families(name + "EnergyValue", ("hasColour",)) == []


def test_the_property_that_names_a_unit_is_known_by_the_end_of_its_iri():
    assert says_unit("http://openenergyplatform.org/ontology/oeo/OEO_00040010")
    assert says_unit("https://openenergyplatform.org/ontology/oeo/"
                     "OEO_00040010")
    assert not says_unit("http://example.org/vocab/hasColour")
    assert not says_unit("http://openenergyplatform.org/ontology/oeo/"
                         "OEO_00040011")


# ---- the draft ----------------------------------------------------------------

def test_the_draft_names_the_family_and_its_units_and_decides_nothing(drafted):
    amount = _by_uri(drafted)["final_energy_amount"]
    [family] = amount["_drafted"]["unit_families"]
    assert (family["family"], family["stated_on"]) == (
        "energy unit", "energy value")
    assert [(unit["label"], unit.get("spellings"))
            for unit in family["units"]] == [
        ("joule", None), ("kilowatt hour", ["kWh"]),
        ("megawatt hour", ["MWh"])]
    # a suggestion: the number's unit is as open as it was
    assert amount["unit_target"] is None and amount["units_accepted"] == {}
    line = _line(drafted, "final_energy_amount")
    assert line is not None and line.startswith(
        "final_energy_amount." + OPEN_LINE)
    assert "Suggestion, not decided" in line
    assert "energy unit" in line and "kilowatt hour (kWh)" in line
    assert "3 unit(s)" in line
    # the emission value is defined with its own, inside an intersection
    assert "mass unit" in _line(drafted, "emission_amount")


def test_a_suggestion_is_no_part_of_the_spec_and_settles_no_point(drafted):
    finished = draft.finished(drafted)
    for text in ("unit_families", "units_listed"):
        assert text not in json.dumps(finished)
    number = _by_uri(finished)["final_energy_amount"]
    assert "kilowatt hour" not in json.dumps(number)
    assert number["units_accepted"] == {}
    # only what the author writes closes the point
    amount = _by_uri(drafted)["final_energy_amount"]
    amount["unit_target"] = "kWh"
    assert _line(drafted, "final_energy_amount") is not None
    amount["units_accepted"] = {"kWh": 1}
    assert _line(drafted, "final_energy_amount") is None


def test_a_long_family_is_cut_in_the_line_and_whole_in_the_draft(drafted):
    amount = _by_uri(drafted)["final_energy_amount"]
    amount["_drafted"]["unit_families"][0]["units"] = [
        {"label": f"unit {number}"} for number in range(12)]
    line = _line(drafted, "final_energy_amount")
    assert "12 unit(s): unit 0" in line and "unit 7" in line
    assert "unit 8" not in line and "and 4 more" in line
    assert len(amount["_drafted"]["unit_families"][0]["units"]) == 12


def test_a_class_without_a_unit_statement_is_drafted_as_it_was(drafted, files):
    expected = "cost_amount." + OPEN_LINE
    for name in ("cost_amount", "stray_amount"):
        assert "unit_families" not in _by_uri(drafted)[name]["_drafted"]
        assert "units_listed" not in _by_uri(drafted)[name]["_drafted"]
    assert _line(drafted, "cost_amount") == expected
    assert _line(drafted, "stray_amount") == "stray_amount." + OPEN_LINE
    # and without any ontology there is nothing to suggest anywhere
    found, prefixes = shapes.read([files[0]])
    bare = draft.draft(found, prefixes)
    for parameter in bare["parameters"]:
        assert "unit_families" not in parameter["_drafted"]
    assert _line(bare, "final_energy_amount") is not None
    assert "Suggestion" not in _line(bare, "emission_amount")


def test_the_units_a_shape_lists_hang_on_its_number(drafted, files):
    by_uri = _by_uri(drafted)
    # no parameter of its own for the has-unit property of that shape
    assert not [uri for uri in by_uri if uri.startswith("final_energy")
                and ("has_unit" in uri or "00040010" in uri)]
    amount = by_uri["final_energy_amount"]
    assert [unit["label"] for unit in amount["_drafted"]["units_listed"]] == [
        "kilowatt hour", "megawatt hour"]
    assert "the shape lists 2 unit(s): kilowatt hour (kWh), megawatt hour " \
        "(MWh)" in _line(drafted, "final_energy_amount")
    assert any("final_energy: the units listed under OEO_00040010 hang on "
               "final_energy_amount" in note for note in drafted["_notes"])
    # a list that is not a unit list is still a parameter of its own
    assert by_uri["final_energy_status"]["value_type"] == "category"
    # the shapes' own words where no ontology gives the labels
    found, prefixes = shapes.read([files[0]])
    bare = draft.draft(found, prefixes)
    assert [unit["label"] for unit in _by_uri(bare)["final_energy_amount"][
        "_drafted"]["units_listed"]] == ["KWh", "MWh"]


def test_a_list_is_a_list_of_units_only_by_its_property_and_beside_a_number(
        files):
    found, _prefixes = shapes.read([files[0]])
    by_name = {shape.name: shape for shape in found}
    listing, numbers = draft.unit_listing(by_name["final_energy"])
    assert [draft.local(prop.path) for prop in listing] == ["OEO_00040010"]
    assert [draft.local(prop.path) for prop in numbers] == ["numericValue"]
    # which property is the unit's is what is asked for, not a property that
    # happens to have a list
    listing, _numbers = draft.unit_listing(by_name["final_energy"],
                                           ("status",))
    assert [draft.local(prop.path) for prop in listing] == ["status"]
    # and a list with no number beside it hangs on nothing
    assert draft.unit_listing(by_name["holder"]) == ([], [])
    # a number with no list beside it
    listing, numbers = draft.unit_listing(by_name["cost"])
    assert listing == [] and len(numbers) == 1
    # and a unit property named some other way is no unit list
    assert draft.unit_listing(by_name["final_energy"], ("hasColour",))[0] == []


def test_a_unit_list_with_no_number_beside_it_stays_a_parameter(drafted):
    held = _by_uri(drafted)["holder_has_unit"]
    assert held["value_type"] == "category"
    assert len(held["vocabulary"]) == 2
    assert not any(note.startswith("holder:") for note in
                   drafted.get("_notes") or ())


def test_the_units_of_a_list_of_words_hang_on_the_number_as_they_are_written(
        tmp_path):
    one = tmp_path / "shapes.ttl"
    one.write_text(PREFIXES + """
ex:AmountShape a sh:NodeShape ; sh:targetClass v:Cost ;
    sh:property [ sh:path v:numericValue ; sh:datatype xsd:integer ] ;
    sh:property [ sh:path oeo:OEO_00040010 ; sh:in ( "MWh" "kWh" ) ] .
""", encoding="utf-8")
    found, prefixes = shapes.read([one])
    raw = draft.draft(found, prefixes)
    [parameter] = raw["parameters"]
    assert parameter["_drafted"]["units_listed"] == [
        {"label": "MWh"}, {"label": "kWh"}]


# ---- the command --------------------------------------------------------------

def test_check_says_the_family_and_that_it_is_a_suggestion(files, tmp_path,
                                                           capsys):
    out = tmp_path / "draft.json"
    assert cli.main(["spec", "--shapes", str(files[0]), "--ontology",
                     str(files[1]), "--out", str(out)]) == 0
    said = capsys.readouterr().out
    assert "hang on final_energy_amount" in said
    assert cli.main(["check", str(out)]) == 1
    listed = capsys.readouterr().out
    assert "final_energy_amount.unit_target, units_accepted" in listed
    assert "Suggestion, not decided: the shape lists 2 unit(s)" in listed
    assert "the ontology gives 'energy value' the unit family 'energy unit'" \
        in listed
    # the class without a statement has the line it always had
    assert "cost_amount." + OPEN_LINE + "\n" in listed


def test_a_hand_edited_suggestion_does_not_stop_check(drafted, tmp_path,
                                                      capsys):
    amount = _by_uri(drafted)["final_energy_amount"]
    amount["_drafted"]["units_listed"] = [{"iri": "x"}, {}]
    amount["_drafted"]["unit_families"] = [{"units": [{"label": "a"}]}]
    out = tmp_path / "draft.json"
    out.write_text(json.dumps(drafted), encoding="utf-8")
    assert cli.main(["check", str(out)]) == 1
    assert "final_energy_amount.unit_target" in capsys.readouterr().out


# ---- a spec held against the shapes -------------------------------------------

def test_a_spec_that_asks_for_the_number_answers_the_units_the_shape_lists(
        files):
    found, prefixes = shapes.read([files[0]])
    terms = Terms.read([files[1]])
    drafted = draft.finished(draft.draft(found, prefixes, terms))
    assert draft.differences(found, drafted, terms) == []

    # without the number the spec does not ask for the units either: both
    # are said, and so is the list that stands alone
    drafted["parameters"] = [
        parameter for parameter in drafted["parameters"]
        if parameter["uri"] != "final_energy_amount"]
    rows = draft.differences(found, drafted, terms)
    unasked = {(row["detail"].split(":")[0], row["path"]) for row in rows
               if row["kind"] == "not_asked"}
    assert ("final_energy", "numericValue") in unasked
    assert ("final_energy", "OEO_00040010") in unasked
