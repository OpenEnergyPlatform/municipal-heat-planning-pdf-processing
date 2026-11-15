"""
test_node_check.py: what the check of the filled nodes promises (owner
decision 2026-11-15, `passboxes.box_node_check`, `runner.around`,
`runner._node_check_payload`, `replies.node_check_verdicts`).

The promises, each with a case that breaks it by construction:

1. The check sees the text around each quote, as many characters on each
   side as the rule says, AND nothing where the passage does not hold the
   quote.
2. A reply is read only where it says true or false for the value and for
   every dimension asked, AND a field left out, a field asked of nobody or a
   verdict that is no boolean is no reply.
3. A dimension that does not hold becomes unbacked, so the steps after it
   ask it again, AND one that holds stays read.
4. A value that does not hold falls where its second reading does not
   agree, AND stays where it does.
5. A node nobody answered is left as it was and holds the stamp back.
6. The flow of the pass asks the open dimensions after the check.

Author: Felix Vossel
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from docpipe import rules
from docpipe.extraction import fields, passboxes, passflow, replies, runner
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import REVIEW_AGREE, REVIEW_DISAGREE

REPO = Path(__file__).resolve().parent.parent
SPEC = load_spec(json.loads(
    (REPO / "profiles" / "kwp" / "extraction_spec.json").read_text(
        encoding="utf-8")))
PARAMETER = next(p for p in SPEC.parameters if fields.asked_slots(p))
SLOTS = fields.asked_slots(PARAMETER)
TEXT = ("Die Tabelle zeigt den Endenergieverbrauch. | Erdgas | 241 | MWh/a | "
        "Danach folgt der Abschnitt zur Fernwärme.")


def row_of() -> dict:
    row = {"kind": "tuple", "parameter": PARAMETER.uri, "value": 241,
           "quote": "| Erdgas | 241 |",
           "provenance": {"owner_kind": "table", "owner_id": 1}}
    for slot in SLOTS:
        row.update({slot.name: "x", f"{slot.name}_state": fields.READ,
                    f"{slot.name}_quote": "| Erdgas | 241 |"})
    return row


def doc_of(rows: list, *, check, ask=None):
    run = SimpleNamespace(
        check=check, ask=ask,
        sources_for=lambda row: [SimpleNamespace(text=TEXT)],
        deps={"owner_sources": lambda pairs: {
            pair: SimpleNamespace(text=TEXT) for pair in pairs}})
    doc = passboxes.Doc(run, Path("a.jsonl"))
    doc.stored = SimpleNamespace(tuples=rows, refusals=[])
    doc.doc_spec = SimpleNamespace(by_uri={PARAMETER.uri: PARAMETER})
    return run, doc


def verdicts(failing=()) -> callable:
    def check(row, parameter, slots, shown):
        names = ["value"] + [slot.name for slot in slots]
        return {name: (name not in failing, "" if name not in failing
                       else "the text says something else")
                for name in names}
    return check


# 1 -----------------------------------------------------------------------

def test_the_check_sees_the_text_around_each_quote():
    with rules.overlaid(node_check_context_chars=10):
        got = runner.around(TEXT, "| Erdgas | 241 |", 10)
    at = TEXT.find("| Erdgas | 241 |")
    assert got == TEXT[at - 10:at + len("| Erdgas | 241 |") + 10]
    assert runner.around(TEXT, "| Heizöl | 99 |", 10) is None
    with rules.overlaid(node_check_context_chars=10):
        body = runner._node_check_payload(
            row_of(), {("table", 1): SimpleNamespace(text=TEXT)},
            PARAMETER, SLOTS)
    assert body["quotes"][0]["around"] == got
    assert body["node"]["value"] == 241


# 2 -----------------------------------------------------------------------

def test_a_reply_is_read_only_with_a_verdict_for_every_field():
    names = ["value", "carrier"]
    good = {"checks": [{"field": "value", "holds": True, "why": ""},
                       {"field": "carrier", "holds": False, "why": "Heizöl"}]}
    assert replies.node_check_verdicts(good, names) == {
        "value": (True, ""), "carrier": (False, "Heizöl")}
    left_out = {"checks": good["checks"][:1]}
    nobodys = {"checks": good["checks"] + [
        {"field": "sector", "holds": True, "why": ""}]}
    no_bool = {"checks": [{"field": "value", "holds": "yes", "why": ""},
                          good["checks"][1]]}
    twice = {"checks": good["checks"] + good["checks"][:1]}
    for bad in (left_out, nobodys, no_bool, twice, [], {"checks": {}}):
        assert replies.node_check_verdicts(bad, names) is None


# 3 -----------------------------------------------------------------------

def test_a_dimension_that_does_not_hold_becomes_unbacked_and_open():
    first = SLOTS[0].name
    row = row_of()
    _run, doc = doc_of([row], check=verdicts(failing=(first,)))
    passboxes.box_node_check(doc.run, doc, {})
    assert row[f"{first}_state"] == fields.UNBACKED
    assert f"node_check:{first}" in row["flags"]
    assert all(row[f"{s.name}_state"] == fields.READ for s in SLOTS[1:])
    assert fields.UNBACKED in fields.OPEN
    assert row["kind"] == "tuple" and not doc.demoted


# 4 -----------------------------------------------------------------------

def test_a_value_that_does_not_hold_falls_where_the_second_reading_disagrees(
        monkeypatch):
    from docpipe.extraction import review
    row = row_of()
    _run, doc = doc_of([row], check=verdicts(failing=("value",)),
                       ask=lambda *a: {})
    monkeypatch.setattr(review, "review_row",
                        lambda *a, **k: REVIEW_DISAGREE)
    passboxes.box_node_check(doc.run, doc, {})
    assert row["kind"] == "refusal" and row["reason"] == fields.UNBACKED
    assert row["claim"]["value"] == 241 and doc.demoted == [row]


def test_a_value_the_second_reading_agrees_with_stays(monkeypatch):
    from docpipe.extraction import review
    row = row_of()
    _run, doc = doc_of([row], check=verdicts(failing=("value",)),
                       ask=lambda *a: {})
    monkeypatch.setattr(review, "review_row", lambda *a, **k: REVIEW_AGREE)
    passboxes.box_node_check(doc.run, doc, {})
    assert row["kind"] == "tuple" and not doc.demoted


# 5 -----------------------------------------------------------------------

def test_a_node_nobody_answered_is_left_and_holds_the_stamp():
    row = row_of()
    before = json.dumps(row, sort_keys=True)
    _run, doc = doc_of([row], check=lambda *a: None)
    passboxes.box_node_check(doc.run, doc, {})
    assert json.dumps(row, sort_keys=True) == before
    assert doc.guard and doc.stats["nodes not answered"] == 1


# 6 -----------------------------------------------------------------------

def test_the_flow_asks_the_open_dimensions_after_the_check():
    tree = passflow.load("node_check")
    order = [node.get("box") or node.get("each") for node in tree]
    assert order.index("ask") < order.index("open") < order.index(
        "dimension") < order.index("replace")
    assert passflow.problems(tree) == []
    assert passflow.startable(tree) is None


# 7 -----------------------------------------------------------------------

def test_the_summary_keeps_the_two_kinds_of_gap_apart():
    left, said = row_of(), row_of()
    left[f"{SLOTS[0].name}_state"] = fields.EXHAUSTED
    said[f"{SLOTS[0].name}_state"] = fields.SAID_UNSTATED
    run = SimpleNamespace()
    doc = passboxes.Doc(run, Path("a.jsonl"))
    doc.stored = SimpleNamespace(tuples=[left, said], refusals=[])
    doc.doc_spec = SPEC
    doc.open_mode = True
    passboxes.box_summary(run, doc, {})
    assert doc.stats["open coordinates left"] == 1
    assert doc.stats["coordinates the document does not state"] == 1
