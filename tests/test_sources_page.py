"""
test_sources_page.py: what the Sources tab of `docpipe edit` promises
(owner, 2026-11-10: "einfach die URLs angeben für Ontologie und KG und dann
eben die auch die Felder auswählen und zusammenlegen").

The promises, each with a case that breaks it by construction:

1. "Fetch" writes nothing but into a folder of the temp directory: the
   profile's folder and the cache are byte for byte what they were, AND the
   fetch folder holds what the refresh wrote.
2. "Apply" writes the files the refresh writes and the lock, the spec never:
   a fetch that also left a spec in its folder does not reach the profile,
   AND the lock names the cache, not the temp folder.
3. A checked row "new entry" puts exactly that entry into the list, with the
   ontology's name and definition, AND the spec the Spec tab saves holds it;
   an entry the pinned ontology does not carry is refused.
4. The comparison reads what a field becomes from the drawing of the
   profile's graph file: no field of KWP is "without an arrow" with its
   drawing, AND every one is without it where no drawing is given.
5. The page never shows a token's value, only whether it is set.
6. "Write a field under it as well" draws an arrow from the field to the
   box of the property's class, AND the written graph then holds the
   field's value under that property; where the drawing has no box of the
   class one is added; a field the spec does not have and a property
   merged twice are refused; and a choice that draws nothing hands no
   drawing back.

Author: Felix Vossel
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from docpipe import sources as source_files
from docpipe import upstream
from docpipe.editor import server, sourcespage
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parent.parent
OEO = "https://openenergyplatform.org/ontology/oeo/"
IAM = "OEO_00020517"
SHAPES = f"""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix oeo: <{OEO}> .
@prefix ex: <https://example.org/shapes/> .

ex:Factsheet a sh:NodeShape ;
    sh:targetClass oeo:OEO_00000365 ;
    sh:property [ sh:path oeo:OEO_00390073 ;
                  sh:in ( oeo:OEO_00020309 oeo:{IAM} oeo:OEO_99999999 ) ] .
"""


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*")) if path.is_file()}


@pytest.fixture
def profile(tmp_path):
    """scenarios with a folder of its own, its spec and its sources."""
    home = tmp_path / "scenarios"
    home.mkdir()
    for name in ("extraction_spec.json", "sources.json", "graph.json"):
        shutil.copy(REPO / "profiles" / "scenarios" / name, home)
    (home / "vocabulary.json").write_text(json.dumps(pinned("OEO_00020309")),
                                          encoding="utf-8")
    return dataclasses.replace(load_profile("scenarios"), home=home)


@pytest.fixture
def cache(tmp_path):
    """An upstream cache whose lock names one shapes file."""
    folder = tmp_path / "cache"
    shapes = folder / "oekg_shapes" / "shapes.ttl"
    shapes.parent.mkdir(parents=True)
    shapes.write_text(SHAPES, encoding="utf-8")
    upstream.write_lock("scenarios", {"oekg_shapes": {
        "kind": "repo_files", "version": "old",
        "files": [{"path": str(shapes), "sha256": "x", "bytes": 1}]}},
        folder)
    return folder


def pinned(*keys) -> dict:
    """A snapshot that carries *keys* with a name and a definition."""
    return {"pin": {}, "sets": {"scenario": list(keys)},
            "terms": {key: {"label": f"name of {key}",
                            "definition": f"{key} is defined so.",
                            "alt_labels": [], "parents": [],
                            "deprecated": False, "kind": "class"}
                      for key in keys}}


def stub_refresh(monkeypatch, extra_spec: bool = False):
    """The profile's refresh without the network: writes what a refresh
    writes into *out* and the lock into *cache*."""
    from profiles.scenarios import vocabulary

    def refresh(cache, out=None):
        cache, out = Path(cache), Path(out)
        shapes = cache / "oekg_shapes" / "shapes.ttl"
        shapes.parent.mkdir(parents=True, exist_ok=True)
        shapes.write_text(SHAPES, encoding="utf-8")
        for name in vocabulary.WRITES:
            data = pinned(IAM) if name == "vocabulary.json" else {"x": 1}
            (out / name).write_text(json.dumps(data), encoding="utf-8")
        if extra_spec:
            (out / "extraction_spec.json").write_text("{}", encoding="utf-8")
        records = {"oekg_shapes": {"kind": "repo_files", "version": "new",
                                   "files": [{"path": str(shapes),
                                              "sha256": "y", "bytes": 1}]}}
        upstream.write_lock("scenarios", records, cache)
        return records

    monkeypatch.setattr(vocabulary, "refresh", refresh)


def make_app(tmp_path, profile, cache) -> server.App:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    app = server.App(profile, None, root, cache=cache,
                     fetch_root=tmp_path / "fetches")
    app.spec_path = Path(profile.package_dir) / "extraction_spec.json"
    return app


def test_a_fetch_writes_only_into_its_own_folder(tmp_path, profile, cache,
                                                 monkeypatch):
    stub_refresh(monkeypatch)
    app = make_app(tmp_path, profile, cache)
    home, kept = Path(profile.package_dir), tree(Path(profile.package_dir))
    cached = tree(cache)
    status, report = app.call("POST", "/api/sources/fetch", {}, {})
    assert status == 200, report
    assert tree(home) == kept and tree(cache) == cached
    where = tmp_path / "fetches" / report["id"]
    assert (where / "profile" / "vocabulary.json").is_file()
    assert [row for row in report["sources"]
            if row["name"] == "oekg_shapes"][0]["moved"]
    # the failure by construction: the fetched list does say what is new
    added = [one for row in report["lists"] for one in row["added"]]
    gone = [one for row in report["lists"] for one in row["gone"]]
    assert [one["id"] for one in added] == [IAM]
    assert [one["id"] for one in gone] == ["OEO_00020309"]


def test_apply_writes_the_lists_and_the_lock_and_never_the_spec(
        tmp_path, profile, cache, monkeypatch):
    stub_refresh(monkeypatch, extra_spec=True)
    app = make_app(tmp_path, profile, cache)
    spec_before = (Path(profile.package_dir) /
                   "extraction_spec.json").read_bytes()
    status, report = app.call("POST", "/api/sources/fetch", {}, {})
    status, done = app.call("POST", "/api/sources/apply", {},
                            {"fetch": report["id"]})
    assert status == 200, done
    home = Path(profile.package_dir)
    assert json.loads((home / "vocabulary.json").read_text(
        encoding="utf-8"))["sets"]["scenario"] == [IAM]
    assert (home / "extraction_spec.json").read_bytes() == spec_before
    lock = upstream.load_lock("scenarios", cache)
    assert lock["sources"]["oekg_shapes"]["version"] == "new"
    named = lock["sources"]["oekg_shapes"]["files"][0]["path"]
    assert Path(named).resolve().is_relative_to(cache.resolve())
    assert "fetches" not in named
    # the failure by construction: an id that is no fetch applies nothing
    status, told = app.call("POST", "/api/sources/apply", {},
                            {"fetch": "../../etc"})
    assert status == 404


def test_a_checked_new_entry_comes_with_the_ontology_s_name(
        tmp_path, profile, cache):
    app = make_app(tmp_path, profile, cache)
    app._snapshot, app._loaded = pinned(IAM), True
    status, shown = app.call("GET", "/api/sources", {}, None)
    assert status == 200, shown
    rows = [row for field in shown["differences"]["fields"]
            if field["field"] == "scenario_type" for row in field["rows"]
            if row["kind"] == "list_missing"]
    entries = {one["iri"]: one for row in rows for one in row["entries"]}
    assert entries[OEO + IAM]["takes"]
    # the failure by construction: the ontology does not carry the other
    assert not entries[OEO + "OEO_99999999"]["takes"]
    status, taken = app.call("POST", "/api/sources/take", {}, {"chosen": [
        {"id": entries[OEO + IAM]["id"], "action": "add"},
        {"id": entries[OEO + "OEO_99999999"]["id"], "action": "add"}]})
    assert status == 200 and len(taken["done"]) == 1
    assert len(taken["refused"]) == 1
    listed = [one for one in taken["data"]["parameters"]
              if one["uri"] == "scenario_type"][0]["vocabulary"]
    assert listed[OEO + IAM] == {"label": f"name of {IAM}", "spellings": [],
                                 "definition": f"{IAM} is defined so."}
    # the Spec tab saves it as it saves any edit
    spec_file = Path(profile.package_dir) / "extraction_spec.json"
    status, told = app.call("POST", "/api/spec/save", {}, {
        "data": taken["data"], "base": server.sha256(spec_file.read_bytes())})
    assert status == 200 and told.get("saved"), told
    saved = json.loads(spec_file.read_text(encoding="utf-8"))
    assert OEO + IAM in [one for one in saved["parameters"]
                         if one["uri"] == "scenario_type"][0]["vocabulary"]


def test_kwp_is_held_to_its_shapes_by_what_its_drawing_writes():
    pytest.importorskip("rdflib")
    profile = load_profile("kwp")
    files = sourcespage.shape_files(profile)
    if not files:
        pytest.skip("no MHPKG shapes in the cache")
    spec = json.loads((REPO / "profiles" / "kwp" / "extraction_spec.json")
                      .read_text(encoding="utf-8"))
    from docpipe import graphfile
    from docpipe.compile import draft, shapes
    found, _ = shapes.read(files)
    drawn = draft.differences(found, spec,
                              drawing=graphfile.load(profile).map)
    assert not [row for row in drawn if row["kind"] == "no_graph_block"]
    # the failure by construction: with no drawing no arrow writes a field
    bare = draft.differences(found, spec)
    assert [row for row in bare if row["kind"] == "no_graph_block"]


def test_a_token_is_shown_as_set_never_as_its_value(tmp_path, profile,
                                                    cache, monkeypatch):
    secret = "tok-very-secret-0815"
    monkeypatch.setenv("OEP_API_TOKEN", secret)
    app = make_app(tmp_path, profile, cache)
    status, shown = app.call("GET", "/api/sources", {}, None)
    assert status == 200 and secret not in json.dumps(shown)
    tokens = [row["token"] for row in shown["sources"] if row["token"]]
    assert tokens and all(one == {"env": "OEP_API_TOKEN", "set": True}
                          for one in tokens)
    # the failure by construction: unset, it says so
    monkeypatch.delenv("OEP_API_TOKEN")
    status, shown = app.call("GET", "/api/sources", {}, None)
    assert not [row for row in shown["sources"]
                if row["token"] and row["token"]["set"]]
    # and a file with a token in it is refused by the run's own reader
    data = json.loads(source_files.dump(source_files.load(profile)))
    data["sources"]["regions"]["token"] = secret
    status, report = app.call("POST", "/api/sources/check", {},
                              {"data": data})
    assert not report["ok"] and "token" in report["errors"][0]



THING = "https://example.org/o/"


def thing_drawing() -> dict:
    return {"prefixes": {"ex": THING,
                         "rdfs": "http://www.w3.org/2000/01/rdf-schema#"},
            "prefix_width": 6,
            "boxes": [{"id": "thing", "class": "ex:Thing",
                       "count": "per_document",
                       "address": {"folder": "thing", "key": "thing",
                                   "from": ["energy"], "fold": True}}],
            "arrows": [{"from": "energy", "to": "thing",
                        "property": "rdfs:label"}]}


def written_text(drawing: dict) -> str:
    """The graph the drawing writes for one document that has one reading of
    the field `energy`."""
    from docpipe.extraction import graph, spec as spec_module
    from docpipe.extraction.bricks import registry
    spec = spec_module.load({"parameters": [{
        "uri": "energy", "label": "Energy", "value_type": "text",
        "description": "The name of the thing this passage says it is, as "
                       "the document prints it.",
        "example": {"source": "Der Plan heißt Wärmeplan Nord.",
                    "tuples": [{"value": "Wärmeplan Nord",
                                "quote": "heißt Wärmeplan Nord"}]}}]})
    writer = graph.Writer(graph.Drawing(drawing), spec=spec,
                          rules={"base": "https://example.org/id/",
                                 "pick_one_order": ["not_contained",
                                                    "most_sources"]},
                          bricks=registry())
    row = {"kind": "tuple", "parameter": "energy", "value": "Wärmeplan Nord",
           "value_raw": "Wärmeplan Nord", "unit": None, "state": "read",
           "quote": "Der Plan heißt Wärmeplan Nord.", "trust": "A",
           "tier": "text",
           "provenance": {"page": 1, "owner_kind": "section",
                          "owner_id": 1}}
    written = writer.write("doc1", [row])
    return written.text() if written else ""


def test_a_merge_draws_the_property_the_field_is_then_written_under():
    pytest.importorskip("rdflib")
    from docpipe.compile.shapes import Property, Shape
    shape = Shape(iri="", name="Thing", target_class=THING + "Thing")
    prop = Property(path=THING + "amount", name="amount")
    parameters = {"energy": {"uri": "energy"}}
    drawing = thing_drawing()
    # the failure by construction: before the merge the property is not
    # drawn and the graph does not hold it
    assert "ex:amount" not in written_text(drawing)
    done, said = sourcespage._merge(parameters, drawing, "energy", shape,
                                    prop, {"ex": THING})
    assert done, said
    assert {"from": "energy", "to": "thing", "property": "ex:amount"} \
        in drawing["arrows"]
    assert len(drawing["boxes"]) == 1
    assert 'ex:amount "Wärmeplan Nord"' in written_text(drawing)
    # merged a second time, or into a field the spec does not have: refused,
    # and the drawing stays as it was
    before = json.dumps(drawing)
    assert not sourcespage._merge(parameters, drawing, "energy", shape,
                                  prop, {"ex": THING})[0]
    assert not sourcespage._merge(parameters, drawing, "nothing", shape,
                                  prop, {"ex": THING})[0]
    assert json.dumps(drawing) == before


def test_a_merge_into_a_class_the_drawing_has_no_box_for_adds_the_box():
    pytest.importorskip("rdflib")
    from docpipe.compile.shapes import Property, Shape
    shape = Shape(iri="", name="Other", target_class=THING + "Other")
    prop = Property(path=THING + "amount", name="amount")
    drawing = thing_drawing()
    done, said = sourcespage._merge({"energy": {"uri": "energy"}}, drawing,
                                    "energy", shape, prop, {"ex": THING})
    assert done, said
    box = [one for one in drawing["boxes"] if one["id"] != "thing"]
    assert [one["class"] for one in box] == ["ex:Other"]
    assert {"from": "energy", "to": box[0]["id"],
            "property": "ex:amount"} in drawing["arrows"]
    text = written_text(drawing)
    assert "a ex:Other" in text and 'ex:amount "Wärmeplan Nord"' in text
    # a profile whose graph file has no drawing has nothing to draw in
    assert not sourcespage._merge({"energy": {"uri": "energy"}}, {},
                                  "energy", shape, prop, {"ex": THING})[0]


def test_take_hands_back_the_drawing_only_where_a_merge_changed_it(
        tmp_path, profile):
    pytest.importorskip("rdflib")
    shapes = tmp_path / "more.ttl"
    shapes.write_text(SHAPES.replace(
        "sh:path oeo:OEO_00390073 ;\n                  sh:in ( oeo:"
        f"OEO_00020309 oeo:{IAM} oeo:OEO_99999999 )",
        "sh:path oeo:OEO_99990001 ; sh:name \"widget\""), encoding="utf-8")
    spec = json.loads((Path(profile.package_dir) / "extraction_spec.json")
                      .read_text(encoding="utf-8"))
    row = "not_asked|factsheet|OEO_99990001"
    taken = sourcespage.take(spec, [{"id": row, "action": "merge",
                                     "into": "scenario_abstract"}],
                             None, profile, [shapes])
    assert not taken["refused"], taken["refused"]
    arrows = [one for one in taken["map"]["arrows"]
              if one["from"] == "scenario_abstract"
              and one["property"] == "oeo:OEO_99990001"]
    assert len(arrows) == 1 and arrows[0]["to"] == "scenario"
    assert taken["data"] == spec           # a merge never touches the spec
    # the failure by construction: a choice that is refused draws nothing
    none = sourcespage.take(spec, [{"id": row, "action": "merge",
                                    "into": "no_such_field"}],
                            None, profile, [shapes])
    assert none["refused"] and none["map"] is None

