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
