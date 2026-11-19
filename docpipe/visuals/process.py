"""
process.py: Core processing logic for table and figure enrichment.

Sends one table or figure image to the vision model, together with
its section context, and returns a copy of the item carrying the
model's markdown or description. A table's transcription passes a
quality gate and gets one retry with a stronger prompt on failure. A table
whose reply does not fit the most room it can be given is read in strips
(`strips`). An image the model could not be read an object for (see
vision.call_vision) has no content: the item carries no markdown or
description, says why in `vlm_why`, and is counted by cause. No plain-text
request fills in for it.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import threading
from contextlib import nullcontext
from pathlib import Path

import openai

from docpipe.reading import Hole

from . import continuation, qa, replies, strips
from .config import (
    max_request_tokens,
    shown_bytes,
    table_continued_prompt,
    table_system_prompt,
    table_user_prompt,
    TABLE_VLM_TEMPERATURE,
    TABLE_QA_MIN_COVERAGE,
    TABLE_QA_MAX_DUPLICATION,
    TABLE_QA_MIN_SOURCE_TOKENS,
    TABLE_QA_MAX_SHARED_UNREADABLE,
    TABLE_QA_MIN_KNOWN_WORDS,
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


def _assess_table(markdown: str, source_text: str,
                  known_words: set[str] | None) -> tuple[bool, dict]:
    return qa.assess(
        markdown, source_text,
        min_coverage=TABLE_QA_MIN_COVERAGE,
        max_duplication=TABLE_QA_MAX_DUPLICATION,
        min_source_tokens=TABLE_QA_MIN_SOURCE_TOKENS,
        known_words=known_words,
        max_shared=TABLE_QA_MAX_SHARED_UNREADABLE,
        min_known=TABLE_QA_MIN_KNOWN_WORDS,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_text(reply: dict) -> str:
    """The Markdown of a table reply, whose `rows` are its lines in order."""
    return "\n".join(str(row) for row in reply["rows"])


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
    known_words: set[str] | None = None,
    before: dict | None = None,
) -> dict:
    """
    Returns a copy of *table* enriched with a ``markdown`` key.

    *before*, for a table that may continue the table before it
    (`continuation.before_of`), is shown to the model with what stands
    between them: the model says whether the table continues it and, where
    it does, writes its rows under that table's head. The result then keeps
    the id of the table before it as ``after`` and the answer as
    ``continues`` (owner decision 2026-11-06).

    A QA gate checks coverage against *source_text* and row duplication; a
    source text that cannot be read as the table against *known_words*, the
    words of the document's text, is no measure (`qa.unreadable`). On
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
        section_content=section.get("content", ""),
        caption_instruction=_caption_instruction(existing_caption, "table"),
    )
    reply = replies.TABLE
    if before is not None:
        user_prompt += table_continued_prompt().format(
            previous_caption=before.get("caption") or "(none)",
            previous_head=before.get("head") or "(no head)",
            between=before.get("between") or "(nothing)",
        )
        reply = replies.TABLE_CONTINUED

    kwargs = {"model": model} if model else {}
    # What this request holds, not the worst of the run: the room a cut-off
    # reply may be given follows from the text it really shows.
    budget = max_request_tokens(shown_bytes(
        section.get("content", ""),
        (before or {}).get("head") or "", (before or {}).get("between") or ""))
    own_prompt = user_prompt if before is None else table_user_prompt().format(
        section_title=section.get("title", "Unknown"),
        page_number=table.get("page_number", section.get("page_number", "?")),
        existing_caption=existing_caption or "(none)",
        section_content=section.get("content", ""),
        caption_instruction=_caption_instruction(existing_caption, "table"),
    )

    def ask(hint: str = "", temperature: float = TABLE_VLM_TEMPERATURE,
            penalty: float | None = None):
        """The table asked once, with *hint* after the prompt; read in
        strips (`strips`) where its reply does not fit the most room it can
        be given. Returns the reply or a Hole."""
        got = call_vision(
            client, table_system_prompt(), user_prompt + hint, image_path,
            temperature=temperature, repetition_penalty=penalty,
            reply=reply, budget=budget, **kwargs)
        if not (isinstance(got, Hole) and got.cause == "cut_off"):
            return got

        def strip(png: bytes, first: dict | None):
            if first is None:
                return call_vision(
                    client, table_system_prompt(), user_prompt + hint,
                    image_path, temperature=temperature,
                    repetition_penalty=penalty, reply=reply, budget=budget,
                    picture=png, **kwargs)
            # A later strip continues the table the first one was read as:
            # the table before it where the first strip continues that one,
            # else the first strip itself.
            if before is not None and first.get("continues") is True:
                caption, head = before.get("caption") or "", \
                    before.get("head") or ""
            else:
                caption = existing_caption or first.get("caption") or ""
                head = continuation.head_lines(_table_text(first))
            shown = table_continued_prompt().format(
                previous_caption=caption or "(none)",
                previous_head=head or "(no head)", between="(nothing)")
            return call_vision(
                client, table_system_prompt(), own_prompt + shown + hint,
                image_path, temperature=temperature,
                repetition_penalty=penalty, reply=replies.TABLE_CONTINUED,
                budget=max_request_tokens(shown_bytes(
                    section.get("content", ""), head)),
                picture=png, **kwargs)

        log.warning("  Table %s: cut off with the most room it can be "
                    "given, read in strips", table["id"])
        read, _asked = strips.read(image_path.read_bytes(), strip,
                                   name=table["id"])
        return read

    response = ask()

    if isinstance(response, Hole):
        with guard:
            stats.hole("table", response.cause)
        result["vlm_why"] = response.cause
        log.error("  ✗ Table %s has no content (%s)", table["id"],
                  response.cause)
        return result

    raw_md = _table_text(response)
    passed, metrics = _assess_table(raw_md, source_text, known_words)

    if not passed:
        retry = ask(_QA_RETRY_HINT, TABLE_QA_RETRY_TEMPERATURE,
                    TABLE_QA_RETRY_PENALTY)
        # A retry that is a hole keeps the first attempt, which was read.
        if not isinstance(retry, Hole):
            retry_md = _table_text(retry)
            passed2, metrics2 = _assess_table(retry_md, source_text,
                                              known_words)
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
    # How many strips the image was read in, where it was (`strips`).
    if response.get("strips"):
        result["strips"] = response["strips"]
    else:
        result.pop("strips", None)
    if not passed:
        result["qa_warning"] = metrics
    continues = False
    if before is not None:
        continues = response.get("continues") is True
        result["after"] = before["after"]
        result["continues"] = continues

    # A part of a table takes the caption of the table it continues, when
    # the merge joins it there; it gets none of its own.
    new_caption = "" if continues else response.get("caption", "")
    generated = bool(not existing_caption and new_caption)
    if generated:
        result["caption"] = new_caption

    with guard:
        if generated:
            stats.captions_generated += 1
        if not passed:
            stats.qa_failed_tables += 1
        if metrics["source_unreadable"]:
            stats.qa_unreadable_sources += 1
        if continues:
            stats.continued_tables += 1
        if result.get("strips"):
            stats.strip_tables += 1
        stats.processed_tables += 1

    if passed and metrics["source_unreadable"]:
        log.info("  ✓ Table %s (its PDF text cannot be read as the table: "
                 "coverage not assessed)", table["id"])
    elif passed:
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
        section_content=section.get("content", ""),
        caption_instruction=_caption_instruction(existing_caption, "figure"),
    )

    kwargs = {"model": model} if model else {}
    response = call_vision(
        client, figure_system_prompt(), user_prompt, image_path,
        reply=replies.FIGURE,
        budget=max_request_tokens(shown_bytes(section.get("content", ""))),
        **kwargs
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