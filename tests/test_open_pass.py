"""The pass over a stored harvest: which coordinates it asks again, that an
open one is only ever replaced by an answer, and what was read is every
source of a rows request."""
import json
from pathlib import Path

from docpipe.extraction import fields, topup
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.topup_rest import owners_in

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
SLOTS = {s.name: s for s in fields.axis_slots(SPEC.by_uri["energy_consumption"])}


def row(**states):
    return {"kind": "tuple", "parameter": "energy_consumption",
            **{f"{name}_state": state for name, state in states.items()}}


def test_every_open_coordinate_is_asked_and_nothing_else():
    rows = [row(carrier=fields.EXHAUSTED, sector=fields.READ),
            row(carrier=fields.SAID_UNSTATED, sector=fields.UNANSWERED),
            row(carrier=fields.OUT_OF_SLICE, sector=fields.UNBACKED),
            row(carrier=fields.READ, sector=fields.DERIVED)]
    got = {slot.name: [rows.index(r) for r in found]
           for _p, slot, found in topup.open_coordinates(rows, SPEC)}
    assert got == {"carrier": [0], "sector": [1, 2]}
    assert topup.open_coordinates([row(carrier=fields.READ)], SPEC) == []


def test_an_open_coordinate_is_replaced_only_by_an_answer():
    """`unstated` after the whole document is an answer; running out again
    is not, and the old block comes back."""
    slot = SLOTS["carrier"]
    for new, kept in ((fields.READ, True), (fields.SAID_UNSTATED, True),
                      (fields.EXHAUSTED, False)):
        claim = {"carrier_state": fields.EXHAUSTED, "carrier_window": ["rest", 12]}
        taken = topup.reopen(claim, slot)
        assert claim == {}
        claim["carrier_state"] = new
        restored = topup.restore(claim, slot, taken, keep=topup.keep_asked())
        assert restored is not kept
        assert claim["carrier_state"] == (new if kept else fields.EXHAUSTED)


def test_what_was_read_is_every_source_of_a_rows_request():
    events = [{"t": "rows", "sources": [["table", 1], ["section", 2]]},
              {"t": "plan", "kind": "figure", "owner": 3},
              {"t": "field", "shown": [["figure", 4]]},
              {"t": "rows", "sources": [["figure", 5], "broken"]},
              "not an event"]
    assert owners_in(events) == {("table", 1), ("section", 2), ("figure", 5)}


