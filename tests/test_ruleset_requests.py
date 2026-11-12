"""The values of asking the model are rules, and a rule decides where the
request is sent, in the step that sends it (owner 2026-11-11: "alles soll
anpassbar sein"; docpipe/ruleset/requests.py).

The promise: the value of the rule decides, read at the time of use. Each
case sets the rule at a step (`rules.in_step`) or for the run
(`rules.overlaid`) and sees the code do another thing, and the same code with
today's standard does today's.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from docpipe import llm_preflight, providers, rules
from docpipe.extraction import runner, scheduler, throttle
from docpipe.providers import base, governor

from conftest import in_turn


class Status(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def at(box, **values):
    """Read with these values for a step of this kind."""
    return rules.in_step(rules.stepped({"id": "x", "box": box}, values))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for env in rules.ENVS:
        monkeypatch.delenv(env, raising=False)
    rules.reset()
    yield
    rules.reset()


# -- the model, the extras and the grammar of a request -----------------------

def test_the_model_of_a_request_is_the_step_s_then_the_run_s():
    assert runner.llm_model() == "Qwen/Qwen3.5-122B-A10B-FP8"
    with at("find", model="other-model"):
        assert runner.llm_model() == "other-model"
    with rules.overlaid(model="the-run-s"):
        assert runner.llm_model() == "the-run-s"
        with at("find", model="other-model"):
            assert runner.llm_model() == "other-model"


def test_the_setting_of_the_start_is_the_run_s_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-the-start")
    rules.reset()
    assert runner.llm_model() == "from-the-start"


def sent_by(step_values: dict):
    """The keyword arguments the one request function sends, read in a step
    that sets *step_values*."""
    taken = {}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: taken.update(kwargs))))
    with at("find", **step_values):
        runner.send_request(client, "system", [{"role": "user",
                                                "content": "x"}], 100, 0)
    return taken


def test_every_request_carries_the_model_and_extras_of_its_step():
    standard = sent_by({})
    assert standard["model"] == "Qwen/Qwen3.5-122B-A10B-FP8"
    assert standard["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "low", "tool_choice": "none"}
    assert standard["temperature"] == 0 and standard["max_tokens"] == 100
    own = sent_by({"model": "m", "thinking": True, "reasoning_effort": "high",
                   "tool_choice": "", "temperature": 0.5})
    assert own["model"] == "m" and own["temperature"] == 0.5
    assert own["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": True},
        "reasoning_effort": "high"}
    assert sent_by({"reasoning_effort": "off"})["extra_body"].get(
        "reasoning_effort") is None


def test_the_grammar_goes_out_as_the_step_says():
    schema = {"type": "object"}
    assert providers.reply_format("llm", "x", schema) is None
    with at("phrase", schema_grammar="all"):
        assert providers.reply_format("llm", "x", schema)["type"] \
            == "json_schema"
        assert runner.reply_grammar("x", schema) is not None
    assert runner.reply_grammar("x", schema, always=True) is not None


def test_the_longest_answer_is_the_step_s():
    assert runner.request_wanted("find") == rules.get("max_tokens")
    with at("find", max_tokens=111):
        assert runner.request_wanted("find") == 111


def test_the_room_of_an_answer_follows_the_window_and_the_margin(monkeypatch):
    monkeypatch.setattr(runner, "_SERVED_WINDOW", None)
    conversation = [{"role": "user", "content": "x" * 262}]
    room = runner.answer_room("", conversation, 10 ** 6)
    with rules.overlaid(model_window_tokens=40000):
        assert runner.answer_room("", conversation, 10 ** 6) == room + 7232
    with at("find", answer_margin_tokens=0):
        assert runner.answer_room("", conversation, 10 ** 6) == room + 256
    with at("find", prompt_chars_per_token=1.31):
        assert runner.answer_room("", conversation, 10 ** 6) < room
    # less than the least room: the request is not sent
    with rules.overlaid(model_window_tokens=700):
        assert runner.request_room("", conversation, 10 ** 6) is None
    # an answer asked for that is shorter than the least room is not sent,
    # unless the room of the whole window is what counts (a search sentence)
    assert runner.request_room("", conversation, 5) is None
    assert runner.request_room("", conversation, 5, whole=True) == 5


# -- asking again -------------------------------------------------------------

def test_the_replies_a_request_takes_are_the_step_s(monkeypatch):
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)

    def asked(**values):
        failures = runner.Failures(7)
        taken = 0
        with at("find", **values):
            for _ in failures.attempts():
                taken += 1
                failures.fault()
                if taken > 10:
                    break
        return taken
    assert asked() == 3                      # the standard of the flow
    assert asked(replies=1) == 1
    assert asked(replies=5) == 5


def test_a_refusal_is_asked_as_often_as_the_rule_says(monkeypatch):
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    failures = runner.Failures(7)
    assert [failures.failed(Status(400)) for _ in range(3)] \
        == [True, True, False]
    with at("find", refusal_retry_most=1):
        assert runner.Failures(7).failed(Status(400)) is False
    with at("find", refusal_retry_most=5):
        many = runner.Failures(7)
        assert [many.failed(Status(400)) for _ in range(5)] \
            == [True] * 4 + [False]


def test_which_statuses_are_the_server_s_failure_is_the_rule():
    assert runner.unserved(Status(503)) and runner.refused(Status(400))
    assert not runner.refused(Status(429))
    with at("find", server_failure_statuses=["429"]):
        assert not runner.unserved(Status(503))
    with at("find", server_failure_statuses=["429", "400-404", "timeout"]):
        assert runner.unserved(Status(400)) and not runner.refused(Status(404))
        assert runner.refused(Status(405))
    with at("find", server_failure_statuses=["x"]):
        with pytest.raises(ValueError, match="no status"):
            runner.unserved(Status(500))


def test_the_server_s_failure_is_asked_without_a_limit_or_as_often_as_set(
        monkeypatch):
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    failures = runner.Failures(7)
    assert all(failures.failed(Status(500)) for _ in range(50))
    with at("find", server_retry_most=2):
        limited = runner.Failures(7)
        assert limited.failed(Status(500)) is True
        assert limited.failed(Status(500)) is False
        assert limited.lost                     # the document stays unfinished


def test_a_search_is_asked_again_until_it_answers_or_the_limit(monkeypatch):
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    calls = []

    def failing(*args):
        calls.append(args)
        raise ConnectionError("gone")
    with at("search", search_retry_most=3):
        with pytest.raises(ConnectionError):
            runner.persistently("search", failing)(1)
    assert len(calls) == 3

    answers = in_turn([ConnectionError("a")] * 7 + ["ok"], "the search")

    def later(*args):
        got = answers()
        if isinstance(got, Exception):
            raise got
        return got
    assert runner.persistently("search", later)(1) == "ok"


def test_the_waits_grow_as_the_rule_says(monkeypatch):
    monkeypatch.setattr(providers, "replaying", lambda: False)
    standard = [runner.retry_wait(n, True) for n in (1, 2, 3)]
    assert standard == [rules.get("transport_wait_s") * k for k in (1, 2, 4)]
    short = [runner.retry_wait(n, False) for n in (1, 2, 3)]
    assert short == [rules.get("retry_wait_s") * k for k in (1, 2, 3)]
    with at("find", retry_wait_growth="linear"):
        assert [runner.retry_wait(n, True) for n in (1, 2, 3)] \
            == [rules.get("transport_wait_s") * k for k in (1, 2, 3)]
    with at("find", retry_wait_growth="doubling"):
        most = rules.get("retry_wait_most_s")
        assert [runner.retry_wait(n, False) for n in (1, 2, 3)] \
            == [min(rules.get("retry_wait_s") * k, most) for k in (1, 2, 4)]


def test_a_document_is_stamped_as_the_rules_say():
    lost = runner.not_happened(SimpleNamespace(refusals=[],
                                               owners_harvested=3),
                               answered=3, lost=1)
    assert lost == ("unserved", 1, 1)
    with at("write", unserved_unstamped=False):
        assert runner.not_happened(SimpleNamespace(refusals=[],
                                                   owners_harvested=3),
                                   answered=3, lost=1) is None
    nothing = SimpleNamespace(refusals=[], owners_harvested=3)
    assert runner.not_happened(nothing, answered=0)[0] == "no_reply"
    with at("write", stamp_without_reply=True):
        assert runner.not_happened(nothing, answered=0) is None


def reply_of(text, finish="stop"):
    return SimpleNamespace(finish_reason=finish, message=SimpleNamespace(
        content=text, reasoning_content=None))


def test_what_a_retry_shows_of_the_broken_answer_is_the_rule():
    text = '{"a": 1, "b": ' + "x" * 300
    _cause, said = runner._reply_fault(reply_of(text), 100)
    with at("find", fault_excerpt_chars={"before": 3, "after": 3,
                                          "foreign": 5}):
        _cause, less = runner._reply_fault(reply_of(text), 100)
    assert len(less) < len(said)
    foreign = 'x {"a": 1} ' + "y" * 400
    _cause, long = runner._reply_fault(reply_of(foreign), 100)
    with at("find", fault_excerpt_chars={"before": 60, "after": 20,
                                          "foreign": 10}):
        _cause, short = runner._reply_fault(reply_of(foreign), 100)
    assert len(short) < len(long)


SHAPE = {"type": "json_schema", "json_schema": {
    "name": "x", "schema": {"type": "object", "required": ["found"],
                            "properties": {"found": {"type": "array"}}}}}


def replying(*said):
    told = iter(said)
    sent = []

    def create(**request):
        sent.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content=next(told), reasoning_content=None))])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), sent


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())


PROMPT = SimpleNamespace(meta={}, text="x", placeholders=frozenset())


def test_an_answer_without_its_key_is_asked_again_or_taken_as_the_rule_says(
        quick):
    client, sent = replying("{}", '{"found": []}')
    assert runner.ask_in_grammar(client, PROMPT, [], SHAPE, 7, "find",
                                 "found") == {"found": []}
    assert len(sent) == 2
    with at("find", missing_key_asks_again=False):
        client, sent = replying("{}", '{"found": []}')
        assert runner.ask_in_grammar(client, PROMPT, [], SHAPE, 7, "find",
                                     "found") == {}
        assert len(sent) == 1


def test_a_retry_shows_the_broken_answer_or_asks_the_same_as_the_rule_says(
        quick):
    client, sent = replying("nonsense", '{"found": []}')
    runner.ask_in_grammar(client, PROMPT, [], SHAPE, 7, "find", "found")
    assert len(sent[1]) == len(sent[0]) + 2
    with at("find", retry_shows_reply=False):
        client, sent = replying("nonsense", '{"found": []}')
        runner.ask_in_grammar(client, PROMPT, [], SHAPE, 7, "find", "found")
        assert sent[1] == sent[0]


def test_a_request_the_window_has_no_room_for_is_not_sent(quick):
    client, sent = replying('{"found": []}')
    with rules.overlaid(model_window_tokens=300):
        assert runner.ask_in_grammar(client, PROMPT, [], SHAPE, 7, "find",
                                     "found") == "cut_off"
    assert sent == []


# -- the timeouts -------------------------------------------------------------

def test_the_time_a_repeat_waits_is_read_where_the_request_is_sent(
        monkeypatch):
    seen = []

    def create(**request):
        seen.append(request.get("timeout"))
        raise TimeoutError("slow")
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(providers, "timed_out", lambda exc: True)
    messages = [{"role": "user", "content": "x"}]
    for values, expected in (({}, [None, 600]),
                             ({"repeat_timeout_s": 777}, [None, 777]),
                             # a step's own time goes with its first request
                             ({"repeat_timeout_s": 50,
                               "llm_timeout_s": 900}, [900, 900])):
        seen.clear()
        repeating = scheduler.Repeats(client)
        with at("find", **values):
            for _ in range(2):
                with pytest.raises(TimeoutError):
                    repeating.create(messages=messages)
        assert seen == expected, values


# -- the load of the server ---------------------------------------------------

def test_the_numbers_of_the_limit_are_the_rules():
    standard = throttle.AdaptiveLimit()
    assert (standard.minimum, standard.maximum, standard.limit) \
        == (16, 512, 128)
    with rules.overlaid(limit_least=2, limit_most=9, limit_start=5):
        small = throttle.AdaptiveLimit()
        assert (small.minimum, small.maximum, small.limit) == (2, 9, 5)
    assert not hasattr(throttle, "MAXIMUM")       # no bridge of old names


def sample(**more):
    values = dict(running=10, waiting=0, kv=0.5, preempted=0.0, tpot=None)
    values.update(more)
    return throttle.Sample(**values)


def test_the_limit_decides_by_its_rules():
    limit = throttle.AdaptiveLimit(start=100, minimum=10, maximum=500)
    up, _ = throttle.Controller(limit).decide(sample(), used=100)
    assert up == 108
    with rules.overlaid(limit_step=20):
        assert throttle.Controller(limit).decide(sample(), used=100)[0] == 120
    with rules.overlaid(limit_backoff=0.5, limit_kv_high=0.7,
                        limit_kv_grow=0.6):
        down, why = throttle.Controller(limit).decide(sample(kv=0.75), 100)
        assert down == 50 and "KV" in why
    # a limit that is not reached does not grow, unless the rule says so
    assert throttle.Controller(limit).decide(sample(), used=10)[0] == 100
    with rules.overlaid(limit_grow_only_when_used=False):
        assert throttle.Controller(limit).decide(sample(), used=10)[0] == 108
    # a preemption steps down, unless the rule says no
    assert throttle.Controller(limit).decide(sample(preempted=2), 100)[0] \
        == 80
    with rules.overlaid(limit_down_on_preemption=False):
        assert throttle.Controller(limit).decide(sample(preempted=2),
                                                 100)[0] == 108
    # the token time steps down only where the rule gives a time
    slow = sample(tpot=0.5)
    assert throttle.Controller(limit).decide(slow, 100)[0] == 108
    with rules.overlaid(limit_token_time_s=0.1):
        assert throttle.Controller(limit).decide(slow, 100)[0] == 80


def test_waiting_samples_and_the_hold_are_the_rules():
    limit = throttle.AdaptiveLimit(start=100, minimum=10, maximum=500)
    waiting = sample(waiting=3)
    control = throttle.Controller(limit)
    assert control.decide(waiting, 100)[0] == 100
    assert control.decide(waiting, 100)[0] == 80        # the second look
    limit.resize(80)
    held = [control.decide(sample(), 80)[0] for _ in range(6)]
    assert held == [80] * 6                              # held six looks
    assert control.decide(sample(), 80)[0] == 88
    with rules.overlaid(limit_waiting_samples=1, limit_hold_samples=0):
        limit.resize(100)
        quick = throttle.Controller(limit)
        assert quick.decide(waiting, 100)[0] == 80
        limit.resize(80)
        assert quick.decide(sample(), 80)[0] == 88


def test_a_cache_mark_to_grow_above_the_one_to_fall_is_refused():
    with rules.overlaid(limit_kv_grow=0.95, limit_kv_high=0.9):
        with pytest.raises(ValueError, match="limit_kv_grow"):
            throttle.Controller(throttle.AdaptiveLimit())


def test_a_server_without_metrics_has_no_limit_or_a_fixed_one():
    class Mute:
        url = "http://x/metrics"

        def sample(self):
            raise OSError("no metrics")
    assert throttle.start("http://x/v1", reader=Mute()) is None
    with rules.overlaid(limit_without_metrics="fixed", limit_start=7):
        fixed = throttle.start("http://x/v1", reader=Mute())
        assert (fixed.minimum, fixed.maximum, fixed.limit) == (7, 7, 7)


def test_a_hosted_api_starts_at_the_rule(monkeypatch):
    monkeypatch.setattr(throttle.threading, "Thread",
                        lambda **k: SimpleNamespace(start=lambda: None))
    gate = governor.Gate("x")
    assert throttle.start_hosted(gate).limit == 16
    with rules.overlaid(limit_start_hosted=33):
        assert throttle.start_hosted(governor.Gate("y")).limit == 33


# -- the queue and the lanes --------------------------------------------------

class Counted:
    """A client that counts how many requests are open at once."""

    def __init__(self, hold=0.05):
        self.hold = hold
        self.open = 0
        self.most = 0
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=self.create))

    def create(self, **kwargs):
        with self.lock:
            self.open += 1
            self.most = max(self.most, self.open)
        time.sleep(self.hold)
        with self.lock:
            self.open -= 1
        return "answer"


def asked_together(client, count, **values):
    """*count* requests of one step with *values*, all asked at once."""
    queue = scheduler.Scheduler(throttle.AdaptiveLimit(start=4, minimum=4,
                                                       maximum=4))
    sent = scheduler.Scheduled(client, queue)
    import contextvars

    def one(_):
        return sent.create(messages=[{"role": "user", "content": "x"}])
    with at("find", **values):
        with ThreadPoolExecutor(count) as pool:
            futures = [pool.submit(contextvars.copy_context().run, one, i)
                       for i in range(count)]
    return [future.result() for future in futures]


def test_a_step_with_its_own_parallel_has_a_lane_of_its_own():
    shared = Counted()
    asked_together(shared, 12)
    assert shared.most == 4                     # the shared limit
    lane = Counted()
    asked_together(lane, 12, parallel=2)
    assert lane.most == 2                       # down from the shared one
    wider = Counted()
    asked_together(wider, 12, parallel=7)
    assert 4 < wider.most <= 7                  # up from it


def test_the_other_steps_keep_sharing_the_limit_while_a_lane_is_busy():
    client = Counted(0.1)
    queue = scheduler.Scheduler(throttle.AdaptiveLimit(start=3, minimum=3,
                                                       maximum=3))
    sent = scheduler.Scheduled(client, queue)
    import contextvars

    def one(_):
        return sent.create(messages=[{"role": "user", "content": "x"}])
    jobs = []
    with ThreadPoolExecutor(12) as pool:
        with at("find", parallel=2):
            jobs += [pool.submit(contextvars.copy_context().run, one, i)
                     for i in range(4)]
        jobs += [pool.submit(contextvars.copy_context().run, one, i)
                 for i in range(8)]
    assert all(job.result() == "answer" for job in jobs)
    assert client.most <= 3 + 2                 # shared limit plus the lane
    assert client.most > 3                      # and the lane really is apart


def test_the_queue_serves_the_documents_in_the_order_of_the_rule():
    queue = scheduler.Scheduler(throttle.AdaptiveLimit(start=1, minimum=1,
                                                       maximum=1))
    first, second = queue.rank(10), queue.rank(11)
    assert first < second < queue.rank(None) + (1 << 61)
    assert queue.rank(None) < first
    with rules.overlaid(queue_order="newest_document"):
        assert queue.rank(11) < queue.rank(10)
    with rules.overlaid(queue_order="arrival"):
        assert queue.rank(10) == queue.rank(11) == 0


# -- the hosted APIs ----------------------------------------------------------

def test_the_gate_holds_as_the_rules_say():
    now = [0.0]
    gate = governor.Gate("x", clock=lambda: now[0], sleep=lambda s: None)
    assert gate.limited() == 2
    now[0] += 5
    assert gate.limited() == 4                    # doubled
    now[0] += 50
    with rules.overlaid(rate_hold_start_s=7, rate_hold_most_s=9):
        fresh_gate = governor.Gate("y", clock=lambda: now[0])
        assert fresh_gate.limited() == 7
        now[0] += 100
        assert fresh_gate.limited() == 9          # the most
        now[0] += 100
        assert fresh_gate.limited(retry_after=1000) == 9 * 5
    with rules.overlaid(rate_hold_server_factor=2, rate_hold_most_s=9):
        assert governor.Gate("z", clock=lambda: now[0]).limited(1000) == 18


def test_a_closed_gate_waits_only_where_the_rule_is_on():
    now = [0.0]
    slept = []
    gate = governor.Gate("x", clock=lambda: now[0],
                         sleep=lambda s: slept.append(s) or now.__setitem__(
                             0, now[0] + s))
    gate.limited()
    with rules.overlaid(rate_gate=False):
        gate.wait()
    assert slept == []
    gate.wait()
    assert slept and gate.closed() is False


def test_which_statuses_close_the_gate_is_the_rule():
    gate = governor.Gate("x")

    def failing(**_):
        raise Status(503)
    client = governor.Governed(SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=failing))), gate)
    with rules.overlaid(rate_limited_statuses=["429"]):
        with pytest.raises(Status):
            client.chat.completions.create()
        assert not gate.closed()
    with pytest.raises(Status):
        client.chat.completions.create()
    assert gate.closed()


def test_a_hosted_api_thinks_and_writes_its_schema_as_the_step_says():
    endpoint = base.Endpoint("llm", "openai")
    assert base.thinking_room(endpoint) == 8192
    with at("find", thinking_room_tokens=100):
        assert base.thinking_room(endpoint) == 100
    assert base.optional_budget() == (24, 16)
    with at("find", schema_optional_fields=3):
        assert base.optional_budget() == (3, 16)
    with at("find", schema_optional_alternatives=2):
        assert base.optional_budget() == (24, 2)
    either = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    wanted = {"type": "json_schema", "json_schema": {"name": "x", "schema": {
        "type": "object", "properties": {"a": either, "b": either,
                                         "c": either},
        "required": ["a", "b", "c"], "additionalProperties": False}}}
    assert base.enforced(wanted, "optional", base.optional_budget())[0] \
        == "x"
    with at("find", schema_optional_alternatives=2):
        with pytest.raises(base.ProviderError):
            base.enforced(wanted, "optional", base.optional_budget())
    assert base.schema_dialect("optional") == "optional"
    with at("find", schema_dialect="all_required"):
        assert base.schema_dialect("optional") == "all-required"
    with at("find", schema_dialect="optional"):
        assert base.schema_dialect("all-required") == "optional"


def test_the_options_of_a_request_are_the_step_s_json():
    endpoint = base.Endpoint("llm", "openai")
    assert base.options_of(endpoint) == {}
    with at("find", request_options='{"top_k": 5}'):
        assert base.options_of(endpoint) == {"top_k": 5}
        assert providers.request_options("llm") == {"top_k": 5}
    with at("find", request_options="[1]"):
        with pytest.raises(ValueError):
            providers.request_options("llm")


# -- the check before the run -------------------------------------------------

def test_the_check_refuses_a_step_whose_model_the_server_does_not_offer(
        monkeypatch):
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda *a, **k: (["served"], 100))
    llm_preflight.assert_step_models("http://x", "k", {"find": "served"})
    llm_preflight.assert_step_models("http://x", "k", {})
    with pytest.raises(llm_preflight.PreflightError,
                       match="coord asks 'nope'"):
        llm_preflight.assert_step_models("http://x", "k",
                                         {"find": "served", "coord": "nope"})


def test_the_steps_that_name_a_model_are_found_in_the_drawing(monkeypatch):
    tree = [{"id": "a", "box": "find", "rules": {"model": "m1"}},
            {"id": "f", "each": "value", "steps": [
                {"id": "b", "box": "coord", "rules": {"model": "m2"}},
                {"id": "c", "box": "search"}]}]
    monkeypatch.setattr(runner.flow_map, "tree_of", lambda profile=None: tree)
    assert runner.step_models() == {"a": "m1", "b": "m2"}
    # A step that is off, or stands in a frame that is off, asks nothing:
    # the check does not need its model.
    tree[0]["off"] = True
    assert runner.step_models() == {"b": "m2"}
    tree[1]["off"] = True
    assert runner.step_models() == {}


def test_a_refusal_of_a_probe_stops_the_run_only_where_the_rule_says():
    assert llm_preflight.refused(Status(400))
    assert not llm_preflight.refused(Status(429))
    assert not llm_preflight.refused(Status(500))
    with rules.overlaid(preflight_refusal_stops=False):
        assert not llm_preflight.refused(Status(400))


def test_the_probes_of_the_check_take_their_time_and_tokens_from_the_rules(
        monkeypatch):
    seen = {}

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: seen.update(kw) or SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                    finish_reason="stop")])))

    def client(role, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return Client()
    monkeypatch.setattr(llm_preflight.providers, "client", client)
    monkeypatch.setattr(llm_preflight.providers, "provider",
                        lambda role: "openai-compatible")
    llm_preflight.assert_reply_schema("http://x", "k", "m")
    assert (seen["timeout"], seen["max_tokens"]) == (60, 32)
    with rules.overlaid(preflight_probe_timeout_s=5, preflight_probe_tokens=9):
        llm_preflight.assert_reply_schema("http://x", "k", "m")
    assert (seen["timeout"], seen["max_tokens"]) == (5, 9)


# -- windows, images, pools ---------------------------------------------------

def test_a_crop_is_scaled_once_for_each_size_and_format_asked(tmp_path):
    from PIL import Image
    path = tmp_path / "crop.png"
    Image.new("RGB", (400, 300), "white").save(path)
    runner._IMAGES.clear()
    big = runner._image_data_url(str(path))
    assert big.startswith("data:image/png;base64,")
    with at("transcribe", image_max_side=100):
        small = runner._image_data_url(str(path))
    assert small != big                       # not the first size for ever
    with at("transcribe", image_format="jpeg"):
        assert runner._image_data_url(str(path)).startswith(
            "data:image/jpeg;base64,")
    runner._IMAGES.clear()
    with at("transcribe", image_cache_crops=1):
        runner._image_data_url(str(path))
        with at("transcribe", image_cache_crops=1, image_max_side=64):
            runner._image_data_url(str(path))
        assert len(runner._IMAGES) == 1
    with at("transcribe", image_cache_crops=0):
        runner._IMAGES.clear()
        runner._image_data_url(str(path))
        assert len(runner._IMAGES) == 0
    with at("transcribe", image_token_side_px=14):
        assert runner.image_tokens() > 4 * (rules.get("image_max_side")
                                            // 28) ** 2
    runner._IMAGES.clear()


def test_the_slots_and_the_threads_follow_the_rules():
    assert runner.sandbox_slots() is runner.sandbox_slots()
    with at("compute", code_slots=3):
        three = runner.sandbox_slots()
    assert three is not runner.sandbox_slots()
    with rules.overlaid(compute_parallel=2):
        assert runner.compute_pool()._max_workers == 2
    assert runner.compute_pool()._max_workers == 192


def test_the_server_is_watched_with_the_numbers_of_the_rules():
    looks = []
    dead = []
    clock = [0.0]

    def sleep(seconds):
        looks.append(seconds)
        clock[0] += seconds
    with rules.overlaid(server_probe_every_s=7, server_dead_after_s=20):
        thread = runner.watch_server(dead.append, probe=lambda: False,
                                     clock=lambda: clock[0], sleep=sleep)
        thread.join(5)
    assert set(looks) == {7} and dead and dead[0] >= 20


def test_the_documents_are_the_current_ones_and_those_the_rule_names():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE Documents(id INTEGER, filename TEXT, is_current INT);"
        "CREATE TABLE Sections(id INTEGER, document INT);"
        "INSERT INTO Documents VALUES (1,'a.pdf',1),(2,'b.pdf',0),"
        "(3,'c.pdf',1);")
    assert [d[0] for d in runner._documents(conn)] == [1, 3]
    with rules.overlaid(current_versions_only=False):
        assert [d[0] for d in runner._documents(conn)] == [1, 2, 3]
    chosen, missing = runner.select_documents([(1, "a"), (3, "c")], None)
    assert len(chosen) == 2 and not missing
    with rules.overlaid(documents=["3", "9"]):
        chosen, missing = runner.select_documents([(1, "a"), (3, "c")], None)
        assert chosen == [(3, "c")] and missing == [9]


def test_the_stamp_compares_the_keys_of_the_rule_where_nothing_finer_is_there(
        tmp_path):
    path = tmp_path / "d.stamp.json"
    path.write_text(json.dumps({"spec": "old"}))
    assert runner.stale(path, {"spec": "new"}) == ["spec"]
    with rules.overlaid(coarse_stamp_keys=[]):
        assert runner.stale(path, {"spec": "new"}) == []


def test_the_window_the_server_is_started_with_follows_the_rules():
    from docpipe import prompts
    from docpipe.profile import load_profile
    prompt = prompts.load("extraction/find", load_profile("kwp"))
    standard = runner.context_budget(prompt)
    with rules.overlaid(window_line_tokens=600):
        assert runner.context_budget(prompt) > standard
    with rules.overlaid(window_line_tokens=1):
        assert runner.context_budget(prompt) < standard
    # a request shows `search_per_request` pieces of `piece_lines` lines
    # and `headings` headings: the largest of each in the flow counts
    assert runner.most_of_number("search_per_request") == 5
    assert runner.most_of_number("piece_lines") == 8
    with rules.overlaid(batch_chars=140000, batch_sources=60):
        assert runner.context_budget(prompt) == standard   # the old batch
    with rules.overlaid(attach_images=False):
        assert runner.context_budget(prompt) < standard
    # the longest answer is the one the steps of the flow set for the kind
    assert runner.answer_tokens_of(prompt) == 2048


def test_a_pool_is_one_model_with_one_place_unless_the_rules_say_more(
        monkeypatch):
    from docpipe.inference import pool
    assert pool.models() == ("Qwen/Qwen3.5-122B-A10B-FP8",)
    assert not pool.wide()
    with rules.overlaid(llm_models="a, b", llm_slots_per_model=2):
        assert pool.models() == ("a", "b") and pool.wide()


def test_no_prompt_of_the_reading_carries_temperature_or_max_tokens():
    import glob
    import re
    root = rules.DEFAULT.parent.parent.parent.parent
    files = (glob.glob(str(root / "docpipe/builtin/*/prompts/extraction/*.md"))
             + glob.glob(str(root / "profiles/*/prompts/extraction/*.md")))
    assert files
    front = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
    for path in files:
        with open(path, encoding="utf-8") as handle:
            found = front.match(handle.read())
        assert not found or not re.search(
            r"^(temperature|max_tokens)\s*:", found.group(1), re.M), path


def test_every_asking_step_of_the_shipped_flow_carries_its_longest_answer():
    from docpipe.extraction import blocks, flow
    asking = {"transcribe": 4096, "docfield": 2048, "find": 2048,
              "coord": 1024, "search": 1536, "check": 256, "names": 512,
              "work": 1024, "phrase": 300, "compute": 2048}
    from docpipe.profile import load_profile
    seen = set()
    # the shipped flows: the default's and those kwp and scenarios draw
    # with the steps of their own (owner decision 2026-11-12)
    for profile in (None, load_profile("kwp"), load_profile("scenarios")):
        for node in flow.boxes(flow.tree_of(profile)):
            block = blocks.LIBRARY.get(node["box"])
            if block is not None and block.asks in asking:
                assert node["rules"]["max_tokens"] == asking[block.asks], \
                    node
                assert node["rules"]["temperature"] == 0
                seen.add(block.asks)
        assert flow.problems(flow.tree_of(profile), profile=profile) == []
    assert seen == set(asking)


# -- the rest of the rows -----------------------------------------------------

def test_an_error_that_is_neither_the_server_s_nor_a_refusal_is_asked_as_set(
        monkeypatch):
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    other = ValueError("our own fault")
    other.status_code = 302  # an answer, but neither refusal nor failure
    assert runner.Failures(7).failed(other) is False
    with at("find", other_errors_retry=2):
        failures = runner.Failures(7)
        assert [failures.failed(other) for _ in range(3)] \
            == [True, True, False]


def test_a_search_may_read_every_chunk_by_the_rule():
    assert runner.search_budget()[0] == runner.numbers().search_pieces
    from test_addressed import Model, in_order, SPEC
    from docpipe.extraction.addressed import Reader
    reader = Reader(SPEC, Model().asks(), in_order)
    assert reader.budget == runner.numbers().search_pieces
    with at("order", search_to_end=True):
        assert reader.budget == runner.REST_TO_END
    assert reader.budget == runner.numbers().search_pieces


def test_the_reranker_of_the_chunks_scores_as_many_as_the_rule_says():
    from docpipe.inference import rerank
    with rules.overlaid(rerank_base_url="http://x"):
        scored = runner.make_chunk_reranker()().reranker
        assert rerank.pool_size("section", scored.pool_rule) == 1000000
        with at("order", rerank_chunk_pool=7):
            assert rerank.pool_size("section", scored.pool_rule) == 7
    assert runner.make_chunk_reranker() is None     # no server, no reranker


def test_the_documents_are_let_in_as_the_rule_says():
    limit = SimpleNamespace(in_flight=1, limit=5)
    assert runner.document_room(limit)(0) == 1
    with rules.overlaid(document_admission="ceiling_only"):
        assert runner.document_room(limit) is None


def test_a_probe_keeps_open_the_requests_the_rule_says(monkeypatch):
    monkeypatch.setattr(runner, "LIMIT", None)
    monkeypatch.setattr(runner, "SCHEDULER", None)
    monkeypatch.setattr(runner.scheduler, "Scheduler",
                        lambda limit: SimpleNamespace(limit=limit))
    runner.start_fixed_limit(5)
    assert runner.LIMIT.limit == 5
    with rules.overlaid(fixed_limit_requests=9):
        runner.start_fixed_limit(5)
    assert runner.LIMIT.limit == 9


def test_the_connections_to_the_server_are_the_rule_s(monkeypatch):
    monkeypatch.setattr(runner, "_SHARED_HTTP", None)
    with rules.overlaid(http_connections=7):
        client = runner.shared_http(SimpleNamespace(maximum=18))
    try:
        assert client._transport._pool._max_connections == 7
    finally:
        client.close()
    monkeypatch.setattr(runner, "_SHARED_HTTP", None)
    client = runner.shared_http(SimpleNamespace(maximum=18))
    try:
        assert client._transport._pool._max_connections == 18
    finally:
        client.close()


def test_the_health_probe_waits_as_long_as_the_rule_says(monkeypatch):
    import urllib.request
    waited = []
    class Open:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout:
                        waited.append(timeout) or Open())
    assert runner.probe_server("http://x/v1")
    with rules.overlaid(server_probe_timeout_s=3):
        runner.probe_server("http://x/v1")
    assert waited == [10, 3]


def test_the_search_sentences_of_a_document_are_written_as_many_at_once_as_set(
        monkeypatch):
    from pathlib import Path
    from docpipe.prompts import Prompt
    client = Counted(0.05)
    client.chat.completions.create = lambda **kw: (
        Counted.create(client, **kw) and SimpleNamespace(
            usage=None, choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(
                    content='{"phrase": "Ein Satz."}',
                    reasoning_content=None))]))
    spec = SimpleNamespace(parameters=[
        SimpleNamespace(uri=uri, label=uri, description=f"Was {uri} ist",
                        vocabulary={}) for uri in "abcd"])
    prompt = Prompt("phrase", "x", {}, "", Path("phrase.md"))
    out = runner.document_anchor(spec, client=client, prompt=prompt)
    assert set(out) == set("abcd") and client.most >= 3
    client.most = 0
    with at("phrase", phrase_parallel=1):
        # the pool is sized by the rule of the step that asks
        out = runner.document_anchor(spec, client=client, prompt=prompt)
    assert client.most == 1


def test_the_location_of_quotes_is_looked_for_as_the_rule_says():
    from pathlib import Path
    with rules.overlaid(locate_quotes=False):
        assert runner.make_locate(Path("x.db"), Path("pdfs")) is None
    assert runner.make_locate(Path("x.db"), None) is None


def test_the_content_of_a_run_is_kept_as_many_owners_as_the_rule_says(
        monkeypatch):
    from docpipe.inference import db
    read = []
    monkeypatch.setattr(db, "fetch_owner_content",
                        lambda conn, kind, owner: read.append(owner) or
                        {"text": str(owner)})
    with rules.overlaid(content_cache_owners=1):
        fetch = runner.make_shared_content()
    for owner in (1, 2, 1, 1):
        fetch(None, "section", owner)
    assert read == [1, 2, 1]                       # one kept, the oldest left
    read.clear()
    fetch = runner.make_shared_content()
    for owner in (1, 2, 1, 2):
        fetch(None, "section", owner)
    assert read == [1, 2]


def test_the_provider_of_the_text_model_is_the_rule_s(monkeypatch):
    assert providers.provider("llm") == "openai-compatible"
    with rules.overlaid(llm_provider="anthropic"):
        assert providers.provider("llm") == "anthropic"
        assert providers.hosted("llm")
    monkeypatch.setenv("VLM_PROVIDER", "gemini")
    assert providers.provider("vlm") == "gemini"      # another role's setting


def test_the_address_and_the_key_belong_to_the_machine():
    assert runner.llm_base_url() == "http://localhost:8000/v1"
    assert runner.llm_api_key() == "EMPTY"
    with rules.overlaid(llm_base_url="http://gpu:8000/v1",
                        llm_api_key="secret"):
        assert runner.llm_base_url() == "http://gpu:8000/v1"
        assert runner.llm_api_key() == "secret"
    for name in ("llm_base_url", "llm_api_key", "llm_models",
                 "llm_slots_per_model", "http_connections"):
        assert rules.BY_NAME[name].machine, name
    assert rules.BY_NAME["llm_api_key"].secret
    assert rules.default()["llm_api_key"] == ""      # never in a file


def test_a_setting_of_the_start_is_the_standard_of_its_rule(monkeypatch):
    from docpipe import settings
    monkeypatch.setenv("EXTRACT_LIMIT_START", "64")
    monkeypatch.setenv("EXTRACT_LIMIT_ADAPTIVE", "0")
    monkeypatch.setenv("EXTRACT_ATTACH_IMAGES", "0")
    rules.reset()
    assert throttle.AdaptiveLimit().limit == 64
    assert rules.get("limit_adaptive") is False
    assert runner.attach_images() is False
    # every setting of the start that sets one of these rules says which
    for setting in settings.SETTINGS:
        one = next((r for r in rules.RULES if r.env == setting.env), None)
        if one is not None and setting.env.startswith("EXTRACT_"):
            assert setting.rule == one.name, setting.env
    assert not [s for s in settings.SETTINGS
                if s.env in ("EXTRACT_LLM_PARALLEL", "EXTRACT_PLAN_PARALLEL")]


def test_a_benchmark_run_reads_one_at_a_time():
    """Both runs of a benchmark read with the limit off, one document in
    flight and one calculation at a time, whatever the rules file says."""
    from docpipe.extraction import benchmark
    held = rules.load(None, environ=benchmark.ONE_AT_A_TIME)
    assert held["limit_adaptive"] is False
    assert held["documents_in_flight"] == 1
    assert held["compute_parallel"] == 1
    # every name it sets is read by a rule, the seed of the sets aside
    envs = {one.env for one in rules.RULES if one.env}
    assert set(benchmark.ONE_AT_A_TIME) - envs == {"PYTHONHASHSEED"}
    # broken by construction: a name no rule reads holds nothing
    dead = rules.load(None, environ={"EXTRACT_LLM_PARALLEL": "1"})
    assert dead["limit_adaptive"] is True
    assert dead["documents_in_flight"] > 1
