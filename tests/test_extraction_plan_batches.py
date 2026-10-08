"""The planning half of a document, lifted out of `runner.main` to be shared.

`plan_batches` is what the harvest does for a document before it asks a
value: the plan, the frame, one plan per pair, the batches. The pass that
appends a parameter to a stored harvest calls the same function with the one
parameter it is for and with the pairs the stored rows already carry, so what
is held here is both halves of that: the harvest's own call plans what it
planned, and the pass's call searches for the named parameter alone and keeps
every pair under the index it was stored with.

No model, no index: the plan, the frame request and the passages are stubs.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import (DocumentReport, Source, WorkItem,
                                         pair_in_text)
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
RAW = json.loads((PROFILES / "kwp" / "extraction_spec.json")
                 .read_text(encoding="utf-8"))
SPEC = load_spec(RAW)
FRAME = fields.frame_slots(SPEC, ("scenario", "year"))
BASE = {"base": {"scenario": "status_quo"}}


def _source(owner, text):
    return Source("table", owner, text, {"document_id": 7, "page": owner})


# Three passages: one prints the pair of 2045, one the pair of 2020, one
# prints no pair at all.
P2045 = _source(1, "Zielszenario 2045 | Erdgas | 12 | MWh/a |")
P2020 = _source(2, "Status quo 2020 | Erdgas | 17 | MWh/a |")
NONE = _source(3, "Allgemeine Hinweise ohne Zahlen")


def _pair(scenario, raw, year):
    return {"scenario": scenario, "scenario_raw": raw,
            "scenario_quote": raw, "scenario_source": ["table", 1],
            "year": year, "year_raw": str(year), "year_quote": str(year),
            "year_source": ["table", 1]}


T2045 = _pair("target", "Zielszenario", 2045)
S2020 = _pair("status_quo", "Status quo", 2020)


class Planner:
    """A `plan` that records how it was called and plans the same three
    passages for every call, whatever it was asked for."""

    def __init__(self, spec=SPEC):
        self.calls = []
        self.spec = spec
        self.lock = threading.Lock()

    def __call__(self, document_id, filename, frame=None, frame_index=0,
                 only=()):
        with self.lock:
            self.calls.append({"frame": frame, "frame_index": frame_index,
                               "only": tuple(only)})
        report = DocumentReport(document_id=document_id)
        report.sources_of = {"energy_consumption": {("table", 1)}}
        items = [WorkItem(document_id, None, source)
                 for source in (P2045, P2020, NONE)]
        report.owners_harvested = len(items)
        return Path(filename).stem, items, report, self.spec


@pytest.fixture
def pool():
    executor = ThreadPoolExecutor(max_workers=2)
    yield executor
    executor.shutdown()


def _plan(pool, planner, *, found=(), stored=None, only=(), ask=True,
          anchor_texts=None, monkeypatch=None, states=BASE):
    """`plan_batches` over the stub planner and a frame that finds `found`
    in addition to what it is seeded with."""
    seen = {}

    def find_frame(sources, slots, document_id, ask_frame, more_sources=None,
                   probes=None, start=None):
        seen["start"] = start
        seen["sources"] = list(sources)
        return list(start or ()) + [dict(p) for p in found], "complete", []

    monkeypatch.setattr(runner, "find_frame", find_frame)
    got = runner.plan_batches(
        7, "plan.pdf", plan=planner, plan_pool=pool,
        ask_frame=(lambda *a, **k: {}) if ask else None, frame_axes=FRAME,
        more_sources=None, year_states=states,
        anchor_texts=anchor_texts if anchor_texts is not None else {},
        only=only, stored_pairs=stored)
    return got, seen


# ---------------------------------------------------------------------------
# The harvest's own call
# ---------------------------------------------------------------------------

def test_the_harvests_call_plans_every_parameter_and_numbers_pairs_from_zero(
        pool, monkeypatch):
    """No `only`, no stored pairs: the document plan and one plan per pair,
    every call asking for everything, pairs under 0 and 1, and every batch
    carrying the document's own spec."""
    planner = Planner()
    got, seen = _plan(pool, planner, found=[T2045, S2020],
                      monkeypatch=monkeypatch)
    assert seen["start"] is None, "nothing seeded"
    assert got.indices == [0, 1] and got.pairs == [T2045, S2020]
    assert [c["only"] for c in planner.calls] == [()] * 3
    assert sorted(c["frame_index"] for c in planner.calls) == [0, 0, 1]
    assert got.batches and all(b.spec is SPEC for b in got.batches)
    framed = {b.frame_index: b.frame for b in got.batches if b.frame}
    assert framed == {0: T2045, 1: S2020}
    assert [(b.frame_index, [i.source.owner_id for i in b.items])
            for b in got.batches if b.frame] == [(0, [1]), (1, [2])]
    rest = [b for b in got.batches if not b.frame]
    assert [i.source.owner_id for b in rest for i in b.items] == [3]
    assert got.failed == 0 and got.name == "plan"


def test_every_batch_carries_the_years_of_the_states_the_profile_names(
        pool, monkeypatch):
    """The plan's own years and, where the profile names a target, the
    target's: on every batch of the document, framed or not, each entry with
    the state it dates."""
    both = dict(BASE, target={"scenario": "target"})
    got, _seen = _plan(pool, Planner(), found=[T2045, S2020],
                       monkeypatch=monkeypatch, states=both)
    assert got.batches
    for batch in got.batches:
        assert [(b["state"], b["year"], b["index"]) for b in batch.bases] == [
            ("base", 2020, 1), ("target", 2045, 0)]
    only_base, _seen = _plan(pool, Planner(), found=[T2045, S2020],
                             monkeypatch=monkeypatch)
    for batch in only_base.batches:
        assert [(b["state"], b["year"]) for b in batch.bases] == [
            ("base", 2020)], "a profile that names no target has none"


def test_a_profile_without_a_frame_plans_once_and_has_no_pairs(pool,
                                                                monkeypatch):
    planner = Planner()
    got, seen = _plan(pool, planner, ask=False, monkeypatch=monkeypatch)
    assert seen == {}, "no frame was asked"
    assert got.pairs == [] and got.indices == []
    assert len(planner.calls) == 1 and planner.calls[0]["frame"] is None
    assert all(b.bases == () for b in got.batches)


def test_a_frame_that_raises_is_counted_and_leaves_no_pairs(pool,
                                                            monkeypatch):
    def find_frame(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "find_frame", find_frame)
    got = runner.plan_batches(
        7, "plan.pdf", plan=Planner(), plan_pool=pool,
        ask_frame=lambda *a, **k: {}, frame_axes=FRAME, more_sources=None,
        year_states=BASE, anchor_texts={})
    assert got.failed == 1 and got.pairs == []


def test_a_pair_whose_plan_raises_is_counted(pool, monkeypatch):
    class Failing(Planner):
        def __call__(self, document_id, filename, frame=None, frame_index=0,
                     only=()):
            if frame is not None and frame_index == 1:
                raise RuntimeError("no passages")
            return super().__call__(document_id, filename, frame,
                                    frame_index, only)

    got, _seen = _plan(pool, Failing(), found=[T2045, S2020],
                       monkeypatch=monkeypatch)
    assert got.failed == 1
    assert {b.frame_index: [i.source.owner_id for i in b.items]
            for b in got.batches if b.frame} == {0: [1], 1: [2]}, (
        "the pair whose own search failed is read over the passages the "
        "document's search kept and that print it")


# ---------------------------------------------------------------------------
# The search is for the named parameter alone
# ---------------------------------------------------------------------------

def test_the_search_is_for_the_new_parameter_alone(pool, monkeypatch):
    """Every call that searches carries `only`: the document plan and EVERY
    pair plan. A call without it searches for every parameter again, which is
    the cost the pass is there to spare."""
    planner = Planner()
    got, _seen = _plan(pool, planner, found=[T2045, S2020],
                       only=("heat_load",), monkeypatch=monkeypatch)
    assert len(planner.calls) == 3, "the document and each of two pairs"
    assert [c["only"] for c in planner.calls] == [("heat_load",)] * 3
    assert got.batches


def test_the_batches_offer_the_named_parameter_and_no_other(pool,
                                                            monkeypatch):
    """The spec the batch carries is what every request is built from, so a
    batch of the pass offers the parameter it is for, its units, and no
    parameter whose row it must not write."""
    got, _seen = _plan(pool, Planner(), found=[T2045], only=("heat_load",),
                       monkeypatch=monkeypatch)
    for batch in got.batches:
        assert [p.uri for p in batch.spec.parameters] == ["heat_load"]
        assert list(batch.spec.by_uri) == ["heat_load"]
        assert fields.unit_slot(batch.spec).options == tuple(
            fields.unit_slot(SPEC, SPEC.by_uri["heat_load"]).options)
    assert got.doc_spec is SPEC, "the document's own spec is handed back"


def test_the_rows_request_names_only_the_new_parameter(pool, monkeypatch):
    """The quantities of the request body are the batch's own spec's. Violated
    by construction: the unnarrowed batch lists every parameter."""
    from docpipe.extraction.pipeline import Batch
    got, _seen = _plan(pool, Planner(), found=[T2045], only=("heat_load",),
                       monkeypatch=monkeypatch)
    batch = got.batches[0]
    body = runner._batch_payload(batch, [], runner.spec_of(batch, SPEC))
    assert [q["uri"] for q in body["quantities"]] == ["heat_load"]
    whole = Batch(7, None, list(batch.items))
    assert [q["uri"] for q in runner._batch_payload(whole, [], SPEC)[
        "quantities"]] == [p.uri for p in SPEC.parameters]
    # A follow-up and a half of a split request keep the narrowed spec.
    from docpipe.extraction.pipeline import Sweep, follow_up
    sweep = Sweep(set(), 1)
    extra = follow_up(batch, {"status": "partial",
                              "need_more": ["Wo steht die Heizlast?" * 2]},
                      sweep, lambda doc, queries, exclude: [NONE])
    assert extra and all(e.spec is batch.spec for e in extra)
    from dataclasses import replace
    assert replace(batch, items=batch.items[:1]).spec is batch.spec


def test_narrow_spec_keeps_the_spec_when_nothing_is_named():
    assert runner.narrow_spec(SPEC, ()) is SPEC
    assert runner.narrow_spec(SPEC, None) is SPEC
    one = runner.narrow_spec(SPEC, ["emission"])
    assert [p.uri for p in one.parameters] == ["emission"]
    assert one.parameter_question == SPEC.parameter_question
    assert one.unit_question == SPEC.unit_question
    assert [p.uri for p in SPEC.parameters][:2] == ["energy_consumption",
                                                    "emission"], (
        "the spec it was cut from is left as it was")
    both = runner.narrow_spec(SPEC, ["emission", "heat_load"])
    assert [p.uri for p in both.parameters] == ["emission", "heat_load"]


# ---------------------------------------------------------------------------
# The pairs a stored harvest carries
# ---------------------------------------------------------------------------

def test_a_stored_pair_keeps_its_index_and_a_new_pair_takes_the_next_free_one(
        pool, monkeypatch):
    """Stored pairs 0 and 3 (a gap: no row carries 1 or 2) are seeded; the
    frame finds one more. It stands under 4, and the stored pairs stand
    where they stood, so ["frame", i] means the same pair across the file."""
    stored = {0: S2020, 3: T2045}
    new = _pair("trend", "Trendszenario", 2030)
    planner = Planner()
    texts = {("plan", 0): ["a"], ("plan", 3): ["b"], ("plan", 4): ["c"]}
    got, seen = _plan(pool, planner, found=[new], stored=stored,
                      only=("heat_load",), anchor_texts=texts,
                      monkeypatch=monkeypatch)
    assert seen["start"] == [S2020, T2045], "stored pairs, in index order"
    assert got.pairs == [S2020, T2045, new] and got.indices == [0, 3, 4]
    assert sorted(c["frame_index"] for c in planner.calls
                  if c["frame"] is not None) == [0, 3, 4], (
        "each pair is planned, and its sentence recorded, under its index")
    framed = {b.frame_index: (b.frame["year"], b.anchors)
              for b in got.batches if b.frame}
    assert framed == {0: (2020, ("a",)), 3: (2045, ("b",))}, (
        "the batches carry the index, and the anchors are looked up by it; "
        "the new pair prints in no passage and has no batch")


def test_the_pairs_handed_to_the_batches_keep_their_gaps_and_name_no_passage(
        pool, monkeypatch):
    """A pair no row carries stands as None under its index. It must not be
    handed to `pair_batches`, which would have it name every passage
    (`names_pair` skips a coordinate the pair does not have), and a row filed
    under another pair must not land on it either."""
    from docpipe.extraction.pipeline import names_pair, pair_of_source
    got, _seen = _plan(pool, Planner(), stored={0: S2020, 3: T2045},
                       only=("heat_load",), monkeypatch=monkeypatch)
    framed = [b for b in got.batches if b.frame]
    assert framed and all(len(b.pairs) == 4 for b in framed)
    assert framed[0].pairs == (S2020, None, None, T2045)
    assert not [b for b in got.batches if b.frame is None and b.frame_index]
    # The reason, shown: a gap would claim every passage.
    assert names_pair(NONE, None, FRAME) is True
    assert pair_of_source(NONE, (None, None), FRAME) is None
    assert pair_of_source(P2045, framed[0].pairs, FRAME) == (T2045, 3)
    assert not pair_in_text(S2020, FRAME, NONE.text)


def test_a_gap_is_no_pair_for_a_request_that_is_for_a_pair_of_its_own(
        pool, monkeypatch):
    """`pair_of_source` leaves out the pair the request is for (`taken`), and a
    gap is not that pair. Without the guard on a pair that is no dict the gaps
    name every passage, the one pair the passage does print is one of three,
    and the claim is refused as another pair's. Violating: the same call with
    the guard taken out answers None, and the row is an orphan."""
    from docpipe.extraction.pipeline import pair_of_source, rows_from_reply
    got, _seen = _plan(pool, Planner(), stored={0: S2020, 3: T2045},
                       only=("heat_load",), monkeypatch=monkeypatch)
    batch = next(b for b in got.batches if b.frame is S2020)
    assert batch.pairs == (S2020, None, None, T2045)
    assert pair_of_source(P2045, batch.pairs, FRAME,
                          taken=batch.frame) == (T2045, 3)
    batch.items = [WorkItem(7, None, P2045)]
    claim = {"source": "Q1", "value": 12, "unit": "kW",
             "quote": "| Erdgas | 12 | MWh/a |"}
    rows, orphans = rows_from_reply(batch, {"tuples": [claim]}, FRAME)
    assert orphans == []
    assert [(r.pair["year"], r.pair_index) for r in rows] == [(2045, 3)]


def test_a_pair_is_read_over_the_passages_its_own_search_found(pool,
                                                               monkeypatch):
    """The document's search and each pair's search keep passages of their
    own. A passage only the search of a pair found, and that prints the pair,
    is read under it, and what that search found for a parameter is that
    parameter's passage in the document's report (`sources_of`, which says
    whether a request that never came back held one of its passages).
    Violating: pair plans whose result is dropped read the pair over the
    document's passages alone and leave the report without them."""
    own = _source(4, "Zielszenario 2045 | Fernwaerme | 9 | MWh/a |")

    class Finding(Planner):
        def __call__(self, document_id, filename, frame=None, frame_index=0,
                     only=()):
            name, items, report, spec = super().__call__(
                document_id, filename, frame, frame_index, only)
            if frame is not None and frame_index == 0:
                items = items + [WorkItem(document_id, None, own)]
                report.sources_of = {"heat_load": {("table", 4)}}
            return name, items, report, spec

    got, _seen = _plan(pool, Finding(), found=[T2045, S2020],
                       only=("heat_load",), monkeypatch=monkeypatch)
    framed = {b.frame_index: [i.source.owner_id for i in b.items]
              for b in got.batches if b.frame}
    assert framed == {0: [1, 4], 1: [2]}, (
        "the passage only the search of the first pair found is read under "
        "it, and the pair whose search found nothing more is read as before")
    assert got.report.sources_of["heat_load"] == {("table", 4)}
    assert got.report.sources_of["energy_consumption"] == {("table", 1)}


def test_a_row_filed_under_another_pair_carries_that_pairs_stored_index(
        pool, monkeypatch):
    """A claim whose own quote prints another pair of the document is filed
    under it, and the index it is filed under is the one the pair stands
    under in the file: 3, not its position in the compact list."""
    from docpipe.extraction.pipeline import rows_from_reply
    got, _seen = _plan(pool, Planner(), stored={0: S2020, 3: T2045},
                       only=("heat_load",), monkeypatch=monkeypatch)
    batch = next(b for b in got.batches if b.frame is S2020)
    batch.items = [WorkItem(7, None, _source(8, "Allgemeiner Absatz"))]
    claim = {"source": "Q1", "value": 12, "unit": "kW",
             "quote": "Zielszenario 2045 | Heizlast | 12 | kW |"}
    rows, orphans = rows_from_reply(batch, {"tuples": [claim]}, FRAME)
    assert orphans == []
    assert [(r.pair["year"], r.pair_index) for r in rows] == [(2045, 3)]


def test_the_base_years_are_named_by_the_index_a_pair_stands_under(
        pool, monkeypatch):
    """A base year carries the index of the pair it was read from: the pair
    stored at 3 is index 3, not position 1."""
    got, _seen = _plan(pool, Planner(), stored={0: T2045, 3: S2020},
                       only=("heat_load",), monkeypatch=monkeypatch)
    bases = got.batches[0].bases
    assert [(b["year"], b["index"]) for b in bases] == [(2020, 3)]
    assert all(b.bases == bases for b in got.batches)


def test_a_pair_that_equals_a_stored_one_is_not_added_a_second_time():
    """The seed is what `find_frame` starts from, and a pair the model names
    again is one pair. Violated by construction: a seed that did not count
    would have the stored pair twice."""
    shown = [P2045]
    asked = []

    def ask(sources, slots, document_id, pairs, usage, recheck, corrections):
        asked.append(list(pairs))
        return {"pairs": [{"scenario": "target",
                           "scenario_raw": "Zielszenario",
                           "scenario_quote": "Zielszenario",
                           "scenario_source": "Q1", "year": 2045,
                           "year_raw": "2045", "year_quote": "2045",
                           "year_source": "Q1"}], "status": "complete"}

    pairs, status, _missed = runner.find_frame(
        shown, FRAME, 7, ask, start=[T2045])
    assert [p["year"] for p in pairs] == [2045] and pairs[0] is T2045
    assert asked[0] == [T2045], "the model is shown the stored pair as known"
    unseeded, _s, _m = runner.find_frame(shown, FRAME, 7, ask)
    assert [p["year"] for p in unseeded] == [2045]
    assert unseeded[0] is not T2045


# ---------------------------------------------------------------------------
# What was lifted keeps what it did
# ---------------------------------------------------------------------------

def test_not_happened_names_the_three_ways_a_reading_does_not_happen():
    def report(sentinels=(), harvested=4):
        out = DocumentReport(document_id=7)
        out.owners_harvested = harvested
        out.refusals = [{"parameter": None, "reason": "r", "owner": ["t", i],
                         "claim": {"_harvest_failed": True, "_why": why}}
                        for i, why in enumerate(sentinels)]
        return out

    assert runner.not_happened(report(), answered=3) is None
    assert runner.not_happened(report(["no_answer", "cut_off"]),
                               answered=3) is None, (
        "a hole with its cause is a result, not a reading that did not happen")
    assert runner.not_happened(report(["unreachable"] * 3),
                               answered=3) == ("unreachable", 3, 4)
    assert runner.not_happened(report(["unreachable"] * 2),
                               answered=3) is None, "half is the line"
    assert runner.not_happened(report(), answered=0) == ("no_reply", 4, 4)
    assert runner.not_happened(report(), answered=None) is None
    assert runner.not_happened(report(["unserved", "unserved"]),
                               answered=3) == ("unserved", 2, 2)
    assert runner.not_happened(report(), answered=3, lost=1) == (
        "unserved", 1, 1)
    assert runner.not_happened(report(harvested=0), answered=0) is None, (
        "no passage planned, nothing to have read")


def test_a_folded_answer_is_traced_and_checked_as_the_harvest_checks(
        monkeypatch):
    """`fold_answers` is the harvest's own fold: the batch's spec decides
    which parameter a claim may name."""
    from docpipe.extraction import trace
    from docpipe.extraction.pipeline import Batch
    events = []
    monkeypatch.setattr(trace, "event",
                        lambda kind, doc=None, /, **kw: events.append(
                            (kind, kw.get("parameter"))))
    source = _source(1, "| Heizlast | 12 | kW |")
    batch = Batch(7, None, [WorkItem(7, None, source)])
    batch.spec = runner.narrow_spec(SPEC, ["heat_load"])
    claims = [{"source": "Q1", "parameter": "heat_load", "value": 12,
               "unit": "kW", "quote": "| Heizlast | 12 | kW |"},
              {"source": "Q1", "parameter": "emission", "value": 12,
               "unit": "kW", "quote": "| Heizlast | 12 | kW |"}]
    report = DocumentReport(document_id=7)
    runner.fold_answers([(batch, {"tuples": claims})], report, locate=None,
                        spec=SPEC)
    assert [r["parameter"] for r in report.tuples] == ["heat_load"]
    assert [r["parameter"] for r in report.refusals] == ["emission"]
    assert report.refusals[0]["reason"] == (
        "claim names no parameter of the spec"), (
        "a parameter the batch did not offer cannot be written")
    assert ("coord", "heat_load") in events
    assert ("refusal", "emission") in events


def test_the_next_batch_is_told_what_survived_checking():
    from docpipe.extraction.pipeline import Batch
    source = _source(1, "| Heizlast | 12 | kW |")
    batch = Batch(7, None, [WorkItem(7, None, source)])
    reply = {"tuples": [
        {"source": "Q1", "parameter": "heat_load", "value": 12, "unit": "kW",
         "quote": "| Heizlast | 12 | kW |"},
        {"source": "Q1", "parameter": "heat_load", "value": 99, "unit": "kW",
         "quote": "| Heizlast | 99 | kW |"},
        {"source": "Q1", "parameter": "nobody", "value": 1, "unit": "kW",
         "quote": "| Heizlast | 12 | kW |"}]}
    rows = runner.accepted_rows(batch, reply, SPEC)
    assert [r["value"] for r in rows] == [12.0], (
        "the claim whose quote stands in no passage is not a hint, and a "
        "parameter the spec does not know is none either")
