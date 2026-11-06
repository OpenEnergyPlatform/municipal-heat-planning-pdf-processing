"""A run harvests from the survey when its spec names groups and its profile
writes every prompt of that flow, and field by field otherwise; its stamps and
producers record the flow and the prompts it sends, and the server's window is
measured over them.

What nothing could read is a hole with its reason: a passage the survey left
unanswered goes to the fold under no parameter and counts among the passages
of every parameter; a reading that came to no readable reply goes under its
reason and names its parameter. Folded, a parameter whose only passage was a
hole ends exhausted, one whose passage was read and held nothing unstated. A
survey that answered no passage is no reply at all. A harvest halted after its
survey reads nothing.

With --start-at the survey covers the found passages under its own scope, and
a parameter no earlier harvest was asked is surveyed over the rest of the plan
too. A survey of part of a plan is kept under its scope beside the whole one's
and taken again only for the same passages, its unanswered passages kept.

A parameter the survey of the whole plan named no passage for is read down
the list a search of the whole plan ranks for it, in its order, one passage a
round and every such parameter in the same round, AND it stops at the first
reading that comes back with a value, AND where none does it is read to the
end of the list as a request shows it, a reading with no reply ending
nothing (owner decision 2026-11-05); AND not after a survey of part of the
plan; every passage it was read in is one of its sources, so a reading there
that came to nothing leaves it exhausted, not unstated; AND each reading
is shown its one passage and no list, since a reading has no tools (ticket
26), AND each passage walked is kept and traced with its place in the list,
AND each parameter's passages are kept in the order the walk read them; a
reading whose answer the check refuses ends nothing; and two surveys joined
keep the walks of both.

What a publication says of itself is read from its first page on, page by
page and first page first, every passage of a page in one round, whatever
the survey named (owner decisions 2026-11-05), AND until a title came, on
the page just read or before it, by the survey's reading or by this one,
AND a title the check refuses ends nothing; a passage the survey named for
a field is not read for it again; every passage it was read in is one of its
sources; AND nothing is read from the front where the profile names no
title among them, nor after a survey of part of the plan, nor once the run
halted. The profile's title is one of its front parameters.

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
                                surveyed)
from docpipe.extraction.pipeline import (Batch, DocumentReport, Row, Source,
                                         WorkItem)
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import parameter_states
from profiles.scenarios import extraction as scenarios_extraction

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

def test_a_passage_the_survey_left_unanswered_is_a_hole_of_every_parameter():
    taken = surveyed.taken_of(7, SPEC, found_of(answer(ONE),
                                                unanswered=[TWO]),
                              [], [], SHOWN)
    holes = sentinels(taken)
    assert len(holes) == 1
    batch, claim = holes[0]
    assert batch.items[0].source is TWO and batch.parameter is None
    assert claim["_why"] == reading.NO_ANSWER and "_parameter" not in claim
    assert all(("table", 2) in owners
               for owners in taken.sources_of.values())
    # Answered without a number of any parameter: no hole.
    assert all(("section", 1) not in owners
               for owners in taken.sources_of.values())


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
        return reading.Reader(SPEC, ask, ask, [])

    cut = reader(reading.CUT).read(7, EMISSION, ONE, [], [], SHOWN)
    silent = reader(None).read(7, EMISSION, ONE, [], [], SHOWN)
    assert cut.unread and cut.why == reading.CUT
    assert silent.unread and silent.why == reading.NO_ANSWER
    answered = reader({"next": None}).read(7, EMISSION, ONE, [], [], SHOWN)
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


def test_a_survey_that_answered_no_passage_is_no_reply_at_all():
    silent = surveyed.taken_of(7, SPEC, found_of(unanswered=[ONE, TWO]),
                               [], [], SHOWN)
    assert silent.replies == 0 and silent.passages == 2
    report = DocumentReport(document_id=7, owners_harvested=silent.passages)
    runner.fold_answers(silent.answered, report, locate=None, spec=SPEC)
    assert runner.not_happened(report, answered=silent.replies)[0] \
        == "no_reply"
    # A plan whose passages hold no number answered: a reply, no hole.
    numberless = surveyed.taken_of(7, SPEC, found_of(answer(ONE), answer(TWO)),
                                   [], [], SHOWN)
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


def test_a_harvest_halted_after_its_survey_reads_nothing():
    whole, made, read_calls = harvest(found_of(answer(ONE, "emission")),
                                      halted=True)
    assert whole(7) is None
    assert made and not read_calls
    whole, made, read_calls = harvest(found_of(answer(ONE, "emission")))
    assert whole(7) is not None and read_calls


def test_start_at_surveys_the_found_passages_and_a_gained_parameter_the_rest():
    whole, made, _reads = harvest(found_of(answer(ONE, "emission")))
    surveyed.take_found(whole, 7, [ONE], ["building_count"])
    assert ((), "found", [("section", 1)]) in made
    assert (("building_count",), "gained",
            [("table", 2), ("section", 3)]) in made
    whole, made, _reads = harvest(found_of(answer(ONE, "emission")))
    surveyed.take_found(whole, 7, [ONE], [])
    assert [scope for _only, scope, _passages in made] == ["found"]


def test_a_survey_of_part_of_a_plan_is_kept_under_its_scope(tmp_path):
    asked = []

    def leaves_out_the_table(context, document_id, corrections=None):
        asked.append(len(context))
        return {"passages": {f"P{i + 1}": {"parameters": ["out:none"]}
                             for i, s in enumerate(context)
                             if s.owner_kind != "table"}}

    def made(scope=""):
        return survey.Survey(leaves_out_the_table,
                             lambda document_id: [ONE, TWO, THREE],
                             lambda document_id: 1,
                             survey.parameters_of(SPEC),
                             survey.tuple_slots(SPEC), runner.frame_pairs,
                             "k", store=tmp_path, scope=scope)

    found = made("found")(7, [ONE, TWO])
    assert (tmp_path / "7.found.json").is_file()
    assert not (tmp_path / "7.json").is_file()
    assert found.unanswered == [("table", 2)]
    asked.clear()
    again = made("found")(7, [ONE, TWO])
    assert not asked and again.unanswered == [("table", 2)]
    # Other passages under the same scope: surveyed anew.
    made("found")(7, [ONE, THREE])
    assert asked


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
               and "year" in c[3]["group"].coordinates
               and c[3]["own"] and c[3]["bases"] == (("status_quo", 2022),)
               for c in calls)
    # Coordinates of two groups: one request per group, each its share.
    calls.clear()
    sweep(batch, rows, [slots["year"], slots["carrier"]])
    assert [(c[0], c[1], c[3]["coordinates"]) for c in calls] == [
        (ONE, ["year"], ["year"]), (ONE, ["carrier"], ["carrier"]),
        (THREE, ["year"], ["year"]), (THREE, ["carrier"], ["carrier"])]


def comber(*replies, ranked=()):
    asked = []

    def ask(payload, shape, document_id, source, group=None):
        asked.append(payload)
        return replies[min(len(asked), len(replies)) - 1]

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
    made, asked = comber({"rows": [{"row": "R1", "carrier": {
        "value": fields.UNSTATED}}]})
    claim = stored_row()
    made.comb(7, EMISSION, ONE, [carrier], [claim], SHOWN, [], None,
              coordinates=["carrier"], own=True)
    assert asked[0]["rows"][0]["open"] == ["carrier"]
    assert [m["text"] for m in asked[0]["more"]] == [ONE.text]
    # Not named and read: not asked.
    made, asked = comber({"rows": []})
    made.comb(7, EMISSION, ONE, [carrier], [stored_row()], SHOWN, [], None)
    assert asked[0]["rows"][0]["open"] == [] and "more" not in asked[0]


def test_the_passages_read_before_are_listed_and_a_stored_row_ranks_none():
    year = next(s for s in reading.slots_of(SPEC, EMISSION)
                if s.name == "year")
    made, asked = comber({"rows": []}, ranked=(TWO, THREE))
    made.comb(7, EMISSION, ONE, [year], [stored_row()], SHOWN, [], None,
              first=[THREE])
    assert [hit["title"] for hit in asked[0]["hits"][0]["hits"]] \
        == ["Ausblick"]
    # A stored row carries no sentence: no list, the model searches itself.
    made, asked = comber({"rows": []}, ranked=(TWO, THREE))
    made.comb(7, EMISSION, ONE, [year], [stored_row()], SHOWN, [], None)
    assert "hits" not in asked[0]


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

def test_a_spec_with_groups_and_every_prompt_harvests_from_the_survey(
        monkeypatch):
    assert runner.surveyed_flow(SPEC)
    assert not runner.surveyed_flow(replace(SPEC, groups={}))
    monkeypatch.setattr(runner, "FLOW", runner.SURVEYED)
    entry = runner.producer("harvest", "m")
    assert entry["flow"] == runner.SURVEYED
    assert set(entry["prompts"]) == set(runner.SURVEY_PROMPT_IDS)
    assert set(runner.SURVEY_PROMPT_IDS) <= set(
        runner._stamp_current("sha", "", SPEC))
    assert runner.sent_prompt_ids(False) == runner.SURVEY_PROMPT_IDS
    monkeypatch.setattr(runner, "FLOW", runner.FIELDWISE)
    entry = runner.producer("harvest", "m")
    assert entry["flow"] == runner.FIELDWISE
    assert runner.FIELD_PROMPT_ID in entry["prompts"]
    assert runner.SURVEY_PROMPT_IDS[0] not in runner.sent_prompt_ids(False)


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
        # A spec without groups never asked for the survey, so the same
        # profile harvests it the old way.
        assert not runner.surveyed_flow(replace(SPEC, groups={}))


# -- a parameter the survey named no passage for --------------------------------

class SearchOnly:
    """The combing's search, best first for a label (*ranked*); it combs
    nothing."""

    def __init__(self, ranked):
        self.ranked = ranked
        self.searched = []
        self.trace = None

    def rank(self, document_id, probes, exclude):
        self.searched.append(list(probes))
        return list(self.ranked.get(probes[0], ()))

    def __call__(self, document_id, reads, shown, pairs, budget):
        return []


def sought_harvest(found, ranked, reads=None, halt_after=None):
    """A harvest whose reader records which passages it was asked to read
    each parameter in and the walk each reading is shown, and gives back
    *reads*: {(parameter uri, owner): Read}. *halt_after* readings halt
    it."""
    asked, hits = [], []

    def make_reader(spec):
        def run(document_id, found, shown, budget):
            named = {p.uri: found.passages_of(p.uri) for p in spec.parameters
                     if found.passages_of(p.uri)}
            asked.append(named)
            hits.append(dict(found.walked))
            return [(reads or {})[(uri, owner)]
                    for uri, owners in named.items() for owner in owners
                    if (uri, owner) in (reads or {})]
        return run

    search = SearchOnly(ranked)
    whole = surveyed.SurveyedHarvest(
        SPEC, lambda spec, only, scope: (lambda document_id, passages: found),
        make_reader, lambda spec: search,
        lambda document_id: [ONE, TWO, THREE], lambda document_id: 2,
        halted=(lambda: len(asked) >= halt_after) if halt_after else None)
    return whole, asked, hits, search


# A value each passage prints, with the quote it stands in.
BACKED = {("section", 1): {"value": 300, "quote": "Es fielen rund 300 t CO2"},
          ("table", 2): {"value": 40, "quote": "2022 | 40 MW"},
          ("section", 3): {"value": 2030,
                           "quote": "Die Werte gelten für 2030"}}


def valued(parameter, source):
    """A reading of *parameter* in *source* that came back with a value the
    check takes there."""
    return read_of(parameter, source, claims=[
        dict(BACKED[(source.owner_kind, source.owner_id)])])


def test_a_parameter_without_a_passage_is_read_down_its_list_until_a_value():
    whole, asked, _hits, search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO, THREE, ONE]},
        reads={("heat_load", ("section", 3)): valued(HEAT_LOAD, THREE)})
    taken = whole(7)
    assert asked == [{"emission": [("section", 1)]},
                     {"heat_load": [("table", 2)]},
                     {"heat_load": [("section", 3)]}]
    # Searched once for every parameter without a passage, not for one with.
    assert [EMISSION.label] not in search.searched
    assert search.searched.count([HEAT_LOAD.label]) == 1
    # Every passage walked is a source, the one never read is not.
    assert taken.sought.passages_of("heat_load") == [("table", 2),
                                                     ("section", 3)]
    assert {("table", 2), ("section", 3)} <= taken.sources_of["heat_load"]
    assert ("section", 1) not in taken.sources_of["heat_load"]
    # the failure by construction: a value in the first passage ends the walk
    whole, asked, _hits, _search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO, THREE, ONE]},
        reads={("heat_load", ("table", 2)): valued(HEAT_LOAD, TWO)})
    whole(7)
    assert asked[1:] == [{"heat_load": [("table", 2)]}]


def test_an_answer_the_check_refuses_does_not_end_the_walk():
    for refused in ({"value": 40, "quote": "2022 | 40 MW"},      # not in THREE
                    {"value": 999, "quote": "Die Werte gelten für 2030"}):
        whole, asked, _hits, _search = sought_harvest(
            found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [THREE, ONE]},
            reads={("heat_load", ("section", 3)):
                   read_of(HEAT_LOAD, THREE, claims=[refused])})
        whole(7)
        assert asked[1:] == [{"heat_load": [("section", 3)]},
                             {"heat_load": [("section", 1)]}]
    # the failure by construction: an answer its passage backs ends the walk
    whole, asked, _hits, _search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [THREE, ONE]},
        reads={("heat_load", ("section", 3)): valued(HEAT_LOAD, THREE)})
    whole(7)
    assert asked[1:] == [{"heat_load": [("section", 3)]}]


def test_every_parameter_without_a_passage_is_read_in_the_same_round():
    other = next(p for p in SPEC.parameters
                 if p.uri not in ("emission", "heat_load"))
    whole, asked, _hits, _search = sought_harvest(
        found_of(answer(ONE, "emission")),
        {HEAT_LOAD.label: [TWO, THREE], other.label: [THREE, TWO]},
        reads={("heat_load", ("table", 2)): valued(HEAT_LOAD, TWO)})
    whole(7)
    assert asked[1:] == [{"heat_load": [("table", 2)],
                          other.uri: [("section", 3)]},
                         {other.uri: [("table", 2)]}]


def test_a_list_no_reading_gives_a_value_is_read_to_the_end_a_request_shows():
    sections = [passage("section", 100 + n, f"Teil {n}\nText", f"Teil {n}")
                for n in range(reading.SHOWN["section"] + 2)]
    lists = surveyed.sought_lists(lambda d, probes, exclude: sections, 7,
                                  [HEAT_LOAD])
    read_in = []

    def read(one):
        read_in.extend(one.passages_of("heat_load"))
        return []
    walked, reads = surveyed.sought_walk(survey.Found(True), lists, read)
    # The two the hit list cuts off are never read.
    assert read_in == [("section", 100 + n)
                       for n in range(reading.SHOWN["section"])]
    assert walked.passages_of("heat_load") == read_in and reads == []


def test_a_reading_that_came_to_no_reply_ends_nothing():
    cut = read_of(HEAT_LOAD, TWO, why=reading.CUT)
    read_in = []

    def read(one):
        owners = one.passages_of("heat_load")
        read_in.extend(owners)
        return [cut] if owners == [("table", 2)] else []
    walked, reads = surveyed.sought_walk(
        survey.Found(True), {"heat_load": [TWO, THREE]}, read)
    assert read_in == [("table", 2), ("section", 3)] and reads == [cut]


def test_each_reading_of_the_walk_is_shown_its_passage_and_no_list():
    whole, asked, shown, _search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO, THREE, ONE]})
    whole(7)
    assert asked[1:] == [{"heat_load": [("table", 2)]},
                         {"heat_load": [("section", 3)]},
                         {"heat_load": [("section", 1)]}]
    assert shown[1:] == [{}, {}, {}]


def test_each_passage_walked_keeps_its_place_in_its_list():
    walked, _reads = surveyed.sought_walk(
        survey.Found(True), {"heat_load": [TWO, THREE, ONE]}, lambda one: [])
    assert walked.walked == {("heat_load", "table", 2): 1,
                             ("heat_load", "section", 3): 2,
                             ("heat_load", "section", 1): 3}
    # the failure by construction: a value in the first passage ends the walk
    stopped, _reads = surveyed.sought_walk(
        survey.Found(True), {"heat_load": [TWO, THREE, ONE]},
        lambda one: [valued(HEAT_LOAD, TWO)])
    assert stopped.walked == {("heat_load", "table", 2): 1}


def test_each_parameter_s_passages_are_kept_in_the_order_the_walk_read_them():
    other = next(p for p in SPEC.parameters
                 if p.uri not in ("emission", "heat_load"))
    walked, _reads = surveyed.sought_walk(
        survey.Found(True), {other.uri: [THREE, ONE], "heat_load": [TWO, THREE]},
        lambda one: [])
    assert surveyed.walks_of(walked) == {
        other.uri: [("section", 3), ("section", 1)],
        "heat_load": [("table", 2), ("section", 3)]}
    # the failure by construction: the survey's own order puts the passage
    # the other parameter read first ahead of the one read before it
    assert walked.passages_of("heat_load") == [("section", 3), ("table", 2)]


def test_each_passage_walked_is_traced_with_its_place_in_the_list():
    whole, _asked, _hits, search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO, THREE]})
    events = []
    search.trace = lambda event, document_id, **about: events.append(
        (event, about))
    whole(7)
    assert events == [("seek", {"parameter": "heat_load", "kind": "table",
                                "owner": 2, "rank": 1}),
                      ("seek", {"parameter": "heat_load", "kind": "section",
                                "owner": 3, "rank": 2})]


def test_a_walk_halted_after_a_round_reads_no_further():
    whole, asked, _hits, _search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO, THREE]},
        halt_after=2)
    assert whole(7) is None
    assert asked[1:] == [{"heat_load": [("table", 2)]}]


def test_a_survey_of_part_of_the_plan_searches_for_nothing():
    whole, asked, _hits, search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO]})
    whole(7, passages=[ONE])
    assert search.searched == [] and len(asked) == 1


def test_a_search_whose_reading_came_to_nothing_is_a_hole_not_a_silent_plan():
    cut = read_of(HEAT_LOAD, TWO, why=reading.CUT)
    whole, _asked, _hits, _search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO]},
        reads={("heat_load", ("table", 2)): cut})
    taken = whole(7)

    def state(taken_view):
        report = DocumentReport(document_id=7,
                                owners_harvested=taken_view.passages,
                                sources_of=taken_view.sources_of)
        runner.fold_answers(taken_view.answered, report, locate=None,
                            spec=SPEC)
        return {s["parameter"]: s["state"] for s in parameter_states(
            SPEC, report.tuples, report.refusals,
            harvested=report.owners_harvested, answered=taken_view.replies,
            sources_of=report.sources_of)}["heat_load"]
    assert state(taken) == fields.EXHAUSTED
    # Without the searched passage among its sources the hole is not its:
    # the plan would read as silent.
    blind = surveyed.taken_of(7, SPEC, taken.found, taken.reads, [], SHOWN)
    assert state(blind) == fields.SAID_UNSTATED


# -- the list of a search of the whole plan ----------------------------------

FIRST = SimpleNamespace(owner_kind="section", owner_id=5)
NEXT = SimpleNamespace(owner_kind="table", owner_id=9)


def test_a_round_of_the_walk_names_its_passage_and_no_other_of_the_list():
    lists = surveyed.sought_lists(
        lambda document, probes, exclude: [FIRST, NEXT], 7, [EMISSION])
    out = surveyed.sought_survey(survey.Found(True), lists, 0)
    assert out.passages_of(EMISSION.uri) == [("section", 5)]
    assert out.walked == {}
    later = surveyed.sought_survey(survey.Found(True), lists, 1)
    assert later.passages_of(EMISSION.uri) == [("table", 9)]
    # By construction: a search that finds nothing names no list either.
    none = surveyed.sought_lists(lambda *a: [], 7, [EMISSION])
    assert none == {}
    assert surveyed.sought_survey(survey.Found(True), none, 0) \
        .passages_of(EMISSION.uri) == []


def test_two_surveys_joined_keep_the_walks_of_both():
    found, also = survey.Found(True), survey.Found(True)
    found.walked = {(EMISSION.uri, "section", 5): 1}
    also.walked = {("heat_load", "table", 9): 2}
    assert surveyed.joined(found, also).walked == {**found.walked,
                                                   **also.walked}
    assert surveyed.joined(found, survey.Found(True)).walked == found.walked


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
                          "quote": "Net zero by 2050"}])
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


# -- what a publication says of itself, read from the front -------------------

OWN = tuple(scenarios_extraction.FRONT_PAGE_PARAMETERS)
TITLE = scenarios_extraction.FRONT_PAGE_TITLE


def on_page(kind, number, text, page):
    return Source(kind, number, text, {"document_id": 7, "page": page,
                                       "section_title": text.split("\n")[0]})


COVER = on_page("figure", 20, "A wind farm at dusk", 1)
TITLE_PAGE = on_page("section", 21, "Net zero by 2050\nAda Lovelace, 2020", 2)
IMPRINT = on_page("section", 22, "Imprint\ndoi:10.2760/081488", 2)
BODY = on_page("section", 23, "Results\nThe scenarios reach net zero.", 3)
OTHER = on_page("section", 24, "Gas for Climate, 2019\nNavigant", 11)
PLAN = [COVER, TITLE_PAGE, IMPRINT, BODY, OTHER]


def owner(source):
    return (source.owner_kind, source.owner_id)


def titled(source, quote="Net zero by 2050"):
    """A reading of the title in *source* answered with *quote*."""
    title = SCENARIOS.by_uri[TITLE]
    return reading.Read(Batch(7, title, [WorkItem(7, title, source)]),
                        [{"value": "Net zero by 2050", "quote": quote}])


def front_harvest(found, reads=None, *, title=TITLE, halt_after=None):
    """A harvest of PLAN whose reader records, round by round, the passages
    it was asked to read each parameter in, and gives back *reads*:
    {(parameter uri, owner): Read}. Nothing is combed or searched."""
    asked = []

    def make_reader(spec):
        def run(document_id, named_by, shown, budget):
            named = {p.uri: set(named_by.passages_of(p.uri))
                     for p in spec.parameters if named_by.passages_of(p.uri)}
            asked.append(named)
            return [(reads or {})[(uri, one)]
                    for uri, owners in named.items() for one in owners
                    if (uri, one) in (reads or {})]
        return run

    whole = surveyed.SurveyedHarvest(
        SCENARIOS, lambda spec, only, scope: (lambda document_id, passages: found),
        make_reader, lambda spec: None, lambda document_id: list(PLAN),
        lambda document_id: 11,
        halted=(lambda: len(asked) >= halt_after) if halt_after else None,
        front=OWN, title=title)
    return whole, asked


def every_field(*sources):
    return {uri: {owner(s) for s in sources} for uri in OWN}


def test_a_publication_s_own_fields_are_read_from_its_first_page_on():
    # The review: the survey named only a chapter on another study.
    named = found_of(answer(OTHER, TITLE, "publication_author",
                            "publication_date"))
    whole, asked = front_harvest(
        named, {(TITLE, owner(TITLE_PAGE)): titled(TITLE_PAGE)})
    taken = whole(7)
    assert asked == [{TITLE: {owner(OTHER)},
                      "publication_author": {owner(OTHER)},
                      "publication_date": {owner(OTHER)}},
                     every_field(COVER),
                     every_field(TITLE_PAGE, IMPRINT)]
    # What it read goes to the fold.
    report = DocumentReport(document_id=7, owners_harvested=taken.passages,
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=None, spec=SCENARIOS)
    assert [(row["value"], row["provenance"]["owner_id"])
            for row in report.tuples] == [("Net zero by 2050", 21)]
    # Every passage read from the front is a source of its field, in page
    # order.
    assert taken.front.passages_of("publication_doi") == [
        owner(COVER), owner(TITLE_PAGE), owner(IMPRINT)]
    assert owner(IMPRINT) in taken.sources_of["publication_doi"]
    blind = surveyed.taken_of(7, SCENARIOS, taken.found, taken.reads, [],
                              {owner(s): s for s in PLAN})
    assert owner(IMPRINT) not in blind.sources_of["publication_doi"]
    # the failure by construction: a profile that names no title reads
    # nothing from the front
    whole, asked = front_harvest(
        named, {(TITLE, owner(TITLE_PAGE)): titled(TITLE_PAGE)}, title=None)
    whole(7)
    assert asked == [{TITLE: {owner(OTHER)},
                      "publication_author": {owner(OTHER)},
                      "publication_date": {owner(OTHER)}}]


def test_a_title_the_check_refuses_does_not_end_the_read_from_the_front():
    whole, asked = front_harvest(
        found_of(), {(TITLE, owner(TITLE_PAGE)):
                     titled(TITLE_PAGE, quote="Net zero by 2060")})
    whole(7)
    assert asked[1:] == [every_field(COVER), every_field(TITLE_PAGE, IMPRINT),
                         every_field(BODY), every_field(OTHER)]
    # the failure by construction: the title its page prints ends it there
    whole, asked = front_harvest(
        found_of(), {(TITLE, owner(TITLE_PAGE)): titled(TITLE_PAGE)})
    whole(7)
    assert asked[1:] == [every_field(COVER), every_field(TITLE_PAGE, IMPRINT)]


def test_a_title_the_survey_read_ends_the_read_at_its_page():
    named = found_of(answer(TITLE_PAGE, TITLE))
    whole, asked = front_harvest(
        named, {(TITLE, owner(TITLE_PAGE)): titled(TITLE_PAGE)})
    whole(7)
    # A passage the survey named for a field is not read for it again.
    assert asked == [{TITLE: {owner(TITLE_PAGE)}}, every_field(COVER),
                     {**every_field(TITLE_PAGE, IMPRINT),
                      TITLE: {owner(IMPRINT)}}]
    # the failure by construction: the survey's title the check refuses
    whole, asked = front_harvest(
        named, {(TITLE, owner(TITLE_PAGE)):
                titled(TITLE_PAGE, quote="Net zero by 2060")})
    whole(7)
    assert every_field(BODY) in asked


def test_nothing_is_read_from_the_front_after_a_survey_of_part_of_the_plan():
    whole, asked = front_harvest(found_of())
    whole(7, passages=[TITLE_PAGE])
    assert asked == [{}]
    whole, asked = front_harvest(found_of())
    whole(7)
    assert asked[1] == every_field(COVER)


def test_a_read_from_the_front_halted_after_a_round_reads_no_further():
    whole, asked = front_harvest(found_of(), halt_after=2)
    assert whole(7) is None
    assert asked == [{}, every_field(COVER)]


def test_the_front_is_read_first_page_first_each_page_in_document_order():
    unpaged = Source("section", 25, "Annex", {"document_id": 7})
    assert surveyed.by_page([OTHER, BODY, unpaged, IMPRINT, COVER,
                             TITLE_PAGE]) == [(1, [COVER]),
                                              (2, [IMPRINT, TITLE_PAGE]),
                                              (3, [BODY]), (11, [OTHER])]


def test_the_profile_s_title_is_one_of_its_front_parameters():
    assert TITLE in OWN and all(uri in SCENARIOS.by_uri for uri in OWN)
    # the failure by construction: a title the spec does not hold reads
    # nothing from the front
    whole, asked = front_harvest(found_of(), title="publication_titel")
    whole(7)
    assert asked == [{}]
