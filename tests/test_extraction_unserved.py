"""A 429 or a 5xx is not an answer, and a document is not finished over one.

Every loop treated a failure that carried an HTTP status as the model's: it
waited two seconds, tried twice more and gave up, and what it gave up on was
written down as a source the model had nothing to say about. The document was
stamped and a resume skipped it. A rate limit lifts and a server recovers, so
the same request asked later is answered; the hole was permanent anyway.

These run the real request loops against a client that answers with a status,
and the real document loop over the registry those loops write to.
"""
import json
import sqlite3
import types
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner, trace
from docpipe.extraction.pipeline import (DocumentReport, Source, WorkItem,
                                         group_items)
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
TEXT = "| Erdgas | 42.005 MWh/a |"


class Status(Exception):
    """What the client raises for a reply that is an HTTP status."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def _reply(content):
    return types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(
        finish_reason="stop",
        message=types.SimpleNamespace(content=content, reasoning_content=""))])


@pytest.fixture(autouse=True)
def _registry():
    runner.UNSERVED.clear()
    yield
    runner.UNSERVED.clear()


@pytest.fixture
def served(monkeypatch):
    """served(script) -> the requests made. *script* is one entry per
    request: an HTTP status to answer with, or the reply's content; the last
    entry repeats."""
    def install(script):
        calls: list = []

        class Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        step = script[min(len(calls), len(script) - 1)]
                        calls.append(kw)
                        if isinstance(step, int):
                            raise Status(step)
                        return _reply(step)

        monkeypatch.setattr(runner, "_client", lambda: Client())
        return calls
    return install


@pytest.fixture
def waits(monkeypatch):
    slept: list = []
    monkeypatch.setattr(runner.time, "sleep", lambda s=0, *a: slept.append(s))
    return slept


def _kwp():
    return load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(
            encoding="utf-8")))


def _batch():
    spec = _kwp()
    return group_items([WorkItem(7, spec.parameters[0], Source(
        "table", 1, TEXT, {"document_id": 7, "page": 3}))])[0]


# ---------------------------------------------------------------------------
# Which failure is whose
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [429, 500, 502, 503, 529])
def test_a_429_and_a_5xx_are_the_servers(status):
    assert runner.unserved(Status(status))
    assert runner.server_side(Status(status))


@pytest.mark.parametrize("status", [400, 401, 404, 413, 422])
def test_any_other_4xx_refuses_the_request_itself(status):
    assert not runner.unserved(Status(status))
    assert not runner.server_side(Status(status))


def test_a_request_that_never_arrived_is_the_servers_but_not_unserved():
    """It keeps the rule it had: more than half of a document's passages."""
    assert runner.server_side(ConnectionError("gone"))
    assert not runner.unserved(ConnectionError("gone"))


# ---------------------------------------------------------------------------
# The request loops
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [429, 503])
def test_a_passage_the_server_did_not_serve_is_named_as_that(status, served,
                                                             waits):
    """Asked as often as a server that is gone, on its curve: a 429 retried
    two seconds later is the same 429."""
    calls = served([status])
    reply = runner.make_harvester(None)(_batch(), [])
    assert reply["tuples"] == [{"_harvest_failed": True, "_why": "unserved",
                                "source": "Q1"}]
    attempts = runner.MAX_RETRIES + runner.CODE_ROUNDS
    assert len(calls) == attempts
    assert waits == [runner.retry_wait(n, True) for n in range(1, attempts)]
    assert waits[0] == runner.TRANSPORT_WAIT > runner.RETRY_WAIT


def test_a_passage_answered_after_a_429_is_an_answer(served, waits):
    calls = served([429, json.dumps({"tuples": [], "status": "complete"})])
    reply = runner.make_harvester(None)(_batch(), [])
    assert len(calls) == 2
    assert reply["tuples"] == [] and reply.get("status") == "complete"


def test_the_last_word_decides_what_a_passage_ended_on(served, waits):
    """A 429 and then replies nobody can read: the server did serve it, and
    the model had nothing usable to say. That is a harvest."""
    served([429, "kein JSON"])
    reply = runner.make_harvester(None)(_batch(), [])
    assert [t["_why"] for t in reply["tuples"]] == ["no_answer"]


def test_a_passage_that_never_arrived_keeps_its_own_name(monkeypatch, waits):
    """No HTTP status at all. It has its own rule for the stamp and its own
    part in the dead-server streak, and both read this word."""
    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise ConnectionError("gone")

    monkeypatch.setattr(runner, "_client", lambda: Client())
    reply = runner.make_harvester(None)(_batch(), [])
    assert [t["_why"] for t in reply["tuples"]] == ["unreachable"]
    assert waits and waits[0] == runner.TRANSPORT_WAIT


def test_a_refused_passage_stays_the_models_and_is_asked_once(served, waits):
    calls = served([400])
    reply = runner.make_harvester(None)(_batch(), [])
    assert [t["_why"] for t in reply["tuples"]] == ["no_answer"]
    assert len(calls) == 1 and waits == []


def _year():
    return fields.Slot(name="year", kind=fields.NUMBER,
                       question="Welches Jahr?")


@pytest.mark.parametrize("status,lost", [(429, 1), (500, 1), (400, 0)])
def test_a_coordinate_the_server_did_not_serve_is_counted_on_its_document(
        status, lost, served, waits):
    """The sweep that asked gets None either way, and cannot tell a request
    that was never served from a window that held nothing."""
    calls = served([status])
    assert runner.make_field_asker()([], [], _year(), None, 7) is None
    assert runner.UNSERVED.of(7) == lost
    assert len(calls) == (runner.MAX_RETRIES if lost else 1)
    assert runner.UNSERVED.of(8) == 0, "counted on its own document only"


def test_a_coordinate_answered_after_a_503_is_not_counted(served, waits):
    served([503, json.dumps({"answers": {}})])
    assert runner.make_field_asker()([], [], _year(), None, 7) == {
        "answers": {}}
    assert runner.UNSERVED.of(7) == 0


def test_a_coordinate_the_model_could_not_answer_is_not_counted(served,
                                                               waits):
    """A 503, then replies nobody can read until the attempts run out. The
    server did serve it; what is missing is the model's, as it always was."""
    calls = served([503, "kein JSON"])
    assert runner.make_field_asker()([], [], _year(), None, 7) is None
    assert len(calls) == runner.MAX_RETRIES
    assert runner.UNSERVED.of(7) == 0


def test_a_frame_and_a_sentence_the_model_could_not_write_are_not_counted(
        served, waits):
    spec = _kwp()
    served([429, "kein JSON"])
    shown = [Source("table", 1, TEXT, {"document_id": 7, "page": 3})]
    slots = fields.frame_slots(spec, ("scenario", "year"))
    assert runner.make_frame_asker()(shown, slots, 7) is None
    served([429, "kein JSON"])
    assert runner.document_anchor(spec, {"name": "Kassel"},
                                  document_id=7) == {}
    served([429, "kein JSON"])
    runner.make_anchors(spec)
    assert runner.UNSERVED.of(7) == 0 and runner.UNSERVED.of(None) == 0


def test_a_dead_server_is_seen_through_its_5xx(served, waits):
    """An engine that died answers every request with a 500. Sixty-four
    requests in a row never served are the same finding as sixty-four that
    never arrived."""
    served([500])
    streak, gave_up = runner.DeadStreak(2), []
    ask = runner.make_field_asker(dead=streak,
                                  on_give_up=lambda: gave_up.append(1))
    ask([], [], _year(), None, 7)
    assert gave_up == []
    ask([], [], _year(), None, 7)
    assert gave_up == [1]


def test_the_rows_pool_counts_unserved_passages_towards_the_streak():
    def unserved(batch, prior=None):
        return {"tuples": [{"_harvest_failed": True, "_why": "unserved",
                            "source": "Q1"}],
                "status": "failed", "need_more": []}

    items = [WorkItem(7, None, Source("table", i, f"| x | {i} |", {}))
             for i in range(6)]
    gave_up: list = []
    done = runner.harvest_batches(
        list(group_items(items, max_sources=1, max_chars=14000)), unserved,
        workers=1, dead=runner.DeadStreak(3),
        on_give_up=lambda: gave_up.append(1))
    assert gave_up == [1] and len(done) < 6


def test_a_frame_the_server_did_not_serve_is_counted_on_its_document(
        served, waits):
    spec = _kwp()
    served([429])
    shown = [Source("table", 1, TEXT, {"document_id": 7, "page": 3})]
    slots = fields.frame_slots(spec, ("scenario", "year"))
    assert runner.make_frame_asker()(shown, slots, 7) is None
    assert runner.UNSERVED.of(7) == 1


def test_a_refused_frame_is_asked_once_and_not_counted(served, waits):
    spec = _kwp()
    calls = served([400])
    shown = [Source("table", 1, TEXT, {"document_id": 7, "page": 3})]
    slots = fields.frame_slots(spec, ("scenario", "year"))
    assert runner.make_frame_asker()(shown, slots, 7) is None
    assert len(calls) == 1 and waits == [] and runner.UNSERVED.of(7) == 0


def _review(script, served):
    from docpipe.extraction import review
    spec = _kwp()
    parameter = spec.parameters[0]
    calls = served(script)
    row = {"parameter": parameter.uri, "value": 42005, "quote": TEXT,
           "provenance": {"owner_kind": "table", "owner_id": 1}}
    shown = [Source("table", 1, TEXT, {"document_id": 7, "page": 3})]
    reply = runner.make_review_asker()(
        row, shown, parameter, review.review_fields(parameter, []))
    return reply, calls


def test_a_refused_review_is_asked_once(served, waits):
    reply, calls = _review([400], served)
    assert reply is None and len(calls) == 1 and waits == []


@pytest.mark.parametrize("status", [429, 503])
def test_a_review_the_server_did_not_serve_is_asked_again(status, served,
                                                          waits):
    """Nothing is counted for it: a row without a review flag is asked again
    by the next review. It is asked as often as the others, on their curve."""
    reply, calls = _review([status], served)
    assert reply is None and len(calls) == runner.MAX_RETRIES
    assert waits == [runner.retry_wait(n, True)
                     for n in range(1, runner.MAX_RETRIES)]


def test_a_search_sentence_the_server_did_not_serve_is_counted(served, waits):
    spec = _kwp()
    served([503])
    out = runner.document_anchor(spec, {"name": "Kassel"}, document_id=7)
    assert out == {}
    assert runner.UNSERVED.of(7) == len(spec.parameters)
    assert set(waits) == {runner.retry_wait(n, True)
                          for n in range(1, runner.MAX_RETRIES)}, (
        "a 429 or a 5xx waits like a server that is not there")


def test_the_runs_own_anchors_are_counted_under_no_document(served, waits):
    served([429])
    runner.make_anchors(_kwp())
    assert runner.UNSERVED.of(None) > 0 and runner.UNSERVED.of(7) == 0
    assert set(waits) == {runner.retry_wait(n, True)
                          for n in range(1, runner.MAX_RETRIES)}


# ---------------------------------------------------------------------------
# The stamp
# ---------------------------------------------------------------------------

def _report(whys):
    report = DocumentReport(document_id=7)
    report.owners_harvested = len(whys)
    report.refusals = [
        {"parameter": "p", "reason": "value is not a number",
         "claim": {"_harvest_failed": True, "_why": why},
         "owner": ["section", i]} for i, why in enumerate(whys) if why]
    return report


def test_one_unserved_passage_withholds_the_stamp(tmp_path, monkeypatch):
    """One, not more than half. A passage that never reached a server that
    is gone is one of many the same outage took; a 429 on one request says
    nothing about the others, and the hole it leaves is one a resume fills."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    runner.finish_document(_report(["unserved", None, None, None]), "ein",
                           tmp_path, "sha")
    assert (tmp_path / "ein.jsonl").is_file(), "what was read is written"
    assert not (tmp_path / "ein.stamp.json").exists()

    runner.finish_document(_report(["no_answer", None, None, None]), "stumm",
                           tmp_path, "sha")
    assert (tmp_path / "stumm.stamp.json").is_file()


def test_an_unserved_request_of_any_kind_withholds_the_stamp(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    assert runner.finish_document(_report([None, None]), "feld", tmp_path,
                                  "sha", lost=1) is False
    assert (tmp_path / "feld.jsonl").is_file()
    assert not (tmp_path / "feld.stamp.json").exists()
    assert runner.finish_document(_report([None, None]), "ganz", tmp_path,
                                  "sha") is True
    assert (tmp_path / "ganz.stamp.json").is_file()


def test_a_passage_that_never_arrived_keeps_its_rule(tmp_path, monkeypatch):
    """More than half of a document's passages, as before."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    half = ["unreachable", "unreachable", None, None]
    assert runner.finish_document(_report(half), "halb", tmp_path, "sha")
    most = ["unreachable", "unreachable", "unreachable", None]
    assert not runner.finish_document(_report(most), "mehr", tmp_path, "sha")
    assert not (tmp_path / "mehr.stamp.json").exists()


@pytest.mark.parametrize("why", ["lost", "unreachable", "silent"])
def test_a_withheld_stamp_takes_the_earlier_one_with_it(tmp_path, monkeypatch,
                                                        why):
    """A document harvested before and harvested again by force. The file is
    rewritten either way; the stamp of the first harvest vouched for the
    file that is gone, and left in place it had the next run call the
    document current and skip it."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    assert runner.finish_document(_report([None, None]), "plan", tmp_path,
                                  "sha")
    assert runner.already_done("plan", tmp_path, "sha")

    report, extra = {
        "lost": (_report([None, None]), {"lost": 1}),
        "unreachable": (_report(["unreachable"] * 3), {}),
        "silent": (_report([None, None]), {"answered": 0}),
    }[why]
    assert runner.finish_document(report, "plan", tmp_path, "sha",
                                  **extra) is False
    assert not (tmp_path / "plan.stamp.json").exists()
    assert not runner.already_done("plan", tmp_path, "sha"), (
        "a resume harvests it again, as the log line says")


def test_the_one_document_path_withholds_the_stamp_as_well(tmp_path,
                                                           monkeypatch):
    """`run_document`, which a caller outside the run's own loop uses."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    spec = _kwp()
    lose = [1]

    def retrieve(probes, document_id, exclude):
        return [] if ("table", 1) in exclude else [
            Source("table", 1, TEXT, {"document_id": 7, "page": 3})]

    def harvest(batch, prior=None):
        for _ in range(lose[0]):
            runner.UNSERVED.note(batch.document_id)
        return {"tuples": [], "status": "complete", "need_more": []}

    args = (7, "plan", tmp_path, spec, "sha", ["{label}"],
            {"retrieve": retrieve, "harvest": harvest})
    assert runner.run_document(*args) is False
    assert (tmp_path / "plan.jsonl").is_file()
    assert not (tmp_path / "plan.stamp.json").exists()

    runner.UNSERVED.clear()         # the next run
    lose[0] = 0
    assert runner.run_document(*args) is True
    assert (tmp_path / "plan.stamp.json").is_file()


# ---------------------------------------------------------------------------
# The document loop
# ---------------------------------------------------------------------------

RUN = "EN_NPi2100"
PASSAGE = ("The Current Policies scenario (CurPol) is reported here for "
           "Germany in 2030 and 2050.")


@pytest.fixture
def corpus_run(monkeypatch, tmp_path):
    """(database, output directory, harvests made) for `runner.main` over one
    publication, with everything that is a server, an index or a card
    stubbed. `lose[0]` is how many coordinates of the next harvest end on a
    503."""
    from docpipe.inference import faiss_store
    db = tmp_path / "corpus.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                is_current INTEGER DEFAULT 1);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               content TEXT);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             markdown TEXT, caption TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             description TEXT, caption TEXT);
        CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,
                                name TEXT);
        CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);
        INSERT INTO Documents VALUES (1, 'a.pdf', 1);
        INSERT INTO Scenarios VALUES (10, 900, 'EN_NPi2100');
        INSERT INTO DocumentScenarios VALUES (1, 10);
    """)
    conn.execute("INSERT INTO Sections VALUES (10, 1, ?)", (PASSAGE,))
    conn.commit()
    conn.close()

    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    monkeypatch.setenv("EXTRACT_ANCHORS", "0")
    monkeypatch.setattr(runner, "ATTACH_IMAGES", False)
    monkeypatch.setattr(runner, "BATCH_SOURCES", runner.BATCH_SOURCES)
    monkeypatch.setattr(runner, "assert_serving", lambda *a, **k: 40960)
    monkeypatch.setattr(runner, "set_model_len", lambda n: None)
    monkeypatch.setattr(runner, "start_limit", lambda: None)
    monkeypatch.setattr(runner, "watch_server", lambda *a, **k: None)
    monkeypatch.setattr(runner, "install_stop_handler", lambda: None)
    monkeypatch.setattr(runner, "prime_probe_cache", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "make_more_sources",
                        lambda *a, **k: (lambda *x: []))
    monkeypatch.setattr(runner, "make_rest_of_document", lambda *a, **k: None)
    monkeypatch.setattr(runner, "make_parents", lambda *a, **k: None)
    monkeypatch.setattr(runner, "make_structure",
                        lambda *a, **k: (lambda d: []))
    monkeypatch.setattr(faiss_store, "load_global_index",
                        lambda p: (None, {}))
    monkeypatch.setattr(runner, "FIELDWISE", True)
    monkeypatch.setattr(runner, "fit_batch_sources", lambda *a, **k: 1)
    monkeypatch.setattr(runner, "LLM_PARALLEL", 1)

    def make_retrieve(conn, index, id_to_pos, cache_conn, fetch, limit=0):
        return lambda probes, document_id, exclude: [Source(
            "section", 10, PASSAGE,
            {"document_id": document_id, "page": 1, "title": "Scenarios"})]

    harvests: list = []
    lose = [0]

    def make_fieldwise(*a, **k):
        def harvest(batch, prior=None):
            harvests.append(batch.document_id)
            for _ in range(lose[0]):
                # What the field request does when its last attempt is a 503.
                runner.UNSERVED.note(batch.document_id)
            return {"tuples": [
                {"source": batch.label(0), "parameter": "scenario_label",
                 "value": RUN, "value_raw": "Current Policies",
                 "quote": "The Current Policies scenario (CurPol)"}],
                "status": "complete", "need_more": []}
        return harvest

    monkeypatch.setattr(runner, "make_retrieve", make_retrieve)
    monkeypatch.setattr(runner, "make_fieldwise_harvester", make_fieldwise)
    yield db, tmp_path / "out", harvests, lose
    trace.close()


def _main(db, out, tmp_path):
    return runner.main([str(db), "no.index", str(out), "--image-root",
                        str(tmp_path), "--document", "1"])


def test_a_document_with_an_unserved_request_is_harvested_again(tmp_path,
                                                                corpus_run):
    """The run that lost a coordinate writes what it read and no stamp. The
    next run harvests the document again and stamps it, and the one after
    that leaves it alone."""
    db, out, harvests, lose = corpus_run
    lose[0] = 1
    assert _main(db, out, tmp_path) == 1, (
        "a run that leaves a document for the next one did not finish")
    assert harvests == [1]
    assert (out / "a.jsonl").is_file(), "what was read is written"
    assert not (out / "a.stamp.json").exists()

    lose[0] = 0
    assert _main(db, out, tmp_path) == 0
    assert harvests == [1, 1], "a resume harvests it again"
    assert (out / "a.stamp.json").is_file(), (
        "and the first run's count is not carried into the second")

    assert _main(db, out, tmp_path) == 0
    assert harvests == [1, 1], "stamped, so left alone"


def test_a_forced_run_that_loses_a_request_is_not_hidden_by_the_old_stamp(
        tmp_path, corpus_run):
    db, out, harvests, lose = corpus_run
    assert _main(db, out, tmp_path) == 0
    assert (out / "a.stamp.json").is_file()

    lose[0] = 1
    assert runner.main([str(db), "no.index", str(out), "--image-root",
                        str(tmp_path), "--document", "1", "--force"]) == 1
    assert not (out / "a.stamp.json").exists()

    lose[0] = 0
    assert _main(db, out, tmp_path) == 0
    assert harvests == [1, 1, 1], "the plain run after it harvests it again"
    assert (out / "a.stamp.json").is_file()


def test_a_lost_search_sentence_leaves_its_document_unstamped(
        tmp_path, monkeypatch, corpus_run):
    """The plan asks for the sentences a document is searched with. One that
    ended on a 503 is a search that was not made, on this document."""
    db, out, _harvests, _lose = corpus_run
    served = [False]

    def document_anchor(spec, context=None, client=None, prompt=None,
                        frame=None, document_id=None):
        if not served[0]:
            runner.UNSERVED.note(document_id)
        return {}

    monkeypatch.setattr(runner, "document_anchor", document_anchor)
    _main(db, out, tmp_path)
    assert (out / "a.jsonl").is_file()
    assert not (out / "a.stamp.json").exists()

    served[0] = True
    assert _main(db, out, tmp_path) == 0
    assert (out / "a.stamp.json").is_file()


def test_nothing_is_harvested_without_the_anchors_the_server_did_not_serve(
        tmp_path, monkeypatch, corpus_run, caplog):
    """The anchors are the run's, not a document's: every document would be
    searched without them and stamped as if it had been searched with them."""
    db, out, harvests, _lose = corpus_run
    monkeypatch.setenv("EXTRACT_ANCHORS", "1")

    def make_anchors(spec, client=None, *, store=None, key=""):
        runner.UNSERVED.note(None)
        return {}

    monkeypatch.setattr(runner, "make_anchors", make_anchors)
    with caplog.at_level("ERROR", logger=runner.log.name):
        assert _main(db, out, tmp_path) == 1
    assert harvests == []
    assert not list(out.glob("*.stamp.json"))
    assert any("429 or a 5xx" in r.getMessage() for r in caplog.records)
