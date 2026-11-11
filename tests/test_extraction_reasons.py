"""
The reasons a run refuses an answer for are the ones agreed (owner rule:
no new check, no new reason, no new filter without the owner's consent):
the two checks of a quote, its least length, the list, and the address of
a line (`schema.DROP_REASONS`). An own check of the flow, drawn in the page
(owner decision 2026-11-10), refuses under its own name, `check:<name>`, and
under no other.

The promises, each with a case that breaks it by construction:

1. The flow the code brings refuses only for the agreed reasons, AND with
   answers that miss in every way it can, it refuses for several of them.
2. An own check adds exactly its own reason, AND a reason nobody agreed to
   is found.
"""
import copy

from docpipe.extraction import addressed, flow, schema
from docpipe.extraction.addressed import Reader
from docpipe.extraction.pipeline import Source

from test_addressed import ENERGY, SPEC, TABLE, TEXT, Model, in_order, plan_of

# The reasons agreed, written out: a new one is added here, openly.
AGREED = {"quote_not_in_source", "quote_too_short", "answer_not_in_quote",
          "not_an_option", "wrong_type", "unbacked", "not_an_address",
          "words_not_in_line"}


def unagreed(reasons) -> set:
    """The reasons of *reasons* nobody agreed to: neither listed nor an own
    check's of the flow."""
    return {why for why in reasons
            if why not in AGREED and not str(why).startswith("check:")}


def missing_in_every_way(p, n):
    """A find whose address names no line, one whose words stand not in
    their line, and one that holds."""
    if p.get("passage", {}).get("kind") != "table":
        return {"found": [{"at": "Z9", "words": "300"}]}
    return {"found": [{"at": "3.2", "words": "1.200"},
                      {"at": "3.3", "words": "99"},
                      {"at": "Z1", "words": "1"}]}


def wrong_coordinate(p, n):
    return {"at": "1", "words": "nicht hier"} \
        if n.get("coordinate") in ("year", "what") else {"at": 0}


def reasons(drawing=None) -> set:
    model = Model(find=missing_in_every_way, coord=wrong_coordinate,
                  follow=lambda p, n: None)
    counts = addressed.Counts()
    Reader(SPEC, model.asks(), in_order, flow=drawing)(
        plan_of(TEXT, TABLE), [ENERGY], counts=counts)
    return set(counts.failed)


def test_the_list_of_reasons_is_the_schema_s():
    assert AGREED == set(schema.DROP_REASONS)


def test_the_flow_the_code_brings_refuses_only_for_the_agreed_reasons():
    got = reasons()
    assert len(got) >= 2
    assert unagreed(got) == set()


def test_an_own_check_adds_exactly_its_own_reason():
    drawing = copy.deepcopy(flow.load().tree)
    steps = next(n for n, _ in flow.walk(drawing)
                 if n.get("id") == "coordinate_way")["else"]
    at = next(i for i, n in enumerate(steps) if n.get("id") == "own_place")
    steps.insert(at + 1, {"id": "short", "box": "check", "set": {
        "name": "kurz", "refuse": {"all": [{"of": "quote", "is": "length",
                                            "op": "less", "value": 400}]},
        "sentence": "Quote more."}})
    model = Model(find=missing_in_every_way,
                  coord=lambda p, n: {"at": "1", "words": "Verbrauch"}
                  if n.get("coordinate") == "what" else {"at": 0})
    counts = addressed.Counts()
    Reader(SPEC, model.asks(), in_order, flow=drawing)(
        plan_of(TEXT, TABLE), [ENERGY], counts=counts)
    got = set(counts.failed)
    assert "check:kurz" in got
    assert unagreed(got) == set()
    assert got - AGREED == {"check:kurz"}


def test_a_reason_nobody_agreed_to_is_found():
    # the failure by construction: a reason of an unagreed check
    assert unagreed({"quote_not_unique", "not_an_address"}) \
        == {"quote_not_unique"}
    assert unagreed({"check:kurz"}) == set()
