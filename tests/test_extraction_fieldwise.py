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
                usage_out=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            for slot in slots:
                asked.append(slot.name)
            return {"fields": {slot.name: answers(slot, rows)
                               for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    return runner.make_fieldwise_harvester(spec=spec), asked


def test_which_quantity_a_number_is_gets_asked_before_its_axes(monkeypatch):
    """The plan used to fix the parameter, so a table holding a consumption and
    an emission was retrieved, read and paid for twice — 804 planned sources
    against 234 owners. Asked instead of assumed, it is a coordinate like any
    other and decides which coordinates the row even has."""
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    consumption = spec.parameters[0]
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005, "unit": "MWh/a",
                              "unit_raw": "MWh/a",
                              "quote": "| Erdgas | 42.005 | MWh/a |"}],
                  "status": "complete", "need_more": []}

    def answers(slot, rows):
        if slot.name == "parameter":
            # The wording the passage really carries is the unit, and the
            # class it stands for is the quantity. That is what value_raw is
            # for: a plan hardly ever prints the word "Endenergieverbrauch"
            # next to the number, it prints MWh/a.
            return {"answers": {"R1": {
                "value": consumption.label, "value_raw": "MWh/a",
                "quote": "| Erdgas | 42.005 | MWh/a |"}}}
        return {"answers": {}}

    harvest, asked = _fieldwise(monkeypatch, spec, rows_reply, answers)
    reply = harvest(_document_batch())

    assert asked[0] == "parameter", "the parameter gates the rest"
    axes = {s.name for s in fields.axis_slots(consumption)}
    assert axes <= set(asked[1:]), "then the axes of the parameter it turned out to be"
    assert reply["tuples"][0]["parameter"] == consumption.uri, (
        "the label the model picked is stored as the class it stands for")


def test_a_row_whose_quantity_stayed_unread_is_not_given_a_guessed_axis(
        monkeypatch):
    """Refusing it later is the point: a row with no parameter has no
    coordinates to fill, and filling the first parameter's would be a guess
    written down as a reading."""
    spec = load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005, "unit": "MWh/a",
                              "unit_raw": "MWh/a",
                              "quote": "| Erdgas | 42.005 | MWh/a |"}],
                  "status": "complete", "need_more": []}

    harvest, asked = _fieldwise(
        monkeypatch, spec, rows_reply,
        lambda slot, rows: {"answers": {"R1": {"value": fields.UNSTATED}}})
    reply = harvest(_document_batch())

    assert asked == ["parameter"], "no axis is asked for a row with no quantity"
    row = reply["tuples"][0]
    assert row["parameter_state"] in (fields.EXHAUSTED, fields.SAID_UNSTATED)
    assert not any(k.endswith("_state") and k != "parameter_state" for k in row)


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
                usage_out=None):
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

    gate_order = [name for name, _rows in asked][:3]
    assert gate_order == ["parameter", "quantity", "scenario"], (
        "the gate is asked first and in order")
    after = {name: rows for name, rows in asked[3:]}
    assert after, "the row that stayed is still asked for its axes"
    assert all(rows == ["R1"] for rows in after.values()), (
        "and only that row: R2 fell out at the quantity")

    out = next(t for t in reply["tuples"] if t.get("value") == 99)
    for axis in fields.axis_slots(spec.parameters[0]):
        if axis.name in ("quantity", "scenario"):
            continue
        assert out.get(f"{axis.name}_state") == fields.OUT_OF_SLICE, (
            f"{axis.name} was never asked and has to say so")


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
                usage_out=None):
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

    assert len(calls) == 3, (
        "one for the parameter, one for the gate, one for the rest — not one "
        "per coordinate: %s" % calls)
    assert calls[0] == ["parameter"]
    assert calls[1] == ["quantity", "scenario"]
    assert len(calls[2]) == len(fields.axis_slots(consumption)) - 2

    # Every field of the one reply is folded on its own.
    row = reply["tuples"][0]
    assert row["quantity_state"] == fields.READ
    assert row["scenario_state"] == fields.READ
    assert row["carrier_state"] == fields.READ
    assert row["carrier_quote"] == quote, "and carries its own evidence"


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
