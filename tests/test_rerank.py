"""The reranker orders the best passages of each kind of a search
(owner decisions 2026-11-06 and 2026-11-08).

- Only the first RERANK_POOL passages of each kind are sent, AND the others
  follow them in the vector search's order.
- A passage's score is the best any search sentence gave it.
- A figure goes with its picture, any other passage as its text.
- A sentence and passage scored once in a document are not sent again.
"""
from types import SimpleNamespace

from docpipe import rules
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
    with rules.overlaid(rerank_drawn=0):            # the best only
        ordered = ranker.order(7, ["q"], found)
    assert [s.owner_id for s in ordered] == [2, 5, 1, 4, 3]
    sent = server.bodies[0]["documents"]
    assert "table 3" not in sent and len(sent) == 4


# Of each kind the reranker is given the best RERANK_POOL passages AND
# RERANK_DRAWN drawn at random from the places after them up to
# RERANK_DRAWN_FROM AND none beyond, the draw the same for the same document
# and sentences AND another for another sentence, all places where fewer are
# left AND none for a kind of 0, the reranker of the pieces draws none, AND
# the rest follow in the vector search's order (owner decision 2026-11-13:
# "30 plus 20 je Art", the same evening 15 plus 10). The numbers are read
# from the rules, so the promises hold whatever the standard is.

BEST, DRAWN, UPTO = (rules.get("rerank_pool"), rules.get("rerank_drawn"),
                     rules.get("rerank_drawn_from"))


def many(kind, start, count):
    return [source(kind, start + i) for i in range(count)]


def sent_ids(server) -> set:
    return {int(text.split()[1]) for body in server.bodies
            for text in body["documents"]}


def test_of_each_kind_the_best_and_some_drawn_from_the_places_up_to_the_last():
    tables, sections = many("table", 1, 150), many("section", 1001, 150)
    found = [s for pair in zip(tables, sections) for s in pair]
    server = Server({})
    ordered = rerank.Reranker(base_url="http://x", post=server).order(
        7, ["q"], found)
    for first in (1, 1001):
        got = {i - first for i in sent_ids(server)
               if first <= i < first + 150}
        assert len(got) == BEST + DRAWN             # the best and the drawn
        assert set(range(BEST)) <= got              # the best
        assert all(place < UPTO for place in got)   # none beyond the last
    # every score is equal: the pool keeps the vector order, the rest after
    sent = sent_ids(server)
    assert [s.owner_id for s in ordered] == \
        [s.owner_id for s in found if s.owner_id in sent] + \
        [s.owner_id for s in found if s.owner_id not in sent]


def test_the_draw_is_the_same_for_the_same_search_and_new_for_another():
    found = many("table", 1, 120)

    def drawn(document, probes):
        server = Server({})
        rerank.Reranker(base_url="http://x", post=server).order(
            document, probes, found)
        return sent_ids(server) - set(range(1, BEST + 1))

    first = drawn(7, ["a", "b"])
    assert len(first) == DRAWN
    assert drawn(7, ["b", "a"]) == first            # the same search
    assert drawn(7, ["a", "c"]) != first            # a new sentence
    assert drawn(8, ["a", "b"]) != first            # another document


def test_where_fewer_places_are_left_all_are_given_and_a_kind_of_0_none():
    server = Server({})
    few = BEST + DRAWN // 2                         # fewer left than drawn
    rerank.Reranker(base_url="http://x", post=server).order(
        7, ["q"], many("table", 1, few))
    assert sent_ids(server) == set(range(1, few + 1))
    server = Server({})
    with rules.overlaid(rerank_pool_by_kind={"table": 0}):
        rerank.Reranker(base_url="http://x", post=server).order(
            7, ["q"], many("table", 1, few) + many("section", 101, 3))
    assert sent_ids(server) == {101, 102, 103}      # no table at all


def test_the_reranker_of_the_pieces_draws_none():
    server = Server({})
    with rules.overlaid(rerank_chunk_pool=2):
        rerank.Reranker(base_url="http://x", post=server,
                        pool_rule="rerank_chunk_pool").order(
            7, ["q"], many("table", 1, 10))
    assert sent_ids(server) == {1, 2}


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
