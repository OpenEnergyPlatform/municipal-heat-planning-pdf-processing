"""A parameter the survey named no passage for is searched with HyDE
sentences and not with its label: one written for this document from what it
says of itself for a field about the document itself, AND one written once
per run from label, description and list names for any other, AND its label
only where no sentence could be written; the sentence of a list parameter is
written with the names of its list, AND both profiles declare which fields
are about the document itself (owner decision 2026-11-05)."""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import runner
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.surveyed import sought_survey
from docpipe.extraction.survey import Found
from profiles.kwp import extraction as kwp_extraction
from profiles.scenarios import extraction as scenarios_extraction

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))
BY_URI = {parameter.uri: parameter for parameter in SPEC.parameters}
TITLE = BY_URI["publication_title"]
DIVISION = BY_URI["study_sector_division"]
PASSAGE = SimpleNamespace(owner_kind="section", owner_id=55052)


def ranking():
    asked = []

    def rank(document_id, probes, exclude):
        asked.append(list(probes))
        return [PASSAGE]
    return rank, asked


def test_the_search_ranks_with_the_sentences_and_names_the_first_passage():
    rank, asked = ranking()
    sentence = "Emissions are reported by sector following the CRF."
    out = sought_survey(Found(True), rank, 151, [DIVISION],
                        lambda parameter, document: [sentence])
    assert asked == [[sentence]]
    assert out.passages_of(DIVISION.uri) == [("section", 55052)]


def test_without_a_sentence_the_search_falls_back_to_the_label():
    rank, asked = ranking()
    sought_survey(Found(True), rank, 151, [DIVISION],
                  lambda parameter, document: [])
    sought_survey(Found(True), rank, 151, [DIVISION])
    assert asked == [[DIVISION.label], [DIVISION.label]]


def test_an_own_field_is_written_per_document_any_other_once_per_run():
    written = []

    def write(parameter, context):
        written.append((parameter.uri, context))
        return [f"{parameter.uri} {context}"]
    probes = runner.make_seek_probes(
        ("publication_title",),
        lambda document: {"name": f"Paper {document}"}, write)
    first, second = probes(TITLE, 4), probes(TITLE, 28)
    assert first != second
    assert probes(DIVISION, 4) == probes(DIVISION, 28)
    assert written == [("publication_title", {"name": "Paper 4"}),
                       ("publication_title", {"name": "Paper 28"}),
                       ("study_sector_division", None)]


def test_a_list_parameter_is_written_with_its_names_a_string_one_without():
    names = runner.phrase_payload(DIVISION).get("names") or []
    assert len(names) == len(DIVISION.vocabulary)
    assert "names" not in runner.phrase_payload(TITLE)
    assert runner.phrase_payload(TITLE, {"name": "Paper 4"})["document"] == {
        "name": "Paper 4"}


def test_both_profiles_declare_the_fields_about_the_document_itself():
    own = set(scenarios_extraction.FRONT_PAGE_PARAMETERS)
    assert {"publication_title", "publication_date", "publication_doi",
            "publication_author"} <= own <= set(BY_URI)
    assert tuple(kwp_extraction.FRONT_PAGE_PARAMETERS) == ()


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
# the document that asked for it, as `phrase_ask` with its tokens, AND a
# sentence kept for the run is asked once.
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
        ("phrase_ask", 4, 11)]
