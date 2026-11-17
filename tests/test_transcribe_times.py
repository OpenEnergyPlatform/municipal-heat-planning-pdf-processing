"""A figure transcribed several times, each number the median of them (rules
`transcribe_times` and `transcribe_temperature`, addressed.py `Transcripts`
and `merge_transcripts`; owner decision 2026-11-17, from the literature on
transcribing a chart several times, Self-Ensembling 2026), each promise with
a case that breaks it by construction.

1. A figure is transcribed `transcribe_times` times AND a number of a line
   that all transcriptions print in the same words is the median of their
   values, written as the transcription it comes from printed it.
2. A line only the first transcription has stays as it has it AND a line only
   a later one has is not added AND the caption is the first's.
3. With 1 the figure is asked once and its transcript is kept as it is under
   the key it always had.
4. The repeats are asked at `transcribe_temperature` AND are never answered
   from the request cache AND are noted as repeats; the first transcription
   is asked as before.
5. A transcript kept under 3 is asked again under 1 and the other way round.
6. A number is read as the harvest reads a printed one: a printed sign
   belongs to it (rule `sign_belongs`), a number grouped by spaces is one
   number, AND the dash of a span after a digit is no sign.
7. The events the run writes for it are records of the trace schema AND the
   statistics total them.
"""
import json

import jsonschema
import pytest

from docpipe import rules
from docpipe.extraction import addressed, schema, stats
from test_addressed import CAPTION, FIGURE


def kept_under(tmp_path, answers, seen=None, trace=None, prompt="p1"):
    """Transcripts whose model answers *answers* one after the other."""
    queue = list(answers)

    def ask(source, document_id):
        if seen is not None:
            seen.append((rules.get("temperature"),
                         rules.get("same_request_once"),
                         addressed.REPEAT.get()))
        return queue.pop(0)
    return addressed.Transcripts(ask, tmp_path, prompt, lambda source: "img",
                                 trace=trace)


def reply(*numbers, caption=CAPTION):
    return {"caption": list(caption), "numbers": list(numbers)}


def test_each_number_is_the_median_written_as_its_transcription_wrote_it(
        tmp_path):
    answers = [reply("Erdgas: 100 MWh"), reply("Erdgas: 120 MWh"),
               reply("Erdgas: 110,0 MWh")]
    with rules.overlaid(transcribe_times=3):
        got, asked = kept_under(tmp_path, answers)(7, [FIGURE])
    # the transcription that read 110 printed it "110,0"; it is not
    # re-spelled, not averaged and not the first's 100
    assert got[5]["numbers"] == ["Erdgas: 110,0 MWh"]
    assert asked == 1
    # the failure by construction: two transcriptions are never a median
    # of three, the lower of the two stands
    answers = [reply("Erdgas: 100 MWh"), reply("Erdgas: 120 MWh")]
    other = tmp_path / "two"
    with rules.overlaid(transcribe_times=2):
        got, _ = kept_under(other, answers)(7, [FIGURE])
    assert got[5]["numbers"] == ["Erdgas: 100 MWh"]
    # and every number of a line of several numbers is its own median
    many = tmp_path / "many"
    answers = [reply("A: 1 und 50"), reply("A: 3 und 20"),
               reply("A: 2 und 30")]
    with rules.overlaid(transcribe_times=3):
        got, _ = kept_under(many, answers)(7, [FIGURE])
    assert got[5]["numbers"] == ["A: 2 und 30"]


def test_a_line_that_does_not_match_stays_and_a_later_only_line_is_not_added(
        tmp_path):
    first = reply("Erdgas: 100 MWh", "Heizöl: 27 MWh", "Gleich: 5 MWh",
                  caption=["Titel 1"])
    second = reply("Erdgas: 120 MWh", "Kohle: 9 MWh", "Gleich: 5 MWh",
                   "Gleich: 6 MWh", caption=["Titel 2"])
    third = reply("Erdgas: 110 MWh", "Gleich: 5 MWh", caption=["Titel 3"])
    with rules.overlaid(transcribe_times=3):
        got, _ = kept_under(tmp_path, [first, second, third])(7, [FIGURE])
    lines = got[5]["numbers"]
    assert lines[0] == "Erdgas: 110 MWh"
    # only the first has it: as it has it
    assert lines[1] == "Heizöl: 27 MWh"
    # one later transcription prints its words twice: no match
    assert lines[2] == "Gleich: 5 MWh"
    # only a later transcription has it: not added
    assert len(lines) == 3 and not any("Kohle" in line for line in lines)
    assert got[5]["caption"] == ["Titel 1"]
    # the failure by construction: the number count of a line must be the
    # same in every transcription
    merged, tally = addressed.merge_transcripts([
        reply("Erdgas: 100 MWh"), reply("Erdgas: 120 MWh"),
        reply("Erdgas: 110 MWh")])
    assert tally == {"lines": 1, "changed": 1}
    merged, tally = addressed.merge_transcripts([
        reply("Erdgas: 100 MWh"), reply("Erdgas: 120 MWh"),
        reply("Erdgas: 110 MWh 2021")])
    assert merged["numbers"] == ["Erdgas: 100 MWh"]
    assert tally == {"lines": 0, "changed": 0}
    # the words are compared folded and with their spaces collapsed
    merged, _ = addressed.merge_transcripts([
        reply("Erdgas:  100 MWh"), reply("ERDGAS: 120 MWh")])
    assert merged["numbers"] == ["Erdgas:  100 MWh"]
    merged, _ = addressed.merge_transcripts([
        reply("Erdgas: 120 MWh"), reply("ERDGAS: 100 MWh")])
    assert merged["numbers"] == ["Erdgas: 100 MWh"]


def test_an_unreadable_number_keeps_the_first_s_text(monkeypatch):
    answers = [reply("A: 5 und 1"), reply("A: 7 und 2"), reply("A: 6 und 3")]
    merged, tally = addressed.merge_transcripts(answers)
    assert merged["numbers"] == ["A: 6 und 2"]
    assert tally == {"lines": 1, "changed": 2}
    # the failure by construction: where a transcription's number cannot be
    # read (here the parser reads no 7) the first's text stays at that place
    # and the other numbers of the line are medians still
    parse = addressed.canonical_number
    monkeypatch.setattr(addressed, "canonical_number",
                        lambda text, *a: None if text == "7" else
                        parse(text, *a))
    merged, tally = addressed.merge_transcripts(answers)
    assert merged["numbers"] == ["A: 5 und 2"]
    assert tally == {"lines": 1, "changed": 1}


def test_one_time_asks_once_and_keeps_the_transcript_under_its_old_key(
        tmp_path):
    only = reply("Erdgas: 100 MWh")
    seen: list = []
    with rules.overlaid(transcribe_times=1):
        got, asked = kept_under(tmp_path, [only, reply("Erdgas: 1 MWh")],
                                seen)(7, [FIGURE])
    assert got[5] == only and asked == 1
    assert len(seen) == 1 and seen[0][2] == 0
    entry = json.loads((tmp_path / "7.json").read_text(encoding="utf-8"))["5"]
    assert entry["prompt"] == "p1"
    # the failure by construction: three times changes the key
    other = tmp_path / "three"
    with rules.overlaid(transcribe_times=3):
        kept_under(other, [only, only, only])(7, [FIGURE])
    entry = json.loads((other / "7.json").read_text(encoding="utf-8"))["5"]
    assert entry["prompt"] != "p1"


def test_the_repeats_are_asked_at_their_temperature_and_not_from_the_cache(
        tmp_path):
    seen: list = []
    answers = [reply("Erdgas: 100 MWh")] * 3
    with rules.overlaid(transcribe_times=3, transcribe_temperature=1.3,
                        temperature=0.2, same_request_once=True):
        kept_under(tmp_path, answers, seen)(7, [FIGURE])
        # the overlay of a repeat does not outlast it
        assert rules.get("temperature") == 0.2
        assert rules.get("same_request_once") is True
    # (temperature, same_request_once, the number of the repeat)
    assert seen == [(0.2, True, 0), (1.3, False, 2), (1.3, False, 3)]
    # the failure by construction: with 1 no request is a repeat
    seen.clear()
    with rules.overlaid(transcribe_times=1, transcribe_temperature=1.3,
                        temperature=0.2, same_request_once=True):
        kept_under(tmp_path / "one", answers, seen)(7, [FIGURE])
    assert seen == [(0.2, True, 0)]


def test_a_kept_transcript_is_asked_again_under_another_number_of_times(
        tmp_path):
    lines = reply("Erdgas: 100 MWh")
    with rules.overlaid(transcribe_times=3):
        assert kept_under(tmp_path, [lines] * 3)(7, [FIGURE])[1] == 1
        # kept: asked nothing
        assert kept_under(tmp_path, [])(7, [FIGURE])[1] == 0
    with rules.overlaid(transcribe_times=1):
        assert kept_under(tmp_path, [lines])(7, [FIGURE])[1] == 1
        assert kept_under(tmp_path, [])(7, [FIGURE])[1] == 0
    with rules.overlaid(transcribe_times=3):
        assert kept_under(tmp_path, [lines] * 3)(7, [FIGURE])[1] == 1
    # another temperature of the repeats is another transcript, too
    with rules.overlaid(transcribe_times=3, transcribe_temperature=0.1):
        assert kept_under(tmp_path, [lines] * 3)(7, [FIGURE])[1] == 1


def test_the_event_is_a_record_of_the_schema_and_the_statistics_total_it(
        tmp_path):
    events: list = []
    answers = [reply("Erdgas: 100 MWh"), reply("Erdgas: 120 MWh"),
               reply("Erdgas: 110 MWh")]
    with rules.overlaid(transcribe_times=3):
        kept_under(tmp_path, answers,
                   trace=lambda *a, **k: events.append((a, k)))(7, [FIGURE])
    ((kind, document), fields), = events
    assert kind == "transcribed_again" and document == 7
    assert fields == {"times": 3, "figures": 1, "requests": 2, "lines": 1,
                      "numbers_changed": 1}
    record = {"t": kind, "doc": document, **fields}
    record_schema = schema.trace_schema()
    jsonschema.validate(record, record_schema)
    jsonschema.validate({"t": "transcribe_ask", "doc": 7, "attempt": 1,
                         "repeat": 2, "prompt_tokens": 1,
                         "completion_tokens": 1, "ms": 1, "kind": "figure",
                         "owner": 5}, record_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**record, "guessed": 1}, record_schema)
    (tmp_path / "a.trace.jsonl").write_text(
        json.dumps(record) + "\n" + json.dumps({**record, "doc": 8}) + "\n",
        encoding="utf-8")
    got = stats.from_traces([tmp_path])["figures_transcribed_again"]
    assert got == {"documents": 2, "figures": 2, "requests": 4, "lines": 2,
                   "numbers_changed": 2}
    # the failure by construction: no trace, nothing totalled
    empty = tmp_path / "none"
    empty.mkdir()
    assert stats.from_traces([empty])["figures_transcribed_again"][
        "figures"] == 0


def test_a_number_is_read_with_its_sign_and_its_space_grouping():
    merged, tally = addressed.merge_transcripts([
        reply("Erdgas -5 MWh"), reply("Erdgas 5 MWh"),
        reply("Erdgas -5 MWh")])
    assert merged["numbers"] == ["Erdgas -5 MWh"]
    assert tally == {"lines": 1, "changed": 0}
    # the failure by construction: with the sign outside the number the
    # words differ ("erdgas -#" and "erdgas #") and the lines do not match
    with rules.overlaid(sign_belongs="off"):
        merged, tally = addressed.merge_transcripts([
            reply("Erdgas -5 MWh"), reply("Erdgas 5 MWh"),
            reply("Erdgas -5 MWh")])
    assert tally["lines"] == 0
    merged, tally = addressed.merge_transcripts([
        reply("Wärme 45 000 MWh"), reply("Wärme 45 500 MWh"),
        reply("Wärme 45 000 MWh")])
    assert merged["numbers"] == ["Wärme 45 000 MWh"]
    assert tally == {"lines": 1, "changed": 0}
    # the failure by construction: 45 500 as the middle one is written as
    # that transcription wrote it, with its space, and "45" and "000" are
    # not two numbers
    merged, tally = addressed.merge_transcripts([
        reply("Wärme 45 000 MWh"), reply("Wärme 45 500 MWh"),
        reply("Wärme 45 400 MWh")])
    assert merged["numbers"] == ["Wärme 45 400 MWh"]
    assert tally == {"lines": 1, "changed": 1}
    # a span after a digit is two numbers joined by a dash, no sign
    merged, tally = addressed.merge_transcripts([
        reply("Ziel 2020-2030"), reply("Ziel 2020-2035"),
        reply("Ziel 2020-2040")])
    assert merged["numbers"] == ["Ziel 2020-2035"]
    assert tally == {"lines": 1, "changed": 1}
