"""The run's one store of passage content (`runner.make_shared_content`).

What it promises: every thread of a run reads an owner's content once, and
gets what the database holds for it, and the store never holds more owners
than its bound. And the harvest's helpers read through the store they are
given, so a run that hands one store to all of them holds each owner once.
"""
import sqlite3
import threading

import pytest

from docpipe.extraction import runner
from docpipe.extraction.pipeline import Source
from docpipe.inference import db as inference_db


@pytest.fixture
def reads(monkeypatch):
    """Stand-in for the database read: counts reads per owner and gives back
    a content that names its owner. It takes a moment, as a read over the
    network does: without that one thread runs through every owner before the
    next is scheduled, and threads never miss the same owner together. Not
    time.sleep, which conftest turns into a no-op for every test."""
    counted: dict = {}
    lock = threading.Lock()
    moment = threading.Event()

    def fetch_owner_content(conn, owner_kind, owner_id):
        moment.wait(0.002)
        with lock:
            counted[(owner_kind, owner_id)] = counted.get(
                (owner_kind, owner_id), 0) + 1
        if owner_id < 0:                    # an owner the database lacks
            return None
        return {"owner_kind": owner_kind, "owner_id": owner_id,
                "title": "", "text": f"{owner_kind} {owner_id}",
                "page_number": 1, "image_path": None, "section_number": 1,
                "section_title": "", "document_id": 7}

    monkeypatch.setattr(inference_db, "fetch_owner_content",
                        fetch_owner_content)
    return counted


def test_threads_missing_the_same_owners_together_read_each_once(reads):
    fetch = runner.make_shared_content()
    owners = [("section", n) for n in range(40)]
    start = threading.Barrier(16)
    got: list = []

    def worker():
        start.wait()                        # all sixteen miss at once
        got.append([fetch(None, kind, n)["text"] for kind, n in owners])

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(reads.values()) == {1}
    assert len(reads) == 40
    # Every thread was given what the database holds, owner by owner.
    assert got == [[f"section {n}" for n in range(40)]] * 16


def test_the_old_store_per_thread_reads_once_per_thread(reads):
    """The case the shared store exists for, by construction: one
    `make_content_fetcher` per thread reads the same owner once per thread."""
    def worker():
        fetch = runner.make_content_fetcher()
        fetch(None, "section", 1)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert reads[("section", 1)] == 4


def test_an_owner_the_database_lacks_is_read_once_and_stays_missing(reads):
    fetch = runner.make_shared_content()
    assert fetch(None, "table", -1) is None
    assert fetch(None, "table", -1) is None
    assert reads[("table", -1)] == 1


def test_the_store_holds_no_more_owners_than_its_bound(reads):
    fetch = runner.make_shared_content(limit=3)
    for n in range(5):
        fetch(None, "section", n)
    # The oldest two went, the newest three stayed.
    for n in range(5):
        fetch(None, "section", n)
    assert [reads[("section", n)] for n in range(5)] == [2, 2, 2, 2, 2]
    for n in (2, 3, 4):
        fetch(None, "section", n)
    assert [reads[("section", n)] for n in (2, 3, 4)] == [2, 2, 2]


def test_bound_zero_keeps_every_owner(reads):
    fetch = runner.make_shared_content(limit=0)
    for _ in range(2):
        for n in range(10):
            fetch(None, "figure", n)
    assert set(reads.values()) == {1}


@pytest.fixture
def plans(tmp_path):
    """Two sections of one document, a table in the first."""
    path = tmp_path / "plans.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,"
        " section_number INTEGER);"
        "CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,"
        " page_number INTEGER);"
        "CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,"
        " page_number INTEGER);"
        "INSERT INTO Sections VALUES (11, 7, 1), (12, 7, 2);"
        "INSERT INTO Tables VALUES (21, 11, 1);")
    conn.commit()
    conn.close()
    return path


def test_the_helpers_read_through_the_store_they_are_given(reads, plans):
    """One store for the rest of the document, the parents and the owner
    sources: what one of them read, the others do not read again."""
    fetch = runner.make_shared_content()
    rest = runner.make_rest_of_document(plans, content=fetch)
    parents = runner.make_parents(plans, content=fetch)
    owner_sources = runner.make_owner_sources(plans, content=fetch)

    read = rest(7, set())
    assert [(s.owner_kind, s.owner_id) for s in read] == [
        ("section", 11), ("table", 21), ("section", 12)]
    table = Source(owner_kind="table", owner_id=21, text="t",
                   provenance={"parent_section": 11})
    assert [s.owner_id for s in parents([table])] == [11]
    assert set(owner_sources([("section", 12), ("table", 21)])) == {
        ("section", 12), ("table", 21)}
    assert reads == {("section", 11): 1, ("table", 21): 1, ("section", 12): 1}


def test_helpers_given_no_store_do_not_share_one(reads, plans):
    """Without a store handed in, each helper reads for itself: what main
    wires is what makes the run read once."""
    runner.make_rest_of_document(plans)(7, set())
    runner.make_owner_sources(plans)([("section", 11)])
    assert reads[("section", 11)] == 2
