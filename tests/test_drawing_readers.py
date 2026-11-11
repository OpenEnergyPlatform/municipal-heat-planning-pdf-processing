"""What reads a field's or a coordinate's place in the graph reads the drawing
of the profile's graph file (`map` of graph.json), not a block of the spec
(owner decision 2026-11-11: the `kg` blocks left the specs).

The promises, each with a case that breaks it by construction:

1. A spec that still has a `kg` block, of a field or of a coordinate, is
   refused with its path, AND the same spec without it loads.
2. The published schema says of a field and of a coordinate the arrows of the
   drawing that read it (`x-kg`), AND says nothing of one no arrow reads, AND
   says nothing where no drawing is given.
3. The preflight's question "does the graph say what this field becomes" is
   answered by the drawing: a field no arrow, box or brick names is reported,
   a drawn one is not.
4. The organisations of a harvest census are the fields the drawing reads into
   a box of the organisation class, not the fields of a node of that name.
5. A carrier outside the energy carriers is declared where the drawing
   declares it (the settings of the arrow that reads the carrier), AND one
   declared there that is a carrier is reported.
6. A drafted spec carries no `kg` block, AND its graph is a drawing with an
   arrow from each field to the box of its shape.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

from docpipe.extraction import schema, spec as spec_module
from docpipe.extraction.graph import Drawing
from docpipe.extraction.preflight import silent_parameters

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PARAMETER = {
    "uri": "energy", "label": "Energieverbrauch",
    "description": "Eine Energiemenge, die der Plan für seine Gemeinde "
                   "bilanziert, je Energieträger und Jahr.",
    "value_type": "float", "unit_target": "OEO_00050008",
    "units_accepted": {"MWh": {"factor": 1.0, "names_period": False}},
    "axes": {
        "year": {"type": "int", "question": "Für welches Jahr gilt das?"},
        "carrier": {"required": False, "question": "Welcher Energieträger?",
                    "vocabulary": {
                        "OEO_00000292": {"label": "Erdgas",
                                         "spellings": ["Gas"]},
                        "OEO_00000132": {"label": "Fernwärme",
                                         "spellings": []}}},
        "what": {"type": "text", "required": False,
                 "question": "Welche Bezeichnung?"}},
    "example": {"source": "Im Jahr 2022 verbrauchte die Stadt 300 MWh "
                          "Erdgas für Wärme.",
                "tuples": [{"value": 300, "quote": "verbrauchte die Stadt "
                                                   "300 MWh Erdgas"}]}}
OFFICE = {
    "uri": "office", "label": "Planungsbüro", "value_type": "text",
    "description": "Das Büro, das den Plan im Auftrag der Gemeinde "
                   "geschrieben hat, wie der Plan es nennt.",
    "example": {"source": "Dieser Plan wurde erstellt von Planungsbüro Nord.",
                "tuples": [{"value": "Planungsbüro Nord",
                            "quote": "erstellt von Planungsbüro Nord"}]}}
SPEC = {"parameters": [PARAMETER, OFFICE]}

DRAWING = {
    "prefixes": {"oeo": "https://openenergyplatform.org/ontology/oeo/",
                 "rdfs": "http://www.w3.org/2000/01/rdf-schema#"},
    "boxes": [
        {"id": "value", "count": "per_value", "of": ["energy"],
         "address": {"brick": "value_identity"}},
        {"id": "organisation", "class": "oeo:OEO_00030022",
         "count": "per_distinct", "of": "office",
         "address": {"folder": "", "key": "organisation",
                     "from": ["@name"]}}],
    "arrows": [
        {"from": "value_target", "to": "value", "property": "oeo:OEO_00140178",
         "brick": "decimal"},
        {"from": "carrier", "to": "value", "property": "oeo:OEO_00370001",
         "brick": "answer_class",
         "settings": {"prefix": "oeo", "outside_root": {
             "OEO_00000132": "district heating"}}},
        {"from": "office", "to": "organisation", "property": "rdfs:label",
         "brick": "node_name"}]}


def raw(change=None) -> dict:
    data = copy.deepcopy(SPEC)
    if change:
        change(data)
    return data


# -- 1 ------------------------------------------------------------------------

@pytest.mark.parametrize("put,where", [
    (lambda d: d["parameters"][0].update(kg={"node": "value"}),
     "spec.parameters[0].kg"),
    (lambda d: d["parameters"][0]["axes"]["year"].update(kg={"role": "type"}),
     "spec.parameters[0].axes.year.kg")])
def test_a_spec_with_a_kg_block_is_refused_with_its_path(put, where):
    with pytest.raises(spec_module.SpecError) as refused:
        spec_module.load(raw(put))
    assert where in str(refused.value) and "graph.json" in str(refused.value)
    # the failure by construction: the same spec without the block loads
    assert spec_module.load(raw()).by_uri["energy"].axes["year"]


def test_the_profiles_specs_carry_no_kg_block():
    for name in ("kwp", "scenarios"):
        data = json.loads((ROOT / "profiles" / name / "extraction_spec.json")
                          .read_text(encoding="utf-8"))
        for parameter in data["parameters"]:
            assert "kg" not in parameter, (name, parameter["uri"])
            for axis, block in (parameter.get("axes") or {}).items():
                assert "kg" not in block, (name, parameter["uri"], axis)


# -- 2 ------------------------------------------------------------------------

def test_the_schema_lists_the_arrows_that_read_a_field_or_a_coordinate():
    spec = spec_module.load(raw())
    drawing = Drawing(DRAWING)
    energy = spec.by_uri["energy"]
    body = schema._tuple_schema(spec, energy, drawing)
    assert body["x-kg"] == [{"to": "value", "property": "oeo:OEO_00140178",
                             "brick": "decimal"}]
    assert body["properties"]["carrier"]["x-kg"] == [
        {"to": "value", "property": "oeo:OEO_00370001",
         "brick": "answer_class"}]
    # a coordinate no arrow reads says nothing
    assert "x-kg" not in body["properties"]["year"]
    assert "x-kg" not in body["properties"]["what"]
    # the class of the box it points at, where the box has one
    office = schema._tuple_schema(spec, spec.by_uri["office"], drawing)
    assert office["x-kg"] == [{"to": "organisation",
                               "class": "oeo:OEO_00030022",
                               "property": "rdfs:label",
                               "brick": "node_name"}]
    # the failure by construction: without a drawing nothing is said
    plain = schema._tuple_schema(spec, energy)
    assert "x-kg" not in plain
    assert not [key for key, one in plain["properties"].items()
                if "x-kg" in one]


def test_the_published_schemas_are_the_ones_the_drawings_make():
    from docpipe import graphfile
    from docpipe.profile import load_profile
    for name in ("kwp", "scenarios"):
        made = schema.build(
            spec_module.load(ROOT / "profiles" / name
                             / "extraction_spec.json"),
            Drawing(graphfile.load(load_profile(name)).map))
        written = (ROOT / "profiles" / name
                   / "extraction_schema.json").read_text(encoding="utf-8")
        assert written.replace("\r\n", "\n") == schema.serialize(made), name


# -- 3 ------------------------------------------------------------------------

def test_a_field_no_arrow_names_is_silent_and_a_drawn_one_is_not():
    drawing = Drawing(DRAWING)
    assert silent_parameters(SPEC, drawing) == []
    # the failure by construction: take the arrows of the office away
    bare = copy.deepcopy(DRAWING)
    bare["arrows"] = [one for one in bare["arrows"] if one["from"] != "office"]
    bare["boxes"][1].pop("of")
    assert silent_parameters(SPEC, Drawing(bare)) == ["office"]
    # and with no drawing at all every field is silent
    assert silent_parameters(SPEC, None) == ["energy", "office"]
    # a box that settles a coordinate by its wording names it
    only = {"boxes": [{"id": "value", "count": "per_value", "of": ["energy"],
                       "settle": {"wording": ["what"]}}], "arrows": []}
    said = Drawing(only).says()
    assert "what" in said and "year" not in said


# -- 4 ------------------------------------------------------------------------

def test_the_organisation_fields_are_those_read_into_an_office():
    import harvest_lists
    spec = spec_module.load(raw())
    assert [p.uri for p in harvest_lists.organisation_parameters(
        spec, DRAWING)] == ["office"]
    # the failure by construction: a drawing that reads nothing into a box of
    # that class has no organisation field
    moved = copy.deepcopy(DRAWING)
    moved["boxes"][1]["class"] = "oeo:OEO_00000064"
    assert harvest_lists.organisation_parameters(spec, moved) == []
    assert harvest_lists.organisation_parameters(spec, {}) == []



def test_the_organisation_key_is_the_fold_the_writer_mints_with():
    import harvest_lists
    from docpipe.extraction import graphkit
    drawing = {"legal_forms": "(gmbh|ag)", "boxes": [], "arrows": []}
    fold = harvest_lists.organisation_normaliser(drawing)
    assert fold("Stadtwerke Muster GmbH") == fold("stadtwerke  Muster")
    assert fold("Stadtwerke Muster AG") == graphkit.normalise(
        "Stadtwerke Muster", "(gmbh|ag)")
    # the failure by construction: another name keeps a key of its own,
    # and without a drawing there is nothing to group by
    assert fold("Stadtwerke Beispiel") != fold("Stadtwerke Muster")
    assert harvest_lists.organisation_normaliser({}) is None

# -- 5 ------------------------------------------------------------------------

def test_a_carrier_outside_the_carriers_is_declared_in_the_drawing():
    from profiles.kwp import vocabulary
    snapshot = {"terms": {"OEO_00000292": {"label": "natural gas"},
                          "OEO_00000132": {"label": "district heating"}},
                "sets": {"energy_carrier": ["OEO_00000292"]}}
    data = raw()
    assert vocabulary.carrier_problems(data, snapshot, DRAWING) == []
    # the failure by construction: undeclared, the district heat is named
    undeclared = copy.deepcopy(DRAWING)
    del undeclared["arrows"][1]["settings"]["outside_root"]
    said = vocabulary.carrier_problems(data, snapshot, undeclared)
    assert len(said) == 1 and "OEO_00000132" in said[0]
    # and a declared one that is a carrier does not belong there
    wrong = copy.deepcopy(DRAWING)
    wrong["arrows"][1]["settings"]["outside_root"]["OEO_00000292"] = "gas"
    said = vocabulary.carrier_problems(data, snapshot, wrong)
    assert len(said) == 1 and "OEO_00000292" in said[0]


# -- 6 ------------------------------------------------------------------------

def test_a_draft_has_no_kg_block_and_draws_an_arrow_per_field():
    pytest.importorskip("rdflib")
    from docpipe.compile import draft, shapes
    path = ROOT / "docpipe" / "builtin" / "default" / "shapes"
    found = sorted(path.glob("*.ttl")) if path.is_dir() else []
    if not found:
        from docpipe.compile import shapes as shape_files
        found = [shape_files.BUNDLED]
    read, prefixes = shapes.read(found)
    drafted = draft.draft(read, prefixes)
    assert drafted["parameters"]
    assert not [one for one in drafted["parameters"] if "kg" in one]
    drawn = drafted["graph"]["map"]
    boxes = {box["id"] for box in drawn["boxes"]}
    for parameter in drafted["parameters"]:
        arrows = [one for one in drawn["arrows"]
                  if one["from"] == parameter["uri"]]
        assert arrows and all(one["to"] in boxes for one in arrows), \
            parameter["uri"]
    # the spec made of the draft has no graph in it, the file has
    finished = draft.finished(drafted)
    assert "graph" not in finished and "kg" not in json.dumps(finished)
    assert draft.graph_file(drafted)["map"] == drawn
    # the failure by construction: a spec that kept a drafted block is refused
    kept = copy.deepcopy(finished)
    kept["parameters"][0]["kg"] = {"node": "x"}
    with pytest.raises(spec_module.SpecError):
        spec_module.load(kept)
