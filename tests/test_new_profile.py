"""A new profile from the editor (owner request 2026-11-14, wish 5): made
with the code `docpipe init` uses, empty or as a copy of another profile, it
loads; a profile with only a draft of its spec is edited as that draft, and
the spec is written once the draft lacks nothing. Each promise has a case
that breaks it on purpose."""
import json

import pytest

from docpipe import cli, newprofile, profile as profile_module
from docpipe.editor import server
from docpipe.extraction import flow as flow_map
from docpipe.extraction import spec as spec_module


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder whose profiles the installation finds."""
    home = tmp_path / "project"
    (home / "profiles").mkdir(parents=True)
    monkeypatch.setenv(profile_module.PATH_ENV, str(home / "profiles"))
    return home


def app(home, profile="kwp", **kw):
    return server.App(profile_module.load_profile(profile), home=home, **kw)


def files_of(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_page_makes_the_profile_init_makes(project, tmp_path):
    made = app(project)._profile_new(None, {"name": "neu", "start": "empty",
                                            "draft": "bundled"})
    assert made["profile"] == "neu" and made["missing"]
    other = tmp_path / "by_init"
    other.mkdir()
    assert cli._init(["neu_init", "--dir", str(other), "--shapes"]) == 0
    page = files_of(project / "profiles" / "neu")
    init = files_of(other / "profiles" / "neu_init")
    assert set(page) == set(init) == {"__init__.py", "profile.py",
                                      "extraction.py",
                                      newprofile.DRAFT_FILE}
    assert page[newprofile.DRAFT_FILE] == init[newprofile.DRAFT_FILE]
    assert page["profile.py"].replace(b"neu", b"X") \
        == init["profile.py"].replace(b"neu_init", b"X") \
        .replace(b"Neu init", b"Neu")
    assert (project / "data" / "neu" / "pdf").is_dir()
    loaded = profile_module.load_profile("neu")
    assert loaded.extends == "default"


def test_a_copy_extends_its_profile_and_has_its_own_files(project):
    app(project)._profile_new(None, {"name": "kwp_copy", "start": "copy",
                                     "from": "kwp"})
    copy = profile_module.load_profile("kwp_copy")
    kwp = profile_module.load_profile("kwp")
    assert copy.extends == "kwp" and copy.document_noun == kwp.document_noun
    folder = project / "profiles" / "kwp_copy"
    for name in ("extraction_spec.json", "graph.json"):
        assert (folder / name).read_bytes() \
            == (kwp.package_dir / name).read_bytes()
    # the flow: the copy draws what kwp draws; kwp's file holds only the
    # changes it makes in the default's drawing, which the copy inherits
    # with kwp's, so the copy needs no flow file of its own
    assert flow_map.load(copy).tree == flow_map.load(kwp).tree
    assert not (folder / "flow.json").exists()
    # the failure by construction: kwp's file as it is makes its changes a
    # second time in a drawing that holds them
    (folder / "flow.json").write_bytes(
        (kwp.package_dir / "flow.json").read_bytes())
    with pytest.raises(flow_map.FlowError):
        flow_map.load(copy)
    assert copy.component("extraction", "SPEC_PATH") \
        == folder / "extraction_spec.json"
    # what the copy does not have itself is the profile's it copies
    assert copy.component("kg", "PRESETS") is kwp.component("kg", "PRESETS")
    spec_module.load(copy.component("extraction", "SPEC_PATH"))


@pytest.mark.parametrize("body, said", [
    ({"name": "Neu"}, "cannot name"),
    ({"name": "kwp"}, "exists already"),
    ({"name": "neu", "start": "copy", "from": "nowhere"}, "no profile"),
    ({"name": "neu", "draft": "shapes"}, "address of the shapes"),
    ({"name": "neu", "addresses": {"ontology": "file:///x.owl"}},
     "no http"),
])
def test_a_profile_that_cannot_be_made_leaves_nothing_behind(project, body,
                                                             said):
    with pytest.raises(server._Refusal, match=said):
        app(project)._profile_new(None, body)
    assert not (project / "profiles" / "neu").exists()


def test_an_address_becomes_a_source_fetched_before_anything_is_written(
        project, monkeypatch):
    fetched = []

    def fetch(sources, cache):
        fetched.append(dict(sources))
        raise server.upstream.UpstreamError("no network here")
    monkeypatch.setattr(server.upstream, "fetch", fetch)
    with pytest.raises(server._Refusal, match="no network"):
        app(project)._profile_new(None, {
            "name": "neu", "addresses": {
                "shapes": "https://example.org/a/shapes.ttl"}})
    assert fetched == [{"shapes": {"kind": "url", "url":
                                   "https://example.org/a/shapes.ttl",
                                   "file": "shapes.ttl"}}]
    assert not (project / "profiles" / "neu").exists()


def finished_draft(draft: dict) -> dict:
    draft = json.loads(json.dumps(draft))
    draft["graph"]["rules"]["base"] = "https://example.com/kg/"
    for parameter in draft["parameters"]:
        parameter["example"] = {
            "source": "Der Bericht über die Wärme der Stadt nennt auf der "
                      "ersten Seite seinen Titel und seine Verfasser.",
            "tuples": [{"value": "Wärme der Stadt",
                        "quote": "die Wärme der Stadt"}]}
    return draft


def test_a_draft_is_edited_and_the_spec_written_once_it_lacks_nothing(
        project):
    app(project)._profile_new(None, {"name": "neu", "draft": "bundled"})
    editor = app(project, "neu")
    view = editor._spec(None, None)
    assert view["draft"] and view["missing"]
    folder = project / "profiles" / "neu"
    said = editor._save(None, {"data": view["data"], "base": view["base"]})
    assert said["saved"] and said["missing"]
    assert not (folder / "extraction_spec.json").exists()
    done = finished_draft(view["data"])
    said = editor._save(None, {"data": done, "base": said["base"]})
    assert said["spec_written"] and not said["missing"]
    written = spec_module.load(folder / "extraction_spec.json")
    assert len(written.parameters) == len(done["parameters"])
    assert json.loads((folder / "graph.json").read_text(encoding="utf-8")
                      )["rules"]["base"] == "https://example.com/kg/"
    assert "draft" not in editor._spec(None, None)


def test_a_draft_that_became_the_spec_goes_to_the_archive_whole(project):
    app(project)._profile_new(None, {"name": "neu", "draft": "bundled"})
    editor = app(project, "neu")
    view = editor._spec(None, None)
    folder = project / "profiles" / "neu"
    from docpipe.compile import examples as proposing
    proposals = proposing.review_path(folder / newprofile.DRAFT_FILE)
    proposals.write_text("[]", encoding="utf-8")
    done = finished_draft(view["data"])
    said = editor._save(None, {"data": done, "base": view["base"]})
    draft = folder / newprofile.DRAFT_FILE
    assert not proposals.exists()
    assert said["spec_written"] and not draft.exists()
    kept = list((folder / "archive").glob(f"draft-*/{newprofile.DRAFT_FILE}"))
    assert len(kept) == 1 and said["draft_kept"]
    assert json.loads(kept[0].read_text(encoding="utf-8")) == done


def test_compile_apply_sets_aside_a_draft_only_in_the_spec_s_folder(tmp_path):
    from docpipe.compile import draft as drafting
    here, there = tmp_path / "here", tmp_path / "there"
    here.mkdir()
    there.mkdir()
    for folder in (here, there):
        (folder / "d.json").write_text("{}", encoding="utf-8")
        (folder / "d.review.json").write_text("[]", encoding="utf-8")
    assert drafting.set_aside(there / "d.json", here / "spec.json") is None
    assert (there / "d.json").exists()
    kept = drafting.set_aside(here / "d.json", here / "spec.json",
                              with_it=(here / "d.review.json",))
    assert sorted(p.name for p in kept.iterdir()) == ["d.json",
                                                      "d.review.json"]
    assert not (here / "d.json").exists()
    assert kept.parent == here / drafting.ARCHIVE



def test_the_page_checks_a_condition_against_the_spec_s_value_types(
        project, monkeypatch):
    from docpipe.extraction import conditions

    def kind_problems():
        return [bool(conditions.problems({"all": [
            {"of": "field", "is": "kind", "op": "one_of", "value": [name]}]}))
            for name in ("percent", "prozent")]

    app(project)._profile_new(None, {"name": "neu", "draft": "bundled"})
    editor = app(project, "neu")
    folder = project / "profiles" / "neu"
    draft = json.loads((folder / newprofile.DRAFT_FILE).read_text(
        encoding="utf-8"))
    draft["value_types"] = {"percent": {"answer": "number",
                                        "in_quote": "words"}}
    (folder / newprofile.DRAFT_FILE).write_text(json.dumps(draft),
                                                encoding="utf-8")
    seen = []
    monkeypatch.setattr(editor, "_state",
                        lambda query, body: seen.append(kind_problems()) or {})
    assert editor.call("GET", "/api/state", {}, None)[0] == 200
    assert seen == [[False, True]]      # the spec's own type, a typo
    assert kind_problems() == [False, False]    # no spec known: any name
