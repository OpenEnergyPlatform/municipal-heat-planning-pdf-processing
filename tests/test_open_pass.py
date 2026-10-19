"""The pass over a stored harvest: which coordinates it asks again, that an
open one is only ever replaced by an answer, and that a passage already
asked for values is not asked again."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docpipe.extraction import fields, runner, topup
from docpipe.extraction.pipeline import DocumentReport, Source, WorkItem
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
        restored = topup.restore(claim, slot, taken, keep=topup.KEEP_ASKED)
        assert restored is not kept
        assert claim["carrier_state"] == (new if kept else fields.EXHAUSTED)


def test_reading_to_the_end_lifts_only_the_rest_budget(monkeypatch):
    monkeypatch.setattr(runner, "REST_MAX_WINDOWS", 12)
    before = runner.window_budget()
    runner.read_to_end()
    after = runner.window_budget()
    assert after["rest"] == runner.REST_TO_END
    assert (after["own"], after["retrieval"]) == (before["own"],
                                                  before["retrieval"])


def test_what_was_read_is_every_source_of_a_rows_request():
    lines = [json.dumps({"t": "rows", "sources": [["table", 1], ["section", 2]]}),
             json.dumps({"t": "plan", "kind": "figure", "owner": 3}),
             json.dumps({"t": "field", "shown": [["figure", 4]]}),
             json.dumps({"t": "rows", "sources": [["figure", 5], "broken"]}),
             "not json \"rows\""]
    assert owners_in(lines) == {("table", 1), ("section", 2), ("figure", 5)}


def source(owner, text):
    return Source("table", owner, text, {"document_id": 7})


READ = source(1, "Zielszenario 2045 | Erdgas | 12 | MWh/a |")
UNREAD = source(2, "Zielszenario 2045 | Biomasse | 3 | MWh/a |")
NOPAIR = source(3, "| Heizöl | 4 | MWh/a |")
TARGET = {"scenario": "target", "scenario_raw": "Zielszenario",
          "scenario_quote": "Zielszenario", "scenario_source": ["table", 1],
          "year": 2045, "year_raw": "2045", "year_quote": "2045",
          "year_source": ["table", 1]}


def test_a_passage_already_asked_for_values_is_not_asked_again(monkeypatch):
    """The frame still sees every planned passage, so the pairs are the
    stored ones; only what was never asked is read, the rest of the document
    included, and only that is counted as harvested."""
    shown_to_frame = []

    def find_frame(sources, *a, start=None, **k):
        shown_to_frame.extend(s.owner_id for s in sources)
        return list(start or ()), "complete", []

    def plan(document_id, filename, frame=None, frame_index=0, only=()):
        report = DocumentReport(document_id=document_id)
        items = [WorkItem(document_id, None, s) for s in (READ, UNREAD)]
        report.owners_harvested = len(items)
        return "plan", items, report, SPEC

    asked_to_skip = []

    def rest(document_id, exclude, start=None):
        asked_to_skip.append(set(exclude))
        return [s for s in (READ, UNREAD, NOPAIR)
                if (s.owner_kind, s.owner_id) not in exclude]

    monkeypatch.setattr(runner, "find_frame", find_frame)
    with ThreadPoolExecutor(max_workers=2) as pool:
        got = runner.plan_batches(
            7, "plan.pdf", plan=plan, plan_pool=pool,
            ask_frame=lambda *a, **k: {},
            frame_axes=fields.frame_slots(SPEC, ("scenario", "year")),
            more_sources=None, year_states={}, anchor_texts={},
            stored_pairs={0: TARGET}, rest_of_document=rest,
            already_read=frozenset({("table", 1)}))
    assert sorted(shown_to_frame) == [1, 2]
    read = sorted(i.source.owner_id for b in got.batches for i in b.items)
    assert read == [2, 3]
    assert ("table", 1) in asked_to_skip[0]
    assert got.report.owners_harvested == 2
