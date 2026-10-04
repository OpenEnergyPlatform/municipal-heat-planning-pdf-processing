"""The lists a document closes, from the plan to the file and back.

A dynamic axis or value list is a closed list only once the document is
known: the scenarios a publication documents, the regions it names. The plan
built those lists and searched with them, and every request that read the
passages, and the check of their answers, was built from the run's spec, where
the lists are empty. Nothing failed. The model was offered nothing to choose
from and wrote a wording, on exactly the fields whose point is the choice.

So these run the real document loop, the real harvester and the passes over a
harvest on disk, for a profile that closes lists per document, with the model
stubbed and nothing else.
"""
import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from docpipe.extraction import fields, recheck, review, runner, trace
from docpipe.extraction.pipeline import (DocumentReport, Source, WorkItem,
                                         fold_batch, group_items,
                                         rows_from_reply)
from docpipe.extraction.spec import fingerprints, load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
RUN = "EN_NPi2100"
FAMILY = "Szenario-Familie"
TEXT = ("The Current Policies scenario (CurPol) is reported here for Germany "
        "in 2030 and 2050.")
LISTS = {
    "scenario": {RUN: [RUN], "out:family": [FAMILY]},
    "scenario_label": {RUN: [RUN], "out:family": [FAMILY]},
    "scenario_region": {"https://example.org/region/Germany": ["Germany"]},
}


@pytest.fixture
def spec(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    return load_spec(json.loads(
        (PROFILES / "scenarios" / "extraction_spec.json").read_text(
            encoding="utf-8")))


def _corpus(path) -> Path:
    """A corpus of one publication that documents one AR6 run."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                is_current INTEGER DEFAULT 1);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               content TEXT);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             markdown TEXT, caption TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             description TEXT, caption TEXT);
        CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,
                                name TEXT);
        CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);
        INSERT INTO Documents VALUES (1, 'a.pdf', 1);
        INSERT INTO Scenarios VALUES (10, 900, 'EN_NPi2100');
        INSERT INTO DocumentScenarios VALUES (1, 10);
    """)
    conn.execute("INSERT INTO Sections VALUES (10, 1, ?)", (TEXT,))
    conn.commit()
    conn.close()
    return path


def _batch(own=None, text=TEXT):
    batch = group_items([WorkItem(1, None, Source(
        "section", 10, text, {"document_id": 1, "page": 3}))],
        max_sources=runner.BATCH_SOURCES)[0]
    batch.spec = own
    return batch


def _harvester(monkeypatch, spec, rows_reply, answer):
    """The real field-wise harvester over a stubbed value request and a
    stubbed field request. `answer(slot)` is what the model says per field."""
    asked: list = []
    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None, **kw):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            asked.extend(slots)
            return {"fields": {slot.name: {"answers": {
                row.label: answer(slot, row) for row in rows}}
                for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    return runner.make_fieldwise_harvester(spec=spec), asked


# ---------------------------------------------------------------------------
# The copy the plan makes
# ---------------------------------------------------------------------------

def test_only_the_lists_differ_in_a_documents_spec(spec):
    """The copy used to keep the parameters and drop the two questions the
    spec asks. Nobody read them off the copy while it only fed the search;
    the moment it built a request, "which field is this value?" went out as
    null."""
    filled = runner.fill_dynamic_axes(spec, LISTS)
    assert filled is not spec
    assert spec.parameter_question, "the fixture has to hold a question"
    assert filled.parameter_question == spec.parameter_question
    assert filled.unit_question == spec.unit_question
    assert (fields.parameter_slot(filled).question
            == fields.parameter_slot(spec).question)
    moved = {key for key, value in fingerprints(filled).items()
             if fingerprints(spec).get(key) != value}
    assert moved and all(key.startswith(("axis/", "value/", "parameter/"))
                         for key in moved), moved
    assert filled.by_uri["scenario_label"].vocabulary == LISTS[
        "scenario_label"]
    assert runner.fill_dynamic_axes(spec, {}) is spec


def test_a_documents_spec_or_none_when_its_lists_cannot_be_closed(spec,
                                                                  caplog):
    """What a pass over a harvest on disk reads a document against. A list
    that cannot be closed is not replaced by the run's empty one: asked
    against that, a choice degrades to a wording and nothing reports it."""
    own = runner.make_document_spec(None, spec, lambda conn, did: LISTS)(1)
    assert own.by_uri["scenario_label"].vocabulary == LISTS["scenario_label"]
    assert runner.make_document_spec(None, spec, None)(1) is spec, (
        "no list depends on the document")
    assert runner.make_document_spec(None, spec,
                                     lambda conn, did: {})(1) is None
    assert runner.make_document_spec(None, spec,
                                     lambda conn, did: LISTS)(None) is None, (
        "which document is not known")

    def broken(conn, document_id):
        raise sqlite3.OperationalError("no such table: Scenarios")

    with caplog.at_level(logging.WARNING):
        assert runner.make_document_spec(None, spec, broken)(1) is None
    assert "dynamic axes unreadable" in caplog.text


# ---------------------------------------------------------------------------
# The requests and the check
# ---------------------------------------------------------------------------

def test_a_choice_outside_the_documents_list_is_not_taken_for_one(monkeypatch,
                                                                  spec):
    """Through the real harvester and the real fold. A run of the list is
    stored as that run, the family entry as the family, and a name the list
    does not hold backs nothing: the coordinate stays empty and says so."""
    filled = runner.fill_dynamic_axes(spec, LISTS)
    year = spec.by_uri["scenario_year"]
    reply = {"tuples": [{"source": "Q1", "value": "2030", "value_raw": "2030",
                         "quote": TEXT}],
             "status": "complete", "need_more": []}

    def stored(scenario):
        def answer(slot, row):
            value = year.label if slot.name == "parameter" else scenario
            return {"value": value, "value_raw": "CurPol", "quote": TEXT}

        harvest, asked = _harvester(monkeypatch, spec, reply, answer)
        batch = _batch(filled)
        report = DocumentReport(1)
        fold_batch(batch, harvest(batch), report,
                   spec=runner.spec_of(batch, spec))
        offered = [[o.label for o in slot.options] for slot in asked
                   if slot.name == "scenario"]
        assert offered and all(RUN in labels for labels in offered)
        assert [slot.question for slot in asked
                if slot.name == "parameter"] == [spec.parameter_question]
        row, = report.tuples
        return row

    row = stored(RUN)
    assert (row["scenario"], row["scenario_state"]) == (RUN, fields.READ)
    row = stored(FAMILY)
    assert (row["scenario"], row["scenario_state"]) == ("out:family",
                                                        fields.READ)
    row = stored("the baseline of another paper")
    assert row.get("scenario") is None
    assert row["scenario_state"] == fields.UNBACKED


def test_a_row_without_an_entry_keeps_its_wording(monkeypatch, spec):
    """The value request leaves `value` out and writes the wording when no
    entry of the list fits. Such a row was dropped unasked, as a number
    without a unit; it is a reading, kept unmapped."""
    filled = runner.fill_dynamic_axes(spec, LISTS)
    region = spec.by_uri["scenario_region"]
    reply = {"tuples": [{"source": "Q1", "value_raw": "Current Policies",
                         "quote": TEXT}],
             "status": "complete", "need_more": []}

    def answer(slot, row):
        value = region.label if slot.name == "parameter" else FAMILY
        return {"value": value, "value_raw": "Current Policies",
                "quote": TEXT}

    harvest, asked = _harvester(monkeypatch, spec, reply, answer)
    batch = _batch(filled)
    report = DocumentReport(1)
    fold_batch(batch, harvest(batch), report,
               spec=runner.spec_of(batch, spec))
    assert [slot.name for slot in asked][:1] == ["parameter"]
    row, = report.tuples
    assert row["parameter"] == "scenario_region"
    assert row["value_uri"] is None
    assert any(flag.startswith("unmapped:value") for flag in row["flags"])


def test_a_year_its_quote_does_not_print_is_dropped_before_it_is_asked(spec):
    """A wording that is not in the passage it cites is not a reading, and
    the place to say so is before any field is swept for it. A year of a
    spec that measures nothing is such a wording: left to the verifier, as a
    number is, it was swept through every window first."""
    reply = {"tuples": [{"source": "Q1", "value": "2031", "value_raw": "2031",
                         "quote": TEXT}]}
    rows, orphans = rows_from_reply(_batch(), reply, None, spec)
    assert rows == []
    assert [o["_why"] for o in orphans] == ["text value not in its quote"]
    kept, _ = rows_from_reply(_batch(), {"tuples": [
        {"source": "Q1", "value": "2030", "value_raw": "2030",
         "quote": TEXT}]}, None, spec)
    assert len(kept) == 1
    # Where something is measured a digit string stays the verifier's.
    kwp = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(
            encoding="utf-8")))
    rows, orphans = rows_from_reply(_batch(), reply, None, kwp)
    assert len(rows) == 1 and orphans == []
    rows, orphans = rows_from_reply(_batch(), reply)
    assert len(rows) == 1 and orphans == []


def test_the_harvester_asks_nothing_about_a_year_no_quote_prints(monkeypatch,
                                                                spec):
    """The same rule where it saves the requests: the row never exists, so
    no parameter and no scenario is asked about it."""
    reply = {"tuples": [{"source": "Q1", "value": "2031", "value_raw": "2031",
                         "quote": TEXT}],
             "status": "complete", "need_more": []}
    harvest, asked = _harvester(monkeypatch, spec, reply,
                                lambda slot, row: {"value": "out:unstated"})
    out = harvest(_batch(runner.fill_dynamic_axes(spec, LISTS)))
    assert asked == []
    assert [claim.get("_why") for claim in out["tuples"]] == [
        "text value not in its quote"]


# ---------------------------------------------------------------------------
# The document loop
# ---------------------------------------------------------------------------

@pytest.fixture
def corpus_run(monkeypatch, tmp_path):
    """(database, output directory) for `runner.main`, with everything that
    is a server, an index or a card stubbed."""
    from docpipe.inference import faiss_store
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    monkeypatch.setenv("EXTRACT_ANCHORS", "0")
    monkeypatch.setattr(runner, "ATTACH_IMAGES", False)
    # `main` fits the batch size to the served window and writes it to the
    # module: put back after the test, or every later test batches by it.
    monkeypatch.setattr(runner, "BATCH_SOURCES", runner.BATCH_SOURCES)
    monkeypatch.setattr(runner, "assert_serving", lambda *a, **k: 40960)
    monkeypatch.setattr(runner, "set_model_len", lambda n: None)
    monkeypatch.setattr(runner, "start_limit", lambda: None)
    monkeypatch.setattr(runner, "watch_server", lambda *a, **k: None)
    monkeypatch.setattr(runner, "install_stop_handler", lambda: None)
    monkeypatch.setattr(runner, "prime_probe_cache", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "make_more_sources",
                        lambda *a, **k: (lambda *x: []))
    monkeypatch.setattr(runner, "make_rest_of_document", lambda *a, **k: None)
    monkeypatch.setattr(runner, "make_parents", lambda *a, **k: None)
    monkeypatch.setattr(runner, "make_structure",
                        lambda *a, **k: (lambda d: []))
    monkeypatch.setattr(faiss_store, "load_global_index",
                        lambda p: (None, {}))
    monkeypatch.setattr(runner, "make_review_asker",
                        lambda image_root=None: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "make_review_sources",
                        lambda db: (lambda row: []))
    yield _corpus(tmp_path / "corpus.db"), tmp_path / "out"
    # A run that ends normally leaves its trace open, as the process ends
    # with it. Here the next test would write into this one's files.
    trace.close()


def test_every_batch_of_a_document_reads_against_its_lists(tmp_path,
                                                           monkeypatch,
                                                           corpus_run):
    """`runner.main` over one document. The spec the plan filled is on every
    batch the harvester is handed, the rows the next batch is told about
    were checked against it, and so is what reaches the file."""
    db, out = corpus_run
    seen = {"specs": [], "priors": []}

    def make_retrieve(conn, index, id_to_pos, cache_conn, fetch, limit=0):
        def retrieve(probes, document_id, exclude):
            return [Source("section", 10 + n, TEXT,
                           {"document_id": document_id, "page": 1 + n,
                            "title": "Scenarios"}) for n in range(2)]
        return retrieve

    def make_fieldwise(*a, **k):
        def harvest(batch, prior=None):
            seen["specs"].append(batch.spec)
            seen["priors"].append(list(prior or []))
            label = batch.label(0)
            return {"tuples": [
                {"source": label, "parameter": "scenario_label",
                 "value": RUN, "value_raw": "Current Policies",
                 "quote": "The Current Policies scenario (CurPol)"},
                {"source": label, "parameter": "scenario_year",
                 "value": "2030", "value_raw": "2030",
                 "scenario": "Current Policies",
                 "scenario_raw": "Current Policies",
                 "quote": "is reported here for Germany in 2030"}],
                "status": "complete", "need_more": []}
        return harvest

    monkeypatch.setattr(runner, "make_retrieve", make_retrieve)
    monkeypatch.setattr(runner, "make_fieldwise_harvester", make_fieldwise)
    monkeypatch.setattr(runner, "FIELDWISE", True)
    monkeypatch.setattr(runner, "fit_batch_sources", lambda *a, **k: 1)
    monkeypatch.setattr(runner, "LLM_PARALLEL", 1)

    assert runner.main([str(db), "no.index", str(out), "--image-root",
                        str(tmp_path), "--document", "1"]) == 0
    assert len(seen["specs"]) == 2, "one batch per passage"
    for own in seen["specs"]:
        assert own is not None, "a batch without its document's spec"
        assert RUN in own.by_uri["scenario_label"].vocabulary
    # What the second batch is told the first one found: checked against the
    # document's list, where "Current Policies" is no entry.
    assert seen["priors"][0] == [] and seen["priors"][1]
    told = [row for row in seen["priors"][1]
            if row["parameter"] == "scenario_year"]
    assert told and told[0].get("scenario") is None
    written = [json.loads(line) for line in
               (out / "a.jsonl").read_text(encoding="utf-8").splitlines()]
    labels = [row for row in written if row.get("kind") == "tuple"
              and row["parameter"] == "scenario_label"]
    assert labels and all(row["value_uri"] == RUN for row in labels)
    assert not any(flag.startswith("unmapped:value")
                   for row in labels for flag in row.get("flags") or ())


# ---------------------------------------------------------------------------
# The passes over a harvest on disk
# ---------------------------------------------------------------------------

def _harvest_file(out: Path, spec) -> Path:
    """One harvested year whose scenario is the family entry of the list,
    stored as the harvest stores it: the entry, and no wording beside it."""
    out.mkdir(exist_ok=True)
    row = {"kind": "tuple", "parameter": "scenario_year", "value": "2030",
           "value_raw": "2030", "quote": TEXT, "tier": "text_located",
           "flags": [], "parameter_state": fields.READ,
           "scenario": "out:family", "scenario_state": fields.READ,
           "scenario_quote": "Die Familie der CurPol-Szenarien, 2030.",
           "provenance": {"document_id": 1, "owner_kind": "section",
                          "owner_id": 10, "page": 3}}
    path = out / "a.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in (
        row, {"kind": "summary", "document_id": 1, "tuples": 1,
              "refusals": 0})) + "\n", encoding="utf-8")
    (out / "a.stamp.json").write_text(json.dumps({"spec": "sha"}),
                                      encoding="utf-8")
    return path


def test_a_recheck_holds_a_choice_to_the_list_it_was_made_from(tmp_path,
                                                               spec):
    """The harvest backed the coordinate as an entry of the document's list,
    by one of its spellings. Rechecked against the run's spec the entry is a
    bare identifier no quote prints, and a coordinate the harvest read was
    stripped."""
    lists = dict(LISTS, scenario={RUN: [RUN],
                                  "out:family": [FAMILY, "Familie"]})
    filled = runner.fill_dynamic_axes(spec, lists)
    path = _harvest_file(tmp_path / "out", spec)
    stats = recheck.run(path.parent, spec, spec_for=lambda did: filled)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert (row["scenario"], row["scenario_state"]) == ("out:family",
                                                        fields.READ)
    assert stats["documents"] == 1 and stats["stamps cleared"] == 1


def test_a_recheck_leaves_a_document_whose_lists_cannot_be_closed(tmp_path,
                                                                  spec):
    path = _harvest_file(tmp_path / "out", spec)
    before = path.read_bytes()
    stats = recheck.run(path.parent, spec, spec_for=lambda did: None)
    assert path.read_bytes() == before
    assert stats[fields.LISTS_UNREADABLE] == 1 and stats["documents"] == 0
    assert (path.parent / "a.stamp.json").is_file(), (
        "still the output of the run its stamp names")


def test_the_passes_over_a_harvest_are_given_the_documents_lists(
        tmp_path, monkeypatch, corpus_run, caplog):
    """`--review` and `--recheck` from the command line: each is handed a
    way to the document's own spec, open for as long as the pass runs, and
    each says when it had to leave a document alone."""
    db, out = corpus_run
    out.mkdir()
    seen = []

    def fake(name):
        def run(*a, **kw):
            own = kw["spec_for"](1)
            seen.append((name, own.by_uri["scenario_label"].vocabulary))
            return Counter({fields.LISTS_UNREADABLE: 2})
        return run

    monkeypatch.setattr(review, "run", fake("review"))
    monkeypatch.setattr(recheck, "run", fake("recheck"))
    with caplog.at_level(logging.WARNING):
        assert runner.main([str(db), "no.index", str(out), "--review",
                            "--image-root", str(tmp_path)]) == 0
        assert runner.main([str(db), "no.index", str(out),
                            "--recheck"]) == 0
    assert [name for name, _ in seen] == ["review", "recheck"]
    assert all(RUN in lists for _, lists in seen)
    assert caplog.text.count("2 document(s) left alone") == 2
