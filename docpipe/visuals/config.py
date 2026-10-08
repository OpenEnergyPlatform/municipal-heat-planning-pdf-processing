"""
config.py – Central configuration for the imageprocessing module.

Author: Felix Vossel
"""
import json
import os
import tempfile
from pathlib import Path

from docpipe import prompts
from docpipe.artifacts import (DIR_IMAGES,                # noqa: F401  (re-exported)
                               SECTIONS_JSON, SECTIONS_REFINED_JSON, VISUALS_JSON)


def dump_json_atomic(data, path) -> None:
    """
    Serialise *data* as UTF-8 JSON to *path* atomically (temp file +
    os.replace). Atomic only within one filesystem.
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


# ---------------------------------------------------------------------------
# Vision model (OpenAI-compatible API)
# ---------------------------------------------------------------------------
# VLM_MODEL must match the name the server serves the model under.
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "http://localhost:8001/v1")
VLM_MODEL    = os.environ.get("VLM_MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
VLM_API_KEY  = os.environ.get("VLM_API_KEY", "EMPTY")  # ignored by vLLM

# Client-side timeout in seconds for a single vision request.
VLM_TIMEOUT  = float(os.environ.get("VLM_TIMEOUT", "180"))

# Concurrent in-flight vision requests; the main throughput lever for images.
VLM_NUM_PARALLEL = int(os.environ.get("VLM_NUM_PARALLEL", "8"))

MAX_RETRIES = 4

# Table transcription must be verbatim, so tables use their own near-
# deterministic temperature.
VLM_TEMPERATURE       = 0.6
TABLE_VLM_TEMPERATURE = 0.1
VLM_MAX_TOKENS        = 8192

# ── Context budget ─────────────────────────────────────────────────────────
# What one request can cost the server, so a serving flag can be checked
# against this number instead of guessed. Deliberately an over-estimate.
TOKENS_PER_WORD = 3.0
# A full-page crop at the resolution this stage sends. An over-estimate: the
# exact count depends on the model's patch grid, and getting it wrong upwards
# only costs KV cache, downwards costs the run.
IMAGE_TOKENS = 4096


def max_request_tokens() -> int:
    """Worst case for one vision request: the longer of the two system
    prompts + one page image + the reply we ask for, once. A reply cut off at
    its limit is asked once more with more room, but the room is bounded by
    what the served window leaves beyond this number (vision.call_vision), so
    no second reply is counted."""
    words = max(len(table_system_prompt().split()),
                len(figure_system_prompt().split()))
    return int(words * TOKENS_PER_WORD + IMAGE_TOKENS + VLM_MAX_TOKENS)

# ---------------------------------------------------------------------------
# Retry ladder
# ---------------------------------------------------------------------------
# Sparse Gantt grids ("Zeitlicher Rahmen", "Maßnahmenzeitplan 2024–2030") make
# the model lose count and emit empty cells until it hits VLM_MAX_TOKENS: the
# reply ends at its limit, cut off. Measured on the August 2026 run: runs of 29
# to 75 consecutive empty cells, where no real table exceeded a handful. The
# reply says so itself (finish_reason "length"), and call_vision starts over
# from the original prompt with the next penalty below.
#
# repetition_penalty for the attempt AFTER the indexed one failed, so index 0 is
# unused: the first attempt runs clean. A table legitimately repeats pipes,
# dashes, units and years, and a penalty blunts exactly that — hence the gentle
# start. A harder ladder (1.4 / 1.8) was tried and reverted: at 1.8 the pipe
# token is penalised so hard that a table is barely writable, and answers
# broke off after ten tokens.
RETRY_PENALTIES = [None, 1.1, 1.3]

# ---------------------------------------------------------------------------
# Table QA gate (see qa.py / process.py)
# ---------------------------------------------------------------------------
# Coverage is only assessed when the table has a text layer.
TABLE_QA_MIN_COVERAGE      = 0.5
TABLE_QA_MAX_DUPLICATION   = 0.4
TABLE_QA_MIN_SOURCE_TOKENS = 8
# Used for the single retry on QA failure.
TABLE_QA_RETRY_TEMPERATURE = 0.4
TABLE_QA_RETRY_PENALTY     = 1.3

# Input / output paths: see docpipe/artifacts.py, imported above. This module
# reads SECTIONS_REFINED_JSON (falling back to SECTIONS_JSON) and writes
# VISUALS_JSON; DIR_IMAGES holds the cropped table/figure PNGs.

# ---------------------------------------------------------------------------
# Prompts – English instructions, German output (the source documents are
# German municipal heat plans).
# ---------------------------------------------------------------------------

PROMPT_IDS = ("visuals/table_system", "visuals/table_user",
              "visuals/figure_system", "visuals/figure_user",
              "visuals/caption_keep", "visuals/caption_generate_table",
              "visuals/caption_generate_figure")

# Read on first use, not on import: a prompt belongs to a profile, and the
# stage is imported before its command line names one.

@prompts.per_profile
def table_system_prompt() -> str:
    return prompts.text("visuals/table_system")


@prompts.per_profile
def table_user_prompt() -> str:
    return prompts.text("visuals/table_user")


# ── Caption instruction fragments (inserted into the two user prompts) ──

@prompts.per_profile
def caption_keep_instruction() -> str:
    return prompts.text("visuals/caption_keep")


@prompts.per_profile
def caption_generate_table_instruction() -> str:
    return prompts.text("visuals/caption_generate_table")


@prompts.per_profile
def caption_generate_figure_instruction() -> str:
    return prompts.text("visuals/caption_generate_figure")


@prompts.per_profile
def figure_system_prompt() -> str:
    return prompts.text("visuals/figure_system")


@prompts.per_profile
def figure_user_prompt() -> str:
    return prompts.text("visuals/figure_user")
