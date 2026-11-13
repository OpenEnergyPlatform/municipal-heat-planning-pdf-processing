"""
test_editor_step_page.py: what the flow tab of `docpipe edit` promises about
the values a step sets for itself (owner 2026-11-11: "alles soll anpassbar
sein") and the values of the machine.

Each test states one promise and holds a case that breaks it by
construction: a value at a box another box does not see, a rule the box does
not read, a key, a project file that git would commit.

Author: Felix Vossel
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import shutil
import subprocess
from pathlib import Path

import pytest

from docpipe import rules, settings
from docpipe.editor import flow as flow_view
from docpipe.editor import rulespage
from docpipe.extraction import blocks, flow
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parent.parent
SETTINGS = sorted({number.env for number in flow.NUMBERS if number.env})
BOX, FRAME = "own_place", "values"          # a coord box in an each value
RULE = "lines_around"                       # read by coord, not by split
STANDARD = rules.BY_NAME[RULE]


@pytest.fixture(autouse=True)
def no_setting_wins(monkeypatch):
    for name in SETTINGS + [rule.env for rule in rules.RULES if rule.env]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def profile(tmp_path):
    home = tmp_path / "scenarios"
    home.mkdir()
    shutil.copy(REPO / "profiles" / "scenarios" / "extraction_spec.json",
                home)
    # the profile draws its own flow (owner decision 2026-11-12)
    shutil.copy(REPO / "profiles" / "scenarios" / "flow.json", home)
    shutil.copytree(REPO / "profiles" / "scenarios" / "prompts",
                    home / "prompts")
    return dataclasses.replace(load_profile("scenarios"), home=home)


def node_of(tree: list, ident: str) -> dict:
    return next(node for node, _ in flow.walk(tree) if node["id"] == ident)


def raw_of(profile):
    path = flow.path_of(profile)
    return path.read_bytes() if path.is_file() else None


def save(profile, tree) -> dict:
    """What the server does with a save of *tree*."""
    raw = raw_of(profile)
    base = flow_view.sha256(raw) if raw is not None else None
    told, written, remove = flow_view.save(
        profile, raw, flow.load(profile).numbers, base, "flow.json", tree)
    if written is not None:
        flow.path_of(profile).write_bytes(written)
    elif remove:
        flow.path_of(profile).unlink()
    return told


def judge(profile, tree) -> dict:
    return flow_view.judge(profile, raw_of(profile),
                           flow.load(profile).numbers, "flow.json", tree)


def value_at(profile, *ids):
    """The rule as the run reads it inside the steps *ids*, outermost
    first: each step's own values laid over those of the steps around it
    (`rules.stepped` inside `rules.in_step`, as `engine.step` does)."""
    tree = flow.load(profile).tree
    with contextlib.ExitStack() as stack:
        for ident in ids:
            node = node_of(tree, ident)
            stack.enter_context(rules.in_step(
                rules.stepped(node, node.get("rules") or {})))
        return rules.get(RULE)


# -- a value at a step reaches the run ----------------------------------------

def test_a_value_saved_at_a_box_comes_back_and_reaches_the_run(profile):
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, BOX)["rules"] = {RULE: 9}
    told = save(profile, tree)
    assert told["saved"], told
    drawn = flow_view.view(profile, raw_of(profile), None,
                           lambda path: Path(path).name)
    # AND it comes back in the drawing the page is sent
    assert node_of(drawn["tree"], BOX)["rules"] == {RULE: 9}
    # AND the run, inside that step, reads it
    assert value_at(profile, FRAME, BOX) == 9
    # the failures by construction: no other step sees it, nor the run
    assert value_at(profile, FRAME) == value_at(profile) != 9
    assert value_at(profile, FRAME, "work") == value_at(profile)


def test_taking_the_value_away_brings_back_the_frame_or_the_standard(profile):
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, FRAME)["rules"] = {RULE: 5}
    node_of(tree, BOX)["rules"] = {RULE: 9}
    assert save(profile, tree)["saved"]
    assert value_at(profile, FRAME, BOX) == 9
    # off at the box: the frame's value holds for what is in it
    again = copy.deepcopy(flow.load(profile).tree)
    del node_of(again, BOX)["rules"]
    assert save(profile, again)["saved"]
    assert "rules" not in node_of(flow.load(profile).tree, BOX)
    assert value_at(profile, FRAME, BOX) == 5
    # off at the frame too: the standard
    last = copy.deepcopy(flow.load(profile).tree)
    del node_of(last, FRAME)["rules"]
    assert save(profile, last)["saved"]
    assert value_at(profile, FRAME, BOX) == rules.get(RULE)


# -- what a step may set ------------------------------------------------------

def test_a_rule_the_box_does_not_read_is_refused_at_that_box(profile):
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, BOX)["rules"] = {"abbreviations": ["Dr."]}   # split reads it
    said = judge(profile, tree)
    assert not said["ok"]
    assert [e["id"] for e in said["errors"]] == [BOX]
    assert "is not read here" in said["errors"][0]["message"]
    before = raw_of(profile)
    told = save(profile, tree)
    assert not told["saved"] and told["reason"] == "invalid"
    assert raw_of(profile) == before
    # the failure by construction: at the box that reads it, it is taken
    fine = copy.deepcopy(flow.load(profile).tree)
    node_of(fine, "pieces")["rules"] = {"abbreviations": ["Dr."]}
    assert judge(profile, fine)["ok"]


def test_the_page_is_offered_each_step_what_it_reads_and_the_tab_of_a_rule():
    kwp = load_profile("kwp")
    got = flow_view.step_rules(kwp)
    assert RULE in got["kinds"]["coord"]
    assert RULE not in got["kinds"].get("split", [])
    # a link opens the tab the rule stands in, and that is not always Flow
    assert got["tabs"][RULE] == rules.BY_NAME[RULE].tab != "flow"
    assert got["tabs"]["retry_wait_s"] == "flow"
    # every rule a step may set: the line's and those of its graph file
    known = flow.known_rules(kwp)
    assert got["tabs"] == {name: one.tab for name, one in known.items()}
    assert got["tabs"]["rounding_tolerance"] == "graph"


def test_the_rules_say_at_which_steps_they_have_an_own_value(profile):
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, BOX)["rules"] = {RULE: 9}
    node_of(tree, FRAME)["rules"] = {RULE: 5}
    assert save(profile, tree)["saved"]
    at = flow_view.own_at(flow.load(profile).tree)
    assert {row["id"] for row in at[RULE]} == {BOX, FRAME}
    shown = rulespage.view(profile, STANDARD.tab, None, str, at)
    row = next(r for r in shown["rules"] if r["name"] == RULE)
    assert {s["id"] for s in row["own_at"]} == {BOX, FRAME}
    # the failure by construction: a rule no step sets has none
    other = next(r for r in shown["rules"] if r["name"] != RULE
                 and r["name"] not in at)
    assert other["own_at"] == []
    # a number a box has "only here" counts under the number's name
    box = next(b for b in blocks.LIBRARY.values()
               if any(s.number for s in b.settings))
    setting = next(s for s in box.settings if s.number)
    fresh = {"id": "x", "box": box.type, "own": {setting.key: 3}}
    assert [s["id"] for s in flow_view.own_at([fresh])[setting.number]] \
        == ["x"]


# -- a key is never sent or written ------------------------------------------

def secret_registry(monkeypatch, name="image_max_side"):
    real = rules.registry

    def registry(profile=None):
        known = dict(real(profile))
        known[name] = dataclasses.replace(known[name], secret=True)
        return known
    monkeypatch.setattr(rules, "registry", registry)
    return real


def test_a_key_is_neither_sent_nor_set_at_a_step_nor_written(
        profile, monkeypatch):
    real = secret_registry(monkeypatch)
    row = next(r for r in rulespage.view(
        profile, "prompts", None, str)["rules"]
        if r["name"] == "image_max_side")
    assert row["secret"] and (row["value"], row["in_effect"],
                              row["inherited"]) == (None, None, None)
    assert "image_max_side" not in [
        r["name"] for r in rulespage.machine_rows(profile)]
    # not set at a step
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, BOX)["rules"] = {"image_max_side": 1600}
    said = judge(profile, tree)
    assert not said["ok"] and "is a key" in said["errors"][0]["message"]
    # not written into a rules file, not into a project file
    said = rulespage.judge(profile, None, {"image_max_side": 1600}, "rules")
    assert not said["ok"]
    path = profile.home.parent / "docpipe.toml"
    told = rulespage.machine_save(profile, {"image_max_side": 1600}, path, str)
    assert not told["saved"] and not path.exists()
    with pytest.raises(settings.ConfigError):
        settings.write_project(path, {"embedding.api_key": "k"})
    assert not path.exists()
    # the failure by construction: the same rule that is no key is sent
    monkeypatch.setattr(rules, "registry", real)
    row = next(r for r in rulespage.view(
        profile, "prompts", None, str)["rules"]
        if r["name"] == "image_max_side")
    assert row["value"] is not None and not row["secret"]
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, BOX)["rules"] = {"image_max_side": 1600}
    assert judge(profile, tree)["ok"]


# -- the values of the machine, in the project file only ----------------------

MACHINE = "server_dead_after_s"


@pytest.fixture
def machine(monkeypatch):
    real = rules.registry

    def registry(profile=None):
        known = dict(real(profile))
        known[MACHINE] = dataclasses.replace(
            known[MACHINE], machine=True, steps=("coord",))
        return known
    monkeypatch.setattr(rules, "registry", registry)


def git(folder: Path, *args) -> None:
    subprocess.run(["git", "-C", str(folder), *args], check=True,
                   capture_output=True)


needs_git = pytest.mark.skipif(shutil.which("git") is None,
                               reason="git is not installed")


@needs_git
def test_a_machine_value_is_written_only_into_an_ignored_project_file(
        profile, machine, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    path = repo / "docpipe.toml"
    path.write_text('# mine\n[llm]\nbase_url = "http://x"\n',
                    encoding="utf-8")
    rows = {r["name"]: r for r in rulespage.machine_rows(profile)}
    # the machine's values and nothing else: the patched one among them
    known = rules.registry(profile)
    assert all(known[name].machine for name in rows)
    assert rows[MACHINE]["key"] == "extract.server_dead_after"
    # inside the repository and not ignored: refused with its reason
    told = rulespage.machine_save(profile, {MACHINE: 600}, path, str)
    assert not told["saved"] and told["reason"] == "git"
    assert "not ignored" in told["message"]
    assert "server_dead_after" not in path.read_text(encoding="utf-8")
    # ignored: written, and every other line stays
    (repo / ".gitignore").write_text("docpipe.toml\n", encoding="utf-8")
    told = rulespage.machine_save(profile, {MACHINE: 600}, path, str)
    assert told["saved"], told
    text = path.read_text(encoding="utf-8")
    assert "# mine" in text and 'base_url = "http://x"' in text
    assert settings.read(path)["EXTRACT_SERVER_DEAD_AFTER"] == "600"
    # set again: the line is replaced, not repeated
    assert rulespage.machine_save(profile, {MACHINE: 900}, path, str)["saved"]
    assert path.read_text(encoding="utf-8").count("server_dead_after") == 1
    # tracked by git (even though ignored): refused
    git(repo, "add", "-f", "docpipe.toml")
    told = rulespage.machine_save(profile, {MACHINE: 910}, path, str)
    assert not told["saved"] and "tracked" in told["message"]
    assert "= 900" in path.read_text(encoding="utf-8")
    # the failure by construction: a file outside every repository is free,
    # and is created where it is missing
    loose = tmp_path / "loose" / "docpipe.toml"
    loose.parent.mkdir()
    told = rulespage.machine_save(profile, {MACHINE: 5}, loose, str)
    assert told["saved"] and told["writes"] == "created"


def test_a_machine_value_is_not_a_value_of_a_step_or_the_rules_file(
        profile, machine):
    tree = copy.deepcopy(flow.load(profile).tree)
    node_of(tree, BOX)["rules"] = {MACHINE: 600}
    said = judge(profile, tree)
    assert not said["ok"] and "machine" in said["errors"][0]["message"]
    said = rulespage.judge(profile, None, {MACHINE: 600}, "rules")
    assert not said["ok"] and "machine" in said["errors"][0]["message"]
    # a rule that is no value of the machine is refused by the project file
    told = rulespage.machine_save(profile, {RULE: 3}, Path("x.toml"), str)
    assert not told["saved"] and told["reason"] == "invalid"
    # the failure by construction: unchanged, the machine value is no edit
    standard = rules.load(profile, environ={})[MACHINE]
    assert rulespage.judge(profile, None, {MACHINE: standard},
                           "rules")["ok"]


def test_the_project_file_keeps_its_lines_and_reads_back(tmp_path):
    path = tmp_path / "docpipe.toml"
    lines = ['profile = "kwp"', "[llm]", 'model = "m"', "[extract]",
             "batch_sources = 2"]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode())
    settings.write_project(path, {"extract.retry_wait": 4.5,
                                  "llm.base_url": "http://y"})
    text = path.read_bytes().decode()
    assert text.count("\r\n") == text.count("\n")          # line ends kept
    said = settings.read(path)
    assert said["EXTRACT_RETRY_WAIT"] == "4.5"
    assert said["EXTRACT_BATCH_SOURCES"] == "2"
    assert 'profile = "kwp"' in text and 'model = "m"' in text
    # the failure by construction: a name that is no setting, a key
    with pytest.raises(settings.ConfigError):
        settings.write_project(path, {"llm.no_such": 1})
    with pytest.raises(settings.ConfigError):
        settings.write_project(path, {"llm.api_key": "k"})
    assert "no_such" not in path.read_text(encoding="utf-8")
