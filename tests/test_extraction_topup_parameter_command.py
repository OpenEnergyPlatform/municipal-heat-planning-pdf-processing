"""`--top-up-parameters`, the command, over a column of one's own.

The pass is one more way to run the harvest's own loop, so what is held here
is what the command does around a document: the plain run names the pass, the
pass appends and stamps and traces beside the harvest, a second run is not one
request, a document the server did not serve ends the run non-zero with its
file untouched, and the two top-up passes are not run as one.

`runner.main` itself, with the corpus a few SQLite tables and the model a
stub; the profile is `scenarios` and its spec lies in a file of its own, so
the harvest has a folder to itself.
"""
import copy
import inspect
import json
import logging
import sqlite3
from pathlib import Path

import pytest

from docpipe.extraction import runner, trace
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
FUNDER = ("This work was funded by the German Federal Ministry of Education "
          "and Research under grant 01LA1809A.")
PASSAGE = ("The Current Policies scenario (CurPol) is reported here for "
           "Germany in 2030 and 2050. " + FUNDER)
RUN = "EN_NPi2100"


def _corpus(path) -> Path:
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
    conn.execute("INSERT INTO Sections VALUES (10, 1, ?)", (PASSAGE,))
    conn.commit()
    conn.close()
    return path


class Column:
    """`runner.main` over one publication, the scenarios profile's spec in a
    file of its own, and a model that is a stub."""

    def __init__(self, monkeypatch, tmp_path):
        from docpipe.inference import faiss_store
        self.tmp = tmp_path
        self.folder = tmp_path / "column"
        self.folder.mkdir()
        self.out = self.folder / "harvest"
        self.spec_file = self.folder / "spec.json"
        self.db = _corpus(tmp_path / "corpus.db")
        self.raw = json.loads((PROFILES / "scenarios"
                               / "extraction_spec.json")
                              .read_text(encoding="utf-8"))
        self.requests: list = []            # the probes every search used
        self.anchored: list = []            # parameters document_anchor saw
        self.harvests: list = []            # parameters each batch offered
        self.lose = [0]
        monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
        monkeypatch.setenv("EXTRACT_ANCHORS", "0")
        monkeypatch.setattr(runner, "ATTACH_IMAGES", False)
        monkeypatch.setattr(runner, "BATCH_SOURCES", runner.BATCH_SOURCES)
        monkeypatch.setattr(runner, "assert_serving", lambda *a, **k: 40960)
        monkeypatch.setattr(runner, "set_model_len", lambda n: None)
        monkeypatch.setattr(runner, "start_limit", lambda: None)
        monkeypatch.setattr(runner, "watch_server", lambda *a, **k: None)
        monkeypatch.setattr(runner, "install_stop_handler", lambda: None)
        monkeypatch.setattr(runner, "prime_probe_cache", lambda *a, **k: 0)
        monkeypatch.setattr(runner, "make_more_sources",
                            lambda *a, **k: (lambda *x: []))
        monkeypatch.setattr(runner, "make_rest_of_document",
                            lambda *a, **k: None)
        monkeypatch.setattr(runner, "make_parents", lambda *a, **k: None)
        monkeypatch.setattr(runner, "make_structure",
                            lambda *a, **k: (lambda d: []))
        monkeypatch.setattr(faiss_store, "load_global_index",
                            lambda p: (None, {}))
        monkeypatch.setattr(runner, "fit_batch_sources", lambda *a, **k: 1)
        monkeypatch.setattr(runner, "LLM_PARALLEL", 1)

        def make_retrieve(conn, index, id_to_pos, cache_conn, fetch,
                          limit=0):
            def retrieve(probes, document_id, exclude, limit=None):
                self.requests.append(list(probes))
                return [Source("section", 10, PASSAGE,
                               {"document_id": document_id, "page": 1,
                                "title": "Scenarios"})]
            return retrieve

        def document_anchor(spec, context=None, client=None, prompt=None,
                            frame=None, document_id=None):
            self.anchored.append([p.uri for p in spec.parameters])
            return {p.uri: [f"anchor of {p.uri}"] for p in spec.parameters}

        def make_fieldwise(*a, **k):
            def harvest(batch, prior=None):
                offered = [p.uri for p in batch.spec.parameters]
                self.harvests.append(offered)
                for _ in range(self.lose[0]):
                    runner.UNSERVED.note(batch.document_id)
                if offered == ["study_funder"]:
                    claim = {"source": batch.label(0),
                             "parameter": "study_funder",
                             "value": "German Federal Ministry of Education "
                                      "and Research", "quote": FUNDER}
                else:
                    claim = {"source": batch.label(0),
                             "parameter": "scenario_label", "value": RUN,
                             "value_raw": "Current Policies",
                             "quote": "The Current Policies scenario (CurPol)"}
                return {"tuples": [claim], "status": "complete",
                        "need_more": []}
            return harvest

        monkeypatch.setattr(runner, "make_retrieve", make_retrieve)
        monkeypatch.setattr(runner, "document_anchor", document_anchor)
        monkeypatch.setattr(runner, "make_fieldwise_harvester",
                            make_fieldwise)

    def write_spec(self, *without):
        raw = copy.deepcopy(self.raw)
        raw["parameters"] = [p for p in raw["parameters"]
                             if p["uri"] not in without]
        self.spec_file.write_text(json.dumps(raw), encoding="utf-8")

    def main(self, *flags):
        try:
            return runner.main([str(self.db), "no.index", str(self.out),
                                "--image-root", str(self.tmp), "--document",
                                "1", "--spec", str(self.spec_file), *flags])
        finally:
            trace.close()

    def bytes(self):
        return ((self.out / "a.jsonl").read_bytes(),
                (self.out / "a.stamp.json").read_bytes())

    def forget(self):
        self.harvests.clear()
        self.requests.clear()
        self.anchored.clear()


@pytest.fixture
def column(monkeypatch, tmp_path):
    return Column(monkeypatch, tmp_path)


def test_a_new_parameter_is_appended_by_one_command_and_a_second_changes_nothing(
        column, caplog):
    """The whole command: a harvest of the spec without `study_funder`, then
    the spec with it. The plain run reports the document stale and names the
    pass; the pass appends one row after every stored line, stamps the
    parameter, writes its trace beside the harvest's and not over it, and a
    second run is not one request."""
    column.write_spec("study_funder")
    assert column.main() == 0
    first = (column.out / "a.jsonl").read_bytes()
    stored = first.decode("utf-8").split("\n")[:-1]
    harvest_trace = (column.out / "trace" / "a.trace.jsonl").read_bytes()
    column.write_spec()
    with caplog.at_level(logging.WARNING, logger=runner.log.name):
        assert column.main() == 0
    assert "--force-stale" in caplog.text
    assert "--top-up-parameters appends them" in caplog.text
    assert (column.out / "a.jsonl").read_bytes() == first, (
        "a plain run leaves a stale document alone")
    column.forget()
    assert column.main("--top-up-parameters") == 0
    now = (column.out / "a.jsonl").read_bytes().decode("utf-8").split(
        "\n")[:-1]
    kept = [line for line in stored
            if json.loads(line)["kind"] != "summary"]
    assert now[:len(kept)] == kept, "every stored line, as it was"
    added = [json.loads(line) for line in now[len(kept):]]
    assert [r["kind"] for r in added] == ["tuple", "parameter_state",
                                          "summary"]
    assert added[0]["parameter"] == "study_funder"
    assert added[0]["value"] == ("German Federal Ministry of Education and "
                                 "Research")
    assert added[1]["state"] == "read"
    assert added[2]["tuples"] == len([
        r for r in (json.loads(line) for line in now)
        if r["kind"] == "tuple"])
    stamp = json.loads((column.out / "a.stamp.json").read_text("utf-8"))
    assert "parameter/study_funder" in stamp
    assert stamp["producers"][-1]["parameters"] == ["study_funder"]
    assert stamp["question_text/study_funder"] == ["anchor of study_funder"]
    current = runner._stamp_current("x", "", load_spec(json.loads(
        column.spec_file.read_text("utf-8"))))
    assert runner.stale(column.out / "a.stamp.json", current) == []
    # The harvest's trace is the harvest's: the pass wrote its own.
    assert (column.out / "trace" / "a.trace.jsonl").read_bytes() == (
        harvest_trace)
    assert (column.out / "trace-topup" / "a.trace.jsonl").is_file()
    # Every request offered the one parameter, and every search was for it.
    assert column.harvests and all(
        offered == ["study_funder"] for offered in column.harvests)
    assert column.anchored and all(
        asked == ["study_funder"] for asked in column.anchored), (
        "the document is searched for the new parameter alone")
    sentences = {probe for probes in column.requests for probe in probes
                 if probe.startswith("anchor of ")}
    assert sentences == {"anchor of study_funder"}
    from docpipe import prompts
    templates = [line for line in prompts.load(
        runner.QUERIES_PROMPT_ID).text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")]
    funder = load_spec(column.raw).by_uri["study_funder"]
    others = [p for p in load_spec(column.raw).parameters
              if p.uri != "study_funder"]
    allowed = {"anchor of study_funder"} | set(
        runner.expand_queries(templates, funder))
    searched = {probe for probes in column.requests for probe in probes}
    assert searched and searched <= allowed, (
        "every probe of every search is the new parameter's")
    assert set(runner.expand_queries(templates, others[0])) - allowed, (
        "the others have probes of their own, so the check can fail")
    # Second run: nothing is asked and nothing moves.
    after = column.bytes()
    column.forget()
    assert column.main("--top-up-parameters") == 0
    assert column.bytes() == after
    assert column.harvests == [] and column.anchored == []


def test_a_pass_whose_server_did_not_serve_ends_the_run_non_zero_and_writes_nothing(
        column):
    """The exit code keeps its meaning: a document the server did not serve
    is a failure, and its file and its stamp are the bytes they were."""
    column.write_spec("study_funder")
    assert column.main() == 0
    before = column.bytes()
    column.write_spec()
    column.lose[0] = 1
    assert column.main("--top-up-parameters") == 1
    assert column.bytes() == before
    column.lose[0] = 0
    assert column.main("--top-up-parameters") == 0, "and the next run is whole"
    assert column.bytes() != before


def test_a_documents_lists_are_closed_per_call_on_whatever_thread_asks(column):
    """`document_spec_per_call`: the loop runs a document per thread and a
    SQLite connection belongs to the thread that opened it, so every call
    opens its own. Violating: one connection shared across the threads
    raises, and a document whose lists cannot be closed is None, never the
    run's own empty ones."""
    from concurrent.futures import ThreadPoolExecutor
    spec = load_spec(column.raw)
    seen, opened = [], []

    def axes(conn, document_id):
        opened.append(conn)
        # By name: the hook of a profile reads its rows so.
        seen.append(conn.execute("SELECT COUNT(*) AS n FROM Documents")
                    .fetchone()["n"])
        if document_id == 2:
            raise RuntimeError("no lists for this one")
        return {"scenario": {RUN: [RUN]}}

    closed = runner.document_spec_per_call(column.db, spec, axes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        got = list(pool.map(closed, [1, 1]))
    assert seen == [1, 1]
    # Nothing is open between two calls. Asked on this thread, so that what
    # raises is the closed database and not another thread's connection.
    closed(1)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[-1].execute("SELECT 1")
    for own in got:
        assert RUN in own.by_uri["scenario_type"].axes["scenario"].vocabulary
    assert closed(2) is None
    assert closed(None) is None
    assert runner.document_spec_per_call(column.db, spec, None)(5) is spec


def test_the_pass_is_not_combined_with_the_coordinate_pass(column, capsys):
    column.write_spec()
    with pytest.raises(SystemExit) as stopped:
        column.main("--top-up", "--top-up-parameters")
    assert stopped.value.code == 2
    assert "not combined" in capsys.readouterr().err
    # Violating: a refusal wider than the decision. `--top-up-key` is a flag
    # of the coordinate pass that every other run ignores, and this one does
    # too; the run goes on and has nothing to do.
    assert column.main("--top-up-key", "axis/x/y",
                       "--top-up-parameters") == 0


def test_a_document_nobody_harvested_is_left_to_the_harvest(column, caplog):
    column.write_spec()
    with caplog.at_level(logging.INFO, logger=runner.log.name):
        assert column.main("--top-up-parameters") == 0
    assert not (column.out / "a.jsonl").exists()
    assert "1 document(s) have no harvest file" in caplog.text
    assert column.harvests == []


def test_a_harvest_that_already_holds_every_parameter_is_not_touched(column):
    """The command over a document with nothing new: no request, and not a
    byte of the file or the stamp."""
    column.write_spec()
    assert column.main() == 0
    before = column.bytes()
    column.forget()
    assert column.main("--top-up-parameters") == 0
    assert column.bytes() == before
    assert column.harvests == [] and column.anchored == []


def test_the_run_wires_the_pass_after_the_harvest_loop_and_keeps_the_top_up_branch():
    """The pass is one assignment after the closure it replaces, so the stop,
    the dead-server cut and the exit code are the harvest's. The branch of the
    coordinate pass stays where it is, and the pass traces beside the
    harvest's own."""
    source = inspect.getsource(runner.main)
    assert source.index("def harvest_document(") < source.index(
        "harvest_document = parameter_pass")
    assert source.index("harvest_document = parameter_pass") < source.index(
        "harvest_documents(")
    opened = source[source.index("document_name = {did"):]
    opened = opened[:opened.index("prior_rows = ")]
    assert opened.index("if args.top_up_parameters:") < opened.index(
        "trace.open_trace(args.out / TOPUP_TRACE_DIR") < opened.index(
        "else:") < opened.index('trace.open_trace(args.out / "trace"'), (
        "the pass opens its own directory, before the first event")
    branch = source[source.index("if args.top_up:"):]
    branch = branch[:branch.index("topup.run(")]
    assert "trace.open_trace(args.out / TOPUP_TRACE_DIR" in branch
    assert source.count("if args.top_up:") == 1


# ---------------------------------------------------------------------------
# A profile with a frame
# ---------------------------------------------------------------------------

HEAT_QUOTE = "| Heizlast Wärmenetz | 12 | kW |"
HEAT_TEXT = "Tabelle 7: Status quo 2020.\n" + HEAT_QUOTE


class FrameColumn(Column):
    """The column over the kwp profile, whose frame of scenario and year is
    asked once per document. The stored harvest is written by hand and the
    pair its one row carries stands under an index of its own; the frame
    request, the rows request and the field requests are stubs, and the run's
    own harvester sits over them."""

    def __init__(self, monkeypatch, tmp_path):
        real = runner.make_fieldwise_harvester
        super().__init__(monkeypatch, tmp_path)
        monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
        monkeypatch.setattr(runner, "make_fieldwise_harvester", real)
        self.raw = json.loads((PROFILES / "kwp" / "extraction_spec.json")
                              .read_text(encoding="utf-8"))
        self.known: list = []       # the pairs each frame request was told of
        self.bases: list = []       # the base years each rows request carried
        claim = {"source": "Q1", "value": 12, "value_raw": "12",
                 "unit": "kW", "unit_raw": "kW", "quote": HEAT_QUOTE}

        def make_frame_asker(image_root=None, **kw):
            def ask(shown, slots, document_id, known, *rest):
                self.known.append([dict(pair) for pair in known])
                return {"pairs": [], "status": "complete", "need_more": []}
            return ask

        def make_retrieve(conn, index, id_to_pos, cache_conn, fetch, limit=0):
            def retrieve(probes, document_id, exclude, limit=None):
                self.requests.append(list(probes))
                return [Source("table", 3, HEAT_TEXT,
                               {"document_id": document_id, "page": 3,
                                "title": "Tabelle 7"})]
            return retrieve

        def make_harvester(*a, **kw):
            def find_rows(batch, prior=None):
                self.harvests.append([p.uri for p in batch.spec.parameters])
                self.bases.append(batch.bases)
                return {"tuples": [dict(claim)], "status": "complete",
                        "need_more": []}
            return find_rows

        def make_field_asker(image_root=None, **kw):
            def ask(shown, rows, slots, corrections=None, document_id=None,
                    usage_out=None, owner_of=None, bases=None):
                slots = slots if isinstance(slots, (list, tuple)) else [slots]
                return {"fields": {slot.name: {"answers": {
                    row.label: ({"value": "kW", "value_raw": "kW",
                                 "quote": HEAT_QUOTE}
                                if slot.name == "unit"
                                else {"value": "unstated"})
                    for row in rows}} for slot in slots}}
            return ask

        monkeypatch.setattr(runner, "make_frame_asker", make_frame_asker)
        monkeypatch.setattr(runner, "make_retrieve", make_retrieve)
        monkeypatch.setattr(runner, "make_harvester", make_harvester)
        monkeypatch.setattr(runner, "make_field_asker", make_field_asker)

    def store(self, **stamp):
        """The harvest of the spec without `heat_load` that a first run left:
        one tuple of `energy_consumption`, read under the pair (Status quo,
        2020) that stands at index 5 because no row carries 0 to 4."""
        raw = copy.deepcopy(self.raw)
        raw["parameters"] = [p for p in raw["parameters"]
                             if p["uri"] != "heat_load"]
        old = load_spec(raw)
        row = {"kind": "tuple", "parameter": "energy_consumption",
               "value": 17.0, "unit": "MWh/a",
               "quote": "| Erdgas | 17 | MWh/a |",
               "scenario": "status_quo", "scenario_raw": "Status quo",
               "scenario_quote": "Status quo 2020",
               "scenario_source": ["table", 3],
               "scenario_window": ["frame", 5],
               "year": 2020, "year_raw": "2020",
               "year_quote": "Status quo 2020", "year_source": ["table", 3],
               "year_window": ["frame", 5],
               "provenance": {"document_id": 1, "owner_kind": "table",
                              "owner_id": 3}}
        states = [{"kind": "parameter_state", "document_id": 1,
                   "parameter": p.uri,
                   "state": "read" if p.uri == "energy_consumption"
                   else "unstated",
                   "tuples": int(p.uri == "energy_consumption"),
                   "refusals": 0} for p in old.parameters]
        summary = {"kind": "summary", "document_id": 1, "tuples": 1,
                   "refusals": 0, "levels": {"A": 0, "B": 1, "C": 0},
                   "reasons": {}, "image_origin": 0}
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "a.jsonl").write_bytes(("\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in (row, *states, summary)) + "\n").encode("utf-8"))
        (self.out / "a.stamp.json").write_text(json.dumps({
            **runner._stamp_current("old-sha", "", old),
            "producers": [{"pass": "harvest", "model": "first"}], **stamp}),
            encoding="utf-8")


@pytest.fixture
def frame_column(monkeypatch, tmp_path):
    return FrameColumn(monkeypatch, tmp_path)


def test_the_pairs_a_stored_harvest_carries_reach_the_plan_through_the_command(
        frame_column, caplog):
    """The run wires the frame of its profile into the pass: the pair the
    stored row carries is what the frame request is told of, and the row
    appended for the new parameter says `frame` and 5, the index the pair
    stands under in the file. Violating: a run that handed the pass no frame
    asks the frame from nothing and numbers its pair from 0, and a row with
    no pair at all. The run ends with what the pass counted."""
    column = frame_column
    column.store()
    column.write_spec()
    with caplog.at_level(logging.INFO, logger="docpipe.extraction"):
        assert column.main("--top-up-parameters") == 0
    assert "documents appended (documents)" in caplog.text
    assert [[pair["year"] for pair in known] for known in column.known] == [
        [2020]], "the frame request is told of the stored pair, as known"
    rows = [json.loads(line) for line in
            (column.out / "a.jsonl").read_text("utf-8").splitlines()]
    row = next(r for r in rows if r["kind"] == "tuple"
               and r["parameter"] == "heat_load")
    assert row["scenario_window"] == ["frame", 5]
    assert row["year_window"] == ["frame", 5] and row["year"] == 2020
    assert column.harvests and all(
        offered == ["heat_load"] for offered in column.harvests)
    assert column.bases and all(
        [(b["year"], b["index"]) for b in bases] == [(2020, 5)]
        for bases in column.bases), (
        "the base year of the stored pair, under the index it is stored at")
    current = runner._stamp_current("x", "", load_spec(column.raw))
    assert runner.stale(column.out / "a.stamp.json", current) == []


def test_a_moved_frame_coordinate_leaves_the_document_stale_through_the_command(
        frame_column):
    """The run names the frame coordinates to the pass, so a moved one blocks
    the document as it blocks the coordinate pass: the pair decides how many
    requests a document gets, and rows read under a moved question are not
    rows to append to. Violating: a pass told of no frame coordinate sees a
    sweepable key, takes the document and asks the frame."""
    column = frame_column
    column.store(**{"axis/energy_consumption/year": "an older question"})
    column.write_spec()
    before = column.bytes()
    assert column.main("--top-up-parameters") == 0
    assert column.bytes() == before
    assert column.known == [] and column.harvests == []
    assert column.requests == []


def test_the_harvest_and_the_pass_plan_and_harvest_a_document_through_one_binding():
    """The plan with the run's frame and the batches in the shared pools, the
    stop and the dead-server cut are bound once in `main`, and the harvest and
    the pass both call that binding. Violating: a second binding of either is
    a second place to wire a pool, a frame or a cut another way, and a pass
    wired so would end a run on a dead server only after every document had
    spent its retries."""
    source = inspect.getsource(runner.main)
    code = "\n".join(line.split("#")[0] for line in source.splitlines())
    assert code.count("plan_batches") == 1
    assert code.count("harvest_batches") == 1
    assert code.count("plan_for") == 3, (
        "bound, called by the harvest, handed to the pass")
    assert code.count("harvest_all") == 3
