"""
test_flow.py: what the flow file promises about the steps a document is read
in and the numbers that bound them.

Each test states one promise and holds a case that breaks it by
construction: a request no step asks, a number the run does not take, a
profile's file that writes steps, a setting that wins over the file. That a
number bounds the reading it stands for is tested where the reading is
(test_addressed.py); what the page makes of the flow in
test_editor_flow.py.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import dataclasses
import json

import pytest

from docpipe.extraction import (addressed, blocks, conditions, flow, remap,
                                runner)
from docpipe.extraction.pipeline import Source
from docpipe.profile import load_profile

SETTINGS = sorted({number.env for number in flow.NUMBERS if number.env})


@pytest.fixture(autouse=True)
def the_run_s_numbers_stay(monkeypatch):
    for name in ("NUMBERS", "TO_END", "_flow_logged"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def profile(tmp_path):
    """scenarios with a folder of its own, still extending default."""
    home = tmp_path / "scenarios"
    home.mkdir()
    return dataclasses.replace(load_profile("scenarios"), home=home)


def write(profile, **numbers) -> None:
    flow.path_of(profile).write_text(flow.dump({"numbers": numbers}),
                                     encoding="utf-8")


def default() -> dict:
    return json.loads(flow.DEFAULT.read_text(encoding="utf-8"))


def tree() -> list:
    return copy.deepcopy(default()["flow"])


def refused(data, whole: bool = True) -> str:
    """What the loader says of a file it refuses."""
    with pytest.raises(flow.FlowError) as caught:
        flow.parse(data if isinstance(data, str) else json.dumps(data),
                   "flow.json", whole)
    return str(caught.value)


def node(drawing: list, ident: str) -> dict:
    return next(n for n, _ in flow.walk(drawing) if n.get("id") == ident)


def said(drawing: list) -> list:
    return [p["message"] for p in flow.problems(drawing)]


# -- the drawing says what the code can do --------------------------------------

def test_every_request_the_code_sends_is_asked_by_a_box_of_the_default():
    # A follow-up is a request of the question it follows, no box of its
    # own; every other kind the code sends has its box: in the default flow,
    # or among the boxes a profile brings itself (owner decision
    # 2026-11-12, profiles/<name>/blocks.py).
    from docpipe.extraction.presets import PRESETS
    blocks.LIBRARY.get("ask")               # the profiles' presets are read
    own = {one.request for one in PRESETS.values() if one.profile}
    assert flow.asked(flow.load().tree) | own \
        == set(flow.kinds()) - {"follow"}
    assert {"names", "work"} <= own
    # the failure by construction: a box switched off asks nothing
    drawing = tree()
    node(drawing, "compute")["off"] = True
    assert "compute" not in flow.asked(drawing)


def test_every_number_is_a_setting_of_a_box_or_preset_of_the_library():
    from docpipe.extraction.presets import PRESETS
    taken = {s.number for box in blocks.LIBRARY.values()
             for s in box.settings if s.number} \
        | {s.number for one in PRESETS.values()
           for s in one.settings if s.number}
    assert taken == {number.name for number in flow.NUMBERS}


# -- 8. what the run cannot do is refused before it is saved ---------------------

def test_the_default_drawing_can_run():
    assert flow.problems(flow.load().tree) == []


def test_a_find_where_values_go_is_refused():
    drawing = tree()
    values = node(drawing, "values")
    values["steps"].insert(0, {"id": "lost_find", "box": "ask",
                               "preset": "find"})
    # what it takes (a chunk) no step before it gives (owner decision
    # 2026-11-12: where a step may stand follows from its inputs)
    assert any("takes the chunk" in m for m in said(drawing))


def test_a_question_of_a_coordinate_outside_each_value_is_refused():
    drawing = tree()
    drawing.insert(drawing.index(node(drawing, "values")),
                   {"id": "stray", "box": "ask", "preset": "coord"})
    assert any("takes the dimension" in m for m in said(drawing))


def test_a_step_asked_apart_from_the_reading_takes_what_its_target_gives():
    # The figures are written out before the document is cut: the step
    # takes the figure and nothing of the reading (owner decision
    # 2026-11-12 evening; the chunks of a field are ordered the same way,
    # by the field and the document alone).
    drawing = tree()
    figures = node(drawing, "figures")
    figures["set"] = {"inputs": [{"key": "figure", "from": "figure",
                                  "show": "figure_text"}]}
    assert said(drawing) == []
    # the failure by construction: an input of the reading
    figures["set"] = {"inputs": [{"key": "headings", "from": "chunk",
                                  "show": "headings"}]}
    assert any("asked apart from the reading" in m for m in said(drawing))


def test_a_frame_of_coordinates_without_a_state_is_refused():
    drawing = tree()
    frame = node(drawing, "coordinates")
    frame["steps"] = [{"id": "only", "box": "ask", "preset": "coord"}]
    assert any("needs a state box" in m for m in said(drawing))


def test_a_round_that_may_not_end_is_refused():
    drawing = tree()
    node(drawing, "search_round")["round"] = {"most": 0}
    assert any("1 or more" in m for m in said(drawing))
    node(drawing, "search_round")["round"] = {}
    assert any("may not end" in m or "is {" in m for m in said(drawing))
    # a round of most N needs no supply
    node(drawing, "search_round")["round"] = {"most": 2}
    assert said(drawing) == []


def test_a_question_whose_prompt_the_profile_does_not_write_is_refused(
        tmp_path):
    drawing = tree()
    profile = load_profile("kwp")
    # kwp writes no names and no work prompt: those boxes are never taken,
    # which is no problem; a prompt it must write is
    assert flow.prompt_problems(drawing, profile) == []
    prompts_dir = tmp_path / "prompts" / "extraction"
    prompts_dir.mkdir(parents=True)
    bare = dataclasses.replace(load_profile("default"), home=tmp_path)
    got = flow.prompt_problems(drawing, bare)
    assert got and all("writes no prompt" in p["message"] for p in got)


@pytest.mark.parametrize("change, part", [
    (lambda d: d.append({"id": "x", "box": "nothing"}), "there is no box"),
    (lambda d: d.append(dict(d[0])), "stands twice"),
    (lambda d: d.insert(0, d.pop(2)), "where the flow gives it"),
    (lambda d: d.append({"id": "late", "box": "ask", "preset": "compute"}),
     "compute stands once at most"),
    (lambda d: node(d, "own_place").update(loops=3), "has no key 'loops'"),
    (lambda d: node(d, "own_place").update(set={"mode": "x"}),
     "no setting 'mode'"),
    (lambda d: node(d, "own_place").update(own={"follow_ups": -1}),
     "at least 0"),
    (lambda d: node(d, "write").update(off=True), "cannot be off"),
    (lambda d: node(d, "pieces").update(off=True),
     "takes the chunks, and no step of the flow gives it"),
    (lambda d: node(d, "coordinate_way")["else"].insert(0, {
        "id": "early_check", "box": "check",
        "set": {"name": "n", "refuse": {"all": [
            {"of": "value", "is": "length", "op": "less", "value": 5}]},
            "sentence": "s"}}), "right after a question"),
])
def test_a_drawing_the_run_cannot_do_is_refused_by_what_is_wrong(change,
                                                                  part):
    drawing = tree()
    change(drawing)
    assert any(part in m for m in said(drawing)), said(drawing)


def test_a_file_without_a_drawing_or_with_steps_is_refused():
    data = default()
    data.pop("flow")
    assert "draws the flow" in refused(data)
    data = default()
    data["steps"] = data.pop("flow")
    assert "now a drawing" in refused(data)


def test_a_key_written_twice_is_refused():
    assert "'numbers' stands twice" in refused(
        '{"numbers": {}, "numbers": {}}', whole=False)


# -- 4. conditions --------------------------------------------------------------

def facts(values: dict):
    def get(subject, prop):
        if (subject, prop) not in values:
            raise LookupError(subject)
        return values[(subject, prop)]
    return conditions.Facts(get)


def test_each_kind_of_property_evaluates_as_it_says():
    short = {"all": [{"of": "quote", "is": "length", "op": "less",
                      "value": 20}]}
    assert conditions.holds(short, facts({("quote", "length"): 15}))
    assert not conditions.holds(short, facts({("quote", "length"): 25}))
    word = {"all": [{"of": "value", "is": "words", "op": "contains",
                     "value": "gas"}]}
    assert conditions.holds(word, facts({("value", "words"): "Erdgas"}))
    assert not conditions.holds(word, facts({("value", "words"): "Öl"}))
    empty = {"all": [{"of": "value", "is": "words", "op": "empty"}]}
    assert conditions.holds(empty, facts({("value", "words"): " "}))
    state = {"all": [{"of": "coordinate", "is": "state", "op": "one_of",
                      "value": ["open"]}]}
    for one, held in (("exhausted", True), ("unbacked", True),
                      ("unanswered", True), ("read", False),
                      ("", False)):
        assert conditions.holds(state, facts(
            {("coordinate", "state"): one})) is held
    none = {"all": [{"of": "coordinate", "is": "state", "op": "one_of",
                     "value": ["none"]}]}
    assert conditions.holds(none, facts({("coordinate", "state"): ""}))
    yes = {"any": [{"of": "answer", "is": "zero", "not": True},
                   {"of": "round", "is": "number", "op": "at_least",
                    "value": 2}]}
    assert conditions.holds(yes, facts({("answer", "zero"): False,
                                          ("round", "number"): 1}))
    assert not conditions.holds(yes, facts({("answer", "zero"): True,
                                              ("round", "number"): 1}))


@pytest.mark.parametrize("row, part", [
    ({"of": "quote", "is": "length", "op": "less"}, "value is missing"),
    ({"of": "quote", "is": "length", "op": "less", "value": "zwanzig"},
     "is a number"),
    ({"of": "quote", "is": "length", "op": "contains", "value": 3},
     "takes is"),
    ({"of": "coordinate", "is": "state", "op": "one_of", "value": ["fine"]},
     "not 'fine'"),
    ({"of": "weather", "is": "rain"}, "nothing a condition can be about"),
])
def test_a_condition_that_cannot_be_evaluated_is_refused_with_its_reason(
        row, part):
    got = conditions.problems({"all": [row]})
    assert got and part in got[0]


def test_a_quote_before_the_first_question_is_refused():
    drawing = tree()
    frame = node(drawing, "coordinates")
    frame["when"] = {"all": [{"of": "quote", "is": "length", "op": "less",
                              "value": 20}]}
    assert any("no question before it" in m for m in said(drawing))
    # after a question it is known
    frame.pop("when")
    node(drawing, "after_own_place")["if"][0]["when"] = {"all": [
        {"of": "quote", "is": "length", "op": "less", "value": 20}]}
    assert said(drawing) == []


def test_a_condition_says_itself_as_a_sentence():
    assert conditions.sentence({"all": [{
        "of": "quote", "is": "length", "op": "less", "value": 20}]}) \
        == "when the quote's length in characters is less than 20"


# -- a profile sets numbers, and only numbers -----------------------------------

def test_a_profile_s_file_is_laid_over_the_default_number_by_number(profile):
    before = flow.load(profile)
    assert before.numbers == flow.load().numbers
    assert set(before.owners.values()) == {"default"}
    write(profile, search_pieces=35)
    after = flow.load(profile)
    assert after.numbers == {**before.numbers, "search_pieces": 35}
    assert after.owners["search_pieces"] == "scenarios"
    assert after.owners["replies"] == "default"
    assert after.tree == before.tree
    assert after.sha256 != before.sha256
    assert flow.inherited(profile).numbers == before.numbers
    # the failure by construction: the default profile's own file inherits
    # from nothing
    assert flow.inherited(load_profile("default")) is None


def test_a_profile_s_own_drawing_is_its_whole_drawing(profile):
    drawing = tree()
    node(drawing, "search_round")["round"] = {"most": 2}
    flow.path_of(profile).write_text(flow.dump(
        {"numbers": {}, "flow": drawing}), encoding="utf-8")
    assert flow.load(profile).tree == drawing
    assert flow.load(profile).tree_from == profile.name
    # the failure by construction: a drawing the run cannot do
    node(drawing, "search_round")["round"] = {}
    flow.path_of(profile).write_text(flow.dump(
        {"numbers": {}, "flow": drawing}), encoding="utf-8")
    with pytest.raises(flow.FlowError, match="search_round"):
        flow.load(profile)


def test_the_file_is_written_in_one_form():
    text = flow.DEFAULT.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert flow.dump(json.loads(text)) == text
    # the failure by construction: a changed number changes one line
    data = json.loads(text)
    data["numbers"]["replies"] += 1
    changed = [pair for pair in zip(text.splitlines(),
                                    flow.dump(data).splitlines())
               if pair[0] != pair[1]]
    assert len(changed) == 1 and '"replies"' in changed[0][0]


# -- a number set in the file reaches the run -----------------------------------

def test_a_number_of_the_file_is_the_run_s_and_a_setting_wins(profile,
                                                             monkeypatch):
    write(profile, search_pieces=35, replies=5)
    numbers = runner.take_flow(profile)
    assert runner.search_budget()[0] == 35
    assert runner.reply_limit() == 5
    assert numbers.origin["search_pieces"] == "flow.json of scenarios"
    assert numbers.origin["search_per_request"] == "flow.json of default"
    # the failure by construction: a setting of the run wins over the file
    monkeypatch.setenv("EXTRACT_SEARCH_PIECES", "7")
    monkeypatch.setenv("EXTRACT_MAX_RETRIES", "2")
    numbers = runner.take_flow(profile)
    assert (runner.search_budget()[0], runner.reply_limit()) == (7, 2)
    assert numbers.origin["search_pieces"] == "environment"
    # and without the profile's file the default's number is read
    monkeypatch.delenv("EXTRACT_SEARCH_PIECES")
    flow.path_of(profile).unlink()
    assert runner.take_flow(profile).search_pieces \
        == flow.default().search_pieces


def test_the_three_shares_are_one_setting(profile, monkeypatch):
    monkeypatch.setenv("EXTRACT_SEARCH_SHARES", "1,2,3")
    monkeypatch.setenv("EXTRACT_SEARCH_CHUNKS", "2")
    runner.take_flow(profile)
    assert runner.search_budget()[1:] == ({"table": 1, "figure": 2,
                                           "section": 3}, 2)
    # the failures by construction: two numbers, and a word
    for value in ("1,2", "1,2,x"):
        monkeypatch.setenv("EXTRACT_SEARCH_SHARES", value)
        with pytest.raises(flow.FlowError, match="EXTRACT_SEARCH_SHARES"):
            runner.take_flow(profile)


def test_a_pass_that_reads_to_the_end_keeps_doing_so(profile):
    write(profile, search_pieces=35)
    runner.read_to_end()
    runner.take_flow(profile)
    assert runner.search_budget()[0] == runner.REST_TO_END


def test_the_numbers_cut_the_plan():
    lines = "\n".join(f"Zeile {i} nennt nichts." for i in range(1, 31))
    sources = [Source("section", 1, lines, {"document_id": 7, "page": 1}),
               *[Source("section", 10 + i, f"Abschnitt {i}.\nEr nennt nichts.",
                        {"document_id": 7, "page": 2 + i,
                         "section_title": f"Abschnitt {i}"})
                 for i in range(15)]]

    def plan(**numbers):
        return addressed.Plan(7, sources, {}, numbers=dataclasses.replace(
            flow.default(), **numbers))
    mine = plan(piece_lines=3, title_page_lines=4, headings=2)
    assert max(len(chunk.numbers) for chunk in mine.chunks) == 3
    assert len(mine.title_page) == 4
    assert len(mine.headings(("section", 24))) == 2
    # the failure by construction: other numbers cut it otherwise
    other = plan(piece_lines=5, title_page_lines=6, headings=3)
    assert max(len(chunk.numbers) for chunk in other.chunks) == 5
    assert len(other.title_page) == 6
    assert len(other.headings(("section", 24))) == 3


# -- the stamp names the flow of each pass and compares nothing of it -----------

def test_a_pass_names_the_numbers_it_read_with_and_none_makes_a_harvest_stale(
        profile, tmp_path):
    runner.take_flow(profile)
    before = runner._stamp_current("0" * 64)
    stamp = tmp_path / "plan.stamp.json"
    stamp.write_text(json.dumps({**before, **runner.stamp_record("plan")}),
                     encoding="utf-8")
    write(profile, search_pieces=35)
    numbers = runner.take_flow(profile)
    # The keys of the run, which are compared and which a pass over a stored
    # harvest carries forward, hold nothing of the flow.
    assert runner._stamp_current("0" * 64) == before
    assert runner.stale(stamp, runner._stamp_current("0" * 64)) == []
    (harvest,) = json.loads(stamp.read_text(encoding="utf-8"))["producers"]
    later = runner.producer("top-up", "a-model")
    assert harvest["numbers"] == flow.default().as_dict()
    assert later["numbers"]["search_pieces"] == 35
    assert later["flow_file"] == numbers.sha256 != harvest["flow_file"]
    # the failures by construction: a pass that asks no model read with no
    # numbers, and what is compared does make the harvest stale
    assert "numbers" not in runner.producer("remap")
    assert runner.stale(stamp, runner._stamp_current("1" * 64)) == ["spec"]


def test_a_pass_over_a_harvest_read_with_other_numbers_still_carries_its_keys(
        profile, tmp_path):
    # A stamp of a harvest read with the default's numbers, one question of
    # it since reworded.
    runner.take_flow(profile)
    stamp = tmp_path / "plan.stamp.json"
    stamp.write_text(json.dumps({
        **runner._stamp_current("0" * 64), "axis/p/year": "a" * 64,
        "axis/p/carrier": "c" * 64, **runner.stamp_record("plan")}),
        encoding="utf-8")
    write(profile, search_pieces=35)
    runner.take_flow(profile)
    current = {**runner._stamp_current("1" * 64), "axis/p/year": "b" * 64,
               "axis/p/carrier": "c" * 64}
    # A pass that settles the one question moves its key and, nothing else
    # being open, the sha of the spec file; the harvest's entry stays.
    assert remap.stamp_forward(stamp, current, {"axis/p/year"})
    stored = json.loads(stamp.read_text(encoding="utf-8"))
    assert (stored["axis/p/year"], stored["spec"]) == ("b" * 64, "1" * 64)
    assert stored["producers"][0]["numbers"] == flow.default().as_dict()
    # the failure by construction: with another question still open the sha
    # of the file stays where it was
    current = {**current, "spec": "2" * 64, "axis/p/year": "d" * 64,
               "axis/p/carrier": "e" * 64}
    assert remap.stamp_forward(stamp, current, {"axis/p/year"})
    stored = json.loads(stamp.read_text(encoding="utf-8"))
    assert (stored["axis/p/year"], stored["spec"]) == ("d" * 64, "1" * 64)
