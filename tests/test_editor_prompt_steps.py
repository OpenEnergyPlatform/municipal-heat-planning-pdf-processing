"""
test_editor_prompt_steps.py: from a prompt to the steps that ask with it,
and a recorded request named by the page and heading of its piece (owner
request 2026-11-19, A7: "neben jedem Prompt der Name des Schritts, wie ihn
der Ablauf-Reiter nennt, als Link dorthin. Eine Anfrage nennt Seite und
Überschrift ihres Stücks").

The promise, in one sentence: every step of a profile's drawings (the main
flow, the flows of its follow-up passes and the chat's) that asks the model
with a prompt the profile has is listed under exactly that prompt, by its
id, the drawing it stands in and the name the Flow tab gives it, AND no
other step is (one whose prompt no profile writes is never taken); a
request that names the passage it reads names that passage's page and
heading too, AND the page's record of the request carries them. Each part
has a case that breaks it by construction.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from docpipe.editor import prompts
from docpipe.editor import requests as rq
from docpipe.extraction import blocks, passflow, targets
from docpipe.extraction import flow as flow_map
from docpipe.extraction.pipeline import Source
from docpipe.inference import chatflow
from docpipe.profile import load_profile

PROFILES = ("kwp", "scenarios")


def asking(profile) -> set:
    """(prompt id, drawing, step id, label) of every step of *profile*'s
    drawings that asks the model, found here on its own."""
    out = set()
    drawings = [("", flow_map.load(profile).tree)] + [
        (name, passflow.load(name, profile))
        for name in passflow.names(profile) if name != passflow.MAIN]
    for flow, tree in drawings:
        for node, _ in flow_map.walk(tree):
            box = blocks.box_of(node) if "box" in node else None
            if box is not None and box.asks:
                out.add((f"extraction/{box.asks}", flow, node["id"],
                         box.label))
    for node in chatflow.walk(chatflow.load(profile).tree):
        box = chatflow.LIBRARY.get(node.get("box")) \
            if isinstance(node, dict) else None
        if box is not None and box.asks:
            out.add((f"inference/{box.asks}", prompts.CHAT_FLOW, node["id"],
                     box.label))
    return out


def kept(profile, steps: set) -> set:
    have = {row["id"] for row in prompts.listing(profile)}
    return {one for one in steps if one[0] in have}


def listed(found: dict) -> set:
    return {(prompt_id, one["flow"], one["id"], one["label"])
            for prompt_id, steps in found.items() for one in steps}


@pytest.mark.parametrize("name", PROFILES)
def test_every_step_that_asks_is_listed_under_its_prompt(name):
    profile = load_profile(name)
    found = prompts.steps_asking(profile)
    assert listed(found) == kept(profile, asking(profile))
    # every prompt a step asks with is a prompt of the profile
    ids = {row["id"] for row in prompts.listing(profile)}
    assert set(found) <= ids
    # the three kinds of drawing are all there
    flows = {one["flow"] for steps in found.values() for one in steps}
    assert "" in flows and prompts.CHAT_FLOW in flows and len(flows) >= 3


def test_a_step_that_asks_with_another_prompt_moves_to_it(monkeypatch):
    # by construction: the step that finds the values of a piece asks with
    # the prompt of a search sentence instead
    profile = load_profile("kwp")
    loaded = flow_map.load(profile)
    tree = copy.deepcopy(loaded.tree)
    for node, _ in flow_map.walk(tree):
        if node.get("id") == "finds":
            node["preset"] = "phrase"
    monkeypatch.setattr(flow_map, "load", lambda _profile: SimpleNamespace(
        tree=tree))
    found = prompts.steps_asking(profile)
    assert "finds" not in {one["id"] for one in found.get(
        "extraction/find", [])}
    assert "finds" in {one["id"] for one in found["extraction/phrase"]}


def test_a_drawing_the_page_cannot_read_names_no_step(monkeypatch):
    def broken(_profile):
        raise flow_map.FlowError("flow.json: broken")
    monkeypatch.setattr(flow_map, "load", broken)
    found = prompts.steps_asking(load_profile("kwp"))
    assert all(one["flow"] != "" for steps in found.values()
               for one in steps)


# -- the page and heading of a request's piece --------------------------------------

SOURCE = Source("table", 48897, "Tabelle 3: Wärmebedarf\n| a | b |",
                provenance={"page": 12, "title": "Tabelle 3: Wärmebedarf",
                            "section_title": "3 Bestand"})


def test_a_request_names_the_page_and_heading_of_its_piece():
    assert targets.place_notes(SOURCE) == {
        "page": 12, "heading": "Tabelle 3: Wärmebedarf"}
    section = Source("section", 7, "x", provenance={
        "page": 3, "title": None, "section_title": "2 Ziele"})
    assert targets.place_notes(section) == {"page": 3, "heading": "2 Ziele"}
    chunk = SimpleNamespace(passage=SimpleNamespace(kind="table",
                                                    source=SOURCE), index=0)
    noted = targets.chunk_notes(chunk)
    assert noted["owner"] == 48897 and noted["page"] == 12
    assert noted["heading"] == "Tabelle 3: Wärmebedarf"


def test_a_piece_without_a_place_names_none():
    # by construction: a passage the database gave no page and no heading
    bare = Source("section", 8, "x")
    assert targets.place_notes(bare) == {}
    chunk = SimpleNamespace(passage=SimpleNamespace(kind="section",
                                                    source=bare), index=2)
    assert "page" not in targets.chunk_notes(chunk)


def test_a_request_about_a_dimension_names_the_place_of_its_value():
    plan = SimpleNamespace(passages={("table", 48897): SimpleNamespace(
        kind="table", source=SOURCE)})
    coord = SimpleNamespace(
        row=SimpleNamespace(claim={"at": {"owner": ["table", 48897]}},
                            label="R1"),
        read=SimpleNamespace(batch=SimpleNamespace(
            parameter=SimpleNamespace(uri="energy"))),
        slot=SimpleNamespace(name="year"))
    noted = targets.coord_notes(coord, plan)
    assert (noted["page"], noted["heading"]) == (12, "Tabelle 3: Wärmebedarf")
    # without the plan the request still names its passage, not its place
    assert "page" not in targets.coord_notes(coord)


def test_the_record_of_a_request_carries_its_place():
    event = {"t": "find_ask", "doc": 1, "owner": 48897, "page": 12,
             "heading": "Tabelle 3: Wärmebedarf",
             "input": {"messages": [{"role": "user", "content": "{}"}]},
             "output": {"content": "{}", "finish": "stop"}}
    record = rq.requests_of([event])[0]
    assert (record["page"], record["heading"]) == (12,
                                                   "Tabelle 3: Wärmebedarf")
    # a log written before the place was noted keeps only the number
    old = dict(event)
    del old["page"], old["heading"]
    assert "page" not in rq.requests_of([old])[0]
