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
# A document-level plan does not fix a parameter, so a claim carries its own.
PARAM = SPEC.parameters[0].uri


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
    """Adapt a one-probe stub to the fused contract retrieval now has.

    plan_document hands every probe over in one call and gets ONE ranking
    back, best score per owner. The stubs here are written per probe, so this
    runs them in turn and merges, keeping each owner at the position the first
    probe that found it put it.
    """
    def retrieve(probes, document_id, exclude):
        taken = set(exclude)
        out = []
        for probe in probes:
            for source in fn(probe, document_id, set(taken)) or []:
                key = (source.owner_kind, source.owner_id)
                if key in taken:
                    continue
                taken.add(key)
                out.append(source)
        return out
    return retrieve


def _per_source(fn, spec=None):
    """Adapt a one-source stub to the batched contract the harvest now has.

    A request reads several sources at once, and every claim names the source
    it came from. This reproduces that from a stub written per source, which
    is what these tests are about: the loop's bookkeeping, not the batching.
    """
    spec = spec if spec is not None else SPEC
    def harvest(batch, prior=None):
        parameter = batch.parameter or spec.parameters[0]
        tuples = []
        for index, item in enumerate(batch.items):
            for claim in fn(item.source, parameter) or []:
                # A document-level plan gets the parameter from the row, the
                # way the field sweep fills it in a real run.
                tuples.append({"parameter": parameter.uri, **claim,
                               "source": batch.label(index)})
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


def test_the_plan_asks_retrieval_once_and_not_until_the_document_is_gone():
    """The defect this replaced: retrieval was called again with everything it
    had already returned excluded, which walks the ranking to the end of the
    document. Measured on the corpus, 277 planned sources against 234 owners,
    once per parameter."""
    calls = []

    def retrieve(query, document_id, exclude):
        calls.append(query)
        return [s for s in _sources()
                if (s.owner_kind, s.owner_id) not in exclude]

    def harvest(source, parameter):
        return []

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(retrieve), harvest=_per_source(harvest))
    assert len(calls) == len(expand(TEMPLATES, SPEC.parameters[0])),         "one pass over the probes, no second round"
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
    assert kinds == {"tuple", "refusal", "summary"}
    # The summary is last, because it is computed from everything above it.
    assert rows[-1]["kind"] == "summary" and rows[-1]["document_id"] == 7
    accepted = [r for r in rows if r["kind"] == "tuple"][0]
    assert accepted["provenance"]["owner_id"] == 1
    assert accepted["provenance"]["page"] == 31


def test_every_table_is_planned_whether_or_not_a_probe_ranked_it():
    """The floor is structural now, not lexical. 12,094 of 15,082 values came
    out of a table or a figure, and whether something is a table is not a
    question a similarity search should be asked."""
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if ("table", s.owner_id) not in exclude]

    def structure(document_id):
        return _sources()[:2]              # table 1 (ranked) + table 2 (not)

    harvested = []

    def harvest(source, parameter):
        harvested.append(source.owner_id)
        return []

    report = harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(retrieve),
                              harvest=_per_source(harvest), structure=structure)
    assert harvested == [1, 2], "the ranked table is not harvested twice"
    assert report.fallback["document"] == {"candidates": 2, "leftover": 1}


def test_prose_is_capped_and_tables_are_not():
    """Top 50 is the limit on the half a ranking has to earn, and only on it."""
    prose = [Source("section", 100 + i, f"Abschnitt {i} mit 42.005 MWh/a", {})
             for i in range(8)]
    tables = [Source("table", 200 + i, f"| Erdgas | 42.00{i} | MWh/a |", {})
              for i in range(4)]

    def retrieve(query, document_id, exclude):
        return [s for s in prose + tables
                if (s.owner_kind, s.owner_id) not in exclude]

    def harvest(source, parameter):
        return []

    report = harvest_document(7, SPEC, TEMPLATES, prose_top=3,
                              retrieve=_per_probe(retrieve),
                              harvest=_per_source(harvest))
    assert report.planned["prose"] == 3
    assert report.planned["visual"] == 4, "the cap must not reach the tables"


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
        return {"tuples": [{"parameter": PARAM, "source": "Q2", "value": 17300, "unit": "MWh/a",
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
        return {"tuples": [{"parameter": PARAM, "source": "Q1", "value": 17300, "unit": "MWh/a",
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
        return {"tuples": [{"parameter": PARAM, "source": "Q1", "value": 17300, "unit": "MWh/a",
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
        return {"tuples": [{"parameter": PARAM, "source": "Q1", "value": 42005, "unit": "MWh/a",
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
    assert report.followups["document"] == {"asked": 1, "served": 1}


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
        return {"tuples": [], "status": "partial", "need_more": ["Die Endenergiebilanz ist in MWh pro Jahr angegeben."]}

    harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(retrieve),
                     harvest=harvest, more_sources=more_sources)
    assert len(rounds) == 2, "one follow-up per chain, then it stops asking"


# ---------------------------------------------------------------------------
# What the audit found: routing, the hint, and the counting
# ---------------------------------------------------------------------------

def test_a_claim_that_names_no_source_is_refused_not_filed_under_the_first():
    """Filing an unroutable claim under Q1 was a way to manufacture evidence:
    verify rebuilds a missing quote from the source it is handed whenever the
    value occurs there once, so a number read from the fourth passage could
    be accepted carrying the first passage's page, section and image."""
    def harvest(batch, prior=None):
        return {"tuples": [{"parameter": PARAM, "value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a",
                            "carrier": "Erdgas", "source": "Q9",
                            "quote": "Erdgas macht 42.005 MWh/a aus"}],
                "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(_all_three), harvest=harvest)
    assert not report.tuples
    assert [r["reason"] for r in report.refusals] == ["claim names no source"]


def test_only_verified_values_become_the_next_batch_s_prior():
    """The prompt tells the model not to repeat what prior holds. A claim the
    verifier threw away used to go in anyway, so one bad quote suppressed
    that value for the rest of the document — leaving neither a tuple nor a
    refusal where it should have been found."""
    seen = []

    def harvest(batch, prior=None):
        seen.append(list(prior or []))
        owner = batch.items[0].source.owner_id
        if owner == 1:
            return {"tuples": [
                {"parameter": PARAM, "value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a",
                 "carrier": "Erdgas", "quote": "| Erdgas | 42.005 | MWh/a |"},
                {"parameter": PARAM, "value": 999999, "unit": "MWh/a", "unit_raw": "MWh/a",
                 "carrier": "Erdgas", "quote": "| Erdgas | 42.005 | MWh/a |"}],
                "status": "complete", "need_more": []}
        return {"tuples": [], "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(_all_three),
                              harvest=harvest, max_sources=1)
    assert len(report.refusals) == 1, "the second value is not in its quote"
    assert [t["value"] for t in seen[1]] == [42005], (
        "the refused value must not be handed on as already extracted")


def test_passages_the_model_asked_for_are_counted_as_harvested():
    """owners_harvested was frozen at plan time, so a report could claim to
    have read fewer passages than it read — and that number is the one the
    coverage audit rests on."""
    def retrieve(query, document_id, exclude):
        return [s for s in _sources()[:1]
                if (s.owner_kind, s.owner_id) not in exclude]

    def more_sources(document_id, queries, exclude):
        return [s for s in _sources()[1:]
                if (s.owner_kind, s.owner_id) not in exclude]

    def harvest(batch, prior=None):
        if batch.followed_up:
            return {"tuples": [], "status": "complete", "need_more": []}
        return {"tuples": [], "status": "partial", "need_more": ["Die Endenergiebilanz ist in MWh pro Jahr angegeben."]}

    report = harvest_document(7, SPEC, TEMPLATES, retrieve=_per_probe(retrieve),
                              harvest=harvest, more_sources=more_sources)
    assert report.owners_harvested == 3, (
        "one planned passage plus the two the model asked for")
    assert report.followups["document"] == {"asked": 1, "served": 1}


def test_routing_is_never_stricter_than_verification():
    """A table row retyped without its column padding is the normal case.
    Routing used to demand a byte-exact substring while verify collapses
    whitespace, so claims verification would have accepted were refused
    before they were ever offered to it — 276 of one pilot's refusals."""
    def harvest(batch, prior=None):
        return {"tuples": [{"parameter": PARAM, "value": 17300, "unit": "MWh/a", "unit_raw": "MWh/a",
                            "carrier": "Heizöl",
                            "quote": "| Heizöl |   17.300 |  MWh/a |"}],
                "status": "complete", "need_more": []}

    report = harvest_document(7, SPEC, TEMPLATES,
                              retrieve=_per_probe(_all_three), harvest=harvest)
    assert not report.refusals, [r["reason"] for r in report.refusals]
    assert report.tuples[0]["provenance"]["owner_id"] == 2
