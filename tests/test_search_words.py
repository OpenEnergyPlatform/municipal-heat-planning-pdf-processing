"""
The search of the harvest asks the word index of the corpus beside the
vector search (owner decision 2026-11-17, from the literature on retrieval
over documents with text and tables: words and vectors together, reranked
once, find more than either).

The promises, each with a case that breaks it by construction:

1. The reranker's pool takes the passages the word index found besides the
   best of each kind and those it draws, AND none of these leaves for them,
   AND a hit that is no passage of the search adds nothing.
2. A search of the harvest asks the word index with each of its sentences
   in its own document, and the hits join the passages the reranker orders,
   as many as the rule `search_words` says, AND 0 asks no word index, AND
   without a reranker the two lists are merged by their places, AND a corpus
   without a current word index is searched by its vectors alone.
3. The event a word search writes in the trace ("words": its search, the
   places found, the time) is a record the published trace schema takes,
   AND a record with a key the schema does not name is refused.
"""
import sqlite3
from types import SimpleNamespace

import jsonschema
import pytest

from docpipe import rules
from docpipe.extraction import runner, schema
from docpipe.inference import lexical, query_cache, rerank


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in ("RERANK_BASE_URL", "RERANK_API_KEY", "RERANK_MODEL",
                 "RERANK_POOL", "RERANK_DRAWN", "RERANK_DRAWN_FROM"):
        monkeypatch.delenv(name, raising=False)
    rules.reset()
    yield
    rules.reset()


def passage(kind, owner_id):
    return SimpleNamespace(owner_kind=kind, owner_id=owner_id,
                           text=f"{kind} {owner_id}")


class Server:
    """A reranker server that scores a passage by the score *by* gives its
    text, and keeps what it was sent."""

    def __init__(self, by=None):
        self.by = by or {}
        self.sent: list = []

    def scored(self) -> list:
        """The texts it scored, each once (it is asked once a sentence)."""
        return sorted(set(self.sent))

    def __call__(self, body):
        texts = [d if isinstance(d, str) else d["content"][-1]["text"]
                 for d in body["documents"]]
        self.sent += texts
        return {"results": [{"index": i, "relevance_score":
                             self.by.get(text, 0.0)}
                            for i, text in enumerate(texts)],
                "usage": {"prompt_tokens": 1}}


FOUND = [passage("table", 1), passage("table", 2), passage("table", 3),
         passage("section", 4), passage("section", 5)]


def test_the_pool_takes_the_word_hits_beside_its_best():
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server)
    with rules.overlaid(rerank_pool=1, rerank_drawn=0):
        ranker.order(1, ["q"], FOUND,
                     also=[("table", 3), ("section", 5), ("figure", 9)])
    assert sorted(server.sent) == ["section 4", "section 5", "table 1",
                                   "table 3"]
    # Without hits the pool is the best of each kind alone.
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server)
    with rules.overlaid(rerank_pool=1, rerank_drawn=0):
        ranker.order(1, ["q"], FOUND)
    assert sorted(server.sent) == ["section 4", "table 1"]


# -- the search of the harvest ------------------------------------------------

VECTOR = [("section", n) for n in range(1, 31)]
WORDS = {("section", 30): "Endenergie Erdgas 2030 GWh/a",
         ("table", 40): "Endenergie Erdgas 2030 GWh/a nach Sektoren"}


def word_index():
    index = sqlite3.connect(":memory:")
    try:
        index.execute(
            'CREATE VIRTUAL TABLE "passages" USING fts5("title", "text", '
            '"owner_kind" UNINDEXED, "owner_id" UNINDEXED, '
            '"document" UNINDEXED, '
            "tokenize = 'unicode61 remove_diacritics 2')")
    except sqlite3.OperationalError:
        pytest.skip("this Python's SQLite has no FTS5")
    for (kind, owner), text in WORDS.items():
        index.execute('INSERT INTO "passages" VALUES (?, ?, ?, ?, ?)',
                      ("", text, kind, owner, 7))
    index.execute('INSERT INTO "passages" VALUES (?, ?, ?, ?, ?)',
                  ("", "Endenergie Erdgas 2030", "section", 99, 8))
    index.commit()
    return index


def content(conn, kind, owner):
    return {"owner_kind": kind, "owner_id": owner, "document_id": 7,
            "text": WORDS.get((kind, owner), f"{kind} {owner}")}


def searched(monkeypatch, tmp_path, *, index="words", ranker=None,
             **values):
    """The passages a search of document 7 hands back, best first, and the
    sentences the word index was asked."""
    db = tmp_path / "corpus.db"
    sqlite3.connect(db).close()
    cache = tmp_path / "query_cache.db"
    query_cache.connect(cache).close()

    def retrieve(probes, document_id, exclude, limit=None):
        return [runner._source_of(content(None, *key)) for key in VECTOR
                if key not in exclude]
    monkeypatch.setattr(runner, "make_retrieve",
                        lambda *a, **k: retrieve)
    asked: list = []
    words = word_index() if index == "words" else None

    def search(found, text, **kw):
        asked.append((text, kw.get("document")))
        return lexical_search(found, text, **kw)
    lexical_search = lexical.search
    monkeypatch.setattr(lexical, "search", search)
    monkeypatch.setattr(lexical, "connect", lambda db_path: words)
    more = runner.make_more_sources(db, None, {}, cache, content=content,
                                    reranker=ranker)
    with rules.overlaid(**values):
        found = more(7, ["Endenergie Erdgas 2030", "Erdgas GWh/a"], set())
    return [(s.owner_kind, s.owner_id) for s in found], asked


def test_the_word_hits_join_the_passages_the_reranker_orders(
        monkeypatch, tmp_path):
    server = Server(by={WORDS[("table", 40)]: 0.9})
    found, asked = searched(
        monkeypatch, tmp_path,
        ranker=lambda: rerank.Reranker(base_url="http://x", post=server),
        rerank_pool=2, rerank_drawn=0)
    # Each sentence asked in its own document; the hits of another
    # document are not taken.
    assert asked == [("Endenergie Erdgas 2030", 7), ("Erdgas GWh/a", 7)]
    assert ("section", 99) not in found
    # The table the vector search did not hand back and the section at its
    # place 30 are scored beside its two best, and the table comes first.
    assert server.scored() == sorted(
        ["section 1", "section 2", WORDS[("section", 30)],
         WORDS[("table", 40)]])
    assert found[0] == ("table", 40)
    # The break by construction: the rule at 0 asks no word index, and the
    # reranker scores the vector search's best alone.
    server.sent.clear()
    found, asked = searched(
        monkeypatch, tmp_path,
        ranker=lambda: rerank.Reranker(base_url="http://x", post=server),
        rerank_pool=2, rerank_drawn=0, search_words=0)
    assert asked == []
    assert server.scored() == ["section 1", "section 2"]
    assert ("table", 40) not in found


def test_the_rule_says_how_many_word_hits_join(monkeypatch, tmp_path):
    server = Server()
    searched(monkeypatch, tmp_path,
             ranker=lambda: rerank.Reranker(base_url="http://x",
                                            post=server),
             rerank_pool=2, rerank_drawn=0, search_words=1)
    assert len(server.scored()) == 3


def test_without_a_reranker_the_two_lists_are_merged_by_their_places(
        monkeypatch, tmp_path):
    found, _ = searched(monkeypatch, tmp_path)
    # Place 30 of the vectors and a word hit comes before place 1 of the
    # vectors alone; the table only the words found comes after it.
    assert found[:3] == [("section", 30), ("section", 1), ("table", 40)] \
        or found[:2] == [("section", 30), ("table", 40)]
    assert found.index(("table", 40)) < found.index(("section", 3))


def test_a_corpus_without_a_word_index_is_searched_by_its_vectors(
        monkeypatch, tmp_path):
    found, asked = searched(monkeypatch, tmp_path, index=None)
    assert asked == []
    assert found == VECTOR


def test_the_trace_schema_takes_the_event_of_the_word_search():
    record = {"t": "words", "doc": 7, "sid": 1,
              "places": [["table", 40], ["section", 30]], "ms": 3}
    jsonschema.validate(record, schema.trace_schema())
    # The break by construction: a key the schema does not name.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**record, "guessed": 1}, schema.trace_schema())
