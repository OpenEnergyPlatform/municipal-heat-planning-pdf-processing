"""Rolling document admission: harvest_documents keeps in_flight at a time."""
import threading
import time

from docpipe.extraction import runner


def _pause(seconds):
    """A real, timed block that (unlike time.sleep) survives the suite's
    autouse no-sleep patch: that patch replaces the shared time module's
    sleep, which time.sleep in this file would also pick up."""
    threading.Event().wait(seconds)


def test_never_more_than_in_flight_documents_run_at_once():
    """The pool is sized by in_flight, not by the document count. Nine
    documents at in_flight=3 must never let a fourth one in, and the ceiling
    has to actually be reached, not just never crossed by accident."""
    lock = threading.Lock()
    current = peak = 0

    def harvest_document(document_id, filename):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        _pause(0.03)
        with lock:
            current -= 1
        return True, 0

    documents = [(i, f"doc{i}") for i in range(9)]
    done, written, failures = runner.harvest_documents(
        documents, harvest_document, in_flight=3)

    assert peak == 3, f"only {peak} document(s) ever ran together"
    assert (done, written, failures) == (9, 9, 0)


def test_a_slow_document_does_not_hold_back_the_ones_admitted_after_it():
    """Not in groups: the moment a fast document is done the next one starts,
    even while the slow one from the same batch is still open. A group would
    have made documents 1-3 wait for document 0's release."""
    release_slow = threading.Event()
    doc3_finished = threading.Event()
    finished: list = []
    lock = threading.Lock()

    def harvest_document(document_id, filename):
        if document_id == 0:
            release_slow.wait(5)
        with lock:
            finished.append(document_id)
        if document_id == 3:
            doc3_finished.set()
        return True, 0

    documents = [(0, "slow"), (1, "fast-a"), (2, "fast-b"), (3, "fast-c")]
    result: dict = {}

    def run():
        result["value"] = runner.harvest_documents(
            documents, harvest_document, in_flight=2)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert doc3_finished.wait(5), (
            "document 3 never ran while document 0 was still open")
        with lock:
            # Documents 1-3 can only have run by using the one slot freed by
            # each other in turn, one after another, in submission order --
            # never by waiting for document 0, which is still blocked here.
            assert finished == [1, 2, 3], "the fast documents must finish first"
    finally:
        release_slow.set()
    thread.join(5)

    assert result["value"] == (4, 4, 0)
    assert finished == [1, 2, 3, 0], "the slow document held nobody back but itself"


def test_done_written_and_failures_add_up_across_documents():
    """Every document runs exactly once, and the three totals are the sum of
    what each one reported: a (False, n) counts as not written and adds n
    failures, a (True, n) is written and still adds its n failures."""
    outcomes = {0: (True, 0), 1: (False, 2), 2: (True, 1), 3: (False, 0),
                4: (True, 0)}
    calls: dict = {}
    lock = threading.Lock()

    def harvest_document(document_id, filename):
        with lock:
            calls[document_id] = calls.get(document_id, 0) + 1
        return outcomes[document_id]

    documents = [(i, f"doc{i}") for i in outcomes]
    done, written, failures = runner.harvest_documents(
        documents, harvest_document, in_flight=3)

    assert calls == {i: 1 for i in outcomes}, "a document ran more than once"
    assert done == len(outcomes)
    assert written == sum(1 for ok, _ in outcomes.values() if ok)
    assert failures == sum(n for _, n in outcomes.values())


def test_an_exception_in_one_document_counts_one_failure_and_the_rest_still_run():
    """A document that raises must not take the others down with it, and it
    still has to be counted: one failure, nothing written for it."""
    ran: set = set()
    lock = threading.Lock()

    def harvest_document(document_id, filename):
        if document_id == 1:
            raise RuntimeError("server gone")
        with lock:
            ran.add(document_id)
        return True, 0

    documents = [(0, "a"), (1, "b"), (2, "c"), (3, "d")]
    done, written, failures = runner.harvest_documents(
        documents, harvest_document, in_flight=2)

    assert ran == {0, 2, 3}, "the other documents must still have run"
    assert (done, written, failures) == (4, 3, 1)


def test_a_stop_returns_at_once_and_admits_nothing_new():
    """SIGTERM at the time limit. The call must not wait for the document
    still open, and nothing queued behind it may start either.

    Document 0 is the one left open; document 1 sets stop and returns right
    away, so the run only ever learns stop is set from a document that has
    already finished -- never from one still racing to start."""
    stop, release = threading.Event(), threading.Event()
    started: list = []
    lock = threading.Lock()

    def harvest_document(document_id, filename):
        with lock:
            started.append(document_id)
        if document_id == 0:
            release.wait(10)          # still open when stop fires
        else:
            stop.set()
        return True, 0

    documents = [(0, "a"), (1, "b"), (2, "c"), (3, "d")]
    began = time.monotonic()
    try:
        done, written, failures = runner.harvest_documents(
            documents, harvest_document, in_flight=2, stop=stop)
    finally:
        release.set()

    assert time.monotonic() - began < 5, "stop waited for the open document"
    assert started == [0, 1], "a document was admitted after stop was set"
    # Document 1 may or may not have been counted before stop cut the loop
    # off -- that depends on which of two checks notices stop first -- but
    # it was never a failure, and document 0 (still open) was never counted.
    assert failures == 0 and written == done and done <= 1


def test_halted_stops_admission_but_waits_for_the_open_documents():
    """halted() only stops new documents from starting; a document already
    running when it flips must still be waited for and counted."""
    halted_flag = threading.Event()
    slow_done = threading.Event()
    started: list = []
    lock = threading.Lock()

    def harvest_document(document_id, filename):
        with lock:
            started.append(document_id)
        if document_id == 0:
            _pause(0.1)                # still open when halted() flips
            slow_done.set()
        else:
            halted_flag.set()          # flips right away
        return True, 0

    documents = [(0, "a"), (1, "b"), (2, "c"), (3, "d")]
    done, written, failures = runner.harvest_documents(
        documents, harvest_document, in_flight=2,
        halted=halted_flag.is_set)

    assert slow_done.is_set(), "the open document was cancelled, not waited for"
    assert 2 not in started and 3 not in started, (
        "a document was admitted after halted() turned true")
    assert (done, written, failures) == (2, 2, 0)
