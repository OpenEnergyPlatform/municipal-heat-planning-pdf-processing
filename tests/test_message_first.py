"""What stays the same over the requests of a field or a document stands first
in a request's message (owner request 2026-11-19, point D2 of the review of
that day): the server computes a beginning two requests share once.

The promises, each with a case that breaks it by construction:

1. The fields the rule `message_first` names come first, in its order, AND
   every other field follows in its own order; no field is lost or added.
2. With the rule empty, the message is in the order of the step's inputs.
3. A request of the dry run is shown as it goes out: a list request's
   message starts with its list, AND a request without a list starts with
   the next field of the rule it carries.
"""
from __future__ import annotations

import json

from docpipe import rules
from docpipe.editor import flowtry
from docpipe.extraction import flow as flow_files, runner
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile

PAYLOAD = {"words": "Erdgas", "value": {"at": "A3"}, "lines": ["A3 x"],
           "settings": ["F1 y"], "list": ["1 Erdgas", "2 Strom"],
           "question": "Welcher Energieträger?", "earlier": []}


def test_the_fields_of_the_rule_come_first_and_the_rest_keep_their_order():
    with rules.overlaid(message_first=["list", "question", "settings"]):
        got = runner.first_shown(PAYLOAD)
    assert list(got) == ["list", "question", "settings", "words", "value",
                         "lines", "earlier"]
    assert got == PAYLOAD                  # the same fields and values


def test_with_the_rule_empty_the_message_keeps_the_order_of_the_inputs():
    with rules.overlaid(message_first=[]):
        assert list(runner.first_shown(PAYLOAD)) == list(PAYLOAD)
    # the failure by construction: a field the rule names moves
    with rules.overlaid(message_first=["earlier"]):
        assert list(runner.first_shown(PAYLOAD))[0] == "earlier"


def test_the_dry_run_shows_a_request_as_it_goes_out(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    profile = load_profile("kwp")
    with rules.overlaid():
        rules.use(profile)
        spec = load_spec(json.loads(open(profile.component(
            "extraction", "SPEC_PATH"), encoding="utf-8").read()))
        out = flowtry.run(profile, spec, flow_files.load(profile).tree,
                          flow_files.in_effect(profile),
                          flowtry.example_sources(spec), "first_line")
        order = rules.get("message_first")
    firsts = [box["first"] for box in out["boxes"].values() if box["first"]]
    assert firsts
    for first in firsts:
        keys = list(json.loads(first["message"]))
        ruled = [key for key in order if key in keys]
        assert keys[:len(ruled)] == ruled, (first["kind"], keys)
    listed = [f for f in firsts if f["kind"] == "list"]
    assert listed and all(list(json.loads(f["message"]))[0] == "list"
                          for f in listed)
