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
    tuples, refusals = hc.read_harvest(tmp_path / "plan_a.jsonl")
    assert len(tuples) == 1 and len(refusals) == 1


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
