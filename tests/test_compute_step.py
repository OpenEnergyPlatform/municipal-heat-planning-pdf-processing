"""What a document's verified rows leave open is worked out in the sandbox: the
questions are found by rule, a number repeated in two passages counts once, the
model writes the code, and the new row carries code, output and inputs. Each
promise has a case that breaks it by construction beside the one that keeps
it."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import jsonschema
import openai
import pytest

from docpipe import providers
from docpipe.app import sandbox_service
from docpipe.extraction import compute, fields, pipeline, replies, runner
from docpipe.extraction import schema, stats, verify
from docpipe.extraction.pipeline import Source, WorkItem
from docpipe.extraction.spec import load as load_spec
from docpipe.inference import code_exec, pool
from profiles.kwp import compute as rules

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
GAS, OIL, HEAT = "OEO_00000292", "OEO_00000211", "OEO_00000132"
HOMES, TRADE = "OEO_00000214", "OEO_00000405"
TOTAL = "out:total"
READ = {f"{axis}_state": fields.READ
        for axis in ("unit", "quantity", "year", "scenario", "carrier",
                     "sector", "spatial_scope")}
FACTOR = {"MWh/a": 1.0, "GWh/a": 1000.0, "kW": 0.001}


def amount(value, carrier=TOTAL, sector=TOTAL, *, unit="MWh/a", owner=1,
           quote=None, year=2023, parameter="energy_consumption", **more):
    return {**READ, "parameter": parameter, "value": value,
            "value_target": value * FACTOR[unit], "unit": unit,
            "quote": quote or f"Der Wert lautet {value} {unit}",
            "quantity": "OEO_00050016", "year": year,
            "scenario": "status_quo", "carrier": carrier, "sector": sector,
            "spatial_scope": "municipality", "source": "Q1",
            "provenance": {"owner_kind": "table", "owner_id": owner}, **more}


def share(value, carrier=OIL, sector=TOTAL, *, whole="Endenergiebedarf",
          owner=9, year=2023, **more):
    row = amount(value, carrier, sector, owner=owner, year=year,
                 parameter="share", quote=f"Der Anteil beträgt {value} %",
                 **more)
    return {**row, "unit": "%", "value_target": float(value), "whole": whole,
            "whole_state": fields.READ}


def kinds(*rows):
    return [q.kind for q in rules.questions(list(rows), SPEC)]


def only(*rows):
    found = rules.questions(list(rows), SPEC)
    assert len(found) == 1
    return found[0]


def shown(question):
    return [number.value for number in question.numbers]


# -- which shares stand open -------------------------------------------------

def test_a_share_without_its_absolute_number_is_asked_with_the_totals():
    question = only(share(21), amount(185200))
    assert question.kind == "share"
    assert shown(question) == [21, 185200]


def test_a_share_with_its_absolute_number_is_not_asked():
    assert kinds(share(21), amount(185200), amount(38000, OIL)) == []


def test_a_share_without_a_total_in_its_frame_is_asked_to_find_its_whole():
    # A total of another year is no whole of it, and is not offered.
    question = only(share(21), amount(185200, year=2030))
    assert shown(question) == [21] and question.take is not None


def test_a_row_saying_nothing_on_an_axis_is_the_same_part():
    silent = {**amount(38000, OIL), "sector_state": fields.UNSTATED}
    assert kinds(share(21), amount(185200), silent) == []


def test_a_share_with_no_whole_read_is_not_asked():
    row = {**share(21), "whole_state": fields.UNSTATED}
    assert kinds(row, amount(185200)) == []


def test_a_share_naming_no_part_is_not_asked():
    assert kinds(share(100, TOTAL), amount(185200)) == []


def test_a_total_said_twice_is_offered_once():
    question = only(share(21), amount(185200, owner=1), amount(185000, owner=2))
    assert shown(question) == [21, 185200]


def test_the_total_of_its_sector_is_offered_and_another_sector_s_is_not():
    found = rules.questions([share(21, OIL, HOMES), amount(900, TOTAL, HOMES),
                             amount(700, TOTAL, TRADE)], SPEC)
    assert [shown(q) for q in found if q.kind == "share"] == [[21, 900]]


# -- which sums stand open ---------------------------------------------------

def test_parts_without_a_sum_are_asked_over_their_axis():
    question = only(amount(120, GAS), amount(80, OIL))
    assert question.kind == "sum"
    assert question.wanted["over"] == "carrier"
    assert sorted(shown(question)) == [80, 120]


def test_parts_of_a_printed_sum_are_not_asked():
    assert kinds(amount(120, GAS), amount(80, OIL), amount(200)) == []


def test_parts_may_stand_in_several_passages():
    assert kinds(amount(120, GAS, owner=1), amount(80, OIL, owner=2)) == ["sum"]


def test_parts_of_two_years_are_no_sum():
    assert kinds(amount(120, GAS), amount(80, OIL, year=2030)) == []


def test_a_power_is_no_amount():
    assert kinds(amount(120, GAS, parameter="heat_load", unit="kW"),
                 amount(80, OIL, parameter="heat_load", unit="kW")) == []


def test_a_number_without_a_class_is_no_part():
    for quantity in ("out:specific", "out:useful_energy"):
        closed = [{**amount(value, carrier), "quantity": quantity}
                  for value, carrier in ((120, GAS), (80, OIL))]
        assert kinds(*closed) == [], quantity


def pooled(done, clears=0):
    """A pool session that notes what it is asked to do."""
    class Session:
        def __init__(self, pool_manager):
            done.append(pool_manager)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def run(self, code, timeout):
            if code == sandbox_service.CLEAR:
                done.append("cleared")
                return SimpleNamespace(exit_code=clears, stdout="", stderr="")
            done.append("ran")
            if "broken" in code:
                raise RuntimeError("the run broke")
            return SimpleNamespace(exit_code=0, stdout="1\n", stderr="")
    return Session


def test_a_run_takes_a_kept_container_and_clears_it_after(monkeypatch):
    done = []
    monkeypatch.setattr(sandbox_service, "POOL", "the pool")
    monkeypatch.setattr(sandbox_service, "PooledSandboxSession", pooled(done))
    assert sandbox_service.run_code("print(1)", None, 5)["ok"]
    assert done == ["the pool", "ran", "cleared"]
    done.clear()
    assert not sandbox_service.run_code("broken()", None, 5)["ok"]
    assert done == ["the pool", "ran", "cleared"]


def test_a_container_left_uncleared_fails_its_run(monkeypatch):
    done = []
    monkeypatch.setattr(sandbox_service, "POOL", "the pool")
    monkeypatch.setattr(sandbox_service, "PooledSandboxSession",
                        pooled(done, clears=1))
    reply = sandbox_service.run_code("print(1)", None, 5)
    assert not reply["ok"] and reply["error"]


class Warming:
    """A pool whose containers stand one after the other."""
    def __init__(self, idle):
        self.idle = list(idle)

    def get_stats(self):
        return {"state_counts": {"idle": self.idle.pop(0) if len(self.idle) > 1
                                 else self.idle[0]}}


def test_the_service_waits_until_every_container_stands(monkeypatch):
    monkeypatch.setattr(sandbox_service, "PARALLEL", 3)
    pool, slept = Warming([0, 1, 2, 3]), []
    sandbox_service.wait_until_ready(pool, 60, clock=lambda: 0,
                                     sleep=slept.append)
    assert len(slept) == 3


def test_a_pool_that_never_stands_stops_the_service(monkeypatch):
    monkeypatch.setattr(sandbox_service, "PARALLEL", 3)
    ticks = iter(range(0, 1000, 10))
    with pytest.raises(SystemExit):
        sandbox_service.wait_until_ready(Warming([1]), 60,
                                         clock=lambda: next(ticks),
                                         sleep=lambda _: None)


def test_the_containers_are_kept_while_the_service_runs(monkeypatch):
    made = {}
    monkeypatch.setattr(sandbox_service, "create_pool_manager",
                        lambda **options: made.update(options) or "pool")
    monkeypatch.setattr(sandbox_service, "PoolConfig", lambda **config: config)
    monkeypatch.setattr(sandbox_service, "SandboxBackend",
                        SimpleNamespace(PODMAN="podman"))
    assert sandbox_service.open_pool() == "pool"
    config = made["config"]
    assert config["min_pool_size"] == config["max_pool_size"] \
        == sandbox_service.PARALLEL
    assert config["idle_timeout"] is None
    assert config["max_container_lifetime"] is None
    assert made["runtime_configs"]["stop_signal"] == 9


def test_zero_is_no_part():
    assert kinds(amount(0, GAS), amount(80, OIL)) == []
    assert sorted(shown(only(amount(0, HEAT), amount(120, GAS),
                             amount(80, OIL)))) == [80, 120]


def test_zero_is_no_share_and_no_total():
    assert kinds(share(0), amount(185200)) == []
    assert shown(only(share(21), amount(0))) == [21]


def test_a_row_without_a_year_is_no_part():
    unread = {**amount(80, OIL), "year_state": fields.UNSTATED}
    assert kinds(amount(120, GAS), unread) == []


def test_a_set_holding_its_sum_under_another_word_is_not_asked():
    assert kinds(amount(120, GAS), amount(80, OIL), amount(200, HEAT)) == []


def test_a_row_saying_nothing_on_another_axis_belongs_to_the_parts():
    silent = {**amount(80, OIL), "technology_state": fields.UNSTATED}
    told = {**amount(120, GAS), "technology": TOTAL,
            "technology_state": fields.READ}
    assert kinds(told, silent) == ["sum"]


def test_each_axis_closes_on_its_own():
    questions = rules.questions([amount(120, GAS, HOMES), amount(80, OIL, HOMES),
                                 amount(70, GAS, TRADE)], SPEC)
    assert sorted(q.wanted["over"] for q in questions) == ["carrier", "sector"]


def test_the_sum_over_sub_areas_tells_them_apart_by_name():
    north = {**amount(120), "spatial_scope": "sub_area",
             "spatial_scope_raw": "Nord"}
    south = {**amount(80), "spatial_scope": "sub_area",
             "spatial_scope_raw": "Süd"}
    assert only(north, south).wanted["over"] == "spatial_scope"


# -- one statement counts once -----------------------------------------------

def test_a_number_repeated_in_a_second_passage_counts_once():
    question = only(amount(120, GAS, owner=1), amount(120, GAS, owner=2),
                    amount(80, OIL, owner=1))
    assert sorted(shown(question)) == [80, 120]


def test_a_repeat_within_the_rounding_keeps_the_precise_number():
    question = only(amount(120, GAS, owner=1), amount(120.4, GAS, owner=2),
                    amount(80, OIL, owner=1))
    assert sorted(shown(question)) == [80, 120.4]


def test_a_repeat_in_another_unit_is_the_same_number():
    question = only(amount(120000, GAS, owner=1),
                    amount(120, GAS, unit="GWh/a", owner=2),
                    amount(80000, OIL, owner=1))
    assert sorted(shown(question)) == [80000, 120000]


def test_two_rows_of_one_passage_with_one_number_are_two_rows():
    question = only(amount(120, GAS, quote="| Gas Wohnen | 120 | MWh/a |"),
                    amount(120, GAS, quote="| Gas Handel | 120 | MWh/a |"),
                    amount(80, OIL))
    assert sorted(shown(question)) == [80, 120, 120]


def test_one_row_written_twice_counts_once():
    same = "| Gas | 120 | MWh/a |"
    question = only(amount(120, GAS, quote=same), amount(120, GAS, quote=same),
                    amount(80, OIL))
    assert sorted(shown(question)) == [80, 120]


def test_one_number_of_two_parts_stays_two_parts():
    question = only(amount(120, GAS, owner=1), amount(120, OIL, owner=2))
    assert shown(question) == [120, 120]


def test_a_part_gone_as_a_repeat_leaves_no_sum():
    assert kinds(amount(120, GAS, owner=1), amount(120, GAS, owner=2)) == []


def test_parts_in_other_units_are_shown_in_one():
    question = only(amount(120000, GAS), amount(80, OIL, unit="GWh/a"))
    assert sorted(shown(question)) == [80000, 120000]
    assert {number.unit for number in question.numbers} == {"MWh/a"}


# -- what a question makes of an answer --------------------------------------

def rows_used(question):
    return [number.row for number in question.numbers]


def test_a_share_s_row_takes_its_frame_from_the_total_and_its_part_from_itself():
    question = only(share(21, OIL, HOMES), amount(900, TOTAL, HOMES))
    row = question.row(rows_used(question))
    assert (row["parameter"], row["carrier"], row["sector"]) == (
        "energy_consumption", OIL, HOMES)
    assert row["unit"] == "MWh/a"
    assert "whole" not in row


def test_a_share_with_no_total_used_makes_no_row():
    question = only(share(21), amount(900))
    assert question.row([question.anchor]) is None


def test_a_share_on_two_totals_makes_no_row():
    question = only(share(21), amount(900, owner=1), amount(500, owner=2))
    assert question.row(rows_used(question)) is None


def test_a_sum_s_row_is_the_total_of_its_axis_and_keeps_the_rest():
    question = only(amount(120, GAS, HOMES), amount(80, OIL, HOMES))
    row = question.row(rows_used(question))
    assert (row["carrier"], row["carrier_state"]) == (TOTAL, fields.DERIVED)
    assert (row["sector"], row["sector_state"]) == (HOMES, fields.READ)
    assert row["subject_state"] == fields.SAID_UNSTATED


def test_what_a_row_had_as_a_reading_does_not_go_over():
    source = {**amount(120, GAS), "tier": "A", "flags": ["x"], "head": "Gas"}
    row = compute.inherited(source, "carrier")
    assert not {"tier", "flags", "head", "provenance", "value_target",
                "carrier", "carrier_state"} & set(row)


# -- the request -------------------------------------------------------------

def report_of(*rows):
    report = pipeline.DocumentReport(document_id=7)
    report.tuples = list(rows)
    return report


def batch_of(*rows):
    items = []
    for row in rows:
        owner = row["provenance"]
        source = Source(owner["owner_kind"], owner["owner_id"],
                        f"Abschnitt\n{row['quote']}",
                        {"document_id": 7, "title": "Tabelle 3"})
        items.append(WorkItem(7, None, source))
    return pipeline.Batch(7, None, items)


PROFILE = SimpleNamespace(component=lambda module, attr: getattr(rules, attr,
                                                                  None))


def printed(number):
    return {"ok": True, "stdout": f"{number}\n", "error": None}


def computing(monkeypatch, *said, ran=None, plan=None):
    """A compute step whose model says *said* in turn. Its requests, the code
    runs with what they were handed, and the trace. *ran* is what every run
    prints, or a list of what each prints in turn. *plan* is the plan's
    passages, which give the request its tools."""
    told = iter(said)
    asked, runs, events = [], [], []

    def create(**request):
        asked.append(request)
        said = next(told)
        if isinstance(said, Exception):
            raise said
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=said))])

    def run_code(code, context=None, timeout=None):
        runs.append((code, context))
        if isinstance(ran, list):
            return ran.pop(0)
        return ran or printed(38892.0)

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(code_exec, "is_enabled", lambda: True)
    monkeypatch.setattr(code_exec, "run_code", run_code)
    monkeypatch.setattr(runner.trace, "event", lambda kind, doc=None, /, **f:
                        events.append({"t": kind, "doc": doc, **f}))
    # A plan of one page: what a search lists and a fetch shows is cut to
    # two pages of it.
    step = (runner.make_computer(PROFILE, lambda document_id: plan,
                                 lambda document_id: 1)
            if plan is not None else runner.make_computer(PROFILE))
    return step, asked, runs, events


CODE = json.dumps({"action": "python", "code": "print(185200 * 0.21)"})
# What a total's passage says it is: every amount's passage here prints it.
WHOLE = "Der Wert lautet"


def answered(value, *used, quote=WHOLE) -> str:
    """The model's answer: *value* worked out from N1 and N2, or from
    *used*, quoting from the passage of the total what it is."""
    return json.dumps({"value": value, "used": list(used or ("N1", "N2")),
                       "quote": quote})


ANSWER = answered(38892.0)
NOTHING = json.dumps({"value": None, "used": []})


def run_step(step, *rows, stop=None):
    report = report_of(*rows)
    done = step([(batch_of(*rows), {})], report, spec=SPEC, stop=stop)
    return report, done


def test_the_code_runs_on_the_numbers_passages_and_tables(monkeypatch):
    step, _asked, runs, _events = computing(monkeypatch, CODE, ANSWER)
    run_step(step, share(21), amount(185200))
    code, handed = runs[0]
    assert code == "print(185200 * 0.21)"
    assert handed["numbers"]["N2"] == {"value": 185200, "unit": "MWh/a"}
    assert set(handed["sources"]) == {"Q1", "Q2"}
    assert [table["caption"] for table in handed["tables"]] == ["Tabelle 3"] * 2


def test_the_output_goes_back_to_the_model(monkeypatch):
    step, asked, _runs, _events = computing(monkeypatch, CODE, ANSWER)
    run_step(step, share(21), amount(185200))
    assert "38892.0" in asked[1]["messages"][-1]["content"]


def test_the_answer_is_a_row_with_code_output_and_inputs(monkeypatch):
    step, _asked, _runs, _events = computing(monkeypatch, CODE, ANSWER)
    report, done = run_step(step, share(21), amount(185200))
    assert done
    row = report.tuples[-1]
    assert row["value"] == 38892.0
    assert row["computed"] is True
    assert "computed" in row["flags"]
    run = row["compute"][-1]
    assert run["code"] == "print(185200 * 0.21)"
    assert [i["value"] for i in run["inputs"]] == [21, 185200]
    assert run["inputs"][1]["quote"] == "Der Wert lautet 185200 MWh/a"
    assert run["inputs"][1]["source"] == ["table", 1]


def test_a_row_stands_under_the_quote_of_its_anchor(monkeypatch):
    step, _asked, _runs, _events = computing(monkeypatch, CODE, ANSWER)
    report, _done = run_step(step, share(21), amount(185200))
    row = report.tuples[-1]
    assert row["quote"] == "Der Anteil beträgt 21 %"
    assert row["provenance"]["owner_id"] == 9


def test_a_number_the_code_did_not_print_is_refused(monkeypatch):
    wrong = answered(40000.0)
    step, _asked, _runs, events = computing(monkeypatch, CODE, wrong)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(report.tuples) == 2
    assert report.refusals
    assert events[-1]["outcome"] == "refused"


def test_nothing_to_compute_adds_no_row_and_runs_no_code(monkeypatch):
    step, _asked, runs, events = computing(monkeypatch, NOTHING)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(report.tuples) == 2
    assert runs == []
    assert events[-1]["outcome"] == "none"


def test_a_number_without_code_is_asked_again(monkeypatch):
    step, asked, runs, _events = computing(monkeypatch, ANSWER, CODE, ANSWER)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(asked) == 3
    assert len(runs) == 1
    assert report.tuples[-1]["computed"] is True


def test_code_that_failed_is_no_evidence(monkeypatch):
    broken = {"ok": False, "stdout": "", "error": "NameError"}
    step, asked, _runs, events = computing(
        monkeypatch, CODE, ANSWER, NOTHING, ran=broken)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(report.tuples) == 2
    assert len(asked) == 3
    assert events[-1]["outcome"] == "none"


def test_an_unreadable_reply_is_asked_again(monkeypatch):
    step, asked, _runs, _events = computing(monkeypatch, "kein json", NOTHING)
    run_step(step, share(21), amount(185200))
    assert len(asked) == 2


def timed(monkeypatch, first):
    """The time each request of the compute step was given, on the stage's
    own client (`runner._client`), when its first request ends on *first*."""
    left, times = [first, NOTHING], []

    def create(**request):
        times.append(request.get("timeout"))
        said = left.pop(0)
        if isinstance(said, Exception):
            raise said
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=said))])

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(providers, "client", lambda *a, **k: client)
    monkeypatch.setattr(runner, "SCHEDULER", None)
    monkeypatch.setattr(pool, "wide", lambda: False)
    monkeypatch.setattr(code_exec, "is_enabled", lambda: True)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0.0)
    run_step(runner.make_computer(PROFILE), share(21), amount(185200))
    return times


class Status(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def test_a_request_that_timed_out_is_repeated_with_the_time_of_a_repeat(
        monkeypatch):
    slow = openai.APITimeoutError(request=httpx.Request("POST", "http://x"))
    assert timed(monkeypatch, slow) == [None, runner.RETRY_TIMEOUT]


def test_a_request_after_a_server_error_keeps_its_time(monkeypatch):
    assert timed(monkeypatch, Status(500)) == [None, None]


# -- a request that fails, by the rule of every request (`runner.Failures`) --

@pytest.fixture
def waits(monkeypatch):
    """The curve of each wait, (failures so far, the server's failure), and a
    count of unfinished documents of this test's own."""
    taken = []
    monkeypatch.setattr(runner, "retry_wait",
                        lambda n, transport=False:
                        taken.append((n, transport)) or 0.0)
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    return taken


def test_a_server_error_is_waited_out_before_the_request_is_asked_again(
        monkeypatch, waits):
    step, asked, _runs, _events = computing(monkeypatch, Status(500), CODE,
                                            ANSWER)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(asked) == 3
    # One failure, on the server's long curve; a round of code is no failure.
    assert waits == [(1, True)]
    assert report.tuples[-1]["computed"] is True
    assert runner.UNSERVED.of(7) == 0


def test_a_refused_request_is_asked_once(monkeypatch, waits):
    step, asked, _runs, events = computing(monkeypatch, Status(400), CODE,
                                           ANSWER)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(asked) == 1
    assert waits == []
    assert len(report.tuples) == 2
    assert events[-1]["outcome"] == "unanswered"
    assert runner.UNSERVED.of(7) == 0


def test_a_request_the_server_never_served_leaves_its_document_unfinished(
        monkeypatch, waits):
    tries = runner.MAX_RETRIES + runner.CODE_ROUNDS + 1
    step, asked, _runs, events = computing(monkeypatch,
                                           *[Status(503)] * tries)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(asked) == tries
    # A wait before every attempt but the first.
    assert waits == [(n, True) for n in range(1, tries)]
    assert len(report.tuples) == 2
    assert events[-1]["outcome"] == "unanswered"
    assert runner.UNSERVED.of(7) == 1


# -- the whole of a share, chosen with evidence -------------------------------

SHARE_SAYS = "Der Anteil beträgt 21 %"


def told_in(request: dict) -> str:
    """What the stage told the model last in this request."""
    return request["messages"][-1]["content"]


def test_the_answer_quotes_from_its_whole_what_the_whole_is(monkeypatch):
    # A quote from the share's own passage says nothing of the whole: told,
    # and asked again. One from the whole's passage stands.
    step, asked, _runs, events = computing(
        monkeypatch, CODE, answered(38892.0, quote=SHARE_SAYS), ANSWER)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(asked) == 3
    assert "N2" in told_in(asked[2])
    row = report.tuples[-1]
    assert row["computed"] and row["compute"][-1]["cited"] == WHOLE
    assert events[-1]["misquoted"] == 1


def test_a_whole_never_quoted_leaves_no_row(monkeypatch):
    wrong = answered(38892.0, quote=SHARE_SAYS)
    step, asked, _runs, events = computing(monkeypatch, CODE, *[wrong] * 5)
    report, _done = run_step(step, share(21), amount(185200))
    assert len(report.tuples) == 2 and not report.refusals
    assert events[-1]["outcome"] == "unanswered"


def plan_of(*passages):
    """The plan: the passages of the rows, then *passages* as sections."""
    return [Source("table", 9, f"Abschnitt\n{SHARE_SAYS}",
                   {"document_id": 7, "title": "Tabelle 3"}),
            *(Source("section", 20 + index, text,
                     {"document_id": 7, "title": "Wärmebilanz"})
              for index, text in enumerate(passages))]


BALANCE = "Der Wärmeverbrauch der Stadt beträgt 185.200 MWh im Jahr 2023."


def take(quote="Der Wärmeverbrauch der Stadt beträgt 185.200 MWh",
         **more) -> str:
    return json.dumps({"take": {
        "parameter": "energy_consumption", "value": 185200, "unit": "MWh/a",
        "quantity": "OEO_00050016", "quantity_raw": "Wärmeverbrauch",
        "quote": quote, **more}})


def test_a_share_takes_its_whole_from_a_passage_it_fetched(monkeypatch):
    found = json.dumps({"more": [{"get": "search",
                                  "pattern": "Wärmeverbrauch"}]})
    fetch = json.dumps({"more": [{"get": "hit", "id": "H1"}]})
    step, asked, runs, events = computing(
        monkeypatch, found, fetch, take(), CODE,
        answered(38892.0, quote="Der Wärmeverbrauch der Stadt"),
        plan=plan_of(BALANCE))
    report, done = run_step(step, share(21), amount(185200, year=2030))
    assert done
    shown_now = json.loads(asked[2]["messages"][1]["content"])
    assert shown_now["more"][0]["id"] == "M1"
    numbers = json.loads(asked[3]["messages"][1]["content"])["numbers"]
    assert [n["id"] for n in numbers] == ["N1", "N2"]
    assert numbers[1]["source"] == "M1"
    assert runs[0][1]["numbers"]["N2"] == {"value": 185200,
                                           "unit": "MWh/a"}
    row = report.tuples[-1]
    assert row["computed"] and row["value"] == 38892.0
    assert row["year"] == 2023 and row["carrier"] == OIL
    assert row["quantity"] == "OEO_00050016"
    assert row["quantity_source"] == ["section", 20]
    assert row["compute"][-1]["inputs"][1]["source"] == ["section", 20]
    assert {key: events[-1][key] for key in ("fetched", "searched", "taken")
            } == {"fetched": 1, "searched": 1, "taken": 1}


def test_a_whole_is_read_from_the_passage_its_quote_stands_in(monkeypatch):
    # No passage to name: of all the request showed, the one that carries
    # the quote is the one the whole is read from (owner decision
    # 2026-11-05), here the first of two it fetched.
    onward = json.dumps({"more": [{"get": "next"}]})
    step, _asked, _runs, _events = computing(
        monkeypatch, onward, onward, take(), CODE,
        answered(38892.0, quote="Der Wärmeverbrauch der Stadt"),
        plan=plan_of(BALANCE, "Abschnitt danach."))
    report, _done = run_step(step, share(21))
    row = report.tuples[-1]
    assert row["computed"] and row["quantity_source"] == ["section", 20]


def test_a_whole_not_read_like_a_number_is_not_taken(monkeypatch):
    # Its number not in its quote, a unit its parameter does not take, a
    # quote in no passage shown: each is told, and no number is added.
    for bad in (take(quote="Der Wärmeverbrauch der Stadt beträgt"),
                take(unit="Tonnen"),
                take(quote="Der Wärmeverbrauch des Landes beträgt 185.200")):
        step, asked, _runs, events = computing(
            monkeypatch, json.dumps({"more": [{"get": "next"}]}), bad,
            NOTHING, plan=plan_of(BALANCE))
        report, _done = run_step(step, share(21))
        assert len(report.tuples) == 1
        assert "take" in told_in(asked[2])
        assert events[-1]["untaken"] == 1 and events[-1]["taken"] == 0


def test_a_whole_whose_quantity_its_quote_does_not_say_leaves_it_open(
        monkeypatch):
    step, _asked, _runs, _events = computing(
        monkeypatch, json.dumps({"more": [{"get": "next"}]}),
        take(quantity_raw="Endenergiebedarf"), CODE,
        answered(38892.0, quote="Der Wärmeverbrauch der Stadt"),
        plan=plan_of(BALANCE))
    report, _done = run_step(step, share(21))
    row = report.tuples[-1]
    assert row["computed"] and row["quantity_state"] == fields.UNBACKED


def test_a_round_that_fetches_something_new_is_no_attempt(monkeypatch):
    # Six sections read one after another, more than the attempts a request
    # has, and the answer after them still counts.
    onward = json.dumps({"more": [{"get": "next"}]})
    step, _asked, _runs, events = computing(
        monkeypatch, *[onward] * 6, CODE, ANSWER,
        plan=plan_of(*(f"Abschnitt {n} des Plans." for n in range(6))))
    report, _done = run_step(step, share(21), amount(185200))
    assert report.tuples[-1]["computed"]
    assert events[-1]["fetched"] == 6 and events[-1]["outcome"] == "read"


def test_the_request_offers_the_search_only_with_the_plan(monkeypatch):
    for plan, offered in ((None, False), (plan_of(BALANCE), True)):
        step, asked, _runs, _events = computing(monkeypatch, NOTHING,
                                                plan=plan)
        run_step(step, share(21), amount(185200))
        reply = json.dumps(asked[0]["response_format"])
        assert ('"more"' in reply) is offered
        assert '"take"' in reply and '"quote"' in reply


def test_a_document_with_nothing_open_asks_nothing(monkeypatch):
    step, asked, _runs, _events = computing(monkeypatch)
    _report, done = run_step(step, amount(200))
    assert done and asked == []


def test_the_inputs_are_the_numbers_the_answer_names(monkeypatch):
    named = answered(38892.0)
    step, _asked, _runs, _events = computing(monkeypatch, CODE, named)
    report, _done = run_step(step, amount(30000, GAS), amount(8892, OIL),
                             amount(500, HEAT))
    inputs = report.tuples[-1]["compute"][-1]["inputs"]
    assert sorted(i["value"] for i in inputs) == [8892, 30000]


def test_an_answer_naming_no_number_used_them_all(monkeypatch):
    step, _asked, _runs, _events = computing(
        monkeypatch, CODE, json.dumps({"value": 38892.0}))
    report, _done = run_step(step, amount(30000, GAS), amount(8892, OIL))
    assert len(report.tuples[-1]["compute"][-1]["inputs"]) == 2


def test_a_stop_says_the_document_is_unfinished(monkeypatch):
    step, asked, _runs, events = computing(monkeypatch)
    stop = SimpleNamespace(is_set=lambda: True)
    _report, done = run_step(step, share(21), amount(185200), stop=stop)
    assert not done and asked == []
    assert events[-1]["outcome"] == "stopped"


def test_without_a_sandbox_there_is_no_step(monkeypatch):
    monkeypatch.setattr(code_exec, "is_enabled", lambda: False)
    assert runner.make_computer(PROFILE) is None


def test_a_profile_naming_no_question_has_no_step(monkeypatch):
    monkeypatch.setattr(code_exec, "is_enabled", lambda: True)
    silent = SimpleNamespace(component=lambda module, attr: None)
    assert runner.make_computer(silent) is None


def test_the_reply_names_only_the_numbers_of_its_question():
    shape = replies.compute(["N1", "N2"])
    jsonschema.validate({"value": 1.5, "used": ["N1"]}, shape)
    jsonschema.validate({"value": None, "used": []}, shape)
    jsonschema.validate({"action": "python", "code": "print(1)"}, shape)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"value": 1.5, "used": ["N3"]}, shape)


def test_the_trace_of_the_step_fits_its_schema(monkeypatch):
    step, _asked, _runs, events = computing(monkeypatch, CODE, ANSWER)
    run_step(step, share(21), amount(185200))
    # each of the two requests (the code, then the answer) writes its ask
    assert [e["t"] for e in events] == ["compute_ask", "code", "compute_ask",
                                        "compute"]
    for event in events:
        jsonschema.validate(event, schema.trace_schema())


def test_the_statistics_count_the_questions_by_how_they_ended(tmp_path):
    trace = tmp_path / "plan.trace.jsonl"
    trace.write_text("\n".join(json.dumps(
        {"t": "compute", "kind": "sum", "outcome": outcome})
        for outcome in ("read", "read", "none")) + "\n", encoding="utf-8")
    assert stats.from_traces([tmp_path])[
        "computed_questions_by_kind_outcome"] == {"sum": {"read": 2, "none": 1}}


def test_a_row_is_checked_against_its_own_parameter(monkeypatch):
    step, _asked, _runs, _events = computing(monkeypatch, CODE, ANSWER)
    rows = share(21), amount(185200)
    report = report_of(*rows)
    batch = batch_of(*rows)
    batch.items[0] = WorkItem(7, SPEC.by_uri["share"], batch.items[0].source)
    step([(batch, {})], report, spec=SPEC)
    assert len(report.tuples) == 3
    assert report.tuples[-1]["parameter"] == "energy_consumption"


# -- what its inputs make ----------------------------------------------------

def test_a_share_makes_its_part_of_the_one_total_named():
    question = only(share(21), amount(185200))
    assert question.makes(question.numbers) == pytest.approx(38892)
    assert question.makes(question.numbers[:1]) is None


def test_a_sum_makes_the_parts_it_names():
    question = only(amount(120, GAS), amount(80, OIL), amount(50, HEAT))
    assert question.makes(question.numbers) == 250
    assert question.makes(question.numbers[:2]) == 200


def test_the_row_carries_what_its_inputs_make(monkeypatch):
    step, _asked, _runs, _events = computing(monkeypatch, CODE, ANSWER)
    report, _done = run_step(step, share(21), amount(185200))
    assert report.tuples[-1]["compute"][-1]["expected"] == pytest.approx(38892)


def test_a_printed_number_its_inputs_do_not_make_is_refused(monkeypatch):
    other = answered(40000.0)
    step, _asked, _runs, events = computing(monkeypatch, CODE, other,
                                            ran=printed(40000.0))
    report, _done = run_step(step, share(21), amount(185200))
    assert len(report.tuples) == 2
    reason = report.refusals[-1]["reason"]
    assert reason == "value 40000.0 does not follow from its inputs"
    assert any(re.match(p, reason) for p in schema.REFUSAL_REASONS)
    assert events[-1]["outcome"] == "refused"


def test_a_sum_of_other_numbers_than_it_names_is_refused(monkeypatch):
    for total, kept in ((200.0, 3), (210.0, 2)):
        said = answered(total)
        step, _asked, _runs, _events = computing(monkeypatch, CODE, said,
                                                 ran=printed(total))
        report, _done = run_step(step, amount(120, GAS), amount(80, OIL))
        assert len(report.tuples) == kept, total


def test_a_number_follows_to_the_rounding_it_is_written_with(monkeypatch):
    # 21 % of 185,201 is 38,892.21.
    for written, kept in ((38892.2, 3), (38892.21, 3), (38893.0, 2)):
        said = answered(written)
        step, _asked, _runs, _events = computing(monkeypatch, CODE, said,
                                                 ran=printed(written))
        report, _done = run_step(step, share(21), amount(185201))
        assert len(report.tuples) == kept, written


# -- one statement, worked out twice -----------------------------------------

def worked_twice(monkeypatch, first, second, values=(38892.0, 38892.0)):
    """Two questions answered in turn, each with its own code."""
    monkeypatch.setattr(runner, "FIELD_PARALLEL", 1)
    said = []
    for index, value in enumerate(values):
        said += [json.dumps({"action": "python",
                             "code": f"print({value})  # {index}"}),
                 answered(value)]
    step, _asked, _runs, events = computing(
        monkeypatch, *said, ran=[printed(value) for value in values])
    report, _done = run_step(step, first, second, amount(185200))
    made = [row for row in report.tuples if row.get("computed")]
    return made, [e for e in events if e["t"] == "compute"], events


def test_two_questions_coming_to_one_statement_leave_one_row(monkeypatch):
    made, asked, events = worked_twice(monkeypatch, share(21, owner=9),
                                       share(21, owner=10))
    assert len(made) == 1
    assert [e["outcome"] for e in asked] == ["read", "same"]
    for event in events:
        jsonschema.validate(event, schema.trace_schema())


def test_the_same_number_on_other_coordinates_is_two_rows(monkeypatch):
    made, _asked, _events = worked_twice(monkeypatch, share(21, OIL, owner=9),
                                         share(21, GAS, owner=10))
    assert sorted(row["carrier"] for row in made) == sorted([OIL, GAS])


def test_another_number_on_the_same_coordinates_is_two_rows(monkeypatch):
    made, _asked, _events = worked_twice(monkeypatch, share(21, owner=9),
                                         share(22, owner=10),
                                         values=(38892.0, 40744.0))
    assert sorted(row["value"] for row in made) == [38892.0, 40744.0]


def test_a_number_the_rows_request_worked_out_names_no_inputs_and_stands():
    text = "| Gas | 300 MWh/a | Öl | 200 MWh/a |"
    claim = {**amount(500), "quote": text, "computed": True,
             "compute": [{"code": "print(300 + 200)", "stdout": "500\n",
                          "ok": True, "error": None}]}
    outcome = verify.verify_tuple(claim, SPEC.by_uri["energy_consumption"],
                                  text, owner_kind="table")
    assert not isinstance(outcome, verify.Refusal)
    named = {**claim, "compute": [{**claim["compute"][0], "inputs": [],
                                   "expected": 450}]}
    assert isinstance(verify.verify_tuple(
        named, SPEC.by_uri["energy_consumption"], text, owner_kind="table"),
        verify.Refusal)
