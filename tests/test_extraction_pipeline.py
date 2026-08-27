"""The harvest loop: sweep until dry, harvest each owner once, keep refusals."""
import json

from docpipe.extraction.pipeline import (Source, harvest_document,
                                         write_report)
from docpipe.extraction.queries import expand
from docpipe.extraction.spec import load

SPEC = load({"parameters": [{
    "uri": "OEO_00050016",
    "label": "Endenergieverbrauch",
    "description": "Endenergieverbrauch je Energieträger, Sektor und Jahr, "
                   "wie im Plan bilanziert.",
    "unit_target": "OEO_00050008",
    "units_accepted": {"MWh/a": 1.0},
    "axes": {
        "carrier": {"vocabulary": {"OEO_00000292": ["Erdgas"],
                                   "OEO_00000211": ["Heizöl"]}},
        "year": {"type": "int"},
    },
    "example": {"source": "| Erdgas | 42.005 | MWh/a | im Jahr 2020 |",
                "tuples": [{"value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a"}]},
}]})

TEMPLATES = ["{label} nach Energieträgern Tabelle", "{label} {axis:carrier}"]


def _sources():
    return [
        Source("table", 1, "| Erdgas | 42.005 | MWh/a |", {"page": 31}),
        Source("table", 2, "| Heizöl | 17.300 | MWh/a |", {"page": 32}),
        Source("figure", 3, "Balkendiagramm: Erdgas etwa 42.000 MWh/a",
               {"page": 33}, image_path="p33_img0.png"),
    ]


def test_queries_expand_per_vocabulary_entry():
    probes = expand(TEMPLATES, SPEC.parameters[0])
    assert probes == ["Endenergieverbrauch nach Energieträgern Tabelle",
                      "Endenergieverbrauch Erdgas",
                      "Endenergieverbrauch Heizöl"]


def _per_probe(fn):
    """Adapt a one-probe stub to the batched contract retrieval now has.

    plan_document hands every probe of a round over in one call, because the
    real implementation builds the document's sub-index once and searches the
    probes as a matrix. Exclusion still grows from probe to probe — that is
    what this reproduces, and what the sequential version did by rebuilding
    the snapshot each time.
    """
    def retrieve(probes, document_id, exclude):
        taken = set(exclude)
        out = []
        for probe in probes:
            found = list(fn(probe, document_id, set(taken)))
            taken.update((s.owner_kind, s.owner_id) for s in found)
            out.append(found)
        return out
    return retrieve


def test_an_owner_found_by_two_queries_is_harvested_once():
    """Query overlap is the rule, not the exception — dedup is one rule:
    one harvest per (owner, parameter)."""
    calls = []

    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if ("table", s.owner_id) not in exclude]

    def harvest(source, parameter):
        calls.append(source.owner_id)
        return [{"value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a", "carrier": "Erdgas",
                 "quote": "Erdgas | 42.005"}]

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=harvest)
    assert calls == [1], "three queries hit the same table; one harvest"
    assert len(report.tuples) == 1


def test_the_sweep_stops_when_a_round_finds_nothing_new():
    rounds_seen = []

    def retrieve(query, document_id, exclude):
        rounds_seen.append(query)
        return [s for s in _sources()
                if (s.owner_kind, s.owner_id) not in exclude]

    def harvest(source, parameter):
        return []

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=harvest)
    # 3 probes find everything in round one; round two adds nothing and stops.
    assert report.sweep_rounds["OEO_00050016"] == 1
    assert report.owners_harvested == 3


def test_refusals_are_reported_not_dropped():
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if ("table", s.owner_id) not in exclude]

    def harvest(source, parameter):
        return [{"value": 99999, "unit": "MWh/a", "unit_raw": "MWh/a",
                 "quote": "Erdgas | 42.005"}]          # value not in quote

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=harvest)
    assert not report.tuples
    assert report.refusals and "does not occur" in report.refusals[0]["reason"]


def test_unmapped_labels_ride_on_the_row_itself():
    """The vocabulary review works from the harvest files: the flag and the
    raw label must survive into the tuple row, not just a log line."""
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if ("table", s.owner_id) not in exclude]

    def harvest(source, parameter):
        return [{"value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a", "carrier": "Klärgas",
                 "quote": "Erdgas | 42.005"}]

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=harvest)
    row = report.tuples[0]
    assert row["flags"] == ["unmapped:carrier:Klärgas"]
    assert row["carrier_raw"] == "Klärgas" and row["carrier"] is None


def test_a_figure_claim_carries_the_visual_tier():
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()
                if (s.owner_kind, s.owner_id) not in exclude]

    def harvest(source, parameter):
        if source.owner_kind != "figure":
            return []
        return [{"value": 42000, "unit": "MWh/a", "unit_raw": "MWh/a", "carrier": "Erdgas",
                 "quote": "Erdgas etwa 42.000 MWh/a"}]

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=harvest)
    assert [t["tier"] for t in report.tuples] == ["visual_source"]
    assert report.tuples[0]["provenance"]["image"] == "p33_img0.png", (
        "the picture is the evidence, so it has to be in the provenance")


def test_the_report_file_is_the_audit_trail(tmp_path):
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:2]
                if (s.owner_kind, s.owner_id) not in exclude]

    def harvest(source, parameter):
        if source.owner_id == 1:
            return [{"value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a", "carrier": "Erdgas",
                     "quote": "Erdgas | 42.005"}]
        return [{"value": 1, "unit": "MWh/a", "unit_raw": "MWh/a", "quote": "Heizöl | 17.300"}]

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=harvest)
    out = tmp_path / "doc7.jsonl"
    write_report(report, out)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    kinds = {r["kind"] for r in rows}
    assert kinds == {"tuple", "refusal"}
    accepted = [r for r in rows if r["kind"] == "tuple"][0]
    assert accepted["provenance"]["owner_id"] == 1
    assert accepted["provenance"]["page"] == 31


def test_the_fallback_harvests_only_what_retrieval_never_saw():
    """D1's division of labour: retrieval is the harvest, the deterministic
    candidate set is the floor. The leftover count is the standing quality
    metric of the probes."""
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if ("table", s.owner_id) not in exclude]

    def candidates(document_id, parameter):
        return _sources()[:2]              # table 1 (seen) + table 2 (missed)

    harvested = []

    def harvest(source, parameter):
        harvested.append(source.owner_id)
        return []

    report = harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(retrieve),
                              harvest=harvest, candidates=candidates)
    assert harvested == [1, 2], "the seen table is not harvested twice"
    assert report.fallback["OEO_00050016"] == {"candidates": 2, "leftover": 1}
