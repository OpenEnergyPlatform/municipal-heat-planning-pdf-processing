"""
The Graph tab of `docpipe edit` draws how a harvest becomes the graph
(docpipe/editor/graphpage.py; the drawing is `map` of the profile's graph
file). The promises of its server side, each with a case that breaks it by
construction:

1. `view` returns the drawing, AND the fields of the harvest as the spec
   asks them, AND the bricks the run knows. (Without a spec there are no
   fields; a profile without a drawing has an empty one.)
2. A save writes the drawing into the graph file, AND a reload returns it.
   (A file that moved since the page loaded it is not written.)
3. A drawing that names a field the spec does not ask, a brick no code has,
   a property the shapes do not give the class, or a box twice is refused
   with the name it is about.
4. A required property without an arrow is not refused.
5. The preview of a document is the document written as the edited drawing
   says: with an arrow removed, its triple is gone.

Author: Felix Vossel
"""
import json
import shutil

import pytest

from docpipe import graphfile
from docpipe.editor import graphpage, server
from docpipe.profile import load_profile


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """The scenarios profile whose graph files live in a temp folder, so a
    save never touches the repository."""
    prof = load_profile("scenarios")
    place = {}
    for one in prof.lineage():
        target = tmp_path / one.name / graphfile.FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        real = graphfile.path_of(one)
        if real.is_file():
            shutil.copy(real, target)
        place[one.name] = target
    monkeypatch.setattr(graphfile, "path_of", lambda one: place[one.name])
    graphfile.reset()
    yield prof
    graphfile.reset()


def page_data(prof) -> dict:
    """What the page sends: the whole file as it has it."""
    made = graphfile.load(prof, environ={})
    return {"classes": dict(made.classes),
            "constraints": dict(made.constraints),
            "rules": dict(made.rules), "map": json.loads(json.dumps(made.map))}


def view_of(prof, spec=None, harvest=None):
    app = server.App(prof, harvest)
    own = graphfile.path_of(prof)
    raw = own.read_bytes() if own.is_file() else None
    return graphpage.view(prof, raw, app.shown, app._spec_raw(), [], None,
                          app._spec_object() if spec is None else spec,
                          harvest)


def arrow(data, source, prop):
    return next(a for a in data["map"]["arrows"]
                if a["from"] == source and a["property"] == prop)


def test_view_returns_the_drawing_the_fields_and_the_bricks(profile):
    view = view_of(profile)
    assert view["map"]["boxes"] and view["map"]["arrows"]
    names = {one["name"] for one in view["fields"]}
    assert "publication_title" in names
    brick = next(b for b in view["bricks"] if b["name"] == "year_to_datetime")
    assert brick["does"] and brick["kind"] == "object"


def test_without_a_spec_there_are_no_fields_and_without_a_map_no_drawing(
        profile):
    class NoSpec:
        by_uri = {}
    view = view_of(profile, spec=NoSpec())
    assert view["fields"] == []
    own = graphfile.path_of(profile)
    said = json.loads(own.read_text(encoding="utf-8"))
    del said["map"]
    own.write_text(json.dumps(said), encoding="utf-8")
    graphfile.reset()
    assert view_of(profile)["map"] == {}


def test_a_save_writes_the_drawing_and_a_reload_returns_it(profile):
    data = page_data(profile)
    gone = arrow(data, "publication_doi", "oeo:OEO_00390098")
    data["map"]["arrows"].remove(gone)
    own = graphfile.path_of(profile)
    raw = own.read_bytes()
    told, written, remove = graphpage.save(
        profile, raw, data, graphpage.sha256(raw), "graph.json")
    assert told["saved"] and written and not remove
    own.write_bytes(written)
    graphfile.reset()
    again = view_of(profile)["map"]
    assert again == data["map"]
    assert gone not in again["arrows"]


def test_a_file_that_moved_is_not_written(profile):
    data = page_data(profile)
    raw = graphfile.path_of(profile).read_bytes()
    told, written, _ = graphpage.save(profile, raw, data, "stale", "g.json")
    assert not told["saved"] and told["reason"] == "moved"
    assert written is None


def judge(profile, data):
    raw = graphfile.path_of(profile).read_bytes()
    return graphpage.judge(profile, raw, data, "graph.json")


def test_a_good_drawing_is_accepted(profile):
    # the case the refusals below break
    assert judge(profile, page_data(profile))["ok"]


def test_an_unknown_field_is_refused_with_its_name(profile):
    data = page_data(profile)
    arrow(data, "publication_doi", "oeo:OEO_00390098")["from"] = "no_such"
    report = judge(profile, data)
    assert not report["ok"]
    assert any("no_such" in said for said in report["errors"])
    assert any(p["arrow"] and "no_such" in p["arrow"]
               for p in report["problems"])


def test_an_unknown_brick_is_refused_with_its_name(profile):
    data = page_data(profile)
    arrow(data, "publication_doi", "oeo:OEO_00390098")["brick"] = "no_brick"
    report = judge(profile, data)
    assert not report["ok"]
    assert any("no_brick" in said for said in report["errors"])


def test_a_property_the_class_does_not_have_is_refused(profile):
    data = page_data(profile)
    arrow(data, "publication_doi", "oeo:OEO_00390098")["property"] = \
        "oeo:OEO_00020220"
    report = judge(profile, data)
    assert not report["ok"]
    assert any("OEO_00020220" in said for said in report["errors"])


def test_a_box_drawn_twice_is_refused_with_its_id(profile):
    data = page_data(profile)
    data["map"]["boxes"].append(dict(data["map"]["boxes"][0]))
    report = judge(profile, data)
    assert not report["ok"]
    assert any("report" in said for said in report["errors"])
    assert any(p["box"] == "report" for p in report["problems"])


def test_a_required_property_without_an_arrow_is_not_refused(profile):
    data = page_data(profile)
    # rdfs:label of the study report is required (min 1) by the shapes
    data["map"]["arrows"].remove(
        arrow(data, "publication_title", "rdfs:label"))
    assert judge(profile, data)["ok"]


def row(parameter, value):
    return {"kind": "tuple", "parameter": parameter, "value": value,
            "quote": value, "parameter_state": "read",
            "tier": "text_located", "work": "work:this_publication",
            "work_state": "read",
            "provenance": {"document_id": 1, "page": 1, "section_number": 0,
                           "section_title": "t", "title": "t",
                           "owner_kind": "section", "owner_id": 1}}


def test_the_preview_loses_the_triple_of_a_removed_arrow(profile, tmp_path):
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    (harvest / "doc.jsonl").write_text("\n".join(json.dumps(r) for r in (
        row("publication_title", "A Title of a Study"),
        row("publication_doi", "10.1000/xyz"))) + "\n", encoding="utf-8")
    data = page_data(profile)
    first = graphpage.preview(profile, data, harvest, "doc",
                              root=tmp_path / "p")
    assert "10.1000/xyz" in first["text"]
    data["map"]["arrows"].remove(
        arrow(data, "publication_doi", "oeo:OEO_00390098"))
    second = graphpage.preview(profile, data, harvest, "doc",
                               root=tmp_path / "p")
    assert "10.1000/xyz" not in second["text"]
    assert "A Title of a Study" in second["text"]


def test_a_preview_of_no_document_or_no_harvest_is_refused(profile, tmp_path):
    data = page_data(profile)
    with pytest.raises(graphpage.PreviewError):
        graphpage.preview(profile, data, None, "doc")
    with pytest.raises(graphpage.PreviewError):
        graphpage.preview(profile, data, tmp_path, "missing")
