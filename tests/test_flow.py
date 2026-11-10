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

import dataclasses
import json

import pytest

from docpipe.extraction import addressed, flow, remap, runner
from docpipe.extraction.pipeline import Source
from docpipe.profile import load_profile

SETTINGS = sorted({number.env for number in flow.NUMBERS if number.env})


@pytest.fixture(autouse=True)
def the_run_s_numbers_stay(monkeypatch):
    for name in ("NUMBERS", "MAX_RETRIES", "TO_END", "_flow_logged"):
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


def walk(steps):
    for step in steps:
        yield step
        yield from walk(step.get("steps") or ())


def refused(data, whole: bool = True) -> str:
    """What the loader says of a file it refuses."""
    with pytest.raises(flow.FlowError) as caught:
        flow.parse(data if isinstance(data, str) else json.dumps(data),
                   "flow.json", whole)
    return str(caught.value)


def without_step(data: dict, wanted: str) -> dict:
    def kept(steps):
        return [{**step, **({"steps": kept(step["steps"])}
                            if "steps" in step else {})}
                for step in steps if step["id"] != wanted]
    return {**data, "steps": kept(data["steps"])}


# -- the steps cannot say something else than the code ---------------------------

def test_every_request_the_code_sends_stands_in_a_step_and_no_other():
    asked = {step["ask"] for step in walk(flow.load().steps)
             if "ask" in step}
    assert asked == set(flow.kinds())
    assert set(addressed.KINDS) <= asked
    # the failure by construction: the step that asks `check` taken out
    assert "check" in refused(without_step(default(), "about"))
    # and a step that asks what the code does not send
    data = default()
    data["steps"][0]["ask"] = "guess"
    assert "'guess'" in refused(data)


def test_a_request_the_code_gains_fails_the_flow_until_a_step_asks_it(
        monkeypatch):
    text = flow.DEFAULT.read_text(encoding="utf-8")
    flow.parse(text, "flow.json", True)
    monkeypatch.setattr(addressed, "KINDS", addressed.KINDS + ("recount",))
    assert "recount" in refused(text)


def test_the_file_names_exactly_the_numbers_the_run_takes():
    names = [number.name for number in flow.NUMBERS]
    assert list(default()["numbers"]) == names
    assert list(flow.default().as_dict()) == names
    # the failures by construction: a number the code does not take, one
    # that is missing, one that is no whole number, one below its least
    data = default()
    data["numbers"]["search_depth"] = 3
    assert "'search_depth' is no number of the flow" in refused(data)
    data = default()
    del data["numbers"]["replies"]
    assert "names no replies" in refused(data)
    for value, said in ((2.5, "whole number"), (True, "whole number"),
                        ("3", "whole number"), (0, "at least 1")):
        data = default()
        data["numbers"]["replies"] = value
        assert said in refused(data)


def test_every_number_bounds_a_step():
    bounded = {place for step in walk(flow.load().steps)
               for place in flow.PLACE.findall(step.get("bound", ""))}
    assert bounded == {number.name for number in flow.NUMBERS}
    # the failure by construction: the one step bounded by it says no more
    data = default()
    step = next(s for s in walk(data["steps"]) if s["id"] == "entry")
    del step["bound"]
    assert "list_meanings bounds no step" in refused(data)
    data = default()
    data["steps"][1]["bound"] = "at most {lines} lines"
    assert "{lines}" in refused(data)


@pytest.mark.parametrize("change, said", [
    (lambda data: data.update(order=["figures"]), "has no key 'order'"),
    (lambda data: data["steps"][0].pop("says"), "must say what it does"),
    (lambda data: data["steps"][0].update(loops=3), "has no key 'loops'"),
    (lambda data: data["steps"].append(dict(data["steps"][0])),
     "stands twice"),
    (lambda data: data["steps"][0].update(needs="mood"), "no switch"),
    (lambda data: data.update(steps=[]), "not empty"),
])
def test_a_file_the_run_cannot_read_is_refused_by_what_is_wrong(change,
                                                                said):
    data = default()
    change(data)
    assert said in refused(data)


def test_a_key_written_twice_is_refused():
    assert "'numbers' stands twice" in refused(
        '{"numbers": {}, "numbers": {}}', whole=False)


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
    assert after.steps == before.steps
    assert after.sha256 != before.sha256
    assert flow.inherited(profile).numbers == before.numbers
    # the failure by construction: the default profile's own file inherits
    # from nothing
    assert flow.inherited(load_profile("default")) is None


def test_a_profile_s_file_writes_all_the_steps_or_none(profile):
    # Since 2026-11-10 the run reads its steps from the file, and a profile
    # may set them: all of them, in an order the code can run.
    steps = default()["steps"]
    flow.path_of(profile).write_text(flow.dump(
        {"numbers": {}, "steps": steps}), encoding="utf-8")
    assert flow.load(profile).steps == steps
    assert flow.load(profile).steps_from == profile.name
    # the failure by construction: a step left out
    flow.path_of(profile).write_text(flow.dump(
        {"numbers": {}, "steps": steps[:-1]}), encoding="utf-8")
    with pytest.raises(flow.FlowError, match="stands 0 times"):
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
    assert runner.MAX_RETRIES == 5
    assert numbers.origin["search_pieces"] == "flow.json of scenarios"
    assert numbers.origin["search_per_request"] == "flow.json of default"
    # the failure by construction: a setting of the run wins over the file
    monkeypatch.setenv("EXTRACT_SEARCH_PIECES", "7")
    monkeypatch.setenv("EXTRACT_MAX_RETRIES", "2")
    numbers = runner.take_flow(profile)
    assert (runner.search_budget()[0], runner.MAX_RETRIES) == (7, 2)
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
