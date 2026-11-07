"""A request belongs to the document it is sent for, and only while it is
sent: a thread left belonging to a document would have a later request of
no document answered from that document's memory (`scheduler.Once`); and a
document that is done, written or not, has the answers kept for its
requests forgotten (`scheduler.read_out` in `harvest_documents`), owner
decision 2026-11-07.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import pipeline, runner, scheduler

SPEC = runner.load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))

ROW = "| Alt Zachun | 120 | 40 |"
TWICE = "| Bandenitz | 120 | 120 |"
NEXT = "| Belsch | 80 | 14 |"


def reply(content):
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=content))])


def recording(monkeypatch, *said):
    """A client that answers *said* in turn and notes the document each
    request was sent for; the run's trace stays shut."""
    told = iter(said)
    documents = []

    def create(**_request):
        documents.append(scheduler.current()[0])
        return reply(next(told))

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    return documents


def rows(*pairs):
    return json.dumps({"tuples": [
        {"source": "Q1", "values": values, "quote": quote}
        for values, quote in pairs], "status": "complete"})


# Promise: a rows request AND its second reading are sent for the batch's
# document, AND the thread belongs to no document afterwards; by
# construction, a number on two quoted rows, so the second reading is asked.
def test_a_rows_request_belongs_to_its_document_only_while_sent(monkeypatch):
    documents = recording(monkeypatch, rows(([120], f"{ROW}\n{TWICE}")),
                          rows(([120], ROW)))
    source = pipeline.Source(owner_kind="table", owner_id=1, provenance={},
                             text=f"{ROW}\n{NEXT}")
    batch = pipeline.Batch(5, None, [pipeline.WorkItem(1, None, source)])
    with scheduler.on_behalf(None):
        runner.make_harvester(spec=SPEC)(batch, [])
        after = scheduler.current()[0]
    assert documents == [5, 5]
    assert after is None


# Promise: a frame request is sent for its document AND leaves the thread
# belonging to the one it belonged to before; by construction, a thread that
# belonged to another document.
def test_a_frame_request_belongs_to_its_document_only_while_sent(monkeypatch):
    documents = recording(monkeypatch,
                          json.dumps({"pairs": [], "status": "complete"}))
    source = pipeline.Source(owner_kind="table", owner_id=1, provenance={},
                             text=f"{ROW}\n{NEXT}")
    with scheduler.on_behalf(9):
        runner.make_frame_asker()([source], runner.frame_slots_of(SPEC), 6)
        after = scheduler.current()[0]
    assert documents == [6]
    assert after == 9


# Promise: a document that is done has the answers to its requests
# forgotten, whether it was written or failed, so the same request sent for
# it again is sent; by construction, one document written and one that
# raised, each asked again after the run.
def test_a_document_done_forgets_its_answers_written_or_failed():
    sent = []

    def create(**_request):
        sent.append(scheduler.current()[0])
        return reply("{}")

    client = scheduler.repeating(SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), 60, 30)

    def ask(document):
        with scheduler.on_behalf(document):
            client.chat.completions.create(model="m", messages=[
                {"role": "user", "content": "the year of 4.367 MWh"}])

    def harvest_document(document_id, filename):
        ask(document_id)
        ask(document_id)                      # answered from memory
        if filename == "broken.pdf":
            raise RuntimeError("broken")
        return True, 0

    done, written, failures = runner.harvest_documents(
        [(1, "plan.pdf"), (2, "broken.pdf")], harvest_document, in_flight=2)
    assert (done, written, failures) == (2, 1, 1)
    assert sorted(sent) == [1, 2]
    ask(1)
    ask(2)
    assert sorted(sent) == [1, 1, 2, 2]
