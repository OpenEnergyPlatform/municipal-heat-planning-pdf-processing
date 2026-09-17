"""llm_preflight's own contract: what the rest of the pipeline gets back
from asking the server what it can do."""
from docpipe import llm_preflight
from docpipe.llm_preflight import assert_serving


def test_assert_serving_returns_the_reported_max_model_len(monkeypatch):
    """The window is read once, at the start of a run, and handed to
    `set_model_len` so every request afterwards is sized against the server
    the job actually got -- not a copy of the number typed into --max-model-len."""
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda base_url, api_key: (["m"], 40960))
    monkeypatch.setattr(llm_preflight, "assert_request_extras",
                        lambda *a, **kw: None)
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) == 40960


def test_assert_serving_returns_none_when_the_server_reports_no_window(
        monkeypatch):
    """A server that does not report its context size cannot be checked, and
    the caller (`set_model_len`) must be told so rather than handed a made-up
    number."""
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda base_url, api_key: (["m"], None))
    assert assert_serving("http://x/v1", "EMPTY", "m", 1000) is None
