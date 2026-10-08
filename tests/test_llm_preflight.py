"""llm_preflight's own contract: what the rest of the pipeline gets back
from asking the server what it can do.

The promise of the request-field probe, one assertion to a test:

  * a server that reports no context size is asked the request fields all
    the same, and a refusal there raises, as it does for any other server;
  * the window is still checked first, and a too small one is refused before
    a request is sent;
  * a probe that could not be answered is told apart from one that was
    accepted, and a rate limit is not a refusal;
  * the doctor's probe sends what `assert_serving` sends for the same kind
    of server.
"""
from types import SimpleNamespace as NS

import pytest

from docpipe import llm_preflight
from docpipe.llm_preflight import (PreflightError, assert_request_accepted,
                                   assert_request_extras, assert_serving)
from docpipe.providers import base


def test_assert_serving_returns_the_reported_max_model_len(monkeypatch):
    """The window is read once, at the start of a run, and handed to
    `set_model_len` so every request afterwards is sized against the server
    the job actually got -- not a copy of the number typed into --max-model-len."""
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda base_url, api_key, **kw: (["m"], 40960))
    monkeypatch.setattr(llm_preflight, "assert_request_extras",
                        lambda *a, **kw: None)
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) == 40960


def test_assert_serving_returns_none_when_the_server_reports_no_window(
        monkeypatch):
    """A server that does not report its context size cannot be checked, and
    the caller (`set_model_len`) must be told so rather than handed a made-up
    number."""
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda base_url, api_key, **kw: (["m"], None))
    monkeypatch.setattr(llm_preflight, "assert_request_extras",
                        lambda *a, **kw: None)
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) is None


# ---------------------------------------------------------------------------
# A server that does not report its context size
# ---------------------------------------------------------------------------

class _Status(Exception):
    def __init__(self, status_code, message="refused"):
        super().__init__(message)
        self.status_code = status_code


def _server(monkeypatch, create, window=None, role_provider=None):
    """A server that serves "m" with the given window (None: it reports
    none), answering the chat request with *create*."""
    sent = []

    def answer(**kwargs):
        sent.append(kwargs)
        return create(**kwargs)

    card = NS(id="m", max_model_len=window)
    client = base.facade(answer, models=lambda: NS(data=[card]))
    monkeypatch.setattr(llm_preflight.providers, "client",
                        lambda role, **kw: client)
    if role_provider:
        monkeypatch.setenv("LLM_PROVIDER", role_provider)
    else:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return sent


def _accepts(**kwargs):
    return base.reply("ok", "length")


def test_a_server_that_reports_no_window_is_asked_the_request_fields(
        monkeypatch):
    """The early return skipped exactly this probe, for exactly the servers
    (a gateway, a local runner) most likely to refuse the fields."""
    sent = _server(monkeypatch, _accepts)
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) is None
    assert len(sent) == 1
    assert sent[0]["max_tokens"] == 1
    assert sent[0]["extra_body"] == llm_preflight.request_extras()


def test_a_server_that_reports_no_window_and_refuses_the_fields_is_refused(
        monkeypatch):
    """The refusal is built in: a 400 on the probe, from a server whose card
    carries no window. Before, assert_serving returned None here."""
    sent = _server(monkeypatch, lambda **kw: (_ for _ in ()).throw(
        _Status(400, "unknown field reasoning_effort")))
    with pytest.raises(PreflightError) as refused:
        assert_serving("http://x/v1", "EMPTY", "m", 1000, what="extraction")
    assert "LLM_REASONING_EFFORT=off" in str(refused.value)
    assert "unknown field reasoning_effort" in str(refused.value)
    assert len(sent) == 1


def test_a_server_that_reports_no_window_but_cannot_be_asked_is_not_refused(
        monkeypatch):
    """No verdict is no refusal: the run's own retries deal with an outage.
    But the request was sent: a probe that is never tried says nothing."""
    def down(**kwargs):
        raise _Status(503, "overloaded")

    sent = _server(monkeypatch, down)
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) is None
    assert len(sent) == 1


def test_the_window_is_checked_before_any_request_is_sent(monkeypatch):
    sent = _server(monkeypatch, _accepts, window=2048)
    with pytest.raises(PreflightError) as refused:
        assert_serving("http://x/v1", "EMPTY", "m", 4096)
    assert "2048" in str(refused.value) and "4096" in str(refused.value)
    assert sent == []


def test_a_window_of_exactly_the_budget_is_enough_and_one_token_less_is_not(
        monkeypatch):
    sent = _server(monkeypatch, _accepts, window=4096)
    assert assert_serving("http://x/v1", "EMPTY", "m", 4096) == 4096
    assert len(sent) == 1
    with pytest.raises(PreflightError):
        assert_serving("http://x/v1", "EMPTY", "m", 4097)
    assert len(sent) == 1               # the refusal sent nothing


def test_a_server_that_reports_a_window_is_asked_the_fields_as_before(
        monkeypatch):
    sent = _server(monkeypatch, _accepts, window=8192)
    assert assert_serving("http://x/v1", "EMPTY", "m", 4096) == 8192
    assert len(sent) == 1


def test_the_recorded_run_of_a_server_with_no_window_names_it(
        monkeypatch, tmp_path):
    """The header a replay plans its requests from says the server offered
    nothing, instead of saying nothing."""
    import json

    from docpipe.providers import cassette
    path = tmp_path / "cassette.jsonl"
    monkeypatch.setenv(cassette.RECORD_ENV, str(path))
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda base_url, api_key, **kw: (["m"], None))
    monkeypatch.setattr(llm_preflight, "assert_request_extras",
                        lambda *a, **kw: None)
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) is None
    header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert (header["kind"], header["model"], header["max_model_len"]) == (
        cassette.HEADER, "m", None)


# ---------------------------------------------------------------------------
# What the probe says it found
# ---------------------------------------------------------------------------

def test_an_accepted_probe_returns_nothing_and_an_unanswered_one_says_why(
        monkeypatch):
    _server(monkeypatch, _accepts)
    assert assert_request_extras("http://x/v1", "EMPTY", "m") is None

    def down(**kwargs):
        raise OSError("connection refused")

    _server(monkeypatch, down)
    why = assert_request_extras("http://x/v1", "EMPTY", "m")
    assert isinstance(why, str) and "connection refused" in why


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_busy_or_broken_server_gives_no_verdict_on_the_fields(
        monkeypatch, status):
    """429 says not now. Counted as a refusal it would tell a gateway under
    load that it does not take reasoning_effort."""
    def busy(**kwargs):
        raise _Status(status)

    _server(monkeypatch, busy)
    assert assert_request_extras("http://x/v1", "EMPTY", "m")


@pytest.mark.parametrize("status", [400, 404, 422])
def test_a_client_error_on_the_probe_is_a_refusal(monkeypatch, status):
    def refused(**kwargs):
        raise _Status(status)

    _server(monkeypatch, refused)
    with pytest.raises(PreflightError):
        assert_request_extras("http://x/v1", "EMPTY", "m")


# ---------------------------------------------------------------------------
# The probe the doctor sends is the one assertion sends
# ---------------------------------------------------------------------------

def test_the_probe_of_a_server_of_ones_own_is_the_reasoning_settings(
        monkeypatch):
    sent = _server(monkeypatch, _accepts)
    assert assert_request_accepted("http://x/v1", "EMPTY", "m") is None
    assert "response_format" not in sent[0]
    assert sent[0]["extra_body"] == llm_preflight.request_extras()


def test_the_probe_of_a_hosted_api_is_a_reply_schema(monkeypatch):
    sent = _server(monkeypatch,
                   lambda **kw: base.reply('{"ok": true}', "stop"),
                   role_provider="gemini")
    assert assert_request_accepted("http://x/v1", "EMPTY", "m") is None
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert sent[0]["extra_body"] == llm_preflight.request_extras()


def test_a_hosted_model_that_answers_outside_the_schema_is_refused_by_the_probe(
        monkeypatch):
    _server(monkeypatch, lambda **kw: base.reply("Sure, here you go", "stop"),
            role_provider="gemini")
    with pytest.raises(PreflightError):
        assert_request_accepted("http://x/v1", "EMPTY", "m")


def test_a_hosted_api_that_cannot_be_asked_gives_no_verdict(monkeypatch):
    def down(**kwargs):
        raise _Status(503)

    _server(monkeypatch, down, role_provider="gemini")
    assert assert_request_accepted("http://x/v1", "EMPTY", "m")


# ---------------------------------------------------------------------------
# The reply schemas a stage sends as its grammar
# ---------------------------------------------------------------------------

SHAPES = {"table_reply": {"type": "object", "properties": {
              "markdown": {"type": "string"}}, "required": ["markdown"]},
          "figure_reply": {"type": "object", "properties": {
              "description": {"type": "string"}}, "required": ["description"]},
          "page_reply": {"type": "object", "properties": {
              "markdown": {"type": "string"}}, "required": ["markdown"]}}


def _refuses(*names, status=400):
    """A server that answers 400 to the schemas of these names only."""
    def create(**kwargs):
        shape = (kwargs.get("response_format") or {}).get("json_schema") or {}
        if shape.get("name") in names:
            raise _Status(status, f"cannot compile {shape['name']}")
        return _accepts()

    return create


def test_an_own_server_that_refuses_a_schema_is_refused_at_once(monkeypatch):
    """The promise: the server is asked every schema the stage will send, and
    one it refuses ends the run before the first document, naming it."""
    sent = _server(monkeypatch, _refuses("page_reply"))
    with pytest.raises(PreflightError) as refused:
        assert_serving("http://x/v1", "EMPTY", "m", 1000, what="page "
                       "transcription", shapes=SHAPES)
    text = str(refused.value)
    assert "page_reply" in text and "HTTP 400" in text
    assert "JSON schema" in text and "response_format" in text
    assert "page transcription" in text
    # the three shapes were asked, and the refused one is the third
    asked = [r["response_format"]["json_schema"]["name"] for r in sent
             if r.get("response_format")]
    assert asked == ["table_reply", "figure_reply", "page_reply"]


def test_a_server_that_takes_every_schema_passes_with_the_stages_own_shapes(
        monkeypatch):
    sent = _server(monkeypatch, _accepts, window=8192)
    assert assert_serving("http://x/v1", "EMPTY", "m", 4096,
                          shapes=SHAPES) == 8192
    probes = [r for r in sent if r.get("response_format")]
    assert [r["response_format"] for r in probes] == [
        {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}
        for name, schema in SHAPES.items()]
    # as small as the reasoning probe: capped, cold, with the same fields
    assert {(r["max_tokens"], r["temperature"]) for r in probes} == {(32, 0)}
    assert all(r["extra_body"] == llm_preflight.request_extras()
               for r in probes)


def test_a_stage_without_shapes_asks_nothing_more(monkeypatch):
    sent = _server(monkeypatch, _accepts, window=8192)
    assert_serving("http://x/v1", "EMPTY", "m", 4096)
    assert not [r for r in sent if r.get("response_format")]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_server_that_cannot_be_asked_the_schemas_gives_no_verdict(
        monkeypatch, status):
    """Only a 4xx that is not a 429 is a refusal: busy or down is no answer
    about the schema, and the run's own retries deal with an outage."""
    sent = _server(monkeypatch, _refuses(*SHAPES, status=status))
    why = llm_preflight.assert_reply_schemas(
        "http://x/v1", "EMPTY", "m", SHAPES, what="refinement")
    assert isinstance(why, str) and "table_reply" in why
    assert len(sent) == len(SHAPES), "every shape was tried"


def test_an_unreachable_server_only_warns(monkeypatch, caplog):
    def down(**kwargs):
        raise OSError("connection refused")

    _server(monkeypatch, down)
    with caplog.at_level("WARNING"):
        why = llm_preflight.assert_reply_schemas(
            "http://x/v1", "EMPTY", "m", {"page_reply": SHAPES["page_reply"]},
            what="page transcription")
    assert "connection refused" in why
    assert "asking anyway" in caplog.text


def test_a_hosted_api_is_asked_the_stages_shapes_too(monkeypatch):
    sent = _server(monkeypatch,
                   lambda **kw: base.reply('{"ok": true}', "stop"),
                   role_provider="gemini")
    assert llm_preflight.assert_reply_schemas(
        "http://x/v1", "EMPTY", "m", SHAPES, what="image enrichment",
        role="llm") is None
    assert [r["response_format"]["json_schema"]["name"] for r in sent] == \
        list(SHAPES)
