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
4. The comparison reads KWP as its shapes name its properties: no field of
   KWP is "without a graph block" once its schema slots are resolved.
5. The page never shows a token's value, only whether it is set.
6. "Write a field under it as well" puts the property beside the predicate
   the choice names (`also`), every predicate of every field being offered,
   AND the written graph then holds that predicate's value under it; a
   field of several predicates named alone, and a property merged twice,
   are refused.

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
    for name in ("extraction_spec.json", "sources.json"):
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


def test_kwp_is_held_to_its_shapes_by_the_names_its_schema_gives():
    pytest.importorskip("rdflib")
    profile = load_profile("kwp")
    files = sourcespage.shape_files(profile)
    if not files:
        pytest.skip("no MHPKG shapes in the cache")
    spec = json.loads((REPO / "profiles" / "kwp" / "extraction_spec.json")
                      .read_text(encoding="utf-8"))
    from docpipe.compile import draft, shapes
    found, _ = shapes.read(files)
    resolved = draft.differences(found, draft.read_as_shapes(spec, profile))
    assert not [row for row in resolved if row["kind"] == "no_graph_block"]
    # the failure by construction: the spec as written names no predicate
    written = draft.differences(found, spec)
    assert [row for row in written if row["kind"] == "no_graph_block"]


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



def test_a_merge_writes_the_property_beside_the_predicate_it_names():
    pytest.importorskip("rdflib")
    from docpipe import graphfile
    from docpipe.compile.shapes import Property
    data = {"parameters": [{"uri": "energy", "kg": {
        "node": "value", "class": "ex:Value",
        "number": {"prefix": "ex", "predicate": "number",
                   "label": "has number"},
        "unit": {"prefix": "ex", "predicate": "unit", "label": "has unit"}},
        "axes": {"carrier": {"kg": {"role": "edge", "prefix": "ex",
                                    "predicate": "carrier"}}}}]}
    parameters = {one["uri"]: one for one in data["parameters"]}
    prop = Property(path="https://example.org/o/amount", name="amount")
    prefixes = {"ex": "https://example.org/o/"}
    assert {one["into"] for one in sourcespage.merge_targets(data)} == {
        "energy|kg.number", "energy|kg.unit", "energy|axes.carrier.kg"}
    done, said = sourcespage._merge(data, parameters, "energy|kg.number",
                                    prop, prefixes)
    assert done, said
    kg = data["parameters"][0]["kg"]
    assert kg["number"]["also"] == {"prefix": "ex", "predicate": "amount",
                                    "label": "amount"}
    assert "also" not in kg["unit"]
    text = """@prefix ex: <https://example.org/o/> .

<https://example.org/id/value/1>
    a ex:Value ;
    ex:number 5 ;
    ex:unit ex:MWh .
"""
    out, added = graphfile.add_also(text, graphfile.also_pairs(data))
    assert added == 1 and "ex:amount 5" in out
    # the failure by construction: named alone, a field of three predicates
    # is refused, and so is a property merged a second time
    assert not sourcespage._merge(data, parameters, "energy", prop,
                                  prefixes)[0]
    assert not sourcespage._merge(data, parameters, "energy|kg.number", prop,
                                  prefixes)[0]
