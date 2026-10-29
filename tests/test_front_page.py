"""The parameters the profile names for the front are asked once more on their
own, in ONE request over the document's sections from its start, as many as
one request holds, besides wherever the harvest reads them; not when they are
not asked, and not in a pass over a stored harvest's unread passages. The
sections come in reading order, page by page, and the first always comes."""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import runner
from docpipe.extraction.pipeline import DocumentReport, Source, WorkItem
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))
TITLE = "Implications of Japan's 2030 target for long-term low emission pathways"
FRONT = ("publication_title", "publication_abstract")


def section(n, text):
    return Source("section", n, text, {"document_id": 7, "section_number": n})


class Pool:
    def submit(self, fn, *args, **kwargs):
        return SimpleNamespace(result=lambda: fn(*args, **kwargs))


def plan(document_id, filename, frame=None, frame_index=0, only=()):
    items = [WorkItem(document_id, None, section(99, "1 Introduction ..."),
                      origin="retrieval")]
    return "doc", items, DocumentReport(document_id=document_id), SPEC


def opening(document_id, max_sources, max_chars):
    # More than one request holds, so the front must stop at one.
    return [section(n, f"{TITLE}\nAbstract {n}")
            for n in range(max_sources + 3)]


def planned(**kwargs):
    return runner.plan_batches(
        7, "doc.pdf", plan=plan, plan_pool=Pool(), ask_frame=None,
        frame_axes=[], more_sources=None, year_states={}, anchor_texts={},
        front_page=opening, **kwargs)


def front_batches(result):
    return [b for b in result.batches
            if any(item.origin == "front" for item in b.items)]


def test_the_front_parameters_are_asked_on_their_own_in_one_request():
    result = planned(front_parameters=FRONT)
    front = front_batches(result)
    assert len(front) == 1
    assert [p.uri for p in front[0].spec.parameters] == list(FRONT)
    assert [item.source.owner_id for item in front[0].items] == \
        list(range(runner.BATCH_SOURCES))
    rest = [b for b in result.batches if b not in front]
    assert rest and all(len(b.spec.parameters) == len(SPEC.parameters)
                        for b in rest)


def test_no_front_request_without_the_parameter_or_over_read_passages():
    assert not front_batches(planned(front_parameters=()))
    assert not front_batches(planned(front_parameters=FRONT,
                                     only=("study_funder",)))
    assert not front_batches(planned(front_parameters=FRONT,
                                     already_read=frozenset({("section", 1)})))


def corpus(tmp_path, rows):
    db = tmp_path / "corpus.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Sections (id INTEGER, document INTEGER, "
                 "section_number INTEGER, page_number INTEGER)")
    conn.executemany("INSERT INTO Sections VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def test_the_opening_is_read_in_order_and_as_far_as_one_request_holds(tmp_path):
    db = corpus(tmp_path, [(10, 7, 2, 3), (11, 7, 1, 2), (12, 7, 0, 2),
                           (14, 7, 0, 4), (13, 8, 0, 1)])
    texts = {10: "x" * 30, 11: "x" * 30, 12: "x" * 30, 14: "x" * 30}

    def content(_conn, kind, owner_id):
        return {"text": texts[owner_id], "page_number": None}

    front_page = runner.make_front_page(db, content=content)
    every = front_page(7, 10, 10_000)
    assert [s.owner_id for s in every] == [12, 11, 10, 14]
    assert all(s.provenance.get("via") == "front" for s in every)
    assert [s.owner_id for s in front_page(7, 2, 10_000)] == [12, 11]
    assert [s.owner_id for s in front_page(7, 10, 60)] == [12, 11]
    # A first section longer than a request still comes, alone.
    assert [s.owner_id for s in front_page(7, 10, 5)] == [12]
