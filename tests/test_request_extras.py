"""Every request says tool_choice none unless the installation turns it off
(owner decision 2026-11-08): an agent endpoint handed figures to its own
"subagent" tool and the requests ran into the timeout."""
from docpipe import llm_preflight


def test_every_request_says_tool_choice_none(monkeypatch):
    monkeypatch.delenv("LLM_TOOL_CHOICE", raising=False)
    assert llm_preflight.request_extras()["tool_choice"] == "none"


def test_off_sends_no_tool_choice(monkeypatch):
    for value in ("off", "", " OFF "):
        monkeypatch.setenv("LLM_TOOL_CHOICE", value)
        assert "tool_choice" not in llm_preflight.request_extras()


def test_the_reasoning_fields_stay_beside_it(monkeypatch):
    monkeypatch.delenv("LLM_TOOL_CHOICE", raising=False)
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("LLM_ENABLE_THINKING", "0")
    extras = llm_preflight.request_extras()
    assert extras["reasoning_effort"] == "low"
    assert extras["chat_template_kwargs"] == {"enable_thinking": False}
