"""The two censuses scripts/harvest_lists.py pulls out of a harvest: every
unit as a plan writes it, checked against the unit chosen for it, and every
organisation spelling, checked against the IRI key it collapses onto.

No model, no database, no GPU. Uses the real kwp spec so unit_factor and the
organisation normalisation are the ones a run actually applies.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.extraction.spec import load as load_spec      # noqa: E402
from scripts import harvest_lists as hl                    # noqa: E402

SPEC_PATH = Path(__file__).resolve().parent.parent / "profiles" / "kwp" / "extraction_spec.json"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC_PATH)


@pytest.fixture(scope="module")
def normalise():
    return hl.organisation_normaliser(SPEC_PATH)


def _tuple(parameter, value, unit, unit_raw, quote="Auszug aus der Tabelle",
          page=12):
    return {"kind": "tuple", "parameter": parameter, "value": value,
            "unit": unit, "unit_raw": unit_raw, "value_target": value,
            "tier": "text_located", "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": "table",
                          "owner_id": 7, "page": page}}


def _refusal(parameter, reason, claim):
    return {"kind": "refusal", "parameter": parameter, "reason": reason,
            "claim": claim, "owner": ["table", 7]}


def _org_tuple(value, value_raw=None, quote="Impressum: Verfasser"):
    row = {"kind": "tuple", "parameter": "planning_organisation",
           "value": value, "quote": quote, "unit": "", "unit_raw": "",
           "tier": "text_located",
           "provenance": {"document_id": 1, "owner_kind": "section",
                          "owner_id": 3, "page": 1}}
    if value_raw is not None:
        row["value_raw"] = value_raw
    return row


def _harvest(tmp_path, name, rows):
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    return path


def _only(rows, **filters):
    hits = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    assert len(hits) == 1, f"expected exactly one row matching {filters}, got {hits}"
    return hits[0]


# --- units.csv --------------------------------------------------------------

def test_a_wording_beside_the_entry_it_was_read_as(tmp_path, spec):
    """The census row: what the plan wrote, which entry the model read it as,
    and whether the wording is itself an entry. A per-square-metre wording
    read as an absolute entry is a row for a person to look at; the script
    counts it and judges nothing."""
    _harvest(tmp_path, "plan_a", [
        _tuple("energy_consumption", 400.0, "kWh/a", "kWh/m²a")])
    files = hl.harvest_files(tmp_path)
    row = _only(hl.unit_rows(files, spec), parameter="energy_consumption")
    assert row["unit_as_written"] == "kWh/m²a"
    assert row["unit_chosen"] == "kWh/a"
    assert row["chosen_factor"] == 0.001
    assert row["listed"] == "no"
    assert row["tuples"] == 1 and row["refusals"] == 0
    assert row["example_plan"] == "plan_a" and row["example_page"] == 12


def test_a_wording_that_is_an_entry_is_listed(tmp_path, spec):
    _harvest(tmp_path, "plan_a", [
        _tuple("energy_consumption", 12.0, "MWh/a", "MWh/a")])
    files = hl.harvest_files(tmp_path)
    row = _only(hl.unit_rows(files, spec), parameter="energy_consumption")
    assert row["chosen_factor"] == 1.0
    assert row["listed"] == "yes"


def test_a_wording_read_as_an_entry_it_does_not_spell(tmp_path, spec):
    """"MWh pro Jahr" is no entry; the model read it as "MWh/a". The factor
    is the entry's, and the wording is what the census exists to collect."""
    _harvest(tmp_path, "plan_a", [
        _tuple("energy_consumption", 12.0, "MWh/a", "MWh pro Jahr")])
    files = hl.harvest_files(tmp_path)
    row = _only(hl.unit_rows(files, spec), parameter="energy_consumption")
    assert row["unit_as_written"] == "MWh pro Jahr"
    assert row["unit_chosen"] == "MWh/a"
    assert row["chosen_factor"] == 1.0
    assert row["listed"] == "no"


def test_a_unit_refusal_is_counted_by_its_own_wording(tmp_path, spec):
    """A unit the spec refuses is still a unit the plans use: no tuple, one
    refusal, no chosen unit at all."""
    _harvest(tmp_path, "plan_a", [
        _refusal("emission", "unit 'lbs CO2' not in units_accepted (t, ...)",
                 {"value": 900, "unit": "lbs CO2", "unit_raw": "lbs CO2",
                  "quote": "900 lbs CO2 pro Jahr"})])
    files = hl.harvest_files(tmp_path)
    row = _only(hl.unit_rows(files, spec), parameter="emission")
    assert row["unit_as_written"] == "lbs CO2"
    assert row["unit_chosen"] == ""
    assert row["chosen_factor"] == ""
    assert row["listed"] == "no"
    assert row["tuples"] == 0 and row["refusals"] == 1


def test_wordings_read_as_no_entry_sort_first_then_by_count(tmp_path, spec):
    """The rows a longer list is written from come first, then the wordings
    seen most, so a spelling nobody uses does not crowd them out."""
    _harvest(tmp_path, "plan_a", [
        _tuple("energy_consumption", 1.0, "MWh/a", "MWh/a"),
        _tuple("energy_consumption", 2.0, "MWh/a", "MWh/a"),
        _tuple("energy_consumption", 3.0, "kWh/a", "kWh/m²a"),
        _refusal("emission", "unit 'lbs CO2' not in units_accepted (t, ...)",
                 {"value": 900, "unit_raw": "lbs CO2",
                  "quote": "900 lbs CO2 pro Jahr"}),
    ])
    files = hl.harvest_files(tmp_path)
    rows = hl.unit_rows(files, spec)
    assert rows[0]["unit_as_written"] == "lbs CO2" and not rows[0]["unit_chosen"]
    assert rows[1]["unit_as_written"] == "MWh/a" and rows[1]["tuples"] == 2
    assert rows[2]["unit_as_written"] == "kWh/m²a"


def test_plans_ignores_trace_and_stamp_files_and_skips_malformed_lines(
        tmp_path, spec):
    _harvest(tmp_path, "plan_a", [
        _tuple("energy_consumption", 1.0, "MWh/a", "MWh/a"),
        {"not even": "a row with a kind"},
    ])
    (tmp_path / "plan_a.trace.jsonl").write_text(
        '{"t": "field", "doc": 1}\n', encoding="utf-8")
    (tmp_path / "plan_a.stamp.json").write_text("not jsonl at all {{{", encoding="utf-8")
    (tmp_path / "plan_a.jsonl").open("a", encoding="utf-8").write("{ not json\n")
    files = hl.harvest_files(tmp_path)
    assert [f.name for f in files] == ["plan_a.jsonl"]
    row = _only(hl.unit_rows(files, spec), parameter="energy_consumption")
    assert row["tuples"] == 1


# --- organisations.csv -------------------------------------------------------

def test_two_spellings_of_one_office_share_an_iri_key(tmp_path, spec, normalise):
    _harvest(tmp_path, "plan_a", [
        _org_tuple("Kassel Wärme Ingenieurbüro", value_raw="Kassel Wärme Ingenieurbüro GmbH"),
    ])
    _harvest(tmp_path, "plan_b", [
        _org_tuple("Kassel Wärme Ingenieurbüro", value_raw="Kassel Wärme Ingenieurbüro"),
    ])
    files = hl.harvest_files(tmp_path)
    rows = hl.organisation_rows(files, spec, normalise)
    names = {r["name_as_written"] for r in rows}
    assert names == {"Kassel Wärme Ingenieurbüro GmbH", "Kassel Wärme Ingenieurbüro"}
    keys = {r["iri_key"] for r in rows}
    assert len(keys) == 1, "the legal form must not survive into the key"
    for row in rows:
        assert row["names_sharing_key"] == 2
        assert row["plans"] == 1


def test_ecb_and_dotted_spellings_show_each_other_as_related(
        tmp_path, spec, normalise):
    """The real corpus example: "ecb energie.concept.bayern" (10 plans) and
    "energie.concept.bayern." (2 plans) normalise to two different keys --
    the office prefix keeps them apart -- so they mint two IRIs and only
    `related_names` says they might be the same office."""
    for i in range(10):
        _harvest(tmp_path, f"plan_ecb_{i}",
                 [_org_tuple("ecb energie.concept.bayern")])
    for i in range(2):
        _harvest(tmp_path, f"plan_dot_{i}",
                 [_org_tuple("energie.concept.bayern.")])
    files = hl.harvest_files(tmp_path)
    rows = hl.organisation_rows(files, spec, normalise)
    ecb = _only(rows, name_as_written="ecb energie.concept.bayern")
    dotted = _only(rows, name_as_written="energie.concept.bayern.")
    assert ecb["iri_key"] != dotted["iri_key"]
    assert ecb["plans"] == 10 and dotted["plans"] == 2
    assert "energie.concept.bayern." in ecb["related_names"]
    assert "ecb energie.concept.bayern" in dotted["related_names"]


def test_organisations_csv_sorts_by_iri_key(tmp_path, spec, normalise):
    _harvest(tmp_path, "plan_a", [
        _org_tuple("Zeta Planung"), _org_tuple("Alpha Planung")])
    files = hl.harvest_files(tmp_path)
    rows = hl.organisation_rows(files, spec, normalise)
    assert [r["iri_key"] for r in rows] == sorted(r["iri_key"] for r in rows)


# --- CLI ---------------------------------------------------------------------

def test_main_writes_both_csvs_and_reports_a_summary(tmp_path, capsys):
    harvest_dir = tmp_path / "harvest"
    harvest_dir.mkdir()
    _harvest(harvest_dir, "plan_a", [
        _tuple("energy_consumption", 400.0, "kWh/a", "kWh/m²a"),
        _org_tuple("Kassel Wärme Ingenieurbüro", value_raw="Kassel Wärme Ingenieurbüro GmbH"),
    ])
    out_dir = tmp_path / "out"
    rc = hl.main([str(harvest_dir), "--out-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "units.csv").is_file()
    assert (out_dir / "organisations.csv").is_file()
    text = (out_dir / "units.csv").read_text(encoding="utf-8")
    assert "kWh/m²a" in text and "listed" in text
    org_text = (out_dir / "organisations.csv").read_text(encoding="utf-8")
    assert "Kassel Wärme Ingenieurbüro GmbH" in org_text
    out = capsys.readouterr().out
    assert "plan(s)" in out and "organisation spelling" in out


def test_empty_directory_exits_1(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = hl.main([str(empty)])
    assert rc == 1
    assert "no harvest" in capsys.readouterr().err


def test_not_a_directory_exits_1(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    rc = hl.main([str(missing)])
    assert rc == 1
    assert "not a directory" in capsys.readouterr().err
