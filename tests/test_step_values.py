"""
A step of the flow and the frames around it set values for themselves
(`"rules"` of a box or frame, `rules.STEP`; owner 2026-11-11: "alles soll
anpassbar sein").

The promises, each with a case that breaks it by construction:

1. A value is read in this order: the step's own, the innermost frame's,
   the outer frames', the setting of the start, the file. Inside the box the
   box's value, in the frame outside the box the frame's, outside both the
   start's, without a start the file's.
2. Work a step hands to another thread reads the step's values when it takes
   the context along (`contextvars.copy_context`), AND a thread that does not
   take it reads the run's value.
3. A number of the flow goes the same way: a box's own number and a frame's
   number are read where the step reads it (`flow.number`), the run's
   outside.
4. What is made from the rules once per state (`rules.derived`) is made again
   for a step that sets a rule it is made from.
5. A drawing may set only what a step in it reads: a name that is no rule, a
   value its rule does not allow, and a rule no step in the node reads are
   refused, each with its reason; a rule a step in a frame reads is not.
"""
import contextvars
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from docpipe import rules
from docpipe.extraction import engine, flow

NAME = "image_max_side"          # a rule with a setting of the start
ENV = "EXTRACT_IMAGE_MAX_SIDE"


def step(node: dict) -> rules.in_step:
    """What the engine does around a node (`engine.Engine.step`)."""
    return rules.in_step(rules.stepped(node, engine.Engine.own_values(node)))


FRAME = {"id": "values", "each": "value", "rules": {NAME: 700}}
BOX = {"id": "ask", "box": "ask", "preset": "coord", "rules": {NAME: 500}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    rules.reset()
    yield
    rules.reset()


def test_the_step_then_the_frame_then_the_start_then_the_file(monkeypatch):
    standard = rules.get(NAME)
    assert standard == rules.default()[NAME]
    monkeypatch.setenv(ENV, "900")
    rules.reset()
    assert rules.get(NAME) == 900                      # the start
    with step(FRAME):
        assert rules.get(NAME) == 700                  # the frame
        with step(BOX):
            assert rules.get(NAME) == 500              # the step
        assert rules.get(NAME) == 700                  # back in the frame
    assert rules.get(NAME) == 900
    monkeypatch.delenv(ENV)
    rules.reset()
    assert rules.get(NAME) == standard                 # the file


def test_a_box_without_a_value_reads_its_frame():
    with step(FRAME), step({"id": "other", "box": "ask", "preset": "coord"}):
        assert rules.get(NAME) == 700
        assert rules.STEP.get().owners[NAME] == "frame values"


def test_a_worker_thread_reads_the_step_with_the_context_only():
    standard = rules.get(NAME)
    seen = {}
    with step(FRAME), step(BOX):
        with ThreadPoolExecutor(max_workers=1) as pool:
            seen["copied"] = pool.submit(
                contextvars.copy_context().run, rules.get, NAME).result()
        bare = threading.Thread(
            target=lambda: seen.__setitem__("bare", rules.get(NAME)))
        bare.start()
        bare.join()
    assert seen["copied"] == 500
    assert seen["bare"] == standard        # broken by construction


def test_numbers_of_the_flow_go_the_same_way():
    numbers = flow.default()
    search = {"id": "search", "box": "ask", "preset": "search",
              "own": {"per_request": 3}}
    frame = {"id": "coords", "each": "coordinate",
             "rules": {"search_per_request": 4, "headings": 1}}
    run = flow.number(numbers, "search_per_request")
    with step(frame):
        assert flow.number(numbers, "search_per_request") == 4
        with step(search):
            assert flow.number(numbers, "search_per_request") == 3
            assert flow.number(numbers, "headings") == 1
    assert flow.number(numbers, "search_per_request") == run
    assert flow.number(numbers, "headings") == numbers.headings


def test_what_is_made_from_the_rules_is_made_per_step():
    made = []

    def build():
        made.append(rules.get(NAME))
        return rules.get(NAME)
    outside = rules.derived("test_step_values", build)
    with step(BOX):
        inside = rules.derived("test_step_values", build)
    assert (outside, inside) == (rules.get(NAME), 500)
    assert rules.derived("test_step_values", build) == outside
    assert len(made) == 2


def tree_with(node: dict) -> list:
    """The default drawing with *node* laid over the first coordinate
    question."""
    tree = copy.deepcopy(flow.tree_of(None))
    for found, _frames in flow.walk(tree):
        if rules.step_kind(found) == "coord":
            found.update(node)
            return tree
    raise AssertionError("the default drawing has no coordinate question")


def said(tree) -> list:
    return [p["message"] for p in flow.problems(tree)]


def test_a_drawing_sets_only_what_a_step_in_it_reads():
    assert said(tree_with({"rules": {NAME: 500}})) == []
    assert any("no rule" in m and "image_max_sid" in m
               for m in said(tree_with({"rules": {"image_max_sid": 500}})))
    assert any(NAME in m and "at least" in m
               for m in said(tree_with({"rules": {NAME: 3}})))
    # a rule only the split box reads, at a question
    assert any("abbreviations is not read here" in m
               for m in said(tree_with({"rules": {"abbreviations": []}})))
    # a rule a question reads, at the frame of values that holds it:
    # allowed; at the box that writes the harvest: refused
    tree = copy.deepcopy(flow.tree_of(None))
    frame = next(n for n in tree if n.get("each") == "value")
    frame["rules"] = {"lines_around": 2}
    assert said(tree) == []
    write = next(n for n in tree if n.get("box") == "write")
    write["rules"] = {"lines_around": 2}
    assert any("lines_around is not read here" in m for m in said(tree))
