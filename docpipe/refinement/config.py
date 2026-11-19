"""
config.py – Configuration and system prompt for the text-refinement module.

Author: Felix Vossel
"""
import json
import os
import tempfile
from pathlib import Path

from docpipe import llm_preflight, prompts, rules
from docpipe.artifacts import (DIR_RESULTS,               # noqa: F401  (re-exported)
                               REFINEMENT_PARTIAL_JSON,   # output (unfinished)
                               REFINEMENT_REPORT_JSON,    # output (what failed)
                               SECTIONS_JSON,             # input
                               SECTIONS_REFINED_JSON)     # output
# The text a stage stores is cleaned by one cleaner under one rule
# (normalize_unicode_nfkc), stages 1 to 3 and this one alike.
from docpipe.preprocessing.config import (clean_data,     # noqa: F401  (re-exported)
                                          clean_unicode)

# ---------------------------------------------------------------------------
# LLM (OpenAI-compatible API)
# ---------------------------------------------------------------------------
# LLM_MODEL must match the name the server serves the model under.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
LLM_API_KEY  = os.environ.get("LLM_API_KEY", "EMPTY")  # ignored by vLLM
LLM_TIMEOUT  = float(os.environ.get("LLM_TIMEOUT", "180"))

# Concurrent in-flight requests; the main throughput lever.
LLM_NUM_PARALLEL = int(os.environ.get("LLM_NUM_PARALLEL", "8"))

# What the stage decides is read from the rules where it decides, when it
# runs (docpipe/ruleset/stage_refine.py): the attempts at a request
# (refine_max_attempts), the sections of a window (refine_window_sections),
# the cutting of oversized sections (split_long_sections, section_max_words,
# section_target_words) and the cleaning of headings (clean_titles).

# ---------------------------------------------------------------------------
# System prompt for the LLM
# ---------------------------------------------------------------------------
# The rule refine_return_corrections asks the model for the changes instead of
# the whole section. Measured over 60 scenarios documents: 28% of sections came
# back byte-identical, the median section was 99% unchanged, and only 166 of
# 4887 were real conversions — the stage was paying output tokens, the
# expensive kind, to retype its own input.
# Off by default: the two modes use different prompts, so switching marks every
# cached document stale (correctly — its output came from the other prompt).


def prompt_ids() -> tuple:
    """The prompts a run of this stage is made of, the ones its stored
    results are versioned by. Only the window prompt actually in use is
    named, or merely having the second one on disk would count as a change
    against every stored result."""
    return (("refinement/refine_corrections"
             if rules.get("refine_return_corrections")
             else "refinement/refine"), "refinement/split",
            "refinement/split_user", "refinement/window_context")


# Read on first use, not on import: a prompt belongs to a profile, and the
# stage is imported before its command line names one.
@prompts.per_profile
def _plain_prompt():
    return prompts.load("refinement/refine")


@prompts.per_profile
def _corrections_prompt():
    return prompts.load("refinement/refine_corrections")


def refine_prompt():
    # Both spelled out, so the architecture test can still find them by AST.
    return (_corrections_prompt() if rules.get("refine_return_corrections")
            else _plain_prompt())


def system_prompt() -> str:
    return refine_prompt().text


def refine_prompt_id() -> str:
    """The prompt a window of this stage is asked with (`refine_prompt`)."""
    return refine_prompt().id


# Sampling belongs to the prompt, so both travel together in the .md front matter.
def llm_temperature() -> float:
    return float(os.environ.get(
        "LLM_TEMPERATURE", refine_prompt().meta.get(
            "temperature", rules.get("refine_default_temperature"))))


def llm_max_tokens() -> int:
    return int(os.environ.get(
        "LLM_MAX_TOKENS", refine_prompt().meta.get(
            "max_tokens", rules.get("refine_default_max_tokens"))))

# ---------------------------------------------------------------------------
# Context budget
# ---------------------------------------------------------------------------
# What one request can cost the server, so a serving flag can be checked
# against this number instead of guessed from a comment. Deliberately an
# over-estimate: too large costs a bit of KV cache, too small costs the run.
# (the rule tokens_per_word).
#
# The reply is the window handed back refined, so it is about as long as the
# window plus JSON scaffolding — a refined sentence is rarely shorter than the
# original (the rule reply_headroom). A flat max_tokens truncated the answer
# mid-string on big windows: 24 of 1030 in the scenarios book run, every one
# "Unterminated string".
# Ceiling (the rule reply_tokens_ceiling), so one runaway window cannot demand
# a context nobody has. The preflight checks the server against this, not
# against the flat default.


def reply_tokens(user_words: int) -> int:
    """The max_tokens for one request, from what that request actually asks
    the model to write. llm_max_tokens() stays the floor for small windows.

    When the model returns corrections it does not scale at all: the reply is a
    list of find/replace pairs, so its size follows the number of artefacts and
    not the length of the section. That is the entire saving. The budget still
    has to cover a bibliography, which is the one case that writes text out.
    """
    if rules.get("refine_return_corrections"):
        return llm_max_tokens()
    wanted = int(user_words * rules.get("tokens_per_word")
                 * rules.get("reply_headroom"))
    return max(llm_max_tokens(), min(wanted, rules.get("reply_tokens_ceiling")))


def largest_reply_tokens() -> int:
    """The largest reply a request of this stage asks for: the one reply the
    context budget counts."""
    return (llm_max_tokens() if rules.get("refine_return_corrections")
            else rules.get("reply_tokens_ceiling"))


def max_request_tokens() -> int:
    """Worst case for one window: prompt + a full window of maximum-size
    sections + the whole section before it as context (a section is at most
    the rule section_max_words) + the largest reply we would ever ask for, once.

    A section that cannot be split any further, whose reply was cut off, is
    asked once more with more room, but the room is bounded by what the served
    window leaves beyond this number (`further_room`), so the budget does not
    count a second reply. Rests on split.py holding section_max_words on its
    output. The one case it cannot hold, a single segment longer than the
    limit, is logged there.
    """
    per_word = rules.get("tokens_per_word")
    system = len(system_prompt().split()) * per_word
    window = ((rules.get("refine_window_sections") + 1)
              * rules.get("section_max_words") * per_word)
    return int(system + window + largest_reply_tokens())


def further_room(asked: int):
    """The token limit of the one further attempt of a window or an outline
    that was cut off at *asked* tokens and cannot be split, or None when the
    served window leaves it no more room than it had. See
    `llm_preflight.further_room`."""
    return llm_preflight.further_room(
        asked, reply=largest_reply_tokens(), budget=max_request_tokens(),
        role="llm")

# ---------------------------------------------------------------------------
# Atomic JSON I/O (the cleaning of the text is the one of stages 1 to 3,
# imported above)
# ---------------------------------------------------------------------------
def dump_json_atomic(data, path) -> None:
    """
    Serialise *data* as UTF-8 JSON to *path* atomically (temp file in the same
    directory + os.replace), so an interrupted write cannot leave a truncated
    file behind. Atomic only within one filesystem.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
