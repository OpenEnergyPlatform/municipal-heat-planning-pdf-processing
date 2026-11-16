"""
test_editor_graph_demands.py: what the Graph tab of `docpipe edit` marks as
demanded by the shapes (docpipe/editor/graphpage.py `classes`, and the rows
of a box, docpipe/editor/ui/src/graph/rows.ts), since the OEKG's shapes
demand of a scenario bundle a name or an acronym (an sh:or on the node)
instead of each of them.

The promise, in one sentence: the tab marks as demanded a property the
shapes require on its own AND each property of a group one of which an sh:or
on the node requires; a group is met by an arrow, or the box's own number,
to any one of its properties, its properties are red while none is, AND an
unmet group counts once among what is missing, AND all of it follows the
drawing as it is edited, not as the page loaded it; the box lists that sh:or
under the key the validation reports it with, AND with the effect the graph
file sets for that key, which the written graph then gets. Each part has a
case that breaks it by construction.

The rows are the page's own TypeScript, run by node with its types
stripped; those tests are skipped where node cannot do that.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("rdflib")

from docpipe import graphfile                                   # noqa: E402
from docpipe.compile import shapes as shapes_module             # noqa: E402
from docpipe.editor import graphpage                            # noqa: E402
from docpipe.profile import load_profile                         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_graph_demands_driver.mjs"
NODE = shutil.which("node")
OEO = "https://openenergyplatform.org/ontology/oeo/"
BUNDLE = "OEO_00020227"
DIVISION = "OEO_00390079"
OR_KEY = f"Or - {BUNDLE}"
HEAD = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dc: <http://purl.org/dc/terms/> .
@prefix oeo: <https://openenergyplatform.org/ontology/oeo/> .
@prefix ex: <http://example.org/> .
"""
EITHER = ("sh:or ( [ sh:path rdfs:label ; sh:minCount 1 ] "
          "[ sh:path dc:acronym ; sh:minCount 1 ] )")


def bundle(node: str = EITHER, name: str = "StudyShape") -> str:
    """A bundle's shape as the OEKG says it since its PR 68: a name and an
    acronym at most once each, a sector division required on its own, and
    *node* said of the node itself."""
    return f"""ex:{name} a sh:NodeShape ;
  sh:targetClass oeo:{BUNDLE} ;
  sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ;
                sh:maxCount 1 ] ;
  sh:property [ sh:path dc:acronym ; sh:datatype xsd:string ;
                sh:maxCount 1 ] ;
  sh:property [ sh:path oeo:{DIVISION} ; sh:minCount 1 ] {";" if node else ""}
  {node} .
"""


@pytest.fixture(scope="module")
def profile():
    return load_profile("scenarios")


@pytest.fixture(scope="module")
def made(profile):
    return graphfile.load(profile, environ={})


def shapes_file(tmp_path: Path, *bodies: str) -> Path:
    path = tmp_path / "shapes.ttl"
    path.write_text(HEAD + "\n".join(bodies), encoding="utf-8")
    return path


def bundle_class(profile, made, path: Path) -> dict:
    """The scenario bundle as the Graph tab gets it from *path*."""
    found = graphpage.classes(profile, made, None, [path], None,
                              made.map.get("prefixes"))
    return next(one for one in found["classes"] if one["id"] == BUNDLE)


# -- the server: the groups and the constraint of the node -------------------

def test_a_class_gets_the_groups_one_of_which_its_shapes_demand(
        profile, made, tmp_path):
    study = bundle_class(profile, made, shapes_file(tmp_path, bundle()))
    assert study["one_of"] == [["dc:acronym", "rdfs:label"]]
    by_path = {one["path"]: one for one in study["properties"]}
    assert (by_path["label"]["min"], by_path["acronym"]["min"]) == (None,
                                                                     None)
    # the failure by construction: the same shapes without the sh:or demand
    # neither, and the class has no group
    plain = bundle_class(profile, made, shapes_file(tmp_path, bundle("")))
    assert plain["one_of"] == [] and plain["constraints"] == []


def test_two_shapes_of_a_class_saying_one_sh_or_give_one_group(
        profile, made, tmp_path):
    path = shapes_file(tmp_path, bundle(), bundle(name="MoreStudyShape"))
    study = bundle_class(profile, made, path)
    assert study["one_of"] == [["dc:acronym", "rdfs:label"]]
    assert [one["key"] for one in study["constraints"]] == [OR_KEY]
    # the failure by construction: read shape by shape, it is two groups
    found, _prefixes = shapes_module.read([path])
    assert sum(len(shape.one_of) for shape in found) == 2


def written(tmp_path: Path, says: str) -> Path:
    """A written graph: one bundle that *says* what is given, with its
    sector division."""
    path = tmp_path / "graph.ttl"
    path.write_text(HEAD + f"ex:b a oeo:{BUNDLE} ; oeo:{DIVISION} ex:d"
                    f"{' ; ' + says if says else ''} .\n"
                    "ex:r a ex:Report ; rdfs:label \"kept\" .\n",
                    encoding="utf-8")
    return path


def test_the_box_lists_the_or_under_the_key_the_validation_reports(
        profile, made, tmp_path):
    path = shapes_file(tmp_path, bundle())
    (said,) = bundle_class(profile, made, path)["constraints"]
    assert said["component"] == "Or"
    assert said["says"] == [["acronym", "label"]]
    unnamed = written(tmp_path, "").read_text(encoding="utf-8")
    keys = {key for key, _focus in graphfile.violations(unnamed, [path])}
    assert said["key"] in keys
    # the failure by construction: a bundle with an acronym is not reported
    # under that key, and the key made like a property's is never reported
    named = written(tmp_path, 'dc:acronym "S"').read_text(encoding="utf-8")
    assert said["key"] not in {key for key, _focus in
                               graphfile.violations(named, [path])}
    assert not keys & {f"Or label {BUNDLE}", f"Or acronym {BUNDLE}"}


def test_the_effect_the_file_sets_for_the_key_is_shown_and_done(
        profile, made, tmp_path):
    path = shapes_file(tmp_path, bundle())
    # nothing else of the file acts on the written graph
    setting = dataclasses.replace(made, classes={},
                                  constraints={OR_KEY: "leave_out_value"})
    (said,) = bundle_class(profile, setting, path)["constraints"]
    assert said["effect"] == "leave_out_value"
    # a file the page saves with that key is read
    assert graphfile.parse(json.dumps({"constraints": {OR_KEY: "stop"}}),
                           "page")["constraints"] == {OR_KEY: "stop"}
    # the written graph gets the effect: the bundle without a name or an
    # acronym leaves it, the rest stays
    graph = written(tmp_path, "")
    report = graphfile.finish(graph, setting, "http://example.org/", [path])
    assert [one["constraint"] for one in report["left_out"]] == [OR_KEY]
    text = graph.read_text(encoding="utf-8")
    assert "kept" in text and BUNDLE not in text
    # the failures by construction: an effect set under a property's key is
    # not the effect of the sh:or, and a bundle with a name stays
    other = dataclasses.replace(
        setting, constraints={f"MinCount label {BUNDLE}": "leave_out_value"})
    assert bundle_class(profile, other, path)["constraints"][0]["effect"] \
        == "report"
    graph = written(tmp_path, 'rdfs:label "A Study"')
    assert graphfile.finish(graph, setting, "http://example.org/",
                            [path])["left_out"] == []
    assert BUNDLE in graph.read_text(encoding="utf-8")


# -- the page: the rows of the bundle box -------------------------------------

def _strips_types() -> bool:
    if NODE is None:
        return False
    done = subprocess.run([NODE, "-p", "process.features.typescript"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() in ("strip",
                                                            "transform")


needs_node = pytest.mark.skipif(not _strips_types(),
                                reason="no node that strips TypeScript types")


def run(jobs: list) -> list:
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def rows(classes: list, *drawings: dict) -> list:
    """What the page makes of the bundle box of each drawing."""
    return run([{"op": "rows", "classes": classes, "map": one,
                 "box": "bundle"} for one in drawings])


@pytest.fixture
def page(profile, made, tmp_path):
    """The classes as the server sends them for the shapes of the bundle,
    and the scenarios drawing."""
    found = graphpage.classes(profile, made, None,
                              [shapes_file(tmp_path, bundle())], None,
                              made.map.get("prefixes"))
    return found["classes"], copy.deepcopy(made.map)


def without(drawing: dict, *properties: str, box: str = "bundle") -> dict:
    """*drawing* without the arrows that write *properties* on *box*."""
    out = copy.deepcopy(drawing)
    out["arrows"] = [a for a in out["arrows"]
                     if not (a["to"] == box and a["property"] in properties)]
    assert len(out["arrows"]) == len(drawing["arrows"]) - len(properties)
    return out


@needs_node
def test_a_group_is_met_by_an_arrow_to_any_one_of_its_properties(page):
    classes, drawing = page
    own = without(drawing, "rdfs:label", "dc:acronym")
    own["boxes"] = [dict(b, uuid="rdfs:label") if b["id"] == "bundle" else b
                    for b in own["boxes"]]
    both, acronym, label, number = rows(
        classes, drawing, without(drawing, "rdfs:label"),
        without(drawing, "dc:acronym"), own)
    for one in (both, acronym, label, number):
        for name in ("label", "acronym"):
            row = one["rows"][name]
            assert row["demanded"] and not row["required"]
            assert row["groups"][0]["met"] and not row["red"]
        assert one["missing"] == 0


@needs_node
def test_without_a_way_to_any_the_group_is_red_and_counts_once(page):
    classes, drawing = page
    (none,) = rows(classes, without(drawing, "rdfs:label", "dc:acronym"))
    for name in ("label", "acronym"):
        assert none["rows"][name]["red"]
        assert none["rows"][name]["groups"][0]["met"] is False
    assert none["missing"] == 1
    # the failure by construction: counted row by row, one demand is two
    assert none["red_rows"] == 2


@needs_node
def test_a_property_required_on_its_own_counts_beside_the_group(page):
    classes, drawing = page
    division = f"oeo:{DIVISION}"
    alone, all_three = rows(
        classes, without(drawing, division),
        without(drawing, division, "rdfs:label", "dc:acronym"))
    row = alone["rows"][DIVISION]
    assert row["required"] and row["red"] and row["groups"] == []
    assert alone["missing"] == 1
    assert all_three["missing"] == 2


@needs_node
def test_the_group_names_its_properties_as_their_rows_do(page):
    classes, drawing = page
    study = next(one for one in classes if one["id"] == BUNDLE)
    named = {one["path"]: one["label"] for one in study["properties"]}
    (one,) = rows(classes, drawing)
    assert one["rows"]["label"]["groups"][0]["labels"] == [
        named["acronym"], named["label"]]
    # a property of a group that is no row is named by its own name
    odd = copy.deepcopy(classes)
    next(c for c in odd if c["id"] == BUNDLE)["one_of"] = [
        ["dc:acronym", "ex:nick"]]
    (two,) = rows(odd, drawing)
    assert two["rows"]["acronym"]["groups"][0]["labels"] == [
        named["acronym"], "nick"]


@needs_node
def test_the_marks_follow_the_drawing_as_edited_not_as_loaded(page):
    classes, drawing = page
    edited = without(drawing, "rdfs:label", "dc:acronym")

    def job(now: dict, loaded: dict, broken=None) -> dict:
        return {"op": "rows", "classes": classes, "map": now,
                "loaded": loaded, "box": "bundle", "broken": broken}

    taken, drawn, stale = run([job(edited, drawing), job(drawing, edited),
                               job(edited, drawing, "loaded")])
    # arrows taken away since the page loaded: the group is red
    assert taken["rows"]["label"]["red"] and taken["missing"] == 1
    # an arrow drawn since: the group is met
    assert not drawn["rows"]["label"]["red"] and drawn["missing"] == 0
    # the failure by construction: the rows of the loaded drawing keep the
    # arrows the edit took away
    assert not stale["rows"]["label"]["red"] and stale["missing"] == 0


@needs_node
def test_the_old_marks_miss_the_group(page):
    # the failure the tab had: a class read without its sh:or demands
    # neither the name nor the acronym, and nothing is missing although
    # neither is written
    classes, drawing = page
    old = copy.deepcopy(classes)
    for one in old:
        one.pop("one_of", None)
    (none,) = rows(old, without(drawing, "rdfs:label", "dc:acronym"))
    for name in ("label", "acronym"):
        assert not none["rows"][name]["demanded"]
        assert not none["rows"][name]["red"]
    assert none["missing"] == 0
