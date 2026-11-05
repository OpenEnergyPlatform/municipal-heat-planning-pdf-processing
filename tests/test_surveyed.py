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

A parameter the survey of the whole plan named no passage for is read once
where a search of the whole plan ranks first for it, AND not after a survey
of part of the plan; the passage it was read in is one of its sources, so a
reading there that came to nothing leaves it exhausted, not unstated; AND the
search's ranked list stays beside that passage under that parameter, so its
reading shows it, and two surveys joined keep the lists of both.

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

from docpipe.extraction import (combing, fields, reading, runner, survey,
                                surveyed)
from docpipe.extraction.pipeline import (Batch, DocumentReport, Row, Source,
                                         WorkItem)
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import parameter_states

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
    return survey.Answer(owner, list(parameters), None, {}, [])


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


def sought_harvest(found, ranked, reads=None):
    """A harvest whose reader records which passages it was asked to read
    each parameter in, and gives back *reads* for a parameter."""
    asked = []

    def make_reader(spec):
        def run(document_id, found, shown, budget):
            named = {p.uri: found.passages_of(p.uri) for p in spec.parameters
                     if found.passages_of(p.uri)}
            asked.append(named)
            return [(reads or {})[uri] for uri in named
                    if uri in (reads or {})]
        return run

    search = SearchOnly(ranked)
    whole = surveyed.SurveyedHarvest(
        SPEC, lambda spec, only, scope: (lambda document_id, passages: found),
        make_reader, lambda spec: search,
        lambda document_id: [ONE, TWO, THREE], lambda document_id: 2)
    return whole, asked, search


def test_a_parameter_without_a_passage_is_read_where_a_search_ranks_first():
    whole, asked, search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO]})
    taken = whole(7)
    assert asked == [{"emission": [("section", 1)]},
                     {"heat_load": [("table", 2)]}]
    # Searched once for every parameter without a passage, not for one with.
    assert [EMISSION.label] not in search.searched
    assert [HEAT_LOAD.label] in search.searched
    assert ("table", 2) in taken.sources_of["heat_load"]
    assert taken.sought.passages_of("heat_load") == [("table", 2)]


def test_a_survey_of_part_of_the_plan_searches_for_nothing():
    whole, asked, search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO]})
    whole(7, passages=[ONE])
    assert search.searched == [] and len(asked) == 1


def test_a_search_whose_reading_came_to_nothing_is_a_hole_not_a_silent_plan():
    cut = read_of(HEAT_LOAD, TWO, why=reading.CUT)
    whole, _asked, _search = sought_harvest(
        found_of(answer(ONE, "emission")), {HEAT_LOAD.label: [TWO]},
        reads={"heat_load": cut})
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


def test_a_passage_a_search_named_keeps_the_search_s_list_for_its_parameter():
    out = surveyed.sought_survey(survey.Found(True),
                                 lambda document, probes, exclude: [FIRST,
                                                                    NEXT],
                                 7, [EMISSION])
    assert out.passages_of(EMISSION.uri) == [("section", 5)]
    assert out.hits == {(EMISSION.uri, "section", 5): [FIRST, NEXT]}
    # By construction: a search that finds nothing names no list either.
    none = surveyed.sought_survey(survey.Found(True), lambda *a: [], 7,
                                  [EMISSION])
    assert none.hits == {} and none.passages_of(EMISSION.uri) == []


def test_two_surveys_joined_keep_the_lists_of_both():
    found, also = survey.Found(True), survey.Found(True)
    found.hits = {(EMISSION.uri, "section", 5): [FIRST]}
    also.hits = {("heat_load", "table", 9): [NEXT]}
    assert surveyed.joined(found, also).hits == {**found.hits, **also.hits}
    assert surveyed.joined(found, survey.Found(True)).hits == found.hits
