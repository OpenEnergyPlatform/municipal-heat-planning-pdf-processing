"""
test_editor_flow.py: what the flow tab of `docpipe edit` promises about the
drawing, the numbers it saves, the settings it shows and what it measures.

Each test states one promise and holds a case that breaks it by
construction: a number the flow does not take, a box the run cannot do, a
file that moved, a secret among the settings, pieces of a search that count
toward no budget. That the run reads the file the page writes is in
test_flow.py and test_flow_engine.py.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import dataclasses
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.editor import flow as flow_view
from docpipe.editor import measured, requests, server
from docpipe.extraction import blocks, flow, trace
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parent.parent
SPEC = {name: json.loads((REPO / "profiles" / name / "extraction_spec.json")
                         .read_text(encoding="utf-8"))
        for name in ("kwp", "scenarios")}
SETTINGS = sorted({number.env for number in flow.NUMBERS if number.env})


@pytest.fixture(autouse=True)
def no_setting_wins(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def profile(tmp_path):
    """scenarios with a folder of its own, its spec and prompts, still
    extending default."""
    home = tmp_path / "scenarios"
    home.mkdir()
    shutil.copy(REPO / "profiles" / "scenarios" / "extraction_spec.json",
                home)
    shutil.copytree(REPO / "profiles" / "scenarios" / "prompts",
                    home / "prompts")
    return dataclasses.replace(load_profile("scenarios"), home=home)


def own_file(profile) -> Path:
    return flow.path_of(profile)


def raw_of(profile):
    path = own_file(profile)
    return path.read_bytes() if path.is_file() else None


def numbers_of(profile, **changed) -> dict:
    return {**flow.load(profile).numbers, **changed}


def view(profile, data=None, computes=False) -> dict:
    return flow_view.view(profile, raw_of(profile),
                          SPEC[profile.name] if data is None else data,
                          lambda path: Path(path).name, computes)


def node_of(tree: list, ident: str) -> dict:
    return next(node for node, _ in flow.walk(tree) if node["id"] == ident)


def number_of(shown: dict, name: str) -> dict:
    return next(n for n in shown["numbers"] if n["name"] == name)


# -- the drawing --------------------------------------------------------------

def test_a_number_says_what_the_files_say_and_where_it_comes_from(
        profile, monkeypatch):
    before = number_of(view(profile), "search_pieces")
    default = flow.default().search_pieces
    assert (before["value"], before["own"], before["inherited"],
            before["owner"], before["in_effect"], before["origin"]) == (
        default, False, default, "default", default, "flow.json of default")
    own_file(profile).write_text(flow.dump(
        {"numbers": {"search_pieces": 35}}), encoding="utf-8")
    after = number_of(view(profile), "search_pieces")
    assert (after["value"], after["own"], after["inherited"],
            after["owner"], after["in_effect"], after["origin"]) == (
        35, True, default, "scenarios", 35, "flow.json of scenarios")
    # the failure by construction: a setting wins for a run started here,
    # and the page still shows and edits what the file says
    monkeypatch.setenv("EXTRACT_SEARCH_PIECES", "7")
    won = number_of(view(profile), "search_pieces")
    assert (won["value"], won["in_effect"], won["origin"]) == (
        35, 7, "environment")


def test_every_number_a_box_takes_is_a_named_number_the_page_is_sent(
        profile):
    shown = view(profile)
    sent = {number["name"] for number in shown["numbers"]}
    taken = {setting["number"] for box in shown["library"]["boxes"]
             for setting in box["settings"]
             if setting["kind"] == "number"}
    assert taken and taken <= sent
    # the drawing on disk is the one the run does, and the page is sent it
    assert shown["tree"] == flow.tree_of(profile) and shown["problems"] == []
    # the failure by construction: a box that takes no number shows none
    beside = next(box for box in shown["library"]["boxes"]
                  if box["type"] == "beside")
    assert [s for s in beside["settings"] if s["kind"] == "number"] == []


def test_a_box_no_run_of_the_profile_takes_says_why():
    kwp, scenarios = load_profile("kwp"), load_profile("scenarios")
    plans = view(kwp, computes=True)
    papers = view(scenarios)
    # the works and names of scenario papers are boxes of their profile,
    # which the page of the heat plans does not offer; scenarios writes no
    # prompt for the calculation
    def offered(shown):
        return {box["type"] for box in shown["library"]["boxes"]} \
            | {one["name"] for one in shown["library"]["presets"]}
    assert "works" not in offered(plans) and "names" not in offered(plans)
    assert {"works", "names"} <= offered(papers)
    assert "works" not in plans["never"]
    assert "extraction/compute" in papers["never"]["compute"]
    assert "works" not in papers["never"]
    assert "compute" not in plans["never"]
    assert papers["prompts"]["work"] == {
        "id": "extraction/work", "written": True, "owner": "scenarios"}
    # the failures by construction: the prompt is written and the spec or
    # the profile does not ask for the box
    assert view(kwp, computes=False)["never"]["compute"] \
        == ("This profile computes nothing, so the step never takes "
            "part in a run.")
    bare = copy.deepcopy(SPEC["scenarios"])
    del bare["works"]
    assert view(scenarios, bare)["never"]["works"] \
        == ("The spec keeps no list of other works, so every value belongs "
            "to this publication. To change it: add the works in the Spec "
            "tab.")


def test_a_switch_lists_what_the_spec_says_and_leads_into_it():
    shown = view(load_profile("scenarios"))
    once = shown["switches"]["once_per_document"]
    marked = [p["uri"] for p in SPEC["scenarios"]["parameters"]
              if p.get("once_per_document")]
    assert [item["label"] for item in once["items"]] == marked and marked
    assert once["items"][0]["to"] == {"t": "param", "uri": marked[0]}
    taken = shown["switches"]["takes_group"]
    assert [item["label"] for item in taken["items"]] == ["scenario_abstract"]
    switches = view(load_profile("kwp"))["switches"]
    assert [item["label"] for item in switches["own_passage"]["items"]] == [
        "unit (number)", "what (number)", "subject (number)",
        "aggregation (context)", "role (context)"]
    assert [item["label"] for item in switches["own_value"]["items"]] == [
        "qualifier (number)"]
    # the failure by construction: a spec that marks nothing lists nothing
    # and says so
    bare = copy.deepcopy(SPEC["kwp"])
    for group in bare["groups"].values():
        group.pop("own_passage", None)
    first = view(load_profile("kwp"), bare)["switches"]["own_passage"]
    assert first["items"] == [] and first["none"]


def test_the_rule_for_a_pass_over_a_stored_harvest_stands_below_the_drawing():
    notes = view(load_profile("kwp"))["notes"]
    assert [note["to"] for note in notes] == [
        {"t": "plan", "key": "base_year"}, {"t": "plan", "key": "target_year"}]
    assert "scenario = status_quo" in notes[0]["says"]
    assert "scenario = target" in notes[1]["says"]
    assert all("--top-up" in note["says"] for note in notes)
    # the failure by construction: a spec that says no such rule has no note
    assert view(load_profile("scenarios"))["notes"] == []


# -- check and save -----------------------------------------------------------

def test_a_save_writes_only_what_differs_from_the_inherited(profile):
    report = flow_view.judge(profile, None,
                             numbers_of(profile, search_pieces=35),
                             "flow.json")
    assert report["ok"] and report["writes"] == "created"
    assert json.loads(report["text"]) == {"numbers": {"search_pieces": 35}}
    assert "\r" not in report["text"]      # a new file has plain line ends
    assert report["changed"] == [{"name": "search_pieces",
                                  "from": flow.default().search_pieces,
                                  "to": 35}]
    assert report["diff"][-5:] == ['+{', '+  "numbers": {',
                                   '+    "search_pieces": 35', '+  }', '+}']
    # the failure by construction: nothing changed, nothing to write
    same = flow_view.judge(profile, None, numbers_of(profile), "flow.json")
    assert (same["writes"], same["text"], same["diff"], same["changed"]) == (
        "unchanged", None, [], [])


def test_a_drawing_is_written_only_where_it_differs_from_the_inherited(
        profile):
    tree = copy.deepcopy(flow.tree_of(profile))
    node_of(tree, "search_round")["round"] = {"most": 3}
    report = flow_view.judge(profile, None, numbers_of(profile), "flow.json",
                             tree)
    assert report["ok"] and report["writes"] == "created"
    assert json.loads(report["text"]) == {"flow": tree}
    assert report["changed"] == [{"name": "flow", "from": "",
                                  "to": "search_round: changed"}]
    # the failure by construction: the inherited drawing writes nothing
    same = flow_view.judge(profile, None, numbers_of(profile), "flow.json",
                           copy.deepcopy(flow.tree_of(profile)))
    assert (same["writes"], same["text"], same["changed"]) == (
        "unchanged", None, [])


def test_a_drawing_the_run_cannot_do_is_refused_at_its_box(profile):
    tree = copy.deepcopy(flow.tree_of(profile))
    # a search outside any coordinate, and a box no library knows
    tree.insert(1, {"id": "lost_search", "box": "ask", "preset": "search"})
    tree.insert(1, {"id": "made_up", "box": "no_such_box"})
    report = flow_view.judge(profile, None, numbers_of(profile), "flow.json",
                             tree)
    assert not report["ok"] and report["writes"] == "unchanged"
    assert {"lost_search", "made_up"} <= {e["id"] for e in report["errors"]}
    told, written, remove = flow_view.save(profile, None, numbers_of(profile),
                                           None, "flow.json", tree)
    assert (told["saved"], told["reason"], written, remove) == (
        False, "invalid", None, False)
    # the failure by construction: without the two the drawing is saved
    del tree[1:3]
    assert flow_view.judge(profile, None, numbers_of(profile), "flow.json",
                           tree)["ok"]


def test_what_an_edit_did_to_the_drawing_is_said_one_line_each():
    old = [{"id": "a", "box": "ask", "preset": "find"},
           {"id": "b", "box": "write"},
           {"id": "c", "each": "value", "steps": [{"id": "d",
                                                  "box": "settle"}]}]
    new = [{"id": "b", "box": "write"},
           {"id": "a", "box": "ask", "preset": "find", "off": True},
           {"id": "c", "each": "value", "steps": [{"id": "e",
                                                  "box": "state"}]}]
    assert flow_view.tree_changes(old, new) == [
        "e: added", "d: removed", "a: changed", "moved: b, a"]
    # the failure by construction: the same drawing says nothing
    assert flow_view.tree_changes(old, copy.deepcopy(old)) == []


def test_a_number_set_back_leaves_the_file_and_an_empty_file_goes(profile):
    own_file(profile).write_text(flow.dump(
        {"numbers": {"search_pieces": 35, "replies": 5}}), encoding="utf-8")
    default = flow.default()
    one = flow_view.judge(profile, raw_of(profile), numbers_of(
        profile, search_pieces=default.search_pieces), "flow.json")
    assert one["writes"] == "changed"
    assert json.loads(one["text"]) == {"numbers": {"replies": 5}}
    none = flow_view.judge(profile, raw_of(profile), numbers_of(
        profile, search_pieces=default.search_pieces,
        replies=default.replies), "flow.json")
    assert (none["writes"], none["text"]) == ("removed", None)
    told, written, remove = flow_view.save(
        profile, raw_of(profile), numbers_of(
            profile, search_pieces=default.search_pieces,
            replies=default.replies),
        flow_view.sha256(raw_of(profile)), "flow.json")
    assert (told["saved"], told["writes"], told["base"], written,
            remove) == (True, "removed", None, None, True)


@pytest.mark.parametrize("change, name, said", [
    ({"search_pieces": 0}, "search_pieces", "must be at least 1, not 0"),
    ({"replies": "3"}, "replies", "must be a whole number"),
    ({"replies": 2.5}, "replies", "must be a whole number"),
    ({"LLM_API_KEY": 1}, None, "is no number of the flow"),
    # beside a number that holds: nothing of the edit is written
    ({"search_pieces": 35, "replies": 0}, "replies",
     "must be at least 1, not 0"),
])
def test_what_the_flow_does_not_take_is_not_written(profile, change, name,
                                                    said):
    numbers = numbers_of(profile, **change)
    report = flow_view.judge(profile, None, numbers, "flow.json")
    assert not report["ok"] and report["writes"] == "unchanged"
    assert [(error["name"], said in error["message"])
            for error in report["errors"]] == [(name, True)]
    told, written, remove = flow_view.save(profile, None, numbers, None,
                                           "flow.json")
    assert (told["saved"], told["reason"], written, remove) == (
        False, "invalid", None, False)


def test_a_file_that_moved_is_not_overwritten(profile):
    own_file(profile).write_text(flow.dump(
        {"numbers": {"replies": 5}}), encoding="utf-8")
    numbers = numbers_of(profile, search_pieces=35)
    told, written, remove = flow_view.save(
        profile, raw_of(profile), numbers, flow_view.sha256(b"older"),
        "flow.json")
    assert (told["saved"], told["reason"], written, remove) == (
        False, "moved", None, False)
    # the failure by construction: with the file's own sha256 it is written
    told, written, _ = flow_view.save(
        profile, raw_of(profile), numbers,
        flow_view.sha256(raw_of(profile)), "flow.json")
    assert told["saved"] and json.loads(written) == {
        "numbers": {"search_pieces": 35, "replies": 5}}
    assert told["base"] == flow_view.sha256(written)


def test_the_line_ends_of_the_file_stay(profile):
    crlf = flow.dump({"numbers": {"replies": 5}}, "\r\n").encode("utf-8")
    own_file(profile).write_bytes(crlf)
    report = flow_view.judge(profile, crlf,
                             numbers_of(profile, search_pieces=35),
                             "flow.json")
    assert report["text"].count("\r\n") == report["text"].count("\n") > 0
    # the failure by construction: a file of plain line ends keeps those
    plain = flow.dump({"numbers": {"replies": 5}}).encode("utf-8")
    own_file(profile).write_bytes(plain)
    report = flow_view.judge(profile, plain,
                             numbers_of(profile, search_pieces=35),
                             "flow.json")
    assert "\r" not in report["text"]


def test_the_whole_file_keeps_its_drawing_and_changes_one_line(tmp_path):
    home = tmp_path / "default"
    home.mkdir()
    shutil.copy(flow.DEFAULT, home)
    whole = dataclasses.replace(load_profile("default"), home=home)
    raw = own_file(whole).read_bytes()
    replies = flow.load(whole).numbers["replies"]
    report = flow_view.judge(whole, raw,
                             numbers_of(whole, replies=replies + 1),
                             "flow.json")
    assert report["writes"] == "changed"
    changed = [line for line in report["diff"][2:]
               if line[:1] in "+-"]
    assert changed == [f'-    "replies": {replies}',
                       f'+    "replies": {replies + 1}']
    assert json.loads(report["text"])["flow"] == json.loads(raw)["flow"]
    # every number is its own there: none is inherited
    shown = flow_view.view(whole, raw, None, str)
    assert shown["whole"] and all(n["own"] and n["inherited"] is None
                                  for n in shown["numbers"])


# -- the server ---------------------------------------------------------------

def make_app(tmp_path, profile, harvest=None) -> server.App:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    app = server.App(profile, harvest, root)
    app.spec_path = Path(profile.package_dir) / "extraction_spec.json"
    return app


def post(app, path: str, body):
    return app.call("POST", path, {}, body)


def test_the_page_is_given_the_flow_and_a_check_writes_nothing(tmp_path,
                                                               profile):
    app = make_app(tmp_path, profile)
    status, shown = app.call("GET", "/api/flow", {}, None)
    assert status == 200 and not shown["exists"] and shown["base"] is None
    assert "flow" in app.call("GET", "/api/state", {}, None)[1]["tabs"]
    numbers = {n["name"]: n["value"] for n in shown["numbers"]}
    tree = copy.deepcopy(shown["tree"])
    node_of(tree, "search_round")["round"] = {"most": 3}
    status, report = post(app, "/api/flow/check",
                          {"numbers": {**numbers, "search_pieces": 35},
                           "tree": tree})
    assert status == 200 and report["writes"] == "created"
    assert {"name": "flow", "from": "", "to": "search_round: changed"} \
        in report["changed"]
    assert "text" not in report and not own_file(profile).exists()
    # the failure by construction: a save does write, into the profile's
    # own folder, and a save back to the inherited takes the file away
    status, told = post(app, "/api/flow/save", {
        "numbers": {**numbers, "search_pieces": 35}, "base": None,
        "tree": tree})
    assert told["saved"] and json.loads(own_file(profile).read_text(
        encoding="utf-8")) == {"numbers": {"search_pieces": 35},
                               "flow": tree}
    assert told["base"] == server.sha256(own_file(profile).read_bytes())
    assert flow.DEFAULT.read_bytes() == (
        REPO / "docpipe" / "builtin" / "default" / "flow.json").read_bytes()
    status, told = post(app, "/api/flow/save", {
        "numbers": numbers, "base": told["base"],
        "tree": shown["tree"]})
    assert told["writes"] == "removed" and not own_file(profile).exists()


def test_a_refused_number_leaves_the_file_as_it_was(tmp_path, profile):
    own_file(profile).write_text(flow.dump(
        {"numbers": {"replies": 5}}), encoding="utf-8")
    before = own_file(profile).read_bytes()
    app = make_app(tmp_path, profile)
    numbers = numbers_of(profile, search_pieces=0)
    status, told = post(app, "/api/flow/save", {
        "numbers": numbers, "base": server.sha256(before)})
    assert status == 200 and not told["saved"]
    assert told["errors"][0]["name"] == "search_pieces"
    assert own_file(profile).read_bytes() == before


def test_no_key_and_no_token_is_shown_or_written(tmp_path, profile,
                                                 monkeypatch):
    secret, password = "sk-very-secret-0815", "hunter2"
    monkeypatch.setenv("LLM_API_KEY", secret)
    monkeypatch.setenv("CODE_EXEC_TOKEN", secret)
    monkeypatch.setenv("LLM_BASE_URL", f"https://felix:{password}@llm.test/v1")
    monkeypatch.setenv("LLM_MODEL", "a-model-anyone-may-see")
    app = make_app(tmp_path, profile)
    status, shown = app.call("GET", "/api/flow", {}, None)
    sent = json.dumps(shown)
    assert status == 200 and secret not in sent and password not in sent
    by_env = {setting["env"]: setting for setting in shown["settings"]}
    assert (by_env["LLM_API_KEY"]["value"], by_env["LLM_API_KEY"]["set"],
            by_env["LLM_API_KEY"]["secret"]) == (None, True, True)
    assert by_env["LLM_BASE_URL"]["value"] == "https://***@llm.test/v1"
    # the failure by construction: what is no secret is shown as it is set
    assert by_env["LLM_MODEL"]["value"] == "a-model-anyone-may-see"
    assert by_env["LLM_MODEL"]["origin"] == "environment"
    # and nothing but a number of the flow is written: a setting is refused,
    # in the numbers as in a box of the drawing
    numbers = {n["name"]: n["value"] for n in shown["numbers"]}
    status, told = post(app, "/api/flow/save", {
        "numbers": {**numbers, "LLM_API_KEY": secret}, "base": None})
    assert not told["saved"] and not own_file(profile).exists()
    tree = copy.deepcopy(shown["tree"])
    node_of(tree, "search")["own"] = {"LLM_API_KEY": secret}
    status, told = post(app, "/api/flow/save", {
        "numbers": numbers, "base": None, "tree": tree})
    assert not told["saved"] and not own_file(profile).exists()


# -- what the traces say ------------------------------------------------------

def search(value: str, *asked) -> list:
    """The requests of one value's search: (pieces shown, what they are or
    None, whether the answer names a place) each."""
    out = []
    for chunks, shows, place in asked:
        out.append({"kind": "search", "doc": 86, "parameter": "p",
                    "coordinate": "year", "owner": 7, "value": value,
                    "chunks": chunks, "attempt": 1, "check": "taken",
                    "answer": "{}", "user": "{}",
                    "answer_json": {"at": "A1", "words": "2030"} if place
                    else {"at": 0},
                    **({"shows": shows} if shows else {})})
    return out


def searches(noted: bool = True) -> list:
    def kind(shows):
        return shows if noted else None
    return (search("R1", (2, kind("near"), False), (4, kind("found"), True))
            + search("R2", *[(5, kind("found"), False)] * 7,
                     (3, kind("fetched"), False), (1, kind("found"), True))
            + search("R3", *[(5, kind("found"), False)] * 10,
                     (1, kind("found"), True))
            + search("R4", (2, kind("near"), False),
                     (5, kind("found"), False)))


def test_a_budget_is_measured_by_the_places_that_came_after_it():
    assert measured.after([4, 36, 51], 35) == 2
    assert (measured.after([4, 36, 51], 51),
            measured.after([4, 36, 51], 3)) == (0, 3)
    found = measured.facts(searches())
    assert [(s["after"], s["found"]) for s in found["searches"]] == [
        (4, True), (36, True), (51, True), (5, False)]
    said = measured.says(found, {"search_pieces": 35,
                                 "search_per_request": 5})
    (searched, budget), (per_request,) = said["search_pieces"], \
        said["search_per_request"]
    assert searched == "Of 4 searches for an open dimension, 3 ended with " \
        "an answer that gives a line number and 1 without one."
    assert budget == "Those answers came after 4 to 51 shown chunks of " \
        "the budget, half of them within 36, 2 of them only after more " \
        "than 35."
    assert per_request == "The 4 searches sent 24 requests, 6.0 each on " \
        "average."
    assert measured.notes(found) == []
    # the failure by construction: a trace that does not say which pieces
    # count has every piece counted, and says so
    found = measured.facts(searches(noted=False))
    assert [s["after"] for s in found["searches"]] == [6, 39, 51, 7]
    (_, budget) = measured.says(found, {"search_pieces": 35,
                                        "search_per_request": 5})[
        "search_pieces"]
    assert budget.startswith("Those answers came after 6 to 51 shown "
                             "chunks, half")
    assert measured.notes(found) == [measured.NOT_NOTED]


def test_replies_are_measured_by_the_attempt_they_were_read_at():
    asked = [{"kind": "find", "doc": 1, "attempt": attempt, "answer": "{}",
              "answer_json": {}, "user": "{}", "check": check}
             for attempt, check in ((1, "taken"), (1, "taken"),
                                    (1, "unreadable: syntax"), (2, "taken"),
                                    (3, "taken"))]
    found = measured.facts(asked)
    assert found["read"] == {1: 2, 2: 1, 3: 1}
    assert found["unreadable"] == {"syntax": 1}
    (said, lost) = measured.says(found, {"replies": 2})["replies"]
    assert said == "4 replies were read, 1 of them only after more than 2 " \
        "attempts. Attempt \u2192 replies read: 1 \u2192 2; 2 \u2192 1; " \
        "3 \u2192 1."
    # a cause is named as code, as the request log names it
    assert lost == "1 reply could not be read, by cause: `syntax` 1."
    # the failure by construction: a number that is none says nothing
    assert measured.says(found, {"replies": ""}) == {}


def test_what_the_traces_say_stands_at_the_number_it_measures():
    said = measured.says(measured.facts(searches()), {
        number.name: getattr(flow.default(), number.name)
        for number in flow.NUMBERS})
    assert said and set(said) <= {number.name for number in flow.NUMBERS}
    # the failure by construction: no numbers, nothing said
    assert measured.says(measured.facts(searches()), {}) == {}


def test_a_request_is_counted_at_the_box_that_asked_it():
    # the boxes of every profile's flow: a step a profile brings itself
    # stands in its own flow (owner decision 2026-11-12)
    boxes = {node["id"]: node for name in ("default", "kwp", "scenarios")
             for node, _ in flow.walk(flow.load(load_profile(name)).tree)
             if "box" in node}
    assert set(measured.STEPS) <= set(boxes)
    kinds = {measured.step_of({"kind": kind, **notes})
             for kind in flow.kinds()
             for notes in ({}, {"coordinate": "year"}, {"shows": "near"},
                           {"step": "plan_years"},
                           {"parameter": "settings"})}
    assert kinds - {None} == set(measured.STEPS)
    # an old request without a box is counted at a box that asks its kind
    for kind in flow.kinds():
        step = measured.step_of({"kind": kind})
        if step is not None:
            assert blocks.box_of(boxes[step]).asks == kind
    # a request that names its box is counted there, a follow-up at its
    # question's box
    found = measured.facts([
        {"kind": "search", "box": "document_search", "doc": 1},
        {"kind": "search", "doc": 1},
        {"kind": "follow", "asked": "search", "doc": 1}])
    assert found["steps"] == {"document_search": 1, "search": 2}
    # the failure by construction: a request of no box is counted nowhere
    assert measured.step_of({"kind": "review"}) is None
    assert measured.step_of({"kind": "follow"}) is None


def reply(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason="stop")])


@pytest.fixture
def harvest(tmp_path, monkeypatch):
    """A harvest folder with one trace, written by the run's own writer."""
    folder = tmp_path / "harvest"
    monkeypatch.setenv("EXTRACT_TRACE", "1")
    rules.reset()
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_name_of", None)
    trace.open_trace(folder, lambda document_id: f"doc{document_id}")

    def ask(kind: str, payload: dict, answer: str, **notes) -> None:
        trace.exchanged({"model": "m", "messages": [
            {"role": "system", "content": "The rules of the request. " * 30},
            {"role": "user", "content": json.dumps(payload, indent=1)}]},
            reply(answer))
        trace.event(f"{kind}_ask", 86, attempt=notes.pop("attempt", 1),
                    ms=1, prompt_tokens=10, completion_tokens=2, **notes)

    entries = [f"{i} Eintrag {i} (means: {'ein langer Text ' * 6})"
               for i in range(1, 31)]
    ask("docfield", {"field": {"name": "Titel"}, "list": entries[:3]},
        '{"found": [{"at": "T1", "words": "Plan", "entry": 1}]}',
        parameter="study_sector", chunks=5)
    ask("docfield", {"field": {"name": "Titel"}}, '{"found": []}',
        parameter="publication_title", chunks=5)
    ask("list", {"words": "Gas", "list": entries}, '{"entry": 2}',
        parameter="p", coordinate="carrier")
    ask("find", {"passage": {}}, "no json at all", parameter="p", owner=7)
    trace.event("error", 86, where="find", kind="unreadable",
                cause="no_object", attempt=1)
    ask("find", {"passage": {}}, '{"found": []}', parameter="p", owner=7,
        attempt=2)
    ask("search", {"value": {}}, '{"at": 0}', parameter="p",
        coordinate="year", owner=7, value="R1", chunks=2, shows="near")
    ask("search", {"value": {}}, '{"at": "A1", "words": "2030"}',
        parameter="p", coordinate="year", owner=7, value="R1", chunks=5,
        shows="found")
    ask("follow", {"value": {}}, '{"at": 0}', parameter="p",
        coordinate="year", owner=7, value="R1", asked="search")
    trace.close()
    trace._thread.exchange = None
    return folder


def test_a_trace_is_counted_without_putting_its_requests_back_together(
        harvest):
    path = trace.path_of(harvest, "doc86")
    light = measured.facts(measured.light(trace.lines(path)))
    full = measured.facts(requests.Trace(path, list(trace.lines(path)))
                          .requests)
    assert light == full
    assert light["requests"] == 8
    assert light["lists"] == [30]
    assert light["docfields"] == {"plain": [], "listed": [5]}
    assert light["unreadable"] == {"no_object": 1}
    assert light["read"] == {1: 6, 2: 1}
    assert light["follow"] == {"search": 1}
    assert light["searches"] == [{"requests": 2, "noted": True, "after": 5,
                                  "found": True}]
    # the follow-up is counted at the search it follows
    assert light["steps"]["beside"] == 1 and light["steps"]["search"] == 2


def test_the_page_is_told_what_was_measured_and_why_not(tmp_path, profile,
                                                        harvest):
    numbers = numbers_of(profile, search_pieces=4)
    app = make_app(tmp_path, profile, harvest)
    status, told = post(app, "/api/flow/measured", {"numbers": numbers,
                                                    "trace": None})
    assert (status, told["harvest"], told["why"], told["traces"],
            told["requests"]) == (200, True, None, 1, 8)
    assert told["says"]["search_pieces"][1].endswith(
        "1 of them only after more than 4.")
    assert set(told["says"]) <= {number.name for number in flow.NUMBERS}
    assert told["steps"]["finds"] == 2
    # asked for by name it is the same trace; one that is not there is not
    assert post(app, "/api/flow/measured", {
        "numbers": numbers, "trace": "doc86"})[1]["says"] == told["says"]
    assert post(app, "/api/flow/measured", {"numbers": numbers,
                                            "trace": "doc1"})[0] == 404
    # the failures by construction: no harvest, and a harvest without a trace
    bare = make_app(tmp_path, profile)
    assert post(bare, "/api/flow/measured", {"numbers": numbers})[1] == {
        "harvest": False, "why": "No harvest folder was given to the page "
        "(--harvest), so there is no request log to show.",
        "traces": 0, "requests": 0, "says": {}, "steps": {}, "notes": []}
    (tmp_path / "empty").mkdir()
    told = post(make_app(tmp_path, profile, tmp_path / "empty"),
                "/api/flow/measured", {"numbers": numbers})[1]
    assert told["harvest"] and "holds no request log" in told["why"]
