"""
The runner reads what is the flow's, and the second ways of reading a reply
are off unless a rule chooses them.

The promises, each with a case that breaks it by construction:

1. A reply is read as it is: a fenced or wrapped one is asked again, AND with
   `repair_replies` naming the repair it is read and noted in the request
   log with the rule, AND a reply cut off at its limit is never closed.
2. A reply cut off in a list is a hole, AND with `cut_off` = rescue the
   complete entries of the list stay and the request is noted as cut off;
   a reply cut off outside a list has nothing to keep.
3. What a call switch says for the run alone is a rule for as long as the
   run goes, AND gone after it.
4. A current harvest is skipped, AND with `skip_current` off it is read
   again; the documents are the rule's.
5. The tokens and the temperature of a request that no run asks are those of
   the box that asks its kind.
6. The Gemini API reads its batch, time and key from the rules.
7. A setting that wins over a rule has no default of its own.
8. A place of the prompt the request shows no reply for is empty text.
"""
import json
from types import SimpleNamespace

import pytest

from docpipe import rules, settings
from docpipe.extraction import mend, runner
from docpipe.providers import gemini_api

SHAPE = {"type": "json_schema", "json_schema": {
    "name": "x", "schema": {"type": "object", "required": ["found"],
                            "properties": {"found": {"type": "array"}}}}}
PROMPT = SimpleNamespace(meta={}, text="x", placeholders=frozenset(),
                         id="p")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for env in rules.ENVS:
        monkeypatch.delenv(env, raising=False)
    rules.reset()
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    yield
    rules.reset()


@pytest.fixture
def traced(monkeypatch):
    events = []
    monkeypatch.setattr(runner.trace, "event",
                        lambda kind, doc=None, /, **fields: events.append(
                            (kind, fields)))
    return events


def replying(*said, finish="stop"):
    told = iter(said)
    sent = []

    def create(**request):
        sent.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason=finish, message=SimpleNamespace(
                content=next(told), reasoning_content=None))])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), sent


def ask(client):
    return runner.ask_in_grammar(client, PROMPT, [], SHAPE, 7, "find",
                                 "found")


# -- 1: repairs ---------------------------------------------------------------

FENCED = '```json\n{"found": []}\n```'


def test_a_fenced_reply_is_asked_again_unless_a_rule_repairs_it(traced):
    client, sent = replying(FENCED, '{"found": []}')
    assert ask(client) == {"found": []}
    assert len(sent) == 2                    # the standard asks again
    assert not [e for e in traced if e[0] == "repaired"]
    with rules.overlaid(repair_replies=["fences"]):
        client, sent = replying(FENCED)
        assert ask(client) == {"found": []}
        assert len(sent) == 1
    noted = [fields for kind, fields in traced if kind == "repaired"]
    assert noted == [{"where": "find", "repairs": ["fences"],
                      "rule": "repair_replies"}]


def test_only_the_repairs_the_rule_names_are_made():
    reply = '<think>x</think>```json\n{"found": []}\n```'
    assert mend.repaired(reply, [], True) == (None, [])
    assert mend.repaired(reply, ["fences"], True)[0] is None
    assert mend.repaired(reply, ["think", "fences"], True) == (
        {"found": []}, ["think", "fences"])
    assert mend.repaired('x {"a": 1} y', ["cut_out"], True) == (
        {"a": 1}, ["cut_out"])
    assert mend.repaired('{"a": [1', ["close"], True) == (
        {"a": [1]}, ["close"])
    assert mend.repaired('{"a": [1', ["close"], False) == (None, [])
    assert mend.repaired('{"a": "x', ["close"], True) == (None, [])


def test_a_reply_cut_off_at_its_limit_is_never_closed(traced):
    client, sent = replying('{"found": [1', finish="length")
    with rules.overlaid(repair_replies=["close"]):
        assert ask(client) == "cut_off"
    assert not [e for e in traced if e[0] == "repaired"]
    client, sent = replying('{"found": [1', '{"found": []}')
    with rules.overlaid(repair_replies=["close"]):
        assert ask(client) == {"found": [1]}        # stopped, not cut off


# -- 2: the rescue of a cut-off reply -----------------------------------------

CUT = '{"found": [{"at": "1"}, {"at": "2"}, {"at": "3'


def test_a_reply_cut_off_in_a_list_is_a_hole_unless_the_rule_rescues(traced):
    client, _sent = replying(CUT, finish="length")
    assert ask(client) == "cut_off"
    with rules.overlaid(cut_off="rescue"):
        client, _sent = replying(CUT, finish="length")
        assert ask(client) == {"found": [{"at": "1"}, {"at": "2"}]}
        client, _sent = replying('{"found": [{"at": "1', finish="length")
        assert ask(client) == "cut_off"                # nothing complete
        client, _sent = replying('{"other": [{"at": "1"}, 2', finish="length")
        assert ask(client) == "cut_off"                # not the list asked
    noted = [fields for kind, fields in traced
             if fields.get("kind") == "cut_off_rescued"]
    assert [(n["rule"], n["kept"]) for n in noted] == [("cut_off", 2)]


def test_the_entries_of_a_list_stop_at_the_first_that_is_cut():
    assert mend.rescued(CUT, "found") == {"found": [{"at": "1"},
                                                    {"at": "2"}]}
    assert mend.rescued('{"found": []}', "found") is None
    assert mend.rescued('{"x": 1', "found") is None


# -- 3 and 4: the run's own rules ---------------------------------------------

def test_a_call_switch_is_a_rule_for_the_run_alone(monkeypatch):
    seen = {}

    def inside(argv, stack):
        stack.enter_context(rules.overlaid(documents=["5"]))
        seen["during"] = rules.get("documents")
        return 0
    monkeypatch.setattr(runner, "_main", inside)
    assert runner.main([]) == 0
    assert seen["during"] == ["5"]
    assert rules.get("documents") == []


def test_the_documents_are_the_rule_s_when_none_are_named():
    listing = [(1, "a.pdf"), (2, "b.pdf"), (3, "c.pdf")]
    assert runner.select_documents(listing, None) == (listing, [])
    with rules.overlaid(documents=["2", "9"]):
        assert runner.select_documents(listing, None) == (
            [(2, "b.pdf")], [9])


def test_a_current_harvest_is_read_again_where_the_rule_says(tmp_path):
    (tmp_path / "d.jsonl").write_text("{}")
    (tmp_path / "d.stamp.json").write_text(json.dumps({}))
    standard = runner.already_done("d", tmp_path, "sha")
    with rules.overlaid(skip_current=False):
        assert runner.already_done("d", tmp_path, "sha") is False
    assert runner.already_done("d", tmp_path, "sha") == standard


# -- 5: what is asked where no run asks ---------------------------------------

def test_the_values_of_a_request_no_run_asks_are_those_of_its_box():
    assert runner.asked_values("phrase")["max_tokens"] == 300
    assert runner.asked_values("docfield")["max_tokens"] == 2048
    standard = runner.asked_values(None)
    assert standard == {"max_tokens": rules.get("max_tokens"),
                        "temperature": rules.get("temperature")}
    with rules.overlaid(max_tokens=77, temperature=0.5):
        assert runner.asked_values(None) == {"max_tokens": 77,
                                             "temperature": 0.5}
        assert runner.asked_values("phrase")["max_tokens"] == 300


def test_no_bridge_of_the_old_names_stands_in_the_modules():
    from docpipe.extraction import throttle
    from docpipe.providers import governor
    assert not hasattr(runner, "LLM_MODEL")
    assert not hasattr(throttle, "MAXIMUM")
    assert not hasattr(governor, "LIMITED")
    assert governor.limited_statuses() == (429, 503, 529)


# -- 6: the Gemini API --------------------------------------------------------

def test_the_gemini_api_reads_its_batch_and_its_key_from_the_rules():
    from docpipe.providers import base
    seen = []

    class Got:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        seen.append((json.loads(request.data), timeout,
                     request.headers["X-goog-api-key"]))
        count = len(json.loads(request.data)["requests"])
        return Got(json.dumps({"embeddings": [{"values": [1]}] * count}
                              ).encode())
    chat = gemini_api.GeminiChat(base.Endpoint(
        "llm", "gemini"), opener=opener)
    with rules.overlaid(gemini_embed_batch=2, gemini_timeout_s=7,
                        google_api_key="g"):
        chat.embeddings(model="m", input=["a", "b", "c"])
    assert [len(body["requests"]) for body, _t, _k in seen] == [2, 1]
    assert {t for _b, t, _k in seen} == {7}
    assert {k for _b, _t, k in seen} == {"g"}
    with rules.overlaid(gemini_api_key="first", google_api_key="g"):
        chat.embeddings(model="m", input=["a"])
    assert seen[-1][2] == "first"
    with pytest.raises(base.ProviderError):
        chat.embeddings(model="m", input=["a"])        # no key at all


# -- 7: the settings ----------------------------------------------------------

@pytest.mark.parametrize("env, rule", [
    ("RERANK_BASE_URL", "rerank_base_url"),
    ("RERANK_API_KEY", "rerank_api_key"), ("RERANK_MODEL", "rerank_model"),
    ("RERANK_POOL", "rerank_pool"), ("CODE_EXEC_TIMEOUT", "code_timeout_s")])
def test_a_setting_that_wins_over_a_rule_has_no_default_of_its_own(env, rule):
    setting = settings.BY_ENV[env]
    assert setting.rule == rule and setting.default is None
    assert rules.BY_NAME[rule].env == env


# -- 8: the places of a prompt ------------------------------------------------

def test_a_place_the_request_shows_no_reply_for_is_empty_text():
    class Prompt:
        id = "p"
        placeholders = frozenset({"example", "nothing"})

        def render(self, **values):
            return json.dumps(values, sort_keys=True)
    one = runner.system_text(Prompt(), ({"a": 1},))
    assert json.loads(one) == {"example": '{"a":1}', "nothing": ""}
    assert json.loads(runner.system_text(Prompt(), ())) == {
        "example": "", "nothing": ""}
    with pytest.raises(KeyError):
        runner.system_text(Prompt(), None)          # no example at all


def test_the_check_against_the_schema_is_made_where_the_rule_says(
        monkeypatch):
    def validators(spec):
        raise AssertionError("the schema was read")
    monkeypatch.setattr(runner, "_harvest_validators", validators)
    with rules.overlaid(write_checks_schema=False):
        assert runner.check_against_schema(None, "d", None) == 0
    with pytest.raises(AssertionError):
        runner.check_against_schema(None, "d", None)
