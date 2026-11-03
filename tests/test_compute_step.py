"""What a document's verified rows leave open is worked out in the sandbox: the
questions are found by rule, a number repeated in two passages counts once, the
model writes the code, and the new row carries code, output and inputs. Each
promise has a case that breaks it by construction beside the one that keeps
it."""
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from docpipe.app import sandbox_service
from docpipe.extraction import compute, fields, pipeline, replies, runner
from docpipe.extraction import schema, stats
from docpipe.extraction.pipeline import Source, WorkItem
from docpipe.extraction.spec import load as load_spec
from docpipe.inference import code_exec
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


def test_a_share_without_a_total_in_its_frame_is_not_asked():
    assert kinds(share(21), amount(185200, year=2030)) == []


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


def test_a_number_the_gate_closed_is_no_part():
    closed = [{**amount(value, carrier), "quantity": "out:potential"}
              for value, carrier in ((120, GAS), (80, OIL))]
    assert kinds(*closed) == []


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
    assert kinds(share(21), amount(0)) == []


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


PROFILE = SimpleNamespace(component=lambda module, attr: rules.questions)


def computing(monkeypatch, *said, ran=None):
    """A compute step whose model says *said* in turn. Its requests, the code
    runs with what they were handed, and the trace."""
    told = iter(said)
    asked, runs, events = [], [], []

    def create(**request):
        asked.append(request)
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=next(told)))])

    def run_code(code, context=None, timeout=None):
        runs.append((code, context))
        return ran or {"ok": True, "stdout": "38892.0\n", "error": None}

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(code_exec, "is_enabled", lambda: True)
    monkeypatch.setattr(code_exec, "run_code", run_code)
    monkeypatch.setattr(runner.trace, "event", lambda kind, doc=None, /, **f:
                        events.append({"t": kind, "doc": doc, **f}))
    return runner.make_computer(PROFILE), asked, runs, events


CODE = json.dumps({"action": "python", "code": "print(185200 * 0.21)"})
ANSWER = json.dumps({"value": 38892.0, "used": ["N1", "N2"]})
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
    wrong = json.dumps({"value": 40000.0, "used": ["N1", "N2"]})
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


def test_a_document_with_nothing_open_asks_nothing(monkeypatch):
    step, asked, _runs, _events = computing(monkeypatch)
    _report, done = run_step(step, amount(200))
    assert done and asked == []


def test_the_inputs_are_the_numbers_the_answer_names(monkeypatch):
    named = json.dumps({"value": 38892.0, "used": ["N1", "N3"]})
    step, _asked, _runs, _events = computing(monkeypatch, CODE, named)
    report, _done = run_step(step, amount(30000, GAS), amount(8892, OIL),
                             amount(500, HEAT))
    inputs = report.tuples[-1]["compute"][-1]["inputs"]
    assert len(inputs) == 2


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
    assert [e["t"] for e in events] == ["code", "compute"]
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
