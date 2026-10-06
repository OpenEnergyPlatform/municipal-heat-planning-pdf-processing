"""Appending a parameter to a stored harvest instead of harvesting it again.

A parameter added to the spec leaves every stored document without that
parameter's key in its stamp, and the resume can only answer that by reading
the whole document again. The pass here reads the document for the new
parameter alone and appends what it found, and each of the promises it makes
has its own test and a case built to break it: stored lines that stay byte for
byte, rows that pass the harvest's checks and no others, a stamp that carries
exactly the keys the pass answered for, a pass that did not read the parameter
and therefore writes nothing.

No model, no GPU, no index: the plan, the model and the passages are stubs.
"""
import ast
import copy
import json
import logging
from pathlib import Path

import pytest

from docpipe.extraction import fields, remap, runner, topup
from docpipe.extraction import topup_parameter as tp
from docpipe.extraction.pipeline import (Batch, DocumentReport, Source,
                                         WorkItem, repeat_key)
from docpipe.extraction.spec import fingerprints, load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
RAW = json.loads((PROFILES / "kwp" / "extraction_spec.json")
                 .read_text(encoding="utf-8"))
SPEC = load_spec(RAW)

QUOTE = "| Heizlast Wärmenetz | 12 | kW |"
TEXT = "Tabelle 7: Heizlast 2045 im Zielszenario.\n" + QUOTE
ORG_QUOTE = "Auftragnehmer: Kassel Wärme Ingenieurbüro GmbH, Bearbeitung: M. Wagner."


@pytest.fixture(autouse=True)
def _no_unserved_request_from_another_test():
    runner.UNSERVED.clear()
    yield
    runner.UNSERVED.clear()


def _raw_without(*uris):
    raw = copy.deepcopy(RAW)
    raw["parameters"] = [p for p in raw["parameters"]
                         if p["uri"] not in uris]
    return raw


def _old(*new):
    """The spec as it read before these parameters were added."""
    return load_spec(_raw_without(*new))


def _run_stamp(spec=SPEC, **overrides):
    """What the run would stamp now: another model and other prompts than
    the harvest had, which a stamp records and never compares."""
    stamp = {"spec": "new-sha", "model": "second", "anchors": "00000000000000a2",
             "extraction/harvest": "h2", "extraction/rows": "r2",
             "extraction/field": "f2", **fingerprints(spec)}
    stamp.update(overrides)
    return stamp


def _stored_stamp(spec, **overrides):
    stamp = {"spec": "old-sha", "model": "first", "anchors": "00000000000000a1",
             "extraction/harvest": "h1", "extraction/rows": "r1",
             "extraction/field": "f1", **fingerprints(spec),
             "producers": [{"pass": "harvest", "model": "first"}]}
    stamp.update(overrides)
    return stamp


# ---------------------------------------------------------------------------
# What was split out of the code that was already there
# ---------------------------------------------------------------------------

def _frame_row(index, scenario="target", year=2045, **overrides):
    row = {"kind": "tuple", "parameter": "energy_consumption", "value": 1.0,
           "scenario": scenario, "scenario_raw": scenario,
           "scenario_quote": f"{scenario} {year}",
           "scenario_source": ["table", 1],
           "scenario_window": ["frame", index],
           "year": year, "year_raw": str(year),
           "year_quote": f"{scenario} {year}", "year_source": ["table", 1],
           "year_window": ["frame", index]}
    row.update(overrides)
    return row


def test_the_frame_of_an_earlier_harvest_is_recovered_without_inventing_any():
    """pairs_of on rows with frame windows 0, 2 and 5 gives pairs keyed 0, 2
    and 5: the gaps stay gaps, nothing is renumbered and no pair is made up
    for an index no row carries."""
    frame = fields.frame_slots(SPEC, ("scenario", "year"))
    rows = [_frame_row(0, "status_quo", 2020), _frame_row(2, "target", 2045),
            _frame_row(2, "target", 2045, value=2.0),
            _frame_row(5, "trend", 2030),
            {"kind": "tuple", "parameter": "energy_consumption",
             "scenario_window": ["own", 1], "year_window": ["own", 1]},
            {"kind": "tuple", "parameter": "planning_organisation"}]
    pairs = topup.pairs_of(rows, frame)
    assert sorted(pairs) == [0, 2, 5]
    assert pairs[2]["scenario"] == "target" and pairs[2]["year"] == 2045
    assert pairs[2]["year_quote"] == "target 2045"
    assert pairs[5]["scenario_source"] == ["table", 1]
    assert topup.pairs_of(rows, []) == {}, "a profile with no frame has none"
    assert topup.pairs_of([], frame) == {}


def test_a_row_that_read_one_frame_coordinate_by_itself_carries_no_pair():
    """Both coordinates have to say `frame`: a row whose year was read from
    its own passage names no pair of the document."""
    frame = fields.frame_slots(SPEC, ("scenario", "year"))
    half = _frame_row(1, year_window=["own", 1])
    assert topup.pairs_of([half], frame) == {}


def test_a_harvest_file_is_read_down_to_the_byte(tmp_path):
    """The lines come back as they stand in the file, with what they parse
    to beside them, the summary left out and its document id kept. A line
    that is no record is kept and counted, an empty one is not a record."""
    lines = ['{"kind": "tuple", "parameter": "x", "value": 241.0}',
             "this is not json",
             '[1, 2]',
             "",
             '{"parameter":"y","kind":"refusal","reason":"r","claim":{}}',
             '{"kind":"parameter_state","parameter":"x","state":"read"}',
             '{"kind": "summary", "document_id": 7, "tuples": 1}']
    path = tmp_path / "plan.jsonl"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    stored = topup.read_harvest(path)
    assert stored.document_id == 7
    assert stored.unreadable == 2
    assert [raw for raw, _row in stored.entries] == [
        lines[0] + "\r", lines[1] + "\r", lines[2] + "\r", lines[4] + "\r",
        lines[5] + "\r"], "the carriage return is part of the line"
    assert [t["parameter"] for t in stored.tuples] == ["x"]
    assert [r["reason"] for r in stored.refusals] == ["r"]
    assert [s["state"] for s in stored.states] == ["read"]
    assert stored.lines == [raw for raw, _row in stored.entries]


def test_a_repeat_is_a_row_that_differs_in_nothing_but_its_provenance():
    first = {"parameter": "x", "value": 1.0, "quote": "q",
             "provenance": {"page": 1}}
    again = {"parameter": "x", "value": 1.0, "quote": "q",
             "provenance": {"page": 9}}
    other = {"parameter": "x", "value": 2.0, "quote": "q",
             "provenance": {"page": 1}}
    assert repeat_key(first) == repeat_key(again)
    assert repeat_key(first) != repeat_key(other)
    assert repeat_key({"b": 1, "a": 2}) == repeat_key({"a": 2, "b": 1})


def test_a_stamp_takes_the_record_of_the_pass_with_the_keys_it_earned(
        tmp_path):
    """The record goes into the same write as the keys: a stamp never holds
    the keys without the sentences of the pass that earned them. A pass that
    earned nothing writes nothing, the record included."""
    stamp = tmp_path / "a.stamp.json"
    stamp.write_text(json.dumps({"parameter/x": "old", "spec": "s"}),
                     encoding="utf-8")
    current = {"parameter/x": "new", "parameter/y": "y", "spec": "s2"}
    assert remap.stamp_forward(
        stamp, current, {"parameter/x"}, producer={"pass": "p"},
        record={"question_text/x": ["a sentence"]})
    stored = json.loads(stamp.read_text(encoding="utf-8"))
    assert stored["parameter/x"] == "new" and "parameter/y" not in stored
    assert stored["question_text/x"] == ["a sentence"]
    assert [p["pass"] for p in stored["producers"]] == ["harvest", "p"]
    before = stamp.read_bytes()
    assert not remap.stamp_forward(stamp, current, {"parameter/x"},
                                   record={"question_text/z": ["no"]})
    assert stamp.read_bytes() == before, (
        "nothing earned, so the record is not written alone")
    assert remap.stamp_forward(stamp, current, {"parameter/y"})
    assert "question_text/z" not in json.loads(stamp.read_text(
        encoding="utf-8")), "a caller that records nothing adds nothing"


def test_the_stamp_schema_knows_the_two_keys_of_a_pass_that_appends():
    jsonschema = pytest.importorskip("jsonschema")
    from docpipe.extraction.schema import stamp_schema
    shape = stamp_schema()
    base = {key: "0" * 64 for key in shape["required"]}
    base.update(model="m", anchors="")
    validator = jsonschema.Draft202012Validator(shape)
    stamp = {**base, "producers": [
        {"pass": "harvest", "model": "m"},
        {"pass": "top-up-parameter", "parameters": ["heat_load"],
         "frame": "none"}]}
    assert not list(validator.iter_errors(stamp))
    stamp["producers"][1]["parameters"] = "heat_load"
    assert list(validator.iter_errors(stamp)), (
        "a parameter list that is no list is not a stamp")
    stamp["producers"][1] = {"pass": "top-up-parameter", "other": 1}
    assert list(validator.iter_errors(stamp)), "and no other key is added"


# ---------------------------------------------------------------------------
# A stored document, its stamp, and a run that wants to append
# ---------------------------------------------------------------------------

STORED_TUPLE = (
    '{"kind":"tuple","value":241.00,"parameter":"energy_consumption",'
    '"unit":"MWh/a","quote":"| Erdgas | 241 | MWh/a |",'
    '"carrier_quote":"Wärmenetze und Erdgas","year":2045,'
    '"year_window":["frame",2],"scenario_window":["frame",2],'
    '"scenario":"target","scenario_raw":"Zielszenario",'
    '"scenario_quote":"Zielszenario 2045","scenario_source":["table",1],'
    '"year_raw":"2045","year_quote":"Zielszenario 2045",'
    '"year_source":["table",1],"sector_raw":"Gewerbe, W\\u00e4rme",'
    '"provenance":{"document_id":7,"owner_kind":"table","owner_id":1}}')
OLD_PARAMETERS = ("energy_consumption", "emission", "planning_organisation")


def _stored_lines(new=("heat_load",)):
    """A harvest of the spec before `new` was added, written the way no
    careful writer would: non-ASCII as it stands, a float with its decimal
    point, keys in no order, a line that is no JSON, a repeat, a refusal."""
    state = ('{"kind": "parameter_state", "document_id": 7, '
             '"parameter": "%s", "state": "%s", "tuples": %d, '
             '"refusals": 0}')
    return [
        STORED_TUPLE,
        "this line is not json {",
        STORED_TUPLE,
        '{"kind": "refusal", "parameter": "emission", "reason": "unit '
        '\'Kilowatt\' not in units_accepted (t)", "claim": {"quote": '
        '"| Wärme | 3 | Kilowatt |"}, "owner": ["table", 1]}',
        *[state % (uri, "read" if uri == "energy_consumption"
                   else "unstated", 2 if uri == "energy_consumption" else 0)
          for uri in OLD_PARAMETERS if uri not in new],
        '{"kind": "summary", "document_id": 7, "tuples": 2, "refusals": 1, '
        '"levels": {"A": 0, "B": 2, "C": 0}, "reasons": {}, '
        '"image_origin": 0}']


class Model:
    """The rows request, as a stub: what it is asked and what it answers."""

    def __init__(self, claims=None, status="complete", unserved=False,
                 note=0):
        self.claims = claims if claims is not None else [
            {"source": "Q1", "parameter": "heat_load", "value": 12,
             "unit": "kW", "quote": QUOTE, "unit_state": fields.READ,
             "unit_quote": QUOTE, "unit_source": ["table", 1],
             "parameter_state": fields.DERIVED}]
        self.status, self.unserved, self.note = status, unserved, note
        self.batches = []

    def __call__(self, batch, prior=None):
        self.batches.append(batch)
        for _ in range(self.note):
            runner.UNSERVED.note(batch.document_id)
        if self.unserved:
            return {"tuples": [{"_harvest_failed": True, "_why": "unserved",
                                "source": batch.label(i)}
                               for i in range(len(batch.items))],
                    "status": "failed", "need_more": []}
        return {"tuples": [dict(c) for c in self.claims],
                "status": self.status, "need_more": []}


class World:
    """One stored document in a folder, and the deps of a run over it."""

    def __init__(self, tmp_path, new=("heat_load",), *, stamp=None,
                 lines=None, text=TEXT, model=None, spec=SPEC, failed=0,
                 unfinished=False, halted=False, no_reply=False,
                 current=None):
        self.dir, self.new, self.spec = Path(tmp_path), tuple(new), spec
        self.old = _old(*new)
        self.path = self.dir / "plan.jsonl"
        self.stamp_path = self.dir / "plan.stamp.json"
        self.lines = list(lines if lines is not None
                          else _stored_lines(self.new))
        self.path.write_bytes(("\n".join(self.lines) + "\n").encode("utf-8"))
        if stamp is not False:
            self.stamp_path.write_text(json.dumps(
                stamp if stamp is not None else _stored_stamp(self.old)),
                encoding="utf-8")
        self.current = current if current is not None else _run_stamp(spec)
        self.text, self.model = text, model or Model()
        self.plan_failed, self.unfinished = failed, unfinished
        self.halted, self.no_reply = halted, no_reply
        self.calls = {"plan": [], "harvest": [], "document_spec": []}
        self.asked = {"heat_load": ["Die Heizlast im Netz."]}

    def deps(self, **overrides):
        def plan(document_id, filename, *, only=(), stored_pairs=None):
            self.calls["plan"].append({"only": tuple(only),
                                       "stored_pairs": stored_pairs})
            source = Source("table", 1, self.text,
                            {"document_id": 7, "page": 3,
                             "title": "Tabelle 7"})
            batch = Batch(7, None, [WorkItem(7, None, source)])
            batch.spec = runner.narrow_spec(self.spec, only)
            report = DocumentReport(document_id=7)
            report.owners_harvested = 1
            report.sources_of = {uri: {("table", 1)} for uri in only}
            return runner.PlannedDocument(
                "plan", report, [batch], self.spec, [], [],
                self.plan_failed)

        def harvest(batches, unfinished=None):
            self.calls["harvest"].append(list(batches))
            if self.unfinished:
                unfinished.add(7)
                return []
            if self.no_reply:
                return []
            return [(batch, self.model(batch, [])) for batch in batches]

        def document_spec(document_id):
            self.calls["document_spec"].append(document_id)
            return self.spec

        deps = {"document_spec": document_spec, "plan": plan,
                "harvest": harvest, "locate": None,
                "questions": lambda name: dict(self.asked),
                "frame_axes": [], "frame_names": (),
                "dynamic_ok": True, "halted": lambda: self.halted}
        deps.update(overrides)
        return deps

    def run(self, **overrides):
        return tp.append_document(7, "plan.pdf", self.dir, self.spec,
                                  self.current, self.deps(**overrides))

    def file_bytes(self):
        return self.path.read_bytes()

    def stamp(self):
        return json.loads(self.stamp_path.read_text(encoding="utf-8"))

    def records(self):
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines()
                if line.startswith("{")]


# ---------------------------------------------------------------------------
# New is told from reworded by the stamp keys
# ---------------------------------------------------------------------------

def _classify(world, **kw):
    return tp.classify(world.stamp_path, world.current, world.spec,
                       world.path, doc_spec_of=lambda: world.spec, **kw)


def test_new_is_told_from_reworded_by_the_stamp(tmp_path):
    """A stamp built from the spec without P says new, and names the keys the
    pass answers for: P's own, its list, its axes, and the two questions that
    belong to no parameter and that the addition alone moved."""
    world = World(tmp_path)
    verdict = _classify(world)
    assert verdict.kind == "new" and [p.uri for p in verdict.new] == [
        "heat_load"]
    assert verdict.owned == {"parameter/heat_load"} | {
        f"axis/heat_load/{name}" for name in SPEC.by_uri["heat_load"].axes}
    assert verdict.shared == {"slot/parameter", "slot/unit"}
    # A parameter with no units moves no unit question.
    (tmp_path / "t").mkdir()
    text = World(tmp_path / "t", new=("planning_organisation",))
    verdict = _classify(text)
    assert verdict.owned == {"parameter/planning_organisation"}
    assert verdict.shared == {"slot/parameter"}


def test_the_keys_a_parameter_owns_are_its_own_and_no_other_parameters():
    """`owned_keys`: the key of the parameter, of its list and of each of its
    axes. A parameter whose uri starts with another's owns none of that
    one's keys, and the questions of no parameter are nobody's."""
    keys = ["parameter/heat", "value/heat", "axis/heat/year",
            "parameter/heat_load", "axis/heat_load/year", "slot/parameter",
            "slot/unit", "model"]
    assert tp.owned_keys("heat", keys) == {
        "parameter/heat", "value/heat", "axis/heat/year"}
    assert tp.owned_keys("heat_load", keys) == {
        "parameter/heat_load", "axis/heat_load/year"}
    assert tp.owned_keys("nobody", keys) == set()


def test_the_keys_an_addition_explains_are_what_the_coordinate_pass_leaves(
        tmp_path):
    """`explained_keys`: the keys of the new parameter and the questions the
    addition alone moved. Violating: a stamp whose question was reworded
    explains no `slot/parameter`, and a stamp that has the parameter explains
    nothing."""
    world = World(tmp_path)
    explained = tp.explained_keys(world.stamp_path, world.current, SPEC)
    assert explained == {"parameter/heat_load", "slot/parameter",
                         "slot/unit"} | {
        f"axis/heat_load/{n}" for n in SPEC.by_uri["heat_load"].axes}
    raw = _raw_without("heat_load")
    raw["parameter_question"] = "Welche Kennzahl ist das?"
    world.stamp_path.write_text(json.dumps(_stored_stamp(load_spec(raw))),
                                encoding="utf-8")
    assert "slot/parameter" not in tp.explained_keys(
        world.stamp_path, world.current, SPEC)
    world.stamp_path.write_text(json.dumps(_stored_stamp(SPEC)),
                                encoding="utf-8")
    assert tp.explained_keys(world.stamp_path, world.current, SPEC) == set()
    assert tp.gained(world.stamp_path, SPEC) == []
    world.stamp_path.write_text(json.dumps(_stored_stamp(_old("heat_load"))),
                                encoding="utf-8")
    assert tp.gained(world.stamp_path, SPEC) == ["heat_load"]
    assert tp.gained(world.dir / "none.stamp.json", SPEC) == [], (
        "no stamp says nothing")


def test_the_lines_of_the_file_are_the_stored_ones_then_the_new_ones(tmp_path):
    """`appended_lines`: the stored lines as strings, never dumped again, then
    tuples, refusals, states, and one summary that counts both."""
    world = World(tmp_path)
    stored = topup.read_harvest(world.path)
    row = {"parameter": "heat_load", "value": 12.0, "quote": QUOTE,
           "provenance": {"page": 3}}
    refusal = {"parameter": "heat_load", "reason": "r", "claim": {},
               "owner": ["table", 1]}
    state = {"parameter": "heat_load", "state": "read", "tuples": 1,
             "refusals": 1}
    lines = tp.appended_lines(stored, 7, [row], [refusal], [state])
    assert lines[:len(stored.lines)] == stored.lines
    kinds = [json.loads(line)["kind"] for line in lines[len(stored.lines):]]
    assert kinds == ["tuple", "refusal", "parameter_state", "summary"]
    summary = json.loads(lines[-1])
    assert summary["tuples"] == 3 and summary["refusals"] == 2
    assert json.loads(lines[-2])["document_id"] == 7
    assert "kind\":\"summary" not in "".join(stored.lines), (
        "the old summary is not among the stored lines")


def test_a_changed_model_or_prompt_beside_the_addition_is_still_new(tmp_path):
    """Recorded, never compared: the stamp of a harvest made by another model
    under other prompts does not make the addition anything else."""
    world = World(tmp_path, stamp=_stored_stamp(
        _old("heat_load"), model="a third model",
        **{"extraction/rows": "other", "extraction/field": "other"}))
    assert _classify(world).kind == "new"


@pytest.mark.parametrize("case, kind", [
    ("reworded", "none"), ("no stamp", "blocked"),
    ("unreadable stamp", "blocked"), ("no parameter keys", "blocked"),
    ("renamed", "blocked"), ("question reworded", "blocked"),
    ("label changed", "blocked"), ("list removed", "blocked")])
def test_what_is_not_an_addition_is_left_stale_as_a_whole(tmp_path, case,
                                                          kind):
    """Each of these must come out as no pass at all: the key of P is there
    and differs (P is reworded, not new), there is no stamp to vouch for
    anything, an old parameter was renamed or has a list the spec no longer
    holds, the question of the spec or a label of an old parameter was
    reworded beside the addition. Violated by construction: each is a stamp
    the pass would otherwise have appended to."""
    old = _old("heat_load")
    stamp = _stored_stamp(old)
    if case == "reworded":
        stamp["parameter/heat_load"] = "another sha"
    elif case == "renamed":
        stamp["parameter/energy_gone"] = "a parameter the spec no longer has"
    elif case == "question reworded":
        raw = _raw_without("heat_load")
        raw["parameter_question"] = "Was ist das?"
        stamp = _stored_stamp(load_spec(raw))
    elif case == "label changed":
        raw = _raw_without("heat_load")
        raw["parameters"][1]["label"] = "Ausstoss"
        stamp = _stored_stamp(load_spec(raw))
    elif case == "list removed":
        stamp["value/energy_consumption"] = "a list the spec no longer has"
    elif case == "no parameter keys":
        stamp = {k: v for k, v in stamp.items()
                 if not k.startswith("parameter/")}
    world = World(tmp_path, stamp=None if case == "unreadable stamp" else (
        False if case == "no stamp" else stamp))
    if case == "unreadable stamp":
        world.stamp_path.write_text("{not json", encoding="utf-8")
    verdict = _classify(world)
    assert verdict.kind == kind, (case, verdict)
    before = world.file_bytes()
    written, failed, stats = world.run()
    assert (written, failed) == (False, 0) and not world.calls["plan"], (
        "not one request for a document the pass may not take")
    assert world.file_bytes() == before


def test_a_remap_that_ran_first_does_not_make_a_new_parameter_look_reworded(
        tmp_path):
    """`--remap` writes `axis/` and `value/` keys for every parameter of the
    spec, read or not. Read as the proof that a parameter was read, they would
    make P look present, and then reworded, and the pass would never be
    taken."""
    world = World(tmp_path)
    remap.remap_file(world.path, SPEC, world.current)
    stored = world.stamp()
    assert "parameter/heat_load" not in stored
    assert any(k.startswith("axis/heat_load/") for k in stored), (
        "the remap settled the axes of a parameter nobody read")
    assert _classify(world).kind == "new"
    # The computation that would block: the stored keys of P read as keys the
    # spec before the addition does not have.
    before = {k: v for k, v in world.current.items()
              if not k.startswith(runner.QUESTION_KEYS)}
    before.update(fingerprints(_old("heat_load")))
    assert set(runner.stale(world.stamp_path, before)) >= {
        k for k in stored if k.startswith("axis/heat_load/")}


def test_a_reworded_parameter_stays_stale_as_a_whole():
    """The coordinate pass is not widened by this one: the key of a parameter
    is no coordinate, and a document whose parameter was reworded is not
    topped up."""
    keys, blocked = topup.actionable(
        ["parameter/energy_consumption", "slot/parameter",
         "value/energy_consumption"], SPEC)
    assert keys == [] and len(blocked) == 3


# ---------------------------------------------------------------------------
# The derivation of the stored rows
# ---------------------------------------------------------------------------

def _numeric_twin(raw, uri="heat_load_shared"):
    twin = copy.deepcopy(next(p for p in raw["parameters"]
                              if p["uri"] == "energy_consumption"))
    twin["uri"] = uri
    twin["label"] = "Zwilling"
    return twin


def test_the_derivation_gate_blocks_what_changes_how_stored_rows_were_decided():
    """A numeric parameter sharing a unit with a stored one leaves a unit two
    parameters accept; a second text parameter leaves a wording two could
    hold. Violated by construction below: a numeric parameter with units of
    its own, and one more text parameter in a spec that already asks several,
    change nothing for a stored row."""
    stored = [
        {"parameter": "energy_consumption", "value": 241.0,
         "unit": "MWh/a"},
        {"parameter": "planning_organisation", "value": "Büro Meier"}]
    shared = copy.deepcopy(RAW)
    shared["parameters"].append(_numeric_twin(RAW))
    twin = load_spec(shared)
    assert tp.derivation_moved(twin, [twin.by_uri["heat_load_shared"]],
                               stored)
    second_text = copy.deepcopy(RAW)
    office = copy.deepcopy(next(p for p in RAW["parameters"]
                                if p["uri"] == "planning_organisation"))
    office["uri"], office["label"] = "second_office", "Zweites Büro"
    second_text["parameters"].append(office)
    spec = load_spec(second_text)
    assert tp.derivation_moved(spec, [spec.by_uri["second_office"]], stored)
    # The same text parameter added to a spec with three texts decides
    # nothing: the wording was already a question.
    many = copy.deepcopy(RAW)
    for n in (1, 2):
        extra = copy.deepcopy(office)
        extra["uri"], extra["label"] = f"office_{n}", f"Büro {n}"
        many["parameters"].append(extra)
    base = load_spec(many)
    last = copy.deepcopy(office)
    last["uri"], last["label"] = "office_3", "Büro 3"
    many["parameters"].append(last)
    grown = load_spec(many)
    assert not tp.derivation_moved(grown, [grown.by_uri["office_3"]], stored)
    assert base.by_uri.get("office_3") is None
    # Units of its own: heat_load's kW are in no other list.
    assert not tp.derivation_moved(SPEC, [SPEC.by_uri["heat_load"]], stored)
    # The rows of the new parameter are the pass's own and are not asked.
    assert not tp.derivation_moved(
        twin, [twin.by_uri["heat_load_shared"]],
        [{"parameter": "heat_load_shared", "value": 1.0, "unit": "MWh/a"}])


def test_a_document_whose_rows_were_decided_otherwise_is_left_alone(tmp_path):
    shared = copy.deepcopy(RAW)
    shared["parameters"].append(_numeric_twin(RAW))
    spec = load_spec(shared)
    world = World(tmp_path, new=("heat_load_shared",), spec=spec,
                  stamp=_stored_stamp(load_spec(RAW)))
    verdict = _classify(world)
    assert verdict.kind == "blocked" and "derivation" in verdict.why
    before = world.file_bytes()
    assert world.run()[:2] == (False, 0)
    assert world.file_bytes() == before and not world.calls["plan"]


# ---------------------------------------------------------------------------
# The coordinate pass is not blocked by the addition, and by nothing less
# ---------------------------------------------------------------------------

def _top_up_world(tmp_path, **stamp_overrides):
    """A harvest whose stamp lacks heat_load AND has one axis moved."""
    stamp = _stored_stamp(_old("heat_load"), **stamp_overrides)
    path = tmp_path / "plan.jsonl"
    row = {"kind": "tuple", "parameter": "energy_consumption", "value": 241.0,
           "unit": "MWh/a", "quote": QUOTE,
           "provenance": {"document_id": 7, "owner_kind": "table",
                          "owner_id": 1}}
    path.write_text("\n".join(json.dumps(r) for r in (
        row, {"kind": "summary", "document_id": 7, "tuples": 1,
              "refusals": 0})) + "\n", encoding="utf-8")
    (tmp_path / "plan.stamp.json").write_text(json.dumps(stamp),
                                              encoding="utf-8")
    return path


def _top_up_deps(calls, answer=None):
    def sweep(batch, rows, slots, anchor_id=""):
        calls.append([slot.name for slot in slots])
        for slot in slots:
            if slot.name in (answer or {}):
                for row in rows:
                    row.claim[slot.name] = answer[slot.name]
                    row.claim[f"{slot.name}_state"] = fields.READ
                    row.claim[f"{slot.name}_raw"] = answer[slot.name]
                    row.claim[f"{slot.name}_quote"] = QUOTE
                    row.claim[f"{slot.name}_source"] = ["table", 1]
        return {}

    def owner_sources(owners):
        return {(k, o): Source(k, o, TEXT, {"document_id": 7})
                for k, o in owners}

    return {"sweep": sweep, "owner_sources": owner_sources,
            "document_spec": lambda did: SPEC, "frame_names": (),
            "dynamic_ok": True, "locate": None}


def test_the_coordinate_pass_is_no_longer_blocked_by_the_new_keys(tmp_path):
    """A new parameter beside one moved axis: the axis is swept, the keys of
    the addition are left stale for the pass that appends it."""
    path = _top_up_world(
        tmp_path, **{"axis/energy_consumption/sector": "an older question"})
    calls = []
    stats = topup.top_up_file(path, SPEC, _run_stamp(), _top_up_deps(
        calls, answer={"sector": "Haushalte"}))
    assert calls == [["sector"]], "the moved axis was swept, and it alone"
    assert not stats["blocked"]
    left = runner.stale(tmp_path / "plan.stamp.json", _run_stamp())
    assert "axis/energy_consumption/sector" not in left, "it was settled"
    assert set(left) == {"parameter/heat_load", "slot/parameter", "slot/unit"
                         } | {f"axis/heat_load/{n}"
                              for n in SPEC.by_uri["heat_load"].axes}, (
        "and the keys of the addition are left for the pass that appends")


def test_the_coordinate_pass_is_still_blocked_by_everything_else(tmp_path):
    """Violating: the addition beside a REWORDED parameter. Taking the
    addition's keys out must not take the blocking one with them."""
    stamp = {"parameter/energy_consumption": "an older description"}
    path = _top_up_world(tmp_path, **stamp)
    calls = []
    stats = topup.top_up_file(path, SPEC, _run_stamp(), _top_up_deps(calls))
    assert calls == [] and stats["blocked"] == 1


def test_the_coordinate_pass_reads_a_file_with_carriage_returns_as_it_always_did(
        tmp_path):
    """`read_harvest` keeps a line as it stands, a carriage return included,
    and the coordinate pass has always read its file with the line endings
    folded and written the line feed alone. Violating: a line that kept its
    carriage return would be written with it, and the file of the same
    content would come out other bytes than its twin with line feeds."""
    written = []
    for name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        folder = tmp_path / name
        folder.mkdir()
        row = {"kind": "tuple", "parameter": "energy_consumption",
               "value": 241.0, "unit": "MWh/a", "quote": QUOTE,
               "provenance": {"document_id": 7, "owner_kind": "table",
                              "owner_id": 1}}
        state = {"kind": "parameter_state", "document_id": 7,
                 "parameter": "emission", "state": "unstated", "tuples": 0,
                 "refusals": 0}
        lines = [json.dumps(row), "this line is not json {",
                 json.dumps(state),
                 json.dumps({"kind": "summary", "document_id": 7,
                             "tuples": 1, "refusals": 0})]
        (folder / "plan.jsonl").write_bytes(
            (newline.join(lines) + newline).encode("utf-8"))
        (folder / "plan.stamp.json").write_text(json.dumps(_stored_stamp(
            SPEC, **{"axis/energy_consumption/sector": "an older question"})),
            encoding="utf-8")
        calls = []
        stats = topup.top_up_file(
            folder / "plan.jsonl", SPEC, _run_stamp(),
            _top_up_deps(calls, answer={"sector": "Haushalte"}))
        assert calls == [["sector"]], name
        assert stats["unreadable line kept"] == 1, name
        written.append((folder / "plan.jsonl").read_bytes())
    assert written[0] == written[1]
    assert b"this line is not json {" in written[0]


def test_a_document_that_only_gained_a_parameter_is_left_to_this_pass(
        tmp_path):
    path = _top_up_world(tmp_path)
    before = path.read_bytes()
    calls = []
    stats = topup.top_up_file(path, SPEC, _run_stamp(), _top_up_deps(calls))
    assert calls == [] and stats["left to --top-up-parameters"] == 1
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def test_stored_lines_stay_byte_for_byte(tmp_path):
    """Every stored line comes back as the same bytes in the same order:
    non-ASCII as it stands, 241.0 with its decimal point, keys in no order, a
    line that is no JSON, two identical tuples, a refusal, the state lines.
    The new tuple, refusal and state lines follow, and only the old summary
    is replaced, by a last line. Violating: dumping the stored tuples again
    moves bytes, and this file would show it."""
    world = World(tmp_path)
    stored = list(world.lines)
    written, failed, stats = world.run()
    assert (written, failed) == (True, 0)
    now = world.path.read_bytes().decode("utf-8").split("\n")
    assert now[-1] == ""
    now = now[:-1]
    kept = stored[:-1]
    assert now[:len(kept)] == kept, "every stored line, as it was"
    assert "Wärmenetze" in now[0] and "241.00" in now[0]
    assert "W\\u00e4rme" in now[0], "an escape stays an escape"
    added = [json.loads(line) for line in now[len(kept):]]
    assert [r["kind"] for r in added] == ["tuple", "parameter_state",
                                          "summary"]
    assert added[0]["parameter"] == "heat_load"
    assert added[1]["parameter"] == "heat_load" and added[1][
        "state"] == "read"
    assert added[2]["tuples"] == 3, "two stored, one appended"
    assert json.loads(stored[-1])["tuples"] == 2, "the old summary is gone"
    # Re-dumped, the stored tuple would not be the line that stands there.
    assert json.dumps(json.loads(STORED_TUPLE),
                      ensure_ascii=False) != STORED_TUPLE, (
        "the line is not what the writer of the harvest would have written")


def test_a_stored_document_is_not_touched_when_no_parameter_is_new(tmp_path):
    world = World(tmp_path, stamp=_stored_stamp(SPEC))
    before = (world.file_bytes(), world.stamp_path.read_bytes())
    written, failed, stats = world.run()
    assert (written, failed) == (False, 0)
    assert stats["documents without a new parameter (documents)"] == 1
    assert (world.file_bytes(), world.stamp_path.read_bytes()) == before
    assert world.calls == {"plan": [], "harvest": [], "document_spec": []}


def test_the_rows_request_and_the_search_are_for_the_new_parameter_alone(
        tmp_path):
    """What the pass hands the plan and what the batches offer: the named
    parameter and no other."""
    world = World(tmp_path)
    world.run()
    [call] = world.calls["plan"]
    assert call["only"] == ("heat_load",)
    [batch] = world.model.batches
    body = runner._batch_payload(batch, [], runner.spec_of(batch, SPEC))
    assert [q["uri"] for q in body["quantities"]] == ["heat_load"]


def test_the_appended_row_is_a_row_of_the_new_parameter_with_the_states_a_row_has(
        tmp_path):
    world = World(tmp_path)
    world.run()
    row = next(r for r in world.records() if r.get("kind") == "tuple"
               and r["parameter"] == "heat_load")
    assert row["value"] == 12.0 and row["unit"] == "kW"
    assert row["quote"] == QUOTE and row["provenance"]["owner_id"] == 1
    # Every coordinate it read points at the entry the pass made, and an
    # older coordinate of an older row is not pointed at anything.
    position = len(_stored_stamp(SPEC)["producers"])
    pointers = {k: v for k, v in row.items() if k.endswith("_producer")}
    assert pointers and set(pointers.values()) == {position}
    assert world.stamp()["producers"][position]["pass"] == "top-up-parameter"
    old = next(r for r in world.records() if r.get("kind") == "tuple"
               and r["parameter"] == "energy_consumption")
    assert not [k for k in old if k.endswith("_producer")]


def test_the_checks_are_the_harvests_and_no_others(tmp_path):
    """Through the real fold and the real verifier, with a stub model: a row
    whose quote is in no shown passage, one whose quote does not carry the
    value and one whose quote is too short are refused and never read; an odd
    but backed row (a power of 0) is kept, and so is a row whose quote the
    harvest itself repairs from its passage. Violating by construction: a
    wrong quote must not come out as a tuple."""
    claims = [
        {"source": "Q1", "parameter": "heat_load", "value": 77, "unit": "kW",
         "quote": "| Heizlast Fernwärme | 77 | kW | that no passage holds"},
        {"source": "Q1", "parameter": "heat_load", "value": 99,
         "unit": "kW", "quote": QUOTE},
        {"source": "Q1", "parameter": "heat_load", "value": 12,
         "unit": "kW", "quote": "12 | kW"},
        {"source": "Q1", "parameter": "heat_load", "value": 0, "unit": "kW",
         "quote": "| Heizlast Gewerbe | 0 | kW |"},
        {"source": "Q1", "parameter": "heat_load", "value": 5, "unit": "kW",
         "quote": "| Heizlast Netz | 5 | kW | and more it never said"}]
    text = "\n".join([TEXT, "| Heizlast Gewerbe | 0 | kW |",
                      "| Heizlast Netz | 5 | kW |"])
    world = World(tmp_path, model=Model(claims), text=text)
    world.run()
    added = world.records()[len(_stored_lines()) - 2:]
    tuples = [r for r in added if r["kind"] == "tuple"]
    refusals = [r for r in added if r["kind"] == "refusal"]
    assert sorted(t["value"] for t in tuples) == [0, 5], (
        "the odd but backed row, and the one the harvest repairs")
    assert sorted(r["reason"] for r in refusals) == sorted([
        "quote not found in the source it cites",
        "value 99 does not occur in the quote",
        "quote missing or too short to identify anything"])
    state = next(r for r in added if r["kind"] == "parameter_state")
    assert state["state"] == "read" and state["refusals"] == 3


def test_the_new_pass_writes_no_reason_of_its_own():
    """An AST scan of the module: no `reason` and no `_why` is written in
    it, and the lists of the reasons a harvest has are as they were."""
    from docpipe.extraction.schema import DROP_REASONS, REFUSAL_REASONS
    tree = ast.parse((Path(tp.__file__)).read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys
                     if isinstance(k, ast.Constant)}
        elif isinstance(node, ast.keyword):
            keys.add(node.arg)
    assert not keys & {"reason", "_why", "why"}, sorted(keys)
    assert len(REFUSAL_REASONS) == 13 and len(DROP_REASONS) == 6
    reasons = (Path(__file__).parent / "test_extraction_reasons.py")
    assert "TOPUP_PARAMETER" in reasons.read_text(encoding="utf-8")


def test_a_reading_identical_to_a_stored_one_is_not_written_twice_and_no_stored_one_is_removed(
        tmp_path):
    """A new row equal to a stored tuple of ANOTHER parameter in everything
    but its provenance is not appended, and the pass counts it. A stored file
    that already holds a repeat keeps both. Violating: keying with the stored
    row's `kind`, or dropping repeats over stored and new together, would
    change one of the two."""
    stored_row = json.loads(STORED_TUPLE)
    repeat = {k: v for k, v in stored_row.items() if k != "kind"}
    rows, identical = tp.drop_stored_repeats(
        [dict(repeat, provenance={"page": 99}),
         dict(repeat, value=2.0)], [stored_row, dict(stored_row)])
    assert identical == 1 and [r["value"] for r in rows] == [2.0]
    # The pointer says who read it, and a reading is the same reading.
    pointed = dict(repeat, year_producer=3)
    assert tp.drop_stored_repeats([pointed], [stored_row])[1] == 1
    # In a whole pass: the stub model answers exactly the stored tuple.
    claim = {"source": "Q1", "parameter": "energy_consumption",
             "value": 241.0, "unit": "MWh/a",
             "quote": "| Erdgas | 241 | MWh/a |"}
    world = World(tmp_path, text="| Erdgas | 241 | MWh/a |\nTabelle 3",
                  model=Model([claim]), spec=SPEC)
    before = world.lines[:-1]
    # The narrowed spec does not offer energy_consumption: the claim is a
    # refusal and no tuple. What the pass compares is the tuples it has.
    world.run()
    now = world.path.read_bytes().decode("utf-8").split("\n")[:-1]
    assert now[:len(before)] == before, "no stored line is removed"
    assert now.count(STORED_TUPLE) == 2, "the stored repeat keeps both"


def test_the_same_reading_twice_in_one_pass_is_written_once(tmp_path):
    """Two requests that read the same value from the same passage are one
    reading, as in the harvest. Violating: the pass that skipped the repeat
    check would append the row twice."""
    claim = {"source": "Q1", "parameter": "heat_load", "value": 12,
             "unit": "kW", "quote": QUOTE}
    world = World(tmp_path, model=Model([claim, dict(claim)]))
    world.run()
    mine = [r for r in world.records() if r["kind"] == "tuple"
            and r["parameter"] == "heat_load"]
    assert len(mine) == 1


def test_a_tuple_of_the_new_parameter_that_is_already_stored_is_not_written_again(
        tmp_path):
    """The pass compares what it read with every stored tuple, whatever its
    parameter. A file that holds the reading already (another run wrote it
    and died before the state line) keeps its one tuple, the pass counts the
    one it did not append, and the stored line is not removed."""
    first = World(tmp_path)
    first.run()
    reading = next(r for r in first.records() if r["kind"] == "tuple"
                   and r["parameter"] == "heat_load")
    (tmp_path / "second").mkdir()
    lines = _stored_lines()
    lines.insert(-1, json.dumps(reading, ensure_ascii=False))
    again = World(tmp_path / "second", lines=lines)
    written, failed, stats = again.run()
    assert (written, failed) == (True, 0)
    mine = [r for r in again.records() if r["kind"] == "tuple"
            and r["parameter"] == "heat_load"]
    assert len(mine) == 1, "the stored one, and not a second"
    assert stats["tuples identical to a stored tuple, not appended "
                 "(tuples)"] == 1
    assert json.dumps(reading, ensure_ascii=False) in (
        again.path.read_text(encoding="utf-8").splitlines())
    state = [r for r in again.records() if r["kind"] == "parameter_state"
             and r["parameter"] == "heat_load"]
    assert [s["state"] for s in state] == ["read"], (
        "the parameter is read: the file holds its tuple")


def test_a_stored_key_of_the_new_parameter_the_spec_no_longer_has_does_not_block(
        tmp_path):
    """A `--remap` under an older spec left `axis/heat_load/legacy` in the
    stamp. It is the new parameter's own, so it is not another question that
    moved: the pass is taken, and the key, which no spec asks any more, stays
    in the stamp for `--force-stale` to answer."""
    stamp = _stored_stamp(_old("heat_load"),
                          **{"axis/heat_load/legacy": "an axis long gone"})
    world = World(tmp_path, stamp=stamp)
    assert _classify(world).kind == "new"
    assert world.run()[:2] == (True, 0)
    assert runner.stale(world.stamp_path, world.current) == [
        "axis/heat_load/legacy"]


def test_the_summary_and_the_parameter_states_describe_the_file(tmp_path):
    """Tuples and refusals are stored plus appended, the levels add up to the
    tuples, the summary is the last line, the stored states are unchanged and
    one new line stands for the new parameter."""
    world = World(tmp_path)
    world.run()
    records = world.records()
    assert records[-1]["kind"] == "summary"
    tuples = [r for r in records if r["kind"] == "tuple"]
    refusals = [r for r in records if r["kind"] == "refusal"]
    summary = records[-1]
    assert summary["tuples"] == len(tuples) == 3
    assert summary["refusals"] == len(refusals) == 1
    assert sum(summary["levels"].values()) == summary["tuples"]
    states = [r for r in records if r["kind"] == "parameter_state"]
    assert [s["parameter"] for s in states] == [
        "energy_consumption", "emission", "planning_organisation",
        "heat_load"]
    stored_states = [json.loads(line) for line in world.lines
                     if '"parameter_state"' in line]
    assert len(stored_states) == 3
    assert states[:3] == stored_states, "the stored lines are not recomputed"


def test_the_refusals_of_the_first_pass_are_not_revisited_and_the_summary_says_so(
        tmp_path, caplog):
    """The owner's decision for a stored refusal the new parameter would now
    read: the line stays, the new tuple is appended beside it, and the summary
    counts both and says what its refusal count is. Violating by construction:
    the cell the stored refusal was made of is read now, so a pass that took
    the refusal back out (a matching rule nobody decided on) would show one
    refusal fewer and a different file."""
    from docpipe.extraction.schema import build
    cell = {"kind": "refusal", "parameter": None,
            "reason": "claim names no parameter of the spec",
            "claim": {"value": 12, "unit": "kW", "quote": QUOTE},
            "owner": ["table", 1]}
    lines = _stored_lines()
    lines.insert(-1, json.dumps(cell, ensure_ascii=False))
    world = World(tmp_path, lines=lines)
    run = tp.DocumentPass(world.dir, SPEC, world.current, world.deps())
    assert run(7, "plan.pdf") == (True, 0)
    now = world.path.read_bytes().decode("utf-8").split("\n")
    assert json.dumps(cell, ensure_ascii=False) in now, "the refusal stays"
    records = world.records()
    assert len([r for r in records if r["kind"] == "refusal"]) == 2
    assert [r["value"] for r in records if r["kind"] == "tuple"
            and r["parameter"] == "heat_load"] == [12], (
        "and the cell is read beside it")
    assert records[-1]["refusals"] == 2 and records[-1]["tuples"] == 3
    described = build(SPEC)["harvest"]["$defs"]["summary"]["description"]
    assert "are not revisited" in described
    # The pass says it in its own log, and only where a stored refusal was
    # left alone.
    assert run.stats["stored refusals not revisited (refusals)"] == 2
    with caplog.at_level(logging.INFO, logger=tp.log.name):
        run.report()
    assert "refusals of the first pass are not revisited" in caplog.text
    caplog.clear()
    (tmp_path / "plain").mkdir()
    plain = World(tmp_path / "plain", lines=[
        line for line in _stored_lines() if '"refusal"' not in line])
    run = tp.DocumentPass(plain.dir, SPEC, plain.current, plain.deps())
    assert run(7, "plan.pdf") == (True, 0)
    with caplog.at_level(logging.INFO, logger=tp.log.name):
        run.report()
    assert "refusals of the first pass are not revisited" not in caplog.text, (
        "a file with no stored refusal has nothing to say about them")


@pytest.mark.parametrize("case, state", [
    ("nothing said", "unstated"), ("only refusals", "unbacked"),
    ("cut off", "exhausted")])
def test_a_new_parameter_with_no_row_still_gets_its_line(tmp_path, case,
                                                         state):
    """The file never says nothing about a parameter. Violating by
    construction: no row at all and clean replies is `unstated`, not a
    missing line; a request that came back cut off leaves it `exhausted`; a
    claim the checks refused leaves it `unbacked`."""
    if case == "nothing said":
        model = Model(claims=[])
    elif case == "only refusals":
        model = Model(claims=[{"source": "Q1", "parameter": "heat_load",
                               "value": 5, "unit": "kW",
                               "quote": "a quote no passage holds"}])
    else:
        model = Model(claims=[])
        cut = {"tuples": [{"_harvest_failed": True, "_why": "cut_off",
                           "source": "Q1"}], "status": "failed",
               "need_more": []}
        model = lambda batch, prior=None: cut
    world = World(tmp_path, model=model)
    written, failed, stats = world.run()
    assert (written, failed) == (True, 0)
    line = [r for r in world.records() if r["kind"] == "parameter_state"
            and r["parameter"] == "heat_load"]
    assert len(line) == 1 and line[0]["state"] == state, (case, line)
    assert stats[f"parameters {state} (parameters x documents)"] == 1


def test_the_stamp_carries_exactly_what_the_pass_answered_for(tmp_path):
    """For a document whose only change is the addition: nothing is stale
    afterwards, every key of another parameter is as it was, the producers
    list ends with the entry of this pass and validates, and the sentences
    the document was searched with are recorded."""
    old = _old("heat_load")
    first = _stored_stamp(old)
    world = World(tmp_path, stamp=first)
    written, failed, _stats = world.run()
    assert (written, failed) == (True, 0)
    after = world.stamp()
    assert runner.stale(world.stamp_path, world.current) == []
    answered = {k for k in after if after.get(k) != first.get(k)}
    owned = {"parameter/heat_load"} | {
        f"axis/heat_load/{n}" for n in SPEC.by_uri["heat_load"].axes}
    assert answered == owned | {"slot/parameter", "slot/unit", "producers",
                                "question_text/heat_load"}
    for key in ("model", "anchors", "extraction/harvest", "extraction/rows",
                "extraction/field", "spec"):
        assert after[key] == first[key], f"{key} is recorded, not rewritten"
    entry = after["producers"][-1]
    assert entry["pass"] == "top-up-parameter"
    assert entry["parameters"] == ["heat_load"]
    assert entry["frame"] == "none" and entry["model"] == runner.LLM_MODEL
    assert after["producers"][:-1] == first["producers"]
    assert after["question_text/heat_load"] == ["Die Heizlast im Netz."]
    jsonschema = pytest.importorskip("jsonschema")
    from docpipe.extraction.schema import stamp_schema
    shape = stamp_schema()
    full = {**{k: "0" * 64 for k in shape["required"]}, **{
        k: v for k, v in after.items() if k in ("model", "anchors",
                                                "producers")}}
    jsonschema.validate(full, shape)


def test_the_whole_file_sha_moves_when_nothing_else_is_stale(tmp_path):
    """The existing rule inside `stamp_forward`: with every other key the
    same, the sha of the file is a mirror of the keys under it and moves with
    them; beside a moved coordinate it stays, which is the next pass's to
    answer."""
    old = _old("heat_load")
    stored = _stored_stamp(old)
    # A run of the same model and prompts as the harvest: only the addition
    # differs, and the sha of the file with it.
    same = {k: v for k, v in stored.items()
            if not k.startswith(runner.QUESTION_KEYS) and k != "producers"}
    current = {**same, **fingerprints(SPEC), "spec": "new-sha"}
    world = World(tmp_path, stamp=stored, current=current)
    world.run()
    assert world.stamp()["spec"] == "new-sha"
    other = tmp_path / "other"
    other.mkdir()
    moved = World(other, stamp={**stored, "spec": "old-sha",
                                "axis/energy_consumption/sector": "older"},
                  current=current)
    moved.run()
    assert runner.stale(moved.stamp_path, current) == [
        "axis/energy_consumption/sector"], (
        "exactly the moved coordinate stays stale")
    assert moved.stamp()["spec"] == "old-sha", (
        "and the sha of the file does not move past it")


def test_an_unexplained_slot_question_blocks_the_pass_and_is_never_written_forward(
        tmp_path):
    """The spec's own question was reworded beside the addition: the stored
    rows were asked another question, and the pass leaves the document
    alone."""
    raw = _raw_without("heat_load")
    raw["parameter_question"] = "Welche Kennzahl ist das?"
    world = World(tmp_path, stamp=_stored_stamp(load_spec(raw)))
    before = (world.file_bytes(), world.stamp_path.read_bytes())
    assert world.run()[:2] == (False, 0)
    assert (world.file_bytes(), world.stamp_path.read_bytes()) == before


def test_a_document_read_from_another_pdf_is_left_stale_as_a_whole(
        tmp_path, monkeypatch):
    """The stamp is held against the PDF as the resume holds it: rows read
    from one file are not appended to from the passages of another. Violating:
    a pass that never looked at the PDF takes the document, and a stamp that
    names no PDF (one from before the key) must not be blocked either."""
    read_from = {"sha256": "a" * 64, "bytes": 10}
    world = World(tmp_path, stamp=_stored_stamp(_old("heat_load"),
                                                document=read_from))
    before = (world.file_bytes(), world.stamp_path.read_bytes())
    monkeypatch.setitem(runner.DOCUMENT_CONTENT, "plan",
                        {"sha256": "b" * 64, "bytes": 11})
    held = tp.classify(
        world.stamp_path, {**world.current, **runner.document_current("plan")},
        SPEC, world.path, doc_spec_of=lambda: SPEC)
    assert held.kind == "blocked" and "document" in held.why
    written, failed, stats = world.run()
    assert (written, failed) == (False, 0) and not world.calls["plan"]
    assert stats["documents left stale as a whole (documents)"] == 1
    assert (world.file_bytes(), world.stamp_path.read_bytes()) == before
    monkeypatch.setitem(runner.DOCUMENT_CONTENT, "plan", read_from)
    assert world.run()[:2] == (True, 0), "the same PDF is taken"
    other = tmp_path / "older"
    other.mkdir()
    older = World(other, stamp=_stored_stamp(_old("heat_load")))
    monkeypatch.setitem(runner.DOCUMENT_CONTENT, "plan", read_from)
    assert older.run()[:2] == (True, 0), "a stamp that names no PDF is taken"
    assert "document" not in older.stamp(), (
        "and the PDF is no key this pass writes")


# ---------------------------------------------------------------------------
# A pass that did not read the parameter completely
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["unserved sentinel", "noted request",
                                  "frame raised", "unfinished", "halted",
                                  "no reply", "lost search sentence"])
def test_a_pass_that_did_not_complete_leaves_file_and_stamp_untouched(
        tmp_path, case):
    """Each case is a stub that does what the server did: a rows request that
    ended on a 503, a request noted inside a field sweep, a frame or a plan
    that raised, a document the run halted in. In every one the file and the
    stamp are the bytes they were. Violating: the coordinate pass writes the
    file in such a case, and this one would then show a changed file."""
    kwargs = {}
    if case == "unserved sentinel":
        kwargs["model"] = Model(unserved=True)
    elif case == "noted request":
        kwargs["model"] = Model(note=1)
    elif case == "frame raised":
        kwargs["failed"] = 1
    elif case == "unfinished":
        kwargs["unfinished"] = True
    elif case == "halted":
        kwargs["halted"] = True
    elif case == "no reply":
        kwargs["no_reply"] = True
    elif case == "lost search sentence":
        class Searching(World):
            def deps(self, **overrides):
                deps = super().deps(**overrides)
                inner = deps["plan"]

                def plan(*a, **k):
                    runner.UNSERVED.note(7)
                    return inner(*a, **k)
                deps["plan"] = plan
                return deps
        world = Searching(tmp_path)
    if case != "lost search sentence":
        world = World(tmp_path, **kwargs)
    before = (world.file_bytes(), world.stamp_path.read_bytes())
    written, failed, stats = world.run()
    assert written is False
    assert (world.file_bytes(), world.stamp_path.read_bytes()) == before
    if case in ("unfinished", "halted"):
        assert failed == 0, "the halt is counted by the run, once"
    else:
        assert failed == 1, case
    assert not (tmp_path / "plan.jsonl.tmp").exists()


def test_a_pass_that_did_not_read_says_what_it_counted_in_its_own_unit(
        tmp_path, caplog):
    """A number in a message says what it counts: sources of a plan, or
    requests. Violating: the message that said "1 of 1" and nothing else."""
    assert tp.not_read("unreachable", 3, 4) == (
        "3 of 4 source(s) never reached the server")
    assert tp.not_read("no_reply", 4, 4) == (
        "4 source(s) planned and not one reply")
    assert tp.not_read("unserved", 2, 2) == (
        "2 request(s) ended on a 429 or a 5xx")
    world = World(tmp_path, model=Model(unserved=True))
    with caplog.at_level(logging.ERROR, logger=tp.log.name):
        world.run()
    assert "1 request(s) ended on a 429 or a 5xx" in caplog.text
    assert "nothing is written" in caplog.text


def test_the_counts_say_what_they_count(tmp_path):
    """Every number the pass reports names its unit, and each is what it says:
    one line that is no JSON, one tuple appended, no refusal, nothing
    identical to a stored tuple, the one refusal of the first pass left
    alone, one parameter read. Violating: a count that is left out or that
    counts another thing is another dictionary."""
    world = World(tmp_path)
    written, failed, stats = world.run()
    assert (written, failed) == (True, 0)
    assert dict(stats) == {
        "unreadable lines kept (lines)": 1,
        "documents appended (documents)": 1,
        "tuples appended (tuples)": 1,
        "refusals appended (refusals)": 0,
        "tuples identical to a stored tuple, not appended (tuples)": 0,
        "stored refusals not revisited (refusals)": 1,
        "parameters read (parameters x documents)": 1}


def test_a_row_the_published_schema_refuses_is_counted_and_still_written(
        tmp_path, caplog):
    """`check_against_schema` over what the pass appends: counted and traced,
    never blocking, as in the harvest. Violating: a pass that does not look
    says nothing about a row downstream cannot read, and one that blocked
    would lose the reading."""
    claim = {"source": "Q1", "parameter": "heat_load", "value": 12,
             "unit": "kW", "quote": QUOTE, "unit_state": fields.READ,
             "unit_quote": QUOTE, "unit_source": ["table", 1],
             "parameter_state": fields.DERIVED,
             "an_invented_key": "no schema holds it"}
    world = World(tmp_path, model=Model([claim]))
    with caplog.at_level(logging.WARNING, logger=runner.log.name):
        assert world.run()[:2] == (True, 0)
    assert "do not match the published schema" in caplog.text
    mine = [r for r in world.records() if r["kind"] == "tuple"
            and r["parameter"] == "heat_load"]
    assert len(mine) == 1, "the reading is written all the same"


def test_a_stamp_that_could_not_be_written_after_the_file_is_completed_by_the_next_run(
        tmp_path, monkeypatch):
    """The window between the file and the stamp, through the failure and not
    only through a stamp that was never written: the document counts as not
    done and the run says so, the file stays what it was written as, and the
    next run completes the stamp and asks nothing. Violating: a pass that
    reported the document done leaves the stamp missing for ever, and one that
    wrote the file again would append the parameter twice."""
    world = World(tmp_path)
    real = tp.stamp_forward
    monkeypatch.setattr(tp, "stamp_forward", lambda *a, **k: False)
    written, failed, stats = world.run()
    assert (written, failed) == (True, 1)
    assert stats["documents not taken (documents)"] == 1
    assert "parameter/heat_load" not in world.stamp()
    appended = world.file_bytes()
    asked = len(world.calls["plan"])
    monkeypatch.setattr(tp, "stamp_forward", real)
    assert world.run()[:2] == (True, 0)
    assert len(world.calls["plan"]) == asked, "no request"
    assert world.file_bytes() == appended
    assert runner.stale(world.stamp_path, world.current) == []


def test_the_trace_of_a_document_is_flushed_when_its_pass_is_done(tmp_path):
    """The loop calls the pass from a thread per document, and the trace of a
    document that is done has to be on disk before the run is. Violating: a
    pass that left the buffer to the end of the run would show an empty file
    here."""
    from docpipe.extraction import trace
    world = World(tmp_path)
    folder = tmp_path / "trace"
    trace.open_trace(folder, {7: "plan"}.get)
    try:
        run = tp.DocumentPass(world.dir, SPEC, world.current, world.deps())
        assert run(7, "plan.pdf") == (True, 0)
        assert (folder / "plan.trace.jsonl").read_text(
            encoding="utf-8").strip(), "the events are on disk"
    finally:
        trace.close()


def test_a_second_run_changes_nothing(tmp_path):
    world = World(tmp_path)
    assert world.run()[:2] == (True, 0)
    after = (world.file_bytes(), world.stamp_path.read_bytes())
    asked = len(world.calls["plan"])
    written, failed, stats = world.run()
    assert (written, failed) == (False, 0)
    assert (world.file_bytes(), world.stamp_path.read_bytes()) == after
    assert len(world.calls["plan"]) == asked, "not one request"


def test_a_file_that_holds_the_state_line_but_no_stamp_key_makes_no_request(
        tmp_path):
    """The one window the pass has: the file was replaced and the stamp was
    never written. The next run completes the stamp and asks nothing."""
    first = World(tmp_path)
    first.run()
    complete = first.stamp()
    stamp = {k: v for k, v in complete.items()
             if k not in ("parameter/heat_load",) and not k.startswith(
                 "axis/heat_load/")}
    stamp["slot/parameter"] = _stored_stamp(_old("heat_load"))[
        "slot/parameter"]
    stamp["slot/unit"] = _stored_stamp(_old("heat_load"))["slot/unit"]
    first.stamp_path.write_text(json.dumps(stamp), encoding="utf-8")
    before = first.file_bytes()
    asked = len(first.calls["plan"])
    written, failed, stats = first.run()
    assert (written, failed) == (True, 0)
    assert len(first.calls["plan"]) == asked, "no request"
    assert first.file_bytes() == before
    assert runner.stale(first.stamp_path, first.current) == []
    assert stats["stamps completed, the file already held the parameters "
                 "(documents)"] == 1


def test_a_file_without_the_line_and_without_the_key_runs_the_whole_pass(
        tmp_path):
    """Violating the marker: nothing in the file says the parameter was read,
    so it is not `applied`."""
    world = World(tmp_path)
    world.run()
    assert len(world.calls["plan"]) == 1


def test_a_file_with_the_line_of_only_some_new_parameters_is_a_failure(
        tmp_path):
    new = ("heat_load", "planning_organisation")
    lines = _stored_lines(new)
    lines.insert(-1, '{"kind": "parameter_state", "document_id": 7, '
                     '"parameter": "heat_load", "state": "read", '
                     '"tuples": 1, "refusals": 0}')
    world = World(tmp_path, new=new, lines=lines)
    before = (world.file_bytes(), world.stamp_path.read_bytes())
    written, failed, _stats = world.run()
    assert (written, failed) == (False, 1)
    assert (world.file_bytes(), world.stamp_path.read_bytes()) == before
    assert not world.calls["plan"]


def test_a_document_whose_lists_cannot_be_closed_is_a_failure_and_untouched(
        tmp_path):
    world = World(tmp_path)
    before = world.file_bytes()
    written, failed, _stats = world.run(document_spec=lambda did: None)
    assert (written, failed) == (False, 1) and world.file_bytes() == before
    assert not world.calls["plan"]


# ---------------------------------------------------------------------------
# What the pass asks, with the real harvester under it
# ---------------------------------------------------------------------------

class RealHarvest:
    """The run's own fieldwise harvester over a stubbed rows request and a
    stubbed field request, recording every row any coordinate is asked of."""

    def __init__(self, monkeypatch, claims, spec=SPEC, frame_axes=()):
        self.rows_seen, self.slots_asked = [], []
        monkeypatch.setattr(
            runner, "make_harvester",
            lambda *a, **kw: (lambda batch, prior=None: {
                "tuples": [dict(c) for c in claims], "status": "complete",
                "need_more": []}))

        def make_asker(image_root=None, **kw):
            def ask(shown, rows, slots, corrections=None, document_id=None,
                    usage_out=None, owner_of=None, bases=None):
                slots = slots if isinstance(slots, (list, tuple)) else [slots]
                for row in rows:
                    self.rows_seen.append(dict(row.claim))
                self.slots_asked += [s.name for s in slots]
                return {"fields": {slot.name: {"answers": {
                    row.label: (
                        {"value": "kW", "value_raw": "kW", "quote": QUOTE}
                        if slot.name == "unit"
                        else {"value": fields.UNSTATED})
                    for row in rows}} for slot in slots}}
            return ask

        monkeypatch.setattr(runner, "make_field_asker", make_asker)
        self.harvest = runner.make_fieldwise_harvester(
            spec=spec, slice_gate={}, frame_axes=frame_axes)

    def __call__(self, batches, unfinished=None):
        return [(batch, self.harvest(batch, [])) for batch in batches]


def test_the_coordinates_are_asked_only_of_new_rows(tmp_path, monkeypatch):
    """A stored file with tuples of three parameters; the pass's stub model
    answers one row. Every row any coordinate is asked of is that row, and
    not one stored tuple is ever shown to the model. Violating: reusing the
    coordinate pass's `mine` (every stored row of a parameter) would hand the
    sweeper a stored row, and the stored quote would be among those seen."""
    stored = [json.dumps({"kind": "tuple", "parameter": uri,
                          "value": 1.0 + n, "unit": "MWh/a",
                          "quote": f"| stored {uri} | {n} |",
                          "provenance": {"document_id": 7,
                                         "owner_kind": "table",
                                         "owner_id": 9}})
              for n, uri in enumerate(("energy_consumption", "emission",
                                       "planning_organisation"))]
    lines = stored + _stored_lines()[-4:]
    claim = {"source": "Q1", "value": 12, "value_raw": "12", "unit": "kW",
             "unit_raw": "kW", "quote": QUOTE}
    real = RealHarvest(monkeypatch, [claim])
    world = World(tmp_path, lines=lines)
    world.run(harvest=real)
    assert real.rows_seen, "the coordinates of the new row were asked"
    assert {r.get("quote") for r in real.rows_seen} == {QUOTE}
    assert not [r for r in real.rows_seen
                if str(r.get("quote", "")).startswith("| stored")]
    asked = set(real.slots_asked)
    assert "unit" in asked and "carrier" in asked and "sector" in asked
    assert "parameter" not in asked, (
        "the batch offers one parameter, so the unit decides it")
    written = [r for r in world.records() if r.get("kind") == "tuple"]
    assert [r["parameter"] for r in written[-1:]] == ["heat_load"]
    assert [r["quote"] for r in written[:3]] == [
        f"| stored {u} | {n} |" for n, u in enumerate(
            ("energy_consumption", "emission", "planning_organisation"))]


def test_a_unit_of_a_stored_parameter_cannot_make_a_row_of_that_parameter(
        tmp_path, monkeypatch):
    """The owner's decision for a row that derives to a stored parameter: the
    request offers the new parameter and its units only, so such a row cannot
    arise, and nothing filters it afterwards. A number in MWh/a answered by
    the model is a unit the list does not hold, and its row is refused with
    the unit as the reason, as the harvest refuses any unit no list holds."""
    claim = {"source": "Q1", "value": 241, "value_raw": "241",
             "unit": "MWh/a", "unit_raw": "MWh/a",
             "quote": "| Erdgas | 241 | MWh/a |"}
    seen = []
    monkeypatch.setattr(
        runner, "make_harvester",
        lambda *a, **kw: (lambda batch, prior=None: {
            "tuples": [dict(claim)], "status": "complete", "need_more": []}))

    def make_asker(image_root=None, **kw):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            for slot in slots:
                seen.append((slot.name, [o.label for o in slot.options]))
            return {"fields": {slot.name: {"answers": {
                row.label: {"value": fields.UNSTATED} for row in rows}}
                for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    harvest = runner.make_fieldwise_harvester(spec=SPEC, slice_gate={})
    world = World(tmp_path, text="| Erdgas | 241 | MWh/a |")
    world.run(harvest=lambda batches, unfinished=None: [
        (b, harvest(b, [])) for b in batches])
    units = [labels for name, labels in seen if name == "unit"]
    assert units and all("MWh/a" not in labels and "kW" in labels
                         for labels in units), (
        "the unit question offers the new parameter's units and no other")
    assert "parameter" not in [name for name, _labels in seen]
    added = world.records()[len(_stored_lines()) - 2:]
    assert [r["kind"] for r in added] == ["refusal", "parameter_state",
                                          "summary"], (
        "no tuple of the stored parameter, and none filtered afterwards")
    assert added[0]["reason"] == "claim names no parameter of the spec"
    assert added[0]["parameter"] is None
    assert added[1]["state"] == "unstated", (
        "a refusal that names no parameter is counted against none")


def test_a_coordinate_answer_outside_its_list_or_its_passage_is_never_read(
        tmp_path, monkeypatch):
    """The checks on a coordinate are the harvest's own, through the real
    sweeper: a closed-list answer that is not on the list is `unbacked`
    (not_an_option) and never read, an answer whose quote is in no shown
    passage is `unbacked`, and the one that is backed is read."""
    claim = {"source": "Q1", "value": 12, "value_raw": "12", "unit": "kW",
             "unit_raw": "kW", "quote": QUOTE}
    monkeypatch.setattr(
        runner, "make_harvester",
        lambda *a, **kw: (lambda batch, prior=None: {
            "tuples": [dict(claim)], "status": "complete", "need_more": []}))
    answers = {
        "unit": {"value": "kW", "value_raw": "kW", "quote": QUOTE},
        "sector": {"value": "Eine Klasse die es nicht gibt",
                   "value_raw": "Wärmenetz", "quote": QUOTE},
        "carrier": {"value": "OEO_00000292", "value_raw": "Erdgas",
                    "quote": "Erdgas steht in keinem Absatz dieses Plans"}}

    def make_asker(image_root=None, **kw):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            return {"fields": {slot.name: {"answers": {
                row.label: answers.get(slot.name,
                                       {"value": fields.UNSTATED})
                for row in rows}} for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    harvest = runner.make_fieldwise_harvester(spec=SPEC, slice_gate={})
    world = World(tmp_path)
    world.run(harvest=lambda batches, unfinished=None: [
        (b, harvest(b, [])) for b in batches])
    row = next(r for r in world.records() if r["kind"] == "tuple"
               and r["parameter"] == "heat_load")
    assert row["unit_state"] == fields.READ and row["unit"] == "kW"
    assert row["sector_state"] == fields.UNBACKED and row.get(
        "sector") is None, "not an entry of the list"
    assert row["carrier_state"] == fields.UNBACKED and row.get(
        "carrier") is None, "the quote is in no shown passage"


# ---------------------------------------------------------------------------
# The frame of an earlier harvest
# ---------------------------------------------------------------------------

def test_the_pairs_of_the_stored_rows_are_handed_to_the_plan(tmp_path):
    """The stored pairs, as stored: keyed by the index they stood under. A
    pair no stored row carries is not made up."""
    frame = fields.frame_slots(SPEC, ("scenario", "year"))
    rows = [json.dumps(_frame_row(2, "target", 2045)),
            json.dumps(_frame_row(5, "trend", 2030)),
            json.dumps(_frame_row(5, "trend", 2030, value=4.0))]
    lines = rows + _stored_lines()[-4:]
    world = World(tmp_path, lines=lines)
    world.run(frame_axes=frame, frame_names=["scenario", "year"])
    [call] = world.calls["plan"]
    assert sorted(call["stored_pairs"]) == [2, 5]
    assert call["stored_pairs"][5]["year"] == 2030
    entry = world.stamp()["producers"][-1]
    assert entry["frame"] == tp.FRAME_SEEDED


def test_an_appended_row_carries_the_index_its_pair_was_stored_under(
        tmp_path, monkeypatch):
    """The whole chain over a stored file, the run's own `plan_batches` and
    harvester under it: the pairs the stored rows carry (stored at 2 and 5, so
    with gaps) are what the frame is seeded with, the passage of the new
    parameter prints the pair stored at 5, and the row appended for it says
    `frame` and 5 on both coordinates, so the index means the same pair across
    the file. Violating: a pass that numbered the pairs again would write 1
    (its position among the pairs it handed on), and one that dropped the seed
    would find no pair for the passage and read it without one."""
    import functools
    from concurrent.futures import ThreadPoolExecutor
    frame = fields.frame_slots(SPEC, ("scenario", "year"))
    stored = [json.dumps(_frame_row(2, "target", 2045,
                                    scenario_raw="Zielszenario")),
              json.dumps(_frame_row(5, "status_quo", 2020,
                                    scenario_raw="Status quo"))]
    seen = {}

    def find_frame(sources, slots, document_id, ask, more_sources=None,
                   probes=None, start=None):
        seen["start"] = list(start or ())
        return list(start or ()), "complete", []

    monkeypatch.setattr(runner, "find_frame", find_frame)

    def inner(document_id, filename, frame=None, frame_index=0, only=()):
        source = Source("table", 8, "Tabelle 7: Status quo 2020.\n" + QUOTE,
                        {"document_id": 7, "page": 3, "title": "Tabelle 7"})
        report = DocumentReport(document_id=7)
        report.owners_harvested = 1
        return "plan", [WorkItem(7, None, source)], report, SPEC

    claim = {"source": "Q1", "value": 12, "value_raw": "12", "unit": "kW",
             "unit_raw": "kW", "quote": QUOTE}
    real = RealHarvest(monkeypatch, [claim], frame_axes=frame)
    world = World(tmp_path, lines=stored + _stored_lines()[-4:])
    with ThreadPoolExecutor(max_workers=2) as pool:
        planned = functools.partial(
            runner.plan_batches, plan=inner, plan_pool=pool,
            ask_frame=lambda *a, **k: {}, frame_axes=frame,
            more_sources=None, base_state=None, anchor_texts={})
        assert world.run(plan=planned, harvest=real, frame_axes=frame,
                         frame_names=["scenario", "year"])[:2] == (True, 0)
    assert [p["year"] for p in seen["start"]] == [2045, 2020], (
        "the stored pairs, in the order of their indices")
    row = next(r for r in world.records() if r["kind"] == "tuple"
               and r["parameter"] == "heat_load")
    assert row["scenario_window"] == ["frame", 5]
    assert row["year_window"] == ["frame", 5]
    assert row["year"] == 2020 and row["scenario"] == "status_quo"
    assert runner.stale(world.stamp_path, world.current) == []


def test_a_profile_without_a_frame_hands_the_plan_no_pair(tmp_path):
    world = World(tmp_path)
    world.run()
    assert world.calls["plan"][0]["stored_pairs"] is None


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def test_the_document_loop_counts_a_failed_document_and_adds_the_counts(
        tmp_path):
    """The pass is what the run's loop calls per document: its counts add up
    over documents, and a failed document is a failure the exit code sees."""
    world = World(tmp_path)
    deps = world.deps()
    run = tp.DocumentPass(tmp_path, SPEC, world.current, deps)
    assert run(7, "plan.pdf") == (True, 0)
    assert run(7, "plan.pdf") == (False, 0)
    assert run.stats["documents appended (documents)"] == 1
    assert run.stats["documents looked at (documents)"] == 2
    (tmp_path / "b").mkdir()
    broken = World(tmp_path / "b", model=Model(unserved=True))
    run = tp.DocumentPass(tmp_path / "b", SPEC, broken.current,
                          broken.deps())
    assert run(7, "plan.pdf") == (False, 1)


def test_documents_without_a_harvest_file_are_left_to_the_harvest(tmp_path):
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    kept, missing = tp.with_harvest([(1, "a.pdf"), (2, "b.pdf")], tmp_path)
    assert kept == [(1, "a.pdf")] and missing == 1


def test_no_closure_in_the_new_module_reads_a_name_bound_after_it():
    """The guard of `test_extraction_reasons` runs over every module of the
    package; it is run here on this one alone, and it still finds the bug it
    is there for."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "reasons_guard", Path(__file__).parent / "test_extraction_reasons.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert guard.late_bound(Path(tp.__file__)) == []
    assert guard.late_bound(Path(runner.__file__)) == []
