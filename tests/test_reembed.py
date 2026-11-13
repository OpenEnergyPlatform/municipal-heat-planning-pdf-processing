"""The messages form of the embedding endpoint and the re-embedding of an
index under the ids it already has (docpipe/embedding/api.py,
docpipe/chunking/reembed.py).

Promises:
- the messages form sends an item as the chat the model's own code builds:
  the instruction as the system turn, the picture before the text, "NULL"
  for an empty item, an empty assistant turn the request continues; and it
  hands back unit vectors; the input form still refuses a picture;
- a re-embedding puts every input whose key the database maps into the new
  file under that id, AND counts the ids without an input, AND the inputs
  without an id, AND takes an id once, AND skips the ids the file holds;
- a batch the embedder fails is tried input by input, and only an input that
  fails alone is missed;
- a file that exists without a record is refused, and so is an embedder that
  leaves pictures out, before anything is written;
- the database gives each key of one document its id, and none of another.
"""
import sqlite3

import faiss
import numpy as np
import pytest

from docpipe.chunking.chunking import EmbeddingInput
from docpipe.chunking.database import ids_of_document
from docpipe.chunking.embedding import Unembedded, index_ids
from docpipe.chunking.reembed import (check_target, embed_into, plan,
                                      record_path, run_reembed)
from docpipe.embedding.api import DEFAULT_INSTRUCTION, ApiEmbedder, conversation

DIM = 4


def item(etype, section, item_id=None, text="t", image=None):
    return EmbeddingInput(embedding_type=etype, pdf_name="plan", section_index=section,
                          item_id=item_id, text=text, image=image)


class Fake:
    """An embedder whose vector names its text, and that fails on a text."""
    text_only = False
    model = "fake"

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.calls = []

    def process(self, items):
        self.calls.append([it["text"] for it in items])
        if self.fail_on and any(it["text"] == self.fail_on for it in items):
            raise RuntimeError("cannot serve")
        rows = []
        for it in items:
            seed = sum(map(ord, it["text"])) % 97 + 1
            rows.append([seed, 1.0, float("image" in it), 0.5])
        return np.asarray(rows, dtype=np.float32)


def new_index():
    return faiss.IndexIDMap(faiss.IndexFlatIP(DIM))


def test_the_messages_form_is_the_chat_of_the_models_own_code():
    plain = conversation({"text": "Wärmebedarf 2045"})
    assert [turn["role"] for turn in plain] == ["system", "user", "assistant"]
    assert plain[0]["content"][0]["text"] == DEFAULT_INSTRUCTION
    assert plain[1]["content"] == [{"type": "text", "text": "Wärmebedarf 2045"}]
    assert plain[2]["content"][0]["text"] == ""

    picture = conversation({"text": "Abbildung 3", "image": "https://x/a.png",
                            "instruction": "Find the table"})
    assert [part["type"] for part in picture[1]["content"]] == ["image_url", "text"]
    assert picture[0]["content"][0]["text"] == "Find the table."

    assert conversation({})[1]["content"] == [{"type": "text", "text": "NULL"}]


def test_the_messages_form_continues_the_assistant_turn_and_returns_unit_vectors():
    sent = []

    def post(body):
        sent.append(body)
        return {"data": [{"embedding": [3.0, 4.0, 0.0, 0.0]}]}

    embedder = ApiEmbedder(base_url="http://localhost:1/v1", model="m",
                           form="messages", post=post)
    vectors = embedder.embed([{"text": "a"}, {"text": "b", "image": "https://x/b.png"}])
    assert len(sent) == 2 and all(body["continue_final_message"] for body in sent)
    assert all("messages" in body and "input" not in body for body in sent)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert not embedder.text_only


def test_the_input_form_still_refuses_a_picture():
    embedder = ApiEmbedder(base_url="http://localhost:1/v1", model="m", form="input")
    assert embedder.text_only
    with pytest.raises(ValueError):
        embedder.embed([{"text": "a", "image": "https://x/a.png"}])


def test_every_mapped_input_goes_in_under_its_own_id():
    inputs = [item("section_text", 0), item("table_vl", 1, "p2_tbl0", "Tabelle", "img.png"),
              item("figure_text", 2, "p3_fig1", "Abbildung")]
    ids = {("section_text", 0, None): 17, ("table_vl", 1, "p2_tbl0"): 4,
           ("figure_text", 2, "p3_fig1"): 230}
    pending, no_id, no_input = plan(inputs, ids, done=set())
    index, missed = new_index(), Unembedded()
    assert embed_into(index, pending, Fake(), missed) == 3
    assert sorted(index_ids(index)) == [4, 17, 230]
    assert not no_id and not no_input and not missed


def test_ids_without_an_input_and_inputs_without_an_id_are_counted_not_filled():
    inputs = [item("section_text", 0), item("figure_vl", 5, "p9_fig0", "Bild", "f.png")]
    ids = {("section_text", 0, None): 1, ("table_text", 3, "p4_tbl2"): 2}
    pending, no_id, no_input = plan(inputs, ids, done=set())
    assert [faiss_id for faiss_id, _ in pending] == [1]
    assert no_id == {"figure_vl": 1}
    assert no_input == {"table_text": 1}


def test_an_id_is_taken_once_and_ids_the_file_holds_are_skipped():
    twice = [item("section_text", 0, text="a"), item("section_text", 0, text="b"),
             item("section_title", 0, text="c")]
    ids = {("section_text", 0, None): 8, ("section_title", 0, None): 9}
    pending, _, _ = plan(twice, ids, done={9})
    assert [(faiss_id, inp.text) for faiss_id, inp in pending] == [(8, "a")]


def test_a_failed_batch_is_tried_input_by_input():
    inputs = [item("section_text", s, text=text) for s, text in enumerate("abcd")]
    ids = {("section_text", s, None): 100 + s for s in range(4)}
    pending, _, _ = plan(inputs, ids, done=set())
    index, missed, fake = new_index(), Unembedded(), Fake(fail_on="c")
    assert embed_into(index, pending, fake, missed, batch_size=4) == 3
    assert sorted(index_ids(index)) == [100, 101, 103]
    assert len(missed) == 1 and missed.by_type == {"section_text": 1}


def test_a_file_without_a_record_is_refused(tmp_path):
    live = tmp_path / "faiss.index"
    live.write_bytes(b"an index some run reads")
    with pytest.raises(ValueError):
        check_target(live)
    assert live.read_bytes() == b"an index some run reads"
    record_path(live).write_text("{}", encoding="utf-8")
    check_target(live)                       # begun by a re-embedding: continued
    check_target(tmp_path / "new.index")     # a new file


def test_an_embedder_that_leaves_pictures_out_is_refused_before_writing(tmp_path):
    target = tmp_path / "new.index"
    blind = Fake()
    blind.text_only = True
    with pytest.raises(ValueError):
        run_reembed(tmp_path, tmp_path / "none.db", target, embedder=blind)
    assert not target.exists() and not record_path(target).exists()


def test_the_database_gives_each_key_of_one_document_its_id():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER, section_number INTEGER);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT);
        CREATE TABLE Embeddings (owner_kind TEXT, owner_id INTEGER, embedding_type TEXT, faiss_id INTEGER);
        INSERT INTO Sections VALUES (1, 7, 0), (2, 7, 1), (3, 8, 0);
        INSERT INTO Tables VALUES (10, 2, 'p2_tbl0');
        INSERT INTO Images VALUES (20, 2, 'p2_fig1');
        INSERT INTO Embeddings VALUES
            ('section', 1, 'section_text', 11), ('section', 1, 'section_title', 12),
            ('table', 10, 'table_vl', 13), ('figure', 20, 'figure_text', 14),
            ('section', 3, 'section_text', 99);
    """)
    assert ids_of_document(db, 7) == {
        ("section_text", 0, None): 11, ("section_title", 0, None): 12,
        ("table_vl", 1, "p2_tbl0"): 13, ("figure_text", 1, "p2_fig1"): 14}
