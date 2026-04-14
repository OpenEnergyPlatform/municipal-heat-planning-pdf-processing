"""
process.py – Core processing logic for table and figure enrichment.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path

import ollama

from .config import (
    TABLE_SYSTEM_PROMPT,
    TABLE_USER_PROMPT,
    FIGURE_SYSTEM_PROMPT,
    FIGURE_USER_PROMPT,
    CAPTION_KEEP_INSTRUCTION,
    CAPTION_GENERATE_TABLE_INSTRUCTION,
    CAPTION_GENERATE_FIGURE_INSTRUCTION,
)
from .models import ProcessingStats
from .vision import call_vision

log = logging.getLogger(__name__)


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


def process_table(
    table: dict,
    section: dict,
    base_path: Path,
    client: ollama.Client,
    stats: ProcessingStats,
    *,
    model: str | None = None,
) -> dict:
    """Enriches a single table entry with a ``markdown`` key."""
    result = copy.deepcopy(table)
    image_path = base_path / table["path"]

    if not image_path.exists():
        log.warning("  Image not found: %s", image_path)
        stats.inc("skipped_missing")
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
        client, TABLE_SYSTEM_PROMPT, user_prompt, image_path, **kwargs
    )

    if response:
        result["markdown"] = response.get("markdown", "")
        new_caption = response.get("caption", "")
        if not existing_caption and new_caption:
            result["caption"] = new_caption
            stats.inc("captions_generated")
        stats.inc("processed_tables")
        log.info("  ✓ Table %s", table["id"])
    else:
        stats.inc("failed_tables")
        log.error("  ✗ Table %s failed", table["id"])

    return result


# ---------------------------------------------------------------------------
# Figure processing
# ---------------------------------------------------------------------------

def process_figure(
    figure: dict,
    section: dict,
    base_path: Path,
    client: ollama.Client,
    stats: ProcessingStats,
    *,
    model: str | None = None,
) -> dict:
    """Enriches a single figure entry with a ``description`` key."""
    result = copy.deepcopy(figure)
    image_path = base_path / figure["path"]

    if not image_path.exists():
        log.warning("  Image not found: %s", image_path)
        stats.inc("skipped_missing")
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
        if not existing_caption and new_caption:
            result["caption"] = new_caption
            stats.inc("captions_generated")
        stats.inc("processed_figures")
        log.info("  ✓ Figure %s", figure["id"])
    else:
        stats.inc("failed_figures")
        log.error("  ✗ Figure %s failed", figure["id"])

    return result