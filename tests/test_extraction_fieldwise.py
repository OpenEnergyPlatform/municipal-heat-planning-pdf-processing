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
        counts = merge_field(rows, batch.sources, slot, {"answers": {
            rows[0].label: {"value": "was auch immer",
                            "quote": "diese Passage steht in keiner Quelle"}}})
        assert (counts["filled"], counts["unquoted"], counts["unbacked"],
                counts["unstated"]) == (0, 1, 0, 0)
        # And the model is told what was wrong, or three attempts are one
        # attempt three times.
        assert [c["row"] for c in counts["failed"]] == [rows[0].label]
        assert "quote" in counts["failed"][0]["reason"]
        assert slot.name not in rows[0].claim
        break


def test_a_quote_that_does_not_contain_the_answer_is_not_evidence(profile):
    """The half that was missing, and the one that mattered.

    A passage lifted verbatim out of the source proves the model read
    something. Only a passage that CONTAINS the answer proves it read this.
    With the first check alone, 27.6% of the corpus run's years cited a
    passage with no year in it — a caption reading "Tabelle 1: Bestehende
    Wärmenetze und Heiz(kraft)werke" was offered as evidence for 1990.
    """
    _name, spec = profile
    for parameter in spec.parameters:
        slots = fields.axis_slots(parameter)
        if not slots:
            continue
        batch = _batch(parameter)
        rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
        if not rows:
            continue
        slot, quote = slots[0], rows[0].claim["quote"]
        assert "Ziegenkaese" not in quote
        counts = merge_field(rows, batch.sources, slot, {"answers": {
            rows[0].label: {"value": "Ziegenkaese", "value_raw": "Ziegenkaese",
                            "quote": quote}}})
        assert (counts["filled"], counts["unquoted"], counts["unbacked"],
                counts["unstated"]) == (0, 0, 1, 0)
        assert "Ziegenkaese" in counts["failed"][0]["reason"],             "the correction has to name what was not found"
        assert slot.name not in rows[0].claim
        return


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
        # The wording has to stand in the passage, so it is taken FROM it.
        wording = quote.strip().split()[0]
        counts = merge_field(rows, batch.sources, slot, {"groups": [
            {"rows": [r.label for r in rows], "value": "Sammelantwort",
             "value_raw": wording, "quote": quote}]})
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
        text = batch.items[0].source.text
        backed: set = set()
        for slot in fields.axis_slots(parameter):
            answers = {}
            for row, want in zip(rows, expected):
                if want.get(slot.name) is None:
                    continue
                wording = want.get(f"{slot.name}_raw") or str(want[slot.name])
                # The passage a real answer would cite: the one in the source
                # that carries the wording. Where the source carries it
                # nowhere, the coordinate is meant to be dropped, and the
                # assertions below hold the rule rather than the outcome.
                at = text.find(str(wording))
                quote = (text[max(0, at - 60):at + len(str(wording)) + 60]
                         if at != -1 else row.claim["quote"])
                if at != -1:
                    backed.add(slot.name)
                answers[row.label] = {"value": want[slot.name],
                                      "value_raw": wording, "quote": quote}
            merge_field(rows, batch.sources, slot, {"answers": answers})
        report = DocumentReport(document_id=7)
        fold_fieldwise(batch, rows, orphans, report)
        assert report.tuples, f"{parameter.uri}: nothing survived"
        assert not report.refusals, \
            f"{parameter.uri}: {report.refusals[0]['reason']}"
        for got, want in zip(report.tuples, expected):
            for name in parameter.axes:
                if want.get(name) is None:
                    continue
                if name in backed:
                    assert got.get(name) is not None, \
                        f"{parameter.uri}.{name} lost on the way through"
                    assert got.get(f"{name}_quote"), \
                        f"{parameter.uri}.{name} arrived without its own evidence"
                else:
                    # The source says it nowhere, so nothing may claim it does.
                    assert got.get(name) is None, \
                        f"{parameter.uri}.{name} written without evidence"


def test_not_stated_is_an_answer_and_needs_no_passage(profile):
    """There is no sentence in a document saying a thing is not in it.

    Which is why this is the one answer that carries no evidence, and why the
    row can be required to answer at all. Leaving a row out used to mean both
    "the plan does not say" and "I skipped it", and that was 16% to 34% of
    every coordinate on the 1079-document run.
    """
    from docpipe.extraction.pipeline import merge_field as merge
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
        counts = merge(rows, batch.sources, slot, {"answers": {
            rows[0].label: {"value": fields.UNSTATED}}})
        assert counts["unstated"] == 1 and counts["filled"] == 0
        assert rows[0].claim[f"{slot.name}_state"] == fields.SAID_UNSTATED
        assert slot.name not in rows[0].claim
        return


def test_every_coordinate_ends_with_a_state_even_when_nothing_answered(profile):
    """100% of coordinates say what happened to them, or the run cannot be read."""
    from docpipe.extraction.pipeline import mark_unanswered
    _name, spec = profile
    for parameter in spec.parameters:
        slots = fields.axis_slots(parameter)
        if not slots:
            continue
        batch = _batch(parameter)
        rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
        if not rows:
            continue
        blank = mark_unanswered(rows, slots)
        assert blank == len(rows) * len(slots)
        for row in rows:
            for slot in slots:
                assert row.claim[f"{slot.name}_state"] == fields.UNANSWERED
        return


def test_one_window_saying_nothing_here_does_not_end_the_sweep(profile):
    """"Not in these two passages" is not "not in this plan".

    A row answered out:unstated stays open and goes into the next window. It
    closes on a reading, or on the document running out — never on the first
    window that happens not to carry the coordinate.
    """
    from docpipe.extraction.pipeline import merge_field as merge, open_rows
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
        merge(rows, batch.sources, slot,
              {"answers": {r.label: {"value": fields.UNSTATED} for r in rows}})
        assert open_rows(rows, slot) == rows, \
            "a window that said nothing closed the sweep"
        # A reading in a later window closes it, and cannot be undone by yet
        # another window that says the coordinate is not in ITS passages.
        quote = rows[0].claim["quote"]
        merge(rows, batch.sources, slot, {"answers": {rows[0].label: {
            "value": "gelesen", "value_raw": quote.strip().split()[0],
            "quote": quote}}})
        assert rows[0] not in open_rows(rows, slot)
        merge(rows, batch.sources, slot,
              {"answers": {rows[0].label: {"value": fields.UNSTATED}}})
        assert rows[0].claim[f"{slot.name}_state"] == fields.READ
        return


def test_a_rows_own_passage_stays_checkable_after_the_window_moves_on(profile):
    """The row carries its quote into every field request, so citing it is a
    reading and not an invention.

    Checked against the window alone it stops being one from the second window
    on, and a correct answer is thrown away for citing the passage the request
    itself showed. Measured live: one batch logged 520 dropped against 31 read.
    """
    from docpipe.extraction.pipeline import merge_field as merge
    _name, spec = profile
    for parameter in spec.parameters:
        slots = fields.axis_slots(parameter)
        if not slots:
            continue
        batch = _batch(parameter)
        rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
        if not rows:
            continue
        slot, quote = slots[0], rows[0].claim["quote"]
        far_away = [Source("section", 999, "eine ganz andere Passage", {})]
        answer = {"answers": {rows[0].label: {
            "value": "gelesen", "value_raw": quote.strip().split()[0],
            "quote": quote}}}
        assert merge(list(rows), far_away, slot, answer)["unquoted"] == 1
        assert merge(rows, far_away + batch.sources, slot, answer)["filled"] == 1
        return


def test_a_dropped_answer_is_not_recorded_as_no_answer(profile):
    """"Said nothing" and "said something it could not back" are two findings.

    And the row stays open either way: a later window can still read it.
    """
    from docpipe.extraction.pipeline import merge_field as merge, open_rows
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
        merge(rows, batch.sources, slot, {"answers": {rows[0].label: {
            "value": "Ziegenkaese", "value_raw": "Ziegenkaese",
            "quote": rows[0].claim["quote"]}}})
        assert rows[0].claim[f"{slot.name}_state"] == fields.UNBACKED
        assert rows[0] in open_rows(rows, slot), "an unbacked row must stay open"
        return


def test_not_stated_is_in_the_list_the_model_picks_from(profile):
    """A finite set of correct answers is a choice, and "the passages do not
    say" is one of them — so it is an entry, not a rule to remember."""
    _name, spec = profile
    for parameter in spec.parameters:
        for slot in fields.axis_slots(parameter):
            if not slot.options:
                continue
            assert fields.UNSTATED in slot.answerable(), \
                f"{parameter.uri}.{slot.name} offers no way to say it is absent"


def test_a_field_request_carries_the_crop_of_what_it_asks_about(profile):
    """A table's transcription is a model's reading of a picture, and the
    coordinate asked for is often clearer in the picture than in the reading.
    The value request has always attached the crops; the field request sent
    JSON text and nothing else."""
    import inspect
    source = inspect.getsource(runner.make_field_asker)
    assert "_image_part" in source and "ATTACH_IMAGES" in source, \
        "the field request attaches no crops"


def test_running_out_of_budget_is_not_the_same_finding_as_a_silent_plan():
    """The pair this stage exists to keep apart, one level up.

    "The plan does not say" is a finding about the corpus and belongs in a
    report. "We stopped looking" is a finding about the run and belongs in a
    backlog. They must not be the same string.
    """
    assert fields.EXHAUSTED != fields.SAID_UNSTATED
    assert len({fields.READ, fields.SAID_UNSTATED,
                fields.UNANSWERED, fields.EXHAUSTED}) == 4


@pytest.mark.parametrize("size,overlap,expected", [
    (2, 1, [["a", "b"], ["b", "c"], ["c", "d"]]),
    (2, 0, [["a", "b"], ["c", "d"]]),
    (3, 1, [["a", "b", "c"], ["c", "d"]]),
])
def test_the_sweep_walks_every_passage_and_never_cuts_a_seam(size, overlap,
                                                             expected):
    """Short windows, and no passage falls between two of them.

    The overlap is not decoration: a caption and the table it belongs to are
    adjacent passages, and the year lives on exactly that seam.
    """
    from docpipe.extraction.pipeline import window_sources
    got = list(window_sources(["a", "b", "c", "d"], size, overlap))
    assert got == expected
    assert set(sum(got, [])) == {"a", "b", "c", "d"}


TABLE = "| Erdgas | 126.656.132 | 520.465.057 | 1.036.767.833 |"


@pytest.mark.parametrize("value,expected", [
    (126656132, (2, 4)),
    (520465057, (3, 4)),
    (1036767833, (4, 4)),
])
def test_the_column_a_number_stands_in_is_counted_not_guessed(value, expected):
    """Three numbers, one quote, three different years. The column tells them
    apart, and it is derivable from the value and the row it was quoted from."""
    from docpipe.extraction.pipeline import cell_index
    assert cell_index(TABLE, value) == expected


@pytest.mark.parametrize("quote,value", [
    ("Der Verbrauch lag bei 126.656.132 kWh/a.", 126656132),   # not a table
    ("| Erdgas | 4.000 | 4.000 | 8.000 |", 4000),              # twice over
    (TABLE, 999),                                              # in no cell
])
def test_an_uncertain_column_is_left_out_rather_than_guessed(quote, value):
    """A wrong column would put a value under the wrong year, which is worse
    than a value with no year at all."""
    from docpipe.extraction.pipeline import cell_index
    assert cell_index(quote, value) is None


def test_the_field_reply_contract_is_stated_by_every_profiles_prompt(profile):
    """merge_field parses one shape, and each profile describes it in its own
    words. A prompt that describes a different one fills nothing and says
    nothing, so the keys the core reads are checked to be named.

    The prompts stay with the profile on purpose (prompts.py: a prompt names
    the corpus and the language, and the core knows neither). This is the seam
    that costs, so it is the seam that is held.
    """
    name, _spec = profile
    text = runner.prompts.load(runner.FIELD_PROMPT_ID).text
    for key in ("groups", "answers", "rows", "value", "value_raw", "quote"):
        assert f'"{key}"' in text, f"{name}: field prompt never names {key!r}"


def test_both_new_prompts_exist_and_leave_room_for_an_answer(profile):
    """A field reply is small, but a table of forty rows is not."""
    name, _spec = profile
    for prompt_id in (runner.ROWS_PROMPT_ID, runner.FIELD_PROMPT_ID):
        prompt = runner.prompts.load(prompt_id)
        assert prompt.text.strip(), f"{name}: {prompt_id} is empty"
        assert int(prompt.meta.get("max_tokens", 0)) >= 4096, \
            f"{name}: {prompt_id} leaves no room for a long table"


def test_a_wording_offered_with_not_stated_is_kept_for_the_vocabulary_review(profile):
    """"There is no sector here" and "I found CCS/CCU and it is in no list"
    are two findings, and they arrive in the same answer shape.

    The wording is not evidence and does not fill the coordinate. It is the
    only trace of which classes the corpus needs and the spec does not have,
    and without it both cases are the same empty cell.
    """
    from docpipe.extraction.pipeline import merge_field as merge
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
        merge(rows, batch.sources, slot, {"answers": {rows[0].label: {
            "value": fields.UNSTATED,
            "value_raw": "CCS/CCU (Abscheideleistung: 95.000 t/a)",
            "quote": rows[0].claim["quote"]}}})
        claim = rows[0].claim
        assert claim[f"{slot.name}_state"] == fields.SAID_UNSTATED
        assert slot.name not in claim, "it must not fill the coordinate"
        assert f"{slot.name}_quote" not in claim, "and it is not evidence"
        assert claim[f"{slot.name}_seen"].startswith("CCS/CCU")
        return


# ---------------------------------------------------------------------------
# The parameter is a coordinate, not a property of the plan
# ---------------------------------------------------------------------------

def _document_batch(sources=1):
    """A batch as a document-level plan produces one: no parameter fixed."""
    items = [WorkItem(7, None, Source("table", n, "| Erdgas | 42.005 | MWh/a |",
                                      {"document_id": 7, "page": n}))
             for n in range(sources)]
    return group_items(items, max_sources=runner.BATCH_SOURCES)[0]


def _fieldwise(monkeypatch, spec, rows_reply, answers):
    """A field-wise harvester whose two model calls are the given stubs.

    `answers` is called with the slot and returns that field's reply, so a
    test says what the model answers per coordinate and nothing else.
    """
    asked = []
    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            for slot in slots:
                asked.append(slot.name)
            return {"fields": {slot.name: answers(slot, rows)
                               for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    return runner.make_fieldwise_harvester(spec=spec), asked


def test_which_quantity_a_number_is_follows_its_unit_and_decides_its_axes(
        monkeypatch):
    """The promise: the parameter is not fixed by the plan and not asked for
    either — the unit settles it, and it decides which coordinates the row has.

    The plan used to fix it, so a table holding a consumption and an emission
    was retrieved, read and paid for twice: 804 planned sources against 234
    owners. Asking instead was right about the shape and wrong about the cost:
    the spec says itself that the unit separates the two parameters, their
    nine and forty-two spellings share none, and not one of Kassel's 559
    accepted tuples contradicted its unit. The question cost 322 of 1,043
    field windows, 30.9 percent."""
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    consumption = spec.parameters[0]
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005, "unit": "MWh/a",
                              "unit_raw": "MWh/a",
                              "quote": "| Erdgas | 42.005 | MWh/a |"}],
                  "status": "complete", "need_more": []}

    harvest, asked = _fieldwise(monkeypatch, spec, rows_reply,
                                lambda slot, rows: {"answers": {}})
    reply = harvest(_document_batch())

    assert "parameter" not in asked, "MWh/a settles it, so nothing asks"
    axes = {s.name for s in fields.asked_slots(consumption)}
    assert axes <= set(asked), "the axes of the parameter it turned out to be"
    row = reply["tuples"][0]
    assert row["parameter"] == consumption.uri, (
        "and it is stored as the class, not as the label")
    assert row["parameter_state"] == fields.DERIVED, (
        "derived, because nothing read it")
    assert row["parameter_raw"] == "MWh/a", "the wording it was derived from"


def test_a_row_whose_quantity_stayed_unread_is_not_given_a_guessed_axis(
        monkeypatch):
    """Refusing it later is the point: a row with no parameter has no
    coordinates to fill, and filling the first parameter's would be a guess
    written down as a reading.

    The unit here is one no parameter accepts. That used to be swept as a real
    question and it is not one: `verify._check_value` refuses on the very
    `unit_factor` lookup `derive_parameter` just failed, so every answer the
    model could give is already decided against. Measured on the M3 run, 69
    such rows cost 178 of 853 field requests, 20.9 percent, and the five
    answers they produced were all refused afterwards. Kassel had three of
    them, amounts in EUR from a cost table.

    So nothing is asked, and the row keeps a state saying it was never in
    range rather than one saying we ran out of document."""
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005, "unit": "EUR",
                              "unit_raw": "EUR",
                              "quote": "| Erdgas | 42.005 | EUR |"}],
                  "status": "complete", "need_more": []}

    harvest, asked = _fieldwise(
        monkeypatch, spec, rows_reply,
        lambda slot, rows: {"answers": {"R1": {"value": fields.UNSTATED}}})
    reply = harvest(_document_batch())

    assert asked == [], "not even the parameter question, which has no answer"
    row = reply["tuples"][0]
    assert row["parameter_state"] == fields.OUT_OF_SLICE
    assert not any(k.endswith("_state") and k != "parameter_state" for k in row)
    # And skipping the question is safe only because every answer it could
    # have produced is refused anyway, on the same lookup that just failed.
    # Asserted through the verifier rather than argued in the comment.
    from docpipe.extraction import verify
    for parameter in spec.parameters:
        if not parameter.is_numeric:
            continue
        _kept, refusal = verify._check_value(
            {"value": 42005, "unit": "EUR", "unit_raw": "EUR"}, parameter, [])
        assert refusal is not None and "EUR" in refusal.reason, parameter.uri


def test_a_unit_two_parameters_accept_is_still_a_real_question(monkeypatch):
    """The other half of the same guard. `derive_parameter` returns None for
    three situations and only this one is a question the model can answer, so
    the skip must not swallow it: a spec whose parameters share a unit still
    gets asked.

    Built here rather than taken from kwp, whose nine energy units and
    forty-two emission units share not one spelling -- which is why the case
    never arises there and the sweep looked harmless.
    """
    raw = json.loads((PROFILES / "kwp" / "extraction_spec.json")
                     .read_text(encoding="utf-8"))
    for parameter in raw["parameters"]:
        if parameter.get("units_accepted"):
            parameter["units_accepted"]["GWh"] = 1.0
    spec = load_spec(raw)
    assert fields.derive_parameter(spec, {"value": 1, "unit": "GWh"}) is None
    assert not fields.parameter_undecidable(spec, {"value": 1, "unit": "GWh"})

    rows_reply = {"tuples": [{"source": "Q1", "value": 12, "unit": "GWh",
                              "unit_raw": "GWh",
                              "quote": "| Erdgas | 12 | GWh |"}],
                  "status": "complete", "need_more": []}
    harvest, asked = _fieldwise(
        monkeypatch, spec, rows_reply,
        lambda slot, rows: {"answers": {"R1": {"value": fields.UNSTATED}}})
    harvest(_document_batch())
    assert asked == ["parameter"], "two holders, so the model decides"


# ---------------------------------------------------------------------------
# The slice gate
#
# The promise: a row that a gate coordinate puts outside the slice is not
# asked for its remaining axes, and every one of its coordinates still ends
# with a state. Two clauses, and a third case so the gate cannot be too wide.
# ---------------------------------------------------------------------------

def _gated(monkeypatch, spec, rows_reply, answers, gate):
    """Like _fieldwise, but it records WHICH rows each field was asked for."""
    asked = []

    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            labels = sorted(r.label for r in rows)
            for slot in slots:
                asked.append((slot.name, labels))
            return {"fields": {slot.name: answers(slot, rows)
                               for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    return runner.make_fieldwise_harvester(spec=spec, slice_gate=gate), asked


def _two_row_spec_and_reply():
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    rows_reply = {"tuples": [
        {"source": "Q1", "value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a",
         "quote": "| Erdgas | 42.005 | MWh/a |"},
        {"source": "Q1", "value": 99, "unit": "MWh/a", "unit_raw": "MWh/a",
         "quote": "| Erdgas | 42.005 | MWh/a |"}],
        "status": "complete", "need_more": []}
    return spec, rows_reply


def _answers_for(spec, quantity_of, scenario_of):
    consumption = spec.parameters[0]
    quote = "| Erdgas | 42.005 | MWh/a |"

    def answers(slot, rows):
        if slot.name == "parameter":
            return {"answers": {r.label: {"value": consumption.label,
                                          "value_raw": "MWh/a", "quote": quote}
                                for r in rows}}
        if slot.name in ("quantity", "scenario"):
            picked = quantity_of if slot.name == "quantity" else scenario_of
            return {"answers": {r.label: {"value": picked.get(r.label),
                                          "value_raw": "MWh/a", "quote": quote}
                                for r in rows if picked.get(r.label)}}
        return {"answers": {}}
    return answers


def test_a_row_outside_the_slice_is_not_asked_for_its_other_axes(monkeypatch):
    """Measured on 20 plans: of 6,763 harvested tuples the serializer took
    1,294 and dropped 4,064 for the quantity or the scenario alone — after the
    run had paid for all seven axes of every one of them."""
    spec, rows_reply = _two_row_spec_and_reply()
    answers = _answers_for(
        spec,
        quantity_of={"R1": "final energy consumption value", "R2": "Potenzial"},
        scenario_of={"R1": "Zielszenario", "R2": "Zielszenario"})
    harvest, asked = _gated(monkeypatch, spec, rows_reply, answers,
                            {"quantity": None, "scenario": ("target",)})
    reply = harvest(_document_batch())

    gate_order = [name for name, _rows in asked][:2]
    assert gate_order == ["quantity", "scenario"], (
        "the gate is asked first and in order, the parameter came from the unit")
    after = {name: rows for name, rows in asked[2:]}
    assert after, "the row that stayed is still asked for its axes"
    assert all(rows == ["R1"] for rows in after.values()), (
        "and only that row: R2 fell out at the quantity")

    out = next(t for t in reply["tuples"] if t.get("value") == 99)
    for axis in fields.asked_slots(spec.parameters[0]):
        if axis.name in ("quantity", "scenario"):
            continue
        assert out.get(f"{axis.name}_state") == fields.OUT_OF_SLICE, (
            f"{axis.name} was never asked and has to say so")
    # And what the spec decided is on the row anyway: a coordinate that never
    # needed a request is not "never asked", and saying so would be a second
    # kind of silence.
    assert out.get("aggregation_state") == fields.DERIVED
    assert out.get("aggregation") == "OEO_00140070"


def test_a_scenario_the_slice_does_not_hold_closes_the_row(monkeypatch):
    """The second gate coordinate, and the bigger one: 2,510 of those 4,064."""
    spec, rows_reply = _two_row_spec_and_reply()
    answers = _answers_for(
        spec,
        quantity_of={"R1": "final energy consumption value",
                     "R2": "final energy consumption value"},
        scenario_of={"R1": "Zielszenario", "R2": "Ist-Zustand"})
    harvest, asked = _gated(monkeypatch, spec, rows_reply, answers,
                            {"quantity": None, "scenario": ("target",)})
    harvest(_document_batch())
    after = {name: rows for name, rows in asked[3:]}
    assert after and all(rows == ["R1"] for rows in after.values())


def test_an_undecided_gate_coordinate_keeps_the_row(monkeypatch):
    """The gate must not be a second way to lose values. A coordinate that
    came back empty is a finding about the passages, not a licence to throw
    the number away."""
    spec, rows_reply = _two_row_spec_and_reply()
    answers = _answers_for(
        spec,
        quantity_of={"R1": "final energy consumption value"},   # R2: no answer
        scenario_of={"R1": "Zielszenario", "R2": "Zielszenario"})
    harvest, asked = _gated(monkeypatch, spec, rows_reply, answers,
                            {"quantity": None, "scenario": ("target",)})
    harvest(_document_batch())
    after = {name: rows for name, rows in asked[3:]}
    assert after and all(rows == ["R1", "R2"] for rows in after.values()), (
        "undecided is not outside")

    # The reply carries the option's LABEL, so the gate has to resolve it.
    # Reading the profile as if it held German spellings kept every potential
    # and threw away every target scenario.
    quantity = next(s for s in fields.axis_slots(spec.parameters[0])
                    if s.name == "quantity")
    scenario = next(s for s in fields.axis_slots(spec.parameters[0])
                    if s.name == "scenario")
    assert runner.keeps_row(quantity, None, None)
    assert runner.keeps_row(scenario, "", ("target",))
    assert runner.keeps_row(scenario, fields.UNSTATED, ("target",))
    assert not runner.keeps_row(quantity, "Potenzial", None)
    assert runner.keeps_row(quantity, "final energy consumption value", None)
    assert runner.keeps_row(scenario, "Zielszenario", ("target",))
    assert not runner.keeps_row(scenario, "Ist-Zustand", ("target",))


def test_the_coordinates_of_a_row_go_out_in_one_request(monkeypatch):
    """The promise: several fields ride in ONE request, and each is folded and
    evidenced on its own.

    One field per request was one round trip per coordinate. Measured over 60
    documents of the corpus run, 2,108 field requests each, which is what made
    it 82 hours for 1,079 plans."""
    spec, rows_reply = _two_row_spec_and_reply()
    consumption = spec.parameters[0]
    quote = "| Erdgas | 42.005 | MWh/a |"
    calls = []

    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            calls.append([s.name for s in slots])
            out = {}
            for slot in slots:
                if slot.name == "parameter":
                    value = consumption.label
                elif slot.name == "quantity":
                    value = "final energy consumption value"
                elif slot.name == "scenario":
                    value = "Zielszenario"
                elif slot.name == "carrier":
                    value = "Erdgas"
                else:
                    continue
                out[slot.name] = {"answers": {r.label: {
                    "value": value, "value_raw": "MWh/a", "quote": quote}
                    for r in rows}}
            return {"fields": out}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    harvest = runner.make_fieldwise_harvester(
        spec=spec, slice_gate={"quantity": None, "scenario": ("target",)})
    reply = harvest(_document_batch())

    assert len(calls) == 2, (
        "one for the gate, one for the rest — the parameter came from the "
        "unit and the aggregation from the spec, not one "
        "per coordinate: %s" % calls)
    assert calls[0] == ["quantity", "scenario"]
    assert len(calls[1]) == len(fields.asked_slots(consumption)) - 2

    # Every field of the one reply is folded on its own.
    row = reply["tuples"][0]
    assert row["quantity_state"] == fields.READ
    assert row["scenario_state"] == fields.READ
    assert row["carrier_state"] == fields.READ
    assert row["carrier_quote"] == quote, "and carries its own evidence"
    # And the two the spec settled carry their own state and their own
    # wording, so nothing on the row is silent about where it came from.
    assert row["parameter_state"] == fields.DERIVED
    assert row["aggregation_state"] == fields.DERIVED
    assert row["aggregation_raw"] == "MWh/a"


# ---------------------------------------------------------------------------
# What a reading is worth once it exists
#
# Four promises, one folding step. A coordinate that was read and backed is
# final, a four-character quote is not a passage, every reading says where and
# when it was read, and a choice that arrives without the words it was read
# from is counted because it can never be re-mapped.
# ---------------------------------------------------------------------------

def _one_row(profile_pair, kind=None):
    """A parameter, its batch, one row and a slot of the wanted kind."""
    _name, spec = profile_pair
    for parameter in spec.parameters:
        slots = [s for s in fields.axis_slots(parameter)
                 if kind is None or s.kind == kind]
        if not slots:
            continue
        batch = _batch(parameter)
        rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
        if rows:
            return batch, rows, slots[0]
    return None, None, None


def test_a_read_coordinate_is_not_overwritten_by_a_later_window(profile):
    """The promise: a coordinate that was read and backed keeps its value,
    its wording and its passage, whatever a later window answers.

    Measured on Kassel: table 10 was read as useful energy in a trend scenario
    in its own window and rewritten to final energy in the target scenario by
    a later window that showed the appendix. 7 value nodes carried the second
    reading, 10 more tuples collided with the first and took six identities
    down with them. The last speaker does not own the coordinate.
    """
    batch, rows, slot = _one_row(profile)
    if batch is None:
        pytest.skip("this profile has no axes")
    quote = rows[0].claim["quote"]
    first = quote.strip().split()[0]
    merge_field(rows, batch.sources, slot, {"answers": {rows[0].label: {
        "value": "gelesen", "value_raw": first, "quote": quote}}})
    assert rows[0].claim[f"{slot.name}_state"] == fields.READ

    later = Source("section", 4242, "Ganz woanders steht gelesen anders.", {})
    counts = merge_field(rows, [later], slot, {"answers": {rows[0].label: {
        "value": "anders", "value_raw": "anders",
        "quote": "Ganz woanders steht gelesen anders."}}})
    assert rows[0].claim[slot.name] == "gelesen", "a reading is final"
    assert rows[0].claim[f"{slot.name}_raw"] == first
    assert rows[0].claim[f"{slot.name}_quote"] == quote
    assert counts["filled"] == 0, "and the second answer is not counted as one"


def test_a_quote_too_short_to_name_a_place_is_not_evidence(profile):
    """The promise: a passage under MIN_QUOTE_CHARS leaves the coordinate
    open, whatever else is right about the answer.

    "2030" stands in a heat plan a hundred times over, so it proves the model
    can read a number and nothing about where it read THIS one. field.md rule
    3 promises eight characters and only the value quote was ever held to it.
    Kassel cited the bare year three times.
    """
    from docpipe.extraction.verify import MIN_QUOTE_CHARS
    batch, rows, slot = _one_row(profile)
    if batch is None:
        pytest.skip("this profile has no axes")
    short = "2030"
    assert len(short) < MIN_QUOTE_CHARS
    sources = [Source("table", 77, f"| Jahr | {short} |", {})]
    counts = merge_field(rows, sources, slot, {"answers": {rows[0].label: {
        "value": short, "value_raw": short, "quote": short}}})
    assert counts["filled"] == 0
    assert rows[0].claim[f"{slot.name}_state"] == fields.UNBACKED
    assert [f["why"] for f in counts["failed"]] == ["quote_too_short"]

    # The same reading in a passage that names a place is taken.
    long = f"| Endenergie gesamt | {short} | 1.234 |"
    assert len(long) >= MIN_QUOTE_CHARS
    counts = merge_field(rows, [Source("table", 77, long, {})],
                         slot, {"answers": {rows[0].label: {
                             "value": short, "value_raw": short,
                             "quote": long}}})
    assert counts["filled"] == 1


def test_every_reading_says_which_passage_and_which_window_it_came_from(profile):
    """The promise: a read coordinate carries the owner its passage was found
    in and the window it was read in.

    Whether a reading is local to its row or borrowed from elsewhere in the
    document is the question the Kassel review could only answer by hand: 370
    of 455 year readings cited a passage outside the row's own table and its
    section, and not one of them said so. A boolean "some source had it"
    cannot be asked that question afterwards.
    """
    batch, rows, slot = _one_row(profile)
    if batch is None:
        pytest.skip("this profile has no axes")
    quote = rows[0].claim["quote"]
    near = Source("section", 4711, f"Im Abschnitt steht: {quote}", {})
    merge_field(rows, [near], slot, {"answers": {rows[0].label: {
        "value": "gelesen", "value_raw": quote.strip().split()[0],
        "quote": quote}}}, window=("retrieval", 3))
    assert rows[0].claim[f"{slot.name}_source"] == ["section", 4711]
    assert rows[0].claim[f"{slot.name}_window"] == ["retrieval", 3]


def test_a_choice_without_its_wording_is_counted_as_unmappable(profile):
    """The promise: a choice read without value_raw is counted, because it can
    never be re-mapped when the vocabulary moves.

    The URI is all that survives such a reading and the words the model
    resolved to it are gone, so an alias added later cannot be applied to it
    offline. That is the difference between minutes of re-mapping and a
    93-GPU-hour re-harvest of 1,082 plans. The absence of the key is the
    marker a top-up looks for, so nothing is invented to fill it.
    """
    batch, rows, slot = _one_row(profile, kind=fields.CHOICE)
    if batch is None:
        pytest.skip("this profile has no choice axis")
    label = slot.options[0].label
    quote = f"In der Tabelle steht {label} als Zeilenbeschriftung."
    counts = merge_field(rows, [Source("table", 5, quote, {})],
                         slot, {"answers": {rows[0].label: {
                             "value": label, "quote": quote}}})
    assert counts["filled"] == 1, "it is still a reading"
    assert counts["raw_missing"] == 1
    assert f"{slot.name}_raw" not in rows[0].claim

    # With the wording it is mappable and not counted.
    batch, rows, slot = _one_row(profile, kind=fields.CHOICE)
    counts = merge_field(rows, [Source("table", 5, quote, {})],
                         slot, {"answers": {rows[0].label: {
                             "value": label, "value_raw": label,
                             "quote": quote}}})
    assert counts["raw_missing"] == 0
    assert rows[0].claim[f"{slot.name}_raw"] == label


def test_the_trace_names_the_field_that_filled_and_the_field_that_dropped(
        monkeypatch):
    """The promise: a field event says which coordinate filled and which
    failed, and a drop event names the coordinate it belongs to.

    Five fields answer in one reply. A run that logs
    "aggregation+carrier+sector+year+spatial_scope: 3 filled, 2 unbacked"
    cannot say which two were dropped, and on one corpus group 7,738 unbacked
    and 3,110 unquoted answers were not attributable to any coordinate. The
    knob that would fix them cannot be found in a number that names five
    things at once.
    """
    spec, rows_reply = _two_row_spec_and_reply()
    consumption = spec.parameters[0]
    good = "| Erdgas | 42.005 | MWh/a |"

    def answers(slot, rows):
        if slot.name == "parameter":
            return {"answers": {r.label: {"value": consumption.label,
                                          "value_raw": "MWh/a",
                                          "quote": good} for r in rows}}
        if slot.name == "carrier":
            return {"answers": {r.label: {"value": "Erdgas",
                                          "value_raw": "Erdgas",
                                          "quote": good} for r in rows}}
        if slot.name == "sector":
            return {"answers": {r.label: {
                "value": "Haushalte", "value_raw": "Haushalte",
                "quote": "Diese Passage steht in keiner gezeigten Quelle."}
                for r in rows}}
        return {"answers": {}}

    events = []
    monkeypatch.setattr(runner.trace, "event",
                        lambda kind, doc, **kw: events.append((kind, kw)))
    harvest, _asked = _gated(monkeypatch, spec, rows_reply, answers, {})
    harvest(_document_batch())

    fields_events = [kw for kind, kw in events if kind == "field"
                     and "carrier" in (kw.get("slot") or "")]
    assert fields_events, "the axes were asked"
    first = fields_events[0]
    assert first["filled_by"].get("carrier") == 2, "carrier read both rows"
    assert "sector" not in first["filled_by"]
    assert first["unbacked_by"].get("sector") == 2
    assert "carrier" not in first["unbacked_by"]

    dropped = [kw for kind, kw in events if kind == "drop"]
    assert dropped, "a failed coordinate is a drop"
    assert {d["field"] for d in dropped} == {"sector"}, (
        "and the drop names the coordinate, not the request")
    assert {d["why"] for d in dropped} == {"quote_not_in_source"}


def test_a_status_quo_row_is_asked_its_coordinates(monkeypatch):
    """The promise: the scenario no longer closes a row, so an inventory value
    is asked its carrier, sector and year like a target value is.

    It used to close it, and that was the bigger half of the loss: 2,510 of
    6,763 harvested tuples over 20 plans were dropped for being a status quo,
    a trend or a potential. MHPO names the inventory analysis and the
    potential analysis, so those rows have a place in the graph and need
    their coordinates to reach it.
    """
    spec, rows_reply = _two_row_spec_and_reply()
    answers = _answers_for(
        spec,
        quantity_of={"R1": "final energy consumption value",
                     "R2": "final energy consumption value"},
        scenario_of={"R1": "Zielszenario", "R2": "Ist-Zustand"})
    harvest, asked = _gated(monkeypatch, spec, rows_reply, answers,
                            {"quantity": None})
    reply = harvest(_document_batch())

    after = {name: rows for name, rows in asked if name not in
             ("parameter", "quantity", "scenario")}
    assert after, "the axes behind the gate were asked"
    assert all(rows == ["R1", "R2"] for rows in after.values()), (
        "the status quo row is asked too")
    out = [t for t in reply["tuples"]
           if t.get(f"carrier_state") == fields.OUT_OF_SLICE]
    assert not out, "and nothing is stamped out_of_slice for its scenario"


def test_the_kwp_gate_holds_only_the_quantity(monkeypatch):
    """The profile's own choice, not the mechanism's. The gate still exists
    and still closes a row whose quantity is a deliberate non-class."""
    from profiles.kwp import extraction as kwp_extraction
    assert set(kwp_extraction.SLICE) == {"quantity"}
    assert kwp_extraction.SLICE["quantity"] is None


def test_a_wording_its_passage_does_not_carry_never_becomes_a_row(profile):
    """The promise: a non-numeric value that its own quote does not contain is
    refused where it arrives, not after every coordinate has been swept for it.

    Measured on Kassel: the office name the prompt's own example suggested was
    written onto the title page, cost 24 windows and 80.3 seconds of sweeping
    and reached the graph never. The claim still travels on and is still
    refused, it just costs nothing now.
    """
    _name, spec = profile
    parameter = spec.parameters[0]
    batch = _batch(parameter)
    text = batch.items[0].source.text
    quote = text[:80]
    assert len(quote) >= 8

    rows, orphans = rows_from_reply(batch, {"tuples": [
        {"source": batch.label(0), "value": "Erfundenes Ingenieurbüro",
         "unit": "", "unit_raw": "", "quote": quote}]})
    assert rows == [], "no row, so no sweep"
    assert [o["_why"] for o in orphans] == ["text value not in its quote"]

    # A wording the passage does carry is a reading like any other.
    word = quote.strip().split()[0]
    rows, orphans = rows_from_reply(batch, {"tuples": [
        {"source": batch.label(0), "value": word,
         "unit": "", "unit_raw": "", "quote": quote}]})
    assert len(rows) == 1 and not orphans

    # And a number is left to the verifier, which knows the German decimal
    # mark and repairs a retyped table row. Refusing it here would refuse
    # claims the verifier would have taken.
    rows, orphans = rows_from_reply(batch, {"tuples": [
        {"source": batch.label(0), "value": "1.036.767,8", "unit_raw": "MWh/a",
         "quote": quote}]})
    assert len(rows) == 1 and not orphans


def test_the_row_prompt_example_names_no_place_this_corpus_contains(profile):
    """The example is an invitation, and this one was taken: it put a firm
    named after the city onto the city's own title page. The names in it come
    from a plan that is not the one being read, and the prompt says so."""
    name, _spec = profile
    text = (PROFILES / name / "prompts" / "extraction" / "rows.md").read_text(
        encoding="utf-8")
    assert "Kassel Wärme" not in text
    if name == "kwp":
        assert "MASCHINELL" in text, "the check is promised where it applies"
        assert "anderen Plan" in text


def test_the_field_prompt_states_the_rule_the_code_enforces(profile):
    """A rule the request does not state is a rule the model cannot follow.
    The code refuses a passage from another source; the prompt has to say
    which source is the row's own and how the request names it."""
    name, _spec = profile
    text = (PROFILES / name / "prompts" / "extraction" / "field.md").read_text(
        encoding="utf-8")
    if name != "kwp":
        pytest.skip("the evidence rule is set per profile")
    for promised in ('"source"', '"section"', '"block_id"', '"holds"',
                     "EIGENEN Tabelle", "Nachbarseite"):
        assert promised in text, promised
    # The two captions the rule turns on, verbatim from Kassel 349525/349566.
    assert "Tabelle 17: Endenergieverbrauch der Gesamtstadt" in text
    assert "Tabelle 28: Endenergieverbrauch der Gesamtstadt" in text
    # And the column rule no longer says the column is the year.
    rules = text.split("4. Tabellen mit mehreren")[1]
    column = rules.split(chr(10) + chr(10))[0]
    assert "SEKTOR" in column and "JAHR" in column


def test_the_own_window_shows_the_section_a_table_stands_in(monkeypatch):
    """The promise: the first window a coordinate is asked in holds the table
    AND the section around it, each section once.

    The own window used to be the batch's tables and nothing else, and the
    coordinates a table does not carry live one level up. Measured on Kassel,
    section 349525 appeared in 0 of 1,043 field windows while its three tables
    were asked for their year 39 times, and 69 tuples from inventory tables
    came back as target-scenario values because no window ever showed the word
    for what they are.
    """
    spec, rows_reply = _two_row_spec_and_reply()
    shown_per_window = []

    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None):
            shown_per_window.append([(s.owner_kind, s.owner_id) for s in shown])
            return {"fields": {}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    section = Source("section", 349525,
                     "Für das Jahr 2040 ergeben sich die Kennzahlen. "
                     "Tabelle 17: Endenergieverbrauch im Zielszenario 2040 "
                     "[p85_tbl0]", {"title": "Zielszenario"})
    calls = []

    def parents(sources):
        calls.append(len(sources))
        return [section]

    harvest = runner.make_fieldwise_harvester(spec=spec, slice_gate={},
                                              parents=parents)
    harvest(_document_batch(sources=2))

    assert calls, "the parent was asked for"
    first = shown_per_window[0]
    assert ("section", 349525) in first, "the section rides in the first window"
    assert sum(1 for kind, _ in first if kind == "table") == 2, (
        "and the tables are still there")
    assert first.count(("section", 349525)) == 1, "once, not once per table"


def test_a_parent_section_is_not_fetched_twice_and_a_long_one_is_cut(tmp_path):
    """Two tables of one section share one parent, and a section too long for
    the window is cut around the table's own placeholder rather than dropped:
    the sentence that dates a table stands next to its placeholder and
    nowhere else."""
    import sqlite3
    from docpipe.extraction.runner import PARENT_CHARS, make_parents, _around

    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    filler = "Fülltext. " * 800
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               section_number INTEGER, title TEXT,
                               content TEXT, page_number INTEGER);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             block_id TEXT, caption TEXT, markdown TEXT,
                             page_number INTEGER, path TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             block_id TEXT, caption TEXT, description TEXT,
                             page_number INTEGER, path TEXT);
    """)
    conn.execute("INSERT INTO Documents VALUES (7, 'plan.pdf')")
    conn.execute("INSERT INTO Sections VALUES (5, 7, 1, 'Zielszenario', ?, 86)",
                 (filler + "Tabelle 17: Verbrauch im Zielszenario 2040 "
                  "[p85_tbl0]" + filler,))
    conn.commit()
    conn.close()

    parents = make_parents(db)
    sources = [Source("table", n, "| Erdgas | 1 |",
                      {"parent_section": 5, "block_id": f"p85_tbl{n}"})
               for n in range(2)]
    got = parents(sources)
    assert len(got) == 1, "two tables of one section share one parent"
    assert len(got[0].text) <= PARENT_CHARS + 200
    assert "Tabelle 17" in got[0].text, "cut around the placeholder, not off it"

    # A source with no parent asks for nothing, and a section already shown is
    # not shown again.
    assert parents([Source("section", 5, "x", {})]) == []
    assert _around("abcdef", "cd", 4) == "abcd", "no room to centre, so from 0"
    assert _around("xxxxxxxxNEEDLExxxxxxxx", "NEEDLE", 10) == "xxxxxNEEDL", (
        "the window opens half a budget before the needle")
    assert _around("abcdef", "zz", 3) == "abc", "needle absent, head of the text"


def test_the_request_says_where_a_source_stands(monkeypatch):
    """Which source is the table and which is the section around it is a fact
    the request carries, not one the model infers from the order."""
    spec, _reply = _two_row_spec_and_reply()
    parameter = spec.parameters[0]
    batch = _batch(parameter)
    rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
    table = Source("table", 87457, "| Erdgas | 1 |",
                   {"page": 86, "block_id": "p85_tbl0", "title": "Tabelle 17"})
    section = Source("section", 349525, "Für das Jahr 2040 ...",
                     {"page": 86, "via": "parent", "title": "Zielszenario"})
    payload = runner._field_payload([table, section], rows,
                                    fields.asked_slots(parameter))
    first, second = payload["sources"]
    assert first["block_id"] == "p85_tbl0" and first["page"] == 86
    assert "holds" not in first
    assert second["holds"], "the parent says what it is"


# ---------------------------------------------------------------------------
# How far from a row its evidence may stand
#
# 370 of Kassel's 455 year readings cited a passage outside the row's own
# table and its section, 146 of them the annotated placeholder of a DIFFERENT
# table, and every one of them verified: the passage was real, it was shown,
# and it carried a year. It was just not this row's year.
# ---------------------------------------------------------------------------

def _sources_near_and_far():
    table = Source("table", 87458, "| Erdgas | 42.005 | MWh/a |",
                   {"page": 87, "parent_section": 349525})
    parent = Source("section", 349525,
                    "Tabelle 18: CO2-Emissionen im Zielszenario 2040",
                    {"page": 86})
    neighbour = Source("table", 87457, "| Erdgas | 1 | 2040 |", {"page": 86})
    far = Source("table", 87517, "| Erdgas | 9 | 2030 |", {"page": 163})
    return table, parent, neighbour, far


@pytest.mark.parametrize("rule,which,allowed", [
    ("own", "own", True), ("own", "parent", True),
    ("own", "neighbour", False), ("own", "far", False),
    ("local", "own", True), ("local", "parent", True),
    ("local", "neighbour", True), ("local", "far", False),
    ("any", "own", True), ("any", "neighbour", True), ("any", "far", True),
])
def test_the_axis_decides_how_far_its_evidence_may_stand(rule, which, allowed):
    from docpipe.extraction.pipeline import evidence_is_local
    table, parent, neighbour, far = _sources_near_and_far()
    found = {"own": table, "parent": parent, "neighbour": neighbour,
             "far": far}[which]
    slot = fields.Slot(name="year", kind=fields.NUMBER, question="?",
                       evidence=rule)
    assert evidence_is_local(slot, found, table) is allowed


def test_a_passage_from_another_table_leaves_the_coordinate_open(profile):
    """The promise: a reading whose passage belongs to another row is refused
    AND the row stays open, because the next window shows other passages.

    Refusing without leaving it open would trade a wrong year for a missing
    one. The passage is real and it carries an answer, it just carries
    somebody else's.
    """
    from docpipe.extraction.pipeline import merge_field as merge, open_rows
    batch, rows, slot = _one_row(profile, kind=fields.CHOICE)
    if batch is None:
        pytest.skip("this profile has no choice axis")
    strict = fields.Slot(name=slot.name, kind=slot.kind, question=slot.question,
                         options=slot.options, evidence="own")
    own = batch.items[rows[0].item_index].source
    label = strict.options[0].label
    far = Source("table", 999999, f"Ganz woanders: {label} steht hier.",
                 {"page": 900})
    counts = merge(rows, [far], strict, {"answers": {rows[0].label: {
        "value": label, "value_raw": label,
        "quote": f"Ganz woanders: {label} steht hier."}}},
        owner_of={rows[0].label: own})
    assert counts["filled"] == 0
    assert [f["why"] for f in counts["failed"]] == ["quote_not_local"]
    assert rows[0] in open_rows(rows, strict), "open, so the next window asks"

    # The same reading from the row's own source is taken.
    near = Source(own.owner_kind, own.owner_id,
                  f"In der eigenen Tabelle: {label}.", own.provenance)
    counts = merge(rows, [near], strict, {"answers": {rows[0].label: {
        "value": label, "value_raw": label,
        "quote": f"In der eigenen Tabelle: {label}."}}},
        owner_of={rows[0].label: own})
    assert counts["filled"] == 1


def test_the_kwp_axes_carry_the_rule_their_measurement_calls_for():
    """A row label is read off its own table, a scenario is named nearby, a
    class is argued in a methods chapter anywhere in the plan."""
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    for parameter in spec.parameters:
        rules = {s.name: s.evidence for s in fields.axis_slots(parameter)}
        if not rules:
            continue
        assert rules.get("carrier") == "own"
        assert rules.get("sector") == "own"
        assert rules.get("year") == "local"
        assert rules.get("scenario") == "local"
        assert rules.get("quantity") == "local"


# ---------------------------------------------------------------------------
# Which source is a row's own, and whether the wording names the class chosen
#
# The evidence rule is per axis and about the distance between a passage and
# THIS row (see above). A rule the request does not state is a rule the model
# cannot follow: measured on Kassel, 146 year readings cited the annotated
# placeholder of ANOTHER table out of the passages it was shown, and every one
# of them verified.
# ---------------------------------------------------------------------------

def _row_and_its_neighbours():
    spec, _rows_reply = _two_row_spec_and_reply()
    parameter = spec.parameters[0]
    batch = _batch(parameter)
    rows, _ = rows_from_reply(batch, _value_reply(parameter, batch.label(0)))
    own = Source("table", 87457, "| Erdgas | 1 |",
                 {"page": 86, "block_id": "p85_tbl0", "parent_section": 349525})
    other = Source("table", 87517, "| Erdgas | 9 |",
                   {"page": 162, "block_id": "p162_tbl0",
                    "parent_section": 349566})
    section = Source("section", 349525,
                     "Für das Jahr 2040 ergeben sich ... [p85_tbl0: Tabelle 17]",
                     {"page": 86, "via": "parent"})
    return parameter, rows, own, other, section


def test_the_request_tells_each_row_which_source_is_its_own():
    """By id, not by position: the own table is the SECOND passage here, and
    a model that assumed the first would date every row off table 28."""
    parameter, rows, own, other, section = _row_and_its_neighbours()
    slots = fields.asked_slots(parameter)
    payload = runner._field_payload([other, own, section], rows, slots, None,
                                    {r.label: own for r in rows})
    assert payload["sources"][1]["block_id"] == "p85_tbl0", "Q2 is the own one"
    assert [r["source"] for r in payload["rows"]] == ["Q2"] * len(rows)
    assert [r["section"] for r in payload["rows"]] == ["Q3"] * len(rows)

    # Its parent section is NOT among the shown passages: then the row says
    # nothing about it rather than pointing at whatever else is there.
    payload = runner._field_payload([other, own], rows, slots, None,
                                    {r.label: own for r in rows})
    assert [r["source"] for r in payload["rows"]] == ["Q2"] * len(rows)
    assert all("section" not in r for r in payload["rows"])

    # And with no ownership handed over, neither key is invented.
    bare = runner._field_payload([other, own, section], rows, slots)
    assert all("source" not in r and "section" not in r for r in bare["rows"])


@pytest.mark.parametrize("given,wording,names", [
    ("Erdgas", "Erdgas", True),
    ("Erdgas", "Gas", True),                    # a listed spelling of its own
    ("Erdgas", "Erdgas (H-Gas)", True),         # among other words
    ("Erdgas", "Flüssiggas", False),            # "gas" inside a compound
    ("Erdgas", "Heizöl", False),                # another class' spelling
    ("Biogas", "Klärgas", False),               # Kassel: 29 such readings
    ("Holz", "Holzige Festbrennstoffe", False),  # Kassel: 17
    ("biogener Festbrennstoff", "sonstige biogene Festbrennstoffe", True),
    # The label is in there as a whole word, and it is still not a wording:
    # Kassel offered the rounding footnote as `value_raw` 15 times.
    ("Erdgas", "Hinweis: Wegen der Rundung können beim Summieren der "
               "Erdgas-Zellenwerte Abweichungen auftreten.", False),
])
def test_a_wording_either_names_the_class_it_was_mapped_to_or_it_does_not(
        given, wording, names):
    """field.md rule 2 says the wording is what the mapping is checked
    against. Until now nothing checked it, so a reply could answer "Biogas"
    with the wording "Klärgas" and the quote would verify."""
    from docpipe.extraction.pipeline import wording_names_option
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    slot = next(s for s in fields.axis_slots(spec.parameters[0])
                if s.name == "carrier")
    assert wording_names_option(slot, given, wording) is names


def test_a_wording_that_does_not_name_its_class_is_counted_and_kept(profile):
    """Counted, not refused. Klärgas IS a biogas and the model is allowed to
    say so; what we have no measurement of is how often it decides wrongly,
    and one corpus run of this counter is what settles that."""
    from docpipe.extraction.pipeline import merge_field as merge
    batch, rows, slot = _one_row(profile, kind=fields.CHOICE)
    if batch is None or not slot.options:
        pytest.skip("this profile has no choice axis")
    own = batch.items[rows[0].item_index].source
    label = slot.options[0].label
    passage = f"In der Zeile steht: Unfugwort und {label} nicht."
    source = Source(own.owner_kind, own.owner_id, passage, own.provenance)
    counts = merge(rows, [source], slot, {"answers": {rows[0].label: {
        "value": label, "value_raw": "Unfugwort", "quote": passage}}})
    assert counts["filled"] == 1, "read, because the quote holds the wording"
    assert counts["raw_foreign"] == 1
    assert rows[0].claim[f"{slot.name}_raw_foreign"] is True
    assert rows[0].claim[slot.name] == label, "the reading itself is kept"

    # The same reading with the class' own word is not flagged.
    rows[0].claim.pop(f"{slot.name}_state")
    rows[0].claim.pop(f"{slot.name}_raw_foreign")
    passage = f"In der Zeile steht: {label}."
    source = Source(own.owner_kind, own.owner_id, passage, own.provenance)
    counts = merge(rows, [source], slot, {"answers": {rows[0].label: {
        "value": label, "value_raw": label, "quote": passage}}})
    assert (counts["filled"], counts["raw_foreign"]) == (1, 0)


def test_the_request_says_what_each_option_means(profile):
    """field.md rule 7 says "decide by the meaning, the spellings are only
    examples" and the request never carried a meaning: the model was handed a
    class identifier and a list of German words. The rule was unfollowable,
    and which class a number is is the decision the whole tuple hangs on."""
    name, spec = profile
    if name != "kwp":
        pytest.skip("the meanings are the profile's to write")
    slot = next(s for s in fields.axis_slots(spec.parameters[0])
                if s.name == "quantity")
    offered = slot.answerable()
    assert offered["final energy consumption value"]["bedeutet"].startswith(
        "A final energy consumption value is")
    assert "Endenergiebedarf" in \
        offered["final energy consumption value"]["Schreibweisen"]
    # "The passages do not state it" is an answer like any other and says so.
    assert offered[fields.UNSTATED]["bedeutet"]
    # And every entry the graph does NOT take says what it excludes.
    assert "Nutzwärme" in offered["Nutzenergie"]["bedeutet"]


def test_an_option_list_without_meanings_keeps_the_short_form():
    """A profile that has written no definition pays nothing for the promise:
    the payload is what it was."""
    slot = fields.Slot(name="carrier", kind=fields.CHOICE, question="?",
                       options=(fields.Option(label="Erdgas", uri="OEO_1",
                                              synonyms=("Gas",)),))
    assert slot.answerable() == {
        "Erdgas": ["Gas"],
        fields.UNSTATED: ["steht in diesen Passagen nicht"]}


# ---------------------------------------------------------------------------
# The sweep's stages
#
# Measured on the M3 acceptance run (2026-09-08, 483 tuples, 853 field
# requests). Both promises below were broken there and neither had a test.
# ---------------------------------------------------------------------------

def _sweeping(monkeypatch, spec, rows_reply, *, more=None, rest=None,
              answer=None):
    """A harvester whose field asker records the passages it was shown.

    Answers nothing, ever, so every row stays open and the sweep walks all its
    stages -- which is the only way to see which stages it reaches.
    """
    shown_at = []
    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None):
            shown_at.append([s.owner_id for s in shown])
            if answer is None:
                return {"fields": {}}
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            return {"fields": {slot.name: answer(slot, rows) for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    return runner.make_fieldwise_harvester(
        spec=spec, more_sources=more, rest_of_document=rest), shown_at


def _far_source(owner_id):
    """A section somewhere else in the plan, saying nothing useful."""
    return Source("section", owner_id, "Nichts hierzu.",
                  {"document_id": 7, "page": owner_id})


def test_a_sweep_that_ran_out_of_budget_still_reads_the_rest_of_the_plan(
        monkeypatch):
    """`run` returns False exactly when the budget ran out, and a sweep with
    budget left has no open rows -- so `combed and still_open(rows)` was never
    both true, and the rest stage was dead code. 0 of the 70 sweeps of the M3
    run entered it, and the harvest shows what that cost: 789 coordinates
    exhausted and not one unstated. The stage exists to keep "we stopped
    looking" apart from "the plan does not say it", and it never once ran.
    """
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005, "unit": "MWh/a",
                              "unit_raw": "MWh/a",
                              "quote": "| Erdgas | 42.005 | MWh/a |"}],
                  "status": "complete", "need_more": []}

    asked_rest = []
    served = []

    def more(document_id, queries, exclude):
        # Enough passages in one round to make more windows than the budget
        # allows, so retrieval really runs out. That is the state the old
        # condition could not survive: `run` returns False, `combed` is False,
        # and `combed and still_open(rows)` skipped the stage.
        if served:
            return []
        served.extend(_far_source(9000 + n)
                      for n in range(runner.FIELD_MAX_WINDOWS * 4))
        return list(served)

    def rest(document_id, exclude):
        asked_rest.append(len(exclude))
        return [_far_source(7001), _far_source(7002)]

    harvest, shown = _sweeping(monkeypatch, spec, rows_reply,
                               more=more, rest=rest)
    harvest(_document_batch())

    assert asked_rest, "the rest of the plan was never read"
    # It really was the exhausted case, not a sweep that had budget left.
    assert len([w for w in shown if w and min(w) >= 9000])         == runner.FIELD_MAX_WINDOWS - 1, shown   # the own window took one
    # And the last stage got its own bounded allowance rather than the
    # leftovers of a budget retrieval had already spent to the last request.
    from_rest = [w for w in shown if 7001 in w or 7002 in w]
    assert from_rest, "no allowance, so the stage ran and asked nothing"
    assert len(from_rest) <= runner.REST_MAX_WINDOWS, len(from_rest)


def test_a_window_is_asked_again_only_where_asking_again_pays(monkeypatch):
    """A retry of the OWN window filled 4.88 rows on the M3 run, a third of
    what a fresh own window fills. A retry further out filled 0.10, a seventh
    of the fresh window it displaces, and 145 of 149 third attempts filled
    nothing at all. `state["asked"]` counts every attempt against the budget,
    so out there a retry is a window spent on a question that already failed.
    """
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005, "unit": "MWh/a",
                              "unit_raw": "MWh/a",
                              "quote": "| Erdgas | 42.005 | MWh/a |"}],
                  "status": "complete", "need_more": []}

    rounds = []

    def more(document_id, queries, exclude):
        rounds.append(len(rounds))
        return [_far_source(9100 + len(rounds))] if len(rounds) <= 2 else []

    def unbackable(slot, rows):
        # An answer whose quote is in none of the shown passages. That is what
        # makes a window worth asking again -- and what made 334 of the M3
        # run's 853 requests a repeat of a question that had already failed.
        return {"answers": {row.label: {"value": "Erdgas",
                                        "quote": "steht in keiner Passage"}
                            for row in rows}}

    harvest, shown = _sweeping(monkeypatch, spec, rows_reply, more=more,
                               answer=unbackable)
    harvest(_document_batch())

    from collections import Counter
    per_window = Counter(tuple(sorted(w)) for w in shown)
    own = [n for window, n in per_window.items() if 0 in window]
    far = [n for window, n in per_window.items()
           if window and min(window) >= 9100]
    assert own and all(n == runner.FIELD_ATTEMPTS for n in own), per_window
    assert far and all(n == 1 for n in far), per_window
