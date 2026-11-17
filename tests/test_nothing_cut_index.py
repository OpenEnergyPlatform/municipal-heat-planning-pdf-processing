"""The entries of the index are the pieces the harvest reads, and nothing of
them is cut (owner decisions 2026-11-17: "Die Einträge im Index sind die
Stücke der Ernte"; "**Nichts** kürzen, einfach ggf. clever aufteilen und
darauf achten, dass die Zuordnung zu Sektion und Seite etc. nicht verlieren
gehen").

The promises, each with a case that breaks it by construction:

1. A section's entries are its pieces, each its heading and its own
   sentences, AND together they hold every sentence of the section once, a
   section of any length whole.
2. A table's entries show its title, its head, every line under it and the
   group row and the rows each of its rows stands under, AND every row of the
   table is an own row of exactly one entry.
3. A group row (a row that fills its first cell only) stands over the rows
   below it up to the next group row, AND a row of one cell is no group row.
4. An entry that does not fit the window is split into parts that each fit,
   AND each part shows every line its piece carries, AND the parts together
   hold every own line of the piece once; a line longer than the window is
   split at its sentences and then its words, every word kept.
5. An entry whose carried lines alone do not fit is not embedded and is
   named, never cut.
6. Every entry knows its piece, part, page and lines: a section piece the
   page its first sentence stands on in the PDF's text, a table's its page.
7. The database of format 2 holds several pieces and parts of one owner and
   type, AND a database of format 1 keeps every vector when it is brought up
   (piece NULL), AND the writer and the readers name piece and part.
8. The embed step takes the vectors of whole owners out of the index and the
   database, so that every owner is embedded again in pieces.
9. An embedder that answers item by item loses only the item it refused, the
   others of its batch get their vectors.
10. A search hit says which piece of its owner scored best, with its page, AND
    an owner counts with its best piece.
11. The reranker scores the pieces of a passage and the passage counts with
    its best piece, AND a pair over the window is split into parts and the
    piece counts with its best part, AND no request asks the server to cut.
12. The window counts a text by its bytes where they fit and exactly
    otherwise, AND the frame and a picture take their share.
13. An embedder that takes text only is never shown a picture input, AND a
    picture input is dropped before the fit check, not after it.
14. The local embedder's window counts the frame of its real template, not
    one token for a batch of one.
15. A database of format 1 holds nothing embedded in the new format: the
    status of the chunk stage reads it as not done and does not fail.
16. The embed step saves the index before it deletes the rows of the whole
    vectors it took out of it.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import faiss
import numpy as np
import pytest

from docpipe.chunking import chunking, pieces
from docpipe.chunking.chunking import build_embedding_inputs, fit_inputs
from docpipe.chunking.database import (EmbeddingWriter, drop_wholes,
                                       get_existing_embeddings,
                                       ids_of_document, wholes_of_index)
from docpipe.chunking.embedding import (Unembedded, create_embeddings,
                                        index_ids)
from docpipe.extraction import units
from docpipe.inference import db as inference_db
from docpipe.inference import faiss_store, rerank
from docpipe.store import schema as store_schema
from docpipe.window import Window, split, TooLong

SENTENCES = [f"Satz {i} sagt etwas über die Wärme im Ort." for i in range(1, 30)]
ROWS = [f"| Zeile {i} | {i * 10} | {i * 11} |" for i in range(1, 21)]
MARKDOWN = "\n".join(
    ["| Bereich | 2020 | 2030 |", "| --- | --- | --- |", "| AT | | |"]
    + ROWS + ["| DE | | |", "| Erdgas | 5 | 6 |",
              "* ohne Industrie", "Angaben in GWh/a."])


def document():
    content = " ".join(SENTENCES) + " Siehe Tabelle 1. [p4_tbl0]"
    first, second = " ".join(SENTENCES[:10]), " ".join(SENTENCES[10:])
    return {"sections": [{
        "title": "Wärmebedarf", "page_number": 3, "pages": [3, 4],
        "content": content,
        "segments": [{"kind": "text", "page": 3, "text": first},
                     {"kind": "text", "page": 4, "text": second},
                     {"kind": "table", "page": 4, "ref": "p4_tbl0"}],
        "tables": [{"id": "p4_tbl0",
                    "caption": "Tabelle 1: Endenergie nach Region",
                    "markdown": MARKDOWN, "path": "images/p4_tbl0.png",
                    "page_number": 4}],
        "figures": []}]}


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "p4_tbl0.png").write_bytes(b"png")
    return tmp_path


def inputs_of(folder, kind):
    return [i for i in build_embedding_inputs(document(), "plan", folder,
                                              log_counts=False, size=8)
            if i.embedding_type == kind]


# -- 1, 2, 3: the pieces --------------------------------------------------------

def test_every_section_piece_shows_its_heading_and_holds_its_own_sentences(folder):
    made = inputs_of(folder, "section_text")
    assert len(made) > 2
    for inp in made:
        assert inp.text.split("\n")[0] == "Wärmebedarf"
        own = inp.text.split("\n")[1:]
        assert len(own) <= 8
    # Every sentence once, in order, however long the section.
    said = [line for inp in made for line in inp.text.split("\n")[1:]]
    assert said[:len(SENTENCES)] == SENTENCES
    assert len(said) == len(SENTENCES) + 1           # the last line names the table


def test_every_table_piece_carries_title_head_group_and_every_line_under_it(folder):
    made = inputs_of(folder, "table_text")
    assert len(made) == 3
    for inp in made:
        lines = inp.text.split("\n")
        assert lines[0] == "Tabelle 1: Endenergie nach Region"
        assert "| Bereich | 2020 | 2030 |" in lines
        assert lines[-2:] == ["* ohne Industrie", "Angaben in GWh/a."]
    # Every row is the own row of exactly one piece.
    owned = []
    for inp in made:
        owned += list(range(inp.first_line, inp.last_line + 1))
    assert sorted(owned) == sorted(set(owned))
    rows = [line for inp in made for line in inp.text.split("\n")
            if line.startswith("| Zeile")]
    assert sorted(rows) == sorted(ROWS)
    # The rows under "AT" are shown with it in every piece that holds one.
    assert all("| AT | | |" in inp.text for inp in made)


def test_a_group_row_stands_over_the_rows_up_to_the_next_and_a_one_cell_row_is_none():
    lines, _fixed = units.table_lines(MARKDOWN)
    parents = units.row_parents(lines)
    at = {line.text: line.number for line in lines}
    assert parents[at["| Zeile 5 | 50 | 55 |"]] == (at["| AT | | |"],)
    assert parents[at["| Erdgas | 5 | 6 |"]] == (at["| DE | | |"],)
    assert at["| DE | | |"] not in parents          # a group row is under none
    one = units.table_lines("| A |\n| --- |\n| x |\n| y |")[0]
    assert units.row_parents(one) == {}


# -- 4, 5: parts ------------------------------------------------------------------

def test_a_piece_over_the_window_is_split_into_parts_that_each_carry_its_lines(folder):
    whole = inputs_of(folder, "table_text")[0]
    window = Window(limit=len(whole.text.encode("utf-8")) - 40)
    parts = fit_inputs([whole], lambda text, picture=None: window.fits(text))
    assert len(parts) > 1
    assert [p.part for p in parts] == list(range(len(parts)))
    for part in parts:
        assert window.fits(part.text)
        assert part.text.split("\n")[0] == "Tabelle 1: Endenergie nach Region"
        assert part.text.endswith("Angaben in GWh/a.")
        assert part.piece == whole.piece and part.page == whole.page
    own = [line for part in parts for line in part.text.split("\n")
           if line.startswith("| Zeile")]
    assert own == [line for line in whole.text.split("\n")
                   if line.startswith("| Zeile")]


def test_a_line_longer_than_the_window_is_split_at_sentences_then_words():
    long_line = " ".join(f"Wort{i}" for i in range(400)) + ". " + \
        " ".join(f"Satz{i}." for i in range(50))
    texts = {1: "Kopf", 2: long_line}

    def render(numbers, replaced):
        return "\n".join([texts[1]] + [replaced.get(n, texts[n]) for n in numbers])
    window = Window(limit=120)
    parts = split([2], render, texts.get, window.fits, units.sentences_of)
    assert len(parts) > 2
    for part in parts:
        assert window.fits(part.text) and part.text.startswith("Kopf\n")
    words = " ".join(part.replaced[2] for part in parts).split()
    assert words == long_line.split()


def test_a_piece_whose_carried_lines_alone_do_not_fit_is_named_never_cut(folder):
    whole = inputs_of(folder, "table_text")[0]
    window = Window(limit=30)
    named = []
    out = fit_inputs([whole], lambda text, picture=None: window.fits(text),
                     lambda inp, reason: named.append(reason))
    assert out == [] and len(named) == 1 and "piece 0" in named[0]
    with pytest.raises(TooLong):
        split([2], lambda numbers, replaced: "x" * 200, lambda n: "a b",
              Window(limit=10).fits, units.sentences_of)


# -- 6: piece, part, page, lines --------------------------------------------------

def test_every_entry_knows_its_piece_page_and_lines(folder):
    sections = inputs_of(folder, "section_text")
    assert [s.piece for s in sections] == list(range(len(sections)))
    assert sections[0].page == 3                      # first sentences: page 3
    assert sections[-1].page == 4                     # the last: page 4
    assert sections[0].first_line == 1
    for before, after in zip(sections, sections[1:]):
        assert after.first_line == before.last_line + 1
    tables = inputs_of(folder, "table_text")
    assert {t.page for t in tables} == {4}
    vl = inputs_of(folder, "table_vl")
    assert [v.piece for v in vl] == [t.piece for t in tables]
    assert all(v.image and v.text == t.text for v, t in zip(vl, tables))


def test_a_line_not_found_in_the_pdf_text_stands_on_the_page_before():
    section = {"page_number": 7, "segments": [
        {"kind": "text", "page": 7, "text": "Erster Satz über Wärme im Ort."},
        {"kind": "text", "page": 8, "text": "Dritter Satz über Kälte im Ort."}]}
    assert pieces.line_pages(["Erster Satz über Wärme im Ort.",
                              "Ein Satz, den das PDF so nicht druckt.",
                              "Dritter Satz über Kälte im Ort."],
                             section) == [7, 7, 8]


# -- 7, 8: the database -----------------------------------------------------------

def corpus(tmp_path, doc):
    from docpipe.chunking.database import _insert_sections
    db = tmp_path / "corpus.db"
    conn = sqlite3.connect(db)
    store_schema.apply(conn)
    conn.execute("INSERT INTO Documents (filename) VALUES ('plan.pdf')")
    doc_id = conn.execute("SELECT id FROM Documents").fetchone()[0]
    _insert_sections(doc_id, doc, conn)
    conn.commit()
    conn.close()
    return db, doc_id


def test_format_2_holds_several_pieces_and_parts_of_one_owner(tmp_path, folder):
    db, doc_id = corpus(tmp_path, document())
    with EmbeddingWriter(db) as writer:
        writer.write("plan", [("table_text", 0, "p4_tbl0", 10, 0, 0, 4, 3, 10),
                              ("table_text", 0, "p4_tbl0", 11, 0, 1, 4, 11, 12),
                              ("table_text", 0, "p4_tbl0", 12, 1, 0, 4, 13, 20)])
    assert get_existing_embeddings(db, "plan", doc_id=doc_id) == {
        ("table_text", 0, "p4_tbl0", 0, 0), ("table_text", 0, "p4_tbl0", 0, 1),
        ("table_text", 0, "p4_tbl0", 1, 0)}
    with sqlite3.connect(db) as conn:
        assert ids_of_document(conn, doc_id) == {
            ("table_text", 0, "p4_tbl0", 0, 0): 10,
            ("table_text", 0, "p4_tbl0", 0, 1): 11,
            ("table_text", 0, "p4_tbl0", 1, 0): 12}
        assert conn.execute(
            "SELECT page, first_line, last_line FROM Embeddings "
            "WHERE faiss_id = 11").fetchone() == (4, 11, 12)


def test_format_1_is_brought_up_with_every_vector_it_held(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        'CREATE TABLE "Embeddings" ("faiss_id" INTEGER PRIMARY KEY, '
        '"embedding_type" TEXT NOT NULL, "owner_kind" TEXT NOT NULL, '
        '"owner_id" INTEGER NOT NULL, '
        'UNIQUE("owner_kind", "owner_id", "embedding_type"));'
        "INSERT INTO Embeddings VALUES (5, 'section_text', 'section', 1);"
        "INSERT INTO Embeddings VALUES (6, 'table_vl', 'table', 2);"
        "PRAGMA user_version = 1;")
    conn.commit()
    store_schema.apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store_schema.FORMAT
    assert conn.execute(
        "SELECT faiss_id, embedding_type, owner_kind, owner_id, piece, part "
        "FROM Embeddings ORDER BY faiss_id").fetchall() == [
        (5, "section_text", "section", 1, None, 0),
        (6, "table_vl", "table", 2, None, 0)]
    # Two pieces of one owner and type now stand side by side.
    conn.execute("INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, "
                 "owner_id, piece, part) VALUES (7, 'section_text', 'section', "
                 "1, 0, 0), (8, 'section_text', 'section', 1, 1, 0)")
    conn.close()
    assert sorted(wholes_of_index(db)) == [5, 6]
    assert drop_wholes(db, [5, 6]) == 2 and wholes_of_index(db) == []


# -- 9: one refused item costs itself alone ---------------------------------------

class EachEmbedder:
    """Answers item by item and refuses the item whose text says so."""
    text_only = False

    def process_each(self, items):
        return [ValueError("too long") if "refuse" in item["text"]
                else np.ones(4, dtype=np.float32) for item in items]


def test_an_item_the_embedder_refuses_costs_itself_alone(tmp_path):
    db, _ = corpus(tmp_path, {"sections": [
        {"title": "A", "content": "eins", "page_number": 1},
        {"title": "B", "content": "refuse", "page_number": 1},
        {"title": "C", "content": "drei", "page_number": 1}]})
    inputs = [chunking.EmbeddingInput("section_text", "plan", n, None, text,
                                      piece=0)
              for n, text in enumerate(["eins", "refuse", "drei"])]
    index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
    missed = Unembedded()
    create_embeddings(inputs, index, 0, db, embedder=EachEmbedder(),
                      batch_size=8, unembedded=missed)
    assert index.ntotal == 2 and len(missed) == 1
    assert get_existing_embeddings(db, "plan") == {
        ("section_text", 0, None, 0, 0), ("section_text", 2, None, 0, 0)}


# -- 10: hits say their piece -------------------------------------------------------

def test_a_hit_says_its_best_piece_and_page_and_the_owner_counts_with_it(
        tmp_path, monkeypatch):
    monkeypatch.setattr(faiss_store, "EMBEDDING_DIM", 2)   # the test's index
    db, doc_id = corpus(tmp_path, document())
    with EmbeddingWriter(db) as writer:
        writer.write("plan", [("section_text", 0, None, 0, 0, 0, 3, 1, 8),
                              ("section_text", 0, None, 1, 1, 0, 4, 9, 16)])
    index = faiss.IndexIDMap(faiss.IndexFlatIP(2))
    index.add_with_ids(np.array([[1, 0], [0, 1]], dtype=np.float32),
                       np.array([0, 1], dtype=np.int64))
    conn = inference_db.connect_readonly(db)
    id_to_pos = faiss_store._build_id_to_pos(index)
    hits = faiss_store.retrieve(conn, index, id_to_pos, doc_id,
                                ["section_text"], np.array([0.2, 0.9]), 5)
    assert len(hits) == 1                                # one owner, once
    assert hits[0]["score"] == pytest.approx(0.9)        # its best piece
    assert hits[0]["piece"]["piece"] == 1 and hits[0]["piece"]["page"] == 4


# -- 11: the reranker reads pieces ------------------------------------------------

class Server:
    def __init__(self, by):
        self.by, self.bodies = by, []

    def __call__(self, body):
        self.bodies.append(body)
        return {"results": [{"index": i, "relevance_score": self.by(text)}
                            for i, text in enumerate(body["documents"])],
                "usage": {"prompt_tokens": 3}}


def test_the_reranker_scores_the_pieces_and_a_passage_counts_with_its_best():
    text = "\n".join(f"Satz {i} über Wärme." for i in range(1, 20))
    passage = SimpleNamespace(owner_kind="section", owner_id=1, text=text,
                              provenance={"section_title": "Kopf"})
    other = SimpleNamespace(owner_kind="section", owner_id=2,
                            text="Nichts dazu.", provenance={})
    server = Server(lambda doc: 0.9 if "Satz 17 " in doc else 0.1)
    ranker = rerank.Reranker(base_url="http://x", post=server)
    ordered = ranker.order(3, ["q"], [other, passage])
    assert [s.owner_id for s in ordered] == [1, 2]
    sent = server.bodies[0]["documents"]
    assert len(sent) == 4                       # three pieces of 1, one of 2
    assert all(doc.startswith("Kopf\n") for doc in sent if "Satz" in doc)
    assert "truncate_prompt_tokens" not in server.bodies[0]


def test_a_pair_over_the_window_is_split_and_the_piece_counts_with_its_best_part():
    rows = "\n".join(f"| Zeile {i} | {i} |" for i in range(1, 9))
    table = SimpleNamespace(owner_kind="table", owner_id=4, text=(
        "Tabelle 2: Werte\n| Name | Wert |\n| --- | --- |\n" + rows),
        provenance={})
    server = Server(lambda doc: 0.8 if "Zeile 7 " in doc else 0.2)
    window = Window(limit=110)
    ranker = rerank.Reranker(base_url="http://x", post=server, window=window)
    scores = ranker.scores(1, "q", [table])
    sent = server.bodies[0]["documents"]
    assert len(sent) > 1
    assert all(doc.startswith("Tabelle 2: Werte\n| Name | Wert |")
               for doc in sent)
    assert scores == [pytest.approx(0.8)]
    shown = [line for doc in sent for line in doc.split("\n")
             if line.startswith("| Zeile")]
    assert shown == rows.split("\n")


# -- 12: the window ---------------------------------------------------------------

def test_the_window_counts_bytes_where_they_fit_and_exactly_otherwise():
    asked = []

    def count(text):
        asked.append(text)
        return len(text.split())
    window = Window(limit=20, frame=5, count=count,
                    picture=lambda path: 4)
    assert window.fits("kurz") and asked == []          # bytes fit: not asked
    assert window.fits("wort " * 12) and asked          # 60 bytes, 12 tokens
    assert not window.fits("wort " * 16)                # 16 tokens, room 15
    assert not window.fits("wort " * 12, ("bild.png",))  # a picture takes 4


def test_a_text_only_embedder_is_never_shown_a_picture_input(monkeypatch, caplog):
    from docpipe import window as window_module
    from docpipe.chunking.embedding import (ApiIndexEmbedder, fits_of,
                                            window_of, without_pictures)
    from docpipe.embedding.api import ApiEmbedder
    monkeypatch.setattr(window_module, "served_limit", lambda *a, **k: 100)
    embedder = ApiIndexEmbedder(ApiEmbedder(
        base_url="http://stub", model="m", form="input", post=lambda *a: None))
    text = chunking.EmbeddingInput(
        embedding_type="table_text", pdf_name="plan", section_index=0,
        item_id="t", text="Zeile")
    picture = chunking.EmbeddingInput(
        embedding_type="table_vl", pdf_name="plan", section_index=0,
        item_id="t", text="Zeile", image="tables/t.png")
    fits = fits_of(window_of(embedder))
    # The break by construction: measured as it is, the picture has no cost.
    with pytest.raises(ValueError):
        fit_inputs([text, picture], fits)

    with caplog.at_level("WARNING"):
        kept = fit_inputs(without_pictures([text, picture], embedder), fits)

    assert kept == [text]
    assert "1 input(s) with a picture are not embedded" in caplog.text
    # An embedder that takes a picture keeps it.
    assert without_pictures([text, picture],
                            SimpleNamespace(text_only=False)) == [text, picture]


def test_the_local_embedders_window_counts_the_frame_of_the_template():
    from docpipe.chunking import qwen3_vl_embedding as qwen
    template = "system|Represent the input|user|.|assistant"

    class Processor:
        def apply_chat_template(self, conversations, **kwargs):
            # As the real one: a list of conversations gives a list of texts.
            return [template for _ in conversations]

        class tokenizer:
            def __call__(self, text, add_special_tokens=False):
                if isinstance(text, list):
                    return {"input_ids": [[0] * len(t.split("|")) for t in text]}
                return {"input_ids": [0] * len(text.split("|"))}
        tokenizer = tokenizer()

    embedder = object.__new__(qwen.Qwen3VLEmbedder)
    embedder.processor = Processor()
    embedder.max_length, embedder.max_pixels = 100, 28 * 28 * 4
    embedder.default_instruction = "Represent the input"

    window = embedder.window()

    assert window.frame == len(template.split("|"))
    assert window.limit == 100


def _status_corpus(tmp_path, format_1):
    """A profile over a database with a document, a section and a vector of
    it, and the processed folder of the document, merged."""
    from docpipe.artifacts import DOCUMENT_JSON
    tmp_path.mkdir(parents=True, exist_ok=True)
    db, doc_id = corpus(tmp_path, document())
    with EmbeddingWriter(db) as writer:
        writer.write("plan", [("section_text", 0, None, 7, 0, 0, 3, 1, 2)])
    if format_1:
        with sqlite3.connect(db) as conn:
            conn.executescript(
                'CREATE TABLE "Old" AS SELECT "faiss_id", "embedding_type", '
                '"owner_kind", "owner_id" FROM "Embeddings"; '
                'DROP TABLE "Embeddings"; ALTER TABLE "Old" RENAME TO "Embeddings";')
    folder = tmp_path / "processed" / "plan"
    (folder / DOCUMENT_JSON).parent.mkdir(parents=True)
    (folder / DOCUMENT_JSON).write_text("{}", encoding="utf-8")
    return SimpleNamespace(name="p", root=tmp_path, db_path=db,
                           processed_dir=tmp_path / "processed",
                           pdf_dir=tmp_path / "pdfs")


def test_a_database_of_format_1_reads_as_not_embedded_in_the_status(tmp_path):
    from docpipe import status
    old = status.collect(_status_corpus(tmp_path / "old", True))
    assert old.documents == ["plan"] and "plan" not in old.there["chunk"]
    # The gate can report: the same database of format 2 has the stage done.
    new = status.collect(_status_corpus(tmp_path / "new", False))
    assert "plan" in new.there["chunk"]


def test_the_embed_step_saves_the_index_before_it_deletes_the_rows_of_wholes(
        tmp_path, monkeypatch):
    from docpipe.chunking import pipeline
    db, doc_id = corpus(tmp_path, document())
    with EmbeddingWriter(db) as writer:
        writer.write("plan", [("section_text", 0, None, 7, 0, 0, 3, 1, 2)])
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE Embeddings SET piece = NULL")
    index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
    index.add_with_ids(np.ones((1, 4), dtype=np.float32),
                       np.array([7], dtype=np.int64))
    order: list = []
    real = pipeline.drop_wholes
    monkeypatch.setattr(pipeline, "load_embedder", lambda name: SimpleNamespace(
        text_only=False, window=lambda: Window(limit=100)))
    monkeypatch.setattr(pipeline, "load_or_create_index",
                        lambda path: (index, 0))
    monkeypatch.setattr(pipeline, "save_index",
                        lambda idx, path: order.append(("index", idx.ntotal)))
    monkeypatch.setattr(pipeline, "drop_wholes",
                        lambda path, ids: order.append(("database", 0))
                        or real(path, ids))
    monkeypatch.setattr(pipeline, "note_embedding", lambda *a: None)
    (tmp_path / "processed").mkdir()

    pipeline.run(tmp_path / "processed", db, tmp_path / "faiss.index",
                 step="embed")

    # The index without the whole vector is written first, the rows go after.
    assert order[:2] == [("index", 0), ("database", 0)]
