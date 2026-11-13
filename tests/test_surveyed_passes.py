"""The two passes over a stored harvest of a run that harvests from the survey
(`surveyed.py`) read only what nothing has read, and write nothing unless they
read it.

holes_of: a refusal that carries `_harvest_failed` and `_parameter` is a
reading hole of that parameter at its owner, one that carries `_harvest_failed`
and no `_parameter` is a passage hole, and one without `_harvest_failed` is
neither.

surveyed_owners: it reads the answers of the whole survey of the document AND
of every scoped one, an owner one of them left unanswered and another answered
is answered, AND the files of another document are not read.

append_unread: a passage no stored survey answered is surveyed again AND one
that was answered is not; a passage hole is surveyed again; a reading hole is
read again for its parameter alone AND with the frame tuples its stored survey
gave the passage; the rows are appended after the stored lines, which stay
byte for byte, AND point at the new producer entry, whose pass is
`topup_rest.PASS`; a document with nothing unread gets that producer entry AND
no new line; a document already read to its end is not read; a document
without a harvest file is not read; a document one of whose requests ended on
a 429 is written nothing.

append_parameters: a parameter the spec gained since the stamp was written is
read through the take with its uri, its rows AND its parameter_state line are
appended AND the stamp gains its keys AND a producer entry names the
parameter; a document with no new parameter is not read AND nothing is
written; a document whose take ended with a request on a 429 is written
nothing AND counts a failure; a row whose quote stands in no shown passage is
no tuple.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import pytest

from docpipe.extraction import pipeline, runner, surveyed, topup_parameter, \
    topup_rest
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.survey import Answer, Found

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
OFFICE = SPEC.by_uri["planning_organisation"]
URI = OFFICE.uri
DOC = 7
NAME = "plan"

ONE, TWO, THREE = ("section", 1), ("section", 2), ("section", 3)
TEXT = {
    ONE: "Titel\nWärmeplanung der Stadt Musterstadt.",
    TWO: "Impressum\nAuftragnehmer: Muster Ingenieurbüro GmbH, Bearbeitung: "
         "M. Wagner.",
    THREE: "Anhang\nDie Karten stehen am Ende.",
}
QUOTE = "Auftragnehmer: Muster Ingenieurbüro GmbH, Bearbeitung"


@pytest.fixture(autouse=True)
def _unserved():
    runner.UNSERVED.clear()
    yield
    runner.UNSERVED.clear()


def source(key):
    return pipeline.Source(key[0], key[1], TEXT[key], {"document_id": DOC})


def every_passage(document_id=DOC):
    return [source(key) for key in (ONE, TWO, THREE)]


def office_answer(key=TWO, quote=QUOTE, value="Muster Ingenieurbüro"):
    """(batch, reply) of the reading of *key* for the office, claiming *quote*
    and a coordinate that was read, so that a row has one to point from."""
    batch = pipeline.Batch(DOC, OFFICE,
                           [pipeline.WorkItem(DOC, OFFICE, source(key))])
    claim = {"source": "Q1", "value": value, "quote": quote,
             "subject_state": "read", "subject": "Planungsbüro"}
    return batch, {"tuples": [claim]}


def refusal(owner, why="no_answer", parameter=None, failed=True):
    claim = {"_why": why, "source": "Q1"}
    if failed:
        claim["_harvest_failed"] = True
    if parameter:
        claim["_parameter"] = parameter
    return {"kind": "refusal", "parameter": None,
            "reason": "claim names no parameter of the spec", "claim": claim,
            "owner": list(owner)}


def stored_tuple():
    return {"kind": "tuple", "parameter": "emission", "value": 300,
            "unit": "t CO2", "quote": "rund 300 t CO2",
            "provenance": {"owner_kind": "section", "owner_id": 1}}


def write_harvest(folder, *records):
    path = folder / f"{NAME}.jsonl"
    path.write_bytes(("\n".join(json.dumps(r, ensure_ascii=False)
                                for r in records) + "\n").encode("utf-8"))
    return path


def write_stamp(folder, stamp):
    path = folder / f"{NAME}.stamp.json"
    path.write_text(json.dumps(stamp), encoding="utf-8")
    return path


def read_stamp(folder):
    return json.loads((folder / f"{NAME}.stamp.json").read_text("utf-8"))


def write_survey(folder, answered=(), unanswered=(), scope="", document=DOC):
    (folder / "survey").mkdir(exist_ok=True)
    name = f"{document}.{scope}.json" if scope else f"{document}.json"
    entries = [{"owner": list(key), "parameters": [URI], "quote": "q",
                "tuples": tuples} for key, tuples in answered]
    (folder / "survey" / name).write_text(json.dumps({
        "answers": entries, "unanswered": [list(k) for k in unanswered]}),
        encoding="utf-8")


def lines_of(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def taken(*answered, passages=1, replies=1, sources_of=None):
    return surveyed.Taken(Found(True), answered=list(answered),
                          replies=replies, passages=passages,
                          sources_of=sources_of or {})


# -- holes_of ----------------------------------------------------------------

def test_a_refusal_with_a_parameter_is_a_reading_hole_without_one_a_passage_hole():
    passages, readings = surveyed.holes_of([
        refusal(ONE, parameter=URI), refusal(TWO)])
    assert readings == {ONE: {URI}}
    assert passages == {TWO}


def test_a_refusal_that_is_no_sentinel_is_neither_hole():
    passages, readings = surveyed.holes_of([
        refusal(ONE, parameter=URI, failed=False), refusal(TWO, failed=False)])
    assert passages == set() and readings == {}


def test_a_sentinel_without_a_two_part_owner_is_neither_hole():
    bad = refusal(ONE)
    bad["owner"] = ["section"]
    assert surveyed.holes_of([bad]) == (set(), {})


# -- surveyed_owners ---------------------------------------------------------

def test_the_whole_and_the_scoped_surveys_of_the_document_are_read(tmp_path):
    write_survey(tmp_path, answered=[(ONE, {})], unanswered=[TWO, THREE])
    write_survey(tmp_path, answered=[(TWO, {})], unanswered=[THREE],
                 scope="found")
    answers, unanswered = surveyed.surveyed_owners(tmp_path, DOC)
    assert set(answers) == {ONE, TWO}
    assert answers[ONE].parameters == [URI]
    # TWO was left unanswered by one survey and answered by the other.
    assert unanswered == {THREE}


def test_an_owner_every_survey_left_unanswered_stays_unanswered(tmp_path):
    write_survey(tmp_path, unanswered=[TWO])
    write_survey(tmp_path, unanswered=[TWO], scope="found")
    assert surveyed.surveyed_owners(tmp_path, DOC) == ({}, {TWO})


def test_the_files_of_another_document_are_not_read(tmp_path):
    write_survey(tmp_path, answered=[(ONE, {})])
    write_survey(tmp_path, answered=[(THREE, {})], unanswered=[TWO],
                 document=70)
    write_survey(tmp_path, answered=[(THREE, {})], scope="found",
                 document=70)
    answers, unanswered = surveyed.surveyed_owners(tmp_path, DOC)
    assert set(answers) == {ONE} and unanswered == set()


# -- append_unread -----------------------------------------------------------

def unread_deps(calls, reply=None, note_429=False):
    def take(document_id, passages, also):
        calls.append((document_id, [(s.owner_kind, s.owner_id)
                                    for s in passages], also))
        if note_429:
            runner.UNSERVED.note(document_id)
        return reply if reply is not None else taken(office_answer())
    return {"take": take, "passages_of": every_passage, "locate": None,
            "spec": SPEC}


def started(folder, *records, producers=None):
    path = write_harvest(folder, *records)
    write_stamp(folder, {"producers": producers or [{"pass": "harvest"}]})
    return path


def test_a_passage_no_survey_answered_is_surveyed_again_an_answered_one_is_not(
        tmp_path):
    path = started(tmp_path, stored_tuple())
    write_survey(tmp_path, answered=[(ONE, {})])
    before = path.read_bytes()
    calls = []
    written, failed, _ = surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))
    assert (written, failed) == (True, 0)
    assert [owners for _d, owners, _a in calls] == [[TWO, THREE]]
    # The rows follow the stored lines, which stay byte for byte.
    now = path.read_bytes()
    assert now.startswith(before) and len(now) > len(before)
    appended = lines_of(path)[len(before.splitlines()):]
    assert [r["kind"] for r in appended] == ["tuple", "summary"]
    assert appended[0]["parameter"] == URI


def test_a_document_every_passage_of_which_was_answered_is_surveyed_again_not(
        tmp_path):
    path = started(tmp_path, stored_tuple())
    write_survey(tmp_path, answered=[(ONE, {}), (TWO, {}), (THREE, {})])
    before = path.read_bytes()
    calls = []
    written, failed, _ = surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))
    assert calls == [] and (written, failed) == (True, 0)
    # It gets its producer entry and no new line.
    assert path.read_bytes() == before
    assert read_stamp(tmp_path)["producers"][-1]["pass"] == topup_rest.PASS


def test_a_passage_hole_is_surveyed_again_though_a_survey_answered_it(tmp_path):
    started(tmp_path, stored_tuple(), refusal(TWO))
    write_survey(tmp_path, answered=[(ONE, {}), (TWO, {}), (THREE, {})])
    calls = []
    surveyed.append_unread(DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))
    assert [owners for _d, owners, _a in calls] == [[TWO]]
    assert calls[0][2].answers == {}


def test_a_reading_hole_is_read_again_for_its_parameter_with_the_frame_tuples(
        tmp_path):
    started(tmp_path, stored_tuple(), refusal(ONE, parameter=URI))
    frame = {"year": 2022, "scenario": "Ist"}
    write_survey(tmp_path, answered=[(ONE, {"frame": [frame]}), (TWO, {}),
                                     (THREE, {})])
    calls = []
    written, failed, _ = surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))
    assert (written, failed) == (True, 0)
    [(_d, owners, also)] = calls
    # The passage is not surveyed again, only its reading is repeated.
    assert owners == []
    assert set(also.answers) == {ONE}
    assert also.answers[ONE].parameters == [URI]
    assert also.answers[ONE].tuples == {"frame": [frame]}


def test_a_reading_hole_in_a_passage_surveyed_again_whole_is_not_listed_twice(
        tmp_path):
    started(tmp_path, stored_tuple(), refusal(TWO, parameter=URI),
            refusal(TWO))
    write_survey(tmp_path, answered=[(ONE, {}), (TWO, {}), (THREE, {})])
    calls = []
    surveyed.append_unread(DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))
    [(_d, owners, also)] = calls
    assert owners == [TWO] and also.answers == {}


def test_the_new_rows_point_at_the_entry_of_the_pass(tmp_path):
    path = started(tmp_path, stored_tuple(),
                   producers=[{"pass": "harvest"}, {"pass": "remap"}])
    write_survey(tmp_path, answered=[(ONE, {})])
    surveyed.append_unread(DOC, f"{NAME}.pdf", tmp_path, unread_deps([]))
    producers = read_stamp(tmp_path)["producers"]
    assert [p["pass"] for p in producers] == ["harvest", "remap",
                                              topup_rest.PASS]
    row = next(r for r in lines_of(path) if r.get("parameter") == URI)
    assert row["subject_producer"] == 2


def test_a_row_whose_quote_stands_in_no_passage_is_no_new_tuple(tmp_path):
    path = started(tmp_path, stored_tuple())
    write_survey(tmp_path, answered=[(ONE, {})])
    false = taken(office_answer(quote="Auftragnehmer: Erfundenes Büro AG",
                                value="Erfundenes Büro"))
    surveyed.append_unread(DOC, f"{NAME}.pdf", tmp_path,
                           unread_deps([], reply=false))
    assert [r for r in lines_of(path) if r.get("parameter") == URI
            and r["kind"] == "tuple"] == []


def test_a_document_read_to_its_end_is_not_read_again(tmp_path):
    path = started(tmp_path, stored_tuple(),
                   producers=[{"pass": "harvest"}, {"pass": topup_rest.PASS}])
    write_survey(tmp_path, answered=[(ONE, {})])
    before = path.read_bytes()
    calls = []
    assert surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))[:2] == (False, 0)
    assert calls == [] and path.read_bytes() == before


def test_a_document_read_by_another_pass_only_is_read(tmp_path):
    started(tmp_path, stored_tuple(),
            producers=[{"pass": "harvest"}, {"pass": "remap"}])
    write_survey(tmp_path, answered=[(ONE, {})])
    calls = []
    surveyed.append_unread(DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))
    assert len(calls) == 1


def test_a_document_without_a_harvest_file_is_not_read(tmp_path):
    write_survey(tmp_path, answered=[(ONE, {})])
    calls = []
    assert surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))[:2] == (False, 0)
    assert calls == []


def test_a_document_nothing_says_was_read_is_not_read(tmp_path):
    path = started(tmp_path, stored_tuple())
    before = path.read_bytes()
    calls = []
    assert surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps(calls))[:2] == (False, 0)
    assert calls == [] and path.read_bytes() == before


def test_a_request_that_ended_on_a_429_writes_nothing_and_counts_a_failure(
        tmp_path):
    path = started(tmp_path, stored_tuple())
    write_survey(tmp_path, answered=[(ONE, {})])
    before, stamp = path.read_bytes(), read_stamp(tmp_path)
    written, failed, _ = surveyed.append_unread(
        DOC, f"{NAME}.pdf", tmp_path, unread_deps([], note_429=True))
    assert (written, failed) == (False, 1)
    assert path.read_bytes() == before and read_stamp(tmp_path) == stamp


# -- append_parameters -------------------------------------------------------

CURRENT = runner._stamp_current("sha", "", SPEC)


def params_started(folder, *records, gained=True):
    """A harvest whose stamp predates the office parameter."""
    old = topup_parameter.without(SPEC, [OFFICE]) if gained else SPEC
    path = write_harvest(folder, *records)
    write_stamp(folder, {**runner._stamp_current("sha", "", old),
                         "producers": [{"pass": "harvest"}]})
    return path


def param_deps(calls, reply=None, note_429=False):
    def take(document_id, uris):
        calls.append((document_id, list(uris)))
        if note_429:
            runner.UNSERVED.note(document_id)
        return reply if reply is not None else taken(
            office_answer(), sources_of={URI: {TWO}})
    return {"document_spec": lambda _id: SPEC, "take": take, "locate": None,
            "frame_names": (), "dynamic_ok": True}


def test_a_gained_parameter_is_read_and_appended_with_its_state_and_stamp(
        tmp_path):
    path = params_started(tmp_path, stored_tuple())
    before = path.read_bytes()
    calls = []
    written, failed, _ = surveyed.append_parameters(
        DOC, f"{NAME}.pdf", tmp_path, SPEC, CURRENT, param_deps(calls))
    assert (written, failed) == (True, 0)
    assert calls == [(DOC, [URI])]
    now = path.read_bytes()
    assert now.startswith(before)
    appended = lines_of(path)[len(before.splitlines()):]
    kinds = [r["kind"] for r in appended]
    assert kinds == ["tuple", "parameter_state", "summary"]
    assert appended[0]["parameter"] == URI
    assert appended[1]["parameter"] == URI
    stamp = read_stamp(tmp_path)
    assert f"parameter/{URI}" in stamp
    assert stamp[f"parameter/{URI}"] == CURRENT[f"parameter/{URI}"]
    entry = stamp["producers"][-1]
    assert entry["parameters"] == [URI]
    assert entry["pass"] == topup_parameter.PASS
    assert appended[0]["subject_producer"] == 1


def test_a_document_that_has_every_parameter_is_not_read_and_not_written(
        tmp_path):
    path = params_started(tmp_path, stored_tuple(), gained=False)
    before, stamp = path.read_bytes(), read_stamp(tmp_path)
    calls = []
    written, failed, _ = surveyed.append_parameters(
        DOC, f"{NAME}.pdf", tmp_path, SPEC, CURRENT, param_deps(calls))
    assert (written, failed) == (False, 0)
    assert calls == []
    assert path.read_bytes() == before and read_stamp(tmp_path) == stamp


def test_a_request_that_ended_on_a_429_writes_no_line_and_no_key(tmp_path):
    path = params_started(tmp_path, stored_tuple())
    before, stamp = path.read_bytes(), read_stamp(tmp_path)
    written, failed, _ = surveyed.append_parameters(
        DOC, f"{NAME}.pdf", tmp_path, SPEC, CURRENT,
        param_deps([], note_429=True))
    assert (written, failed) == (False, 1)
    assert path.read_bytes() == before and read_stamp(tmp_path) == stamp
    assert f"parameter/{URI}" not in read_stamp(tmp_path)


def test_a_reading_with_a_quote_in_no_passage_appends_no_tuple_for_it(tmp_path):
    path = params_started(tmp_path, stored_tuple())
    false = taken(office_answer(quote="Auftragnehmer: Erfundenes Büro AG",
                                value="Erfundenes Büro"),
                  sources_of={URI: {TWO}})
    surveyed.append_parameters(DOC, f"{NAME}.pdf", tmp_path, SPEC, CURRENT,
                               param_deps([], reply=false))
    assert [r for r in lines_of(path) if r.get("parameter") == URI
            and r["kind"] == "tuple"] == []


def test_a_parameter_read_by_a_pass_without_any_reply_writes_nothing(tmp_path):
    path = params_started(tmp_path, stored_tuple())
    before = path.read_bytes()
    silent = taken(replies=0, passages=3)
    written, failed, _ = surveyed.append_parameters(
        DOC, f"{NAME}.pdf", tmp_path, SPEC, CURRENT,
        param_deps([], reply=silent))
    assert (written, failed) == (False, 1)
    assert path.read_bytes() == before
