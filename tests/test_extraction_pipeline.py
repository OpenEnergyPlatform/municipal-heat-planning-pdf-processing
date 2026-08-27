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


def _per_source(fn):
    """Adapt a one-source stub to the batched contract the harvest now has.

    A request reads several sources at once, and every claim names the source
    it came from. This reproduces that from a stub written per source, which
    is what these tests are about: the loop's bookkeeping, not the batching.
    """
    def harvest(batch, prior=None):
        tuples = []
        for index, item in enumerate(batch.items):
            for claim in fn(item.source, batch.parameter) or []:
                tuples.append({**claim, "source": batch.label(index)})
        return {"tuples": tuples, "status": "complete", "need_more": []}
    return harvest


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
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
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
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
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
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
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
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
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
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
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
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
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
                              harvest=_per_source(harvest), candidates=candidates)
    assert harvested == [1, 2], "the seen table is not harvested twice"
    assert report.fallback["OEO_00050016"] == {"candidates": 2, "leftover": 1}


# ---------------------------------------------------------------------------
# Several sources per request: the batch, its prior, and its follow-up
# ---------------------------------------------------------------------------

def _all_three(query, document_id, exclude):
    return [s for s in _sources() if (s.owner_kind, s.owner_id) not in exclude]


def test_one_request_carries_several_sources_of_the_same_parameter():
    """The reason the batch exists: the carrier is in one passage and the
    number in another, and a model shown only the second has to invent the
    first or refuse."""
    seen = []

    def harvest(batch, prior=None):
        seen.append([(i.source.owner_kind, i.source.owner_id)
                     for i in batch.items])
        return {"tuples": [], "status": "complete", "need_more": []}

    harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(_all_three),
                     harvest=harvest)
    assert seen == [[("table", 1), ("table", 2), ("figure", 3)]], (
        "three sources of one parameter belong in one request")


def test_a_value_is_checked_against_the_source_it_was_read_from():
    """The batch widens what the model may read, not what a quote may be
    checked against: the label says where the number came from, and that is
    the text the quote has to be in."""
    def harvest(batch, prior=None):
        return {"tuples": [{"source": "Q2", "value": 17300, "unit": "MWh/a",
                            "unit_raw": "MWh/a", "carrier": "Heizöl",
                            "quote": "| Heizöl | 17.300 | MWh/a |"}],
                "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(_all_three), harvest=harvest)
    assert len(report.tuples) == 1
    assert report.tuples[0]["provenance"]["owner_id"] == 2, (
        "the quote is in table 2, so the value's provenance is table 2")


def test_a_mislabelled_source_is_settled_by_the_quote_not_refused():
    """A label is the easiest thing in a batch to get wrong. Refusing a value
    whose quote is verbatim in the document, because the model wrote Q1 where
    it meant Q2, would throw away a correct extraction over bookkeeping."""
    def harvest(batch, prior=None):
        return {"tuples": [{"source": "Q1", "value": 17300, "unit": "MWh/a",
                            "unit_raw": "MWh/a", "carrier": "Heizöl",
                            "quote": "| Heizöl | 17.300 | MWh/a |"}],
                "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(_all_three), harvest=harvest)
    assert not report.refusals
    assert report.tuples[0]["provenance"]["owner_id"] == 2


def test_a_quote_in_no_source_is_still_refused():
    """The routing must not become a way to smuggle an invented quote past
    verification: a string none of the passages carries stays a refusal."""
    def harvest(batch, prior=None):
        return {"tuples": [{"source": "Q1", "value": 17300, "unit": "MWh/a",
                            "unit_raw": "MWh/a",
                            "quote": "Heizoel betraegt 17300 MWh pro Jahr"}],
                "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(_all_three), harvest=harvest)
    assert not report.tuples and report.refusals


def test_the_next_batch_is_told_what_the_earlier_ones_yielded():
    """Without prior, the same table read under two probes hands back the same
    value twice and the duplicate cannot be told from a second real figure."""
    priors = []

    def harvest(batch, prior=None):
        priors.append(list(prior or []))
        owner = batch.items[0].source.owner_id
        if owner != 1:
            return {"tuples": [], "status": "complete", "need_more": []}
        return {"tuples": [{"source": "Q1", "value": 42005, "unit": "MWh/a",
                            "unit_raw": "MWh/a", "carrier": "Erdgas",
                            "quote": "| Erdgas | 42.005 | MWh/a |"}],
                "status": "complete", "need_more": []}

    # One source per request, so the document takes three of them.
    harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(_all_three),
                     harvest=harvest, max_sources=1)
    assert priors[0] == [], "the first batch has nothing to be told"
    assert [t["value"] for t in priors[1]] == [42005]
    assert [t["value"] for t in priors[2]] == [42005]


def test_more_paragraphs_are_fetched_when_the_model_says_it_needs_them():
    """The third answer option: a value is here but its context is not. The
    model writes what to search for, and what comes back is one more batch of
    the same chain."""
    asked = []

    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if (s.owner_kind, s.owner_id) not in exclude]

    def more_sources(document_id, queries, exclude):
        asked.append(list(queries))
        return [s for s in _sources()[1:]
                if (s.owner_kind, s.owner_id) not in exclude]

    read = []

    def harvest(batch, prior=None):
        read.append([i.source.owner_id for i in batch.items])
        if len(read) == 1:
            return {"tuples": [], "status": "partial",
                    "need_more": ["Die Bilanz bezieht sich auf das Jahr 2020."]}
        return {"tuples": [], "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(retrieve),
                              harvest=harvest, more_sources=more_sources)
    assert asked == [["Die Bilanz bezieht sich auf das Jahr 2020."]]
    assert read == [[1], [2, 3]], "what came back is read as one more batch"
    assert report.followups["OEO_00050016"] == {"asked": 1, "served": 1}


def test_a_model_that_keeps_asking_cannot_loop():
    """Bounded, because a stop heuristic without a bound is an outage."""
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if (s.owner_kind, s.owner_id) not in exclude]

    def more_sources(document_id, queries, exclude):
        return [s for s in _sources()[1:]
                if (s.owner_kind, s.owner_id) not in exclude]

    rounds = []

    def harvest(batch, prior=None):
        rounds.append(1)
        return {"tuples": [], "status": "partial", "need_more": ["mehr davon"]}

    harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(retrieve),
                     harvest=harvest, more_sources=more_sources)
    assert len(rounds) == 2, "one follow-up per chain, then it stops asking"
