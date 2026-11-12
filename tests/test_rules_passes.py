"""
The rules of the passes over a stored harvest, each read where a step of a
pass flow uses it (owner decision 2026-11-11, the promise of a step
value): a rule set at the box of a pass changes what that box does, AND the
standard gives today's result, AND a value set at another box of the flow
does not reach it.

Author: Felix Vossel
"""
import json
from types import SimpleNamespace

import pytest

from docpipe import prompts, rules
from docpipe.extraction import (fields, passflow, review, runner,
                                topup, topup_parameter)
from docpipe.extraction.pipeline import Source

from test_ruleset_passes import SPEC, energy
from conftest import step_node

DEFAULT = rules.default()


def at(kind: str, values: dict):
    """What the engine does around a box of *kind* that sets *values*."""
    return rules.in_step(rules.stepped(step_node(kind), values))


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


# -- the review flow's box picks the rows it reviews --------------------------

def reviewed_by(tmp_path, **at_box):
    """How many rows the flow `review` reads a second time, where the rules
    *at_box* are set at its step of that kind, as {kind of step
    (`rules.step_kind`): {rule: value}}."""
    rows = [energy(1, provenance={"owner_kind": "section", "owner_id": 1}),
            energy(2, carrier="exhausted", provenance={
                "owner_kind": "section", "owner_id": 1}),
            energy(3, carrier="unbacked", provenance={
                "owner_kind": "section", "owner_id": 1})]
    (tmp_path / "d.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    source = SimpleNamespace(owner_kind="section", owner_id=1, text="t")
    tree = json.loads(json.dumps(passflow.load("review")))
    for node in tree:
        node.setdefault("rules", {}).update(
            at_box.get(rules.step_kind(node), {}))
    kept = passflow.load
    passflow.load = lambda name, profile=None: tree
    try:
        return review.run(tmp_path, SPEC, ask=lambda *a: {},
                          sources_for=lambda row: [source])["reviewed"]
    finally:
        passflow.load = kept


def test_the_levels_set_at_the_review_box_pick_the_rows_it_reviews(tmp_path):
    assert reviewed_by(tmp_path) == 2                      # the lowest two
    assert reviewed_by(tmp_path, review={"review_levels": ["A"]}) == 1
    assert reviewed_by(tmp_path, review={
        "review_levels": ["A", "C", "D"]}) == 3
    # the failure by construction: the same value at another box of the
    # flow is that box's own and does not reach the review
    assert reviewed_by(tmp_path, summary={"review_levels": ["A"]}) == 2
    assert reviewed_by(tmp_path, review={"review_once_per_row": False,
                                         "review_levels": ["D"]}) == 1


# -- the prompt of the review is composed where the review box asks ---------

def test_the_least_quote_set_at_the_review_box_is_in_its_prompt(monkeypatch):
    sent = []

    def create(**request):
        sent.append(request["messages"][0]["content"])
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
    slots = fields.asked_slots(parameter)[:1]

    def asked(home_values):
        monkeypatch.setattr(runner, "in_home", lambda kind: at(
            kind, home_values))
        runner.make_review_asker(None)(row, shown, parameter, slots)
        return sent[-1]
    standard = asked({})
    least = DEFAULT["quote_min_chars"]
    assert f"{least} Zeichen" in standard or f"{least} characters" in standard
    own = asked({"quote_min_chars": 77})
    assert "77" in own and "77" not in standard
    # the failure by construction: a prompt composed before the box (as the
    # asker was made) would carry the run's number whatever the box sets
    with rules.overlaid(quote_min_chars=55):
        assert "55" in asked({})
        assert "77" in asked({"quote_min_chars": 77})
    assert prompts.load(runner.REVIEW_PROMPT_ID).text == standard


# -- what a pass reads again and what it keeps --------------------------------

def test_the_states_of_a_new_reading_that_replace_the_old_are_the_box_s():
    slot = next(s for s in fields.axis_slots(SPEC.by_uri[
        "energy_consumption"]) if s.name == "carrier")
    taken = {"carrier_state": "read", "carrier": "OEO_1"}

    def restored(keep_states):
        with at("better", keep_states):
            claim = {"carrier_state": "derived"}
            return topup.restore(claim, slot, taken, keep=topup.keep_read())
    assert topup.keep_read() == ("read", "derived")
    assert restored({}) is False                      # derived stays
    assert restored({"reread_keep_states": ["read"]}) is True
    # the failure by construction: a state that is no state of the rule's
    # list is no reason to keep what the new reading made
    assert restored({"reread_keep_states": ["exhausted"]}) is True
    assert topup.keep_read() == ("read", "derived")   # outside the box


def stamped_for_a_new_parameter(monkeypatch, tmp_path, moved: bool):
    new = SPEC.parameters[0]
    found = topup_parameter.Addition({"slot/parameter": "x"}, [new], set(),
                                     set(), [])
    monkeypatch.setattr(topup_parameter, "addition",
                        lambda *a, **k: (found, ""))
    monkeypatch.setattr(topup_parameter, "read_harvest",
                        lambda path: SimpleNamespace(states=[], tuples=[]))
    monkeypatch.setattr(topup_parameter, "derivation_moved",
                        lambda *a, **k: moved)
    return lambda: topup_parameter.classify(
        tmp_path / "a.stamp.json", {}, SPEC, tmp_path / "a.jsonl",
        doc_spec_of=lambda: SPEC)


def test_a_moved_derivation_blocks_a_document_unless_the_box_says_not(
        monkeypatch, tmp_path):
    classify = stamped_for_a_new_parameter(monkeypatch, tmp_path, True)
    assert classify().kind == "blocked"               # the standard
    with at("classify", {"parameter_pass_blocks_on_derivation": False}):
        assert classify().kind == "new"
    # the failure by construction: no derivation moved, nothing to block
    classify = stamped_for_a_new_parameter(monkeypatch, tmp_path, False)
    assert classify().kind == "new"
    with at("classify", {"parameter_pass_blocks_on_derivation": True}):
        assert classify().kind == "new"


# -- how long a pass looks away from its documents --------------------------

def test_the_pause_between_two_looks_is_the_value_of_the_box_that_starts():
    start = {"id": "s", "box": "stored"}
    assert passflow._poll(start) == (DEFAULT["document_poll_s"],
                                     DEFAULT["document_poll_room_s"])
    assert passflow._poll({**start, "rules": {
        "document_poll_s": 0.5}}) == (0.5, DEFAULT["document_poll_room_s"])
    assert passflow._poll({**start, "rules": {
        "document_poll_room_s": 9}}) == (DEFAULT["document_poll_s"], 9)
    # the failure by construction: both set, each is read for what it is
    assert passflow._poll({**start, "rules": {
        "document_poll_s": 0.25, "document_poll_room_s": 7}}) == (0.25, 7)
