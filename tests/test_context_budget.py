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


def test_split_gives_up_loudly_on_one_huge_segment(caplog):
    """A single segment over the limit cannot be cut — that is the one case
    the budget cannot bound, so it has to be said out loud."""
    section = _section(1500, n_segments=1)
    out = split_oversized([section], ask=None,
                          max_words=refine_config.SECTION_MAX_WORDS)
    assert len(out) == 1
    assert "no segment boundary" in caplog.text, "the unbounded case must warn"


# ---------------------------------------------------------------------------
# The budget itself
# ---------------------------------------------------------------------------

def test_budget_covers_a_full_window_plus_the_reply():
    budget = refine_config.max_request_tokens()
    window_words = refine_config.WINDOW_SIZE * refine_config.SECTION_MAX_WORDS
    assert budget > window_words + refine_config.LLM_MAX_TOKENS
    assert budget >= refine_config.LLM_MAX_TOKENS


def test_budget_reacts_to_the_knobs_it_names():
    """If a knob moves and the number does not, the number is decoration."""
    base = refine_config.max_request_tokens()
    with patch.object(refine_config, "WINDOW_SIZE", refine_config.WINDOW_SIZE + 1):
        assert refine_config.max_request_tokens() > base
    with patch.object(refine_config, "LLM_MAX_TOKENS",
                      refine_config.LLM_MAX_TOKENS + 1000):
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


def test_preflight_reports_an_unreachable_server_as_such():
    client = MagicMock()
    client.models.list.side_effect = OSError("connection refused")
    with patch("openai.OpenAI", return_value=client):
        with pytest.raises(PreflightError) as e:
            assert_serving("http://x/v1", "EMPTY", "m", 1000)
    assert "is the server up" in str(e.value)
