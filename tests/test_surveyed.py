"""A run reads each plan passage by passage, so its spec names groups and its
profile writes every prompt of that flow, or the run stops; its stamps and
producers record the flow and the prompts it sends, and the server's window
is measured over them.

What nothing could read is a hole with its reason: a reading that came to no
readable reply goes under its reason and names its parameter. Folded, a
parameter whose only passage was a hole ends exhausted, one whose passage was
read and held nothing unstated. A document none of whose readings came back
is no reply at all. A harvest halted after its order reads nothing.

With --start-at the order covers the found passages under its own scope, and
a parameter no earlier harvest was asked is read over the rest of the plan
too.

A pass re-reads a coordinate by combing it, whatever its state, in its own
passage first and with the years of the stored rows; the combing lists the
passages an earlier harvest read it in, AND a stored row, which carries no
sentence of the reading, ranks no search of its own. A request
whose last attempt ended on a 429 leaves its document unserved, and one that
timed out is asked again with the time of a repeat, one refused by the
server with the time it had.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import (combing, fields, reading, runner, survey,
                                surveyed, years)
from docpipe.extraction.pipeline import (Batch, DocumentReport, Row, Source,
                                         WorkItem)
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import parameter_states


def answered(thread, reply):
    """What the run keeps of an answer (`runner.ask_in_grammar`): a reply
    the conversation goes on after (owner decisions 2026-11-07)."""
    if thread is not None and isinstance(reply, dict):
        thread.messages = [*thread.messages, {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
HEAT_LOAD = SPEC.by_uri["heat_load"]
UNANSWERED_STATES = (fields.UNANSWERED,)


def passage(kind, number, text, title):
    return Source(kind, number, text, {"document_id": 7,
                                       "section_title": title})


ONE = passage("section", 1, "Bilanz\nEs fielen rund 300 t CO2 an.", "Bilanz")
TWO = passage("table", 2, "| Jahr | Last |\n| 2022 | 40 MW |", "Lasten")
THREE = passage("section", 3, "Ausblick\nDie Werte gelten für 2030.",
                "Ausblick")
SHOWN = {(s.owner_kind, s.owner_id): s for s in (ONE, TWO, THREE)}


def answer(source, *parameters):
    owner = (source.owner_kind, source.owner_id)
    return survey.Answer(owner, list(parameters), {}, [])


def found_of(*answers, unanswered=()):
    return survey.Found(True, {a.owner: a for a in answers},
                        [(s.owner_kind, s.owner_id) for s in unanswered])


def read_of(parameter, source, claims=(), why=None):
    batch = Batch(7, parameter, [WorkItem(7, parameter, source)])
    return reading.Read(batch, list(claims), unread=why is not None, why=why)


def sentinels(taken):
    return [(batch, claim) for batch, reply in taken.answered
            for claim in reply["tuples"] if claim.get("_harvest_failed")]


# -- holes ---------------------------------------------------------------------

def test_a_reading_with_no_readable_reply_is_a_hole_that_names_its_parameter():
    claim = {"source": "Q1", "value": 300, "quote": "rund 300 t CO2"}
    taken = surveyed.taken_of(
        7, SPEC, found_of(answer(ONE, "emission"), answer(TWO, "heat_load")),
        [read_of(EMISSION, ONE, why=reading.CUT),
         read_of(HEAT_LOAD, TWO, [claim])], [], SHOWN)
    holes = sentinels(taken)
    assert [(c["_why"], c["_parameter"]) for _b, c in holes] == [
        (reading.CUT, "emission")]
    assert holes[0][0].items[0].source is ONE
    # The reading that came back goes as its values.
    assert [reply["tuples"] for batch, reply in taken.answered
            if batch.parameter is HEAT_LOAD] == [[claim]]


def test_a_part_of_a_table_no_reply_answered_is_a_hole_beside_its_values():
    claim = {"source": "Q1", "value": 40, "quote": "| 2022 | 40 MW |"}
    read = read_of(HEAT_LOAD, TWO, [claim])
    read.lost = [reading.CUT]
    taken = surveyed.taken_of(7, SPEC, found_of(answer(TWO, "heat_load")),
                              [read], [], SHOWN)
    assert [(c["_why"], c["_parameter"]) for _b, c in sentinels(taken)] \
        == [(reading.CUT, "heat_load")]
    assert [reply["tuples"] for batch, reply in taken.answered
            if batch.parameter is HEAT_LOAD] == [[claim]]
    read.lost = []
    assert sentinels(surveyed.taken_of(
        7, SPEC, found_of(answer(TWO, "heat_load")), [read], [], SHOWN)) == []


def test_a_reading_says_why_it_came_to_nothing():
    def reader(reply):
        def ask(*args, **kwargs):
            return reply
        return reading.Reader(SPEC, ask, ask)

    cut = reader(reading.CUT).read(7, EMISSION, ONE, [], SHOWN)
    silent = reader(None).read(7, EMISSION, ONE, [], SHOWN)
    assert cut.unread and cut.why == reading.CUT
    assert silent.unread and silent.why == reading.NO_ANSWER
    answered = reader({"values": [], "incomplete": False}).read(
        7, EMISSION, ONE, [], SHOWN)
    assert not answered.unread and answered.why is None


def test_a_parameter_whose_passage_was_a_hole_is_exhausted_not_unstated():
    taken = surveyed.taken_of(
        7, SPEC, found_of(answer(ONE, "emission"), answer(TWO, "heat_load")),
        [read_of(EMISSION, ONE, why=reading.NO_ANSWER),
         read_of(HEAT_LOAD, TWO)], [], SHOWN)
    report = DocumentReport(document_id=7, owners_harvested=taken.passages,
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=None, spec=SPEC)
    assert [r["claim"]["_why"] for r in report.refusals
            if r["claim"].get("_harvest_failed")] == [reading.NO_ANSWER]
    states = {s["parameter"]: s["state"] for s in parameter_states(
        SPEC, report.tuples, report.refusals,
        harvested=report.owners_harvested, answered=taken.replies,
        sources_of=report.sources_of)}
    assert states["emission"] == fields.EXHAUSTED
    assert states["heat_load"] == fields.SAID_UNSTATED


def test_a_document_none_of_whose_readings_came_back_is_no_reply_at_all():
    # Owner decisions 2026-11-08: every passage is read for every parameter,
    # so a reply is a reading that came back, not a passage ordered.
    found = found_of(answer(ONE, "emission"), answer(TWO, "emission"))
    silent = surveyed.taken_of(
        7, SPEC, found, [read_of(EMISSION, ONE, why=reading.NO_ANSWER),
                         read_of(EMISSION, TWO, why=reading.CUT)], [], SHOWN)
    assert silent.replies == 0 and silent.passages == 2
    report = DocumentReport(document_id=7, owners_harvested=silent.passages)
    runner.fold_answers(silent.answered, report, locate=None, spec=SPEC)
    assert runner.not_happened(report, answered=silent.replies)[0] \
        == "no_reply"
    # A plan whose passages hold no number came back: a reply, no hole.
    numberless = surveyed.taken_of(
        7, SPEC, found, [read_of(EMISSION, ONE), read_of(EMISSION, TWO)], [],
        SHOWN)
    report = DocumentReport(document_id=7,
                            owners_harvested=numberless.passages)
    runner.fold_answers(numberless.answered, report, locate=None, spec=SPEC)
    assert numberless.replies == 2
    assert runner.not_happened(report, answered=numberless.replies) is None


# -- the harvest of one document -------------------------------------------------

def harvest(found, *, halted=False, reads=()):
    made, read_calls = [], []

    def make_survey(spec, only, scope):
        def run(document_id, passages):
            made.append((only, scope, [(s.owner_kind, s.owner_id)
                                       for s in passages]))
            return found
        return run

    def make_reader(spec):
        def run(document_id, found, shown, budget):
            read_calls.append(found)
            return list(reads)
        return run

    whole = surveyed.SurveyedHarvest(
        SPEC, make_survey, make_reader, lambda spec: None,
        lambda document_id: [ONE, TWO, THREE], lambda document_id: 2,
        halted=lambda: halted)
    return whole, made, read_calls


def test_a_harvest_halted_after_its_order_reads_nothing():
    whole, made, read_calls = harvest(found_of(answer(ONE, "emission")),
                                      halted=True)
    assert whole(7) is None
    assert made and not read_calls
    whole, made, read_calls = harvest(found_of(answer(ONE, "emission")))
    assert whole(7) is not None and read_calls


def test_start_at_orders_the_found_passages_and_a_gained_parameter_the_rest():
    whole, made, _reads = harvest(found_of(answer(ONE, "emission")))
    surveyed.take_found(whole, 7, [ONE], ["building_count"])
    assert ((), "found", [("section", 1)]) in made
    assert (("building_count",), "gained",
            [("table", 2), ("section", 3)]) in made
    whole, made, _reads = harvest(found_of(answer(ONE, "emission")))
    surveyed.take_found(whole, 7, [ONE], [])
    assert [scope for _only, scope, _passages in made] == ["found"]


# -- passes over a stored harvest ------------------------------------------------

def test_a_pass_combs_a_coordinate_in_its_own_passage_first():
    calls = []

    class Comber(combing.Comber):
        def comb(self, document_id, parameter, source, slots, claims,
                 passages, pairs, budget, **given):
            calls.append((source, [s.name for s in slots], claims, given))

    sweep = surveyed.comb_sweep(
        lambda spec: Comber(SPEC, None, None, None), lambda d: SPEC,
        lambda d, exclude: [ONE, TWO, THREE], lambda d: 2)
    slots = {s.name: s for s in reading.slots_of(SPEC, EMISSION)}
    batch = Batch(7, EMISSION, [WorkItem(7, EMISSION, ONE),
                                WorkItem(7, EMISSION, THREE)],
                  bases=(("status_quo", 2022),))
    first, second = {"value": 300}, {"value": 310}
    rows = [Row("R1", 0, first), Row("R2", 1, second)]
    sweep(batch, rows, [slots["year"]])
    assert [(c[0], c[2]) for c in calls] == [(ONE, [first]),
                                             (THREE, [second])]
    assert all(c[1] == ["year"] and c[3]["coordinates"] == ["year"]
               and c[3]["own"] and c[3]["bases"] == (("status_quo", 2022),)
               for c in calls)
    # Coordinates of two groups: one conversation per value (owner decision
    # 2026-11-07), asking both.
    calls.clear()
    sweep(batch, rows, [slots["year"], slots["carrier"]])
    assert [(c[0], c[1], c[3]["coordinates"]) for c in calls] == [
        (ONE, ["year", "carrier"], ["year", "carrier"]),
        (THREE, ["year", "carrier"], ["year", "carrier"])]


def comber(*replies, ranked=()):
    asked = []

    def ask(payload, shape, document_id, source, group=None, example=None,
            thread=None, follow=None):
        # A follow-up as its message shows it (owner decisions 2026-11-07).
        asked.append(payload if follow is None
                     else {**follow, "follows": True})
        return answered(thread, replies[min(len(asked), len(replies)) - 1])

    made = combing.Comber(SPEC, ask,
                          lambda d, probes, exclude: [
                              s for s in ranked
                              if (s.owner_kind, s.owner_id) not in exclude],
                          lambda claim, names: {})
    return made, asked


def everything():
    return {s.name: {"value": fields.UNSTATED}
            for s in reading.slots_of(SPEC, EMISSION)}


def stored_row():
    claim = {"value": 300, "quote": "rund 300 t CO2", "unit": "t CO2",
             "unit_state": fields.READ, "carrier": "Erdgas",
             "carrier_state": fields.READ}
    for slot in reading.slots_of(SPEC, EMISSION):
        claim.setdefault(f"{slot.name}_state", fields.SAID_UNSTATED)
    return claim


def test_a_named_coordinate_is_asked_whatever_its_state_in_its_own_passage():
    carrier = next(s for s in reading.slots_of(SPEC, EMISSION)
                   if s.name == "carrier")
    made, asked = comber({"carrier": {"value": fields.UNSTATED}})
    claim = stored_row()
    made.comb(7, EMISSION, ONE, [carrier], [claim], SHOWN, [], None,
              coordinates=["carrier"], own=True)
    assert list(asked[0]["coordinates"]) == ["carrier"]
    # What the older question read there stands no more: not among the
    # answers shown, and the passage itself is shown.
    assert "carrier" not in asked[0]["read"]
    assert [m["text"] for m in asked[0]["more"]] == [ONE.text]
    # Not named and read: not asked at all.
    made, asked = comber({})
    made.comb(7, EMISSION, ONE, [carrier], [stored_row()], SHOWN, [], None)
    assert asked == []


def test_the_passages_read_before_are_listed_and_a_stored_row_ranks_none():
    year = next(s for s in reading.slots_of(SPEC, EMISSION)
                if s.name == "year")
    made, asked = comber({"rows": []}, ranked=(TWO, THREE))
    made.comb(7, EMISSION, ONE, [year], [stored_row()], SHOWN, [], None,
              first=[TWO])
    # The second reading's message shows the section after the value's
    # place; the search's first message lists the passage read before.
    search = [p for p in asked if "coordinates" in p][1]
    assert [hit["title"] for hit in search["hits"][0]["hits"]] == ["Lasten"]
    # A stored row carries no sentence: no list, the model searches itself.
    made, asked = comber({"rows": []}, ranked=(TWO, THREE))
    made.comb(7, EMISSION, ONE, [year], [stored_row()], SHOWN, [], None)
    search = [p for p in asked if "coordinates" in p][1]
    assert "hits" not in search


def test_a_request_whose_last_attempt_hit_a_429_leaves_its_document_unserved(
        monkeypatch):
    class Refused(Exception):
        status_code = 429

    answered = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"rows": []}'),
        finish_reason="stop")], usage=None)

    def client(*outcomes):
        left = list(outcomes)

        def create(**kwargs):
            outcome = left.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "answer_room", lambda *a, **k: 4096)
    prompt = SimpleNamespace(meta={}, text="x")
    runner.UNSERVED.clear()
    refused = [Refused() for _ in range(runner.MAX_RETRIES)]
    assert runner.ask_in_grammar(client(*refused), prompt, [], {}, 71,
                                 "comb", "rows") is None
    assert runner.UNSERVED.of(71) == 1
    reply = runner.ask_in_grammar(client(Refused(), answered), prompt, [], {},
                                  72, "comb", "rows")
    assert reply == {"rows": []} and runner.UNSERVED.of(72) == 0
    runner.UNSERVED.clear()


def test_a_request_that_timed_out_is_asked_again_with_the_time_of_a_repeat(
        monkeypatch):
    import httpx
    import openai

    answered = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"rows": []}'),
        finish_reason="stop")], usage=None)
    times = []

    def client(first):
        left = [first, answered]

        def create(**kwargs):
            times.append(kwargs.get("timeout"))
            outcome = left.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))

    class Failed(Exception):
        status_code = 500

    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "answer_room", lambda *a, **k: 4096)
    prompt = SimpleNamespace(meta={}, text="x")
    slow = openai.APITimeoutError(request=httpx.Request("POST", "http://x"))
    assert runner.ask_in_grammar(client(slow), prompt, [], {}, 73,
                                 "read_text", "rows") == {"rows": []}
    assert times == [None, runner.RETRY_TIMEOUT]
    times.clear()
    runner.ask_in_grammar(client(Failed()), prompt, [], {}, 74, "read_text",
                          "rows")
    assert times == [None, None]        # a server error is no timeout
    runner.UNSERVED.clear()


# -- the flow ------------------------------------------------------------------

def test_a_spec_with_groups_and_every_prompt_harvests_passage_by_passage(
        monkeypatch):
    assert runner.surveyed_flow(SPEC)
    assert not runner.surveyed_flow(replace(SPEC, groups={}))
    monkeypatch.setattr(runner, "FLOW", runner.SURVEYED)
    entry = runner.producer("harvest", "m")
    assert entry["flow"] == runner.SURVEYED
    # And the plan's years, which this profile asks once per plan (owner
    # decision 2026-11-06).
    sent = (*runner.SURVEY_PROMPT_IDS, years.YEARS_PROMPT_ID)
    assert set(entry["prompts"]) == set(sent)
    assert set(sent) <= set(runner._stamp_current("sha", "", SPEC))
    assert runner.survey_prompt_ids() == sent


def test_a_spec_without_groups_stops_the_run(tmp_path, monkeypatch, capsys):
    raw = json.loads((Path(__file__).resolve().parent.parent / "profiles"
                      / "kwp" / "extraction_spec.json").read_text(
        encoding="utf-8"))
    del raw["groups"]
    folder = tmp_path / "trial"
    folder.mkdir()
    (folder / "spec.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("DOCPIPE_USAGE_DB", str(tmp_path / "usage.db"))
    with pytest.raises(SystemExit) as stopped:
        runner.main([str(tmp_path / "corpus.db"), str(tmp_path / "x.index"),
                     str(folder / "out"), "--spec", str(folder / "spec.json"),
                     "--profile", "kwp"])
    assert stopped.value.code == 2
    assert "needs groups" in capsys.readouterr().err


def test_a_spec_with_groups_and_a_missing_prompt_stops_and_names_it(
        monkeypatch):
    real = runner.prompts.load
    for missing in runner.SURVEY_PROMPT_IDS:
        def load(prompt_id, profile=None, _missing=missing):
            if prompt_id == _missing:
                raise FileNotFoundError(prompt_id)
            return real(prompt_id, profile)

        monkeypatch.setattr(runner.prompts, "load", load)
        with pytest.raises(LookupError) as stopped:
            runner.surveyed_flow(SPEC)
        assert missing in str(stopped.value)
        # A spec without groups is never harvested: no prompt is looked
        # at, and the run stops on it elsewhere.
        assert not runner.surveyed_flow(replace(SPEC, groups={}))


# Promise: a row read for the one field its request asked carries the state of
# its parameter coordinate, derived, since nobody asked it per row, AND such a
# row matches the published harvest schema (owner decision 2026-11-05).
SCENARIOS = load_spec(json.loads((Path(__file__).resolve().parent.parent
                            / "profiles" / "scenarios" / "extraction_spec.json")
                           .read_text(encoding="utf-8")))


def test_a_row_read_for_one_field_has_its_parameter_derived():
    title = SCENARIOS.by_uri["publication_title"]
    front = passage("section", 1, "Net zero by 2050\nAda Lovelace",
                    "Net zero by 2050")
    read = reading.Read(Batch(7, title, [WorkItem(7, title, front)]),
                        [{"source": "Q1", "value": "Net zero by 2050",
                          "quote": "Net zero by 2050",
                          "work_state": fields.UNANSWERED}])
    taken = surveyed.taken_of(7, SCENARIOS,
                              found_of(answer(front, "publication_title")),
                              [read], [], {("section", 1): front})
    report = DocumentReport(document_id=7, owners_harvested=taken.passages,
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=None, spec=SCENARIOS)
    assert [r.get("parameter_state") for r in report.tuples] == [fields.DERIVED]
    assert runner.check_against_schema(report, "doc", SCENARIOS) == 0
    # the failure by construction: the same row without the state
    report.tuples[0].pop("parameter_state")
    assert runner.check_against_schema(report, "doc", SCENARIOS) == 1


def test_the_title_page_line_is_the_one_naming_the_plan_s_place():
    # Owner decision 2026-11-06: every reading request shows the line of the
    # title page that names the municipality the plan is about.
    cover = Source("section", 1, "Kommunale Wärmeplanung\nfür die Stadt "
                   "Musterstadt\nEndbericht", {"page": 1})
    body = Source("section", 2, "Musterstadt hat 30.000 Einwohner.",
                  {"page": 3})
    line = runner.title_line([body, cover], "Musterstadt")
    assert (line.owner_kind, line.owner_id, line.text) == (
        "section", 1, "für die Stadt Musterstadt")
    # the failure by construction: no name, or a name the first pages do
    # not print, shows no line
    assert runner.title_line([body, cover], None) is None
    assert runner.title_line([body, cover], "Beispielort") is None
