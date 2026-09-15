"""The record a run leaves behind, so the next setting is measured not guessed.

Every knob this stage has was picked without a distribution at least once, and
every one of those picks was wrong: top_k, the window budget, the batch
threads. The text log cannot answer "at which rank was this found" or "in
which window did this close", because those are questions about a million
requests.
"""
import json

from docpipe.extraction import trace


def _open(tmp_path, names=None):
    trace.close()
    trace.ENABLED = True
    trace.open_trace(tmp_path, (names or {}).get)


def _lines(tmp_path, name):
    trace.flush()
    path = tmp_path / f"{name}.trace.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_an_event_lands_in_the_file_of_its_own_document(tmp_path):
    _open(tmp_path, {7: "plan_a", 8: "plan_b"})
    trace.event("plan", 7, rank=0, origin="structure")
    trace.event("plan", 8, rank=3, origin="retrieval")

    assert _lines(tmp_path, "plan_a") == [
        {"t": "plan", "doc": 7, "rank": 0, "origin": "structure"}]
    assert _lines(tmp_path, "plan_b")[0]["rank"] == 3
    trace.close()


def test_a_field_carrying_its_own_kind_does_not_collide_with_the_signature(
        tmp_path):
    """`kind` and `status` are event field names AND would-be parameters. The
    first version took them positionally and every error event raised."""
    _open(tmp_path, {7: "plan_a"})
    trace.event("error", 7, kind="unparsable", status=500, slot="year")
    row = _lines(tmp_path, "plan_a")[0]
    assert row == {"t": "error", "doc": 7, "kind": "unparsable",
                   "status": 500, "slot": "year"}
    trace.close()


def test_a_document_harvested_twice_does_not_leave_two_traces_in_one_file(
        tmp_path):
    """A trace holding both attempts cannot be counted without knowing which
    line belongs to which."""
    _open(tmp_path, {7: "plan_a"})
    trace.event("plan", 7, rank=0)
    trace.close()
    _open(tmp_path, {7: "plan_a"})
    trace.event("plan", 7, rank=1)
    assert [r["rank"] for r in _lines(tmp_path, "plan_a")] == [1]
    trace.close()


def test_an_unwritable_event_never_reaches_the_harvest(tmp_path):
    """A broken trace must not kill a run. It is a record, not a dependency."""
    _open(tmp_path, {7: "plan_a"})

    class Boom:
        def __repr__(self):
            raise RuntimeError("nope")

    trace.event("plan", 7, value=Boom())        # must not raise
    trace.event("plan", 7, rank=1)
    assert [r.get("rank") for r in _lines(tmp_path, "plan_a")] == [1]
    trace.close()


def test_switched_off_it_writes_nothing_at_all(tmp_path):
    trace.close()
    trace.ENABLED = False
    try:
        trace.open_trace(tmp_path, {7: "plan_a"}.get)
        trace.event("plan", 7, rank=0)
        assert not list(tmp_path.glob("*.trace.jsonl"))
    finally:
        trace.ENABLED = True
        trace.close()
