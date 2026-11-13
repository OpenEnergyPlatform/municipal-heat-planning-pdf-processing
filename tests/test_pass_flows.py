"""
test_pass_flows.py: what the flows of the follow-up passes promise
(`extraction.passflow`, `extraction.passboxes`, the flow files under
`docpipe/builtin/default/flows/`).

Each test states one promise and holds a case that breaks it by
construction: a switch that names another flow, a box that is off, a value
a box sets that must not outlive it, two passes that write one folder, a
profile's own file over the shipped one, a request without the values of
its box. That the passes do what they did before (the same requests, the
same files) is the probe of the change, not a test: it needs a model.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import dataclasses
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.editor import flow as flow_view
from docpipe.editor import server
from docpipe.extraction import (blocks, engine, fields, passboxes, passflow,
                                recheck, runner)
from docpipe.extraction import flow as flow_map
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parent.parent
FLOWS = REPO / "docpipe" / "builtin" / "default" / "flows"
SPEC = load_spec(json.loads(
    (REPO / "profiles" / "kwp" / "extraction_spec.json").read_text(
        encoding="utf-8")))
NAMES = ("top_up", "top_up_open", "top_up_parameters", "remap", "recheck",
         "review", "start_at", "example")


@pytest.fixture
def profile(tmp_path):
    """scenarios with a folder of its own, still extending default."""
    home = tmp_path / "scenarios"
    home.mkdir()
    return dataclasses.replace(load_profile("scenarios"), home=home)


def switches(**on) -> Namespace:
    given = {switch: None if switch == "start_at" else False
             for switch, _name in runner.SWITCH_FLOWS}
    return Namespace(**{**given, "flow": None, **on})


def write_flow(profile, name: str, tree: list) -> Path:
    path = passflow.path_of(profile, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(passflow.dump(tree), encoding="utf-8")
    return path


def harvest_of(tmp_path: Path) -> Path:
    """A harvest of one document that holds a summary and nothing else: it
    is enough for the passes that ask no model."""
    out = tmp_path / "harvest"
    out.mkdir(parents=True)
    (out / "a.jsonl").write_text(
        json.dumps({"kind": "summary", "document_id": 1}) + "\n",
        encoding="utf-8")
    (out / "a.stamp.json").write_text("{}", encoding="utf-8")
    return out


def run_of(out: Path) -> passflow.Run:
    return passflow.Run(out=out, spec=SPEC, current={},
                        document_spec=lambda document_id: SPEC)


@pytest.fixture
def seen(monkeypatch):
    """The boxes that run, in order, by id: every act of the library laid
    over by one that notes the node and does what it did."""
    ran: list = []
    for kind, act in dict(passboxes.ACTS).items():
        def noting(run, doc, node, _act=act):
            ran.append(node["id"])
            return _act(run, doc, node)
        monkeypatch.setitem(passboxes.ACTS, kind, noting)
    return ran


# -- the switches choose a flow -----------------------------------------------

@pytest.mark.parametrize("switch, name", runner.SWITCH_FLOWS)
def test_each_switch_runs_exactly_the_flow_it_names(switch, name):
    on = {switch: [Path("x")] if switch == "start_at" else True}
    assert runner.chosen_flow(switches(**on)) == (name, None)
    named = switches(**on)
    named.flow = name
    assert runner.chosen_flow(named) == (name, None)
    # the failure by construction: --flow names another flow than the switch
    other = switches(**on)
    other.flow = "main" if name != "main" else "remap"
    chosen, why = runner.chosen_flow(other)
    assert why and "name two flows" in why
    assert runner.chosen_flow(switches()) == (passflow.MAIN, None)


def test_a_switch_and_its_flow_run_the_same_boxes(tmp_path, seen):
    """--recheck is the flow recheck: the boxes that run are those of the
    file, in its order; with a box off they are the file's without it."""
    wanted = [node["id"] for node in passflow.load("recheck")
              if "each" not in node]
    recheck.run(harvest_of(tmp_path), SPEC)
    assert seen == wanted
    seen.clear()
    passflow.run_named("recheck", run_of(harvest_of(tmp_path / "again")))
    assert seen == wanted
    # the failure by construction: the order is the file's, so a flow
    # without the quotes check runs no check of quotes
    tree = copy.deepcopy(passflow.load("recheck"))
    tree[1]["off"] = True
    seen.clear()
    passflow.run_flow(tree, run_of(harvest_of(tmp_path / "third")))
    assert seen == [i for i in wanted if i != "recheck_recheck"]


def test_a_flow_the_profile_does_not_have_is_refused_with_its_names(profile):
    said = runner.follow_up_problem("nothing", profile)
    assert said and "no such flow" in said and "recheck" in said
    assert runner.follow_up_problem("recheck", profile) is None
    assert runner.follow_up_problem(passflow.MAIN, profile) is None


def test_a_flow_no_run_starts_is_refused_before_the_start(profile):
    said = runner.follow_up_problem("example", profile)
    assert said and "not a step a run starts" in said
    # the failure by construction: the same flow with its box off has
    # nothing left that no run starts
    tree = copy.deepcopy(passflow.load("example"))
    tree[0]["off"] = True
    assert passflow.startable(tree) is None


# -- boxes that are off, values that stay -------------------------------------

def test_a_box_that_is_off_does_not_run(tmp_path, seen):
    out = harvest_of(tmp_path)
    tree = copy.deepcopy(passflow.load("recheck"))
    recheck_box = next(n for n in tree if n["box"] == "recheck")
    recheck_box["off"] = True
    stats = passflow.run_flow(tree, run_of(out))
    assert "recheck_recheck" not in seen and not stats["summaries rewritten"]
    # the failure by construction: on, the same box counts the summary
    recheck_box["off"] = False
    assert passflow.run_flow(tree, run_of(harvest_of(tmp_path / "b")))[
        "summaries rewritten"] == 1


def test_a_boxs_values_hold_inside_it_and_not_after_it(tmp_path,
                                                       monkeypatch):
    held: dict = {}
    for kind in ("recheck", "summary"):
        def noting(run, doc, node, _kind=kind):
            held[_kind] = (rules.get("temperature"), rules.get("max_tokens"))
        monkeypatch.setitem(passboxes.ACTS, kind, noting)
    tree = copy.deepcopy(passflow.load("recheck"))
    next(n for n in tree if n["box"] == "recheck")["rules"] = {
        "temperature": 0.7, "max_tokens": 33}
    outside = (rules.get("temperature"), rules.get("max_tokens"))
    passflow.run_flow(tree, run_of(harvest_of(tmp_path)))
    assert held["recheck"] == (0.7, 33)
    assert held["summary"] == outside != held["recheck"]
    assert (rules.get("temperature"), rules.get("max_tokens")) == outside


def test_a_frame_of_a_pass_lays_its_values_over_the_boxes_inside(
        tmp_path, monkeypatch):
    held: list = []

    def noting(run, doc, node):
        held.append(rules.get("reread_refused_becomes_refusal"))
    monkeypatch.setitem(passboxes.ACTS, "better", noting)
    monkeypatch.setitem(passboxes.ACTS, "take_back", lambda *a: None)
    tree = [{"id": "s", "box": "stored", "set": {"files": "all"}},
            {"id": "o", "box": "open"},
            {"id": "e", "each": "dimension",
             "rules": {"reread_refused_becomes_refusal": "keep_old"},
             "steps": [{"id": "t", "box": "take_back"},
                       {"id": "b", "box": "better"}]}]
    assert [one["id"] for one in passflow.problems(tree)] == []
    doc = SimpleNamespace(units=[1, 2], stop=False, unit=None)
    passflow.run_node(run_of(tmp_path), doc, tree[2])
    assert held == ["keep_old", "keep_old"]
    # the failure by construction: outside the frame the run's value
    assert rules.get("reread_refused_becomes_refusal") == "refusal"


# -- two flows that write one folder ------------------------------------------

def test_two_passes_that_share_a_trace_folder_never_run_together(capsys):
    said = passflow.shared_trace("top_up", "top_up_parameters")
    assert said and "trace-topup" in said and "do not run together" in said
    # the failure by construction: passes with folders of their own
    assert passflow.shared_trace("top_up", "top_up_open") is None
    assert passflow.shared_trace("top_up_open", "top_up_parameters") is None
    with pytest.raises(SystemExit):
        runner.main(["db.sqlite", "index.bin", "out", "--top-up",
                     "--top-up-parameters"])
    refused = capsys.readouterr().err
    assert "not combined with --top-up" in refused
    assert "trace-topup" in refused


def test_the_two_passes_stop_sharing_when_a_profile_moves_one_folder(profile):
    tree = copy.deepcopy(passflow.load("top_up_parameters"))
    tree[0]["set"]["trace"] = "trace-parameters"
    write_flow(profile, "top_up_parameters", tree)
    assert passflow.shared_trace("top_up", "top_up_parameters",
                                 profile) is None
    assert passflow.shared_trace("top_up", "top_up_parameters") is not None


# -- the profile's own file wins ----------------------------------------------

def test_a_profiles_own_flow_wins_over_the_shipped_one(profile):
    shipped = passflow.load("remap", profile)
    assert shipped == passflow.load("remap")
    own = copy.deepcopy(shipped)
    next(n for n in own if n["box"] == "carry_stamp")["off"] = True
    path = write_flow(profile, "remap", own)
    assert passflow.load("remap", profile) == own != shipped
    # the failure by construction: the file is the profile's alone
    assert passflow.load("remap") == shipped
    path.unlink()
    assert passflow.load("remap", profile) == shipped


def test_a_profile_may_have_a_flow_of_its_own_name(profile):
    assert "mine" not in passflow.names(profile)
    write_flow(profile, "mine", passflow.load("remap"))
    assert "mine" in passflow.names(profile)
    assert "mine" not in passflow.names(None)
    assert runner.follow_up_problem("mine", profile) is None


def test_a_flow_that_cannot_run_is_refused_with_its_reason(profile):
    tree = [{"id": "c", "box": "recheck"}]
    said = passflow.problems(tree)
    assert said and "takes the documents" in said[0]["message"]
    write_flow_text = passflow.path_of(profile, "broken")
    write_flow_text.parent.mkdir(parents=True, exist_ok=True)
    write_flow_text.write_text(passflow.dump(tree), encoding="utf-8")
    with pytest.raises(flow_map.FlowError):
        passflow.load("broken", profile)
    assert "broken" in (runner.follow_up_problem("broken", profile) or "")


# -- the review asks with the values of its box -------------------------------

def asked_by_review(monkeypatch) -> tuple:
    seen: list = []

    def create(**request):
        seen.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content="{}", reasoning_content=None))], usage=None)
    monkeypatch.setattr(runner, "_client", lambda *a, **k: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    parameter = SPEC.parameters[0]
    row = {"parameter": parameter.uri, "value": 5, "quote": "Der Wert 5",
           "provenance": {"owner_kind": "section", "owner_id": 1}}
    shown = [Source("section", 1, "Der Wert 5 MWh.",
                    {"document_id": 1, "page": 1})]
    runner.make_review_asker(None)(row, shown, parameter,
                                   fields.asked_slots(parameter)[:1])
    return seen[0]["temperature"], seen[0]["max_tokens"]


def test_the_review_request_asks_with_the_values_of_its_box(monkeypatch):
    for name in ("_HOMES", "_FLOW_NODES"):
        monkeypatch.setattr(runner, name, {})
    monkeypatch.setattr(runner, "NUMBERS", runner.NUMBERS)
    assert runner.asked_values("review", None) == {
        "max_tokens": 1024, "temperature": 0.0}
    runner.take_flow(None)
    assert asked_by_review(monkeypatch) == (0, 1024)
    # the failure by construction: without the home of its box the request
    # asks with the values of the run
    monkeypatch.setattr(runner, "_HOMES", {})
    assert asked_by_review(monkeypatch) == (
        rules.get("temperature"), rules.get("max_tokens"))
    assert rules.get("max_tokens") != 1024


def test_the_example_request_has_a_home_that_asks_it_with_0_and_1024(
        monkeypatch):
    assert runner.asked_values("example") == {"max_tokens": 1024,
                                              "temperature": 0.0}
    # the failure by construction: a kind no flow has asks with the run's
    assert runner.asked_values("nothing")["max_tokens"] == rules.get(
        "max_tokens")
    from docpipe.compile import cli
    from docpipe import prompts
    seen: list = []

    def create(**request):
        seen.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content=json.dumps({"tuples": []}),
                reasoning_content=None))], usage=None)
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    parameter = {"uri": "p", "value_type": "float", "name": "p",
                 "description": "d"}
    cli.ask_for_example(client, prompts.load("extraction/example"),
                        parameter, "Der Wert 5 MWh.")
    assert (seen[0]["temperature"], seen[0]["max_tokens"]) == (0, 1024)


# -- every asking box says what it asks with ----------------------------------

def lacking(tree: list) -> list:
    """The boxes of *tree* that ask a model and do not carry the
    temperature and the answer room of their request."""
    out = []
    for node, _frames in flow_map.walk(tree):
        kind = blocks.box_of(node)
        if kind is not None and kind.asks:
            own = node.get("rules") or {}
            if not {"temperature", "max_tokens"} <= set(own):
                out.append(node["id"])
    return out


def test_every_asking_box_of_every_shipped_flow_carries_its_values():
    assert lacking(flow_map.tree_of(None)) == []
    for name in passflow.names(None):
        if name != passflow.MAIN:
            assert lacking(passflow.load(name)) == [], name
    # the failure by construction: a box that asks and sets nothing
    bad = [{"id": "r", "box": "ask", "preset": "review"}]
    assert lacking(bad) == ["r"]
    assert lacking([{"id": "s", "box": "stored"}]) == []


def test_the_flow_files_are_written_in_the_one_form_they_are_read_in():
    for path in sorted(FLOWS.glob("*.json")):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert text == passflow.dump(passflow.parse(text, path)), path.name
    assert {p.stem for p in FLOWS.glob("*.json")} == set(NAMES)
    # the failure by construction: a key twice is refused, not the last
    with pytest.raises(flow_map.FlowError):
        passflow.parse('{"flow": [], "flow": []}', "x")


# -- a pass box is no box of the main flow ------------------------------------

def steps_of_the_library() -> dict:
    """{kind of step (`rules.step_kind`): the box it is}: the boxes of the
    library and the presets of "Ask the model"."""
    from docpipe.extraction.presets import PRESETS
    out = {kind: box for kind, box in blocks.LIBRARY.items()
           if kind != "ask"}
    for name, one in PRESETS.items():
        out.setdefault(one.kind, blocks.box_of(
            {"box": "ask", "preset": name}))
    return out


def test_a_pass_box_is_never_an_end_box_of_the_main_flow():
    tree = copy.deepcopy(flow_map.tree_of(None))
    assert flow_map.problems(tree) == []
    steps = steps_of_the_library()
    ends = [kind for kind, box in steps.items()
            if box.group == "end" and kind != "write"]
    assert "compute" in ends
    assert not any(steps[kind].flow for kind in ends)
    assert not any(steps[kind].flow for kind in engine.AFTER)
    for kind, box in steps.items():
        if box.flow:
            assert box.group == "pass" and kind not in engine.AFTER
    # the failure by construction: a pass box after write is refused, and
    # the sentence about the end boxes does not name it
    tree.append({"id": "late", "box": "carry_stamp"})
    said = [one["message"] for one in flow_map.problems(tree)]
    assert any("follow-up pass" in one for one in said)
    assert not any("carry_stamp" in one and "come after it" in one
                   for one in said)


def test_the_page_gets_the_pass_boxes_apart_from_the_boxes_of_the_flow():
    library = blocks.catalogue()
    kinds = {box["type"] for box in library["boxes"]} \
        | {one["name"] for one in library["presets"]}
    apart = {box["type"] for box in library["pass_boxes"]} \
        | {one["name"] for one in blocks.presets_catalogue()
           if one["flow"] == "pass"}
    assert kinds.isdisjoint(apart) and "review" in apart
    assert "write" in kinds and "write" not in apart


# -- the editor reads, checks and saves a flow by name ------------------------

def make_app(tmp_path, profile) -> server.App:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    return server.App(profile, None, root)


def test_the_editor_lists_the_flows_of_the_passes(tmp_path, profile):
    app = make_app(tmp_path, profile)
    status, listed = app.call("GET", "/api/flow/passes", {}, None)
    assert status == 200
    assert {one["name"] for one in listed["passes"]} == set(NAMES)
    assert not any(one["own"] for one in listed["passes"])
    write_flow(profile, "remap", passflow.load("remap"))
    owned = {one["name"]: one["own"] for one in app.call(
        "GET", "/api/flow/passes", {}, None)[1]["passes"]}
    assert owned["remap"] and not owned["recheck"]


def test_the_editor_loads_a_flow_by_name_and_refuses_a_name_that_is_none(
        tmp_path, profile):
    app = make_app(tmp_path, profile)
    status, shown = app.call("GET", "/api/flow/pass", {"name": "review"},
                             None)
    assert status == 200 and shown["tree"] == passflow.load("review")
    assert not shown["exists"] and shown["base"] is None
    assert shown["problems"] == []
    assert "stored" in {box["type"] for box in shown["library"]["boxes"]}
    assert "review" in {one["name"] for one in shown["library"]["presets"]}
    assert shown["library"]["each"].keys() == {"dimension"}
    # the failure by construction: a name that is no flow, and one that
    # tries to leave the folder of the flows
    for name in ("nothing", "../flow", "main", None, ""):
        status, said = app.call("GET", "/api/flow/pass", {"name": name},
                                None)
        assert status == 404, name
    assert not (tmp_path / "scenarios" / "flow.json").exists()


def test_a_check_of_a_flow_writes_nothing_and_says_every_reason(tmp_path,
                                                                profile):
    app = make_app(tmp_path, profile)
    tree = copy.deepcopy(passflow.load("recheck"))
    tree[0]["off"] = True
    status, report = app.call("POST", "/api/flow/pass/check", {},
                              {"name": "recheck", "tree": tree})
    assert status == 200 and not report["ok"]
    reasons = {one["id"] for one in report["errors"]}
    assert "recheck_recheck" in reasons and "text" not in report
    assert not passflow.path_of(profile, "recheck").exists()
    # the failure by construction: the drawing as it is has no reason
    status, report = app.call("POST", "/api/flow/pass/check", {},
                              {"name": "recheck"})
    assert report["ok"] and report["writes"] == "unchanged"


def test_a_save_writes_the_profiles_own_file_and_a_save_back_removes_it(
        tmp_path, profile):
    app = make_app(tmp_path, profile)
    tree = copy.deepcopy(passflow.load("remap"))
    next(n for n in tree if n["box"] == "carry_stamp")["off"] = True
    status, told = app.call("POST", "/api/flow/pass/save", {},
                            {"name": "remap", "base": None, "tree": tree})
    path = passflow.path_of(profile, "remap")
    assert told["saved"] and told["writes"] == "created"
    assert passflow.parse(path.read_text(encoding="utf-8"), path) == tree
    assert told["base"] == server.sha256(path.read_bytes())
    assert passflow.load("remap") != tree     # the shipped file is not hers
    # the failure by construction: a file that moved is not written over
    status, moved = app.call("POST", "/api/flow/pass/save", {}, {
        "name": "remap", "base": "0" * 64,
        "tree": passflow.load("remap")})
    assert not moved["saved"] and moved["reason"] == "moved"
    assert passflow.parse(path.read_text(encoding="utf-8"), path) == tree
    status, back = app.call("POST", "/api/flow/pass/save", {}, {
        "name": "remap", "base": told["base"],
        "tree": passflow.load("remap")})
    assert back["writes"] == "removed" and not path.exists()


def test_a_save_of_a_flow_the_run_cannot_do_writes_nothing(tmp_path,
                                                           profile):
    app = make_app(tmp_path, profile)
    tree = [{"id": "x", "box": "ask", "preset": "review"}]
    status, told = app.call("POST", "/api/flow/pass/save", {},
                            {"name": "review", "base": None, "tree": tree})
    assert not told["saved"] and told["reason"] == "invalid"
    assert "takes the documents" in told["message"]
    assert not passflow.path_of(profile, "review").exists()
    status, told = app.call("POST", "/api/flow/pass/save", {},
                            {"name": "../x", "base": None, "tree": tree})
    assert status == 404
