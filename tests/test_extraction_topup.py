"""Re-reading one coordinate instead of one document.

The pass exists because a reworded question makes 1.082 documents stale and
the resume can only answer that by harvesting them again. What is held here is
mostly the refusals: a stamp key that decided which rows exist, or which model
read them, is not a coordinate, and a file half from one run and half from
another with a stamp saying it is all one is worse than a stale file.

The other half is the safety net. No coordinate of either profile is required,
so a re-sweep that answers nothing would pass verification in silence and the
old reading would be gone with nothing saying so.

No model, no GPU, no index: the sweeper and the source fetcher are stubs.
"""
import json
from pathlib import Path

from docpipe.extraction import fields, runner, topup
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
PARAMETER = "energy_consumption"
QUOTE = "| Erdgas | 241 | MWh/a |"
TEXT = "Tabelle 4: Endenergieverbrauch 2020. " + QUOTE + " | Nahwaerme | 12 |"


def _spec(name="kwp"):
    return load_spec(json.loads(
        (PROFILES / name / "extraction_spec.json").read_text(encoding="utf-8")))


SPEC = _spec()


def _slot(name, spec=SPEC, parameter=PARAMETER):
    return next(s for s in fields.axis_slots(spec.by_uri[parameter])
                if s.name == name)


def _row(**overrides):
    row = {
        "kind": "tuple", "parameter": PARAMETER, "value": 241.0,
        "value_target": 241.0, "unit": "MWh/a", "unit_raw": "MWh/a",
        "quote": QUOTE, "tier": "text_located",
        "parameter_state": fields.READ,
        "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
        "quantity_state": fields.READ, "quantity_source": ["table", 1],
        "quantity_quote": TEXT,
        "aggregation": "OEO_00140070", "aggregation_state": fields.DERIVED,
        "scenario": "target", "scenario_raw": "Zielszenario",
        "scenario_state": fields.READ, "scenario_source": ["table", 1],
        "scenario_quote": TEXT,
        "spatial_scope": "municipality", "spatial_scope_raw": "Stadtgebiet",
        "spatial_scope_state": fields.READ,
        "spatial_scope_source": ["table", 1], "spatial_scope_quote": TEXT,
        "carrier": "OEO_00000292", "carrier_raw": "Erdgas",
        "carrier_state": fields.READ, "carrier_source": ["table", 1],
        "carrier_quote": QUOTE, "carrier_window": ["own", 1],
        "sector": "OEO_00000405", "sector_raw": "Gewerbe",
        "sector_state": fields.READ, "sector_source": ["table", 1],
        "sector_quote": QUOTE,
        "year": 2020, "year_state": fields.READ, "year_source": ["table", 1],
        "year_quote": TEXT,
        "provenance": {"document_id": 7, "owner_kind": "table",
                       "owner_id": 1, "parent_section": 5, "page": 85,
                       "rects": [[1, 2, 3, 4]], "image": "p85_tbl0.png"},
    }
    row.update(overrides)
    return row


def _summary(**overrides):
    line = {"kind": "summary", "document_id": 7, "tuples": 1, "refusals": 0,
            "levels": {"A": 1, "B": 0, "C": 0}, "reasons": {},
            "image_origin": 0}
    line.update(overrides)
    return line


def _sources(text=TEXT):
    def owner_sources(owners):
        out = {}
        for kind, owner in owners:
            out[(kind, owner)] = Source(
                kind, owner, text,
                {"document_id": 7, "page": 85, "parent_section": 5,
                 "block_id": "p85_tbl0"})
        return out
    return owner_sources


def _sweeper(answers=None, calls=None):
    """A sweep that writes what `answers` says onto every row it is given."""
    def sweep(batch, rows, slots, anchor_id=""):
        if calls is not None:
            calls.append({"batch": batch, "rows": rows, "slots": slots,
                          "anchor": anchor_id})
        for slot in slots:
            given = (answers or {}).get(slot.name)
            if given is None:
                continue
            for row in rows:
                row.claim[slot.name] = given["value"]
                row.claim[f"{slot.name}_state"] = given.get("state",
                                                            fields.READ)
                row.claim[f"{slot.name}_raw"] = given.get("raw",
                                                          given["value"])
                row.claim[f"{slot.name}_quote"] = given.get("quote", QUOTE)
                row.claim[f"{slot.name}_source"] = given.get("source",
                                                             ["table", 1])
                row.claim[f"{slot.name}_window"] = ["own", 1]
        return {}
    return sweep


def _deps(**overrides):
    deps = {"sweep": _sweeper(), "owner_sources": _sources(),
            "document_spec": lambda did: SPEC, "frame_names": (),
            "dynamic_ok": True, "locate": None}
    deps.update(overrides)
    return deps


def _harvest(tmp_path, rows, stamp=None, name="plan"):
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    if stamp is not None:
        (tmp_path / f"{name}.stamp.json").write_text(
            json.dumps(stamp), encoding="utf-8")
    return path


def _stamp(**overrides):
    from docpipe.extraction.spec import fingerprints
    stamp = {"spec": "spec-sha", "model": "m", "anchors": "a",
             "extraction/harvest": "h", "extraction/queries": "q",
             "extraction/anchors": "an", "extraction/rows": "r",
             "extraction/field": "f", **fingerprints(SPEC)}
    stamp.update(overrides)
    return stamp


def _rows(path):
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").strip().splitlines()]


# ---------------------------------------------------------------------------
# Which keys
# ---------------------------------------------------------------------------
def test_only_a_coordinate_key_is_topped_up_and_the_rest_blocks():
    """A key that decided which rows exist, which passages were planned or
    which model read them is not a coordinate. Swept anyway, the file is half
    one run and half another and the stamp says it is all one."""
    changed = [f"axis/{PARAMETER}/sector", f"parameter/{PARAMETER}",
               f"value/{PARAMETER}", "slot/parameter", "model", "anchors",
               "extraction/rows"]
    keys, blocked = topup.actionable(changed, SPEC)
    assert keys == [f"axis/{PARAMETER}/sector"]
    assert blocked == sorted(k for k in changed if not k.startswith("axis/"))


def test_a_frame_coordinate_is_never_a_top_up():
    """The frame decides how many passes the document gets, so a moved frame
    coordinate can mean pairs, and therefore rows, this file does not have."""
    keys, blocked = topup.actionable([f"axis/{PARAMETER}/year"], SPEC,
                                     ("scenario", "year"))
    assert keys == [] and blocked == [f"axis/{PARAMETER}/year"]
    # And without the profile naming it, the same key is ordinary.
    keys, blocked = topup.actionable([f"axis/{PARAMETER}/year"], SPEC)
    assert keys == [f"axis/{PARAMETER}/year"] and blocked == []


def test_a_dynamic_axis_needs_this_documents_own_list():
    """Swept against an empty list a dynamic axis degrades to a wording, and a
    wording written where a class stood is a demotion nothing reports."""
    other = _spec("scenarios")
    dynamic = next(
        (p.uri, name) for p in other.parameters
        for name, axis in (p.axes or {}).items() if axis.dynamic)
    key = f"axis/{dynamic[0]}/{dynamic[1]}"
    assert topup.actionable([key], other, dynamic_ok=True)[0] == [key]
    assert topup.actionable([key], other, dynamic_ok=False) == ([], [key])


def test_a_named_key_is_the_only_one_swept():
    """Two questions moved and only one is being answered: claiming the other
    would say a coordinate was re-read that nobody read."""
    changed = [f"axis/{PARAMETER}/sector", f"axis/{PARAMETER}/carrier"]
    keys, blocked = topup.actionable(changed, SPEC,
                                     only=[f"axis/{PARAMETER}/sector"])
    assert keys == [f"axis/{PARAMETER}/sector"] and blocked == []


def test_a_stale_model_or_prompt_stops_the_document_before_a_request(tmp_path):
    """Not one token spent, and the file untouched: what is stale is not
    something a coordinate sweep can answer."""
    path = _harvest(tmp_path, [_row(), _summary()], stamp=_stamp(model="alt"))
    before = path.read_bytes()
    stamp_before = (tmp_path / "plan.stamp.json").read_bytes()
    calls = []
    stats = topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(calls=calls)))
    assert calls == []
    assert stats["blocked"] == 1
    assert path.read_bytes() == before
    assert (tmp_path / "plan.stamp.json").read_bytes() == stamp_before


def test_nothing_is_asked_and_nothing_is_written_when_the_stamp_is_current(
        tmp_path):
    path = _harvest(tmp_path, [_row(), _summary()], stamp=_stamp())
    before = path.read_bytes()
    calls = []
    stats = topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(calls=calls)))
    assert calls == [] and stats["already current"] == 1
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# Re-opening
# ---------------------------------------------------------------------------
def test_a_read_coordinate_is_reopened_before_the_sweep_sees_it():
    """`merge_field` refuses to overwrite a coordinate that is already read,
    and that rule is not this pass's to soften: the coordinate comes off the
    claim instead, so the state is simply absent."""
    from docpipe.extraction.pipeline import Row, merge_field, open_rows
    slot = _slot("sector")
    row = Row("R1", 0, _row())
    assert open_rows([row], slot) == [], "read, so nothing to ask"
    taken = topup.reopen(row.claim, slot)
    assert open_rows([row], slot) == [row]
    assert taken["sector"] == "OEO_00000405"
    shown = [Source("table", 1, TEXT, {"document_id": 7, "page": 85})]
    merge_field([row], shown, slot,
                {"answers": {"R1": {"value": "Haushalte", "quote": QUOTE}}},
                window=("own", 1))
    assert row.claim.get("sector_state") in (fields.READ, fields.UNBACKED)


def test_reopening_leaves_every_other_coordinate_alone():
    """Cleared by prefix, `sector` would take `sector_source` and nothing
    else -- and `year` would take `year_quote` from a row that shares the
    string. Eight named keys, one coordinate."""
    row = _row()
    before = {k: v for k, v in row.items() if not k.startswith("sector")}
    topup.reopen(row, _slot("sector"))
    assert not [k for k in row if k.startswith("sector")]
    assert {k: v for k, v in row.items()} == before


def test_a_coordinate_the_re_sweep_cannot_read_keeps_its_old_reading(tmp_path):
    """No axis of either profile is required, so an emptied one passes
    verification and the reading is simply gone. The old block goes back."""
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    before = _rows(path)[0]
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper()))
    after = _rows(path)[0]
    for key in ("sector", "sector_raw", "sector_state", "sector_quote",
                "sector_source"):
        assert after[key] == before[key], key
    # And the key is not written forward: the question is still unanswered.
    assert runner.stale(tmp_path / "plan.stamp.json",
                        _stamp()) == [f"axis/{PARAMETER}/sector"]


def test_a_coordinate_the_re_sweep_reads_is_written_and_the_key_settled(
        tmp_path):
    """The whole point, and the only case where the stamp may move."""
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    after = _rows(path)[0]
    assert after["sector_raw"] == "Haushalte"
    assert runner.stale(tmp_path / "plan.stamp.json", _stamp()) == []


def test_a_swept_coordinate_is_a_uri_not_the_label_the_model_answered(
        tmp_path):
    """The sweep writes the option label; the harvest carries classes. Written
    straight through, every re-read row would carry a German word where a URI
    stands and the graph would mint nothing for it."""
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    after = _rows(path)[0]
    assert after["sector"].startswith("OEO_"), after["sector"]
    assert after["sector_raw"] == "Haushalte"


def test_every_coordinate_still_ends_with_a_state(tmp_path):
    """The schema requires a state on every coordinate of every row.

    The case that decides it is a spec that GAINED this axis: the stored rows
    carry nothing for it, so there is no old block to put back, and a sweep
    that answers nothing would leave the coordinate simply absent."""
    fresh = _row()
    for key in ("sector", "sector_raw", "sector_state", "sector_quote",
                "sector_source"):
        fresh.pop(key, None)
    path = _harvest(tmp_path, [fresh, _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper()))
    after = _rows(path)[0]
    for slot in fields.asked_slots(SPEC.by_uri[PARAMETER]):
        assert f"{slot.name}_state" in after, slot.name
    assert after["sector_state"] == fields.UNANSWERED


def test_the_provenance_keeps_its_rects_when_no_pdf_is_configured(tmp_path):
    """The rectangles a reader highlights come from a locator that only
    exists when a PDF root does. Rebuilt from the source alone, every
    highlight in the corpus is gone after one top-up."""
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    provenance = _rows(path)[0]["provenance"]
    assert provenance["rects"] == [[1, 2, 3, 4]]
    assert provenance["image"] == "p85_tbl0.png"


def test_a_row_whose_source_no_longer_carries_its_quote_is_left_alone(
        tmp_path):
    """The database was rebuilt under the harvest and the owner id now names
    another passage. Nothing about that row can be re-read against it."""
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    before = _rows(path)[0]
    stats = topup.run(tmp_path, SPEC, _stamp(),
                      _deps(owner_sources=_sources("Ein ganz anderer Text."),
                            sweep=_sweeper({"sector": {"value": "Haushalte"}})))
    assert stats["source moved"] == 1
    assert _rows(path)[0] == before
    assert runner.stale(tmp_path / "plan.stamp.json",
                        _stamp()) == [f"axis/{PARAMETER}/sector"]


def test_the_passage_a_coordinate_was_read_in_is_shown_again(tmp_path):
    """The sweep can only offer a passage that is in the batch, and the one a
    coordinate was last read in is the one that already carried its answer."""
    row = _row(sector_source=["section", 5])
    _harvest(tmp_path, [row, _summary()],
             stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    calls = []
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(calls=calls)))
    assert calls, "the sweep never ran"
    owners = {(s.owner_kind, s.owner_id) for s in calls[0]["batch"].sources}
    assert ("table", 1) in owners and ("section", 5) in owners


def test_a_row_the_re_verification_refuses_keeps_the_reading_it_had(tmp_path):
    """A required coordinate emptied is a refusal, and a refused row is not a
    row to write: it keeps what it had and its key stays stale."""
    spec = _spec()
    parameter = spec.by_uri[PARAMETER]
    axis = parameter.axes["sector"]
    object.__setattr__(axis, "required", True)
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    before = _rows(path)[0]
    stats = topup.run(tmp_path, spec, _stamp(), _deps(
        document_spec=lambda did: spec,
        sweep=_sweeper({"sector": {"value": "Ein Wort aus keiner Liste",
                                   "raw": "Ein Wort aus keiner Liste",
                                   "quote": QUOTE}})))
    assert stats["re-verification refused"] == 1
    assert _rows(path)[0] == before


def test_the_summary_is_recomputed_from_the_coordinates_that_moved(tmp_path):
    """This pass changes what the tuples say and the summary counts them."""
    path = _harvest(tmp_path, [_row(), _summary(levels={"A": 0, "B": 0,
                                                        "C": 1},
                                                reasons={"conflict": 1})],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    rows = _rows(path)
    assert rows[-1]["kind"] == "summary"
    assert rows[-1]["reasons"] == {}, "recomputed, not carried"


def test_a_row_it_could_not_settle_keeps_that_axis_stale(tmp_path):
    """One unsettled row unsettles the key for the whole document: a stamp is
    per document, and half an answer is not one."""
    good, bad = _row(), _row(quote="| Nahwaerme | 12 |", value=12.0,
                             value_target=12.0)
    path = _harvest(tmp_path, [good, bad, _summary(tuples=2)],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))

    def sweep(batch, rows, slots, anchor_id=""):
        # Answers the first row and leaves the second open.
        for slot in slots:
            row = rows[0]
            row.claim[slot.name] = "Haushalte"
            row.claim[f"{slot.name}_state"] = fields.READ
            row.claim[f"{slot.name}_raw"] = "Haushalte"
            row.claim[f"{slot.name}_quote"] = QUOTE
            row.claim[f"{slot.name}_source"] = ["table", 1]
        return {}

    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=sweep))
    assert runner.stale(tmp_path / "plan.stamp.json",
                        _stamp()) == [f"axis/{PARAMETER}/sector"]
    assert len(_rows(path)) == 3


def test_a_derived_coordinate_is_written_without_a_request(tmp_path):
    """The spec decides it from the unit, so asking would be asking a question
    the run never asks -- and the reopen is what makes it write at all."""
    parameter = SPEC.by_uri[PARAMETER]
    derived = next(s for s in fields.axis_slots(parameter) if s.derive)
    row = _row(**{derived.name: "OEO_00000000",
                  f"{derived.name}_state": fields.DERIVED})
    path = _harvest(tmp_path, [row, _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/{derived.name}": "x"}))
    calls = []
    stats = topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(calls=calls)))
    assert calls == [], "a derived coordinate costs no request"
    assert stats["derived"] == 1
    after = _rows(path)[0]
    assert after[derived.name] == derived.derive["value"]
    assert after[f"{derived.name}_state"] == fields.DERIVED


def test_the_gate_reopens_the_axes_it_had_closed(tmp_path):
    """A row the slice gate closed was never asked its other coordinates. If
    the gate reads differently now, those questions were never put."""
    gate = {"quantity": None}
    closed = _row(sector_state=fields.OUT_OF_SLICE)
    for key in ("sector", "sector_raw", "sector_quote", "sector_source"):
        closed.pop(key, None)
    path = _harvest(tmp_path, [closed, _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/quantity": "moved"}))
    calls = []
    topup.run(tmp_path, SPEC, _stamp(), _deps(
        slice_gate=gate,
        sweep=_sweeper({"quantity": {"value": "OEO_00050016"},
                        "sector": {"value": "Haushalte", "raw": "Haushalte"}},
                       calls)))
    assert [c["slots"][0].name for c in calls] == ["quantity", "sector"]
    assert _rows(path)[0]["sector_raw"] == "Haushalte"


def test_nothing_new_reaches_the_file(tmp_path):
    """The published tuple branch is closed. A key this pass invents is a row
    nobody downstream can read, and it would be in every re-read row."""
    import jsonschema
    schema = json.loads((PROFILES / "kwp" / "extraction_schema.json")
                        .read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        {"$schema": schema["harvest"]["$schema"],
         "$defs": schema["harvest"]["$defs"],
         **schema["harvest"]["$defs"][f"tuple_{PARAMETER}"]})
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    row = _rows(path)[0]
    errors = list(validator.iter_errors(row))
    assert not errors, [e.message for e in errors]


def test_the_top_up_leaves_the_trace_files_alone(tmp_path):
    """A trace is not a harvest, and reading one as a harvest rewrites it."""
    _harvest(tmp_path, [_row(), _summary()],
             stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    trace_path = tmp_path / "plan.trace.jsonl"
    trace_path.write_text('{"t": "rows", "ms": 10}', encoding="utf-8")
    before = trace_path.read_bytes()
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper()))
    assert trace_path.read_bytes() == before


def test_the_top_up_writes_its_trace_beside_the_harvests_and_not_over_it(
        tmp_path, monkeypatch):
    """`trace._handle` opens "w", so a top-up tracing into the harvest's own
    `trace/` would truncate the file that says what the harvest cost. Its
    events land under `trace-topup/` and the original survives byte for
    byte -- and the runner's `--top-up` branch opens exactly that directory.
    """
    import inspect
    from docpipe.extraction import trace
    monkeypatch.setattr(trace, "ENABLED", True)
    # `close` closes the files and leaves the root; put both back afterwards.
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_name_of", None)
    harvest_trace = tmp_path / "trace" / "plan.trace.jsonl"
    harvest_trace.parent.mkdir()
    harvest_trace.write_text('{"t": "rows", "doc": 7, "ms": 10}',
                             encoding="utf-8")
    before = harvest_trace.read_bytes()
    trace.open_trace(tmp_path / runner.TOPUP_TRACE_DIR, {7: "plan"}.get)
    try:
        trace.event("sweep", 7, field="sector", stage="own")
        trace.flush()
    finally:
        trace.close()
    assert harvest_trace.read_bytes() == before
    written = (tmp_path / "trace-topup" / "plan.trace.jsonl").read_text(
        encoding="utf-8")
    assert json.loads(written)["t"] == "sweep"
    branch = inspect.getsource(runner.main)
    branch = branch[branch.index("if args.top_up:"):]
    branch = branch[:branch.index("topup.run(")]
    assert "trace.open_trace(args.out / TOPUP_TRACE_DIR" in branch
    assert runner.TOPUP_TRACE_DIR == "trace-topup"


def test_the_file_sha_moves_only_when_nothing_else_is_stale(tmp_path):
    """The whole-file sha is a coarse mirror of the keys under it, and moved
    early it makes a document read current with a changed prompt unaddressed.
    """
    stale_prompt = _stamp(**{f"axis/{PARAMETER}/sector": "moved",
                             "spec": "old", "extraction/rows": "old"})
    _harvest(tmp_path, [_row(), _summary()], stamp=stale_prompt)
    topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    stored = json.loads((tmp_path / "plan.stamp.json").read_text(
        encoding="utf-8"))
    assert stored["spec"] == "old", "another key is still stale"


# `test_the_sweeper_is_the_one_the_harvest_uses` lives in
# tests/test_extraction_fieldwise.py: the fieldwise suite is the guard against
# this module growing a second copy of sweep_field.

def test_the_key_names_one_coordinate_of_one_parameter():
    """`slot_of` is what turns a stamp key back into a question. A key the
    spec no longer has resolves to nothing and blocks the document, because
    the run cannot ask what it no longer knows."""
    got = topup.slot_of(SPEC, f"axis/{PARAMETER}/sector")
    assert got is not None
    parameter, slot = got
    assert parameter.uri == PARAMETER and slot.name == "sector"
    assert topup.slot_of(SPEC, f"axis/{PARAMETER}/gibt_es_nicht") is None
    assert topup.slot_of(SPEC, "axis/kein_parameter/sector") is None
    assert topup.slot_of(SPEC, f"value/{PARAMETER}") is None


def test_the_old_reading_comes_back_unless_the_new_state_is_better():
    """`restore` is the whole safety net, and its rule is asymmetric: a
    reading is only replaced by a reading, while a coordinate that was never
    read is bettered by any answer -- "the passages do not say it" included,
    because that is an answer. Running out of budget is not."""
    slot = _slot("sector")
    row = _row()
    taken = topup.reopen(row, slot)

    row["sector_state"] = fields.READ
    assert topup.restore(row, slot, taken, keep=topup.KEEP_READ) is False
    row["sector_state"] = fields.SAID_UNSTATED
    assert topup.restore(row, slot, taken, keep=topup.KEEP_READ) is True
    assert row["sector"] == "OEO_00000405", "the old reading is back"

    topup.reopen(row, slot)
    row["sector_state"] = fields.SAID_UNSTATED
    assert topup.restore(row, slot, taken, keep=topup.KEEP_ASKED) is False
    row["sector_state"] = fields.EXHAUSTED
    assert topup.restore(row, slot, taken, keep=topup.KEEP_ASKED) is True


def test_the_passages_a_row_names_are_its_own_and_the_ones_it_was_read_in():
    """`owners_of` decides what the re-sweep may show. Its own passage alone
    and the coordinate is looked for everywhere except where it was last
    found, which is the failure the re-entry rule exists to end."""
    row = _row(sector_source=["section", 5])
    got = topup.owners_of(row, [_slot("sector")])
    assert got == [("table", 1), ("section", 5)]
    # A coordinate read in its own passage adds nothing, and a row that never
    # recorded one names only itself.
    assert topup.owners_of(_row(), [_slot("sector")]) == [("table", 1)]
    bare = _row()
    bare.pop("sector_source")
    assert topup.owners_of(bare, [_slot("sector")]) == [("table", 1)]


def test_the_gate_releases_only_the_rows_it_now_keeps(tmp_path):
    """`reopened_by_gate` decides which closed rows get their questions put.
    A row the gate still keeps out is untouched: it is not in the slice this
    run serializes and asking it anything spends a request for nothing."""
    gate = {"quantity": None}
    staying = _row(sector_state=fields.OUT_OF_SLICE)
    leaving = _row(quantity="out:potential", quantity_raw="Potenzial",
                   sector_state=fields.OUT_OF_SLICE)
    got = topup.reopened_by_gate([staying, leaving], SPEC, gate)
    assert [(p.uri, s.name, len(rows)) for p, s, rows in got] == [
        (PARAMETER, "sector", 1)]
    assert got[0][2] == [staying]
    # And with no gate configured there is nothing to release.
    assert topup.reopened_by_gate([staying, leaving], SPEC, {}) == []


def test_one_file_is_read_rewritten_and_stamped_in_one_place(tmp_path):
    """`top_up_file` is the unit: one document, one stamp, one rewrite. A
    document whose stamp holds nothing sweepable comes back untouched, and
    that is not the same as one that had nothing stale at all."""
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{f"axis/{PARAMETER}/sector": "moved"}))
    stats = topup.top_up_file(path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    assert stats["rows"] == 1 and stats["stamps carried forward"] == 1
    assert stats["already current"] == 0

    again = topup.top_up_file(path, SPEC, _stamp(), _deps())
    assert again["already current"] == 1 and again["rows"] == 0

def test_the_passages_a_harvest_named_are_fetched_back_the_way_it_read_them(
        tmp_path):
    """`make_owner_sources` rebuilds a Source from the address a harvest
    stored. Through the same two functions the harvest used, or the heading is
    not prefixed the same way and a quote that was checkable during the
    harvest stops being checkable one pass later."""
    import sqlite3
    path = tmp_path / "plans.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE Sections ("
        " id INTEGER PRIMARY KEY, document INTEGER, section_number INTEGER,"
        " title TEXT, content TEXT, page_number INTEGER);"
        "CREATE TABLE Tables ("
        " id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,"
        " caption TEXT, markdown TEXT, page_number INTEGER, path TEXT);"
        "CREATE TABLE Images ("
        " id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,"
        " caption TEXT, description TEXT, page_number INTEGER, path TEXT);")
    conn.execute("INSERT INTO Documents (id, filename) VALUES (7, 'plan.pdf')")
    conn.execute("INSERT INTO Sections (id, document, section_number, title, "
                 "content, page_number) VALUES (5, 7, 4, 'Verbrauch', ?, 85)",
                 ("Der Abschnitt zum Verbrauch.",))
    conn.execute("INSERT INTO Tables (id, section, block_id, caption, "
                 "markdown, page_number, path) VALUES "
                 "(1, 5, 'p85_tbl0', 'Tabelle 4: Endenergieverbrauch 2020', "
                 "?, 85, NULL)",
                 ("| Erdgas | 241 | MWh/a |",))
    conn.commit()
    conn.close()

    got = runner.make_owner_sources(path)([("table", 1), ("section", 5)])
    assert sorted(got) == [("section", 5), ("table", 1)]
    table = got[("table", 1)]
    # The caption joins the text the quote is checked against: a unit or a
    # year printed only there was shown to the model and must stay quotable.
    assert "Tabelle 4" in table.text and "| Erdgas | 241 | MWh/a |" in table.text
    assert table.provenance["parent_section"] == 5
    # An owner that is not there is left out rather than faked.
    assert runner.make_owner_sources(path)([("table", 999)]) == {}

def test_a_stale_document_is_not_filtered_away_before_the_pass_runs(
        tmp_path, monkeypatch):
    """The harvest skips a document its stamp calls current and re-reads the
    rest. A top-up wants exactly the rest, so the same filter would hand it an
    empty list and the flag would be a no-op that logs "nothing to harvest"."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    _harvest(tmp_path, [_row(), _summary()], name="fresh")
    _harvest(tmp_path, [_row(), _summary()], name="stale",
             stamp=_stamp(model="alt"))
    _harvest(tmp_path, [_row(), _summary()], name="neu")
    current = runner._stamp_current("sha", "anchors", SPEC)
    (tmp_path / "fresh.stamp.json").write_text(json.dumps(current),
                                               encoding="utf-8")
    documents = [(1, "fresh.pdf"), (2, "stale.pdf"), (3, "neu.pdf")]

    harvesting = runner.documents_to_harvest(
        documents, tmp_path, "sha", anchors_sha="anchors", spec=SPEC)
    # The current one is skipped and so is the stale one: without
    # --force-stale a moved stamp is a warning, not a re-harvest. Only the
    # document with no stamp at all is work for a harvest.
    assert harvesting == [(3, "neu.pdf")]

    topping_up = runner.documents_to_harvest(
        documents, tmp_path, "sha", anchors_sha="anchors", spec=SPEC,
        top_up=True)
    assert topping_up == documents, "a top-up decides per key, not per stamp"


# ---------------------------------------------------------------------------
# The field prompt as a named key (WP12e)
# ---------------------------------------------------------------------------

def test_the_field_prompt_is_swept_only_when_named():
    """The field prompt is the only prompt the sweep uses, so a document whose
    stamp says it moved CAN be re-read coordinate by coordinate. But that is
    every asked coordinate of every row, a corpus-sized decision, so the key
    blocks unless --top-up-key names it."""
    assert topup.FIELD_PROMPT == runner.FIELD_PROMPT_ID
    key = topup.FIELD_PROMPT
    assert topup.actionable([key], SPEC) == ([], [key])
    assert topup.actionable([key], SPEC, only=[key]) == ([key], [])
    # Named together with a coordinate key, both are swept and nothing blocks.
    axis = f"axis/{PARAMETER}/sector"
    assert topup.actionable([key, axis], SPEC, only=[key, axis]) \
        == ([axis, key], [])
    # And named alone while a coordinate also moved, the coordinate is left
    # for another pass rather than claimed.
    assert topup.actionable([key, axis], SPEC, only=[key]) == ([key], [])


def test_a_named_field_prompt_re_reads_every_asked_coordinate(tmp_path):
    """Every asked, unframed coordinate of every row goes through the sweep
    once; a derived one does not (no request ever read it). The key is
    carried forward only when every one of them settled."""
    parameter = SPEC.by_uri[PARAMETER]
    asked = sorted(s.name for s in fields.asked_slots(parameter)
                   if s.name != "year")
    assert "aggregation" not in asked, "derived, so never asked"
    calls = []
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=_stamp(**{topup.FIELD_PROMPT: "moved"}))
    stats = topup.top_up_file(
        path, SPEC, _stamp(),
        _deps(sweep=_sweeper(calls=calls), frame_names=("year",)),
        only=[topup.FIELD_PROMPT])
    swept = sorted(slot.name for call in calls for slot in call["slots"])
    assert swept == asked
    # A sweep that answered nothing put every old block back, so the key is
    # not the pass's to write forward.
    stored = json.loads((tmp_path / "plan.stamp.json").read_text(
        encoding="utf-8"))
    assert stored[topup.FIELD_PROMPT] == "moved"
    assert stats["stamps carried forward"] == 0

    row = _row()
    answers = {name: {"value": row[name], "raw": row.get(f"{name}_raw",
                                                          row[name])}
               for name in asked}
    stats = topup.top_up_file(
        path, SPEC, _stamp(),
        _deps(sweep=_sweeper(answers), frame_names=("year",)),
        only=[topup.FIELD_PROMPT])
    # `rows` counts one re-verification per coordinate swept.
    assert stats["rows"] == len(asked)
    assert stats["stamps carried forward"] == 1
    stored = json.loads((tmp_path / "plan.stamp.json").read_text(
        encoding="utf-8"))
    assert stored[topup.FIELD_PROMPT] == _stamp()[topup.FIELD_PROMPT]


# ---------------------------------------------------------------------------
# A dynamic axis, end to end (WP12e test 3)
# ---------------------------------------------------------------------------

def test_a_dynamic_axis_is_swept_against_this_documents_own_list(tmp_path):
    """The scenarios `scenario` axis has no corpus-wide list: the profile
    closes it per document. Swept with that list the coordinate comes out
    the run identifier; without the hook the document is left alone, because
    swept against an empty list the coordinate degrades to a wording."""
    from docpipe.extraction.spec import fingerprints
    other = _spec("scenarios")
    region = "https://openenergyplatform.org/ontology/oekg/region/Germany"
    text = ("The Current Policies scenario covers Germany. "
            "Results are reported for 2050.")
    row = {"kind": "tuple", "parameter": "scenario_region",
           "value": "Germany", "value_raw": "Germany", "value_uri": region,
           "quote": "covers Germany", "tier": "text_located",
           "parameter_state": fields.READ,
           "scenario": "the NDC scenario", "scenario_raw": "the NDC scenario",
           "scenario_state": fields.READ, "scenario_source": ["section", 9],
           "scenario_quote": "The Current Policies scenario covers Germany.",
           "provenance": {"document_id": 1, "owner_kind": "section",
                          "owner_id": 9, "parent_section": 9, "page": 9}}
    summary = {"kind": "summary", "document_id": 1, "tuples": 1,
               "refusals": 0, "levels": {"A": 1, "B": 0, "C": 0},
               "reasons": {}, "image_origin": 0}
    base = {"spec": "s", "model": "m", "anchors": "a",
            "extraction/harvest": "h", "extraction/queries": "q",
            "extraction/anchors": "an", "extraction/rows": "r",
            "extraction/field": "f", **fingerprints(other)}
    moved = {**base, "axis/scenario_region/scenario": "moved"}
    lists = {"scenario": {"EN_NPi2020_300f": ["Current Policies", "CurPol"]},
             "scenario_region": {region: ["Germany"]}}
    answer = {"scenario": {"value": "Current Policies",
                           "raw": "Current Policies",
                           "quote": "The Current Policies scenario covers "
                                    "Germany.",
                           "source": ["section", 9]}}

    def sources(owners):
        return {(kind, owner): Source(kind, owner, text,
                                      {"document_id": 1, "page": 9,
                                       "parent_section": 9})
                for kind, owner in owners}

    path = _harvest(tmp_path, [row, summary], stamp=moved, name="geco")
    deps = _deps(sweep=_sweeper(answer), owner_sources=sources,
                 document_spec=lambda did: runner.fill_dynamic_axes(other,
                                                                    lists))
    stats = topup.top_up_file(path, other, base, deps)
    assert stats["rows"] == 1 and stats["stamps carried forward"] == 1
    stored = _rows(path)[0]
    assert stored["scenario"] == "EN_NPi2020_300f", "a URI, not the wording"
    assert stored["scenario_raw"] == "Current Policies"

    # Without the hook the list cannot be closed and the file is left alone.
    path = _harvest(tmp_path, [row, summary], stamp=moved, name="ohne")
    before = path.read_bytes()
    stats = topup.top_up_file(path, other, base,
                              _deps(sweep=_sweeper(answer),
                                    owner_sources=sources,
                                    document_spec=lambda did: None))
    assert stats["dynamic list unavailable"] == 1 and stats["rows"] == 0
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# The circle closed (WP12e test 20)
# ---------------------------------------------------------------------------

def test_a_topped_up_document_is_current_and_an_untouched_one_is_not(
        tmp_path, monkeypatch):
    """End to end through `already_done`/`stale`, mirroring
    tests/test_extraction_remap.py: the swept document reads current on the
    next run and the one the pass had to skip stays stale."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    monkeypatch.setattr(runner, "LLM_MODEL", "m")
    current = runner._stamp_current("sha", "anchors", SPEC)
    _harvest(tmp_path, [_row(), _summary()], name="plan",
             stamp={**current, f"axis/{PARAMETER}/sector": "moved"})
    _harvest(tmp_path, [_row(), _summary()], name="offen",
             stamp={**current, "model": "alt"})
    # Before: both stale, one in a coordinate and one in the model. A stale
    # stamp is skipped with a warning by a plain harvest, so `already_done`
    # is True for both; `stale` is what tells them apart.
    assert runner.stale(tmp_path / "plan.stamp.json", current)         == [f"axis/{PARAMETER}/sector"]
    assert runner.stale(tmp_path / "offen.stamp.json", current) == ["model"]

    stats = topup.run(tmp_path, SPEC, current, _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    assert stats["stamps carried forward"] == 1 and stats["blocked"] == 1

    assert runner.stale(tmp_path / "plan.stamp.json", current) == []
    assert runner.already_done("plan", tmp_path, "sha",
                               anchors_sha="anchors", spec=SPEC) is True
    # The stamp says current because the row really carries the new reading,
    # not because the key was written forward on its own.
    after = _rows(tmp_path / "plan.jsonl")[0]
    assert after["sector_raw"] == "Haushalte"
    assert after["sector"] != _row()["sector"]
    assert runner.stale(tmp_path / "offen.stamp.json", current) == ["model"],         "the document the pass had to skip is still stale"
