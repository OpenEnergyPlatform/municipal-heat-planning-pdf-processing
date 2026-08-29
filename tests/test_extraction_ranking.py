"""The ranking the plan is cut at, and the questions it is built from.

Every one of these was a real defect, measured over 65 harvested documents and
15,082 values: the plan was a concatenation of per-probe lists rather than a
ranking (median rank of a productive source 77 instead of 26), the query
templates were merged in beside the anchors and pushed it to 84, and the cap
that was going to be put on top of that would have thrown away correct
readings to save time.
"""
from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import Source, plan_document
from docpipe.extraction.spec import load

SPEC = load({
    "parameter_question": "Um WELCHE Kennzahl handelt es sich?",
    "parameters": [{
        "uri": "OEO_00050016",
        "label": "Endenergieverbrauch",
        "description": "Endenergieverbrauch je Energieträger, Sektor und Jahr, wie im Plan bilanziert.",
        "unit_target": "OEO_00050008",
        "units_accepted": {"MWh/a": 1.0},
        "axes": {"year": {"type": "int", "question": "Für welches Jahr?"}},
        "example": {"source": "| Erdgas | 42.005 | MWh/a |",
                    "tuples": [{"value": 42005, "unit": "MWh/a",
                                "unit_raw": "MWh/a"}]},
    }, {
        "uri": "OEO_00000199",
        "label": "Emission",
        "description": "Treibhausgasemissionen je Sektor und Jahr, wie im Plan bilanziert.",
        "unit_target": "OEO_00000201",
        "units_accepted": {"t CO2eq/a": 1.0},
        "axes": {"year": {"type": "int", "question": "Für welches Jahr?"}},
        "example": {"source": "| THG | 12.000 | t CO2eq/a |",
                    "tuples": [{"value": 12000, "unit": "t CO2eq/a",
                                "unit_raw": "t CO2eq/a"}]},
    }],
})


class _Prepared(dict):
    """The three things fuse_prepared reads out of a prepared document."""

    def __init__(self, owners):
        super().__init__(faiss_ids=list(range(len(owners))),
                         owner_of={i: o for i, o in enumerate(owners)},
                         rows_per_owner={o: 1 for o in owners})


def _scores(rows):
    """A score matrix as numpy-free stand-ins: one .tolist() per probe row."""
    class Row(list):
        def tolist(self):
            return list(self)
    return [Row(r) for r in rows]


def _content(_conn, kind, owner_id):
    return {"document_id": 7, "owner_kind": kind, "owner_id": owner_id,
            "text": f"Passage {kind} {owner_id}", "page_number": 1,
            "section_number": 1, "section_title": "", "title": ""}


def test_the_best_match_of_the_last_probe_outranks_the_worst_of_the_first():
    """The defect the plan was built on: results came back grouped per probe
    and were concatenated in probe order, so a passage that matched probe two
    perfectly sat behind everything probe one had scraped up."""
    from docpipe.inference import faiss_store

    prepared = _Prepared([("section", 1), ("section", 2), ("section", 3)])
    # probe 1 likes sections 1 and 2 a little, probe 2 loves section 3.
    scores = _scores([[0.30, 0.29, 0.01], [0.02, 0.03, 0.95]])
    positions = _scores([[0, 1, 2], [0, 1, 2]])

    hits = faiss_store.fuse_prepared(None, prepared, scores, positions, 0,
                                     content_fetcher=_content,
                                     probes=["erste", "zweite"])
    assert [h["owner_id"] for h in hits] == [3, 1, 2]
    assert hits[0]["rank"] == 0 and hits[0]["probe"] == "zweite", (
        "each hit says which wording found it, or the next round of anchors "
        "cannot be written from anything")


def test_a_probe_that_matches_nothing_cannot_push_a_good_hit_down():
    """Max over probes, not mean. Averaging a strong match against fifteen
    questions the passage has nothing to do with is how the templates pushed
    the median productive rank from 26 to 84."""
    from docpipe.inference import faiss_store

    prepared = _Prepared([("section", 1), ("section", 2)])
    sharp = _scores([[0.9, 0.1]])
    positions = _scores([[0, 1]])
    alone = faiss_store.fuse_prepared(None, prepared, sharp, positions, 0,
                                      content_fetcher=_content)

    vague = _scores([[0.9, 0.1], [0.5, 0.5], [0.5, 0.5], [0.5, 0.5]])
    positions = _scores([[0, 1]] * 4)
    with_noise = faiss_store.fuse_prepared(None, prepared, vague, positions, 0,
                                           content_fetcher=_content)
    assert [h["owner_id"] for h in alone] == [1, 2]
    assert [h["owner_id"] for h in with_noise] == [1, 2]


def test_the_cap_falls_on_the_prose_and_never_on_a_table():
    """Top 50 is the limit, and it is a limit on the half a ranking has to
    earn. 12,094 of 15,082 values came out of a table or a figure."""
    ranked = ([Source("section", 100 + i, f"Abschnitt {i}", {}) for i in range(9)]
              + [Source("table", 200 + i, f"Tabelle {i}", {}) for i in range(5)])

    items, report = plan_document(
        7, SPEC, ["{label}"],
        extra_probes={p.uri: ["Ein Satz wie er im Plan stünde."]
                      for p in SPEC.parameters},
        retrieve=lambda probes, doc, exclude: list(ranked), prose_top=2)

    kinds = [it.source.owner_kind for it in items]
    assert kinds.count("table") == 5, "the cap must not reach a table"
    assert kinds.count("section") == 2
    assert report.planned["prose_top"] == 2


def test_the_plan_is_built_from_the_anchors_and_not_from_the_templates():
    """Measured: with the templates merged in, the source a value was really
    read from sat at median rank 84. Without them, at 26."""
    asked = []

    def retrieve(probes, document_id, exclude):
        asked.append(list(probes))
        return []

    plan_document(7, SPEC, ["{label} Tabelle"],
                  extra_probes={p.uri: [f"Anker fuer {p.label}."]
                                for p in SPEC.parameters},
                  retrieve=retrieve)
    assert asked == [["Anker fuer Endenergieverbrauch.", "Anker fuer Emission."]]
    assert not any("Tabelle" in probe for probe in asked[0]), (
        "a template names the thing, an anchor says the sentence")


def test_without_anchors_the_plan_says_so_instead_of_ranking_badly_in_silence(
        caplog):
    """A run whose ranking quietly fell back to the templates is a run whose
    numbers mean something else than the last one's."""
    import logging

    with caplog.at_level(logging.WARNING):
        plan_document(7, SPEC, ["{label} Tabelle"],
                      retrieve=lambda probes, doc, exclude: [])
    assert any("no anchors" in r.getMessage() for r in caplog.records)


def test_every_question_gets_its_own_anchor_target():
    """One anchor set per question. The sentence that states a value and the
    sentence that states its reference year are not the same sentence."""
    keys = [t[0] for t in runner.anchor_targets(SPEC)]
    assert runner.PARAMETER_ANCHOR in keys, (
        "which quantity a number is, is asked for and so must be searched for")
    for parameter in SPEC.parameters:
        assert parameter.uri in keys
        assert runner.anchor_key(parameter.uri, "year") in keys
    assert len(keys) == len(set(keys))


def test_an_axis_anchor_is_written_from_the_axis_question():
    """The payload decides what the anchors are about. An axis target that
    carried only the parameter description would get the parameter's own six
    sentences back, which is what the field sweep searched with before."""
    target = next(t for t in runner.anchor_targets(SPEC)
                  if t[0] == runner.anchor_key(SPEC.parameters[0].uri, "year"))
    assert target[3] == "Für welches Jahr?"
    value = next(t for t in runner.anchor_targets(SPEC)
                 if t[0] == SPEC.parameters[0].uri)
    assert value[3] is None, "the value question is the parameter itself"


def test_the_parameter_is_a_choice_over_the_spec_with_a_way_to_say_nothing():
    slot = fields.parameter_slot(SPEC)
    answerable = slot.answerable()
    assert set(answerable) == {"Endenergieverbrauch", "Emission",
                               fields.UNSTATED}
    assert slot.required and slot.question


def test_the_structural_floor_is_every_table_and_every_figure():
    """Whether something is a table is not a question a similarity search
    should be asked. Retrieval decides the order, structure decides the set."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, is_current INT);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INT);
        CREATE TABLE "Tables" (id INTEGER PRIMARY KEY, section INT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INT);
        INSERT INTO Documents VALUES (7, 1), (8, 1);
        INSERT INTO Sections VALUES (1, 7), (2, 7), (3, 8);
        INSERT INTO "Tables" VALUES (10, 1), (11, 2), (12, 3);
        INSERT INTO Images VALUES (20, 1), (21, 3);
    """)

    def fetch(_conn, kind, owner_id):
        return {"owner_kind": kind, "owner_id": owner_id, "text": "",
                "document_id": 7, "page_number": 1, "section_number": 1,
                "section_title": "", "title": ""}

    structure = runner.make_structure(conn, fetch)
    assert [(s.owner_kind, s.owner_id) for s in structure(7)] == [
        ("table", 10), ("table", 11), ("figure", 20)], (
        "every table and figure of THIS document, and nothing of the next one")
    assert [(s.owner_kind, s.owner_id) for s in structure(8)] == [
        ("table", 12), ("figure", 21)]


def test_a_table_whose_content_is_gone_is_skipped_and_not_planned_empty():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INT);
        CREATE TABLE "Tables" (id INTEGER PRIMARY KEY, section INT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INT);
        INSERT INTO Sections VALUES (1, 7);
        INSERT INTO "Tables" VALUES (10, 1), (11, 1);
    """)
    structure = runner.make_structure(
        conn, lambda _c, kind, oid: None if oid == 10 else
        {"owner_kind": kind, "owner_id": oid, "text": "x", "document_id": 7,
         "page_number": 1, "section_number": 1, "section_title": "",
         "title": ""})
    assert [s.owner_id for s in structure(7)] == [11]


def test_the_parallel_scheduler_harvests_a_batch_that_fixes_no_parameter():
    """The path the corpus actually runs on. The serial harvest_document is
    what the tests owned, so a plan that had correctly dropped 825 sources to
    162 still died on its first batch: the scheduler keyed its sweeps through
    batch.parameter.uri, and a document-level plan has no parameter."""
    from docpipe.extraction.pipeline import Batch, WorkItem, batch_uri

    batches = [Batch(7, None, [WorkItem(7, None,
                                        Source("table", n, "| x | 1 |", {}))])
               for n in (1, 2)]
    assert batch_uri(batches[0]) is None

    seen = []

    def harvest(batch, prior=None):
        seen.append([(i.source.owner_kind, i.source.owner_id)
                     for i in batch.items])
        return {"tuples": [], "status": "complete", "need_more": []}

    answered = runner.harvest_batches(batches, harvest, workers=2)
    assert len(answered) == 2 and sorted(seen) == [[("table", 1)],
                                                   [("table", 2)]]
    assert all(reply.get("status") == "complete" for _b, reply in answered), (
        "a batch that raised comes back as a failure sentinel, and would hide "
        "exactly this defect behind a retry"
    )
