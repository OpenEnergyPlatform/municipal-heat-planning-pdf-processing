"""The reranker orders the best passages of each kind of a search
(owner decisions 2026-11-06 and 2026-11-08).

- Only the first RERANK_POOL passages of each kind are sent, AND the others
  follow them in the vector search's order.
- A passage's score is the best any search sentence gave it.
- A figure goes with its picture, any other passage as its text.
- A sentence and passage scored once in a document are not sent again.
"""
from types import SimpleNamespace

from docpipe.inference import rerank


def source(kind, owner_id, text=""):
    return SimpleNamespace(owner_kind=kind, owner_id=owner_id,
                           text=text or f"{kind} {owner_id}")


class Server:
    """A /rerank that scores a passage by the table *by* (probe, text)."""

    def __init__(self, by):
        self.by = by
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        results = []
        for i, document in enumerate(body["documents"]):
            text = document if isinstance(document, str) else \
                document["content"][-1]["text"]
            results.append({"index": i, "relevance_score":
                            self.by.get((body["query"], text), 0.0)})
        return {"results": results, "usage": {"prompt_tokens": 3}}


def test_the_pool_is_reordered_and_the_rest_follows_unsent():
    found = [source("table", 1), source("table", 2), source("table", 3),
             source("section", 4), source("section", 5)]
    server = Server({("q", "table 2"): 0.9, ("q", "table 1"): 0.1,
                     ("q", "section 5"): 0.8})
    ranker = rerank.Reranker(base_url="http://x", pool=2, post=server)
    ordered = ranker.order(7, ["q"], found)
    assert [s.owner_id for s in ordered] == [2, 5, 1, 4, 3]
    sent = server.bodies[0]["documents"]
    assert "table 3" not in sent and len(sent) == 4


def test_a_passage_takes_the_best_score_of_any_sentence():
    found = [source("section", 1), source("section", 2)]
    server = Server({("a", "section 1"): 0.2, ("b", "section 1"): 0.95,
                     ("a", "section 2"): 0.5, ("b", "section 2"): 0.1})
    ranker = rerank.Reranker(base_url="http://x", pool=10, post=server)
    assert [s.owner_id for s in ranker.order(7, ["a", "b"], found)] == [1, 2]


def test_a_figure_goes_with_its_picture_and_a_table_as_text():
    picture = {"type": "image_url", "image_url": {"url": "data:image/png;x"}}
    found = [source("figure", 1), source("table", 2)]
    server = Server({})
    ranker = rerank.Reranker(
        base_url="http://x", pool=10, post=server,
        image_of=lambda s: picture if s.owner_kind == "figure" else None)
    ranker.order(7, ["q"], found)
    figure, table = server.bodies[0]["documents"]
    assert figure["content"][0] == picture
    assert table == "table 2"


def test_a_pair_scored_once_is_not_sent_again_in_its_document():
    found = [source("section", 1), source("section", 2)]
    server = Server({})
    ranker = rerank.Reranker(base_url="http://x", pool=10, post=server)
    ranker.order(7, ["q"], found)
    ranker.order(7, ["q"], found[1:])
    assert len(server.bodies) == 1
    ranker.order(8, ["q"], found[1:])
    assert len(server.bodies) == 2


# The rerankers of one run share their scores (plan of 2026-11-13, point 1):
# a pair is sent once for the document, whichever thread asks for it, AND
# two documents never share a score, AND a failed scoring leaves the pair to
# the thread that waits for it, AND a document's scores go when no reranker
# is on it any more.

def test_two_threads_asking_the_same_pair_send_it_once():
    import threading
    found = [source("section", 1)]
    entered, go = threading.Event(), threading.Event()
    inner = Server({("q", "section 1"): 0.7})

    def slow(body):
        entered.set()
        assert go.wait(5)
        return inner(body)

    store = rerank.Scores()
    first = rerank.Reranker(base_url="http://x", pool=10, post=slow,
                            store=store)
    second = rerank.Reranker(base_url="http://x", pool=10, post=inner,
                             store=store)
    got = []
    worker = threading.Thread(target=lambda: got.append(
        first.scores(7, "q", found)))
    worker.start()
    assert entered.wait(5)
    waiter = threading.Thread(target=lambda: got.append(
        second.scores(7, "q", found)))
    waiter.start()
    go.set()
    worker.join(5)
    waiter.join(5)
    assert got == [[0.7], [0.7]]
    assert len(inner.bodies) == 1


def test_two_documents_share_no_score():
    store = rerank.Scores()
    server = Server({})
    one = rerank.Reranker(base_url="http://x", pool=10, post=server,
                          store=store)
    two = rerank.Reranker(base_url="http://x", pool=10, post=server,
                          store=store)
    one.order(7, ["q"], [source("section", 1), source("section", 2)])
    two.order(8, ["q"], [source("section", 1), source("section", 2)])
    assert len(server.bodies) == 2


def test_a_failed_scoring_is_left_to_the_waiting_thread():
    import threading
    found = [source("section", 1)]
    entered, go = threading.Event(), threading.Event()
    good = Server({("q", "section 1"): 0.4})

    def broken(body):
        entered.set()
        assert go.wait(5)
        raise TimeoutError("timed out")

    store = rerank.Scores()
    first = rerank.Reranker(base_url="http://x", pool=10, post=broken,
                            store=store)
    second = rerank.Reranker(base_url="http://x", pool=10, post=good,
                             store=store)
    failed, got = [], []

    def ask_first():
        try:
            first.scores(7, "q", found)
        except TimeoutError:
            failed.append(True)

    worker = threading.Thread(target=ask_first)
    worker.start()
    assert entered.wait(5)
    waiter = threading.Thread(target=lambda: got.append(
        second.scores(7, "q", found)))
    waiter.start()
    go.set()
    worker.join(5)
    waiter.join(5)
    assert failed == [True] and got == [[0.4]] and len(good.bodies) == 1


def test_a_document_is_dropped_when_no_reranker_is_on_it():
    store = rerank.Scores()
    server = Server({})
    one = rerank.Reranker(base_url="http://x", pool=10, post=server,
                          store=store)
    two = rerank.Reranker(base_url="http://x", pool=10, post=server,
                          store=store)
    one.order(7, ["q"], [source("section", 1), source("section", 2)])
    two.order(7, ["q"], [source("section", 1), source("section", 2)])
    one.order(8, ["q"], [source("section", 1), source("section", 2)])
    assert 7 in store.scores
    two.order(8, ["q"], [source("section", 1), source("section", 2)])
    assert 7 not in store.scores and len(server.bodies) == 2
