"""What a document's batches leave open is searched once, not once per batch.

The promise, as one sentence. For every coordinate of a document the passages
a value came from are asked in its batch's turn as before, AND what is still
open after them is searched ONCE per document and coordinate with the open
rows of all its batches together, AND no passage window of that search is asked
twice for the same coordinate, AND the rest stage of that search may ask
REST_MAX_WINDOWS windows (scaled by SEARCH_SHARE) for every batch that had open
rows of the coordinate and stops where the document does, AND it never sends
more requests than those batches' own windows could, AND a coordinate
whose search read the document to its end is `unstated` while one whose search
ended on its allowance is `exhausted`, AND a row is asked for a coordinate only
when the coordinates that decide it (unit, parameter, each gate axis) are
settled, AND every answer is checked as before against the passages shown and
the row's own, AND what a search that rows wait on raises fails the document
while the same in an axis nothing waits on leaves it `unanswered`, AND a pass
over a stored harvest walks the three stages per batch as before.

Every AND is a test below, and each of them has the case that violates it. Where
the code cannot be made to violate its own promise from outside, the case is
the check run over a record the violation would have left: a check that cannot
fail on such a record proves nothing about a record the code left.

No GPU, no database. The model is a stub that records every request.
"""
import json
import shutil
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner, trace
from docpipe.extraction.pipeline import (Row, Source, WorkItem, group_items,
                                         merge_field, rows_from_reply)
from docpipe.extraction.spec import Spec, load as load_spec

# The fixture of the run over a one-document corpus, for the one test that
# goes through `main`.
from tests.test_extraction_document_lists import (  # noqa: F401
    TEXT, corpus_run)
# The run over the kwp profile, with the real harvester over a stub model,
# for the tests that go through `main`.
from tests.test_extraction_topup_parameter_command import (  # noqa: F401
    frame_column)

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
KWP = load_spec(json.loads(
    (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
CONSUMPTION = KWP.parameters[0]
GATE = {"quantity": None, "scenario": ("target",)}
VALUE0 = 42000


def _slot(name):
    return next(s for s in fields.axis_slots(CONSUMPTION) if s.name == name)


QUANTITY, SCENARIO, CARRIER = (_slot(n) for n in ("quantity", "scenario",
                                                  "carrier"))
FINAL = QUANTITY.options[0]            # a class the gate keeps
POTENTIAL = next(o for o in QUANTITY.options if o.label == "Potenzial")
# A line that names every answer the stub gives, so that each of them is
# backed by the passage of the row it is given for.
HEADER = (f"Tabelle 7: {FINAL.synonyms[0]}, Potenzial, Zielszenario, "
          f"{CARRIER.options[0].label}, {CARRIER.options[1].label}, 2030")


def spec_of_axes(*names):
    """The consumption parameter with only these axes. Its unit list stays, so
    the unit decides the parameter as it does in a run."""
    return Spec(parameters=[replace(
        CONSUMPTION, axes={n: CONSUMPTION.axes[n] for n in names})])


def ambiguous_spec(*names):
    """Two numeric parameters that accept the same units, so the unit does not
    settle which one a number is and the parameter is a question of its own."""
    heat = KWP.by_uri["heat_load"]
    return Spec(parameters=[
        replace(CONSUMPTION, axes={n: CONSUMPTION.axes[n] for n in names}),
        replace(heat, units_accepted=CONSUMPTION.units_accepted,
                axes={n: heat.axes[n] for n in names})])


# What the passage of the ambiguous document says about the quantity.
ENERGY = "Tabelle 7: Energieverbrauch der Waermenetze, Erdgas, 2030"


def reads_parameter(slot, rows, own):
    """The model reads the parameter in a search and nothing else."""
    if own or slot.name != "parameter":
        return None
    return {"answers": {r.label: {"value": CONSUMPTION.label,
                                  "quote": ENERGY} for r in rows}}


@dataclass
class Call:
    """One field request the stub model was asked."""
    slots: tuple
    labels: tuple
    values: tuple
    shown: tuple
    bases: tuple
    corrections: bool

    @property
    def window(self) -> tuple:
        """The far passages of the request: the window itself. What rides in
        front of it (a row's own passage) is the re-entry and not a window."""
        return tuple(k for k in self.shown if k[0] == "section")

    @property
    def own(self) -> bool:
        """A request over the passages a value came from and nothing else."""
        return not self.window


@dataclass
class World:
    """A document of several batches, a stub model that records what it was
    asked, and the harvester built over both."""
    monkeypatch: object
    batches: int = 3
    axes: tuple = ("carrier", "year")
    gate: dict = field(default_factory=dict)
    retrieval: int = 40
    rest: int = 40
    unstated: bool = False
    unit_in_own: bool = True
    # The values whose rows leave their own stage with the unit still open.
    unit_late: tuple = ()
    share: dict = None
    rows_per_batch: int = 1
    # The model's answer to one slot: (slot, rows, own) -> reply or None.
    model: object = None
    # A retrieval that does not honour what it is told has been seen.
    forget_seen: bool = False
    text: object = None
    stop: object = None
    # (which requests meet, how many of them): the first of them that are
    # asked wait for each other, and the barrier breaks if one is asked alone.
    meet: object = None
    wait: float = 5.0
    # A spec of one's own, for a document the unit does not settle.
    spec_given: object = None
    # The passages the batches' values came from are in the ranking too, as a
    # real ranking has them.
    own_in_pool: bool = False
    calls: list = field(default_factory=list)
    events: list = field(default_factory=list)
    queries: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    need_more: list = field(default_factory=list)

    def __post_init__(self):
        self.spec = self.spec_given or spec_of_axes(*self.axes)
        self.far = [Source("section", 9000 + n, f"Nichts hierzu {n}.",
                           {"document_id": 7, "page": n})
                    for n in range(self.retrieval)]
        if self.own_in_pool:
            self.far = [Source("table", n, self.text_of(n),
                               {"document_id": 7, "page": n})
                        for n in range(self.batches)] + self.far
        self.tail = [Source("section", 7000 + n, f"Abschnitt {n} ohne Angabe.",
                            {"document_id": 7, "page": n})
                     for n in range(self.rest)]
        self.monkeypatch.setattr(trace, "event", lambda kind, doc, **kw:
                                 self.events.append((kind, kw)))
        self.monkeypatch.setattr(runner, "make_harvester",
                                 lambda *a, **kw: self.rows)
        self.monkeypatch.setattr(runner, "make_field_asker", self.make_asker)
        self.barrier = threading.Barrier(2)
        self.arrivals = 0
        self.lock = threading.Lock()

    # The stubs.

    def text_of(self, n: int) -> str:
        """What the test says about batch n, and then the lines of its rows."""
        lines = [self.text(n) if self.text is not None else HEADER]
        lines += [f"| Erdgas | {VALUE0 + n + 100 * m} | MWh/a |"
                  for m in range(self.rows_per_batch)]
        return "\n".join(lines)

    def rows(self, batch, prior=None) -> dict:
        n = batch.items[0].source.owner_id
        tuples = []
        for m in range(self.rows_per_batch):
            value = VALUE0 + n + 100 * m
            tuples.append({"source": batch.label(0), "value": value,
                           "unit": "MWh/a", "unit_raw": "MWh/a",
                           "quote": f"| Erdgas | {value} | MWh/a |"})
        return {"tuples": tuples, "status": "complete", "need_more": []}

    def answer(self, slot, rows, own):
        if slot.name == fields.UNIT:
            if own and not self.unit_in_own:
                return None
            # The rows whose unit only a search reads.
            rows = [r for r in rows
                    if not (own and r.claim.get("value") in self.unit_late)]
            return {"answers": {r.label: {
                "value": "MWh/a", "value_raw": "MWh/a",
                "quote": r.claim["quote"]} for r in rows}} if rows else None
        if self.model is not None:
            return self.model(slot, rows, own)
        if self.unstated:
            return {"answers": {r.label: {"value": fields.UNSTATED}
                                for r in rows}}
        return None

    def make_asker(self, image_root=None, **kw):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            keys = tuple((s.owner_kind, s.owner_id) for s in shown)
            call = Call(tuple(s.name for s in slots),
                        tuple(r.label for r in rows),
                        tuple(r.claim.get("value") for r in rows), keys,
                        tuple(json.dumps(b, sort_keys=True)
                              for b in bases or ()),
                        bool(corrections))
            self.calls.append(call)
            if self.meet is not None and self.meet(call):
                with self.lock:
                    self.arrivals += 1
                    first = self.arrivals <= 2
                if first:
                    try:
                        self.barrier.wait(timeout=self.wait)
                    except threading.BrokenBarrierError:
                        pass
            out = {}
            for slot in slots:
                reply = self.answer(slot, rows, call.own)
                if reply is not None:
                    out[slot.name] = reply
            return {"fields": out,
                    **({"need_more": list(self.need_more)} if call.own
                       and self.need_more else {})}
        return ask

    def more(self, document_id, queries, exclude, limit=0):
        self.queries.append(list(queries))
        self.excluded.append(set(exclude))
        fresh = [s for s in self.far if self.forget_seen
                 or (s.owner_kind, s.owner_id) not in exclude]
        return fresh[:limit] if limit else fresh

    def after(self, document_id, exclude, start=None):
        return [s for s in self.tail + self.far
                if (s.owner_kind, s.owner_id) not in exclude]

    # Running it.

    def harvester(self):
        return runner.make_fieldwise_harvester(
            spec=self.spec, more_sources=self.more,
            rest_of_document=self.after, slice_gate=self.gate,
            search_share=self.share)

    def planned(self) -> list:
        return group_items(
            [WorkItem(7, None, Source("table", n, self.text_of(n),
                                      {"document_id": 7, "page": n}))
             for n in range(self.batches)], max_sources=1)

    def run(self, whole: bool = False) -> list:
        """The batches' turns and then the document step; or, whole, every
        batch swept through all its stages on its own, as a pass over a stored
        harvest does."""
        harvest = self.harvester()
        batches = self.planned()
        if whole:
            self.answered = runner.harvest_batches(batches, harvest,
                                                   workers=1, progress=False)
            return self.answered
        self.answered = runner.harvest_batches(batches, harvest.turn,
                                               workers=1, progress=False)
        self.finished = harvest.search_document(self.answered, stop=self.stop)
        return self.answered

    # Reading it.

    def claims(self) -> list:
        """Every row's claim, in the order of the values."""
        return sorted((c for _batch, reply in self.answered
                       for c in reply["tuples"]), key=lambda c: c["value"])

    def searches(self) -> list:
        return [c for c in self.calls if not c.own]

    def owns(self) -> list:
        return [c for c in self.calls if c.own]

    def traced(self, kind, **where) -> list:
        return [kw for name, kw in self.events if name == kind
                and all(kw.get(k) == v for k, v in where.items())]


def repeats(calls: list) -> dict:
    """{(coordinates, window): times} of every window asked more than once."""
    seen = Counter((c.slots, c.window) for c in calls)
    return {k: n for k, n in seen.items() if n > 1}


def small_budget(monkeypatch, rest=2):
    """No retrieval and `rest` windows of the rest stage per batch."""
    monkeypatch.setattr(runner, "FIELD_ATTEMPTS", 1)
    monkeypatch.setattr(runner, "FIELD_MAX_WINDOWS", 1)
    monkeypatch.setattr(runner, "REST_MAX_WINDOWS", rest)


# ---------------------------------------------------------------------------
# AND the passages a value came from are asked in its batch's turn as before
# ---------------------------------------------------------------------------

def test_a_batchs_own_stage_asks_what_it_asked_before(monkeypatch):
    """Own requests of the new flow are the requests of the old one: the same
    rows over the same passages, the unit first. Violating: an own stage that
    is skipped, which the comparison must see."""
    world = World(monkeypatch, batches=3)
    world.run(whole=True)
    before = sorted((c.slots, c.labels, c.shown) for c in world.owns())
    assert before, "the old flow asked its own stage"
    world.calls.clear()
    world.run()
    after = sorted((c.slots, c.labels, c.shown) for c in world.owns())
    assert after == before
    for n in range(3):
        mine = [c.slots for c in world.owns() if ("table", n) in c.shown]
        assert mine[0] == (fields.UNIT,), "the unit comes first in a turn"

    monkeypatch.setattr(runner.Sweeper, "own",
                        lambda self, *a, **k: {"asked": 0})
    skipped = World(monkeypatch, batches=3)
    skipped.run()
    assert sorted((c.slots, c.labels, c.shown)
                  for c in skipped.owns()) != before


# ---------------------------------------------------------------------------
# AND what is still open is searched once per document and coordinate
# ---------------------------------------------------------------------------

def test_what_the_batches_left_open_is_searched_once_with_their_rows_together(
        monkeypatch):
    """Three batches each leave one row open on the same axis: every window of
    the search is asked once, with the three rows in it. Violating: a search
    per batch asks every window three times, which is what the batches' own
    sweeps did."""
    world = World(monkeypatch, batches=3, unstated=True)
    world.run()
    searches = world.searches()
    assert searches
    assert max(Counter((c.slots, c.window) for c in searches).values()) == 1
    assert all(len(c.labels) == 3 for c in searches), (
        "every row still open is in every window")
    # One search per coordinate, so one `sweep` event per coordinate.
    document = world.traced("sweep", scope="document")
    assert sorted(e["slot"] for e in document) == ["carrier", "year"]
    assert all(e["batches"] == 3 for e in document)

    per_batch = World(monkeypatch, batches=3, unstated=True)
    per_batch.run(whole=True)
    again = Counter((c.slots, c.window) for c in per_batch.searches())
    assert max(again.values()) == 3, "the old sweeps asked each window thrice"


def test_what_the_own_stages_read_is_written_as_the_whole_harvest_wrote_it(
        monkeypatch):
    """A document whose coordinates every batch's own stages read has nothing
    left to search: no search request, and the rows are the rows the
    whole harvest of each batch made, key for key. Violating: a model that
    leaves a coordinate open, whose rows must differ from them."""
    def reads(slot, rows, own):
        said = {"carrier": CARRIER.options[0].label, "year": 2030}[slot.name]
        return {"answers": {r.label: {"value": said, "quote": HEADER}
                            for r in rows}}

    before = World(monkeypatch, batches=3, model=reads)
    before.run(whole=True)
    now = World(monkeypatch, batches=3, model=reads)
    now.run()
    assert now.claims() == before.claims()
    assert not now.searches() and not before.searches()
    assert {c["carrier_state"] for c in now.claims()} == {fields.READ}
    quiet = World(monkeypatch, batches=3, unstated=True)
    quiet.run()
    assert quiet.claims() != before.claims()


def test_the_rows_of_a_one_batch_document_keep_their_labels(monkeypatch):
    """A batch's rows are asked under the labels the rows request gave them,
    so a field request for a given set of rows and passages is what it was.
    Only rows of several batches are given labels of their own."""
    world = World(monkeypatch, batches=1, rows_per_batch=2, unstated=True)
    world.run()
    assert world.searches()
    assert all(c.labels == ("R1", "R2") for c in world.calls)
    many = World(monkeypatch, batches=2, rows_per_batch=2, unstated=True)
    many.run()
    assert all(c.labels == ("R1", "R2") for c in many.owns())
    assert all(c.labels == ("R1", "R2", "R3", "R4") for c in many.searches())


def test_what_the_model_still_needed_in_a_batchs_own_stage_reaches_the_search(
        monkeypatch):
    """The own stage's `need_more` is a probe of the retrieval, as it was when
    the stages were one sweep. Violating: a search that heard nothing."""
    ask = "Welche Jahreszahl nennt die Tabelle fuer den Bestand der Netze?"
    world = World(monkeypatch, batches=2, unstated=True)
    world.need_more = [ask]
    world.run()
    assert any(ask in q for q in world.queries)
    quiet = World(monkeypatch, batches=2, unstated=True)
    quiet.run()
    assert not any(ask in q for q in quiet.queries)


def test_batches_that_read_the_document_differently_are_asked_apart(
        monkeypatch):
    """The base years are on every batch of a document, so there is one group
    in a run. Rows under other base years would be asked in requests of their
    own, because a request carries one list of them."""
    world = World(monkeypatch, batches=3, unstated=True)
    base = {"axis": "year", "year": 2020, "quote": "Basisjahr 2020 im Plan",
            "source": ["table", 0], "index": 0}
    planned = world.planned()
    planned[0].bases = (base,)
    harvest = world.harvester()
    world.answered = runner.harvest_batches(planned, harvest.turn, workers=1,
                                            progress=False)
    assert harvest.search_document(world.answered)
    sizes = sorted({len(c.labels) for c in world.searches()})
    assert sizes == [1, 2], "one row under the base year, two under none"
    assert {c.bases for c in world.searches() if len(c.labels) == 1} == {
        (json.dumps(base, sort_keys=True),)}
    assert {c.bases for c in world.searches() if len(c.labels) == 2} == {()}


def test_a_document_of_one_batch_asks_what_it_asked_before(monkeypatch):
    """With one batch the search is that batch's own sweep: the same requests
    over the same passages, the retrieval told to leave out the passages its
    own stage asked. Violating: a search that leaves nothing out shows the
    batch's own passage again, which the pool of a real ranking holds; and
    several batches ask fewer requests than their sweeps did, so the same
    comparison over three batches must come out unequal."""
    def asked(world):
        return Counter((c.slots, c.labels, c.shown, c.corrections)
                       for c in world.calls)

    def looked(world):
        return sorted(sorted(e) for e in world.excluded)

    before = World(monkeypatch, batches=1, unstated=True, retrieval=6,
                   rest=9, own_in_pool=True)
    before.run(whole=True)
    now = World(monkeypatch, batches=1, unstated=True, retrieval=6, rest=9,
                own_in_pool=True)
    now.run()
    assert asked(now) == asked(before)
    assert looked(now) == looked(before)
    assert sorted(map(tuple, now.queries)) == sorted(map(tuple,
                                                         before.queries))
    assert all(("table", 0) in e for e in now.excluded), (
        "the retrieval is told what the own stage asked")

    three = World(monkeypatch, batches=3, unstated=True, retrieval=6,
                  rest=9, own_in_pool=True)
    three.run()
    wholes = World(monkeypatch, batches=3, unstated=True, retrieval=6,
                   rest=9, own_in_pool=True)
    wholes.run(whole=True)
    assert asked(three) != asked(wholes)


def test_a_search_over_several_batches_leaves_nothing_out_of_its_ranking(
        monkeypatch):
    """What one batch's rows were read in is new to the rows of the others,
    so the retrieval of a search over several batches is told nothing about
    them. Violating: the one-batch rule applied to three, which hides the
    passage another batch's row stands in."""
    one = World(monkeypatch, batches=1, unstated=True, retrieval=6, rest=9)
    one.run()
    many = World(monkeypatch, batches=3, unstated=True, retrieval=6, rest=9)
    many.run()
    assert one.excluded and many.excluded
    assert all(any(k[0] == "table" for k in e) for e in one.excluded)
    assert not any(k[0] == "table" for e in many.excluded for k in e)


# ---------------------------------------------------------------------------
# AND no window of that search is asked twice for the same coordinate
# ---------------------------------------------------------------------------

def test_no_window_of_the_search_is_asked_twice(monkeypatch):
    """Across retrieval and the rest of the document: no (coordinate, window)
    repeats. Violating: a retrieval that hands its pool over again, which the
    same check sees."""
    world = World(monkeypatch, batches=3, unstated=True, retrieval=6, rest=9)
    world.run()
    assert world.searches()
    assert repeats(world.searches()) == {}

    forgetful = World(monkeypatch, batches=3, unstated=True, retrieval=6,
                      rest=9, forget_seen=True)
    forgetful.run()
    assert repeats(forgetful.searches()), (
        "the check can see a pool handed over twice")


# ---------------------------------------------------------------------------
# AND the rest stage's allowance is the batches' together, and ends with the
# document
# ---------------------------------------------------------------------------

def test_the_rest_stage_gets_its_allowance_once_for_every_batch_with_an_open_row(
        monkeypatch):
    """REST_MAX_WINDOWS 2: three batches may ask six windows, one batch two;
    SEARCH_SHARE scales it (`budget_of` of the sweeper). Violating: a fixed
    two, or no bound at all, both of which miss the exact count."""
    small_budget(monkeypatch, rest=2)
    for batches, expected in ((3, 6), (1, 2)):
        world = World(monkeypatch, batches=batches, unstated=True, rest=40)
        world.run()
        windows = world.traced("field", slot="carrier", stage="rest")
        assert len(windows) == expected, (batches, len(windows))
        assert all(w["batches"] == batches for w in windows)
    scaled = World(monkeypatch, batches=3, unstated=True, rest=40,
                   share={"carrier": 0.5})
    scaled.run()
    assert len(scaled.traced("field", slot="carrier", stage="rest")) == 3
    assert len(scaled.traced("field", slot="year", stage="rest")) == 6

    # Counted on the batches that still have an open row when the stage
    # begins, as the batches' own sweeps would have: a batch whose row was
    # read by the retrieval has no rest stage.
    monkeypatch.setattr(runner, "FIELD_MAX_WINDOWS", 3)

    def read_for_first(slot, rows, own):
        if own or slot.name != "carrier":
            return None
        return {"answers": {r.label: {
            "value": CARRIER.options[0].label, "quote": HEADER}
            for r in rows if r.claim["value"] == VALUE0}}

    mixed = World(monkeypatch, batches=3, rest=40, model=read_for_first)
    mixed.run()
    assert len(mixed.traced("field", slot="carrier", stage="retrieval")) == 2
    assert len(mixed.traced("field", slot="carrier", stage="rest")) == 4, (
        "two batches still had an open row of the carrier")


def rest_requests(world, slot: str = "carrier") -> int:
    """The requests the rest stage sent for one coordinate. The asker cuts the
    open rows of a window into requests of FIELD_ROWS; the stub is asked once
    per window, so the cut is made here."""
    return sum(-(-window["open"] // runner.FIELD_ROWS)
               for window in world.traced("field", slot=slot, stage="rest"))


def test_the_rest_stage_never_sends_more_requests_than_the_batches_own_windows(
        monkeypatch):
    """Owner, 2026-10-07: the search costs as much as today in total. Three
    batches of 40 open rows and two windows each: a batch's own sweep sends two
    requests per window (40 rows over 32), 12 for the document. One window of
    the search shows 120 rows and is four requests, so three windows are what
    the document may ask, not the six that counting windows alone allows.
    Violating: the cost of a window counted as nothing, which the same sum
    must see as more than before."""
    small_budget(monkeypatch, rest=2)

    def harvested(whole: bool = False):
        world = World(monkeypatch, batches=3, rows_per_batch=40,
                      axes=("carrier",), unstated=True, retrieval=0, rest=40)
        world.run(whole=whole)
        return world

    before, after = harvested(whole=True), harvested()
    assert rest_requests(before) == 12
    assert 0 < rest_requests(after) <= rest_requests(before)
    windows = after.traced("field", slot="carrier", stage="rest")
    assert len(windows) == 3 and {w["open"] for w in windows} == {120}
    # Cut by its allowance and not at the document's end: said as such.
    assert {c["carrier_state"] for c in after.claims()} == {fields.EXHAUSTED}

    monkeypatch.setattr(runner.Sweeping, "requests_of", lambda self, rows: 0)
    unbounded = harvested()
    assert rest_requests(unbounded) > rest_requests(before)


def test_the_rest_stage_stops_where_the_document_does(monkeypatch):
    """A document of three passages is two windows, and the allowance of
    three batches is six. Violating: asking the allowance."""
    small_budget(monkeypatch, rest=2)
    world = World(monkeypatch, batches=3, unstated=True, rest=3, retrieval=0)
    world.run()
    assert len(world.traced("field", slot="carrier", stage="rest")) == 2


# ---------------------------------------------------------------------------
# AND a search that read the document to its end is unstated, one that ended
# on its allowance is exhausted
# ---------------------------------------------------------------------------

def test_a_document_read_to_its_end_is_unstated_and_a_cut_one_exhausted(
        monkeypatch):
    """Five passages are four windows. Per batch the allowance of two cut every
    sweep short; for three batches together it reaches the end. Violating: the
    states swapped, which is what the old flow gave the short document."""
    small_budget(monkeypatch, rest=2)
    short = World(monkeypatch, batches=3, unstated=True, rest=5, retrieval=0)
    short.run()
    assert {c["carrier_state"] for c in short.claims()} == {fields.SAID_UNSTATED}
    assert {c["year_state"] for c in short.claims()} == {fields.SAID_UNSTATED}

    long = World(monkeypatch, batches=3, unstated=True, rest=40, retrieval=0)
    long.run()
    assert {c["carrier_state"] for c in long.claims()} == {fields.EXHAUSTED}

    old = World(monkeypatch, batches=3, unstated=True, rest=5, retrieval=0)
    old.run(whole=True)
    assert {c["carrier_state"] for c in old.claims()} == {fields.EXHAUSTED}, (
        "the short document ended on the allowance of the batch, so the old "
        "flow could not say what the new one says")


# ---------------------------------------------------------------------------
# AND a row is asked for a coordinate only when the coordinates that decide it
# are settled
# ---------------------------------------------------------------------------

def asked_before(calls: list, value: int, slots: tuple, gate: str) -> bool:
    """Was this row asked for any of these slots before the search that asked
    it for the gate, or at all when no search did?"""
    first = next((i for i, c in enumerate(calls)
                  if not c.own and gate in c.slots and value in c.values),
                 len(calls))
    return any(i < first for i, c in enumerate(calls)
               if value in c.values and set(c.slots) & set(slots))


def gate_model(slot, rows, own):
    """The first row is closed by the quantity at once; the second and the
    third are not answered by their own passage, and the search finds a class
    the gate keeps for the second and one it closes for the third."""
    said = {
        "quantity": {VALUE0: POTENTIAL.label,
                     VALUE0 + 1: None if own else FINAL.label,
                     VALUE0 + 2: None if own else POTENTIAL.label},
        "scenario": {n: "Zielszenario" for n in range(VALUE0, VALUE0 + 3)},
        "carrier": {n: CARRIER.options[0].label
                    for n in range(VALUE0, VALUE0 + 3)},
        "year": {n: 2030 for n in range(VALUE0, VALUE0 + 3)}}[slot.name]
    return {"answers": {r.label: {"value": said[r.claim["value"]],
                                  "quote": HEADER}
                        for r in rows if said[r.claim["value"]] is not None}}


def test_a_row_waits_at_a_gate_coordinate_that_is_still_open(monkeypatch):
    """A row whose quantity is open after its own stage is asked no other axis
    until the quantity's search has settled it, and a row the gate closes is
    never asked for one: its axes say out_of_slice. Violating: axes asked
    before the gate, which `asked_before` must see in a record that has them."""
    world = World(monkeypatch, batches=3, axes=("quantity", "scenario",
                                                "carrier", "year"),
                  gate=GATE, model=gate_model)
    world.run()
    behind = ("scenario", "carrier", "year")
    for closed in (VALUE0, VALUE0 + 2):
        assert not any(closed in c.values and set(c.slots) & set(behind)
                       for c in world.calls), "a closed row is asked nothing"
    claims = {c["value"]: c for c in world.claims()}
    for closed in (VALUE0, VALUE0 + 2):
        assert all(claims[closed][f"{n}_state"] == fields.OUT_OF_SLICE
                   for n in behind), claims[closed]
        assert claims[closed]["quantity_state"] == fields.READ
    kept = claims[VALUE0 + 1]
    assert [kept[f"{n}_state"] for n in behind] == [fields.READ] * 3
    assert not asked_before(world.calls, VALUE0 + 1, behind, "quantity")
    assert any(not c.own and "quantity" in c.slots
               and VALUE0 + 1 in c.values for c in world.calls), (
        "and its quantity was asked in the search")

    early = [Call(("carrier",), ("R1",), (VALUE0 + 1,), (("table", 1),), (),
                  False),
             Call(("quantity",), ("R1",), (VALUE0 + 1,),
                  (("section", 9000),), (), False)]
    assert asked_before(early, VALUE0 + 1, behind, "quantity")


def test_a_row_whose_unit_is_open_waits_for_the_unit_search(monkeypatch):
    """A row with an open unit is asked for no axis before the unit's search
    (`Turn.go_on` is not reached for it); when the search reads the unit the
    parameter is derived (`Turn.settle_parameter`) and the axes are asked, own
    stage first and then their searches. A unit the search does not read
    leaves the row out of the slice, its axes never asked. Violating: axes
    asked in the turn."""
    world = World(monkeypatch, batches=2, unit_in_own=False, unstated=True)
    world.run()
    calls = world.calls
    unit_search = next(i for i, c in enumerate(calls)
                       if fields.UNIT in c.slots and not c.own)
    assert all(c.slots == (fields.UNIT,) for c in calls[:unit_search]), (
        "nothing but the unit before the unit's search")
    axes = [i for i, c in enumerate(calls) if set(c.slots) & {"carrier",
                                                              "year"}]
    assert axes and min(axes) > unit_search
    assert all(c["parameter_state"] == fields.DERIVED
               and c["unit_state"] == fields.READ for c in world.claims())
    # The axes' own stages come before the axes' searches.
    own_axes = [i for i in axes if calls[i].own]
    assert own_axes and max(own_axes) < min(i for i in axes
                                            if not calls[i].own)

    never = World(monkeypatch, batches=2, unit_in_own=False)
    never.model = None
    never.answer = lambda slot, rows, own: None
    never.run()
    assert not [c for c in never.calls if set(c.slots) & {"carrier", "year"}]
    for claim in never.claims():
        assert claim["parameter_state"] == fields.OUT_OF_SLICE
        assert claim["unit_state"] in (fields.UNANSWERED, fields.EXHAUSTED)


def test_a_coordinate_is_searched_once_though_its_rows_reach_it_by_different_ways(
        monkeypatch):
    """One row waits at the unit and reaches the gate only after the unit's
    search; the other's unit was read in its own stage and it waits at the gate
    at once. The gate is still searched ONCE, over both rows, because a
    coordinate is searched when every row that will come to it has: the unit,
    then the parameter, then each gate axis in its order (`DocumentSearch.phase`).
    Violating: phases that are not kept apart search the gate for the row that
    was there and again for the row that came."""
    world = World(monkeypatch, batches=2, axes=("quantity", "carrier",
                                                "year"),
                  gate={"quantity": None}, unit_late=(VALUE0,), retrieval=4,
                  rest=4, model=lambda slot, rows, own: None)
    world.run()
    quantity = world.traced("sweep", scope="document", slot="quantity")
    assert len(quantity) == 1, "one search for the gate"
    assert quantity[0]["rows"] == 2 and quantity[0]["batches"] == 2
    assert all(len(c.labels) == 2 for c in world.searches()
               if c.slots == ("quantity",))
    assert repeats(world.searches()) == {}
    unit = world.traced("sweep", scope="document", slot=fields.UNIT)
    assert len(unit) == 1 and unit[0]["rows"] == 1, (
        "and the unit's search is over the one row that waited at it")


def test_a_row_whose_parameter_is_open_waits_for_the_parameter_search(
        monkeypatch):
    """The unit settles nothing here (two parameters accept it), so the
    parameter is asked: its own stage in each batch's turn, and one search over
    the rows of both batches. No axis is asked for a row before that search
    has read the parameter (`Turn.settle_parameter` hands them to
    `Turn.enter`), and then their own stages come before their searches. A
    parameter the search does not read leaves the row with no axes to ask.
    Violating: axes asked before the search, which `asked_before` must see in
    a record that has them."""
    spec = ambiguous_spec("carrier", "year")
    world = World(monkeypatch, batches=2, spec_given=spec,
                  text=lambda n: ENERGY, model=reads_parameter)
    world.run()
    calls = world.calls
    search = next(i for i, c in enumerate(calls)
                  if c.slots == ("parameter",) and not c.own)
    assert all(set(c.slots) <= {fields.UNIT, "parameter"}
               for c in calls[:search]), (
        "nothing but the unit and the parameter's own stage before the search")
    assert len([c for c in calls[:search] if c.slots == ("parameter",)]) == 2
    assert all(len(c.labels) == 2 for c in calls
               if c.slots == ("parameter",) and not c.own), (
        "one search for the rows of both batches")
    axes = [i for i, c in enumerate(calls)
            if set(c.slots) & {"carrier", "year"}]
    assert axes and min(axes) > search
    own_axes = [i for i in axes if calls[i].own]
    assert own_axes and max(own_axes) < min(i for i in axes
                                            if not calls[i].own)
    claims = world.claims()
    assert {c["parameter_state"] for c in claims} == {fields.READ}
    assert {c["parameter"] for c in claims} == {CONSUMPTION.uri}
    for value in (VALUE0, VALUE0 + 1):
        assert not asked_before(calls, value, ("carrier", "year"),
                                "parameter")

    early = [Call(("carrier",), ("R1",), (VALUE0,), (("table", 0),), (),
                  False),
             Call(("parameter",), ("R1",), (VALUE0,), (("section", 9000),),
                  (), False)]
    assert asked_before(early, VALUE0, ("carrier", "year"), "parameter")

    never = World(monkeypatch, batches=2, spec_given=spec,
                  text=lambda n: ENERGY, model=lambda slot, rows, own: None)
    never.run()
    assert not [c for c in never.calls
                if set(c.slots) & {"carrier", "year"}], (
        "a row without a parameter has no axes to ask for")
    for claim in never.claims():
        assert claim["parameter_state"] in (fields.EXHAUSTED,
                                            fields.UNANSWERED)
        assert "carrier_state" not in claim and "year_state" not in claim


# ---------------------------------------------------------------------------
# AND every answer is checked as before: against the passages shown and the
# row's own
# ---------------------------------------------------------------------------

def test_two_batches_with_a_row_of_the_same_label_get_their_own_answers(
        monkeypatch):
    """Both rows are R1 in their batches and open on the carrier. The search
    gives them labels of their own and an answer for one never lands on the
    other. Violating: the labels passed through, which `merge_field` cannot
    tell apart."""
    gas, oil = CARRIER.options[0].label, CARRIER.options[1].label
    said = {VALUE0: (gas, f"{gas} im Block {VALUE0}"),
            VALUE0 + 1: (oil, f"{oil} im Block {VALUE0 + 1}")}

    def model(slot, rows, own):
        if own:
            return None
        return {"answers": {r.label: {
            "value": said[r.claim["value"]][0],
            "quote": said[r.claim["value"]][1]} for r in rows}}

    world = World(monkeypatch, batches=2, axes=("carrier",), model=model,
                  text=lambda n: said[VALUE0 + n][1])
    world.run()
    labels = [c.labels for c in world.searches()]
    assert labels and all(len(set(l)) == len(l) == 2 for l in labels)
    got = {c["value"]: c["carrier"] for c in world.claims()}
    assert got == {VALUE0: gas, VALUE0 + 1: oil}

    # The hazard the labels remove: two rows of one label in one reply.
    first = Row("R1", 0, {"value": 1})
    second = Row("R1", 0, {"value": 2})
    quote = f"{gas} im Netz"
    merge_field([first, second], [Source("table", 0, quote, {})], CARRIER,
                {"answers": {"R1": {"value": gas, "quote": quote}}})
    assert "carrier" not in first.claim, "the answer went to the other row"


def test_an_answer_quoting_the_passage_of_another_batch_is_not_read(
        monkeypatch):
    """A quote is good when it stands in a passage shown in this request or in
    the row's own passages. The other batch's passage was not shown, so the
    first row's answer is dropped; the second row's, in its own, is read.
    Violating: the union of the batches' passages as the pool, which reads
    both."""
    monkeypatch.setattr(runner, "FIELD_RE_ENTRY", 0)
    carrier = CARRIER.options[0].label
    texts = {0: f"{carrier} im Waermenetz Nord, Zeile {VALUE0}",
             1: f"{carrier} im Waermenetz Sued, Zeile {VALUE0 + 1}"}
    south = f"{carrier} im Waermenetz Sued"

    def model(slot, rows, own):
        if own:
            return None
        return {"answers": {r.label: {"value": carrier, "quote": south}
                            for r in rows}}

    # A document of two passages: one window, read to its end, so what the
    # first row's answer was left as is what the search says of it.
    world = World(monkeypatch, batches=2, axes=("carrier",), model=model,
                  text=lambda n: texts[n], retrieval=0, rest=2)
    world.run()
    claims = {c["value"]: c for c in world.claims()}
    assert claims[VALUE0]["carrier_state"] == fields.UNBACKED
    assert "carrier" not in claims[VALUE0]
    assert claims[VALUE0 + 1]["carrier_state"] == fields.READ
    assert claims[VALUE0 + 1]["carrier"] == carrier

    one = Source("table", 0, texts[0], {})
    other = Source("table", 1, texts[1], {})
    row = Row("R1", 0, {"value": VALUE0})
    got = merge_field([row], [one, other], CARRIER,
                      {"answers": {"R1": {"value": carrier, "quote": south}}})
    assert got["filled"] == 1, (
        "against the union of the passages the same answer would be read")


# ---------------------------------------------------------------------------
# AND a pass over a stored harvest walks the three stages per batch as before
# ---------------------------------------------------------------------------

def test_the_whole_harvest_of_a_batch_is_still_every_stage_for_that_batch(
        monkeypatch):
    """`harvest` itself (`turn_of` with the stages not deferred) is unchanged
    for the passes over a stored harvest: each batch is swept on its own, and
    its reply is final. `harvest_turn` is the other one. Violating: a reply
    that still waits for a document step."""
    world = World(monkeypatch, batches=2, unstated=True)
    answered = world.run(whole=True)
    assert all("_turn" not in reply for _batch, reply in answered)
    assert world.traced("sweep", scope="batch")
    assert not world.traced("sweep", scope="document")
    states = {c["carrier_state"] for c in world.claims()}
    assert states <= {fields.SAID_UNSTATED, fields.EXHAUSTED}

    deferred = World(monkeypatch, batches=2, unstated=True)
    turns = deferred.harvester().turn
    reply = turns(deferred.planned()[0])
    assert "_turn" in reply, "a turn waits for the document step"


def test_the_sweeper_of_a_stored_harvest_walks_every_stage_for_its_batch(
        monkeypatch):
    """What a top-up re-reads one coordinate with (`Sweeper.__call__`, the
    callable `make_sweeper` returns): own, retrieval and rest for the rows of
    ONE batch, in one sweep, with the allowance of one batch. Violating: the
    two halves called apart, which leave a sweep of the own stage alone or a
    search over the rows of one batch, each with a scope of its own."""
    world = World(monkeypatch, batches=1, unstated=True, retrieval=6, rest=9)
    sweeper = runner.make_sweeper(world.make_asker(),
                                  more_sources=world.more,
                                  rest_of_document=world.after)
    batch = world.planned()[0]
    rows, _orphans = rows_from_reply(batch, world.rows(batch), None,
                                     world.spec)
    totals = sweeper(batch, rows, [CARRIER], "anchor")
    stages = [e["stage"] for e in world.traced("field")]
    assert stages[0] == "own" and {"retrieval", "rest"} <= set(stages)
    assert [e["scope"] for e in world.traced("sweep")] == ["batch"]
    assert totals["asked"] == len(stages) == len(world.calls)
    assert {e["batches"] for e in world.traced("field")} == {1}

    halves = World(monkeypatch, batches=1, unstated=True, retrieval=6, rest=9)
    parts = runner.make_sweeper(halves.make_asker(),
                                more_sources=halves.more,
                                rest_of_document=halves.after)
    batch = halves.planned()[0]
    rows, _orphans = rows_from_reply(batch, halves.rows(batch), None,
                                     halves.spec)
    parts.own(batch, rows, [CARRIER], "anchor")
    assert [e["scope"] for e in halves.traced("sweep")] == ["own"]
    assert {e["stage"] for e in halves.traced("field")} == {"own"}


# ---------------------------------------------------------------------------
# What runs beside what
# ---------------------------------------------------------------------------

def test_the_axes_of_a_turn_are_asked_side_by_side(monkeypatch):
    """A turn's own stages of its axes (`Turn.run_jobs`) are as concurrent as
    the whole sweeps were. Two requests wait for each other; a chain would
    leave the first waiting for a partner that never comes."""
    world = World(monkeypatch, batches=1,
                  meet=lambda c: c.own and c.slots != (fields.UNIT,))
    world.run()
    assert world.arrivals == 2 and not world.barrier.broken


def test_the_searches_of_different_coordinates_run_side_by_side(monkeypatch):
    """The carrier's search and the year's search are tasks of the field pool
    beside each other (`DocumentSearch.fan_out`). Violating: one coordinate
    after the other, which breaks the barrier; the same record under a
    single coordinate is what that looks like."""
    world = World(monkeypatch, batches=2, unstated=True, rest=4, retrieval=2,
                  meet=lambda c: not c.own)
    world.run()
    assert world.arrivals >= 2 and not world.barrier.broken

    alone = World(monkeypatch, batches=2, axes=("carrier",), unstated=True,
                  rest=4, retrieval=2, meet=lambda c: not c.own)
    alone.wait = 0.2
    alone.run()
    assert alone.barrier.broken, "a lone search finds no partner"


def test_the_batches_that_go_on_after_a_search_do_so_side_by_side(monkeypatch):
    """After the unit's search every batch whose rows waited for it asks its
    axes' own stages (`DocumentSearch.carry_on`), as tasks of the field pool.
    Two of them meet; the batches are not walked one after another."""
    world = World(monkeypatch, batches=2, unit_in_own=False,
                  meet=lambda c: c.own and c.slots != (fields.UNIT,))
    world.run()
    assert world.arrivals >= 2 and not world.barrier.broken
    assert {tuple(sorted(c.values)) for c in world.owns()
            if c.slots != (fields.UNIT,)} <= {(VALUE0,), (VALUE0 + 1,)}


# ---------------------------------------------------------------------------
# The trace, the dry run and the stop
# ---------------------------------------------------------------------------

def test_the_trace_tells_a_search_from_a_batchs_own_stage(monkeypatch):
    """`field` and `sweep` keep their keys; `batches` and `scope` say what the
    rows came from. A drop carries `batches` too, because a label of a search
    does not name a batch."""
    world = World(monkeypatch, batches=3, unstated=True, rest=4, retrieval=2)

    def bad(slot, rows, own):
        return {"answers": {r.label: {"value": CARRIER.options[0].label,
                                      "quote": "steht in keiner Passage"}
                            for r in rows}}

    world.model = bad
    world.run()
    own = [e for e in world.traced("field") if e["stage"] == "own"]
    found = [e for e in world.traced("field") if e["stage"] != "own"]
    assert own and found
    assert {e["batches"] for e in own} == {1}
    assert {e["batches"] for e in found} == {3}
    # The unit, the carrier and the year of each of three batches in their
    # own stages; the carrier and the year once for the document.
    assert Counter(e["scope"] for e in world.traced("sweep")) == Counter(
        own=9, document=2)
    assert {e["batches"] for e in world.traced("drop", attempt=0)} == {1, 3}
    for event in world.traced("field"):
        assert {"slot", "window", "stage", "attempt", "filled", "open",
                "shown"} <= set(event)


def test_every_coordinate_of_a_dry_run_ends_in_a_state(monkeypatch):
    """The stub model says nothing at all, so every row is walked through
    every stage and still every coordinate that applies to it has a state."""
    world = World(monkeypatch, batches=5, axes=("quantity", "scenario",
                                                "carrier", "year"),
                  gate=GATE, retrieval=4, rest=6)
    world.run()
    assert world.finished
    claims = world.claims()
    assert len(claims) == 5
    for claim in claims:
        for name in ("unit", "parameter", "quantity", "scenario", "carrier",
                     "year"):
            assert claim.get(f"{name}_state"), (claim["value"], name)


def test_a_stop_during_the_document_step_ends_it_and_says_so(monkeypatch):
    """The step is not finished and says so, so the document is not written.
    Violating: a stop that is only noticed once the search is over."""
    halt = threading.Event()
    world = World(monkeypatch, batches=3, axes=("carrier",), unstated=True,
                  stop=halt)
    seen = []
    plain = world.make_asker

    def make_asker(*a, **kw):
        ask = plain(*a, **kw)

        def stopping(shown, rows, slots, *rest, **more):
            if not all(s.owner_kind == "table" for s in shown):
                seen.append(1)
                halt.set()
            return ask(shown, rows, slots, *rest, **more)
        return stopping

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    world.run()
    assert world.finished is False
    assert len(seen) == 1, "no request was sent after the stop"

    calm = World(monkeypatch, batches=3, axes=("carrier",), unstated=True,
                 stop=threading.Event())
    calm.run()
    assert calm.finished is True


def test_a_document_whose_step_did_not_finish_is_not_written(monkeypatch,
                                                              tmp_path,
                                                              corpus_run):
    """`main` harvests a document through its turn, hands the step the run's
    stop, and writes nothing when the step says it did not finish. Violating:
    a document stamped as read whole, which the same run with a step that does
    finish must not be mistaken for: that one is written."""
    db, out = corpus_run
    seen = {}

    def make_retrieve(conn, index, id_to_pos, cache_conn, fetch, limit=0):
        return lambda probes, document_id, exclude: [Source(
            "section", 10, TEXT, {"document_id": document_id, "page": 1,
                                  "title": "Scenarios"})]

    monkeypatch.setattr(runner, "make_retrieve", make_retrieve)

    def make_fieldwise(*a, **k):
        def whole(batch, prior=None):
            seen["whole"] = seen.get("whole", 0) + 1
            return turn(batch, prior)

        def turn(batch, prior=None):
            seen["turns"] = seen.get("turns", 0) + 1
            return {"tuples": [], "status": "complete", "need_more": []}

        def search_document(answered, stop=None):
            seen["stop"] = stop
            seen["answered"] = len(answered)
            return seen["finished"]
        whole.turn, whole.search_document = turn, search_document
        return whole

    monkeypatch.setattr(runner, "make_fieldwise_harvester", make_fieldwise)
    monkeypatch.setattr(runner, "fit_batch_sources", lambda *a, **k: 1)
    monkeypatch.setattr(runner, "LLM_PARALLEL", 1)

    def run(finished):
        seen.clear()
        seen["finished"] = finished
        shutil.rmtree(out, ignore_errors=True)
        try:
            return runner.main([str(db), "no.index", str(out), "--image-root",
                                str(tmp_path), "--document", "1"])
        finally:
            trace.close()

    run(False)
    assert seen["turns"] >= 1 and not seen.get("whole"), (
        "a document is harvested through its turn")
    assert seen["answered"] >= 1 and hasattr(seen["stop"], "is_set")
    assert not (out / "a.jsonl").exists()
    assert not (out / "a.stamp.json").exists()

    run(True)
    assert (out / "a.jsonl").exists() and (out / "a.stamp.json").exists()


# ---------------------------------------------------------------------------
# The path a real run takes, and the passes that do not take it
# ---------------------------------------------------------------------------

def spied(monkeypatch) -> list:
    """The run's own harvester, and which of its entries a run used: its turn
    and its document step, or the whole harvest of a batch."""
    real = runner.make_fieldwise_harvester
    used: list = []

    def make(*a, **k):
        harvest = real(*a, **k)

        def whole(batch, prior=None):
            used.append("whole")
            return harvest(batch, prior)

        def turn(batch, prior=None):
            used.append("turn")
            return harvest.turn(batch, prior)

        def step(answered, stop=None):
            used.append("search")
            return harvest.search_document(answered, stop=stop)
        whole.turn, whole.search_document = turn, step
        return whole

    monkeypatch.setattr(runner, "make_fieldwise_harvester", make)
    return used


def traced_scopes(folder: Path) -> Counter:
    """How many sweeps of each scope a document's trace file holds."""
    lines = (folder / "a.trace.jsonl").read_text("utf-8").splitlines()
    return Counter(r.get("scope") for r in map(json.loads, lines)
                   if r["t"] == "sweep")


def test_a_harvested_document_goes_through_its_turn_and_one_search(
        monkeypatch, frame_column):
    """`runner.main` over a document, the run's own harvester, the model a
    stub that says "not stated" to everything it is asked: each batch asks its
    own stage in its turn, the document is searched once for every coordinate
    that stayed open, the file is written, and every coordinate of every row
    in it has a state. Violating: the same run through a harvester that has no
    halves walks every batch in whole and has no search of the document in its
    trace."""
    column = frame_column
    column.write_spec()
    # The violating run first: a harvester without halves is harvested in
    # whole, batch by batch, and the trace says so.
    real = runner.make_fieldwise_harvester

    def without_halves(*a, **k):
        harvest = real(*a, **k)
        return lambda batch, prior=None: harvest(batch, prior)

    monkeypatch.setattr(runner, "make_fieldwise_harvester", without_halves)
    assert column.main() == 0
    scopes = traced_scopes(column.out / "trace")
    assert scopes["batch"] >= 1 and not scopes["document"]
    shutil.rmtree(column.out)
    monkeypatch.setattr(runner, "make_fieldwise_harvester", real)

    used = spied(monkeypatch)
    assert column.main() == 0
    assert used.count("turn") >= 1 and used.count("search") == 1
    assert "whole" not in used
    scopes = traced_scopes(column.out / "trace")
    assert scopes["document"] >= 1 and scopes["own"] >= 1
    assert not scopes["batch"]
    rows = [json.loads(line) for line in
            (column.out / "a.jsonl").read_text("utf-8").splitlines()]
    tuples = [r for r in rows if r["kind"] == "tuple"]
    assert tuples
    axes = ("quantity", "aggregation", "carrier", "sector", "year",
            "scenario", "spatial_scope")
    for row in tuples:
        for axis in axes:
            assert row.get(f"{axis}_state"), (axis, row)


def test_the_pass_for_a_new_parameter_asks_each_rebuilt_batch_in_whole(
        monkeypatch, frame_column):
    """The pass appends a parameter to a stored harvest through the same
    batches and pools, and walks the three stages per rebuilt batch as it
    always did: no turn, no document step, and its sweeps are the sweeps of a
    batch. Violating: the harvest of the same corpus, which does take the
    turn and the step."""
    column = frame_column
    column.store()
    column.write_spec()
    used = spied(monkeypatch)
    assert column.main("--top-up-parameters") == 0
    assert used and set(used) == {"whole"}, used
    scopes = traced_scopes(column.out / runner.TOPUP_TRACE_DIR)
    assert scopes["batch"] >= 1
    assert not scopes["own"] and not scopes["document"]


# ---------------------------------------------------------------------------
# AND the rows of a search follow the plan, AND a stop is a stop to the end
# ---------------------------------------------------------------------------

def test_the_rows_of_a_search_follow_the_plan_and_not_the_replies(monkeypatch):
    """Replies come back as the batches finish and the labels of a search are
    given in the order its rows are met, so the request for a document must not
    depend on which batch was quicker. Violating: the replies in the order they
    came back, which the same turns handed over reversed put the rows in."""
    world = World(monkeypatch, batches=3, axes=("carrier",), unstated=True,
                  retrieval=0, rest=3)
    harvest = world.harvester()
    answered = runner.harvest_batches(world.planned(), harvest.turn,
                                      workers=1, progress=False)
    world.answered = list(reversed(answered))
    assert harvest.search_document(world.answered)
    assert world.searches()
    assert all(c.values == (VALUE0, VALUE0 + 1, VALUE0 + 2)
               for c in world.searches()), [c.values for c in world.searches()]


def test_a_stop_that_comes_with_the_last_request_of_the_step_is_a_stop(
        monkeypatch):
    """A stop is seen between two requests, and one that comes while the last
    request of the step is out has no request after it to be seen by. The step
    must say it was cut all the same, because that request may be the one the
    server did not answer. Violating: the same document with no stop, which is
    finished."""
    halt = threading.Event()
    world = World(monkeypatch, batches=1, axes=("carrier",), unstated=True,
                  retrieval=0, rest=1, stop=halt)
    plain = world.make_asker

    def make_asker(*a, **kw):
        ask = plain(*a, **kw)

        def stopping(shown, rows, slots, *rest, **more):
            if not all(s.owner_kind == "table" for s in shown):
                halt.set()
            return ask(shown, rows, slots, *rest, **more)
        return stopping

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    world.run()
    assert len(world.searches()) == 1, "the stop came with the only request"
    assert world.finished is False

    calm = World(monkeypatch, batches=1, axes=("carrier",), unstated=True,
                 retrieval=0, rest=1, stop=threading.Event())
    calm.run()
    assert len(calm.searches()) == 1 and calm.finished is True


# ---------------------------------------------------------------------------
# AND what a search that rows wait on raises fails the document
# ---------------------------------------------------------------------------

def breaks_in_the_search_of(name: str):
    """A model whose own passages answer nothing and whose search of one
    coordinate raises."""
    def model(slot, rows, own):
        if slot.name == name and not own:
            raise RuntimeError("the search broke")
        return None
    return model


def test_a_search_that_rows_wait_on_fails_the_document_when_it_raises(
        monkeypatch):
    """The rows of both batches wait at the gate. In a batch's own sweep a
    raise there went into its turn and the batch was not read; the document
    step has no batch to fail, so the document is not finished and the caller
    does not write it. Violating: the same raise in the search of an axis
    nothing waits on, which finishes the document and leaves the coordinate
    `unanswered` while the other axis is still read to its end."""
    gated = World(monkeypatch, batches=2, axes=("quantity", "carrier"),
                  gate={"quantity": None},
                  model=breaks_in_the_search_of("quantity"))
    with pytest.raises(RuntimeError):
        gated.run()
    assert any(not c.own and "quantity" in c.slots for c in gated.calls)
    assert not any("carrier" in c.slots for c in gated.calls), (
        "nothing behind the gate was asked")

    free = World(monkeypatch, batches=2, axes=("carrier", "year"),
                 model=breaks_in_the_search_of("carrier"))
    free.run()
    assert free.finished is True
    assert {c["carrier_state"] for c in free.claims()} == {fields.UNANSWERED}
    assert any(not c.own and "year" in c.slots for c in free.calls), (
        "the search of the other axis went on")
