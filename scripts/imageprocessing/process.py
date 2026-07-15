"""
process.py – Core processing logic for table and figure enrichment.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import threading
from contextlib import nullcontext
from pathlib import Path

import openai

from . import qa
from .config import (
    TABLE_SYSTEM_PROMPT,
    TABLE_USER_PROMPT,
    TABLE_VLM_TEMPERATURE,
    TABLE_QA_MIN_COVERAGE,
    TABLE_QA_MAX_DUPLICATION,
    TABLE_QA_MIN_SOURCE_TOKENS,
    TABLE_QA_RETRY_TEMPERATURE,
    TABLE_QA_RETRY_PENALTY,
    FIGURE_SYSTEM_PROMPT,
    FIGURE_USER_PROMPT,
    CAPTION_KEEP_INSTRUCTION,
    CAPTION_GENERATE_TABLE_INSTRUCTION,
    CAPTION_GENERATE_FIGURE_INSTRUCTION,
)
from .models import ProcessingStats
from .vision import call_vision

log = logging.getLogger(__name__)

# Appended to the user prompt on a QA-failure retry.
_QA_RETRY_HINT = (
    "\n\nIMPORTANT: A previous attempt was incomplete or repeated rows. Read "
    "the table again carefully, row by row, and reproduce EVERY row exactly "
    "once — do not omit any row and do not repeat any row."
)


def _assess_table(markdown: str, source_text: str) -> tuple[bool, dict]:
    return qa.assess(
        markdown, source_text,
        min_coverage=TABLE_QA_MIN_COVERAGE,
        max_duplication=TABLE_QA_MAX_DUPLICATION,
        min_source_tokens=TABLE_QA_MIN_SOURCE_TOKENS,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 800) -> str:
    """Truncates text with an ellipsis if it exceeds max_len."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _caption_instruction(existing: str, kind: str) -> str:
    """Returns the appropriate caption instruction fragment."""
    if existing:
        return CAPTION_KEEP_INSTRUCTION
    if kind == "table":
        return CAPTION_GENERATE_TABLE_INSTRUCTION
    return CAPTION_GENERATE_FIGURE_INSTRUCTION


# ---------------------------------------------------------------------------
# Table processing
# ---------------------------------------------------------------------------

def process_table(
    table: dict,
    section: dict,
    base_path: Path,
    client: openai.OpenAI,
    stats: ProcessingStats,
    *,
    model: str | None = None,
    lock: threading.Lock | None = None,
    source_text: str = "",
) -> dict:
    """
    Returns a copy of *table* enriched with a ``markdown`` key.

    A QA gate checks coverage against *source_text* and row duplication; on
    failure the table is still returned (best effort) but carries a
    ``qa_warning`` field.

    *lock* guards the shared ProcessingStats: without it this is not safe to
    call from several threads at once.
    """
    guard = lock or nullcontext()
    # Shallow copy is enough: the caller deep-copied the whole document and we
    # only set top-level keys on the result.
    result = dict(table)
    result.pop("source_text", None)  # internal QA aid, never part of the output
    image_path = base_path / table["path"]

    if not image_path.exists():
        log.warning("  Image not found: %s", image_path)
        with guard:
            stats.skipped_missing += 1
        return result

    existing_caption = table.get("caption") or ""

    user_prompt = TABLE_USER_PROMPT.format(
        section_title=section.get("title", "Unknown"),
        page_number=table.get("page_number", section.get("page_number", "?")),
        existing_caption=existing_caption or "(none)",
        section_content=_truncate(section.get("content", "")),
        caption_instruction=_caption_instruction(existing_caption, "table"),
    )

    kwargs = {"model": model} if model else {}
    response = call_vision(
        client, TABLE_SYSTEM_PROMPT, user_prompt, image_path,
        temperature=TABLE_VLM_TEMPERATURE, **kwargs
    )

    if not response:
        with guard:
            stats.failed_tables += 1
        log.error("  ✗ Table %s failed", table["id"])
        return result

    raw_md = response.get("markdown", "")
    passed, metrics = _assess_table(raw_md, source_text)

    if not passed:
        retry = call_vision(
            client, TABLE_SYSTEM_PROMPT, user_prompt + _QA_RETRY_HINT, image_path,
            temperature=TABLE_QA_RETRY_TEMPERATURE,
            repetition_penalty=TABLE_QA_RETRY_PENALTY, **kwargs,
        )
        if retry:
            retry_md = retry.get("markdown", "")
            passed2, metrics2 = _assess_table(retry_md, source_text)
            # Keep the better attempt: prefer one that passes, else higher coverage.
            if (passed2 and not passed) or metrics2["coverage"] > metrics["coverage"]:
                response, raw_md, passed, metrics = retry, retry_md, passed2, metrics2

    # Only collapse stutter rows on the failure path: a passing table may
    # legitimately contain identical adjacent rows, so don't touch it.
    result["markdown"] = raw_md if passed else qa.dedup_consecutive_rows(raw_md)
    if not passed:
        result["qa_warning"] = metrics

    new_caption = response.get("caption", "")
    generated = bool(not existing_caption and new_caption)
    if generated:
        result["caption"] = new_caption

    with guard:
        if generated:
            stats.captions_generated += 1
        if not passed:
            stats.qa_failed_tables += 1
        stats.processed_tables += 1

    if passed:
        log.info("  ✓ Table %s", table["id"])
    else:
        log.warning(
            "  ⚠ Table %s low QA (coverage=%.2f duplication=%.2f)",
            table["id"], metrics["coverage"], metrics["duplication"],
        )

    return result


# ---------------------------------------------------------------------------
# Figure processing
# ---------------------------------------------------------------------------

def process_figure(
    figure: dict,
    section: dict,
    base_path: Path,
    client: openai.OpenAI,
    stats: ProcessingStats,
    *,
    model: str | None = None,
    lock: threading.Lock | None = None,
) -> dict:
    """
    Returns a copy of *figure* enriched with a ``description`` key.

    *lock* guards the shared ProcessingStats: without it this is not safe to
    call from several threads at once.
    """
    guard = lock or nullcontext()
    result = dict(figure)
    image_path = base_path / figure["path"]

    if not image_path.exists():
        log.warning("  Image not found: %s", image_path)
        with guard:
            stats.skipped_missing += 1
        return result

    existing_caption = figure.get("caption") or ""

    user_prompt = FIGURE_USER_PROMPT.format(
        section_title=section.get("title", "Unknown"),
        page_number=figure.get("page_number", section.get("page_number", "?")),
        existing_caption=existing_caption or "(none)",
        section_content=_truncate(section.get("content", "")),
        caption_instruction=_caption_instruction(existing_caption, "figure"),
    )

    kwargs = {"model": model} if model else {}
    response = call_vision(
        client, FIGURE_SYSTEM_PROMPT, user_prompt, image_path, **kwargs
    )

    if response:
        result["description"] = response.get("description", "")
        new_caption = response.get("caption", "")
        generated = bool(not existing_caption and new_caption)
        if generated:
            result["caption"] = new_caption
        with guard:
            if generated:
                stats.captions_generated += 1
            stats.processed_figures += 1
        log.info("  ✓ Figure %s", figure["id"])
    else:
        with guard:
            stats.failed_figures += 1
        log.error("  ✗ Figure %s failed", figure["id"])

    return result