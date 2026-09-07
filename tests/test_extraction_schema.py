"""The published shape of the harvest, held to what the run really writes.

A schema is only worth having if it fails when the code moves. So it is
generated from the spec and checked in, and these tests run the real dry-run
path, take the tuples that come out of the real verifier, and validate them.
A key added to a row without a line in the schema is a failing test here, not
a document that quietly stops describing the thing it names.

The kg half is checked the same way: every predicate the spec's `kg` blocks
promise is a predicate the serializer really writes into the Turtle, read back
out of the Turtle rather than out of a second copy of the list.

No model, no GPU.
"""
import json
from pathlib import Path

import jsonschema
import pytest

from docpipe.extraction import runner
from docpipe.extraction.pipeline import DocumentReport, fold_batch
from docpipe.extraction.schema import (SCHEMA_NAME, build, schema_path,
                                       serialize)
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
VALIDATOR = jsonschema.Draft202012Validator


def _profiles():
    return sorted(p.parent.name for p in PROFILES.glob("*/extraction_spec.json"))


@pytest.fixture(params=_profiles())
def profile(request, monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", request.param)
    spec_file = PROFILES / request.param / "extraction_spec.json"
    return request.param, load_spec(json.loads(
        spec_file.read_text(encoding="utf-8")))


def _tuples(monkeypatch, spec):
    """Tuples the way a run really writes them.

    The real field-wise harvester, over a batch that fixes no parameter --
    which is the shape every plan builds -- with the two model calls stubbed
    to answer the profile's own example. Not a stored fixture: a fixture pins
    the shape of the day it was taken, and whether the shape moved is the
    whole question.
    """
    from docpipe.extraction import fields
    from docpipe.extraction.pipeline import Source, WorkItem, group_items
    from tests.test_extraction_fieldwise import (_example_tuples, _fieldwise,
                                                 _value_reply)
    out = []
    for parameter in spec.parameters:
        text = (parameter.example or {}).get("source") or ""
        batch = group_items([WorkItem(7, None, Source(
            "table", 1, text, {"document_id": 7, "page": 1}))],
            max_sources=runner.BATCH_SOURCES)[0]
        expected = _example_tuples(parameter)

        def answers(slot, rows, _expected=expected, _text=text,
                    _parameter=parameter):
            reply = {}
            for row, want in zip(rows, _expected):
                if slot.name == "parameter":
                    # Which parameter a wording belongs to has no unit to
                    # follow, so it is a real question and the stub answers
                    # it. The two profiles differ here: kwp derives it.
                    reply[row.label] = {"value": _parameter.label,
                                        "value_raw": _parameter.label,
                                        "quote": row.claim.get("quote", "")}
                    continue
                given = want.get(slot.name)
                if given is None:
                    continue
                wording = want.get(f"{slot.name}_raw") or str(given)
                at = _text.find(str(wording))
                quote = (_text[max(0, at - 60):at + len(str(wording)) + 60]
                         if at != -1 else row.claim.get("quote", ""))
                reply[row.label] = {"value": given, "value_raw": wording,
                                    "quote": quote}
            return {"answers": reply}

        harvest, _asked = _fieldwise(monkeypatch, spec, _value_reply(
            parameter, batch.label(0)), answers)
        report = DocumentReport(document_id=7)
        fold_batch(batch, harvest(batch), report, spec=spec)
        out += report.tuples
    # Not every parameter of every profile can be answered by a stub: which
    # parameter a WORDING belongs to has no unit to follow and no word in the
    # passage to cite, so a text parameter legitimately comes back refused
    # here. What this helper owes is real rows, and the numeric parameters
    # give them.
    assert out, "the profile's example harvested to nothing"
    return out


def test_all_three_schemas_are_valid_json_schema(profile):
    _name, spec = profile
    for part, schema in build(spec).items():
        VALIDATOR.check_schema(schema)
        assert schema["$id"].endswith(
            {"harvest": "harvest-line", "stamp": "stamp",
             "trace": "trace-record"}[part])


def test_the_checked_in_schema_is_the_generated_one(profile):
    """It is generated, so it can be regenerated; the checked-in copy exists
    so a reader outside this repository has something to read. The two being
    the same is what makes that copy worth reading."""
    name, spec = profile
    path = schema_path(name)
    assert path.is_file(), (
        f"profiles/{name}/{SCHEMA_NAME} missing — "
        f"python -m docpipe.extraction.schema {name} --write")
    assert path.read_text(encoding="utf-8") == serialize(build(spec)), (
        f"profiles/{name}/{SCHEMA_NAME} is stale — "
        f"python -m docpipe.extraction.schema {name} --write")


def test_what_the_harvest_really_writes_validates(profile, monkeypatch):
    """Not a stored fixture: a fixture pins the shape of the day it was
    taken, and this is exactly the question of whether the shape moved."""
    _name, spec = profile
    validator = VALIDATOR(build(spec)["harvest"])
    for row in _tuples(monkeypatch, spec):
        line = {"kind": "tuple", **row}
        errors = list(validator.iter_errors(line))
        assert not errors, (
            f"{jsonschema.exceptions.best_match(errors).message[:200]}\n"
            f"{json.dumps(line, ensure_ascii=False)[:400]}")


def test_every_coordinate_a_row_carries_is_described(profile):
    """A key with no description is a key nobody outside this repository can
    read. That is the whole complaint the schema answers."""
    _name, spec = profile
    harvest = build(spec)["harvest"]
    for parameter in spec.parameters:
        props = harvest["$defs"][f"tuple_{parameter.uri}"]["properties"]
        for name, prop in props.items():
            assert prop.get("description") or prop.get("$ref") or \
                prop.get("const") is not None, f"{parameter.uri}.{name}"
        for axis_name, axis in parameter.axes.items():
            axis_prop = props[axis_name]
            assert axis_prop.get("x-question") == axis.question
            if axis.kg:
                assert axis_prop["x-kg"] == axis.kg
            if axis.vocabulary:
                offered = {o["uri"] for o in axis_prop["x-options"].values()}
                assert offered == set(axis.vocabulary)


@pytest.mark.parametrize("what", [
    "state missing", "read without a value", "value without a read state",
    "unknown key", "a tier that no longer exists", "unstated as a value",
    "a flag off the vocabulary", "a four-character quote",
])
def test_a_broken_row_is_refused(what, monkeypatch):
    """Eight ways a row can be wrong, each rejected. A schema that accepts
    everything is a schema that says nothing: the four-character quote is
    real — three of Kassel's year readings were the bare year."""
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    good = {"kind": "tuple", **_tuples(monkeypatch, spec)[0]}
    validator = VALIDATOR(build(spec)["harvest"])
    assert validator.is_valid(good), "the control itself has to be valid"
    broken = {
        "state missing": {k: v for k, v in good.items() if k != "year_state"},
        "read without a value": {**good, "year_state": "read", "year": None},
        "value without a read state": {**good, "year_state": "unanswered",
                                       "year": 2030},
        "unknown key": {**good, "jahr": 2030},
        "a tier that no longer exists": {**good, "tier": "pdf_verified"},
        "unstated as a value": {**good, "carrier_state": "read",
                                "carrier": "out:unstated"},
        "a flag off the vocabulary": {**good, "flags": ["guessed:year"]},
        "a four-character quote": {**good, "year_state": "read", "year": 2030,
                                   "year_quote": "2030"},
    }[what]
    assert not validator.is_valid(broken)


def test_the_stamp_the_runner_writes_validates():
    stamp = runner._stamp_current("a" * 64, "b" * 16)
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    errors = list(VALIDATOR(build(spec)["stamp"]).iter_errors(stamp))
    assert not errors, [e.message for e in errors]
    # And it is the resume's whole basis, so a missing key is not tolerated.
    assert not VALIDATOR(build(spec)["stamp"]).is_valid(
        {k: v for k, v in stamp.items() if k != "spec"})


def test_the_kg_block_names_the_predicates_the_serializer_writes(tmp_path):
    """The spec says what each coordinate becomes; the serializer writes it.
    Read the promise out of the spec and the fact out of the Turtle, so the
    two cannot be kept in step by being copied from one another."""
    import re
    from tests.test_kwp_extraction import one_plan_turtle
    turtle = one_plan_turtle(tmp_path)
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    written = set(re.findall(r"oeo:(OEO_\d+)\s", turtle))
    promised = set()
    for parameter in spec.parameters:
        for key in ("number", "unit"):
            block = (parameter.kg or {}).get(key) or {}
            if block.get("predicate"):
                promised.add(block["predicate"])
        for axis in parameter.axes.values():
            block = axis.kg or {}
            if block.get("role") == "edge":
                promised.add(block["predicate"])
    assert promised, "the spec promises no predicate at all"
    missing = promised - written
    assert not missing, f"promised in the spec, absent from the Turtle: {missing}"


def test_a_row_the_schema_refuses_is_written_and_counted(monkeypatch, tmp_path):
    """Counted and traced, never blocking. The harvest is the durable
    artifact and a row the schema does not recognise is still evidence;
    refusing to write it would turn a documentation defect into a data loss.
    What it must not do is pass unnoticed."""
    from docpipe.extraction import trace
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    good, *_rest = _tuples(monkeypatch, spec)
    report = DocumentReport(document_id=7)
    report.tuples = [dict(good), dict(good, jahr=2030)]

    events = []
    monkeypatch.setattr(trace, "event",
                        lambda name, doc, **fields: events.append(
                            (name, fields)))
    from docpipe.extraction.runner import check_against_schema
    assert check_against_schema(report, "plan", spec) == 1
    assert [k for k, _f in events] == ["invalid"]
    assert events[0][1]["kind"] == "tuple"
    assert "jahr" in events[0][1]["detail"]

    # And the row is still written: the file is the audit trail.
    from docpipe.extraction.pipeline import write_report
    out = tmp_path / "plan.jsonl"
    write_report(report, out)
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_the_invalid_event_is_itself_in_the_trace_schema():
    """A check that writes an event no schema describes has moved the
    problem rather than solved it."""
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    validator = VALIDATOR(build(spec)["trace"])
    assert validator.is_valid({"t": "invalid", "doc": 7, "kind": "tuple",
                               "where": "year_quote", "why": "minLength",
                               "detail": "'2030' is too short"})
    assert not validator.is_valid({"t": "invalid", "doc": 7, "kind": "row",
                                   "where": "", "why": "", "detail": ""})


def test_two_profiles_in_one_process_are_checked_against_their_own_schema():
    """The validators are compiled once and cached, and a cache with no key
    is a cache for whichever profile ran first: every row of the second one
    then comes back invalid against a schema that never described it."""
    from docpipe.extraction.runner import _harvest_validators
    kwp = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    other = load_spec(PROFILES / "scenarios" / "extraction_spec.json")
    for first, second in ((kwp, other), (other, kwp)):
        _harvest_validators(first)
        got = _harvest_validators(second)
        assert set(got) == {("refusal", None)} | {
            ("tuple", p.uri) for p in second.parameters}
