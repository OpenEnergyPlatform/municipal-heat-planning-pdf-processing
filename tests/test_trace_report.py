"""The trace report over a trace that has document searches and one that has
not. A search counts its windows from one and a batch's own stage does the same,
so the two are not read as one distribution; a trace written before there were
searches reads as it always did."""
import json

from scripts import trace_report


def _trace(tmp_path, events):
    (tmp_path / "plan.trace.jsonl").write_text(
        "\n".join(json.dumps({"doc": 1, **e}) for e in events) + "\n",
        encoding="utf-8")
    return tmp_path


def _report(tmp_path, events, capsys):
    assert trace_report.main([str(_trace(tmp_path, events))]) == 0
    return capsys.readouterr().out


def test_a_trace_without_searches_reads_as_it_always_did(tmp_path, capsys):
    events = [{"t": "field", "slot": "year", "stage": "retrieval", "window": 3,
               "filled": 1, "ms": 5},
              {"t": "sweep", "slot": "year", "windows": 7, "rows": 1}]
    out = _report(tmp_path, events, capsys)
    assert "(search)" not in out and "(own)" not in out
    assert "year" in out


def test_a_search_and_an_own_stage_are_counted_apart(tmp_path, capsys):
    events = [{"t": "field", "slot": "year", "stage": "own", "window": 1,
               "batches": 1, "filled": 1, "ms": 5},
              {"t": "field", "slot": "year", "stage": "rest", "window": 2,
               "batches": 3, "filled": 2, "ms": 5},
              {"t": "sweep", "slot": "year", "windows": 1, "rows": 1,
               "batches": 1, "scope": "own"},
              {"t": "sweep", "slot": "year", "windows": 9, "rows": 3,
               "batches": 3, "scope": "document"}]
    out = _report(tmp_path, events, capsys)
    assert "year (search)" in out, "the window of a read in a search"
    assert "year (own)" in out and "year (document)" in out, (
        "the windows of the two kinds of sweep")
