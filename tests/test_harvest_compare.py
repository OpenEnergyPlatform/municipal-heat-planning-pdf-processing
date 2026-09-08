"""The measuring instrument, measured.

Every acceptance number of the repair is read off this script, so an error in
it is an error in the decision it feeds. The three pieces that can be wrong
without anyone noticing are here: what counts as a document, what a trace
costs, and whether a coordinate agrees with what the plan really states.

No model, no database, no GPU.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import harvest_compare as hc

NEWLINE = chr(10)


def _write(path: Path, rows: list) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")


def test_a_trace_is_not_a_document(tmp_path):
    """A hand-copied set of files has the trace next to the harvest, and
    counting it as a document halves every per-document average."""
    _write(tmp_path / "plan_a.jsonl", [{"kind": "tuple", "value": 1},
                                       {"kind": "refusal", "reason": "x"}])
    _write(tmp_path / "plan_a.trace.jsonl", [{"t": "rows", "ms": 10}])

    files = sorted(p for p in tmp_path.glob("*.jsonl")
                   if not p.name.endswith(".trace.jsonl"))
    assert [p.stem for p in files] == ["plan_a"]
    tuples, refusals, summary, _states = hc.read_harvest(
        tmp_path / "plan_a.jsonl")
    assert len(tuples) == 1 and len(refusals) == 1 and summary is None


def test_the_cost_is_read_from_both_places_a_trace_lives(tmp_path):
    """A run writes it under trace/, a copied set has it alongside. Both are
    the same file and returning zero for one of them makes a repair look free.
    """
    events = [{"t": "rows", "ms": 100}, {"t": "field", "ms": 50},
              {"t": "field", "ms": 25},
              {"t": "error", "kind": "unparsable"},
              {"t": "drop", "why": "quote_not_in_source"},
              {"t": "plan", "rank": 3}]
    _write(tmp_path / "plan_a.trace.jsonl", events)
    beside = hc.trace_costs(tmp_path, "plan_a")
    assert beside == {"rows": 1, "field": 2, "ms": 175, "unparsable": 1,
                      "drops": 1}

    nested = tmp_path / "nested"
    (nested / "trace").mkdir(parents=True)
    _write(nested / "trace" / "plan_a.trace.jsonl", events)
    assert hc.trace_costs(nested, "plan_a") == beside
    assert hc.trace_costs(nested, "plan_b")["field"] == 0, "no trace, no cost"


def test_agreement_counts_only_the_owners_the_truth_names(tmp_path):
    """The claim is about twelve tables. Tuples from other owners are untested,
    not right: counting them as right is how a repair measures itself.
    """
    tuples = [
        {"provenance": {"owner_id": 87457}, "year": 2040},   # right
        {"provenance": {"owner_id": 87457}, "year": 2030},   # wrong
        {"provenance": {"owner_id": 87458}, "year": 2040},   # right
        {"provenance": {"owner_id": 99999}, "year": 1234},   # not named
        {"provenance": {}, "year": 2040},                    # no owner
    ]
    got = hc.agreement(tuples, {"years": {"87457": 2040, "87458": 2040}})
    assert got["years"]["hit"] == 2
    assert got["years"]["miss"] == 1
    assert got["years"]["worst"] == [("87457: 2030", 1)]

    # A second coordinate is checked the same way and on its own owners.
    tuples = [{"provenance": {"owner_id": 87438}, "scenario": "status_quo"},
              {"provenance": {"owner_id": 87439}, "scenario": "target"}]
    got = hc.agreement(tuples, {"scenarios": {"87438": "status_quo",
                                              "87439": "status_quo"}})
    assert (got["scenarios"]["hit"], got["scenarios"]["miss"]) == (1, 1)


def test_the_summary_line_is_neither_a_tuple_nor_a_refusal(tmp_path):
    """It is the file's own last line. Counted as a refusal it adds one to
    every document in the corpus, and the refusal share is one of the numbers
    the repair is judged on."""
    _write(tmp_path / "plan_a.jsonl", [
        {"kind": "tuple", "value": 1},
        {"kind": "refusal", "reason": "x"},
        {"kind": "summary", "document_id": 7, "tuples": 1, "refusals": 1,
         "levels": {"A": 0, "B": 1, "C": 0}, "reasons": {}, "image_origin": 1},
    ])
    tuples, refusals, summary, _states = hc.read_harvest(
        tmp_path / "plan_a.jsonl")
    assert len(tuples) == 1
    assert len(refusals) == 1, "the summary is not one of them"
    assert summary["levels"] == {"A": 0, "B": 1, "C": 0}


def test_a_parameter_state_is_neither_a_tuple_nor_a_refusal(tmp_path):
    """There is one per parameter of the spec, so an `else` that swept them
    into the refusals would report fourteen model errors per ar6 document
    that nobody made, and the refusal share is one of the numbers the repair
    is judged on."""
    _write(tmp_path / "plan_b.jsonl", [
        {"kind": "tuple", "value": 1},
        {"kind": "refusal", "reason": "x"},
        {"kind": "parameter_state", "document_id": 7,
         "parameter": "planning_organisation", "state": "unstated",
         "tuples": 0, "refusals": 0},
        {"kind": "parameter_state", "document_id": 7,
         "parameter": "emission", "state": "exhausted",
         "tuples": 0, "refusals": 0},
        {"kind": "summary", "document_id": 7, "tuples": 1, "refusals": 1,
         "levels": {"A": 0, "B": 1, "C": 0}, "reasons": {}, "image_origin": 1},
    ])
    tuples, refusals, summary, states = hc.read_harvest(
        tmp_path / "plan_b.jsonl")
    assert len(tuples) == 1
    assert len(refusals) == 1, "the two parameter states are not refusals"
    assert summary["tuples"] == 1
    assert [s["parameter"] for s in states] == ["planning_organisation",
                                                "emission"]


def test_a_harvest_without_a_summary_still_reads(tmp_path):
    """Every file written before the summary existed, and the report has to
    read those too: this script is how an old run is compared to a new one."""
    _write(tmp_path / "old.jsonl", [{"kind": "tuple", "value": 1}])
    tuples, refusals, summary, _states = hc.read_harvest(
        tmp_path / "old.jsonl")
    assert tuples and not refusals and summary is None


def test_the_truth_file_is_read_the_way_it_is_written(tmp_path):
    """The measurement this feeds -- the acceptance criterion of M3, the year
    repair -- printed "keine Ernte" on every run since 1f609f8 and nobody saw
    it, because the caller read the truth file's top level as DOCUMENT names
    while it is coordinate names. `agreement` was tested and the glue calling
    it was not, so the shape mismatch lived between them.

    So this drives the caller against the REAL file, scripts/kassel_truth.json,
    rather than a fixture shaped the way the code happens to want it.
    """
    truth = json.loads((Path(hc.__file__).resolve().parent / "kassel_truth.json")
                       .read_text(encoding="utf-8"))
    assert set(truth) == {"_comment", "years", "scenarios"}, \
        "the shape this test is about"

    # Every coordinate on every row, as a harvested tuple carries them: three
    # owners (87457/58/59) are named by BOTH coordinates of the truth file, so
    # a fixture that answers only one of them measures a miss that is its own.
    _write(tmp_path / "waermeplan_kassel_20260326.jsonl", [
        # right on both: the truth file says 2040 and target for this table
        {"kind": "tuple", "provenance": {"owner_id": 87457},
         "year": 2040, "scenario": "target"},
        # wrong year, and its scenario is not claimed by the truth file
        {"kind": "tuple", "provenance": {"owner_id": 87517},
         "year": 2040, "scenario": "target"},
        # wrong scenario: the truth file says status_quo for this one
        {"kind": "tuple", "provenance": {"owner_id": 87438},
         "year": 2040, "scenario": "target"},
        {"kind": "tuple", "provenance": {"owner_id": 99999},
         "year": 1234, "scenario": "target"},
    ])
    files = sorted(tmp_path.glob("*.jsonl"))
    lines = hc.truth_report(files, truth)
    body = NEWLINE.join(lines)

    assert "keine Ernte" not in body
    # 87457 wants 2040 and got it, 87517 wants 2030 and got 2040.
    assert "years      richtig 1 von 2 (50%)" in body
    assert "falsch: 87517: 2040 (1x)" in body
    assert "scenarios  richtig 1 von 2 (50%)" in body
    assert "falsch: 87438: target (1x)" in body
    # `_comment` is prose, not a coordinate, and must not become a line.
    assert "_comment" not in body
    # And the owner nobody claimed is untested, not right.
    assert "99999" not in body


def test_a_truth_file_that_matches_nothing_says_so(tmp_path):
    """The state the old code was permanently in. It read as an empty section,
    which is indistinguishable from a passing measurement -- so it is a named
    line now."""
    _write(tmp_path / "plan_a.jsonl",
           [{"kind": "tuple", "provenance": {"owner_id": 1}, "year": 2040}])
    lines = hc.truth_report(sorted(tmp_path.glob("*.jsonl")),
                            {"years": {"87457": 2040}})
    assert lines == ["  years: kein Tupel von einem Eigner, den die "
                     "Wahrheitsdatei nennt"]
