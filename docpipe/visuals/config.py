"""
config.py – Central configuration for the imageprocessing module.

Author: Felix Vossel
"""
import json
import os
import tempfile
from pathlib import Path

from docpipe import prompts, rules
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

# The attempts, the temperatures and the reply room of a vision request are
# rules (`ruleset/stage_visuals.py`): vision_max_attempts, figure_temperature,
# table_temperature, vision_max_tokens.

# ── Context budget ─────────────────────────────────────────────────────────
# What one request can cost the server, so a serving flag can be checked
# against this number instead of guessed. Deliberately an over-estimate; the
# words-to-tokens factor is the rule vision_tokens_per_word.
# A full-page crop at the resolution this stage sends. An over-estimate: the
# exact count depends on the model's patch grid, and getting it wrong upwards
# only costs KV cache, downwards costs the run.
IMAGE_TOKENS = 4096
# What a request shows beside its prompts is shown whole (owner decision
# 2026-11-17): the section's text and, for a table that may continue the
# table before it, that table's head and what stands between the two. Its
# size counts in UTF-8 bytes, which bound its tokens from above (the
# tokenizers are byte-level: a token holds at least one byte).


def shown_bytes(section_content: str = "", head: str = "",
                between: str = "") -> int:
    """The UTF-8 bytes one request shows beside its prompts."""
    return sum(len((text or "").encode("utf-8"))
               for text in (section_content, head, between))


def longest_shown(sections: list) -> int:
    """The most UTF-8 bytes one request of a document with *sections* shows
    beside its prompts: its longest section text, the longest text between
    two of its tables that may continue one another, and, for the head of
    the table before, the longest PDF text of one of its tables (a head is
    part of it)."""
    from . import continuation
    content = max((shown_bytes(str(s.get("content") or ""))
                   for s in sections), default=0)
    between = max((shown_bytes(v.get("between") or "")
                   for v in continuation.links(sections).values()), default=0)
    head = max((shown_bytes(str(t.get("source_text") or ""))
                for s in sections for t in s.get("tables") or ()), default=0)
    return content + between + head


def longest_in(root, names: tuple = ()) -> int:
    """`longest_shown` over every document the stage reads under *root*,
    or over *root* itself where it is one document: the first of *names*
    each has (the sections files the stage reads, the refined one first
    where none are given); 0 where there are none or none can be read."""
    from docpipe.artifacts import document_dirs
    names = tuple(names) or (SECTIONS_REFINED_JSON, SECTIONS_JSON)
    most = 0
    if root is None or not Path(root).is_dir():
        return 0
    own = any((Path(root) / name).exists() for name in names)
    for doc in ([Path(root)] if own else
                document_dirs(root, *names, distinct=False)):
        for name in names:
            path = Path(doc) / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                break
            sections = data.get("sections") if isinstance(data, dict) else None
            if isinstance(sections, list):
                most = max(most, longest_shown(
                    [s for s in sections if isinstance(s, dict)]))
            break
    return most


def max_request_tokens(shown: int | None = None) -> int:
    """Worst case for one vision request: the longer of the two requests'
    prompts with the texts they show, + one page image + the reply we ask
    for, once. *shown* is the UTF-8 bytes the request shows beside its
    prompts (`shown_bytes`; for the stage's preflight `longest_in` of the
    documents the run reads, taken from the active profile's processed
    folder where not given). A table's request counts the part it gets
    where it may continue the table before it. A reply cut off at its limit
    is asked once more with more room, but the room is bounded by what the
    served window leaves beyond this number (vision.call_vision), so no
    second reply is counted."""
    if shown is None:
        from docpipe.profile import active_profile
        profile = active_profile()
        shown = longest_in(getattr(profile, "processed_dir", None))
    text = shown
    per_word = float(rules.get("vision_tokens_per_word"))
    table = ((len(table_system_prompt().split())
              + len(table_user_prompt().split())
              + len(table_continued_prompt().split())) * per_word
             + text)
    figure = ((len(figure_system_prompt().split())
               + len(figure_user_prompt().split())) * per_word
              + text)
    return int(max(table, figure) + IMAGE_TOKENS
               + int(rules.get("vision_max_tokens")))

# ---------------------------------------------------------------------------
# Retry ladder, strips and table check
# ---------------------------------------------------------------------------
# Sparse Gantt grids ("Zeitlicher Rahmen", "Maßnahmenzeitplan 2024–2030") make
# the model lose count and emit empty cells until it hits its reply room: the
# reply ends at its limit, cut off. Measured on the August 2026 run: runs of 29
# to 75 consecutive empty cells, where no real table exceeded a handful. The
# reply says so itself (finish_reason "length"), and call_vision starts over
# from the original prompt with the next penalty of the rule
# vision_retry_penalties. A table legitimately repeats pipes, dashes, units and
# years, and a penalty blunts exactly that, hence the gentle start; a penalty
# of 1.8 broke answers off after ten tokens.
#
# The strips (strips.py) are cut by the rules strip_ink_contrast,
# strip_blank_pixels and strip_rule_drift; the table check (qa.py,
# process.py) follows table_min_coverage, table_max_duplication,
# table_min_source_tokens, table_unreadable_shared_below,
# table_unreadable_known_below, table_retry_temperature and
# table_retry_penalty. Measured on the scenarios rebuild of 2026-11-11: of
# 1,609 assessable tables 31 fell below the coverage; 27 were sideways tables
# of a scanned book with an upside-down OCR layer (shared <= 0.11, known <=
# 0.41), one a frame whose layer is a heading with two links (0.04, 0.44); the
# 3 with a readable layer had >= 0.57 and >= 0.86.

# Input / output paths: see docpipe/artifacts.py, imported above. This module
# reads SECTIONS_REFINED_JSON (falling back to SECTIONS_JSON) and writes
# VISUALS_JSON; DIR_IMAGES holds the cropped table/figure PNGs.

# ---------------------------------------------------------------------------
# Prompts – English instructions, German output (the source documents are
# German municipal heat plans).
# ---------------------------------------------------------------------------

PROMPT_IDS = ("visuals/table_system", "visuals/table_user",
              "visuals/table_continued", "visuals/table_retry_hint",
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


# Added to the user prompt of a table that may continue the table before it
# (see continuation.py).
@prompts.per_profile
def table_continued_prompt() -> str:
    return prompts.text("visuals/table_continued")


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
