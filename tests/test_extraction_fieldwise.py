"""The field-wise harvest, with the model stubbed and nothing else.

The defect this replaces was silent by construction. One request asked for a
whole tuple, every coordinate was nullable, and a coordinate the model skipped
looked exactly like a coordinate the document does not state. Measured on the
204-document corpus run: 63.5% of all values carried no year, and on 13% of
those the year stood in the very quote the model had itself cited.

So the shape is no longer the model's to decide. It comes from the spec, one
request asks for the values, and one request per coordinate fills them, each
answer carrying the passage it was read in. What these tests hold to is that
contract: the skeleton is the spec's, an answer without evidence in its own
source is not written, and an answer that has it survives the same verifier
the whole-tuple path used.

No GPU, no database.
"""
import json
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import (DocumentReport, Source, WorkItem,
                                         fold_fieldwise, group_items,
                                         merge_field, rows_from_reply)
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _profiles():
    return sorted(p.parent.name for p in PROFILES.glob("*/extraction_spec.json"))


@pytest.fixture(params=_profiles())
def profile(request, monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", request.param)
    spec_file = PROFILES / request.param / "extraction_spec.json"
    return request.param, load_spec(json.loads(spec_file.read_text(encoding="utf-8")))


def _batch(parameter, sources=2):
    text = (parameter.example or {}).get("source") or ""
    items = [WorkItem(7, parameter, Source("table", n, text,
                                           {"document_id": 7, "page": n}))
             for n in range(sources)]
    return group_items(items, max_sources=runner.BATCH_SOURCES)[0]


def _example_tuples(parameter):
    """The example's tuples with its defaults folded in, as one flat list."""
    example = parameter.example or {}
    defaults = {k: v for k, v in (example.get("defaults") or {}).items()
                if k != "source"}
    return [{**defaults, **dict(t)} for t in example["tuples"]]


def _value_reply(parameter, label):
    """What the value request returns: the number, its unit, its quote."""
    keep = ("value", "value_raw", "unit", "unit_raw", "quote", "computed")
    return {"tuples": [{**{k: t[k] for k in keep if k in t}, "source": label}
                       for t in _example_tuples(parameter)],
            "status": "complete", "need_more": []}


def test_the_skeleton_is_the_specs_and_not_the_models(profile):
    """Every coordinate the spec declares becomes exactly one question."""
    _name, spec = profile
    for parameter in spec.parameters:
        slots = fields.slots(parameter)
        assert slots[0].kind == fields.VALUE
        assert [s.name for s in slots[1:]] == list(parameter.axes), parameter.uri
        for slot in slots[1:]:
            axis = parameter.axes[slot.name]
            if axis.vocabulary:
                assert slot.is_closed, f"{parameter.uri}.{slot.name}"
                assert len(slot.options) == len(axis.vocabulary)


def test_every_closed_axis_states_its_question(profile):
    """A field request whose question is blank is a request with no rule in it.

    The rules used to live in one prompt that covered sixteen fields at once,
    which is precisely how they became skippable. Asking per field only helps
    if the field brings its rule along.
    """
    _name, spec = profile
    for parameter in spec.parameters:
        for slot in fields.axis_slots(parameter):
            assert slot.question and slot.question.strip(), \
                f"{parameter.uri}.{slot.name} has no question"


def test_an_answer_whose_evidence_is_not_in_the_source_is_not_written(profile):
    """The whole point of a per-field quote: it is checked, like every other."""
    _name, spec = profile
    for parameter in spec.parameters:
        slots = fields.axis_slots(parameter)
        if not slots:
            continue
        batch = _batch(parameter)
        rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
        if not rows:
            continue
        slot = slots[0]
        counts = merge_field(rows, batch, slot, {"answers": {
            rows[0].label: {"value": "was auch immer",
                            "quote": "diese Passage steht in keiner Quelle"}}})
        assert counts == {"filled": 0, "unquoted": 1}
        assert slot.name not in rows[0].claim
        break


def test_a_group_answer_reaches_every_row_it_names(profile):
    """Thirteen table rows share one caption, and it is sent once."""
    _name, spec = profile
    for parameter in spec.parameters:
        slots = fields.axis_slots(parameter)
        batch = _batch(parameter)
        rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
        if not slots or len(rows) < 2:
            continue
        slot, quote = slots[0], rows[0].claim["quote"]
        counts = merge_field(rows, batch, slot, {"groups": [
            {"rows": [r.label for r in rows], "value": "Sammelantwort",
             "value_raw": "Sammelantwort", "quote": quote}]})
        assert counts["filled"] == len(rows)
        assert all(r.claim[slot.name] == "Sammelantwort" for r in rows)
        assert all(r.claim[f"{slot.name}_quote"] == quote for r in rows)
        return


def test_the_example_survives_the_field_wise_round_trip(profile):
    """Value request, then one request per coordinate, then the same verifier.

    Each field answers with the example's own coordinate and cites the tuple's
    own quote, which is the one passage we know is verbatim in the source. What
    comes out has to be what the whole-tuple contract produced, coordinates
    included — otherwise the change traded a silent gap for a silent loss.
    """
    _name, spec = profile
    for parameter in spec.parameters:
        batch = _batch(parameter)
        expected = _example_tuples(parameter)
        rows, orphans = rows_from_reply(batch, _value_reply(parameter,
                                                            batch.label(0)))
        assert not orphans, parameter.uri
        assert len(rows) == len(expected), parameter.uri
        for slot in fields.axis_slots(parameter):
            answers = {}
            for row, want in zip(rows, expected):
                if want.get(slot.name) is None:
                    continue
                answers[row.label] = {
                    "value": want[slot.name],
                    "value_raw": want.get(f"{slot.name}_raw") or str(want[slot.name]),
                    "quote": row.claim["quote"]}
            merge_field(rows, batch, slot, {"answers": answers})
        report = DocumentReport(document_id=7)
        fold_fieldwise(batch, rows, orphans, report)
        assert report.tuples, f"{parameter.uri}: nothing survived"
        assert not report.refusals, \
            f"{parameter.uri}: {report.refusals[0]['reason']}"
        for got, want in zip(report.tuples, expected):
            for name, axis in parameter.axes.items():
                if want.get(name) is None:
                    continue
                assert got.get(name) is not None, \
                    f"{parameter.uri}.{name} lost on the way through"
                assert got.get(f"{name}_quote"), \
                    f"{parameter.uri}.{name} arrived without its own evidence"


def test_both_new_prompts_exist_and_leave_room_for_an_answer(profile):
    """A field reply is small, but a table of forty rows is not."""
    name, _spec = profile
    for prompt_id in (runner.ROWS_PROMPT_ID, runner.FIELD_PROMPT_ID):
        prompt = runner.prompts.load(prompt_id)
        assert prompt.text.strip(), f"{name}: {prompt_id} is empty"
        assert int(prompt.meta.get("max_tokens", 0)) >= 4096, \
            f"{name}: {prompt_id} leaves no room for a long table"
