"""
config.py – Configuration and system prompt for the text-refinement module.

Author: Felix Vossel
"""
import json
import os
import tempfile
import unicodedata
from pathlib import Path
from re import compile

from docpipe import prompts
from docpipe.artifacts import (DIR_RESULTS,               # noqa: F401  (re-exported)
                               SECTIONS_JSON,             # input
                               SECTIONS_REFINED_JSON)     # output

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

MAX_RETRIES = 4
WINDOW_SIZE = 3  # sections per LLM call

# ── Oversized sections ─────────────────────────────────────────────────────
# A section is one retrieval chunk and one vector. Above SECTION_MAX_WORDS it
# is cut into parts of roughly SECTION_TARGET_WORDS (see split.py). Short
# sections are left alone: a short chunk is precise, a long one is mush.
SECTION_SPLIT_ENABLE  = True
SECTION_MAX_WORDS     = 1000
SECTION_TARGET_WORDS  = 600
SECTION_OUTLINE_WORDS = 14   # words per block shown to the model in the outline

# Numbering-prefix strip + ALL-CAPS de-shout applied on top of the LLM's pass.
TITLE_CLEANUP_ENABLE = True

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
SURROGATES = compile(r"[\uD800-\uDFFF]")

# ---------------------------------------------------------------------------
# System prompt for the LLM
# ---------------------------------------------------------------------------
PROMPT_IDS = ("refinement/refine", "refinement/split")

_REFINE = prompts.load("refinement/refine")
SYSTEM_PROMPT = _REFINE.text
# Sampling belongs to the prompt, so both travel together in the .md front matter.
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE",
                                       _REFINE.meta.get("temperature", 0.1)))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS",
                                    _REFINE.meta.get("max_tokens", 8192)))

# ---------------------------------------------------------------------------
# Context budget
# ---------------------------------------------------------------------------
# What one request can cost the server, so a serving flag can be checked
# against this number instead of guessed from a comment. Deliberately an
# over-estimate: too large costs a bit of KV cache, too small costs the run.
TOKENS_PER_WORD = 3.0


def max_request_tokens() -> int:
    """Worst case for one window: prompt + a full window of maximum-size
    sections + the reply we ask for.

    Rests on split.py holding SECTION_MAX_WORDS on its output. The one case it
    cannot hold — a single segment longer than the limit — is logged there.
    """
    system = len(SYSTEM_PROMPT.split()) * TOKENS_PER_WORD
    window = WINDOW_SIZE * SECTION_MAX_WORDS * TOKENS_PER_WORD
    return int(system + window + LLM_MAX_TOKENS)

# ---------------------------------------------------------------------------
# Unicode cleaning + atomic JSON I/O
# ---------------------------------------------------------------------------
def clean_unicode(s: str) -> str:
    """Remove surrogates, control chars, non-characters."""
    s = unicodedata.normalize("NFKC", s)
    s = SURROGATES.sub("", s)
    s = "".join(
        c for c in s
        if unicodedata.category(c) != "Cn"
        and not (0xFDD0 <= ord(c) <= 0xFDEF or (ord(c) & 0xFFFE) == 0xFFFE)
    )
    return s


def clean_data(obj):
    """Recursively clean unicode in nested dicts/lists/strings."""
    if isinstance(obj, dict):
        return {k: clean_data(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_data(v) for v in obj]
    if isinstance(obj, str):
        return clean_unicode(obj)
    return obj


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
