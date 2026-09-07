"""The list a person works from, so the list is measured too.

A curation list is a filter, and a filter that quietly drops something is
worse than no filter: what it does not show reads as "nothing wrong with it".
So these hold the three things it can get wrong without anyone noticing -- who
is on it, what a row says about where to look, and the order they come in.

No model, no database, no GPU.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.extraction import fields                       # noqa: E402
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL  # noqa: E402
from scripts import curation_list as cl                     # noqa: E402


def _row(**overrides):
    """An accepted value with every coordinate read off its own table."""
    row = {"kind": "tuple", "parameter": "https://x/energy_consumption",
           "value": 241.0, "unit": "GWh/a", "unit_raw": "GWh/a",
           "tier": TIER_TEXT, "quote": "| Erdgas | 241 |",
           "provenance": {"document_id": 857, "owner_kind": "table",
                          "owner_id": 87457, "parent_section": 349525,
                          "page": 86, "title": "Tabelle 17: Endenergie",
                          "image": "p86_tbl0.png"}}
    for name in ("carrier", "sector", "year"):
        row[f"{name}_state"] = fields.READ
        row[f"{name}_source"] = ["table", 87457]
    row["year"] = 2040
    row["carrier"] = "oeo:OEO_00000292"
    row.update(overrides)
    return row


def _harvest(tmp_path, name, rows):
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    return path


def test_only_the_values_nobody_can_stand_behind_are_listed(tmp_path):
    """The default is C. A list that also carries the clean values is a list
    of the whole corpus, and the point is the short one."""
    _harvest(tmp_path, "plan_a", [
        _row(),                                          # A
        _row(tier=TIER_VISUAL),                          # B
        _row(year_source=["table", 87517]),              # C
        {"kind": "refusal", "reason": "value is not a number"},
        {"kind": "summary", "document_id": 857, "tuples": 3, "refusals": 1,
         "levels": {"A": 1, "B": 1, "C": 1}, "reasons": {}, "image_origin": 1},
    ])
    tuples = cl.read_tuples(tmp_path / "plan_a.jsonl")
    assert len(tuples) == 3, "a refusal is not a value and neither is a summary"

    only_c = cl.rows_of("plan_a", tuples, levels={"C"})
    assert [r["reasons"] for r in only_c] == ["nonlocal:year"]
    # And asking for everything gives everything, with its level named.
    everything = cl.rows_of("plan_a", tuples, levels={"A", "B", "C"})
    assert sorted(r["level"] for r in everything) == ["A", "B", "C"]


def test_a_row_says_where_to_look_without_opening_the_harvest(tmp_path):
    """Page, source, caption, crop and the passage that was cited. Without
    them the list says a value is doubtful and leaves the reader to find it,
    which is the work the list exists to remove."""
    tuples = cl.read_tuples(_harvest(tmp_path, "plan_a",
                                     [_row(year_source=["table", 87517])]))
    row = cl.rows_of("plan_a", tuples, levels={"C"})[0]
    assert row["page"] == 86 and row["owner"] == "table 87457"
    assert row["title"] == "Tabelle 17: Endenergie"
    assert row["image"] == "p86_tbl0.png"
    assert row["quote"] == "| Erdgas | 241 |"
    assert row["parameter"] == "energy_consumption"
    # The coordinates carry their state: "year=2040" alone says nothing about
    # whether to trust it.
    assert "year=2040(read)" in row["coordinates"]
    assert set(row) == set(cl.COLUMNS), "the CSV writer takes exactly these"


def test_the_worst_value_comes_first(tmp_path):
    """A value with three things wrong with it teaches more per minute than
    three values with one. Ordering is the only thing a list of 10.000 rows
    can do for a curator who reads 50."""
    tuples = cl.read_tuples(_harvest(tmp_path, "plan_a", [
        _row(year_source=["table", 87517]),                       # 1 reason
        _row(year_source=["table", 87517], flags=["computed"],
             sector_state=fields.EXHAUSTED),                      # 3 reasons
        _row(flags=["not_located"]),                              # 1 reason
    ]))
    rows = cl.rows_of("plan_a", tuples, levels={"C"})
    assert len(rows[0]["reasons"].split(",")) == 3
    assert rows[0]["reasons"].startswith("exhausted:sector")


def test_a_reason_filter_matches_the_family_not_the_exact_word(tmp_path):
    """"nonlocal:" is a question about evidence locality and covers every
    axis; typing out the seven axes is how one gets forgotten."""
    tuples = cl.read_tuples(_harvest(tmp_path, "plan_a", [
        _row(year_source=["table", 87517]),
        _row(carrier_source=["section", 1]),
        _row(flags=["computed"]),
    ]))
    got = cl.rows_of("plan_a", tuples, levels={"C"}, reason="nonlocal:")
    assert len(got) == 2
    assert cl.rows_of("plan_a", tuples, levels={"C"},
                      reason="nonlocal:year")[0]["reasons"] == "nonlocal:year"
    assert cl.rows_of("plan_a", tuples, levels={"C"}, reason="erfunden") == []


def test_a_long_passage_is_cut_where_the_reader_can_see_it(tmp_path):
    """The harvest keeps the whole quote; this list is not the archive, and a
    cell that breaks a spreadsheet row is a cell nobody reads."""
    long_quote = "Der Endenergieverbrauch der privaten Haushalte betrug " * 20
    tuples = cl.read_tuples(_harvest(tmp_path, "plan_a", [
        _row(year_source=["table", 87517], quote=long_quote)]))
    cell = cl.rows_of("plan_a", tuples, levels={"C"})[0]["quote"]
    assert len(cell) < len(long_quote) and cell.endswith(" …")
