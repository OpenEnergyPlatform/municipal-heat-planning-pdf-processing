"""A DOI and a year the document does not print are looked up by the title
it was read with: the first record the catalogue finds counts only where two
of its authors' family names stand among the authors read, or one where
either side names one author, AND never over a value the document prints,
AND not without a title read; such a row is quoted by the title it was
looked up with and carries its record, AND is graded D for its own reason,
AND is a valid harvest row.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

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
    completion.complete(report, SPEC, fetch=looked(RECORD)[0])
    assert [row["value"] for row in report.tuples
            if row["parameter"] == "publication_doi"] == ["10.1000/printed"]
    assert list(looked_up(report)) == ["publication_date"]
    year = read("publication_date", "2018", "Published 2018, Carbon Management")
    both = report_of(read("publication_title", TITLE), printed, year)
    fetch, asked = looked(RECORD)
    assert completion.complete(both, SPEC, fetch=fetch) is None
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
