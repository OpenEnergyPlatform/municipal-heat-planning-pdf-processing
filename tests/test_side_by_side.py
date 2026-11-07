"""Every place stays taken to the end (owner decision 2026-11-07: the values
of a passage side by side, a passage combed the moment it is read, a probe's
places counting requests), each promise with a case that breaks it by
construction.

1. With a pool, the conversations of a passage's values run side by side:
   two values of one passage are asked at the same time.
2. Each value's conversation keeps its order, one coordinate a message in
   the order of the groups, AND the reading comes to the same rows, counts
   and messages of its rounds as without a pool.
3. A value read as no value of its parameter is asked for once more only
   when every value of its passage is done, in the order of the values.
4. A passage is combed while the rest of the plan is still read.
5. A table's job is done before the jobs of its values begin.
6. A value shown every name read in the plan waits for the whole plan: a
   name read in a passage added later is in its list.
7. A job not begun when the combing is taken back never runs.
8. A probe's places count requests with the model: no more than the limit
   are open at once, however many conversations wait.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import (combing, fields, reading, runner, scheduler,
                                survey)
from docpipe.extraction.pipeline import Batch, Source, WorkItem
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
SCENARIOS = load_spec(json.loads(
    (PROFILES / "scenarios" / "extraction_spec.json").read_text(
        encoding="utf-8")))
KWP = load_spec(json.loads(
    (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
YEAR = SCENARIOS.by_uri["scenario_year"]
ENERGY = KWP.by_uri["energy_consumption"]
PUBLISHED = "Published in the year 2018 by BNEF."
LATER = "Revised in the year 2019 by BNEF."
RUNS = "The NEO scenario runs to the year 2050."
QUOTES = {"2018": PUBLISHED, "2019": LATER, "2050": RUNS}
YEARS = Source("section", 4, "\n".join((PUBLISHED, LATER, RUNS)),
               {"document_id": 7, "section_title": "Studies"})


def answered(thread, reply):
    """What the run keeps of an answer: the conversation goes on after it."""
    if thread is not None and isinstance(reply, dict):
        thread.messages = [*thread.messages, {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


def read_years(kinds, again=(), pool=None, meet=None,
               named=("2018", "2019"), slow=()):
    """The reading of the scenario years of YEARS: the rounds name *named*,
    *kinds* answers the kind of each year, a year of *slow* a moment later,
    the question asked again names *again* in turn. With *meet*, the first
    message of each value waits there for the other's. (the Reads, the
    events in their order, the follow-ups of the rounds)."""
    rounds = iter([{"value": year, "quote": QUOTES[year]} for year in named]
                  + [{"value": None}])
    again = list(again)
    events, follows = [], []
    lock = threading.Lock()

    def ask_values(src, parameter, context, read, thread, follow=None,
                   drawn=False):
        with lock:
            follows.append(follow)
        if follow and reading.WRONG in follow:
            with lock:
                events.append(("wrong", follow[reading.WRONG]["value"]))
            return answered(thread, again.pop(0) if again
                            else {"value": None})
        return answered(thread, next(rounds))

    def ask_text(src, parameter, group, slots, row, context, thread,
                 follow=None):
        name, year = slots[0].name, row.claim["value"]
        if follow is None:
            with lock:
                events.append(("ask", year, name))
            if meet is not None and name == "year_kind":
                try:
                    meet.wait()
                except threading.BrokenBarrierError:
                    with lock:
                        events.append(("alone", year))
        if name == "year_kind":
            if year in slow:
                time.sleep(0.3)
            return answered(thread, {"year_kind": {
                "value": kinds[year], "value_raw": QUOTES[year].split(" in ")[0],
                "quote": QUOTES[year]}})
        return answered(thread, {"scenario": {"value": "NEO",
                                              "quote": RUNS}})

    reader = reading.Reader(SCENARIOS, ask_values, ask_text,
                            runner.frame_slots_of(SCENARIOS), pool=pool)
    found = survey.Found(True, {("section", 4): survey.Answer(
        ("section", 4), [YEAR.uri], {}, [])}, [])
    reads = reader(7, found, {("section", 4): YEARS})
    return reads, events, follows


def test_the_values_of_a_passage_are_asked_side_by_side():
    with ThreadPoolExecutor(4) as pool:
        _reads, events, _follows = read_years(
            {"2018": "scenario year", "2019": "scenario year"}, pool=pool,
            meet=threading.Barrier(2, timeout=5))
    assert ("ask", "2018", "year_kind") in events
    assert ("ask", "2019", "year_kind") in events
    # One after another, the first value would wait for the second alone.
    assert not [one for one in events if one[0] == "alone"]


def test_each_value_keeps_its_order_and_the_reading_is_the_same_as_alone():
    kinds = {"2018": "scenario year", "2019": "scenario year"}
    alone, alone_events, alone_follows = read_years(kinds)
    with ThreadPoolExecutor(4) as pool:
        side, side_events, side_follows = read_years(kinds, pool=pool)
    groups = reading.groups_of(SCENARIOS, reading.slots_of(SCENARIOS, YEAR))
    order = [slot.name for group, slots in groups
             for slot in reading.in_group_order(group, slots)]
    for year in ("2018", "2019"):
        asked = [one[2] for one in side_events
                 if one[0] == "ask" and one[1] == year]
        assert asked == [name for name in order if name in asked]
        assert asked == [one[2] for one in alone_events
                         if one[0] == "ask" and one[1] == year]
    assert json.dumps([read.claims for read in side], sort_keys=True,
                      default=str) == json.dumps(
        [read.claims for read in alone], sort_keys=True, default=str)
    assert [(r.asked, r.corrected, r.failed) for r in side] \
        == [(r.asked, r.corrected, r.failed) for r in alone]
    assert side_follows == alone_follows


def test_a_value_read_wrongly_is_asked_again_after_every_value_in_order():
    # 2018 and 2050 are read wrongly at once; 2019 answers its kind late and
    # only then is asked its scenario.
    with ThreadPoolExecutor(4) as pool:
        _reads, events, _follows = read_years(
            {"2018": "other year", "2019": "scenario year",
             "2050": "other year"},
            pool=pool, named=("2018", "2019", "2050"), slow=("2019",))
    wrong = [i for i, one in enumerate(events) if one[0] == "wrong"]
    last_asked = max(i for i, one in enumerate(events) if one[0] == "ask")
    assert events[last_asked] == ("ask", "2019", "scenario")
    assert wrong and min(wrong) > last_asked
    assert [events[i][1] for i in wrong] == ["2018", "2050"]


class Seen(combing.Comber):
    """A combing that records each conversation instead of asking: its
    kind (a table's or a value's), when it began and ended, and the names it
    was shown. A table's takes *pause* seconds."""

    def __init__(self, spec, pool=None, pause=0.0):
        super().__init__(spec, None, None, None, pool=pool)
        self.pause = pause
        self.calls = []
        self.began = threading.Event()
        self.lock = threading.Lock()

    def comb(self, document_id, parameter, source, slots, claims, passages,
             pairs, budget=None, **given):
        self.began.set()
        start = time.monotonic()
        if given.get("whole_table"):
            time.sleep(self.pause)
        with self.lock:
            self.calls.append({"table": bool(given.get("whole_table")),
                               "start": start, "end": time.monotonic(),
                               "names": list(given.get("names_so_far")
                                             or ()),
                               "value": claims[0].get("value")})
        return combing.Combed(parameter.uri,
                              (source.owner_kind, source.owner_id), 1,
                              len(slots))


def test_a_passage_is_combed_while_the_rest_of_the_plan_is_read():
    first = Source("section", 1, "Der Verbrauch lag bei 120 GWh.",
                   {"document_id": 7})
    second = Source("section", 2, "Der Verbrauch sank auf 90 GWh.",
                    {"document_id": 7})
    rounds = {1: iter([{"value": 120, "quote": first.text},
                       {"value": None}]),
              2: iter([{"value": 90, "quote": second.text},
                       {"value": None}])}
    waited = []

    with ThreadPoolExecutor(4) as pool:
        comber = Seen(KWP, pool=pool)

        def ask_values(src, parameter, context, read, thread, follow=None,
                       drawn=False):
            if src.owner_id == 2 and follow is None and not waited:
                # The second passage is read only once the first is combed.
                waited.append(comber.began.wait(timeout=5))
            return answered(thread, next(rounds[src.owner_id]))

        def ask_text(*args, **kwargs):
            return {}

        reader = reading.Reader(KWP, ask_values, ask_text,
                                runner.frame_slots_of(KWP), pool=pool)
        found = survey.Found(True, {
            ("section", 1): survey.Answer(("section", 1), [ENERGY.uri], {},
                                          []),
            ("section", 2): survey.Answer(("section", 2), [ENERGY.uri], {},
                                          [])}, [])
        passages = {("section", 1): first, ("section", 2): second}
        session = comber.session(7, passages, [], None)
        reads = reader(7, found, passages, on_read=session.add)
        combed = session.finish(reads)
    assert waited == [True]
    assert sorted(call["value"] for call in comber.calls) == [90, 120]
    assert len(combed) == 2


def table_read(spec, parameter, values, open_also):
    """A Read of *parameter* in a table whose frame is open on every one of
    its *values*, each value also open on the coordinates *open_also*."""
    table = Source("table", 9, "Sektor | Verbrauch\n" + "\n".join(
        f"Zeile {i} | {value}" for i, value in enumerate(values)),
                   {"document_id": 7})
    batch = Batch(7, parameter, [WorkItem(7, parameter, table)], spec=spec)
    claims = []
    for i, value in enumerate(values):
        claim = {"value": value, "quote": f"Zeile {i} | {value}",
                 "source": batch.label(0)}
        for name in ("scenario", "year", "period_start", *open_also):
            claim[f"{name}_state"] = fields.UNANSWERED
        claims.append(claim)
    return reading.Read(batch, claims), table


def test_a_table_is_combed_before_its_values():
    read, table = table_read(KWP, ENERGY, [120, 80, 60], ["sector"])
    with ThreadPoolExecutor(4) as pool:
        comber = Seen(KWP, pool=pool, pause=0.2)
        tables, values = comber.plan(read)
        assert len(tables) == 1 and len(values) == 3
        session = comber.session(7, {("table", 9): table}, [], None)
        session.add(read)
        combed = session.finish([read])
    ended = max(call["end"] for call in comber.calls if call["table"])
    begun = [call["start"] for call in comber.calls if not call["table"]]
    assert len(begun) == 3 and min(begun) >= ended
    assert len(combed) == 4


def year_read(source, claim):
    batch = Batch(7, YEAR, [WorkItem(7, YEAR, source)], spec=SCENARIOS)
    claim = dict(claim, source=batch.label(0))
    return reading.Read(batch, [claim])


def test_a_value_shown_every_name_waits_for_the_whole_plan():
    open_scenario = year_read(YEARS, {
        "value": "2050", "quote": RUNS, "year_kind": "scenario year",
        "year_kind_state": fields.READ,
        "scenario_state": fields.UNANSWERED})
    later = Source("section", 5, "Net Zero reaches zero in 2045.",
                   {"document_id": 7})
    named = year_read(later, {
        "value": "2045", "quote": later.text,
        "year_kind": "scenario year", "year_kind_state": fields.READ,
        "scenario": "Net Zero", "scenario_state": fields.READ,
        "scenario_quote": later.text, "scenario_source": ["section", 5]})
    comber = Seen(SCENARIOS)
    jobs = comber.plan(open_scenario)[1]
    assert [comber.shows_names(job) for job in jobs] == [True]
    session = comber.session(7, {("section", 4): YEARS,
                                 ("section", 5): later}, [], None)
    session.add(open_scenario)
    assert comber.calls == []
    session.add(named)
    session.finish([open_scenario, named])
    assert [call["names"] for call in comber.calls
            if call["value"] == "2050"] == [["Net Zero"]]


def test_a_combing_taken_back_runs_no_job_not_begun():
    read, table = table_read(KWP, ENERGY, [120, 80], ["sector"])
    other, _ = table_read(KWP, ENERGY, [60, 40], ["sector"])
    hold = threading.Event()
    with ThreadPoolExecutor(1) as pool:
        comber = Seen(KWP, pool=pool)
        pool.submit(hold.wait, 5)
        session = comber.session(7, {("table", 9): table}, [], None)
        session.add(read)
        session.add(other)
        session.cancel()
        hold.set()
    assert comber.calls == []


def test_a_probe_s_places_count_requests_not_conversations(monkeypatch):
    monkeypatch.setattr(runner, "LIMIT", None)
    monkeypatch.setattr(runner, "SCHEDULER", None)
    runner.start_fixed_limit(3)
    assert runner.LIMIT.resize(9) == 3
    lock = threading.Lock()
    open_now, most = [0], [0]

    def create(**kwargs):
        with lock:
            open_now[0] += 1
            most[0] = max(most[0], open_now[0])
        time.sleep(0.05)
        with lock:
            open_now[0] -= 1
        return "ok"
    model = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    client = scheduler.Scheduled(model, runner.SCHEDULER)
    with ThreadPoolExecutor(9) as pool:
        got = list(pool.map(lambda _: client.chat.completions.create(),
                            range(9)))
    assert got == ["ok"] * 9
    assert most[0] == 3
