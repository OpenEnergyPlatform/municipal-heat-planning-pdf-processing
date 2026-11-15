"""
test_value_check_live.py: the check of a value as soon as it is read (owner
decision 2026-11-15: the check sits in the harvest, not in a run after it;
`engine.Engine.box_check_value`, `check_row`).

The promises, each with a case that breaks it by construction:

1. A dimension that does not hold is asked again at once, through the steps
   of the value's coordinate frame, with the reason shown to that request,
   AND it stays read where the new answer holds.
2. Where the new answer does not hold either, it is unbacked.
3. A value that does not hold is refused as unbacked where its second
   reading does not agree, AND stays where it agrees.
4. A check nobody answered leaves the row as it was; a reader without a
   checking asks nothing.
5. Every value frame of both profiles checks its values after their
   dimensions.

Author: Felix Vossel
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import engine as engine_map
from docpipe.extraction import fields, passboxes
from docpipe.extraction import flow as flow_map
from docpipe.extraction.pipeline import Row
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import REVIEW_AGREE, REVIEW_DISAGREE

REPO = Path(__file__).resolve().parent.parent
SPEC = load_spec(json.loads(
    (REPO / "profiles" / "kwp" / "extraction_spec.json").read_text(
        encoding="utf-8")))
PARAMETER = next(p for p in SPEC.parameters if fields.asked_slots(p))
SLOTS = fields.asked_slots(PARAMETER)
FIRST = SLOTS[0]
SOURCE = SimpleNamespace(owner_kind="table", owner_id=7,
                         text="| Erdgas | 241 | MWh/a |")


def claim_of() -> dict:
    claim = {"parameter": PARAMETER.uri, "value": 241,
             "quote": "| Erdgas | 241 |"}
    for slot in SLOTS:
        claim.update({slot.name: "x", f"{slot.name}_state": fields.READ,
                      f"{slot.name}_quote": "| Erdgas | 241 |"})
    return claim


class Scope:
    def __init__(self, **values):
        self.values = values

    def get(self, name):
        return self.values.get(name)

    def child(self, _new, **more):
        return Scope(**{**self.values, **more})


def run(failing_rounds, *, review=REVIEW_AGREE, answer=True):
    """check_row over one row; *failing_rounds* are the names each check
    says do not hold, in order. Returns the claim, what the asking again
    saw and how often it was asked."""
    claim = claim_of()
    row = Row("r", 0, claim)
    rounds = list(failing_rounds)
    seen: dict = {"asked": 0, "shown": []}

    def check(view, parameter, slots, shown):
        if not answer:
            return None
        assert shown[("table", 7)] is SOURCE
        bad = rounds.pop(0) if rounds else ()
        names = ["value"] + [slot.name for slot in slots]
        return {name: (name not in bad, "the line says something else")
                for name in names}

    def again(steps, scope):
        coord = scope.get("coord")
        seen["asked"] += 1
        seen["shown"].append(passboxes.not_held(coord.row.claim,
                                                coord.slot.name))
        coord.row.claim[coord.slot.name] = "y"
        coord.row.claim[f"{coord.slot.name}_state"] = fields.READ

    checking = SimpleNamespace(
        check=check, owner_sources=lambda pairs: {},
        review_sources=lambda row: [SOURCE],
        review=lambda row, parameter, sources: review)
    fake = SimpleNamespace(
        slot_sequence=lambda parameter: [(None, slot) for slot in SLOTS],
        run_steps=again)
    value = SimpleNamespace(
        read=SimpleNamespace(batch=SimpleNamespace(
            items=[SimpleNamespace(source=SOURCE)], document_id=1)),
        rows=[row], clone=lambda one: one)
    scope = Scope(doc=SimpleNamespace(seen_of={}))
    engine_map.Engine.check_row(fake, checking, scope, value, row,
                                PARAMETER, {"each": "coordinate",
                                            "steps": []})
    return claim, seen


# 1 -----------------------------------------------------------------------

def test_a_dimension_that_does_not_hold_is_asked_again_with_its_reason():
    claim, seen = run([(FIRST.name,), ()])
    assert seen["asked"] == 1
    assert seen["shown"] == [{"answer": "x", "quote": "| Erdgas | 241 |",
                              "why": "the line says something else"}]
    assert claim[FIRST.name] == "y"
    assert claim[f"{FIRST.name}_state"] == fields.READ
    assert f"node_check:{FIRST.name}" in claim["flags"]
    assert passboxes.not_held(claim, FIRST.name) is None
    # the failure by construction: nothing failing, nothing asked again
    claim, seen = run([()])
    assert seen["asked"] == 0 and "flags" not in claim


# 2 -----------------------------------------------------------------------

def test_a_dimension_that_does_not_hold_again_is_unbacked():
    claim, _seen = run([(FIRST.name,), (FIRST.name,)])
    assert claim[f"{FIRST.name}_state"] == fields.UNBACKED


# 3 -----------------------------------------------------------------------

def test_a_value_falls_where_its_second_reading_disagrees():
    claim, _seen = run([("value",)], review=REVIEW_DISAGREE)
    assert claim["_why"] == fields.UNBACKED
    claim, _seen = run([("value",)], review=REVIEW_AGREE)
    assert "_why" not in claim


# 4 -----------------------------------------------------------------------

def test_an_unanswered_check_leaves_the_row_and_no_checking_asks_nothing():
    claim, seen = run([], answer=False)
    assert claim == claim_of() and seen["asked"] == 0
    reader = SimpleNamespace()
    fake = SimpleNamespace(reader=reader)
    value = SimpleNamespace(read=SimpleNamespace(batch=SimpleNamespace(
        parameter=PARAMETER)), rows=[Row("r", 0, claim_of())])
    engine_map.Engine.box_check_value(fake, {}, Scope(value=value))
    assert value.rows[0].claim == claim_of()


# 5 -----------------------------------------------------------------------

def test_every_value_frame_checks_its_values_after_their_dimensions():
    from docpipe.profile import load_profile
    for name in ("kwp", "scenarios"):
        tree = flow_map.tree_of(load_profile(name))
        frames = [node for node, _ in flow_map.walk(tree)
                  if node.get("each") == "value"]
        assert frames, name
        for frame in frames:
            order = [step.get("each") or step.get("box")
                     for step in frame.get("steps") or []]
            assert order.index("check_value") == order.index(
                "coordinate") + 1, (name, order)
            check = next(step for step in frame["steps"]
                         if step.get("box") == "check_value")
            fake = SimpleNamespace(tree=tree)
            assert engine_map.Engine.sibling_frame(
                fake, check, "coordinate")["each"] == "coordinate"
