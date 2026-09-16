"""The numbers a curator pulls by hand after every run, pulled by a script
instead. Each section of the report reads a different kind of row (tuple,
refusal, parameter_state, summary), so each is its own doubt here: is a
sentinel counted separately from an ordinary refusal, is a state nobody
published flagged loudly, does the thinnest-plans cut really narrow the
overall share.

No model, no GPU, no document database. The token usage database is the one
optional SQLite read.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import usage                                      # noqa: E402
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL     # noqa: E402
from scripts import harvest_report as hr                         # noqa: E402


def _write(path: Path, rows: list) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")


def _tuple(tier=TIER_TEXT, year_state="read", **overrides):
    row = {"kind": "tuple", "parameter": "p:x", "parameter_state": "read",
           "tier": tier, "quote": "some quoted passage of the source",
           "year": 2040, "year_state": year_state}
    row.update(overrides)
    return row


def _summary(**overrides):
    row = {"kind": "summary", "document_id": 1, "tuples": 0, "refusals": 0,
           "levels": {"A": 0, "B": 0, "C": 0}, "reasons": {}, "image_origin": 0}
    row.update(overrides)
    return row


def _stats(tmp_path, usage_rows=None):
    files = hr.harvest_files(tmp_path)
    return hr.build_stats(files, hr.scan(files), usage_rows or [],
                          tmp_path / "usage.db")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def test_a_trace_file_and_a_stamp_file_are_not_a_plan(tmp_path):
    _write(tmp_path / "a.jsonl", [_tuple()])
    (tmp_path / "a.trace.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "a.stamp.json").write_text("{}\n", encoding="utf-8")
    assert [p.stem for p in hr.harvest_files(tmp_path)] == ["a"]


def test_an_empty_directory_exits_with_an_error(tmp_path, capsys):
    assert hr.main([str(tmp_path)]) == 1
    assert "no harvest" in capsys.readouterr().err


def test_a_missing_directory_exits_with_an_error(tmp_path, capsys):
    assert hr.main([str(tmp_path / "does_not_exist")]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_malformed_lines_and_missing_fields_do_not_crash(tmp_path):
    """A corpus harvest is hundreds of MB; one torn line must not lose it,
    and a row missing the keys this report reads must not raise."""
    (tmp_path / "a.jsonl").write_text(
        "not json at all\n"
        + json.dumps({"kind": "tuple"}) + "\n"
        + json.dumps({"kind": "refusal"}) + "\n"
        + json.dumps({"kind": "parameter_state"}) + "\n"
        + json.dumps({"kind": "summary"}) + "\n"
        + "\n"
        + json.dumps([1, 2, 3]) + "\n",
        encoding="utf-8")
    stats = _stats(tmp_path)
    assert stats["plans"]["total"] == 1
    assert stats["plans"]["distribution"]["n"] == 1


# ---------------------------------------------------------------------------
# 1. Tuples per plan
# ---------------------------------------------------------------------------

def test_the_tuple_distribution_and_floors_are_read_off_every_plan(tmp_path):
    counts = {"a": 1, "b": 5, "c": 10, "d": 12, "e": 30, "f": 50}
    for name, n in counts.items():
        _write(tmp_path / f"{name}.jsonl", [_tuple() for _ in range(n)])
    stats = _stats(tmp_path)
    dist = stats["plans"]["distribution"]
    values = sorted(counts.values())
    assert dist["n"] == 6
    assert dist["min"] == 1 and dist["max"] == 50
    assert dist["median"] == hr.percentile(values, .5)
    assert dist["p10"] == hr.percentile(values, .10)
    assert dist["p75"] == hr.percentile(values, .75)
    # under 25: 1, 5, 10, 12 -- under 10: 1, 5
    assert stats["plans"]["under"] == {"25": 4, "10": 2}


def test_percentile_matches_trace_reports_own_helper():
    from scripts import trace_report
    values = [1, 5, 9, 12, 40, 3, 7]
    for share in (0, .1, .5, .75, .9, 1.0):
        assert hr.percentile(values, share) == trace_report.percentile(values,
                                                                       share)
    assert hr.percentile([], .5) is None


# ---------------------------------------------------------------------------
# 2. Image share
# ---------------------------------------------------------------------------

def test_image_share_is_read_from_the_tuples_own_tier(tmp_path):
    _write(tmp_path / "text_plan.jsonl",
           [_tuple(tier=TIER_TEXT) for _ in range(2)]
           + [_summary(tuples=2, image_origin=0)])
    _write(tmp_path / "image_plan.jsonl",
           [_tuple(tier=TIER_VISUAL) for _ in range(2)]
           + [_summary(tuples=2, image_origin=2)])
    stats = _stats(tmp_path)
    assert stats["image_share"]["overall"] == {"tuples": 4, "image": 2,
                                               "share": 0.5}
    assert stats["image_share"]["consistency"] == {
        "tuple_derived_finished": 2, "summary_total": 2, "agree": True}


def test_the_thinnest_plans_are_a_narrower_cut_than_overall(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(hr, "THIN_PLAN_COUNT", 1)
    _write(tmp_path / "thin.jsonl", [_tuple(tier=TIER_VISUAL)])
    _write(tmp_path / "fat.jsonl", [_tuple(tier=TIER_TEXT) for _ in range(9)])
    stats = _stats(tmp_path)
    assert stats["image_share"]["overall"]["share"] == 0.1
    thin = stats["image_share"]["thinnest"]
    assert thin["n"] == 1
    assert thin["tuples"] == 1 and thin["image"] == 1 and thin["share"] == 1.0


def test_a_summary_image_origin_mismatch_is_flagged_not_hidden(tmp_path):
    """The tuple's own tier is authoritative; the summary's image_origin is a
    cross-check, and disagreement must be visible, not silently trusted."""
    _write(tmp_path / "plan.jsonl",
           [_tuple(tier=TIER_VISUAL), _tuple(tier=TIER_TEXT),
            _summary(tuples=2, image_origin=99)])
    stats = _stats(tmp_path)
    consistency = stats["image_share"]["consistency"]
    assert consistency == {"tuple_derived_finished": 1, "summary_total": 99,
                           "agree": False}
    assert "DISAGREE" in hr.render_report(stats)


def test_an_unfinished_plan_is_left_out_of_the_consistency_check(tmp_path):
    """No summary line yet, so comparing it to a tuple-derived count would
    report a mismatch on every run still in progress."""
    _write(tmp_path / "running.jsonl", [_tuple(tier=TIER_VISUAL)])
    stats = _stats(tmp_path)
    assert stats["image_share"]["consistency"] == {
        "tuple_derived_finished": 0, "summary_total": 0, "agree": True}
    assert stats["image_share"]["overall"] == {"tuples": 1, "image": 1,
                                               "share": 1.0}


# ---------------------------------------------------------------------------
# 3. Trust
# ---------------------------------------------------------------------------

def test_trust_levels_and_reasons_are_summed_across_summaries(tmp_path):
    _write(tmp_path / "a.jsonl", [_summary(levels={"A": 3, "B": 1, "C": 1},
                                           reasons={"exhausted:year": 2,
                                                    "computed": 1})])
    _write(tmp_path / "b.jsonl", [_summary(levels={"A": 0, "B": 0, "C": 2},
                                           reasons={"exhausted:year": 3})])
    stats = _stats(tmp_path)
    assert stats["trust"]["levels"] == {"A": 3, "B": 1, "C": 3}
    assert stats["trust"]["top_reasons"]["exhausted:year"] == 5
    assert stats["trust"]["top_reasons"]["computed"] == 1


# ---------------------------------------------------------------------------
# 4. Refusals
# ---------------------------------------------------------------------------

def test_refusal_family_matches_the_published_schema_patterns():
    assert hr.refusal_family(
        "quote missing or too short to identify anything") == \
        "quote missing or too short to identify anything"
    assert hr.refusal_family("required axis 'year' is empty").startswith(
        "required axis")
    assert hr.refusal_family("a reason nobody published") == "(unmatched)"


def test_refusal_reasons_are_grouped_into_families_and_counted(tmp_path):
    _write(tmp_path / "a.jsonl", [
        {"kind": "refusal",
         "reason": "unit 'kWh' not in units_accepted (MWh, GWh)",
         "claim": {}, "owner": ["table", 1]},
        {"kind": "refusal",
         "reason": "unit 'MJ' not in units_accepted (MWh, GWh)",
         "claim": {}, "owner": ["table", 1]},
        {"kind": "refusal", "reason": "a made up reason nobody published",
         "claim": {}, "owner": ["table", 1]},
    ])
    stats = _stats(tmp_path)
    families = stats["refusals"]["families"]
    assert stats["refusals"]["total"] == 3
    assert families["(unmatched)"] == 1
    assert stats["refusals"]["unmatched"] == 1
    [(family, count)] = [(f, c) for f, c in families.items()
                         if f != "(unmatched)"]
    assert count == 2 and family.startswith("unit .* not in units_accepted")


def test_harvest_failure_sentinels_are_counted_by_why_not_by_reason(tmp_path):
    _write(tmp_path / "a.jsonl", [
        {"kind": "refusal", "reason": "claim names no source",
         "claim": {"_harvest_failed": True, "_why": "unreachable"},
         "owner": ["table", 1]},
        {"kind": "refusal", "reason": "claim names no source",
         "claim": {"_harvest_failed": True, "_why": "cut_off"},
         "owner": ["table", 1]},
        {"kind": "refusal", "reason": "claim names no source",
         "claim": {"_harvest_failed": True, "_why": "cut_off"},
         "owner": ["table", 1]},
        # An ordinary refusal must never be read as a sentinel.
        {"kind": "refusal",
         "reason": "quote missing or too short to identify anything",
         "claim": {"value": 1}, "owner": ["table", 1]},
    ])
    stats = _stats(tmp_path)
    assert stats["refusals"]["sentinels"] == {"unreachable": 1, "cut_off": 2}
    assert stats["refusals"]["total"] == 4


# ---------------------------------------------------------------------------
# 5. Parameter states
# ---------------------------------------------------------------------------

def test_parameter_states_are_counted_per_parameter(tmp_path):
    _write(tmp_path / "a.jsonl", [
        {"kind": "parameter_state", "document_id": 1, "parameter": "p:cons",
         "state": "read", "tuples": 3, "refusals": 0},
        {"kind": "parameter_state", "document_id": 1, "parameter": "p:org",
         "state": "unstated", "tuples": 0, "refusals": 0},
    ])
    _write(tmp_path / "b.jsonl", [
        {"kind": "parameter_state", "document_id": 2, "parameter": "p:cons",
         "state": "exhausted", "tuples": 0, "refusals": 1},
    ])
    stats = _stats(tmp_path)
    assert stats["parameter_states"]["p:cons"] == {"read": 1, "exhausted": 1}
    assert stats["parameter_states"]["p:org"] == {"unstated": 1}


# ---------------------------------------------------------------------------
# 6. Coordinate states
# ---------------------------------------------------------------------------

def test_every_known_axis_state_is_accepted_not_flagged(tmp_path):
    rows = [_tuple(year_state=state) for state in sorted(hr.KNOWN_AXIS_STATES)]
    _write(tmp_path / "a.jsonl", rows)
    stats = _stats(tmp_path)
    assert stats["unknown_axis_states"] == []
    assert "UNKNOWN STATE" not in hr.render_report(stats)


def test_an_axis_state_outside_the_known_set_is_flagged_prominently(tmp_path):
    _write(tmp_path / "a.jsonl", [
        _tuple(year_state="read"), _tuple(year_state="exhausted"),
        _tuple(year_state="totally_made_up")])
    stats = _stats(tmp_path)
    assert stats["coordinate_states"]["year"] == {
        "read": 1, "exhausted": 1, "totally_made_up": 1}
    assert stats["unknown_axis_states"] == [
        {"axis": "year", "state": "totally_made_up", "count": 1}]
    assert "UNKNOWN STATE" in hr.render_report(stats)


# ---------------------------------------------------------------------------
# 7. Tokens
# ---------------------------------------------------------------------------

def test_a_missing_usage_database_is_reported_not_an_error(tmp_path, capsys):
    _write(tmp_path / "a.jsonl", [_tuple()])
    missing = tmp_path / "does_not_exist.db"
    code = hr.main([str(tmp_path), "--usage-db", str(missing)])
    out = capsys.readouterr().out
    assert code == 0
    assert f"no usage database at {missing}" in out


def test_token_usage_is_read_per_stage_and_model(tmp_path, monkeypatch,
                                                 capsys):
    """Built through docpipe.usage itself, the way a real run writes it, so
    this checks the report against the module's own schema rather than a
    hand-rolled table."""
    _write(tmp_path / "a.jsonl", [_tuple()])
    db = tmp_path / "usage.db"
    monkeypatch.setenv("DOCPIPE_USAGE_DB", str(db))
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    monkeypatch.setattr(usage, "_warned", False)
    monkeypatch.setattr(usage.atexit, "register", lambda fn: None)
    usage.begin("extraction")
    usage.add("llm", input_tokens=100, output_tokens=10)
    usage.flush()

    code = hr.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "extraction" in out and "llm" in out and "100" in out and "10" in out


# ---------------------------------------------------------------------------
# 8. Unfinished plans
# ---------------------------------------------------------------------------

def test_plans_without_a_summary_row_are_listed_as_unfinished(tmp_path):
    _write(tmp_path / "done.jsonl", [_tuple(), _summary(tuples=1)])
    _write(tmp_path / "unfinished_one.jsonl", [_tuple()])
    _write(tmp_path / "unfinished_two.jsonl", [_tuple()])
    stats = _stats(tmp_path)
    assert stats["unfinished_plans"]["count"] == 2
    assert stats["unfinished_plans"]["first"] == ["unfinished_one",
                                                  "unfinished_two"]


def test_the_unfinished_preview_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "UNFINISHED_PREVIEW", 2)
    for i in range(5):
        _write(tmp_path / f"p{i}.jsonl", [_tuple()])
    stats = _stats(tmp_path)
    assert stats["unfinished_plans"]["count"] == 5
    assert stats["unfinished_plans"]["first"] == ["p0", "p1"]


# ---------------------------------------------------------------------------
# --json
# ---------------------------------------------------------------------------

def test_the_json_output_matches_the_printed_numbers(tmp_path, capsys):
    _write(tmp_path / "a.jsonl", [
        _tuple(), _summary(tuples=1, levels={"A": 1, "B": 0, "C": 0})])
    out_path = tmp_path / "out.json"
    code = hr.main([str(tmp_path), "--usage-db", str(tmp_path / "nope.db"),
                    "--json", str(out_path)])
    assert code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["plans"]["total"] == 1
    assert data["trust"]["levels"]["A"] == 1
    printed = capsys.readouterr().out
    assert f"written: {out_path}" in printed
    # The file is exactly what was printed, not a second computation of it.
    assert hr.render_report(data) in printed
