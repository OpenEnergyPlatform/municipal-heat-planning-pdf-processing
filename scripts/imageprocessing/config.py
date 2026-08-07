"""
config.py – Central configuration for the imageprocessing module.

Author: Felix Vossel
"""
import json
import os
import tempfile
from pathlib import Path

from docpipe import prompts


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

# ---------------------------------------------------------------------------
# Input / output file paths (relative to a preprocessing output_dir)
# ---------------------------------------------------------------------------

# Preferred input; falls back to STRUCTURED_OUTPUT_JSON when absent.
FINAL_OUTPUT_JSON      = "results/structured_output_final.json"
STRUCTURED_OUTPUT_JSON = "results/structured_output.json"

# Output produced by this module.
ENRICHED_OUTPUT_JSON   = "results/structured_output_images.json"

# Directory containing cropped table/figure PNGs (relative to output_dir).
DIR_IMAGES = "images"

# ---------------------------------------------------------------------------
# Prompts – English instructions, German output (the source documents are
# German municipal heat plans).
# ---------------------------------------------------------------------------

PROMPT_IDS = ("visuals/table_system", "visuals/table_user",
              "visuals/figure_system", "visuals/figure_user",
              "visuals/caption_keep", "visuals/caption_generate_table",
              "visuals/caption_generate_figure")

TABLE_SYSTEM_PROMPT = prompts.text("visuals/table_system")

TABLE_USER_PROMPT = prompts.text("visuals/table_user")

# ── Caption instruction fragments (inserted into TABLE/FIGURE_USER_PROMPT) ──

CAPTION_KEEP_INSTRUCTION = prompts.text("visuals/caption_keep")

CAPTION_GENERATE_TABLE_INSTRUCTION = prompts.text("visuals/caption_generate_table")

CAPTION_GENERATE_FIGURE_INSTRUCTION = prompts.text("visuals/caption_generate_figure")

FIGURE_SYSTEM_PROMPT = prompts.text("visuals/figure_system")

FIGURE_USER_PROMPT = prompts.text("visuals/figure_user")
