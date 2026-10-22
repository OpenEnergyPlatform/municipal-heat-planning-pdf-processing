"""A parameter the profile names for the first page is asked once more on its
own, over the sections of that page and nothing else, besides wherever the
harvest reads it; not when it is not asked, and not in a pass over a stored
harvest's unread passages. The first page is the lowest page a section stands
on, its sections in their order."""
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


def section(n, text):
    return Source("section", n, text, {"document_id": 7, "section_number": n})


class Pool:
    def submit(self, fn, *args, **kwargs):
        return SimpleNamespace(result=lambda: fn(*args, **kwargs))


def plan(document_id, filename, frame=None, frame_index=0, only=()):
    items = [WorkItem(document_id, None, section(9, "1 Introduction ..."),
                      origin="retrieval")]
    return "doc", items, DocumentReport(document_id=document_id), SPEC


def planned(**kwargs):
    return runner.plan_batches(
        7, "doc.pdf", plan=plan, plan_pool=Pool(), ask_frame=None,
        frame_axes=[], more_sources=None, year_states={}, anchor_texts={},
        front_page=lambda document_id: [section(2, f"{TITLE}\nKen Oshiro")],
        **kwargs)


def front_batches(result):
    return [b for b in result.batches
            if any(item.origin == "front" for item in b.items)]


def test_the_title_is_asked_on_its_own_over_the_first_page():
    result = planned(front_parameters=("publication_title",))
    front = front_batches(result)
    assert len(front) == 1
    assert [p.uri for p in front[0].spec.parameters] == ["publication_title"]
    assert [item.source.owner_id for item in front[0].items] == [2]
    rest = [b for b in result.batches if b not in front]
    assert rest and all(len(b.spec.parameters) == len(SPEC.parameters)
                        for b in rest)


def test_no_front_request_without_the_parameter_or_over_read_passages():
    assert not front_batches(planned(front_parameters=()))
    assert not front_batches(planned(front_parameters=("publication_title",),
                                     only=("study_funder",)))
    assert not front_batches(planned(front_parameters=("publication_title",),
                                     already_read=frozenset({("section", 1)})))


def test_the_first_page_is_the_lowest_page_with_a_section_in_its_order(tmp_path):
    db = tmp_path / "corpus.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Sections (id INTEGER, document INTEGER, "
                 "section_number INTEGER, page_number INTEGER)")
    conn.executemany("INSERT INTO Sections VALUES (?, ?, ?, ?)",
                     [(10, 7, 2, 3), (11, 7, 1, 2), (12, 7, 0, 2),
                      (13, 8, 0, 1)])
    conn.commit()
    conn.close()

    def content(_conn, kind, owner_id):
        return {"text": f"text {owner_id}", "page_number": None}

    front = runner.make_front_page(db, content=content)(7)
    assert [s.owner_id for s in front] == [12, 11]
    assert all(s.provenance.get("via") == "front" for s in front)
