"""A run starts at the passages earlier harvests found something in, takes no
answer from them, and leaves every open coordinate to the search. Each promise
has a case that breaks it by construction beside the one that keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import fields, found, runner
from docpipe.extraction.pipeline import Row, Source, WorkItem
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
CARRIER = {slot.name: slot for slot in fields.axis_slots(
    SPEC.by_uri["energy_consumption"])}["carrier"]

TABLE, HEADING, OTHER = ("table", 5), ("section", 1), ("section", 2)


def passage(key, text="Text", at=None):
    return Source(key[0], key[1], text, {"document_id": 7,
                                         "section_number": at})


def stored_tuple(own=TABLE, **coordinates):
    return {"kind": "tuple", "provenance": {"owner_kind": own[0],
                                            "owner_id": own[1]},
            **coordinates}


READ_IN_HEADING = {"carrier_state": fields.READ,
                   "carrier_source": list(HEADING)}


def kept_of(*rows):
    kept = found.Kept()
    found.places_of(rows, kept)
    return kept


# -- what a found place is ---------------------------------------------------

def test_a_row_s_passage_and_where_its_coordinate_was_read_are_places():
    assert kept_of(stored_tuple(**READ_IN_HEADING)).passages == {TABLE, HEADING}


def test_a_coordinate_not_read_there_is_no_place():
    row = stored_tuple(carrier_state=fields.EXHAUSTED,
                       carrier_source=list(HEADING))
    assert kept_of(row).passages == {TABLE}


def test_a_refused_row_marks_its_passage():
    refused = {"kind": "refusal", "owner": list(TABLE), "claim": {}}
    assert kept_of(refused).passages == {TABLE}


def test_a_coordinate_is_filed_under_the_passage_of_its_row():
    assert kept_of(stored_tuple(**READ_IN_HEADING)).read_at == {
        "carrier": {TABLE: {HEADING}}}


# -- which harvests count ----------------------------------------------------

def harvest(directory, *rows, stamped=True, stamp=None):
    directory.mkdir(exist_ok=True)
    (directory / "plan.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    if stamped:
        (directory / "plan.stamp.json").write_text(json.dumps(stamp or {}),
                                                   encoding="utf-8")


def asked(*uris):
    """A stamp with the per-parameter keys of these parameters."""
    return {"slot/parameter": "x", **{f"parameter/{uri}": "x" for uri in uris}}


EVERY_BUT_BUILDINGS = [p.uri for p in SPEC.parameters
                       if p.uri != "building_count"]


def test_a_parameter_no_harvest_asked_is_gained(tmp_path):
    harvest(tmp_path / "a", stored_tuple(), stamp=asked(*EVERY_BUT_BUILDINGS))
    assert found_in(tmp_path / "a").gained(7, SPEC) == ["building_count"]


def test_a_parameter_one_harvest_asked_is_not_gained(tmp_path):
    harvest(tmp_path / "a", stored_tuple(), stamp=asked(*EVERY_BUT_BUILDINGS))
    harvest(tmp_path / "b", stored_tuple(own=OTHER),
            stamp=asked("building_count"))
    assert found_in(tmp_path / "a", tmp_path / "b").gained(7, SPEC) == []


def test_a_stamp_without_parameter_keys_gains_nothing(tmp_path):
    harvest(tmp_path / "a", stored_tuple())
    assert found_in(tmp_path / "a").gained(7, SPEC) == []


def found_in(*directories, holds=(TABLE, HEADING, OTHER)):
    every = [passage(key) for key in holds]
    return found.Found(directories, lambda _d: "plan", lambda _d, _x: every)


def keys(sources):
    return [(s.owner_kind, s.owner_id) for s in sources]


def test_the_places_of_two_harvests_add_up(tmp_path):
    harvest(tmp_path / "a", stored_tuple(own=TABLE))
    harvest(tmp_path / "b", stored_tuple(own=OTHER))
    assert keys(found_in(tmp_path / "a", tmp_path / "b").passages(7)) == \
        [TABLE, OTHER]


def test_an_unstamped_harvest_counts_for_nothing(tmp_path):
    harvest(tmp_path / "a", stored_tuple(), stamped=False)
    assert found_in(tmp_path / "a").passages(7) == []


def test_a_document_that_lost_a_place_has_no_places(tmp_path):
    harvest(tmp_path / "a", stored_tuple(**READ_IN_HEADING))
    known = found_in(tmp_path / "a", holds=(TABLE,))
    assert known.passages(7) == []
    assert known.read_at(7, ["carrier"]) == {}


# -- the plan ----------------------------------------------------------------

class Now:
    """A pool that runs what it is given."""
    @staticmethod
    def submit(function, *args, **kwargs):
        done = function(*args, **kwargs)
        return SimpleNamespace(result=lambda: done)


def plan_of(known, gained=None):
    searched, rest, excluded = [], [], []

    def plan(document_id, filename, frame=None, frame_index=0, only=()):
        searched.append(frame)
        report = runner.DocumentReport(document_id=document_id)
        items = [WorkItem(document_id, None, passage(key, "Text 2045"))
                 for key in (TABLE, OTHER)]
        return "plan", items, report, SPEC

    def rest_of_document(document_id, exclude):
        rest.append(document_id)
        excluded.append(set(exclude))
        return []

    def plan_known(document_id, filename):
        if not known:
            return None
        report = runner.DocumentReport(document_id=document_id, planned={
            found.STAGE: 1})
        item = WorkItem(document_id, None, passage(TABLE, "Text 2045"),
                        origin=found.STAGE)
        return "plan", [item], report, SPEC

    framed = []

    def ask_frame(sources, *_rest, **_kw):
        framed.extend(keys(sources))
        return {"status": "complete", "pairs": []}

    planned = runner.plan_batches(
        7, "plan.pdf", plan=plan, plan_pool=Now(), ask_frame=ask_frame,
        frame_axes=[SPEC_SLOT], more_sources=None, year_states={},
        anchor_texts={}, rest_of_document=rest_of_document,
        plan_known=plan_known, gained=gained)
    planned.excluded = excluded
    return planned, searched, rest, framed


SPEC_SLOT = SimpleNamespace(name="year", kind=fields.NUMBER, question="Jahr?")


def asked_in(batch):
    return sorted(p.uri for p in batch.spec.parameters)


def test_found_places_replace_every_search_of_the_plan():
    planned, searched, rest, framed = plan_of(known=True)
    assert searched == [] and rest == []
    assert set(framed) == {TABLE}
    assert [keys(b.sources) for b in planned.batches] == [[TABLE]]


def test_a_document_without_places_is_planned_as_in_any_run():
    planned, searched, rest, framed = plan_of(known=False)
    assert searched == [None] and rest == [7]
    assert set(framed) == {TABLE, OTHER}


def test_a_gained_parameter_is_searched_over_the_whole_plan():
    planned, searched, rest, _framed = plan_of(
        known=True, gained=lambda _d, _spec: ["building_count"])
    assert searched == [None] and rest == [7]
    assert [(keys(b.sources), asked_in(b)) for b in planned.batches] == [
        ([TABLE], sorted(p.uri for p in SPEC.parameters)),
        ([OTHER], ["building_count"])]
    assert TABLE in planned.excluded[0]


def test_no_gained_parameter_searches_nothing():
    planned, searched, rest, _framed = plan_of(
        known=True, gained=lambda _d, _spec: [])
    assert searched == [] and rest == []
    assert [keys(b.sources) for b in planned.batches] == [[TABLE]]


# -- the search --------------------------------------------------------------

def sweep_at(read_at, *, reads=None, own=TABLE, parents=()):
    asked = []

    def ask(shown, todo, slots, corrections, document_id, usage, owner_of,
            bases=None):
        asked.append(keys(shown))
        return (reads or {}).get(tuple(keys(shown)[-1])) or {
            "fields": {"carrier": {}}}

    source = passage(own, "| Erdgas | 120 | MWh/a |")
    batch = SimpleNamespace(document_id=7, bases=(), parameter=None,
                            items=[SimpleNamespace(source=source)],
                            sources=[source])
    rows = [Row(label="R1", item_index=0, claim={"value": 120})]
    searched = []

    def on_the_map(_document, _axes):
        searched.append(True)
        return []

    sweeper = runner.make_sweeper(
        ask, places=on_the_map, parents=lambda _s: list(parents),
        found=SimpleNamespace(read_at=lambda _d, _a: read_at))
    sweeping = runner.Sweeping(sweeper, runner.Scope([(batch, rows)]),
                               [CARRIER], "", seen=set(), held={},
                               kind="document")
    return sweeping, rows, asked, searched


def test_a_coordinate_read_at_its_found_place_is_searched_no_further(
        monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", None)
    quote = "Die Heizungen laufen mit Erdgas."
    reads = {HEADING: {"fields": {"carrier": {"answers": {"R1": {
        "value": "Erdgas", "value_raw": "Erdgas", "quote": quote}}}}}}
    place = passage(HEADING, quote)
    sweeping, rows, asked, searched = sweep_at({TABLE: [place]}, reads=reads)
    sweeping.search()
    assert rows[0].claim["carrier_window"][0] == found.STAGE
    assert rows[0].claim["carrier_source"] == list(HEADING)
    assert searched == []


def test_a_coordinate_still_open_goes_on_to_the_search(monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", None)
    place = passage(HEADING)
    sweeping, rows, asked, searched = sweep_at({TABLE: [place]})
    assert sweeping.search()
    assert asked[0][-1] == HEADING
    assert searched == [True]
    assert HEADING not in sweeping.seen


def test_a_coordinate_found_for_no_row_of_this_passage_asks_nothing_first(
        monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", None)
    sweeping, rows, asked, searched = sweep_at({OTHER: [passage(HEADING)]})
    sweeping.search()
    assert asked == []
    assert searched == [True]


def test_a_passage_the_batch_asked_already_is_not_asked_again(monkeypatch):
    monkeypatch.setattr(runner, "AHEAD", None)
    parent = passage(HEADING)
    sweeping, rows, asked, searched = sweep_at(
        {TABLE: [parent, passage(TABLE)]}, parents=[parent])
    sweeping.search()
    assert asked == []


# -- the stamp ---------------------------------------------------------------

def stamped(tmp_path, *passes):
    harvest(tmp_path, stored_tuple())
    (tmp_path / "plan.stamp.json").write_text(json.dumps(
        {"producers": [{"pass": p} for p in passes]}), encoding="utf-8")
    return tmp_path


def done(out, **kwargs):
    return runner.already_done("plan", out, "sha", **kwargs)


def not_stale(monkeypatch):
    monkeypatch.setattr(runner, "stale", lambda *_a: [])


def test_a_document_read_in_part_is_owed_to_a_whole_run(tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert not done(stamped(tmp_path, found.PASS))


def test_a_document_read_in_part_is_done_for_a_run_that_starts_there(
        tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert done(stamped(tmp_path, found.PASS), start_at=True)


def test_reading_the_rest_makes_it_whole(tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert done(stamped(tmp_path, found.PASS, "rest"))


def test_an_ordinary_harvest_is_done(tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert done(stamped(tmp_path, "harvest"))
