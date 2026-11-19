"""
test_flow_parts.py: what the parts of a drawing and a profile's changes to
the drawing it inherits promise (owner request 2026-11-19, point C2 of the
review of that day; docpipe/extraction/flowparts.py).

1. A frame that uses a part draws the part's steps, every id prefixed with
   its prefix, AND keeps its own settings.
2. The three profiles go through the steps for one value from one part in
   both frames of values.
3. A profile that extends another writes only what it changes in the
   drawing it inherits, AND a change to a part reaches every frame that
   uses it.
4. A save folds the drawn drawing back: a change to the steps of a part in
   one frame is made in every frame that uses it, AND two frames changed
   differently are refused.
5. The changes a save writes give the drawing exactly when they are made in
   the drawing it inherits.
6. A save that leaves the drawing as it was leaves the drawing in the file
   as the file writes it.
7. The run reads the drawing with every part drawn, AND its fingerprint is
   that of the drawn drawing.
8. A copy of a profile takes the numbers of its flow file, not its
   changes.
9. The page is told which frames use a part and which others use it too.

Each test holds a case that breaks its promise by construction.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from docpipe import newprofile
from docpipe.editor import flow as flow_view
from docpipe.extraction import flow, flowparts
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parent.parent
SETTINGS = sorted({number.env for number in flow.NUMBERS if number.env})
PART = "value"
FRAMES = {"document_values": "document_", "values": ""}


@pytest.fixture(autouse=True)
def no_setting_wins(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def profile(tmp_path):
    """scenarios with a folder of its own and its prompts, still extending
    default; it writes no flow file until a test does."""
    home = tmp_path / "scenarios"
    home.mkdir()
    shutil.copy(REPO / "profiles" / "scenarios" / "extraction_spec.json",
                home)
    shutil.copytree(REPO / "profiles" / "scenarios" / "prompts",
                    home / "prompts")
    return dataclasses.replace(load_profile("scenarios"), home=home)


def node_of(tree: list, ident: str) -> dict:
    return next(node for node, _ in flow.walk(tree) if node.get("id") == ident)


def ids(steps: list) -> list:
    return [node.get("id") for node, *_ in flowparts.places(steps)]


def judge(profile, tree=None, numbers=None) -> dict:
    path = flow.path_of(profile)
    raw = path.read_bytes() if path.is_file() else None
    return flow_view.judge(profile, raw, numbers or flow.load(profile).numbers,
                           "flow.json", tree)


SMALL_PARTS = {"p": [{"id": "x", "box": "ask", "preset": "find"},
                     {"id": "y", "each": "piece", "steps": [
                         {"id": "z", "box": "ask", "preset": "find"}]}]}


def small_top() -> list:
    return [{"id": "first", "box": "document"},
            {"id": "a", "each": "field", "order": "document", "part": "p",
             "prefix": "a_"},
            {"id": "b", "each": "field", "order": "names_first",
             "part": "p"}]


# -- 1. a frame that uses a part ------------------------------------------------

def test_a_frame_that_uses_a_part_draws_its_steps_prefixed():
    drawn = flowparts.expand(small_top(), SMALL_PARTS)
    assert ids(drawn) == ["first", "a", "a_x", "a_y", "a_z", "b", "x", "y",
                          "z"]
    assert node_of(drawn, "a_z") == {"id": "a_z", "box": "ask",
                                     "preset": "find"}
    # the failure by construction: a part the drawing does not name
    top = small_top()
    top[1]["part"] = "q"
    with pytest.raises(flowparts.PartError, match="does not name"):
        flowparts.expand(top, SMALL_PARTS)


def test_a_frame_that_uses_a_part_keeps_its_own_settings():
    drawn = flowparts.expand(small_top(), SMALL_PARTS)
    assert {k: v for k, v in node_of(drawn, "a").items() if k != "steps"} \
        == {"id": "a", "each": "field", "order": "document"}
    assert node_of(drawn, "b")["order"] == "names_first"
    # the failures by construction: a frame that also draws steps of its
    # own, a part that uses a part, a box that uses one
    top = small_top()
    top[1]["steps"] = []
    with pytest.raises(flowparts.PartError, match="draws none"):
        flowparts.expand(top, SMALL_PARTS)
    nested = {"p": [{"id": "inner", "each": "piece", "part": "p"}]}
    with pytest.raises(flowparts.PartError, match="uses none"):
        flowparts.expand(small_top(), nested)
    with pytest.raises(flowparts.PartError, match="only a frame"):
        flowparts.expand([{"id": "c", "box": "ask", "part": "p"}],
                         SMALL_PARTS)


# -- 2. the profiles' steps for one value -----------------------------------------

@pytest.mark.parametrize("name", ["default", "kwp", "scenarios"])
def test_both_frames_of_values_go_through_one_part(name):
    loaded = flow.load(None if name == "default" else load_profile(name))
    uses = flowparts.uses(loaded.top)
    assert {use["id"]: use.get("prefix", "") for use in uses} == FRAMES
    assert {use["part"] for use in uses} == {PART}
    steps = {ident: node_of(loaded.tree, ident)["steps"] for ident in FRAMES}
    assert [flowparts.without_prefix(one, "document_")
            for one in steps["document_values"]] == steps["values"] \
        == loaded.parts[PART]
    # the failure by construction: the same drawing written whole, without
    # parts, uses none
    assert flowparts.uses(loaded.tree) == []


# -- 3. a profile's changes ---------------------------------------------------------

def test_a_profile_writes_only_its_changes():
    for name in ("kwp", "scenarios"):
        written = json.loads((REPO / "profiles" / name / "flow.json")
                             .read_text(encoding="utf-8"))
        assert "changes" in written
        assert "flow" not in written and "parts" not in written
    # the failure by construction: a file that draws and changes
    with pytest.raises(flow.FlowError, match="does one of them"):
        flow.parse(json.dumps({"flow": [], "changes": []}), "flow.json",
                   False)


def test_a_change_to_a_part_reaches_every_frame_that_uses_it(profile):
    box = {"id": "extra", "box": "check_value"}
    flow.path_of(profile).write_text(flow.dump({"changes": [
        {"insert": box, "after": "values_check", "part": PART}]}),
        encoding="utf-8")
    drawn = flow.tree_of(profile)
    assert ids(node_of(drawn, "values")["steps"])[-1] == "extra"
    assert ids(node_of(drawn, "document_values")["steps"])[-1] \
        == "document_extra"
    # the failure by construction: a change that names no step is refused,
    # naming the file
    flow.path_of(profile).write_text(flow.dump({"changes": [
        {"insert": box, "after": "no_such_step", "part": PART}]}),
        encoding="utf-8")
    with pytest.raises(flow.FlowError, match="no_such_step") as caught:
        flow.load(profile)
    assert str(flow.path_of(profile)) in str(caught.value)


# -- 4. a save folds the drawing back ---------------------------------------------

def test_a_change_in_one_frame_is_made_in_every_frame_of_its_part(profile):
    drawn = copy.deepcopy(flow.tree_of(profile))
    node_of(drawn, "values")["steps"].append(
        {"id": "extra", "box": "check_value"})
    report = judge(profile, drawn)
    assert report["ok"], report["errors"]
    assert {"name": "flow", "from": "", "to": "document_extra: added"} \
        in report["changed"]
    loaded = flow.load(profile)
    top, parts = flowparts.fold(drawn, loaded.top, loaded.parts)
    assert ids(parts[PART])[-1] == "extra"
    assert [use["id"] for use in flowparts.uses(top)] == list(FRAMES)
    # a frame whose id the edit changed no longer uses its part
    renamed = copy.deepcopy(flow.tree_of(profile))
    node_of(renamed, "values")["id"] = "values_alone"
    top, _parts = flowparts.fold(renamed, loaded.top, loaded.parts)
    assert [use["id"] for use in flowparts.uses(top)] == ["document_values"]
    assert node_of(top, "values_alone")["steps"]


def test_two_frames_of_one_part_changed_differently_are_refused(profile):
    drawn = copy.deepcopy(flow.tree_of(profile))
    node_of(drawn, "values")["steps"].append(
        {"id": "extra", "box": "check_value"})
    node_of(drawn, "document_values")["steps"].append(
        {"id": "document_other", "box": "check_value"})
    report = judge(profile, drawn)
    assert not report["ok"] and report["writes"] == "unchanged"
    assert "changed differently" in report["errors"][0]["message"]
    # the failure by construction: the same change in both is one change
    node_of(drawn, "document_values")["steps"][-1]["id"] = "document_extra"
    assert judge(profile, drawn)["ok"]


# -- 5. the changes give the drawing ------------------------------------------------

def _edits() -> list:
    """Edits of the default's drawing, each a function of the drawn
    drawing."""
    def set_box(tree):
        node_of(tree, "values_check")["note"] = "checked"

    def insert_frame(tree):
        tree.insert(3, {"id": "new_frame", "each": "piece", "steps": [
            {"id": "new_find", "box": "ask", "preset": "find"}]})

    def move_box(tree):
        steps = node_of(tree, "values")["steps"]
        steps.insert(0, steps.pop())

    def move_across(tree):
        catalogue = next(n for n in tree if n.get("id") == "catalogue")
        tree.remove(catalogue)
        tree.insert(tree.index(next(n for n in tree
                                    if n.get("id") == "compute")), catalogue)

    def remove_frame(tree):
        tree[:] = [n for n in tree if n.get("id") != "untaken_numbers"]

    def new_way(tree):
        for ident in ("coordinate_way", "document_coordinate_way"):
            node_of(tree, ident)["if"].append({"when": {"all": [
                {"of": "coordinate", "is": "kind", "op": "one_of",
                 "value": ["quantity"]}]}, "steps": [
                {"id": ident.replace("coordinate_way", "asked_quantity"),
                 "box": "ask", "preset": "quantity"}]})

    def wrap(tree):
        # a box moved into a new frame around it
        at = next(i for i, n in enumerate(tree) if n.get("id") == "compute")
        tree[at] = {"id": "around", "round": {"most": 1},
                    "steps": [tree[at]]}
    return [set_box, insert_frame, move_box, move_across, remove_frame,
            new_way, wrap]


@pytest.mark.parametrize("edit", _edits(), ids=lambda f: f.__name__)
def test_the_changes_a_save_writes_give_the_drawing(edit):
    base = flow.load(None)
    drawn = copy.deepcopy(base.tree)
    edit(drawn)
    top, parts = flowparts.fold(drawn, base.top, base.parts)
    changes = flowparts.as_changes(base.top, base.parts, top, parts)
    assert changes is not None
    got_top, got_parts = flowparts.apply(base.top, base.parts, changes)
    assert flowparts.expand(got_top, got_parts) \
        == flowparts.expand(top, parts)
    assert len(json.dumps(changes)) < len(json.dumps(top))


def test_a_drawing_the_changes_cannot_say_is_written_whole():
    base = flow.load(None)
    drawn = copy.deepcopy(base.tree)
    drawn.append({"id": "write", "box": "write"})      # an id twice
    top, parts = flowparts.fold(drawn, base.top, base.parts)
    assert flowparts.as_changes(base.top, base.parts, top, parts) is None
    # the failure by construction: without the second one they can
    assert flowparts.as_changes(base.top, base.parts, top[:-1], parts) == []


# -- 6. a drawing left as it was -----------------------------------------------------

def test_a_save_of_numbers_leaves_the_written_changes_as_they_are(profile):
    written = json.loads((REPO / "profiles" / "scenarios" / "flow.json")
                         .read_text(encoding="utf-8"))["changes"]
    # the same changes, the one outside the part first: another way to say
    # them
    changes = written[-1:] + written[:-1]
    assert changes != written
    flow.path_of(profile).write_text(flow.dump({"changes": changes}),
                                     encoding="utf-8")
    numbers = {**flow.load(profile).numbers, "replies": 7}
    report = judge(profile, None, numbers)
    assert json.loads(report["text"]) == {"numbers": {"replies": 7},
                                          "changes": changes}
    same = judge(profile, copy.deepcopy(flow.tree_of(profile)), numbers)
    assert json.loads(same["text"])["changes"] == changes
    # the failure by construction: an edit of the drawing writes the
    # changes anew, in the order a save says them
    drawn = copy.deepcopy(flow.tree_of(profile))
    node_of(drawn, "values_check")["note"] = "checked"
    rewritten = json.loads(judge(profile, drawn, numbers)["text"])
    assert rewritten["changes"] != changes
    assert rewritten["changes"][0]["set"] == "coordinate_way"


# -- 7. what the run reads ---------------------------------------------------------

def test_the_run_reads_the_drawing_with_every_part_drawn(profile):
    loaded = flow.load(None)
    assert not any(flowparts.PART in node for node, _ in
                   flow.walk(loaded.tree))
    assert flowparts.uses(loaded.top)
    # the failure by construction: the drawing as written names its parts
    assert any(flowparts.PART in node for node, *_ in
               flowparts.places(loaded.top))


def test_the_fingerprint_is_that_of_the_drawn_drawing(profile):
    loaded = flow.load(None)
    whole = {"numbers": loaded.numbers, "flow": loaded.tree}
    assert loaded.sha256 == hashlib.sha256(json.dumps(
        whole, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    # the same drawing written whole, without parts, has it too
    flow.path_of(profile).write_text(flow.dump({"flow": loaded.tree}),
                                     encoding="utf-8")
    assert flow.load(profile).sha256 == loaded.sha256
    # the failure by construction: another drawing has another
    other = copy.deepcopy(loaded.tree)
    node_of(other, "values_check")["note"] = "checked"
    flow.path_of(profile).write_text(flow.dump({"flow": other}),
                                     encoding="utf-8")
    assert flow.load(profile).sha256 != loaded.sha256


# -- 8. the copy of a profile --------------------------------------------------------

def test_a_copy_takes_the_numbers_of_the_flow_file_not_its_changes(
        tmp_path):
    source = tmp_path / "source.json"
    source.write_text(flow.dump({"numbers": {"replies": 5},
                                 "changes": [{"remove": "compute"}]}),
                      encoding="utf-8")
    target = tmp_path / "copy.json"
    assert newprofile._copy_flow(source, target)
    assert json.loads(target.read_text(encoding="utf-8")) \
        == {"numbers": {"replies": 5}}
    # the failure by construction: a file of changes alone leaves nothing
    source.write_text(flow.dump({"changes": [{"remove": "compute"}]}),
                      encoding="utf-8")
    target.unlink()
    assert not newprofile._copy_flow(source, target)
    assert not target.exists()


# -- 9. what the page is told ---------------------------------------------------------

def test_the_page_is_told_which_frames_use_a_part():
    told = flow_view.parts_at(flow.load(load_profile("kwp")).top)
    assert told == {
        "document_values": {"part": PART, "prefix": "document_",
                            "with": ["values"]},
        "values": {"part": PART, "prefix": "", "with": ["document_values"]}}
    # the failure by construction: a drawing without parts tells none
    assert flow_view.parts_at(flow.load(load_profile("kwp")).tree) == {}
