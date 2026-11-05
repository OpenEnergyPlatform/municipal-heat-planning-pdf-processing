"""A DOI, a year and, where the text yields none, the authors the document
does not print are looked up in its catalogue record: found first by the DOI
the corpus index holds, then by the DOI the harvest read, then by the title,
AND a record a DOI finds is taken without an author match, while one the
title finds counts only where two of its authors' family names stand among
the authors read, or one where either side names one author, AND never over
a value the document prints, AND not without a title read; such a row is
quoted by the read value it was found with and carries its record, AND is
graded D for its own reason, AND is a valid harvest row, AND once the
catalogue cannot be reached the run asks it no more.

A field its front pages give, or one looked up already, is not looked up,
AND one read only elsewhere is; the record is found with the title AND the
DOI of the front pages where they were read there, AND a record the title
finds is matched against the authors of the front pages where it read any
there (owner decision 2026-11-05).

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import io
import json
import sqlite3
import urllib.error
from pathlib import Path

import pytest

from docpipe.extraction import runner
from docpipe.extraction.pipeline import DocumentReport
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import CATALOGUE, LEVEL_D, trust
from profiles.scenarios import completion

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))

TITLE = "Socio-economic factors and future challenges of 1.5°C goal"
PASSAGE = {"document_id": 4, "page": 1, "section_number": 0,
           "section_title": TITLE, "title": TITLE, "parent_section": None,
           "block_id": None, "via": "survey", "owner_kind": "section",
           "owner_id": 48498}
DOI = "10.1080/17583004.2018.1477374"


def read(parameter, value, quote=None) -> dict:
    return {"parameter": parameter, "parameter_state": "read",
            "value": value, "value_raw": value, "quote": quote or value,
            "tier": "text_located", "provenance": dict(PASSAGE)}


AUTHORS = [read("publication_author", name, f"{name} Center for Research")
           for name in ("Jing-Yu Liu*", "Shinichiro Fujimori1",
                        "Kiyoshi Takahashi")]


def record(*authors) -> dict:
    return {"id": "https://openalex.org/W2806", "doi": f"https://doi.org/{DOI}",
            "display_name": "Socioeconomic factors and future challenges",
            "publication_year": 2018, "publication_date": "2018-06-11",
            "authorships": [{"author": {"display_name": name}}
                            for name in authors]}


RECORD = record("Jingyu Liu", "Shinichiro Fujimori", "Kiyoshi Takahashi")


def report_of(*rows) -> DocumentReport:
    report = DocumentReport(document_id=4)
    report.tuples.extend(rows)
    return report


def looked(found):
    asked = []

    def fetch(title):
        asked.append(title)
        return found
    return fetch, asked


def looked_up(report) -> dict:
    return {row["parameter"]: row for row in report.tuples
            if row.get("catalogue")}


@pytest.fixture(autouse=True)
def reachable():
    """Each case starts with a catalogue the run has not yet failed to reach."""
    completion.OFFLINE.clear()
    yield
    completion.OFFLINE.clear()


def no_doi(doi):
    raise AssertionError(f"a DOI was looked up: {doi}")


def test_a_record_two_read_authors_name_fills_doi_and_year_by_the_title():
    title = read("publication_title", TITLE)
    report = report_of(title, *AUTHORS)
    fetch, asked = looked(RECORD)
    outcome = completion.complete(report, SPEC, fetch=fetch)
    got = looked_up(report)
    assert asked == [TITLE] and outcome["outcome"] == "taken"
    assert got["publication_doi"]["value"] == DOI
    assert got["publication_date"]["value"] == "2018"
    for row in got.values():
        assert row["quote"] == title["quote"]
        assert row["provenance"]["owner_id"] == PASSAGE["owner_id"]
        assert row["catalogue"]["publication_date"] == "2018-06-11"
        verdict = trust(row)
        assert verdict["level"] == LEVEL_D
        assert CATALOGUE in verdict["reasons"]


def test_a_record_only_one_of_whose_authors_was_read_is_not_taken():
    report = report_of(read("publication_title", TITLE), *AUTHORS)
    found = record("Jingyu Liu", "Maria Rossi", "Ahmed Khan")
    outcome = completion.complete(report, SPEC, fetch=looked(found)[0])
    assert looked_up(report) == {}
    assert outcome["outcome"] == "authors" and outcome["matched"] == ["liu"]


def test_one_author_on_either_side_is_enough_and_must_be_that_one():
    one = read("publication_author", "A. Smith", "A. Smith, University")
    for authors, taken in ((("Alice Smith",), True), (("Bob Jones",), False),
                           (("Alice Smith", "Bob Jones"), True)):
        report = report_of(read("publication_title", TITLE), one)
        completion.complete(report, SPEC, fetch=looked(record(*authors))[0])
        assert bool(looked_up(report)) is taken, authors


def test_a_value_the_document_prints_goes_first():
    printed = read("publication_doi", "10.1000/printed",
                   "doi: 10.1000/printed, Carbon Management")
    report = report_of(read("publication_title", TITLE), *AUTHORS, printed)
    completion.complete(report, SPEC, fetch=looked(RECORD)[0],
                        fetch_doi=looked(RECORD)[0])
    assert [row["value"] for row in report.tuples
            if row["parameter"] == "publication_doi"] == ["10.1000/printed"]
    assert list(looked_up(report)) == ["publication_date"]
    year = read("publication_date", "2018", "Published 2018, Carbon Management")
    both = report_of(read("publication_title", TITLE), *AUTHORS, printed, year)
    fetch, asked = looked(RECORD)
    assert completion.complete(both, SPEC, fetch=fetch, fetch_doi=fetch) is None
    assert asked == []


def test_without_a_title_read_nothing_is_looked_up():
    fetch, asked = looked(RECORD)
    report = report_of(*AUTHORS)
    outcome = completion.complete(report, SPEC, fetch=fetch)
    assert asked == [] and outcome["outcome"] == "no_title"
    assert looked_up(report) == {}


def test_a_looked_up_row_is_a_valid_harvest_row():
    validators = runner._harvest_validators(SPEC)

    def errors(row):
        return list(validators[("tuple", row["parameter"])].iter_errors(
            {"kind": "tuple", **row}))
    title = read("publication_title", TITLE)
    assert errors(title) == []
    report = report_of(title, *AUTHORS)
    completion.complete(report, SPEC, fetch=looked(RECORD)[0])
    rows = list(looked_up(report).values())
    assert len(rows) == 2 and all(errors(row) == [] for row in rows)
    # A key the schema does not name is refused: the check can fail.
    wrong = dict(rows[0])
    wrong["catalog"] = wrong.pop("catalogue")
    assert errors(wrong)


def test_a_printed_doi_finds_the_record_without_authors_and_fills_them():
    title = read("publication_title", TITLE)
    printed = read("publication_doi", DOI, f"https://doi.org/{DOI} Received")
    report = report_of(title, printed)
    by_doi, asked = looked(RECORD)
    outcome = completion.complete(report, SPEC, fetch=no_doi, fetch_doi=by_doi)
    assert asked == [DOI] and outcome["key"] == completion.BY_READ_DOI
    got = [row for row in report.tuples if row.get("catalogue")]
    assert {row["parameter"] for row in got} == {"publication_date",
                                                 "publication_author"}
    assert [row["value"] for row in got
            if row["parameter"] == "publication_author"] == [
        "Jingyu Liu", "Shinichiro Fujimori", "Kiyoshi Takahashi"]
    for row in got:
        assert row["quote"] == printed["quote"]
        assert row["catalogue"]["key"] == completion.BY_READ_DOI
        assert trust(row)["level"] == LEVEL_D
    # The same record found by the title, with no author read, is not taken.
    by_title = report_of(read("publication_title", TITLE))
    outcome = completion.complete(by_title, SPEC, fetch=looked(RECORD)[0],
                                  fetch_doi=lambda doi: None)
    assert outcome["outcome"] == "authors" and looked_up(by_title) == {}


def test_the_index_doi_goes_before_the_printed_one_and_the_title():
    title = read("publication_title", TITLE)
    asked = []

    def by_doi(doi):
        asked.append(doi)
        return RECORD if doi == DOI else None
    report = report_of(title)
    outcome = completion.complete(report, SPEC, fetch=no_doi, fetch_doi=by_doi,
                                  catalogue_doi=f"https://doi.org/{DOI}")
    assert asked == [DOI] and outcome["key"] == completion.BY_INDEX_DOI
    assert looked_up(report)["publication_doi"]["value"] == DOI
    assert looked_up(report)["publication_doi"]["quote"] == title["quote"]
    # A DOI the paper cites, read as its own, is never asked before the index's.
    asked.clear()
    cited = read("publication_doi", "10.5281/zenodo.123", "doi:10.5281/zenodo.123")
    report = report_of(title, cited)
    outcome = completion.complete(report, SPEC, fetch=no_doi, fetch_doi=by_doi,
                                  catalogue_doi=DOI)
    assert asked == [DOI] and outcome["key"] == completion.BY_INDEX_DOI
    # An index DOI the catalogue does not hold gives way to the printed one.
    asked.clear()
    printed = read("publication_doi", DOI, f"doi:{DOI}")
    report = report_of(title, printed)
    outcome = completion.complete(report, SPEC, fetch=no_doi, fetch_doi=by_doi,
                                  catalogue_doi="10.1000/unknown")
    assert asked == ["10.1000/unknown", DOI]
    assert outcome["key"] == completion.BY_READ_DOI


def test_authors_from_the_record_never_join_authors_the_text_names():
    report = report_of(read("publication_title", TITLE), AUTHORS[0])
    completion.complete(report, SPEC, fetch=no_doi,
                        fetch_doi=looked(RECORD)[0], catalogue_doi=DOI)
    assert [row["value"] for row in report.tuples
            if row["parameter"] == "publication_author"] == [
        AUTHORS[0]["value"]]


def test_an_unreachable_catalogue_is_asked_no_more_in_the_run():
    def down(_key):
        raise urllib.error.URLError("timed out")
    fetch, asked = looked(RECORD)
    first = report_of(read("publication_title", TITLE), *AUTHORS)
    assert completion.complete(first, SPEC, fetch=down)["outcome"] == "offline"
    second = report_of(read("publication_title", TITLE), *AUTHORS)
    assert completion.complete(second, SPEC, fetch=fetch)["outcome"] == "offline"
    assert asked == [] and looked_up(second) == {}


def test_an_answer_with_an_error_is_no_reason_to_stop_asking():
    def refused(_key):
        raise urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO(b""))
    report = report_of(read("publication_title", TITLE), *AUTHORS)
    assert completion.complete(report, SPEC, fetch=refused)["outcome"] == "error"
    assert not completion.OFFLINE.is_set()
    fetch, asked = looked(RECORD)
    completion.complete(report, SPEC, fetch=fetch)
    assert asked == [TITLE]


def test_a_doi_the_catalogue_does_not_hold_is_no_hit_not_an_error(monkeypatch):
    def missing(_url):
        raise urllib.error.HTTPError("u", 404, "not found", {}, io.BytesIO(b""))
    monkeypatch.setattr(completion, "_get", missing)
    assert completion.by_doi(DOI) is None
    def busy(_url):
        raise urllib.error.HTTPError("u", 500, "error", {}, io.BytesIO(b""))
    monkeypatch.setattr(completion, "_get", busy)
    with pytest.raises(urllib.error.HTTPError):
        completion.by_doi(DOI)


def test_the_index_doi_is_the_one_the_index_holds_for_this_document():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE DocumentMeta (document INTEGER, doi TEXT)")
    conn.executemany("INSERT INTO DocumentMeta VALUES (?, ?)",
                     [(5, "10.1000/other"), (4, f"https://doi.org/{DOI}"),
                      (6, None)])
    assert completion.index_doi(conn, 4) == DOI
    assert completion.index_doi(conn, 6) is None
    assert completion.index_doi(conn, 7) is None
    # Another profile's DocumentMeta, without a doi column, holds none.
    other = sqlite3.connect(":memory:")
    other.execute("CREATE TABLE DocumentMeta (document INTEGER, ags TEXT)")
    assert completion.index_doi(other, 4) is None


# Promise: the run's database is opened by its path, read-only, for the index
# DOI of one document, AND a database that is not there gives none.
def test_the_index_doi_is_read_from_the_run_database_file(tmp_path):
    db = tmp_path / "run.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE DocumentMeta (document INTEGER, doi TEXT)")
    conn.executemany("INSERT INTO DocumentMeta VALUES (?, ?)",
                     [(5, "10.1000/other"), (4, f"https://doi.org/{DOI}")])
    conn.commit()
    conn.close()
    assert completion._index_doi_in(db, 4) == DOI
    assert completion._index_doi_in(db, 6) is None
    # the failure by construction: no database where the run says it is
    assert completion._index_doi_in(tmp_path / "missing.db", 4) is None
    assert not (tmp_path / "missing.db").exists()


def test_the_completer_hands_the_run_database_to_the_profile():
    got = {}

    class Profile:
        def component(self, module, attr):
            def complete(report, spec, **kwargs):
                got.update(kwargs)
            return complete if (module, attr) == ("completion",
                                                  "complete") else None
    runner.make_completer(Profile(), Path("run.db"))(report_of(), SPEC)
    assert got == {"db": Path("run.db")}


def test_without_a_given_index_doi_the_run_database_is_asked(monkeypatch):
    seen = []
    monkeypatch.setattr(completion, "_index_doi_in",
                        lambda db, document: seen.append((db, document)) or DOI)
    by_doi, asked = looked(RECORD)
    report = report_of(read("publication_title", TITLE))
    outcome = completion.complete(report, SPEC, fetch=no_doi, fetch_doi=by_doi,
                                  db="run.db")
    assert seen == [("run.db", 4)] and asked == [DOI]
    assert outcome["key"] == completion.BY_INDEX_DOI


# -- the front pages (owner decision 2026-11-05) ---------------------------------

def on(row: dict, page: int) -> dict:
    """*row* as read on *page*."""
    return {**row, "provenance": {**row["provenance"], "page": page}}


CITED = "10.1080/14693062.2020.1798734"


def by_index(doi):
    return RECORD if doi == DOI else None


def test_a_field_read_only_off_the_front_pages_is_looked_up():
    title, year = (read("publication_title", TITLE),
                   read("publication_date", "2018", "Published 2018"))
    cited = on(read("publication_doi", CITED, f"doi:{CITED}"), 29)
    report = report_of(title, *AUTHORS, year, cited)
    outcome = completion.complete(report, SPEC, fetch=no_doi,
                                  fetch_doi=by_index, catalogue_doi=DOI)
    assert outcome["filled"] == ["publication_doi"]
    assert looked_up(report)["publication_doi"]["value"] == DOI
    # the failure by construction: the same DOI on the title page is the
    # document's own, and nothing is looked up
    fetch, asked = looked(RECORD)
    front = report_of(title, *AUTHORS, year, on(cited, 1))
    assert completion.complete(front, SPEC, fetch=fetch, fetch_doi=fetch,
                               catalogue_doi=DOI) is None
    assert asked == []


def test_a_field_looked_up_already_is_not_looked_up_again():
    report = report_of(read("publication_title", TITLE), *AUTHORS)
    completion.complete(report, SPEC, fetch=looked(RECORD)[0])
    assert set(looked_up(report)) == {"publication_doi", "publication_date"}
    fetch, asked = looked(RECORD)
    assert completion.complete(report, SPEC, fetch=fetch) is None
    assert asked == []
    # the failure by construction: without the rows looked up it is asked
    fresh = report_of(*[row for row in report.tuples
                        if not row.get("catalogue")])
    assert completion.complete(fresh, SPEC, fetch=fetch)["outcome"] == "taken"
    assert asked == [TITLE]


def test_the_record_is_found_by_the_title_of_the_front_pages():
    other = on(read("publication_title", "Net Zero by 2050 (IEA)"), 12)
    report = report_of(read("publication_title", TITLE), other, on(other, 13),
                       *AUTHORS)
    fetch, asked = looked(RECORD)
    completion.complete(report, SPEC, fetch=fetch, fetch_doi=lambda doi: None)
    assert asked == [TITLE]
    # the failure by construction: without the title page's reading, the
    # other work's title is the key
    fetch, asked = looked(RECORD)
    completion.complete(report_of(other, on(other, 13), *AUTHORS), SPEC,
                        fetch=fetch, fetch_doi=lambda doi: None)
    assert asked == ["Net Zero by 2050 (IEA)"]


def test_the_record_is_found_by_the_doi_of_the_front_pages():
    title = read("publication_title", TITLE)
    own = read("publication_doi", DOI, f"doi:{DOI}")
    cited = on(read("publication_doi", CITED, f"doi:{CITED}"), 20)
    by_doi, asked = looked(RECORD)
    completion.complete(report_of(title, own, cited, on(cited, 21), *AUTHORS),
                        SPEC, fetch=no_doi, fetch_doi=by_doi)
    assert asked == [DOI]
    # the failure by construction: read twice, the cited DOI is the key
    # where the front pages print none
    by_doi, asked = looked(RECORD)
    completion.complete(report_of(title, cited, on(cited, 21), *AUTHORS),
                        SPEC, fetch=no_doi, fetch_doi=by_doi)
    assert asked == [CITED]


def test_a_record_the_title_finds_is_matched_against_the_front_page_authors():
    one = read("publication_author", "A. Smith", "A. Smith, University")
    others = [on(read("publication_author", name, f"{name} et al."), 12)
              for name in ("Carl Weber", "Dora Lang")]
    found = record("Alice Smith", "Xavier Roe")
    report = report_of(read("publication_title", TITLE), one, *others)
    completion.complete(report, SPEC, fetch=looked(found)[0],
                        fetch_doi=lambda doi: None)
    assert set(looked_up(report)) == {"publication_doi", "publication_date"}
    # the failure by construction: the same three names on the front page
    # ask for two family names, and only one of them stands in the record
    report = report_of(read("publication_title", TITLE), one,
                       *[on(row, 1) for row in others])
    outcome = completion.complete(report, SPEC, fetch=looked(found)[0],
                                  fetch_doi=lambda doi: None)
    assert outcome["outcome"] == "authors" and looked_up(report) == {}
