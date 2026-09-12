"""The context budget, and the split bound it rests on.

These are the first tests in the suite that talk about a number rather than a
corpus. They exist because a serving flag was guessed from a prose comment
("the largest window of this corpus has ~8k input tokens"), the guess was
wrong, and 42 windows kept their raw text without anyone being told.
"""
from unittest.mock import MagicMock, patch

import pytest

from docpipe.llm_preflight import PreflightError, assert_serving
from docpipe.refinement import config as refine_config
from docpipe.refinement.split import split_oversized


def _section(words: int, n_segments: int = 8, title: str = "S") -> dict:
    """A section whose content is exactly rebuildable from its segments —
    split.py refuses to cut anything else."""
    per = max(1, words // n_segments)
    segments = [{"page": 1, "kind": "text", "text": " ".join(["w"] * per)}
                for _ in range(n_segments)]
    return {"title": title, "page_number": 1, "pages": [1],
            "content": " ".join(s["text"] for s in segments),
            "segments": segments, "tables": [], "figures": []}


# ---------------------------------------------------------------------------
# The bound the budget rests on
# ---------------------------------------------------------------------------

def test_split_holds_its_own_limit():
    """The model may return parts over the limit; the output must not."""
    limit = refine_config.SECTION_MAX_WORDS          # 1000, the real bound
    # An LLM splitter that cuts once, far too late — exactly the failure seen
    # in the ar6 run, where an 11596-word section came back with a 2392 part.
    lazy = MagicMock(return_value='{"cuts": [{"at": 10}], "first_title": null}')
    out = split_oversized([_section(3000, n_segments=30)], ask=lazy,
                          max_words=limit)
    assert len(out) > 2, "one lazy cut must not be the final answer"
    oversized = [s for s in out if len(s["content"].split()) > limit]
    assert not oversized, f"{len(oversized)} part(s) still over {limit} words"


def test_split_gives_up_loudly_when_provenance_no_longer_lines_up(caplog):
    """The only remaining case that cannot be cut: the segments no longer
    rebuild the content, so any cut position would attach text to the wrong
    page. Leaving it whole is right — saying nothing is not."""
    section = _section(1500, n_segments=4)
    section["content"] = "something else entirely " * 400   # provenance broken
    out = split_oversized([section], ask=None,
                          max_words=refine_config.SECTION_MAX_WORDS)
    assert len(out) == 1
    assert "no longer rebuild" in caplog.text, "the unbounded case must warn"


# ---------------------------------------------------------------------------
# The budget itself
# ---------------------------------------------------------------------------

def test_budget_covers_a_full_window_plus_the_reply():
    budget = refine_config.max_request_tokens()
    window_words = refine_config.WINDOW_SIZE * refine_config.SECTION_MAX_WORDS
    assert budget > window_words + refine_config.LLM_MAX_TOKENS
    assert budget >= refine_config.LLM_MAX_TOKENS


def test_budget_reacts_to_the_knobs_it_names():
    """If a knob moves and the number does not, the number is decoration.

    The reply side is the ceiling, not the flat default: max_tokens is chosen
    per request now, so what the server must be able to hold is the largest
    reply we would ever ask for.
    """
    base = refine_config.max_request_tokens()
    with patch.object(refine_config, "WINDOW_SIZE", refine_config.WINDOW_SIZE + 1):
        assert refine_config.max_request_tokens() > base
    with patch.object(refine_config, "REPLY_TOKENS_CEILING",
                      refine_config.REPLY_TOKENS_CEILING + 1000):
        assert refine_config.max_request_tokens() == base + 1000


# ---------------------------------------------------------------------------
# The preflight
# ---------------------------------------------------------------------------

def _server(model_id="m", max_len=32768):
    card = MagicMock()
    card.id = model_id
    card.max_model_len = max_len
    client = MagicMock()
    client.models.list.return_value = MagicMock(data=[card])
    return client


def test_preflight_rejects_a_server_with_too_little_context():
    with patch("openai.OpenAI", return_value=_server(max_len=20480)):
        with pytest.raises(PreflightError) as e:
            assert_serving("http://x/v1", "EMPTY", "m", 25000)
    assert "20480" in str(e.value) and "25000" in str(e.value)


def test_preflight_rejects_a_server_serving_another_model():
    with patch("openai.OpenAI", return_value=_server(model_id="other")):
        with pytest.raises(PreflightError) as e:
            assert_serving("http://x/v1", "EMPTY", "m", 1000)
    assert "other" in str(e.value)


def test_preflight_passes_when_the_context_fits():
    with patch("openai.OpenAI", return_value=_server(max_len=32768)):
        assert_serving("http://x/v1", "EMPTY", "m", 20000)   # must not raise


def test_the_reasoning_settings_are_one_setting_for_every_stage(monkeypatch):
    """Thinking off and the smallest effort, in one place. They were six
    copies of one dict literal, and a model that wants a different switch
    would have needed six edits and a release."""
    from docpipe.llm_preflight import request_extras
    monkeypatch.delenv("LLM_ENABLE_THINKING", raising=False)
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    assert request_extras() == {"chat_template_kwargs":
                                {"enable_thinking": False},
                                "reasoning_effort": "low"}
    # And both are a restart, not a release: a server that refuses either
    # refuses every request of the run.
    monkeypatch.setenv("LLM_REASONING_EFFORT", "off")
    assert "reasoning_effort" not in request_extras()
    monkeypatch.setenv("LLM_ENABLE_THINKING", "1")
    assert request_extras()["chat_template_kwargs"]["enable_thinking"] is True


def test_the_preflight_refuses_a_server_that_will_not_take_them(monkeypatch):
    """Otherwise a refused setting is a 400 per document for as long as the
    job lives, and the job lives for hours."""
    from docpipe.llm_preflight import assert_request_extras

    class _Refused(Exception):
        status_code = 400

    client = _server()
    client.chat.completions.create.side_effect = _Refused("unknown field")
    with patch("openai.OpenAI", return_value=client):
        with pytest.raises(PreflightError) as e:
            assert_request_extras("http://x/v1", "EMPTY", "m")
    assert "LLM_REASONING_EFFORT=off" in str(e.value)

    # A server that is merely unreachable is not a refusal: the settings go
    # out anyway and the run's own retries deal with the outage.
    client.chat.completions.create.side_effect = OSError("connection refused")
    with patch("openai.OpenAI", return_value=client):
        assert_request_extras("http://x/v1", "EMPTY", "m")


def test_preflight_reports_an_unreachable_server_as_such():
    client = MagicMock()
    client.models.list.side_effect = OSError("connection refused")
    with patch("openai.OpenAI", return_value=client):
        with pytest.raises(PreflightError) as e:
            assert_serving("http://x/v1", "EMPTY", "m", 1000)
    assert "is the server up" in str(e.value)


# ---------------------------------------------------------------------------
# The reply budget
# ---------------------------------------------------------------------------

def test_reply_budget_grows_with_the_window():
    """A flat max_tokens truncated the answer mid-string on big windows — 24 of
    1030 in the ar6 book run. The reply echoes the window, so it has to follow
    the window's size."""
    small = refine_config.reply_tokens(300)
    big = refine_config.reply_tokens(3 * 1400)
    assert small == refine_config.LLM_MAX_TOKENS, "small windows keep the floor"
    assert big > small, "a window three times larger must get more room"


def test_reply_budget_is_capped():
    """One runaway window must not demand a context nobody serves."""
    assert (refine_config.reply_tokens(10 ** 6)
            == refine_config.REPLY_TOKENS_CEILING)


def test_the_budget_covers_the_largest_reply_it_would_ask_for():
    """Otherwise the preflight passes and the request is still rejected."""
    budget = refine_config.max_request_tokens()
    assert budget >= refine_config.REPLY_TOKENS_CEILING
    worst_window_words = (refine_config.WINDOW_SIZE
                          * refine_config.SECTION_MAX_WORDS)
    assert budget >= refine_config.reply_tokens(worst_window_words)


# ---------------------------------------------------------------------------
# The case that used to escape the bound entirely
# ---------------------------------------------------------------------------

def test_one_huge_segment_is_subdivided_not_surrendered():
    """A section whose whole text sits in ONE segment has no boundary to be cut
    on, and used to stay oversized however often it was asked — 51 of them in
    one ar6 run, up to 1409 words against a 1000 limit. Three in a window is
    what the model then had to hand back through an 8192-token door."""
    limit = refine_config.SECTION_MAX_WORDS
    out = split_oversized([_section(3000, n_segments=1)], ask=None,
                          max_words=limit)
    assert len(out) > 1, "one long segment must not defeat the limit"
    oversized = [s for s in out if len(s["content"].split()) > limit]
    assert not oversized, f"{len(oversized)} part(s) still over {limit} words"


def test_subdividing_a_segment_keeps_its_page_and_kind():
    """Splitting inside a segment must not cost provenance: both halves come
    from the same page and are still text."""
    section = _section(3000, n_segments=1)
    section["segments"][0]["page"] = 7
    out = split_oversized([section], ask=None,
                          max_words=refine_config.SECTION_MAX_WORDS)
    segs = [seg for part in out for seg in part["segments"]]
    assert len(segs) > 1
    assert {seg["page"] for seg in segs} == {7}
    assert {seg["kind"] for seg in segs} == {"text"}


def test_a_placeholder_segment_is_never_subdivided():
    """A table/figure reference has no text to divide."""
    from docpipe.refinement.split import _subdivide_segments
    section = {"title": "S", "content": "[p1_tbl0]",
               "segments": [{"page": 1, "kind": "table", "ref": "p1_tbl0"}]}
    assert _subdivide_segments(section, target=5) is False
    assert len(section["segments"]) == 1
