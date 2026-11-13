"""The sync step (docpipe/chunking/sync.py): a document processed again goes
into the database under the numbers its entries have, and only the vectors
whose input changed leave the indexes.

Each test writes one document with the db step's own insert and gives every
input a vector, as the db and embed steps leave a plan, then writes a new
document.json and syncs."""
from __future__ import annotations

import copy
import json
import sqlite3

import faiss
import numpy as np
import pytest

from docpipe.artifacts import DOCUMENT_JSON
from docpipe.chunking import sync as sync_module
from docpipe.chunking.chunking import build_embedding_inputs
from docpipe.chunking.database import EmbeddingWriter, _insert_sections, ids_of_document
from docpipe.chunking.embedding import index_ids
from docpipe.chunking.reembed import record_path
from docpipe.chunking.sync import align, run_sync
from docpipe.store import schema as store_schema


def same(caption, content, block_id):
    """Captions as the stage wrote them."""
    return caption


def section(title, content, *, tables=(), page=1):
    return {"title": title, "content": content, "page_number": page,
            "pages": [page], "segments": [{"kind": "text", "page": page, "text": content}],
            "tables": list(tables), "figures": []}


def table(block_id, caption, markdown, page=1):
    return {"id": block_id, "caption": caption, "markdown": markdown,
            "path": f"tables/{block_id}.png", "page_number": page}


HEAD = "| Jahr | MWh |\n| --- | --- |"


class Corpus:
    """One document in a database and an index, each input with a vector."""

    def __init__(self, tmp_path, doc):
        self.root = tmp_path / "processed"
        self.dir = self.root / "plan"
        (self.dir / "results").mkdir(parents=True)
        self.db = tmp_path / "corpus.db"
        conn = sqlite3.connect(self.db)
        store_schema.apply(conn)
        conn.execute("INSERT INTO Documents (filename) VALUES ('plan.pdf')")
        self.doc_id = conn.execute("SELECT id FROM Documents").fetchone()[0]
        _insert_sections(self.doc_id, doc, conn)
        # What enrich_caption records for a caption it keeps.
        conn.execute("UPDATE Tables SET caption_source = 'stage'")
        conn.commit()
        conn.close()
        inputs = build_embedding_inputs(doc, "plan", self.dir)
        with EmbeddingWriter(self.db) as writer:
            writer.write("plan", [(i.embedding_type, i.section_index, i.item_id, n)
                                  for n, i in enumerate(inputs)])
        self.index = tmp_path / "faiss.index"
        self.save(self.index, len(inputs))
        self.write(doc)

    @staticmethod
    def save(path, n):
        index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
        index.add_with_ids(np.ones((n, 4), dtype=np.float32),
                           np.arange(n, dtype=np.int64))
        faiss.write_index(index, str(path))

    def write(self, doc):
        (self.dir / DOCUMENT_JSON).write_text(json.dumps(doc), encoding="utf-8")

    def ids(self):
        with sqlite3.connect(self.db) as conn:
            return ids_of_document(conn, self.doc_id)

    def held(self, path=None):
        return set(index_ids(faiss.read_index(str(path or self.index))))

    def sections(self):
        """{title: (row id, number)}"""
        with sqlite3.connect(self.db) as conn:
            return {title: (row, number) for row, number, title in conn.execute(
                "SELECT id, section_number, title FROM Sections WHERE document = ?",
                (self.doc_id,))}

    def tables(self):
        """{block id: (row id, section row id, caption, caption source)}"""
        with sqlite3.connect(self.db) as conn:
            return {block: (row, sec, caption, source)
                    for row, sec, block, caption, source in conn.execute(
                        "SELECT id, section, block_id, caption, caption_source FROM Tables")}

    def sync(self, *paths, resolve=same, **kwargs):
        return run_sync(self.root, self.db, [self.index, *paths],
                        resolve=resolve, **kwargs)


def test_an_unchanged_document_keeps_every_row_and_every_vector(tmp_path):
    doc = {"sections": [
        section("Wärme", "Bedarf [p1_tbl0]",
                tables=[table("p1_tbl0", "Tabelle 1: Bedarf", HEAD + "\n| 2025 | 10 |")]),
        section("Ende", "Schluss")]}
    corpus = Corpus(tmp_path, doc)
    rows, tables, ids = corpus.sections(), corpus.tables(), corpus.ids()

    report = corpus.sync()

    assert report.changed == [] and not report.dropped
    assert corpus.sections() == rows and corpus.tables() == tables
    assert corpus.ids() == ids and corpus.held() == set(ids.values())


def test_a_joined_part_goes_with_its_vectors_and_its_start_is_embedded_again(tmp_path):
    old = {"sections": [
        section("Wärme", "Bedarf [p1_tbl0]",
                tables=[table("p1_tbl0", "Tabelle 1: Bedarf", HEAD + "\n| 2025 | 10 |")]),
        section("Fortsetzung", "Weiter [p2_tbl0]", page=2,
                tables=[table("p2_tbl0", "Tabelle 1 (Forts.)", HEAD + "\n| 2030 | 8 |", page=2)])]}
    corpus = Corpus(tmp_path, old)
    tables, ids = corpus.tables(), corpus.ids()
    new = copy.deepcopy(old)
    new["sections"][0]["tables"][0]["markdown"] += "\n| 2030 | 8 |"
    new["sections"][1]["tables"] = []
    corpus.write(new)

    corpus.sync()

    # The part's own vector, its start's (new rows), and the section whose
    # placeholder no longer names a table go; the rest stays.
    gone = {ids[("table_text", 1, "p2_tbl0")], ids[("table_text", 0, "p1_tbl0")],
            ids[("section_text", 1, None)]}
    assert set(ids.values()) - set(corpus.ids().values()) == gone
    assert corpus.held() == set(ids.values()) - gone
    assert corpus.tables()["p1_tbl0"][0] == tables["p1_tbl0"][0]
    assert "p2_tbl0" not in corpus.tables()
    # A second run finds nothing left to write.
    again = corpus.sync()
    assert again.changed == [] and not again.dropped


def test_a_section_put_in_front_moves_the_numbers_and_keeps_rows_and_vectors(tmp_path):
    old = {"sections": [section("A", "eins"), section("B", "zwei")]}
    corpus = Corpus(tmp_path, old)
    rows, ids = corpus.sections(), corpus.ids()
    corpus.write({"sections": [section("Titel", "Vorne"), *old["sections"]]})

    corpus.sync()

    now = corpus.sections()
    assert now["A"] == (rows["A"][0], 1) and now["B"] == (rows["B"][0], 2)
    assert now["Titel"][0] not in {row for row, _ in rows.values()}
    assert set(ids.values()) <= set(corpus.ids().values())
    assert corpus.held() == set(ids.values())


def test_a_changed_section_keeps_its_row_and_loses_only_its_changed_vector(tmp_path):
    old = {"sections": [section("A", "eins"), section("B", "zwei"), section("C", "drei")]}
    corpus = Corpus(tmp_path, old)
    rows, ids = corpus.sections(), corpus.ids()
    new = copy.deepcopy(old)
    new["sections"][1]["content"] = "zwei, neu gelesen"
    corpus.write(new)

    corpus.sync()

    assert corpus.sections() == rows
    assert set(ids.values()) - set(corpus.ids().values()) == {ids[("section_text", 1, None)]}
    assert ids[("section_title", 1, None)] in corpus.held()


def test_a_gone_section_takes_its_vectors_and_the_next_keeps_row_and_vectors(tmp_path):
    old = {"sections": [section("A", "eins"), section("B", "zwei"), section("C", "drei")]}
    corpus = Corpus(tmp_path, old)
    rows, ids = corpus.sections(), corpus.ids()
    corpus.write({"sections": [old["sections"][0], old["sections"][2]]})

    corpus.sync()

    now = corpus.sections()
    assert "B" not in now and now["C"] == (rows["C"][0], 1)
    assert set(ids.values()) - corpus.held() == {
        ids[("section_text", 1, None)], ids[("section_title", 1, None)]}


def test_a_table_moving_to_another_section_keeps_its_row_and_its_vector(tmp_path):
    t = table("p1_tbl0", "Tabelle 1: Bedarf", HEAD + "\n| 2025 | 10 |")
    old = {"sections": [section("Eins", "Text [p1_tbl0]", tables=[t]),
                        section("Zwei", "Mehr")]}
    corpus = Corpus(tmp_path, old)
    rows, tables, ids = corpus.sections(), corpus.tables(), corpus.ids()
    corpus.write({"sections": [section("Eins", "Text"),
                               section("Zwei", "Mehr [p1_tbl0]", tables=[t])]})

    corpus.sync()

    row, sec, _caption, _source = corpus.tables()["p1_tbl0"]
    assert row == tables["p1_tbl0"][0] and sec == rows["Zwei"][0]
    assert ids[("table_text", 0, "p1_tbl0")] in corpus.held()
    assert set(ids.values()) - corpus.held() == {
        ids[("section_text", 0, None)], ids[("section_text", 1, None)]}


def test_a_dry_run_counts_and_writes_nothing(tmp_path):
    old = {"sections": [section("A", "eins"), section("B", "zwei")]}
    corpus = Corpus(tmp_path, old)
    corpus.write({"sections": [section("A", "eins, neu")]})
    db, index = corpus.db.read_bytes(), corpus.index.read_bytes()

    report = corpus.sync(dry_run=True)

    assert report.changed == ["plan"] and sum(report.dropped.values()) == 3
    assert corpus.db.read_bytes() == db and corpus.index.read_bytes() == index


def test_a_further_index_loses_the_same_vectors_and_its_record_says_incomplete(tmp_path):
    old = {"sections": [section("A", "eins"), section("B", "zwei")]}
    corpus = Corpus(tmp_path, old)
    ids = corpus.ids()
    further = tmp_path / "faiss_vllm.index"
    Corpus.save(further, len(ids))
    record_path(further).write_text(json.dumps({"complete": True, "vectors": len(ids)}),
                                    encoding="utf-8")
    new = copy.deepcopy(old)
    new["sections"][0]["content"] = "eins, neu"
    corpus.write(new)

    corpus.sync(further)

    gone = {ids[("section_text", 0, None)]}
    assert corpus.held() == corpus.held(further) == set(ids.values()) - gone
    record = json.loads(record_path(further).read_text(encoding="utf-8"))
    assert record["complete"] is False and record["vectors"] == len(ids) - 1


def test_the_indexes_lose_the_vectors_before_the_database_is_written(tmp_path, monkeypatch):
    old = {"sections": [section("A", "eins"), section("B", "zwei")]}
    corpus = Corpus(tmp_path, old)
    ids = corpus.ids()
    new = copy.deepcopy(old)
    new["sections"][1]["content"] = "zwei, neu"
    corpus.write(new)

    def dies(conn, plan):
        raise RuntimeError("killed")

    monkeypatch.setattr(sync_module, "apply_plan", dies)
    with pytest.raises(RuntimeError):
        corpus.sync()
    gone = ids[("section_text", 1, None)]
    assert gone not in corpus.held() and corpus.ids() == ids
    monkeypatch.undo()

    corpus.sync()

    assert set(ids.values()) - set(corpus.ids().values()) == {gone}


def test_a_caption_is_compared_and_written_as_the_database_holds_it(tmp_path):
    t = table("p1_tbl0", "Hinweis: Wegen der Rundung", HEAD + "\n| 2025 | 10 |")
    doc = {"sections": [section("Wärme", "Tabelle 3: Bedarf [p1_tbl0]", tables=[t])]}
    corpus = Corpus(tmp_path, doc)
    with sqlite3.connect(corpus.db) as conn:     # what enrich_caption left
        conn.execute("UPDATE Tables SET caption = 'Tabelle 3: Bedarf', "
                     "caption_source = 'section_text'")
    ids = corpus.ids()

    def title(caption, content, block_id):
        return "Tabelle 3: Bedarf" if caption.startswith("Hinweis") else caption

    kept = corpus.sync(resolve=title)

    assert kept.changed == [] and corpus.held() == set(ids.values())
    assert corpus.tables()["p1_tbl0"][2:] == ("Tabelle 3: Bedarf", "section_text")

    corpus.sync(resolve=same)

    assert corpus.tables()["p1_tbl0"][2:] == ("Hinweis: Wegen der Rundung", "stage")
    assert ids[("table_text", 0, "p1_tbl0")] not in corpus.held()


@pytest.mark.parametrize("old, new, rows", [
    ("abc", "xabc", [None, 0, 1, 2]),
    ("abc", "ac", [0, 2]),
    ("ab", "aB", [0, 1]),
    ("abc", "axyc", [0, 1, None, 2]),
])
def test_a_new_section_takes_the_row_of_its_equal_or_of_its_place_in_a_changed_stretch(old, new, rows):
    assert align(list(old), list(new)) == rows
