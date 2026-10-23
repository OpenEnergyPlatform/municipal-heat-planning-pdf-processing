"""Requests are sent oldest document first and a withdrawn one never; a
sweep asks several windows at once and folds them in their order; the map of
places takes a place only on a quote from its own passage, is used only when
complete, splits a reply that does not fit, and is read again from disk.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import dataclasses
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import fields, places, runner, scheduler
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.throttle import AdaptiveLimit

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
CARRIER = {slot.name: slot for slot in fields.axis_slots(
    SPEC.by_uri["energy_consumption"])}["carrier"]


def section(n, text, at=None):
    return Source("section", n, text, {"document_id": 7,
                                       "section_number": n if at is None
                                       else at})


# -- the queue -----------------------------------------------------------------

def test_the_older_document_is_sent_first_and_a_withdrawn_request_never():
    limit = AdaptiveLimit(start=1, minimum=1, maximum=1)
    queue = scheduler.Scheduler(limit)
    queue.rank(1)                       # document 1 asked first
    queue.rank(2)
    hold = threading.Event()
    sent = []
    blocker = queue.submit(lambda: hold.wait(2), document=9)
    while limit.in_flight == 0:
        time.sleep(0.01)
    ticket = scheduler.Ticket()
    later = queue.submit(lambda: sent.append("doc 2"), document=2)
    gone = queue.submit(lambda: sent.append("withdrawn"), document=1,
                        ticket=ticket)
    first = queue.submit(lambda: sent.append("doc 1"), document=1)
    ticket.withdraw()
    hold.set()
    for future in (blocker, later, first):
        future.result(2)
    with pytest.raises(scheduler.Withdrawn):
        gone.result(2)
    assert sent == ["doc 1", "doc 2"]


# -- windows ahead ---------------------------------------------------------------

WINDOWS = [[section(n, text)] for n, text in (
    (2, "Die Heizungen laufen mit Erdgas."),
    (3, "Alle Gebäude heizen mit Heizöl."),
    (4, "Ein Absatz ohne Träger."))]


def answer(rows, raw, quote):
    return {"fields": {"carrier": {"answers": {
        r: {"value": raw, "value_raw": raw, "quote": quote} for r in rows}}}}


def sweep(monkeypatch, width, slow_first):
    def ask(shown, todo, slots, corrections, document_id, usage, owner_of,
            bases=None):
        owners = {s.owner_id for s in shown}
        if 2 in owners:
            if slow_first:
                time.sleep(0.2)          # answers last, folds first
            return answer(["R1"], "Erdgas", "Die Heizungen laufen mit Erdgas.")
        if 3 in owners:
            return answer(["R1", "R2"], "Heizöl",
                          "Alle Gebäude heizen mit Heizöl.")
        return {"fields": {"carrier": {}}}

    own = section(1, "| Wohngebäude | 120 | MWh/a |")
    batch = SimpleNamespace(document_id=7, bases=(), parameter=None,
                            items=[SimpleNamespace(source=own)],
                            sources=[own])
    rows = [Row(label=label, item_index=0, claim={"value": 120})
            for label in ("R1", "R2")]
    sweeper = runner.make_sweeper(ask)
    sweeping = runner.Sweeping(sweeper, runner.Scope([(batch, rows)]),
                               [CARRIER], "", seen=set(), held={},
                               kind="document")
    sweeping.state["stage"] = "rest"
    monkeypatch.setattr(runner.Sweeping, "width", lambda self: width)
    combed = sweeping.run(iter(WINDOWS))
    return rows, sweeping, combed


def test_an_earlier_window_s_reading_stands_whatever_answers_first(
        monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", ThreadPoolExecutor(4))
    rows, sweeping, combed = sweep(monkeypatch, width=3, slow_first=True)
    assert combed
    assert rows[0].claim["carrier_raw"] == "Erdgas"
    assert rows[1].claim["carrier_raw"] == "Heizöl"
    assert sweeping.totals["withdrawn"] == 1      # the window behind


def test_one_window_at_a_time_reads_the_same(monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", None)
    rows, sweeping, combed = sweep(monkeypatch, width=1, slow_first=False)
    assert [r.claim["carrier_raw"] for r in rows] == ["Erdgas", "Heizöl"]
    assert sweeping.totals["withdrawn"] == 0


# -- the map of places -------------------------------------------------------------

AXES = {"carrier": "Welcher Energieträger?", "year": "Für welches Jahr?"}
PARAMETERS = {"energy_consumption": "Energieverbrauch"}
DOC = [section(n, text) for n, text in (
    (1, "Einleitung des Plans ohne Zahlen."),
    (2, "Tabelle 3: Endenergie 2022 nach Energieträgern"),
    (3, "| Erdgas | 120 | MWh/a |"),
    (4, "Ausblick auf das Jahr 2045."))]


def hit(passage, axes, quote, parameters=()):
    return {"passage": passage, "axes": list(axes), "quote": quote,
            "parameters": list(parameters)}


def test_a_place_is_taken_on_a_quote_from_its_own_passage_only():
    window = DOC[1:3]
    taken, dropped = places.read_hits({"hits": [
        hit("P1", ["carrier", "year"], "Endenergie 2022 nach Energieträgern"),
        hit("P2", ["carrier"], "Endenergie 2022 nach Energieträgern"),
        hit("P2", ["carrier"], "Erdgas"),
        hit("P9", ["year"], "| Erdgas | 120 | MWh/a |")]},
        window, AXES, PARAMETERS)
    assert [(s.owner_id, axes) for s, axes, _p, _q in taken] == \
        [(2, ["carrier", "year"])]
    assert dropped == 3


ONE_SECTION = [section(s.owner_id, s.text, at=1) for s in DOC]


def make_places(reply_of, store=None, key="k", doc=ONE_SECTION):
    calls = []

    def ask(window, document_id):
        calls.append(len(window))
        return reply_of(window)
    found = places.Places(ask, lambda _d: list(doc), lambda w: len(w) <= 4,
                          AXES, PARAMETERS, key, store=store)
    return found, calls


def full_map(window):
    if len(window) > 1:
        return places.CUT                         # never fits but alone
    source = window[0]
    if source.owner_id == 2:
        return {"hits": [hit("P1", ["carrier", "year"], source.text)]}
    if source.owner_id == 4:
        return {"hits": [hit("P1", ["year"], source.text)]}
    return {"hits": []}


def test_a_reply_that_does_not_fit_is_split_until_it_does(tmp_path):
    found, calls = make_places(full_map)
    assert [s.owner_id for s in found(7, ["year"])] == [2, 4]
    assert [s.owner_id for s in found(7, ["carrier"])] == [2]
    assert calls == [4, 2, 1, 1, 2, 1, 1]


def test_a_window_ends_where_its_section_ends():
    found, calls = make_places(full_map, doc=DOC)
    assert [s.owner_id for s in found(7, ["year"])] == [2, 4]
    assert calls == [1, 1, 1, 1]                  # four sections, fits all
    two = [section(1, "a", at=1), section(2, "b", at=1), section(3, "c", at=2)]
    assert [[s.owner_id for s in w] for w in
            places.windows_of(two, lambda w: True)] == [[1, 2], [3]]
    assert [[s.owner_id for s in w] for w in
            places.windows_of(two, lambda w: len(w) < 2)] == [[1], [2], [3]]


def test_the_map_asks_for_the_unit_when_the_spec_asks_for_one():
    axes, _named = places.questions(SPEC)
    assert fields.UNIT in axes and "carrier" in axes
    silent = dataclasses.replace(SPEC, unit_question=None)
    assert fields.UNIT not in places.questions(silent)[0]


def test_a_map_with_an_unread_window_is_not_used():
    def broken(window):
        reply = full_map(window)
        return None if window[0].owner_id == 4 and len(window) == 1 else reply
    found, _calls = make_places(broken)
    assert found(7, ["year"]) is None
    assert found(7, ["sector"]) is None           # an axis it never knew


def test_a_kept_map_is_read_again_and_a_new_question_asks_again(tmp_path):
    first, calls = make_places(full_map, store=tmp_path)
    first(7, ["year"])
    again, calls_again = make_places(full_map, store=tmp_path)
    assert [s.owner_id for s in again(7, ["year"])] == [2, 4]
    assert calls_again == []
    moved, calls_moved = make_places(full_map, store=tmp_path, key="other")
    moved(7, ["year"])
    assert calls_moved


def test_the_places_nearest_the_rows_come_first():
    pool = [section(n, "x") for n in (1, 5, 9, 12)]
    assert [s.owner_id for s in places.nearest_first(pool, [10])] == \
        [9, 12, 5, 1]


def test_a_complete_map_without_a_place_ends_combed_not_exhausted(
        monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", None)
    asked = []
    own = section(3, "| Erdgas | 120 | MWh/a |")
    batch = SimpleNamespace(document_id=7, bases=(), parameter=None,
                            items=[SimpleNamespace(source=own)],
                            sources=[own])
    rows = [Row(label="R1", item_index=0, claim={"value": 120})]
    sweeper = runner.make_sweeper(lambda *a, **k: asked.append(a) or None,
                                  places=lambda _d, _axes: [])
    sweeping = runner.Sweeping(sweeper, runner.Scope([(batch, rows)]),
                               [CARRIER], "", seen=set(), held={},
                               kind="document")
    combed = sweeping.search()
    assert combed and not asked
    sweeping.close(combed)
    assert rows[0].claim.get("carrier_state") != fields.EXHAUSTED
