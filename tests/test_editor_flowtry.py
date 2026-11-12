"""
test_editor_flowtry.py: what "Try" in the flow tab of `docpipe edit`
promises (flowtry.py, test 9 of the plan of 2026-11-10).

A drawing is tried on a document with made-up answers: every request is
built as it would go out AND kept at the box that asked it AND nothing is
sent; "nothing" asks at least as much as "first_line" AND none of its
answers fails the form of its request; a find of a number field names a
number as its line prints it. Each promise holds a case that breaks it by
construction.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import json

import pytest

from docpipe.editor import flowtry, specs
from docpipe.extraction import addressed, flow, runner
from docpipe.extraction.presets import PRESETS
from docpipe.profile import load_profile


@pytest.fixture
def scenarios(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    profile = load_profile("scenarios")
    spec_path = profile.component("extraction", "SPEC_PATH")
    with open(spec_path, "rb") as handle:
        spec = runner.load_spec(specs.parse(handle.read()))

    def never(*args, **kwargs):
        raise AssertionError("a try sent a request")
    # nothing is sent: the run's way out raises
    monkeypatch.setattr(runner, "ask_in_grammar", never)
    monkeypatch.setattr(runner, "_client", never)
    return profile, spec


def tried(scenarios, mode: str, tree=None) -> dict:
    profile, spec = scenarios
    return flowtry.run(profile, spec,
                       flow.tree_of(profile) if tree is None else tree,
                       flow.in_effect(profile),
                       flowtry.example_sources(spec), mode)


def test_every_request_is_kept_at_its_box_and_none_is_sent(scenarios):
    got = tried(scenarios, "first_line")
    profile, _ = scenarios
    ids = {node["id"] for node, _ in flow.walk(flow.tree_of(profile))}
    assert got["requests"] > 0 and set(got["boxes"]) <= ids
    assert sum(box["requests"] for box in got["boxes"].values()) \
        == got["requests"]
    # each box's first request is built in full: its prompt and its message
    finds = got["boxes"]["finds"]["first"]
    assert finds["kind"] == "find" and finds["system"] \
        and finds["message"].startswith("{")
    # the failure by construction: a box switched off asks nothing
    tree = copy.deepcopy(flow.tree_of(profile))
    next(node for node, _ in flow.walk(tree)
         if node["id"] == "name")["off"] = True
    assert "name" in got["boxes"]
    assert "name" not in tried(scenarios, "first_line", tree)["boxes"]


def test_a_request_whose_answer_may_fetch_is_built_with_its_part(scenarios):
    # the try builds a prompt as the run does (`runner.request_prompt`): the
    # question at the value's place may fetch, so it is told how
    told = "fetches pieces a shown line points to"
    got = tried(scenarios, "first_line")
    assert told in got["boxes"]["own_place"]["first"]["system"]
    # the failure by construction: a step that may fetch nothing has no
    # "more" in its reply form, and its prompt does not tell of it
    profile, _ = scenarios
    tree = copy.deepcopy(flow.tree_of(profile))
    next(node for node, _ in flow.walk(tree)
         if node["id"] == "own_place")["rules"] = {"fetches": []}
    again = tried(scenarios, "first_line", tree)
    assert told not in again["boxes"]["own_place"]["first"]["system"]


def test_nothing_goes_the_whole_way_and_no_answer_fails_its_form(scenarios):
    nothing = tried(scenarios, "nothing")
    first = tried(scenarios, "first_line")
    assert nothing["requests"] >= first["requests"]
    assert nothing["values"] == first["values"] > 0
    ends = {state for states in nothing["states"].values()
            for state in states}
    assert ends <= {"unstated", "exhausted", "derived", "out_of_slice"}
    assert nothing["refused"] == {}
    # first_line reads where nothing reads nothing
    assert {state for states in first["states"].values()
            for state in states} >= {"read"}


FORMS = {
    "found": addressed.found_format(), "found listed":
    addressed.found_format(True), "work": addressed.work_format(),
    "work choice": addressed.work_choice_format(),
    "phrase": addressed.phrase_format(),
    "coordinate": addressed.coord_format(False),
    "coordinate several": addressed.coord_format(True, more=True),
    "entry": addressed.entry_format(),
    "entries new": addressed.entry_format(True, True),
    "year": addressed.year_format(), "lines": addressed.lines_format(),
    "check": addressed.about_format(),
}


def fits(value, schema: dict) -> bool:
    """Does *value* have the type *schema* asks (enough for the forms of
    the reader)?"""
    if "anyOf" in schema:
        return any(fits(value, one) for one in schema["anyOf"])
    if "enum" in schema:
        return value in schema["enum"]
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    checks = {"object": lambda v: isinstance(v, dict),
              "array": lambda v: isinstance(v, list),
              "integer": lambda v: isinstance(v, int)
              and not isinstance(v, bool),
              "string": lambda v: isinstance(v, str)}
    if not any(checks[kind](value) for kind in kinds if kind in checks):
        return False
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        return set(schema.get("required") or ()) <= set(value) \
            and set(value) <= set(properties) \
            and all(fits(v, properties[k]) for k, v in value.items())
    if isinstance(value, list):
        return all(fits(v, schema.get("items") or {}) for v in value)
    return True


@pytest.mark.parametrize("name", sorted(FORMS))
def test_the_empty_answer_has_the_form_of_its_request(name):
    schema = FORMS[name]["json_schema"]["schema"]
    assert fits(flowtry.empty(schema), schema)
    assert flowtry.answer("coord", {}, FORMS[name], "nothing") \
        == flowtry.empty(schema)


def test_the_empty_answer_says_none_in_its_own_words():
    assert flowtry.empty(FORMS["work choice"]["json_schema"]["schema"]) \
        == {"entry": 0}
    assert flowtry.empty(FORMS["coordinate"]["json_schema"]["schema"]) \
        == {"at": 0}
    assert flowtry.empty(FORMS["check"]["json_schema"]["schema"]) \
        == {"about": "no"}
    assert flowtry.empty(FORMS["entries new"]["json_schema"]["schema"]) \
        == {"entry": []}
    # the failure by construction: an answer of another request's form
    # misses the key this one requires
    schema = FORMS["work choice"]["json_schema"]["schema"]
    assert not fits({"at": 0}, schema)


def payload(*lines) -> dict:
    return {"field": {"name": "Leistung"},
            "passage": {"lines": [f"{i} {text}" for i, text in
                                  enumerate(lines, start=1)]}}


def test_a_find_of_a_number_field_names_a_number_as_its_line_prints_it():
    shape = addressed.found_format()
    got = flowtry.answer("find", payload("Die Leistung steigt.",
                                         "Sie beträgt 1.155,5 MW."), shape,
                         "nothing", numeric=True)
    assert got == {"found": [{"at": "2", "words": "1.155,5"}]}
    # a number at the end of a sentence is named without the full stop
    got = flowtry.answer("find", payload("Stand 2023."), shape, "nothing",
                         numeric=True)
    assert got["found"][0]["words"] == "2023"
    # the failures by construction: a piece without a number has none to
    # name, and a field of words names the first word
    assert flowtry.answer("find", payload("Keine Zahl hier."), shape,
                          "nothing", numeric=True) == {"found": []}
    assert flowtry.answer("find", payload("Keine Zahl hier."), shape,
                          "first_line") == {
        "found": [{"at": "1", "words": "Keine"}]}


def test_a_drawing_the_run_cannot_do_is_not_tried(scenarios):
    profile, _ = scenarios
    tree = copy.deepcopy(flow.tree_of(profile))
    tree.insert(1, {"id": "lost_search", "box": "ask", "preset": "search"})
    with pytest.raises(flowtry.Refused, match="lost_search"):
        tried(scenarios, "nothing", tree)
    with pytest.raises(flowtry.Refused, match="mode"):
        tried(scenarios, "everything")


def test_a_step_with_a_prompt_of_its_own_is_tried_as_the_run_asks_it(
        scenarios):
    # every way the run asks stands in a try (`addressed.Asks`): a question
    # with a text of its own is kept under its kind, its prompt that text
    # with its {{key.field}} inputs written in
    profile, _ = scenarios
    tree = copy.deepcopy(flow.tree_of(profile))
    node = next(node for node, _ in flow.walk(tree)
                if node["id"] == "own_place")
    node["set"] = {"prompt": {"text": "Say the line of {{value.words}}."}}
    first = tried(scenarios, "first_line", tree)["boxes"]["own_place"][
        "first"]
    assert first["kind"] == "coord"
    assert first["system"].startswith("Say the line of Example.")
    # the failure by construction: a try without a stand-in for a prompt of
    # a step's own cannot ask it
    def lacking(self):
        return addressed.Asks(**{**vars(asks_of(self)), "own": None})
    asks_of = flowtry.Recorder.asks
    try:
        flowtry.Recorder.asks = lacking
        with pytest.raises(TypeError):
            tried(scenarios, "first_line", tree)
    finally:
        flowtry.Recorder.asks = asks_of


def test_a_field_s_sentence_is_asked_from_the_inputs_of_its_step(scenarios):
    # the request a field's chunks are ordered by is built as the run builds
    # it (`runner.phrase_payload`): from the inputs of the step that writes
    # it, kept at that step
    profile, _ = scenarios
    got = tried(scenarios, "nothing")["boxes"]["sentences"]
    assert got["kinds"] == {"phrase": got["requests"]} and got["requests"]
    assert set(json.loads(got["first"]["message"])) >= {"label",
                                                          "description"}
    # the failure by construction: a step without the input "description"
    # asks without it
    tree = copy.deepcopy(flow.tree_of(profile))
    node = next(node for node, _ in flow.walk(tree)
                if node["id"] == "sentences")
    node["set"] = {"inputs": [one for one in PRESETS["sentences"].inputs
                              if one["key"] != "description"]}
    again = tried(scenarios, "nothing", tree)["boxes"]["sentences"]
    assert "description" not in json.loads(again["first"]["message"])
