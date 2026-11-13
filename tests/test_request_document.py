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

from docpipe.extraction import runner, scheduler

SPEC = runner.load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))


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


SAID = json.dumps({"phrase": "Der Plan nennt seinen Waermebedarf."})


# Promise: a search sentence written for one document is sent for that
# document, whichever thread asks for it; by construction, one asked from a
# thread of no document, and one asked for another document than the
# thread's own (owner decisions 2026-11-07 and 2026-11-09).
def test_a_search_sentence_is_sent_for_the_document_it_is_written_for(
        monkeypatch):
    documents = recording(monkeypatch, SAID, SAID, SAID)
    own, other = SPEC.parameters[0], SPEC.parameters[1]
    probes = runner.make_seek_probes(context_of=lambda document: {})
    with scheduler.on_behalf(None):
        assert probes(own, 4)
    with scheduler.on_behalf(8):
        assert probes(other, 8)
        assert probes(other, 9)
        after = scheduler.current()[0]
    assert documents == [4, 8, 9]
    assert after == 8
