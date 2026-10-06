"""
process.py: Core processing logic for table and figure enrichment.

Sends one table or figure image to the vision model, together with
its section context, and returns a copy of the item carrying the
model's markdown or description. A table's transcription passes a
quality gate and gets one retry with a stronger prompt on failure. An
image the model could not be read an object for (see vision.call_vision)
has no content: the item carries no markdown or description, says why in
`vlm_why`, and is counted by cause. No plain-text request fills in for it.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import threading
from contextlib import nullcontext
from pathlib import Path

import openai

from docpipe.reading import Hole

from . import qa, replies
from .config import (
    max_request_tokens,
    table_system_prompt,
    table_user_prompt,
    TABLE_VLM_TEMPERATURE,
    TABLE_QA_MIN_COVERAGE,
    TABLE_QA_MAX_DUPLICATION,
    TABLE_QA_MIN_SOURCE_TOKENS,
    TABLE_QA_RETRY_TEMPERATURE,
    TABLE_QA_RETRY_PENALTY,
    figure_system_prompt,
    figure_user_prompt,
    caption_keep_instruction,
    caption_generate_table_instruction,
    caption_generate_figure_instruction,
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
        return caption_keep_instruction()
    if kind == "table":
        return caption_generate_table_instruction()
    return caption_generate_figure_instruction()


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
    ``qa_warning`` field. The result of the check is kept for every table the
    model transcribed, as ``qa`` (the metrics of the kept attempt and whether
    it passed). A table the model gave no object for has none: it was not
    checked, which is not the same as passed. It has no ``markdown`` either,
    and says why in ``vlm_why``.

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

    user_prompt = table_user_prompt().format(
        section_title=section.get("title", "Unknown"),
        page_number=table.get("page_number", section.get("page_number", "?")),
        existing_caption=existing_caption or "(none)",
        section_content=_truncate(section.get("content", "")),
        caption_instruction=_caption_instruction(existing_caption, "table"),
    )

    kwargs = {"model": model} if model else {}
    response = call_vision(
        client, table_system_prompt(), user_prompt, image_path,
        temperature=TABLE_VLM_TEMPERATURE, reply=replies.TABLE,
        budget=max_request_tokens(), **kwargs
    )

    if isinstance(response, Hole):
        with guard:
            stats.hole("table", response.cause)
        result["vlm_why"] = response.cause
        log.error("  ✗ Table %s has no content (%s)", table["id"],
                  response.cause)
        return result

    raw_md = response["markdown"]
    passed, metrics = _assess_table(raw_md, source_text)

    if not passed:
        retry = call_vision(
            client, table_system_prompt(), user_prompt + _QA_RETRY_HINT, image_path,
            temperature=TABLE_QA_RETRY_TEMPERATURE,
            repetition_penalty=TABLE_QA_RETRY_PENALTY,
            reply=replies.TABLE, budget=max_request_tokens(), **kwargs,
        )
        # A retry that is a hole keeps the first attempt, which was read.
        if not isinstance(retry, Hole):
            retry_md = retry["markdown"]
            passed2, metrics2 = _assess_table(retry_md, source_text)
            # Keep the better attempt: prefer one that passes, else higher
            # coverage. An unassessable coverage is not "better" - there is
            # nothing to compare - so it never displaces the first attempt.
            cov2, cov1 = metrics2["coverage"], metrics["coverage"]
            if ((passed2 and not passed)
                    or (cov2 is not None and cov1 is not None and cov2 > cov1)):
                response, raw_md, passed, metrics = retry, retry_md, passed2, metrics2

    # Only collapse stutter rows on the failure path: a passing table may
    # legitimately contain identical adjacent rows, so don't touch it.
    result["markdown"] = raw_md if passed else qa.dedup_consecutive_rows(raw_md)
    result["qa"] = {"passed": passed, **metrics}
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
        cov = metrics["coverage"]
        log.warning(
            "  ⚠ Table %s low QA (coverage=%s duplication=%.2f)",
            table["id"],
            "n/a" if cov is None else f"{cov:.2f}", metrics["duplication"],
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

    user_prompt = figure_user_prompt().format(
        section_title=section.get("title", "Unknown"),
        page_number=figure.get("page_number", section.get("page_number", "?")),
        existing_caption=existing_caption or "(none)",
        section_content=_truncate(section.get("content", "")),
        caption_instruction=_caption_instruction(existing_caption, "figure"),
    )

    kwargs = {"model": model} if model else {}
    response = call_vision(
        client, figure_system_prompt(), user_prompt, image_path,
        reply=replies.FIGURE, budget=max_request_tokens(), **kwargs
    )

    if isinstance(response, Hole):
        with guard:
            stats.hole("figure", response.cause)
        result["vlm_why"] = response.cause
        log.error("  ✗ Figure %s has no content (%s)", figure["id"],
                  response.cause)
        return result

    result["description"] = response["description"]
    new_caption = response.get("caption", "")
    generated = bool(not existing_caption and new_caption)
    if generated:
        result["caption"] = new_caption
    with guard:
        if generated:
            stats.captions_generated += 1
        stats.processed_figures += 1
    log.info("  ✓ Figure %s", figure["id"])

    return result