"""A field's pieces are ordered with HyDE sentences and not with its
label: one written for each document by the model, from the field's label,
description and list names AND from what the document says of itself (its
municipality or title), AND its label only where no sentence could be
written; the sentence of a list parameter is written with the names of its
list (owner decisions 2026-11-05, 2026-11-08 and 2026-11-09)."""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import runner
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.addressed import Orders, Plan
from docpipe.extraction.pipeline import Source
from profiles.scenarios import extraction as scenarios_extraction

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))
BY_URI = {parameter.uri: parameter for parameter in SPEC.parameters}
TITLE = BY_URI["publication_title"]
DIVISION = BY_URI["study_sector_division"]
PLAN = Plan(151, [Source("table", 7, "| A | B |\n| --- | --- |\n| x | 1 |",
                         {"document_id": 151, "page": 2}),
                  Source("section", 55052, "Emissions by sector follow the CRF.",
                         {"document_id": 151, "page": 3})], {}, 8)


def ordering():
    """An order of the pieces that puts the section first, and the
    sentences it was asked with."""
    asked = []

    def order(document_id, sentences, chunks):
        asked.append(list(sentences))
        return sorted(chunks, key=lambda c: c.passage.kind != "section")
    return order, asked


def order_of(order, probes=None) -> list:
    got = Orders(order, probes or (lambda parameter, document: []),
                 None)(PLAN, [DIVISION], 8)
    return got[DIVISION.uri]


def test_the_pieces_are_ordered_with_the_sentences_and_all_kept():
    order, asked = ordering()
    sentence = "Emissions are reported by sector following the CRF."
    out = order_of(order, lambda parameter, document: [sentence])
    assert asked == [[sentence]]
    # The piece the order put first, the other after it, none left out.
    assert [key[:2] for key in out] == [("section", 55052), ("table", 7)]


def test_without_a_sentence_the_order_falls_back_to_the_label():
    order, asked = ordering()
    order_of(order, lambda parameter, document: [])
    order_of(order)
    assert asked == [[DIVISION.label], [DIVISION.label]]


def test_every_field_is_written_per_document_with_what_it_says_of_itself():
    written = []

    def write(parameter, context):
        written.append((parameter.uri, context))
        return [f"{parameter.uri} {context}"]
    probes = runner.make_seek_probes(
        lambda document: {"name": f"Paper {document}"}, write)
    assert probes(TITLE, 4) != probes(TITLE, 28)
    # the failure by construction: a field about the values, not about the
    # document, is written for each document all the same
    assert probes(DIVISION, 4) != probes(DIVISION, 28)
    assert written == [("publication_title", {"name": "Paper 4"}),
                       ("publication_title", {"name": "Paper 28"}),
                       ("study_sector_division", {"name": "Paper 4"}),
                       ("study_sector_division", {"name": "Paper 28"})]


def test_a_list_parameter_is_written_with_its_names_a_string_one_without():
    names = runner.phrase_payload(DIVISION).get("names") or []
    assert len(names) == len(DIVISION.vocabulary)
    assert "names" not in runner.phrase_payload(TITLE)
    assert runner.phrase_payload(TITLE, {"name": "Paper 4"})["document"] == {
        "name": "Paper 4"}


def test_a_publication_says_its_title_from_the_index():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE DocumentMeta (document INTEGER, title TEXT)")
    conn.executemany("INSERT INTO DocumentMeta VALUES (?, ?)",
                     [(5, "Another paper"), (4, " Net zero by 2050 ")])
    assert scenarios_extraction.document_context(conn, 4) == {
        "name": "Net zero by 2050"}
    assert scenarios_extraction.document_context(conn, 6) == {}
    assert scenarios_extraction.document_context(
        sqlite3.connect(":memory:"), 4) == {}


# Promise: the run's database is opened by its path, read-only, for what a
# document says of itself, AND without a database or without the profile's
# function the context is {}.
def test_the_document_context_is_read_from_the_run_database_file(tmp_path):
    db = tmp_path / "run.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE DocumentMeta (document INTEGER, title TEXT)")
    conn.execute("INSERT INTO DocumentMeta VALUES (4, 'Net zero by 2050')")
    conn.commit()
    conn.close()
    context_of = runner.document_context_of(
        db, scenarios_extraction.document_context)
    assert context_of(4) == {"name": "Net zero by 2050"}
    assert context_of(6) == {}

    def writes(conn, document_id):
        conn.execute("CREATE TABLE written (x)")
    with pytest.raises(sqlite3.OperationalError):
        runner.document_context_of(db, writes)(4)
    # the failure by construction: no database, no function of the profile
    assert runner.document_context_of(
        None, scenarios_extraction.document_context)(4) == {}
    assert runner.document_context_of(db, None)(4) == {}


# Promise: the request that writes a search sentence goes into the trace of
# the document that asked for it, as `phrase_ask` with its tokens, AND each
# document asks its own.
def test_a_search_sentence_request_is_traced_for_its_document(monkeypatch):
    events = []
    monkeypatch.setattr(
        runner.trace, "event",
        lambda kind, document=None, /, **fields: events.append(
            (kind, document, fields.get("prompt_tokens"))))
    said = "Emissions are reported by CRF sector."
    reply = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content=json.dumps({"phrase": said})))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: reply)))
    monkeypatch.setattr(runner, "_client", lambda: client)
    probes = runner.make_seek_probes()
    assert probes(DIVISION, 4) == probes(DIVISION, 28) == [said]
    assert [e for e in events if e[0].endswith("_ask")] == [
        ("phrase_ask", 4, 11), ("phrase_ask", 28, 11)]


# Promise: an order is kept under what writes its sentences, AND one kept
# from sentences written otherwise is made again.
def test_an_order_kept_from_sentences_written_otherwise_is_made_again(
        tmp_path):
    order, asked = ordering()

    def made(written):
        Orders(order, lambda parameter, document: ["Sentence."], tmp_path,
               written=written)(PLAN, [DIVISION], 8)
        return len(asked)
    assert made("document:a") == 1
    assert made("document:a") == 1          # kept, not made again
    assert made("document:b") == 2
