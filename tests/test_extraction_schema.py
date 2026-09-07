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


def kwp_promises(spec) -> set:
    """Every predicate a kwp kg block names, qualified.

    Every place a block can hold one: the value's number and unit, the edge a
    parameter hangs off the plan by, every role=edge axis, the edge a parent
    axis hangs its container by, and the one inside a map entry. The last two
    were written as prose inside a `note` and reached no reader at all.
    """
    from profiles.kwp.kg import PREFIXES
    from docpipe.extraction.spec import kg_name
    out = set()
    for parameter in spec.parameters:
        blocks, stack = [], [parameter.kg or {}]
        stack += [axis.kg or {} for axis in parameter.axes.values()]
        while stack:
            block = stack.pop()
            blocks.append(block)
            stack.extend(v for v in block.values() if isinstance(v, dict))
        for block in blocks:
            if block.get("predicate"):
                out.add(kg_name(block, PREFIXES))
    return out


def test_the_kg_block_names_the_predicates_the_serializer_writes(tmp_path):
    """The spec says what each coordinate becomes; the serializer writes it.
    Read the promise out of the spec and the fact out of the Turtle, so the
    two cannot be kept in step by being copied from one another.

    Over every namespace, not just oeo: since the map entries were opened up
    the spec also promises obo:BFO_0000050, and a collector that only reads
    oeo: would call that kept without looking.
    """
    import re
    from tests.test_kwp_extraction import full_turtle
    turtle = full_turtle(tmp_path)
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    written = set(re.findall(r"\b([a-z]+:[A-Za-z]+_\d+)\s", turtle))
    promised = kwp_promises(spec)
    assert len(promised) == 9, sorted(promised)
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
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3                       # two tuples + the summary
    assert json.loads(lines[-1])["kind"] == "summary"


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
        assert set(got) == {("refusal", None), ("summary", None)} | {
            ("tuple", p.uri) for p in second.parameters}


# ---------------------------------------------------------------------------
# The summary line
# ---------------------------------------------------------------------------
def test_the_summary_line_is_the_last_one_and_matches_its_own_branch(
        monkeypatch, tmp_path):
    """A corpus of 1.082 plans is not read tuple by tuple, and "how much of
    this plan can I use" has no answer in a file of 559 rows. The line that
    answers it is only worth writing if everyone downstream can read it, so
    it is a branch of the published schema like the other two."""
    from docpipe.extraction.pipeline import DocumentReport, write_report
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    good, *_rest = _tuples(monkeypatch, spec)
    report = DocumentReport(document_id=7)
    report.tuples = [dict(good), dict(good)]
    report.refusals = [{"parameter": None, "reason": "value is not a number",
                        "claim": {}, "owner": ["table", 1]}]

    out = tmp_path / "plan.jsonl"
    write_report(report, out)
    rows = [json.loads(line) for line
            in out.read_text(encoding="utf-8").strip().splitlines()]
    summary = rows[-1]
    assert summary["kind"] == "summary"
    assert summary["document_id"] == 7
    assert summary["tuples"] == 2 and summary["refusals"] == 1
    assert sum(summary["levels"].values()) == 2

    validator = VALIDATOR({**build(spec)["harvest"]})
    for row in rows:
        assert validator.is_valid(row), row


def test_the_summary_names_only_reasons_the_schema_knows():
    """The reasons are a closed list precisely so they can be counted. A
    reason the schema does not describe is a column nobody downstream can
    add up, and "nonlocal" without its axis is exactly that."""
    spec = load_spec(PROFILES / "kwp" / "extraction_spec.json")
    validator = VALIDATOR({**build(spec)["harvest"]})
    line = {"kind": "summary", "document_id": 7, "tuples": 1, "refusals": 0,
            "levels": {"A": 0, "B": 0, "C": 1}, "image_origin": 0,
            "reasons": {"nonlocal:year": 1}}
    assert validator.is_valid(line)
    assert validator.is_valid({**line, "reasons": {"exhausted:carrier": 1,
                                                   "conflict": 1,
                                                   "page_transcribed": 1,
                                                   "repaired": 0}})
    for bad in ({"nonlocal": 1}, {"nonlocal:Jahr": 1}, {"erfunden": 1},
                {"nonlocal:year extra": 1}):
        assert not validator.is_valid({**line, "reasons": bad}), bad
    # A level the schema does not list is a level nobody can act on.
    assert not validator.is_valid({**line, "levels": {"A": 0, "B": 0, "C": 1,
                                                      "D": 0}})
    assert not validator.is_valid({**line, "levels": {"A": 0, "B": 0}})


def test_a_category_parameter_publishes_the_list_it_answers_from():
    """`value_uri` said "the entry of the parameter's own vocabulary" and the
    schema never showed what that vocabulary is. Unseen until scenarios,
    because kwp has no category parameter at all -- so the profile that would
    have reported the gap does not have the shape.

    The three cases read differently on purpose: a closed list is published,
    a dynamic one says the profile fills it per document, and a text
    parameter says it never writes the key.
    """
    schema = json.loads((PROFILES / "scenarios"
                         / "extraction_schema.json").read_text(encoding="utf-8"))
    defs = schema["harvest"]["$defs"]

    closed = defs["tuple_scenario_type"]["properties"]["value_uri"]
    assert len(closed["enum"]) == 19, "eighteen entries and null"
    assert None in closed["enum"]
    options = closed["x-options"]
    assert len(options) == 18
    assert options["policy scenario"]["meaning"].startswith("A policy scenario")
    assert options["target driven scenario"]["spellings"] == [
        "normative scenario", "backcasting scenario", "Zielszenario"]
    # The question belongs on `value`, not here: it would be the parameter's
    # description a second time, under a key claiming to be a question.
    assert "x-question" not in closed

    dynamic = defs["tuple_scenario_label"]["properties"]["value_uri"]
    assert "enum" not in dynamic and "x-options" not in dynamic
    assert "per document" in dynamic["description"]

    text = defs["tuple_publication_title"]["properties"]["value_uri"]
    assert "enum" not in text and "x-options" not in text
    assert "never writes the key" in text["description"]


def test_no_description_of_the_harvest_is_shaped_like_one_corpus():
    """The generated schema is one file per profile out of one generator, so a
    sentence about heat plans lands in the AR6 profile's schema too. Five did:
    an AR6 paper has no AGS, mints no heat plan IRI, and its running text is
    not "the plan's text". Held on the ar6 side, where the mismatch is."""
    blob = (PROFILES / "scenarios" / "extraction_schema.json").read_text(
        encoding="utf-8")
    schema = json.loads(blob)
    for kwp_shaped in ("heat plan", "AGS", "the plan's", "transcribed plan",
                       "about the plan", "x-description-de"):
        assert kwp_shaped not in blob, kwp_shaped
    # And the one occurrence that legitimately stays: a planned source is a
    # trace record kind, the same word in both profiles.
    kinds = {(r.get("properties") or {}).get("t", {}).get("const")
             for r in schema["trace"]["oneOf"]}
    assert "plan" in kinds


def test_a_stamp_key_moves_for_what_its_description_says_it_does():
    """Twice now a published key described something it does not carry: the
    `anchors` one after b15f230 (fixed in 75fa443) and the `parameter` one,
    which claimed the parameter's own vocabulary while `parameter_fingerprint`
    hashes it nowhere. A description nobody can check is a description that
    goes stale between two commits and is read as true for a year.

    So each edit is applied to a real spec and the keys that move are compared
    against the keys the descriptions claim.
    """
    import copy
    from docpipe.extraction.spec import fingerprints

    raw = json.loads((PROFILES / "scenarios" / "extraction_spec.json")
                     .read_text(encoding="utf-8"))

    def moved(edit):
        before = fingerprints(load_spec(copy.deepcopy(raw)))
        after_raw = copy.deepcopy(raw)
        edit(after_raw)
        after = fingerprints(load_spec(after_raw))
        return sorted(k for k in set(before) | set(after)
                      if before.get(k) != after.get(k))

    def a_parameter(d):
        return [p for p in d["parameters"] if p["uri"] == "scenario_type"][0]

    def reword_the_question(d):
        a_parameter(d)["description"] += " Und noch ein Satz dazu."

    def add_a_spelling(d):
        a_parameter(d)["vocabulary"][
            "https://openenergyplatform.org/ontology/oeo/OEO_00020345"][
                "spellings"].append("Suffizienzszenario")

    def reword_a_meaning(d):
        a_parameter(d)["vocabulary"][
            "https://openenergyplatform.org/ontology/oeo/OEO_00020345"][
                "definition"] = "A sufficiency scenario is something else."

    def reword_an_axis(d):
        a_parameter(d)["axes"]["scenario"]["question"] += " Bitte genau."

    # The parameter key: its own question, and NOT the list it answers from.
    assert moved(reword_the_question) == ["parameter/scenario_type"]
    # The list has keys of its own -- spellings and meanings both.
    assert moved(add_a_spelling) == ["value/scenario_type"]
    assert moved(reword_a_meaning) == ["value/scenario_type"]
    # And an axis moves its axis and nothing else.
    assert moved(reword_an_axis) == ["axis/scenario_type/scenario"]

    # The published words for those two keys, held to what just happened.
    stamp = build(load_spec(PROFILES / "scenarios" / "extraction_spec.json"))[
        "stamp"]["patternProperties"]
    parameter_doc = stamp["^parameter/[^/]+$"]["description"]
    assert "without its own list" in parameter_doc
    assert "keys of their own" in parameter_doc
    assert "the list a category parameter answers from" \
        in stamp["^value/[^/]+$"]["description"].lower()
