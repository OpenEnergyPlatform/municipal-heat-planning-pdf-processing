"""The word index beside the vectors, and one ranking out of both.

What is promised, sentence by sentence:

  * the word index is a file beside the corpus database AND holds one row
    per section, table and figure AND is never written into the database;
  * it finds a passage by a word of its text or its title, without regard
    to case and accents AND ranks a passage with more of the question's
    words higher AND a word in the title above one in the text;
  * a search can be limited to one document AND to kinds of passage;
  * punctuation in a question is not query syntax;
  * an index built from another state of the database is stale AND a stale
    or missing one is not asked;
  * two rankings are merged by reciprocal rank: a passage both found ranks
    above one only one found;
  * without a word index, or without words, the result is the search by
    meaning alone, unchanged;
  * over the whole corpus only current documents answer AND a passage is
    there once AND only kinds that were asked for;
  * a source of a corpus-wide answer names its document AND one of a
    single document does not;
  * an image the model asks for over the whole corpus is taken only when
    exactly one of the shown documents has it.
"""
import sqlite3

import pytest

np = pytest.importorskip("numpy")
if not hasattr(np, "asarray") or not hasattr(np, "argsort"):
    pytest.skip("numpy is a stub here", allow_module_level=True)

from docpipe.inference import answer, chunker, hybrid, lexical  # noqa: E402

SCHEMA = """
CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                        is_current INTEGER);
CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                       section_number INTEGER, title TEXT, content TEXT,
                       page_number INTEGER);
CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,
                     path TEXT, page_number INTEGER, caption TEXT,
                     markdown TEXT);
CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,
                     path TEXT, page_number INTEGER, caption TEXT,
                     description TEXT);
CREATE TABLE Embeddings (faiss_id INTEGER PRIMARY KEY, embedding_type TEXT,
                         owner_kind TEXT, owner_id INTEGER);
"""


@pytest.fixture
def corpus_db(tmp_path):
    path = tmp_path / "corpus.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO Documents VALUES (?, ?, ?)", [
        (1, "kassel.pdf", 1), (2, "marburg.pdf", 1), (3, "kassel_alt.pdf", 0)])
    conn.executemany("INSERT INTO Sections VALUES (?, ?, ?, ?, ?, ?)", [
        (10, 1, 1, "Wärmenetze", "Die Stadtwerke Kassel betreiben das "
                                 "Fernwärmenetz.", 4),
        (11, 1, 2, "Bestand", "Der Endenergieverbrauch liegt bei 241 GWh.", 9),
        (20, 2, 1, "Wärmenetze", "Die Stadtwerke Marburg planen ein "
                                 "Wärmenetz.", 5),
        (21, 2, 2, "Stadtwerke Marburg", "Organisation und Aufgaben.", 6),
        (30, 3, 1, "Wärmenetze", "Die Stadtwerke Kassel, alter Stand.", 4),
        (31, 3, 2, None, None, 5)])
    conn.execute("INSERT INTO Tables VALUES (100, 11, 'p9_tbl0', 't.png', 9, "
                 "'Tabelle 3: Endenergie', '| Erdgas | 241 |')")
    conn.execute("INSERT INTO Images VALUES (200, 20, 'p5_img0', 'f.png', 5, "
                 "'Abbildung 2: Netzkarte', 'Karte des Wärmenetzes Marburg')")
    conn.execute("INSERT INTO Images VALUES (201, 10, 'p5_img0', 'g.png', 4, "
                 "'Abbildung 1', 'Karte Kassel')")
    conn.executemany("INSERT INTO Embeddings VALUES (?, ?, ?, ?)", [
        (0, "section_text", "section", 10), (1, "section_title", "section", 10),
        (2, "section_text", "section", 11), (3, "section_text", "section", 20),
        (4, "section_text", "section", 21), (5, "section_text", "section", 30),
        (6, "table_text", "table", 100), (7, "figure_text", "figure", 200)])
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def conn(corpus_db):
    opened = sqlite3.connect(corpus_db)
    opened.row_factory = sqlite3.Row
    yield opened
    opened.close()


@pytest.fixture
def index(corpus_db):
    lexical.build(corpus_db)
    opened = lexical.connect(corpus_db)
    yield opened
    opened.close()


def owners(found):
    return [(kind, owner) for kind, owner, _document in found]


# ------------------------------------------------------------- the word index

def test_the_index_is_a_file_beside_the_database(corpus_db):
    before = corpus_db.read_bytes()
    held = lexical.build(corpus_db)
    assert held == {"section": 5, "table": 1, "figure": 2}  # not the empty one
    assert lexical.path_for(corpus_db) == corpus_db.with_name(
        "corpus.lexical.db")
    assert lexical.path_for(corpus_db).is_file()
    assert corpus_db.read_bytes() == before
    assert not list(corpus_db.parent.glob("*.building"))


def test_a_passage_is_found_by_a_word_of_its_text_or_title(index):
    assert owners(lexical.search(index, "Fernwärmenetz")) == [("section", 10)]
    assert owners(lexical.search(index, "FERNWARMENETZ")) == [("section", 10)]
    assert ("table", 100) in owners(lexical.search(index, "Erdgas"))
    assert owners(lexical.search(index, "Netzkarte")) == [("figure", 200)]
    assert lexical.search(index, "Geothermie") == []
    assert lexical.search(index, "") == []
    assert lexical.search(index, "Fernwärmenetz", limit=0) == []


def test_more_of_the_questions_words_rank_higher(index):
    found = owners(lexical.search(index, "Stadtwerke Marburg Wärmenetz"))
    assert found[0] in (("section", 20), ("section", 21))
    assert set(found[:2]) == {("section", 20), ("section", 21)}
    assert found.index(("section", 20)) < found.index(("section", 10))


def test_a_word_in_the_title_counts_more_than_one_in_the_text(index):
    # "Marburg" stands in the title of 21 and in the text of 20
    found = owners(lexical.search(index, "Marburg", kinds=["section"]))
    assert found == [("section", 21), ("section", 20)]


def test_a_search_limited_to_a_document_and_to_kinds(index):
    everywhere = owners(lexical.search(index, "Stadtwerke"))
    assert {owner for _kind, owner in everywhere} == {10, 20, 21, 30}
    assert owners(lexical.search(index, "Stadtwerke", document=2)) \
        == [("section", 21), ("section", 20)]
    assert owners(lexical.search(index, "Karte", kinds=["figure"],
                                 document=1)) == [("figure", 201)]
    assert lexical.search(index, "Karte", kinds=["table"]) == []
    assert [document for _k, _o, document
            in lexical.search(index, "Erdgas")] == [1]


@pytest.mark.parametrize("question", [
    'Was sagt "Kassel" (Stadtwerke)?', "Kassel AND OR NOT", "Kassel*",
    "title:Kassel", "Kassel - Stadtwerke", "NEAR(Kassel)", "Kassel^2",
])
def test_punctuation_in_a_question_is_not_query_syntax(index, question):
    assert ("section", 10) in owners(lexical.search(index, question))


def test_the_words_of_a_question():
    assert lexical.words("Wie hoch ist der Verbrauch, der VERBRAUCH?") == [
        "wie", "hoch", "ist", "der", "verbrauch"]
    assert lexical.words("a b 2030") == ["2030"]
    assert len(lexical.words(" ".join(f"w{i}" for i in range(99)))) \
        == lexical.MAX_WORDS


def test_an_index_of_another_state_of_the_database_is_not_asked(
        corpus_db, caplog):
    assert lexical.state(corpus_db) == "missing"
    assert lexical.connect(corpus_db) is None
    assert "missing" in caplog.text and "docpipe lexical" in caplog.text
    lexical.build(corpus_db)
    assert lexical.state(corpus_db) == "current"
    conn = sqlite3.connect(corpus_db)
    conn.execute("INSERT INTO Sections VALUES (99, 1, 9, 'Neu', 'Neu.', 1)")
    conn.commit()
    conn.close()
    assert lexical.state(corpus_db) == "stale"
    assert lexical.connect(corpus_db) is None
    lexical.build(corpus_db)                    # built again, current again
    assert lexical.state(corpus_db) == "current"


@pytest.mark.parametrize("change", [
    # a text rewritten in place: same rows, same ids, other words
    "UPDATE Sections SET content = 'Ganz anderer Text.' WHERE id = 10",
    "UPDATE Sections SET title = 'Anders' WHERE id = 10",
    # a passage moved to another document
    "UPDATE Sections SET document = 2 WHERE id = 11",
    "UPDATE Tables SET markdown = '| Kohle | 5 |' WHERE id = 100",
    "UPDATE Images SET description = 'Foto' WHERE id = 200",
])
def test_a_change_that_keeps_every_count_makes_the_index_stale(corpus_db,
                                                              change):
    lexical.build(corpus_db)
    assert lexical.state(corpus_db) == "current"
    conn = sqlite3.connect(corpus_db)
    conn.execute(change)
    conn.commit()
    conn.close()
    assert lexical.state(corpus_db) == "stale"
    assert lexical.connect(corpus_db) is None


def test_a_change_outside_the_passages_leaves_the_index_current(corpus_db):
    lexical.build(corpus_db)
    conn = sqlite3.connect(corpus_db)
    conn.execute("UPDATE Documents SET filename = 'k.pdf' WHERE id = 1")
    conn.execute("INSERT INTO Embeddings VALUES (9, 'section_text', "
                 "'section', 21)")
    conn.commit()
    conn.close()
    assert lexical.state(corpus_db) == "current"


def test_a_word_with_a_sharp_s_is_found_as_it_is_written(corpus_db):
    conn = sqlite3.connect(corpus_db)
    conn.execute("UPDATE Sections SET content = 'Maßnahmen an der Straße "
                 "in Großalmerode.' WHERE id = 11")
    conn.commit()
    conn.close()
    lexical.build(corpus_db)
    index = lexical.connect(corpus_db)
    try:
        for word in ("Maßnahmen", "maßnahmen", "Straße", "Großalmerode"):
            assert owners(lexical.search(index, word)) == [("section", 11)]
    finally:
        index.close()
    assert lexical.words("Maßnahmen") == ["maßnahmen"]


def test_an_index_that_cannot_be_replaced_stays_and_nothing_is_left_over(
        corpus_db, monkeypatch, capsys):
    """Where a file cannot be replaced while a program has it open, the
    build says so. The index that was there is whole and still found."""
    lexical.build(corpus_db)
    held = lexical.path_for(corpus_db).read_bytes()

    def refuse(self, target):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(lexical.Path, "replace", refuse)
    with pytest.raises(RuntimeError) as caught:
        lexical.build(corpus_db)
    assert "stop it and run this again" in str(caught.value)
    with pytest.raises(SystemExit) as ended:
        lexical.main([str(corpus_db)])
    assert "could not be replaced" in str(ended.value)
    assert lexical.path_for(corpus_db).read_bytes() == held
    assert not list(corpus_db.parent.glob("*.building"))
    assert lexical.state(corpus_db) == "current"


def test_a_build_that_fails_leaves_no_half_built_file(tmp_path):
    bare = tmp_path / "bare.db"
    sqlite3.connect(bare).close()               # a database without passages
    with pytest.raises(sqlite3.OperationalError):
        lexical.build(bare)
    assert not list(tmp_path.glob("*.building"))
    assert not lexical.path_for(bare).exists()


@pytest.mark.parametrize("folder, name", [
    ("has#hash", "corpus.db"), ("plain", "c#1.db"), ("x%41", "corpus.db"),
    ("with space", "corpus.db"),
])
def test_a_database_is_opened_under_the_name_it_has(corpus_db, tmp_path,
                                                    folder, name):
    """A `#` or a `%` in a path is part of the path. Written into the
    address unescaped it named another file, which was then created."""
    home = tmp_path / folder
    home.mkdir()
    database = home / name
    database.write_bytes(corpus_db.read_bytes())
    held = lexical.build(database)
    assert held == {"section": 5, "table": 1, "figure": 2}
    assert lexical.state(database) == "current"
    index = lexical.connect(database)
    try:
        assert owners(lexical.search(index, "Netzkarte")) == [("figure", 200)]
    finally:
        index.close()
    assert sorted(path.name for path in home.iterdir()) == sorted(
        [name, lexical.path_for(database).name])
    opened = answer.db.connect_readonly(database)
    try:
        assert opened.execute("SELECT COUNT(*) FROM Sections").fetchone()[0] \
            == 6
    finally:
        opened.close()


def test_the_command(corpus_db, capsys):
    assert lexical.main([str(corpus_db), "--check"]) == 1
    assert "missing" in capsys.readouterr().out
    assert lexical.main([str(corpus_db)]) == 0
    assert "8 passage(s)" in capsys.readouterr().out
    assert lexical.main([str(corpus_db), "--check"]) == 0
    with pytest.raises(SystemExit):
        lexical.main([str(corpus_db.with_name("nothing.db"))])


# -------------------------------------------------------------------- merging

def test_two_rankings_are_merged_by_reciprocal_rank():
    merged = hybrid.fuse([["a", "b", "c"], ["c", "d"]])
    assert [key for key, _score in merged] == ["c", "a", "b", "d"]
    scores = dict(merged)
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == scores["d"] == pytest.approx(1 / 62)
    assert hybrid.fuse([[], []]) == []
    assert [key for key, _s in hybrid.fuse([["a", "b"]])] == ["a", "b"]


def test_the_kinds_of_embedding_types():
    assert hybrid.kinds_of(["section_text", "section_title", "table_vl",
                            "figure_text", "unknown_x"]) == [
        "section", "table", "figure"]


class Index:
    """A global index of unit vectors: searched by inner product."""

    def __init__(self, vectors):
        self.vectors = np.asarray(vectors, dtype="float32")
        self.ntotal = len(vectors)
        self.asked = []

    def search(self, query, k):
        self.asked.append(k)
        scores = self.vectors @ np.asarray(query, dtype="float32").reshape(-1)
        order = np.argsort(-scores)[:k]
        return scores[order].reshape(1, -1), order.reshape(1, -1)


def unit(*weights):
    vector = np.zeros(8, dtype="float32")
    for position, weight in enumerate(weights):
        vector[position] = weight
    return vector


@pytest.fixture
def vectors():
    # faiss id -> its vector; the query is the first axis
    return Index([unit(0.9), unit(0.95), unit(0.5), unit(0.8), unit(0.3),
                  unit(0.99), unit(0.7), unit(0.6)])


TEXT = ["section_text", "section_title"]
EVERY = TEXT + ["table_text", "figure_text"]


def test_over_the_whole_corpus_only_current_documents_answer(conn, vectors):
    hits = hybrid.dense_corpus(conn, vectors, EVERY, unit(1.0), 10)
    found = [(hit["owner_kind"], hit["owner_id"]) for hit in hits]
    # 30 has the best vector and belongs to a superseded document
    assert ("section", 30) not in found
    assert found == [("section", 10), ("section", 20), ("table", 100),
                     ("figure", 200), ("section", 11), ("section", 21)]
    assert hits[0]["score"] == pytest.approx(0.95)  # its better vector
    assert [hit["document_id"] for hit in hits] == [1, 2, 1, 2, 1, 2]


def test_only_the_kinds_asked_for_and_not_what_was_examined(conn, vectors):
    hits = hybrid.dense_corpus(conn, vectors, ["table_text"], unit(1.0), 10)
    assert [(h["owner_kind"], h["owner_id"]) for h in hits] \
        == [("table", 100)]
    hits = hybrid.dense_corpus(conn, vectors, TEXT, unit(1.0), 2,
                               exclude={("section", 10)})
    assert [h["owner_id"] for h in hits] == [20, 11]
    assert hybrid.dense_corpus(conn, vectors, [], unit(1.0), 5) == []
    assert hybrid.dense_corpus(conn, Index(np.zeros((0, 8))), EVERY,
                               unit(1.0), 5) == []


def _crowded():
    """Forty vectors of which the database knows the first eight. The one
    wanted table (faiss id 6) is the worst of all of them."""
    return Index([unit(0.1) if number == 6 else unit(0.9)
                  for number in range(40)])


def test_the_global_search_asks_for_more_until_enough_are_found(conn):
    index = _crowded()
    hits = hybrid.dense_corpus(conn, index, ["table_text"], unit(1.0), 1)
    assert [h["owner_id"] for h in hits] == [100]
    # eight at first, which hold no table; then more, up to all there are
    assert index.asked == [8, 32, 40]


def test_the_global_search_stops_at_its_ceiling(conn, monkeypatch):
    monkeypatch.setattr(hybrid, "MAX_FETCH", 4)
    index = _crowded()
    assert hybrid.dense_corpus(conn, index, ["table_text"], unit(1.0),
                               1) == []
    assert index.asked == [4]           # the first pass is held to it too
    monkeypatch.setattr(hybrid, "MAX_FETCH", 16)
    index = _crowded()
    hybrid.dense_corpus(conn, index, ["table_text"], unit(1.0), 1)
    assert index.asked == [8, 16]


@pytest.mark.parametrize("at_once", [1, 3, 500])
def test_the_ids_are_looked_up_a_few_at_a_time(conn, vectors, monkeypatch,
                                               at_once):
    """However many ids one statement carries, the result is the same: a
    search that asks for thousands does not put them into one."""
    whole = hybrid.dense_corpus(conn, vectors, EVERY, unit(1.0), 10)
    statements = []
    conn.set_trace_callback(statements.append)
    monkeypatch.setattr(hybrid, "LOOKUP", at_once)
    again = hybrid.dense_corpus(conn, vectors, EVERY, unit(1.0), 10)
    conn.set_trace_callback(None)
    assert again == whole
    looked_up = [text for text in statements if '"Embeddings"' in text]
    assert len(looked_up) == -(-8 // at_once)       # eight ids, in parts


def test_without_a_word_index_the_result_is_the_search_by_meaning(
        conn, vectors, index):
    dense = hybrid.dense_corpus(conn, vectors, EVERY, unit(1.0), 4)
    assert hybrid.retrieve(conn, vectors, {}, None, EVERY, unit(1.0), 4,
                           text="Stadtwerke Marburg") == dense
    assert hybrid.retrieve(conn, vectors, {}, None, EVERY, unit(1.0), 4,
                           text="  ", lexical_index=index) == dense
    assert hybrid.retrieve(conn, vectors, {}, None, EVERY, unit(1.0), 4,
                           text="Geothermie", lexical_index=index) == dense
    assert "dense_rank" not in dense[0]


def test_a_passage_both_searches_found_ranks_first(conn, vectors, index):
    hits = hybrid.retrieve(conn, vectors, {}, None, EVERY, unit(1.0), 6,
                           text="Stadtwerke Marburg", lexical_index=index)
    first = hits[0]
    assert (first["owner_kind"], first["owner_id"]) == ("section", 20)
    assert first["dense_rank"] == 2 and first["lexical_rank"] is not None
    assert first["score"] == pytest.approx(
        1 / 62 + 1 / (60 + first["lexical_rank"]))
    found = [(hit["owner_kind"], hit["owner_id"]) for hit in hits]
    assert len(found) == len(set(found))
    assert ("section", 30) not in found             # superseded, by word too
    only_dense = next(hit for hit in hits if hit["owner_id"] == 100)
    assert only_dense["lexical_rank"] is None
    assert len(hybrid.retrieve(conn, vectors, {}, None, EVERY, unit(1.0), 2,
                               text="Stadtwerke", lexical_index=index)) == 2


def test_the_word_search_fills_its_places_after_what_is_taken_out(
        conn, index, monkeypatch):
    """By word, the two best sections for "Stadtwerke Kassel" are 10 and
    the superseded 30. What an older version says is taken out afterwards,
    and so is what was examined before; neither uses up a place the next
    passage should have."""
    monkeypatch.setattr(hybrid, "dense_corpus", lambda *a, **more: [])
    by_word = [owner for _kind, owner, _document in hybrid.lexical.search(
        index, "Stadtwerke Kassel", kinds=["section"], limit=2)]
    assert sorted(by_word) == [10, 30]          # what two places would hold
    hits = hybrid.retrieve(conn, None, {}, None, TEXT, unit(1.0), 2,
                           text="Stadtwerke Kassel", lexical_index=index)
    found = [hit["owner_id"] for hit in hits]
    assert len(found) == 2 and found[0] == 10 and 30 not in found
    hits = hybrid.retrieve(conn, None, {}, None, TEXT, unit(1.0), 2,
                           text="Stadtwerke Kassel", lexical_index=index,
                           exclude={("section", 10)})
    found = [hit["owner_id"] for hit in hits]
    assert len(found) == 2 and not {10, 30} & set(found)


def test_a_passage_only_the_word_index_found_is_in_the_result(conn, index):
    # the vectors know nothing about section 21; its title names Marburg
    blind = Index([unit(0.9), unit(0.9), unit(0.5), unit(0.8), unit(-1.0),
                   unit(0.9), unit(0.7), unit(0.6)])
    hits = hybrid.retrieve(conn, blind, {}, None, TEXT, unit(1.0), 3,
                           text="Marburg", lexical_index=index)
    found = {hit["owner_id"]: hit for hit in hits}
    assert 21 in found and found[21]["dense_rank"] is None
    assert found[21]["text"] == "Organisation und Aufgaben."


def test_one_document_is_searched_as_before_and_by_word_within_it(
        conn, index, monkeypatch):
    seen = {}

    def dense(conn_, index_, id_to_pos, document, types, vector, top_k,
              exclude=None):
        seen.update(document=document, exclude=exclude)
        return [{"owner_kind": "section", "owner_id": 11, "score": 0.9,
                 "document_id": 1, "text": "x"}]

    monkeypatch.setattr(hybrid.faiss_store, "retrieve", dense)
    hits = hybrid.retrieve(conn, None, {}, 1, TEXT, unit(1.0), 5,
                           text="Stadtwerke", lexical_index=index,
                           exclude={("section", 99)})
    assert seen == {"document": 1, "exclude": {("section", 99)}}
    assert [hit["owner_id"] for hit in hits] == [11, 10]    # 20, 21: not doc 1
    excluded = hybrid.retrieve(conn, None, {}, 1, TEXT, unit(1.0), 5,
                               text="Stadtwerke", lexical_index=index,
                               exclude={("section", 10)})
    assert [hit["owner_id"] for hit in excluded] == [11]


# ------------------------------------------------------------------ the turn

def hit(owner=10, document=1, **more):
    return {"owner_kind": "section", "owner_id": owner, "title": "T",
            "text": "Der Bedarf betrug 100 GWh.", "page_number": 4,
            "section_title": "Bestand", "image_path": None,
            "document_id": document, **more}


def test_a_source_of_a_corpus_wide_answer_names_its_document():
    plain = chunker.citation_label(hit())
    named = chunker.citation_label(hit(document_label="Kassel 2024"))
    assert named == "Kassel 2024: " + plain
    assert chunker.format_hit(0, hit(document_label="Kassel 2024"))[
        "source"] == named
    for kind in ("table", "figure", "other"):
        labelled = chunker.citation_label(
            hit(owner_kind=kind, document_label="Kassel 2024"))
        assert labelled.startswith("Kassel 2024: ")


def test_a_corpus_wide_source_is_named_by_its_file_where_nobody_names_it(
        conn, monkeypatch):
    """`Corpus.document_label` is the caller's. Where it is not given, or
    says nothing for a document, the source still says whose it is."""
    seen = {}

    def from_sources(task, items, **more):
        seen["sources"] = [item["source"] for item in items]
        return {"found": False, "answer": None, "supports": []}

    monkeypatch.setattr(answer.hybrid, "retrieve",
                        lambda *a, **more: [hit(10, 1), hit(20, 2)])
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda task, **more: ("Bedarf", False))
    monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                        from_sources)
    conn.row_factory = sqlite3.Row
    unnamed = answer.Corpus(conn=conn, index=None, id_to_pos={},
                            embed=lambda item: ([0.0] * 4, False))
    answer.answer_question("Wie hoch?", unnamed, None,
                           [answer.config.SCOPE_TEXT])
    assert [source.split(":")[0] for source in seen["sources"]] \
        == ["kassel", "marburg"]
    partly = answer.Corpus(conn=conn, index=None, id_to_pos={},
                           embed=lambda item: ([0.0] * 4, False),
                           document_label={1: "Kassel 2024"}.get)
    answer.answer_question("Wie hoch?", partly, None,
                           [answer.config.SCOPE_TEXT])
    assert [source.split(":")[0] for source in seen["sources"]] \
        == ["Kassel 2024", "marburg"]


def _turn(monkeypatch, document_id, hits):
    seen = {}

    def retrieve(conn, index, id_to_pos, document, types, vector, top_k,
                 **more):
        seen.update(document=document, **more)
        return hits

    def from_sources(task, items, **more):
        seen["sources"] = [item["source"] for item in items]
        seen["requester"] = more["image_requester"]
        return {"found": False, "answer": None, "supports": []}

    monkeypatch.setattr(answer.hybrid, "retrieve", retrieve)
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda task, **more: ("Bedarf", False))
    monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                        from_sources)
    corpus = answer.Corpus(
        conn=None, index=None, id_to_pos={}, lexical="the word index",
        embed=lambda item: ([0.0] * 4, False),
        document_label=lambda document: {1: "Kassel", 2: "Marburg"}.get(
            document))
    answer.answer_question("Wie hoch?", corpus, document_id,
                           [answer.config.SCOPE_TEXT])
    return seen, corpus


def test_the_turn_asks_both_searches_and_names_documents_only_corpus_wide(
        monkeypatch):
    seen, _corpus = _turn(monkeypatch, None, [hit(10, 1), hit(20, 2)])
    assert seen["document"] is None
    assert seen["lexical_index"] == "the word index"
    assert seen["text"] == "Wie hoch? Bedarf"
    assert [source.split(":")[0] for source in seen["sources"]] \
        == ["Kassel", "Marburg"]
    seen, _corpus = _turn(monkeypatch, 1, [hit(10, 1)])
    assert seen["document"] == 1
    assert not seen["sources"][0].startswith("Kassel")


def test_an_image_asked_for_corpus_wide_is_taken_from_the_one_document(
        conn, monkeypatch):
    seen, corpus = _turn(monkeypatch, None, [hit(10, 1), hit(20, 2)])
    corpus.conn = conn
    corpus.resolve_image = lambda path: path
    monkeypatch.setattr(answer.db, "_document_folder",
                        lambda conn_, document: f"doc{document}")
    monkeypatch.setattr(answer.db, "_asset_path",
                        lambda folder, path: f"{folder}/{path}")
    request = seen["requester"]
    assert request("p9_tbl0")["owner_id"] == 100    # only Kassel has it
    assert request("p9_tbl0")["document_id"] == 1
    assert request("p5_img0") is None               # both shown have one
    assert request("p1_img9") is None               # nobody has it
