"""
The search of the harvest asks the page index of the corpus beside the vector
search and the word index (owner decision 2026-11-17, from the literature on
searching the page image directly: ColPali 2024, Nemotron ColEmbed V2 2026).

The promises, each with a case that breaks it by construction:

1. The passages that stand on the pages the page index finds join the
   passages the reranker orders, AND a passage that spans pages stands on
   each of them, AND one that stands on no found page does not join; without
   a reranker the lists are merged by their places.
2. The rule `search_pages` says how many pages are asked, AND 0 asks no page
   index.
3. A corpus without a current page index is searched without it and nothing
   changes, AND the log says so once per run, not per request.
4. The page index is stale when the model, the render size or the documents
   of the corpus differ from what it was built with, AND a current one finds
   the page whose vector lies closest.
5. The build skips a document without a PDF and says so, AND refuses an
   embedder that takes text only, AND never writes into the corpus database.
6. The command is registered beside `lexical`.
7. The event a page search writes in the trace ("pages") is a record the
   published trace schema takes, AND a record with a key it does not name is
   refused.
"""
import importlib.util
import logging
import sqlite3
from types import SimpleNamespace

import jsonschema
import numpy as np
import pytest

from docpipe import cli, rules
from docpipe.extraction import runner, schema
from docpipe.inference import pages, query_cache, rerank
from docpipe.store import schema as store_schema

from test_search_words import Server, content, VECTOR


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in ("RERANK_BASE_URL", "RERANK_API_KEY", "RERANK_MODEL",
                 "RERANK_POOL", "RERANK_DRAWN", "RERANK_DRAWN_FROM"):
        monkeypatch.delenv(name, raising=False)
    rules.reset()
    yield
    rules.reset()


# -- a small corpus ---------------------------------------------------------

def corpus(tmp_path, pdfs=("a.pdf",), pages_of=3):
    """A corpus database of document 7 (and 8, if named) with sections,
    tables and figures on pages 1 to *pages_of*: section 41 on page 3,
    section 43 spanning pages 3 and 4, table 42 on page 3 by its own page
    number, table 44 on page 4 and standing on page 3 by its segment, figure
    45 on page 1."""
    path = tmp_path / "corpus.db"
    conn = store_schema.connect(path)
    for n, name in enumerate(pdfs):
        doc = 7 + n
        conn.execute('INSERT INTO "Documents" ("id", "filename", "sha256", '
                     '"bytes", "num_pages") VALUES (?, ?, ?, ?, ?)',
                     (doc, name, "x" * 8, 10, pages_of))
        for number in range(1, pages_of + 2):
            conn.execute('INSERT INTO "Pages" ("id", "document", '
                         '"page_number") VALUES (?, ?, ?)',
                         (doc * 100 + number, doc, number))
    for sid, number in ((41, 3), (43, 3), (46, 1)):
        conn.execute('INSERT INTO "Sections" ("id", "document", '
                     '"section_number", "page_number") VALUES (?, 7, ?, ?)',
                     (sid, sid, number))
    conn.execute('INSERT INTO "SectionPages" VALUES (43, 703)')
    conn.execute('INSERT INTO "SectionPages" VALUES (43, 704)')
    conn.execute('INSERT INTO "Tables" ("id", "section", "block_id", "path", '
                 '"page_number") VALUES (42, 41, "t1", "p", 3)')
    conn.execute('INSERT INTO "Tables" ("id", "section", "block_id", "path", '
                 '"page_number") VALUES (44, 43, "t2", "p", 4)')
    conn.execute('INSERT INTO "Segments" ("section", "ordinal", "page", '
                 '"kind", "ref") VALUES (43, 1, 703, "table", "t2")')
    conn.execute('INSERT INTO "Images" ("id", "section", "block_id", "path", '
                 '"page_number") VALUES (45, 46, "f1", "p", 1)')
    conn.commit()
    conn.close()
    return path


def test_the_passages_that_stand_on_a_page_are_found_by_every_page_they_span(
        tmp_path):
    db = sqlite3.connect(corpus(tmp_path))
    on_3 = pages.passages_on(db, 7, [3])
    # Sections first, then tables; the spanning section, and the table
    # whose own page is 4 but whose segment is on page 3.
    assert on_3 == [("section", 41), ("section", 43), ("table", 42),
                    ("table", 44)]
    # The spanning section stands on page 4 as well, listed once.
    assert pages.passages_on(db, 7, [4, 3]).count(("section", 43)) == 1
    assert ("section", 43) in pages.passages_on(db, 7, [4])
    # By construction: a page no passage stands on finds none, and a
    # passage of another page is not found.
    assert pages.passages_on(db, 7, [2]) == []
    assert ("figure", 45) not in on_3
    assert pages.passages_on(db, 7, [1]) == [("section", 46),
                                             ("figure", 45)]


# -- the search of the harvest ----------------------------------------------

class Rows:
    """The vectors of a page index: page n of document 7 is the unit vector
    n - 1 of four."""

    def reconstruct(self, vector):
        return np.eye(4, dtype=np.float32)[vector]


def stub_index():
    return pages.PageIndex(Rows(), {7: [(n, n - 1) for n in range(1, 5)]})


def searched(monkeypatch, tmp_path, *, index="pages", ranker=None,
             sentences=("p1",), **values):
    """(the passages a search of document 7 hands back, the page index it
    asked, the number of times a page index was opened)."""
    tmp_path = tmp_path / f"run{len(list(tmp_path.iterdir()))}"
    tmp_path.mkdir()
    db = corpus(tmp_path)
    cache = tmp_path / "query_cache.db"
    query_cache.connect(cache).close()

    def retrieve(probes, document_id, exclude, limit=None):
        return [runner._source_of(content(None, *key)) for key in VECTOR
                if key not in exclude]
    asked: list = []
    # Every sentence is the unit vector of page 3.
    retrieve.vectors = lambda probes: [[0.0, 0.0, 1.0, 0.0]
                                       for _ in probes]
    monkeypatch.setattr(runner, "make_retrieve", lambda *a, **k: retrieve)
    held = stub_index() if index == "pages" else None
    opened: list = []

    def connect(db_path, *a, **k):
        opened.append(db_path)
        return held
    monkeypatch.setattr(pages, "connect", connect)
    if held is not None:
        original = held.search

        def search(*a, **k):
            result = original(*a, **k)
            asked.append(result)
            return result
        monkeypatch.setattr(held, "search", search)
    # A search of the words does not run: no word index.
    from docpipe.inference import lexical
    monkeypatch.setattr(lexical, "connect", lambda db_path: None)

    def shared(conn, kind, owner):
        return {"owner_kind": kind, "owner_id": owner, "document_id": 7,
                "text": f"{kind} {owner}"}
    more = runner.make_more_sources(db, None, {}, cache, content=shared,
                                    reranker=ranker)
    with rules.overlaid(**values):
        out = []
        for _ in range(2):
            out = more(7, list(sentences), set())
    return [(s.owner_kind, s.owner_id) for s in out], asked, opened


def reranker(server):
    return lambda: rerank.Reranker(base_url="http://x", post=server)


def test_the_passages_on_the_best_pages_join_the_reranker(monkeypatch,
                                                          tmp_path):
    server = Server(by={"table 44": 0.9})
    found, asked, _ = searched(monkeypatch, tmp_path,
                               ranker=reranker(server), rerank_pool=2,
                               rerank_drawn=0, search_pages=1)
    # Page 3 is the best page; its four passages are scored beside the
    # two best of the vector search, the table first.
    assert asked[0] == [3]
    assert {"section 41", "section 43", "table 42", "table 44"} \
        <= set(server.scored())
    assert found[0] == ("table", 44)
    # A passage that stands on no found page does not join.
    assert ("figure", 45) not in found
    # By construction: without the page index the reranker never sees them.
    server = Server(by={"table 44": 0.9})
    found, asked, _ = searched(monkeypatch, tmp_path,
                               ranker=reranker(server), rerank_pool=2,
                               rerank_drawn=0, search_pages=1, index=None)
    assert "table 44" not in server.scored()
    assert ("table", 44) not in found


def test_without_a_reranker_the_lists_are_merged_by_their_places(
        monkeypatch, tmp_path):
    found, _, _ = searched(monkeypatch, tmp_path, search_pages=1)
    assert ("table", 44) in found
    # The vector search's own places are kept (nothing leaves).
    assert all(key in found for key in VECTOR)


def test_the_rule_says_how_many_pages_are_asked(monkeypatch, tmp_path):
    _, asked, _ = searched(monkeypatch, tmp_path, search_pages=2)
    assert len(asked[0]) == 2 and asked[0][0] == 3
    # 0 asks no page index, not even to open it.
    found, asked, opened = searched(monkeypatch, tmp_path, search_pages=0)
    assert asked == [] and opened == []
    assert ("table", 44) not in found


def test_a_corpus_without_a_page_index_changes_nothing_and_logs_once(
        monkeypatch, tmp_path, caplog):
    # The real `connect` on a corpus that has no page index.
    db = corpus(tmp_path)
    cache = tmp_path / "query_cache.db"
    query_cache.connect(cache).close()

    def retrieve(probes, document_id, exclude, limit=None):
        return [runner._source_of(content(None, *key)) for key in VECTOR]
    retrieve.vectors = lambda probes: [[1.0, 0.0, 0.0, 0.0]] * len(probes)
    monkeypatch.setattr(runner, "make_retrieve", lambda *a, **k: retrieve)
    from docpipe.inference import lexical
    monkeypatch.setattr(lexical, "connect", lambda db_path: None)
    more = runner.make_more_sources(db, None, {}, cache, content=content)
    with caplog.at_level(logging.WARNING):
        first = more(7, ["p1"], set())
        second = more(7, ["p2"], set())
    assert [(s.owner_kind, s.owner_id) for s in first] == VECTOR
    assert len(second) == len(first)
    said = [r for r in caplog.records if "page index" in r.getMessage()]
    assert len(said) == 1 and "missing" in said[0].getMessage()


# -- the index ---------------------------------------------------------------

needs_faiss = pytest.mark.skipif(
    importlib.util.find_spec("faiss") is None,
    reason="faiss is not importable")


class Embedder:
    """A page's vector is the unit vector of the page number its picture's
    file name carries; the model is *model*."""

    def __init__(self, model="m1", text_only=False):
        self.model = model
        self.text_only = text_only
        self.seen: list = []

    def process(self, items):
        out = []
        for item in items:
            name = item["image"].rsplit("_", 1)[-1][:-4]
            self.seen.append(item["image"])
            vector = np.zeros(4, dtype=np.float32)
            vector[int(name) - 1] = 1.0
            out.append(vector)
        return np.stack(out)


class Picture:
    def save(self, path):
        open(path, "wb").write(b"png")


def render(pdf, number, dpi):
    return Picture()


def built(tmp_path, **kw):
    db = corpus(tmp_path, pdfs=kw.pop("pdfs", ("a.pdf",)))
    root = tmp_path / "pdf"
    root.mkdir(exist_ok=True)
    (root / "a.pdf").write_bytes(b"%PDF")
    held = pages.build(db, pdf_root=root, embedder=Embedder(), render=render,
                       model="m1", dpi=kw.pop("dpi", 150))
    return db, held


@needs_faiss
def test_a_built_index_finds_the_page_whose_vector_is_closest(tmp_path):
    db, held = built(tmp_path)
    assert held["pages"] == 4 and held["documents"] == 1
    assert pages.state(db, model="m1") == "current"
    index = pages.connect(db, model="m1")
    one_hot = lambda n: [1.0 if i == n - 1 else 0.0 for i in range(4)]  # noqa
    assert index.search([one_hot(2)], 7, 1) == [2]
    # The best score of any sentence decides, and the number is a bound.
    assert index.search([one_hot(4), one_hot(1)], 7, 5) == [1, 4, 2, 3]
    # By construction: a document the index does not hold finds no page.
    assert index.search([one_hot(2)], 99, 3) == []
    # The corpus database was only read.
    assert not any(tmp_path.glob("*.building"))


@needs_faiss
def test_another_model_another_size_or_other_documents_make_it_stale(
        tmp_path):
    db, _ = built(tmp_path)
    assert pages.state(db, model="m1") == "current"
    assert pages.state(db, model="m2") == "stale"
    assert pages.state(db, model="m1", dpi=72) == "stale"
    assert pages.state(db, model="m1", dpi=150) == "current"
    conn = sqlite3.connect(db)
    conn.execute('UPDATE "Documents" SET "sha256" = \'changed\'')
    conn.commit()
    conn.close()
    assert pages.state(db, model="m1") == "stale"
    # A stale or missing index is not opened.
    assert pages.connect(db, model="m1") is None
    assert pages.state(tmp_path / "none.db", model="m1") == "missing"


@needs_faiss
def test_the_build_skips_a_document_without_a_pdf_and_says_so(tmp_path,
                                                              caplog):
    db = corpus(tmp_path, pdfs=("a.pdf", "gone.pdf"))
    root = tmp_path / "pdf"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF")
    with caplog.at_level(logging.WARNING):
        held = pages.build(db, pdf_root=root, embedder=Embedder(),
                           render=render, model="m1")
    assert held["skipped"] == ["gone.pdf"]
    assert held["documents"] == 1
    assert any("gone.pdf" in r.getMessage() for r in caplog.records)
    # By construction: the skipped document has no page in the index.
    index = pages.connect(db, model="m1")
    assert index.documents() == [7]


@needs_faiss
def test_an_embedder_of_text_only_builds_no_page_index(tmp_path):
    db = corpus(tmp_path)
    root = tmp_path / "pdf"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF")
    with pytest.raises(RuntimeError, match="text only"):
        pages.build(db, pdf_root=root, embedder=Embedder(text_only=True),
                    render=render, model="m1")
    assert not pages.path_for(db).exists()
    assert not pages.faiss_path_for(db).exists()
    # A model other than the one the corpus's vectors were made with.
    conn = store_schema.connect(db)
    store_schema.set_meta(conn, {"embedding/model": "m1"})
    conn.close()
    with pytest.raises(RuntimeError, match="do not compare"):
        pages.build(db, pdf_root=root, embedder=Embedder("m9"),
                    render=render, model="m9")


def test_the_command_is_registered_beside_lexical():
    assert cli.STAGES["pages"][0] == "docpipe.inference.pages"
    assert "lexical" in cli.STAGES


# -- the trace -----------------------------------------------------------------

def test_the_trace_schema_takes_the_event_of_the_page_search():
    record = {"t": "pages", "doc": 7, "sid": 1, "pages": [3, 4],
              "added": [["table", 44], ["section", 41]], "ms": 3}
    jsonschema.validate(record, schema.trace_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**record, "guessed": 1}, schema.trace_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**record, "pages": ["three"]},
                            schema.trace_schema())
