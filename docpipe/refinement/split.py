"""
split.py – Cutting a section that is too long to be one retrieval chunk.

A section is one chunk and one vector. Past a certain length that vector stops
meaning anything in particular, and past the embedding model's token limit the
tail is not indexed at all. Such a section has to become several.

The model is never asked to reproduce the text — only to say WHERE it would cut
and what to call the parts. The cut itself happens mechanically at segment
boundaries, which is what makes this safe: nothing is rephrased, dropped or
invented, and each part keeps exactly the pages, tables and figures that belong
to its own text. It also keeps the call small, since a section long enough to
need splitting is by definition too long to echo.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

from docpipe import prompts

from .config import (
    SECTION_MAX_WORDS,
    SECTION_OUTLINE_WORDS,
    SECTION_SPLIT_ENABLE,
    SECTION_TARGET_WORDS,
)

log = logging.getLogger(__name__)

_SPLIT = prompts.load("refinement/split")
SPLIT_PROMPT = _SPLIT.text
SPLIT_TEMPERATURE = float(_SPLIT.meta.get("temperature", 0.1))
SPLIT_MAX_TOKENS = int(_SPLIT.meta.get("max_tokens", 1024))
PROMPT_IDS = ("refinement/split",)


def word_count(text: str) -> int:
    return len((text or "").split())


def _segment_text(seg: dict) -> str:
    """What this segment contributes to the section's content string."""
    if seg.get("kind") == "text":
        return seg.get("text") or ""
    ref = seg.get("ref")
    return f"[{ref}]" if ref else ""


def content_from_segments(segments: list) -> str:
    """
    Rebuild a section's content from its segments — the inverse of how Stage 3
    assembled it (text run by text run, a [block_id] marker where a table or
    figure sits).
    """
    return " ".join(t for t in (_segment_text(s) for s in segments) if t)


def _rebuild_matches(section: dict) -> bool:
    """
    Is this section's content exactly what its segments say it is?

    Only then can it be cut along them. Refinement may have rewritten the
    content, and a section whose provenance no longer lines up must be left
    alone rather than cut at a guessed position.
    """
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip()
    return norm(content_from_segments(section.get("segments") or [])) \
        == norm(section.get("content") or "")


def needs_split(section: dict, max_words: int = SECTION_MAX_WORDS) -> bool:
    content = section.get("content")
    if not isinstance(content, str):        # [LITERATURE] sections hold a list
        return False
    return word_count(content) > max_words


def outline(section: dict, sample_words: int = SECTION_OUTLINE_WORDS) -> str:
    """One numbered line per segment: its size and how it starts."""
    lines = []
    for i, seg in enumerate(section.get("segments") or []):
        if seg.get("kind") == "text":
            words = (seg.get("text") or "").split()
            head = " ".join(words[:sample_words])
            if len(words) > sample_words:
                head += " …"
            lines.append(f"{i:4d} [{len(words)} words] {head}")
        else:
            kind = "TABLE" if seg.get("kind") == "table" else "FIGURE"
            lines.append(f"{i:4d} [{kind}] {seg.get('ref') or ''}")
    return "\n".join(lines)


def _even_cuts(section: dict, target: int = SECTION_TARGET_WORDS) -> list:
    """Fallback: cut at the segment boundary nearest each target multiple."""
    cuts, running = [], 0
    for i, seg in enumerate(section.get("segments") or []):
        if i and running >= target:
            cuts.append({"at": i, "title": None})
            running = 0
        running += word_count(_segment_text(seg))
    return cuts


def _sanitize(cuts, n_segments: int, section: dict) -> list:
    """Keep only cuts that name a real segment boundary, in order, no duplicates."""
    clean, seen = [], set()
    for c in cuts or []:
        try:
            at = int(c.get("at"))
        except (AttributeError, TypeError, ValueError):
            continue
        if not (0 < at < n_segments) or at in seen:
            continue
        seen.add(at)
        title = (c.get("title") or "").strip() or None
        clean.append({"at": at, "title": title})
    clean.sort(key=lambda c: c["at"])
    # Drop a cut that would leave a sliver: below ~100 words a part is not a
    # chunk, it is debris.
    segments = section.get("segments") or []
    kept, previous = [], 0
    for c in clean:
        if sum(word_count(_segment_text(s)) for s in segments[previous:c["at"]]) < 100:
            continue
        kept.append(c)
        previous = c["at"]
    if kept and sum(word_count(_segment_text(s)) for s in segments[kept[-1]["at"]:]) < 100:
        kept.pop()
    return kept


def apply_cuts(section: dict, cuts: list, first_title: Optional[str] = None) -> list:
    """
    Cut *section* at the given segment indices. Returns the parts in order; the
    original is returned untouched (as a single-element list) when there is
    nothing to cut.
    """
    segments = section.get("segments") or []
    if not cuts:
        return [section]

    bounds = [0] + [c["at"] for c in cuts] + [len(segments)]
    titles = [first_title or section.get("title") or ""] + [c["title"] for c in cuts]
    media = {**{t["id"]: ("tables", t) for t in section.get("tables") or []},
             **{f["id"]: ("figures", f) for f in section.get("figures") or []}}

    parts = []
    for k in range(len(bounds) - 1):
        chunk = segments[bounds[k]:bounds[k + 1]]
        if not chunk:
            continue
        part = dict(section)
        part["segments"] = chunk
        part["content"] = content_from_segments(chunk)
        part["title"] = (titles[k] or section.get("title") or "").strip() \
            or f"{section.get('title') or 'Abschnitt'} ({k + 1})"
        # Each part keeps only the media its own text refers to.
        refs = [s.get("ref") for s in chunk if s.get("kind") in ("table", "figure")]
        part["tables"] = [media[r][1] for r in refs if r in media and media[r][0] == "tables"]
        part["figures"] = [media[r][1] for r in refs if r in media and media[r][0] == "figures"]
        pages = sorted({s["page"] for s in chunk if s.get("page") is not None})
        part["pages"] = pages
        part["page_number"] = pages[0] if pages else section.get("page_number")
        parts.append(part)
    return parts or [section]


def split_section(section: dict, ask: Optional[Callable] = None) -> list:
    """
    Split one oversized section. *ask* takes the rendered prompt and returns the
    model's raw reply; without it (or when the reply is unusable) the section is
    cut mechanically at even intervals.
    """
    if not _rebuild_matches(section):
        log.warning(
            "Section %r is %d words but its segments do not reproduce its "
            "content — not cutting it.",
            section.get("title"), word_count(section.get("content")),
        )
        return [section]

    n = len(section.get("segments") or [])
    cuts, first_title = [], None
    if ask is not None:
        try:
            reply = ask(prompts.text("refinement/split", target=SECTION_TARGET_WORDS),
                        f"TITLE: {section.get('title') or ''}\n\nOUTLINE:\n{outline(section)}")
            parsed = json.loads(reply) if isinstance(reply, str) else (reply or {})
            cuts = _sanitize(parsed.get("cuts"), n, section)
            first_title = (parsed.get("first_title") or "").strip() or None
        except Exception as e:                       # any failure → mechanical
            log.warning("Split call failed for %r: %s", section.get("title"), e)

    if not cuts:
        cuts = _sanitize(_even_cuts(section), n, section)
        if cuts:
            log.info("Section %r cut mechanically into %d parts",
                     section.get("title"), len(cuts) + 1)
    if not cuts:
        return [section]
    parts = apply_cuts(section, cuts, first_title)
    log.info("Section %r (%d words) → %d parts (%s words)",
             section.get("title"), word_count(section.get("content")), len(parts),
             ", ".join(str(word_count(p["content"])) for p in parts))
    return parts


def _subdivide_segments(section: dict, target: int) -> bool:
    """Cut text segments longer than *target* into smaller ones, in place.

    Sections are cut at segment boundaries, so a section whose text sits in one
    long segment has nowhere to be cut and stays oversized however often it is
    asked — 51 sections in one ar6 run, up to 1409 words against a 1000 limit,
    and three of those in a window is what the model then had to hand back.

    A text segment's page and kind are unchanged by the cut, so provenance is
    not lost here; it only gets finer. Placeholders (a table or figure ref)
    have no text to divide and are left alone.
    """
    segments = section.get("segments") or []
    if not segments:
        return False
    out, changed = [], False
    for seg in segments:
        words = (seg.get("text") or "").split() if seg.get("kind") == "text" else []
        if len(words) <= target:
            out.append(seg)
            continue
        for i in range(0, len(words), target):
            piece = dict(seg)
            piece["text"] = " ".join(words[i:i + target])
            out.append(piece)
        changed = True
    if changed:
        section["segments"] = out
    return changed


def _enforce_max(part: dict, max_words: int) -> list:
    """Cut *part* down until every piece fits *max_words*.

    The model is asked for readable boundaries, not for a bound, and it does
    return parts over the limit — an 11596-word section came back as 10 parts
    with one of 2392. Without this, max_words is a suggestion, and any context
    budget resting on it (config.max_request_tokens) is fiction.
    """
    # Aim below the limit, not at it: a cut lands on a segment boundary, so the
    # piece is the target plus whatever the straddling segment adds.
    target = min(SECTION_TARGET_WORDS, max(1, max_words // 2))
    out, queue = [], [part]
    while queue:
        piece = queue.pop(0)
        if not needs_split(piece, max_words):
            out.append(piece)
            continue
        rebuildable = _rebuild_matches(piece)
        cuts = (_sanitize(_even_cuts(piece, target=target),
                          len(piece.get("segments") or []), piece)
                if rebuildable else [])
        if not cuts and rebuildable and _subdivide_segments(piece, target):
            # No boundary to cut on because one segment carries the overflow.
            # Give it boundaries, then ask again.
            cuts = _sanitize(_even_cuts(piece, target=target),
                             len(piece.get("segments") or []), piece)
        if not cuts:
            # Left only when the segments no longer rebuild the content —
            # refinement rewrote it, and cutting at a guessed position would
            # attach text to the wrong page.
            log.warning(
                "Section %r stays at %d words (limit %d): its segments no "
                "longer rebuild its content, so there is no safe cut.",
                piece.get("title"), word_count(piece.get("content")), max_words)
            out.append(piece)
            continue
        queue.extend(apply_cuts(piece, cuts))
    return out


def split_oversized(sections: list, ask: Optional[Callable] = None,
                    max_words: int = SECTION_MAX_WORDS) -> list:
    """Split every section longer than *max_words*; returns the new list."""
    if not SECTION_SPLIT_ENABLE:
        return sections
    out, n_split, n_recut = [], 0, 0
    for section in sections:
        if needs_split(section, max_words):
            parts = split_section(section, ask)
            n_split += len(parts) > 1
            bounded = []
            for part in parts:
                pieces = _enforce_max(part, max_words)
                n_recut += len(pieces) > 1
                bounded.extend(pieces)
            out.extend(bounded)
        else:
            out.append(section)
    if n_split:
        log.info("Stage 4: split %d oversized section(s) → %d sections",
                 n_split, len(out))
    if n_recut:
        log.info("Stage 4: re-cut %d part(s) the model left over the limit",
                 n_recut)
    return out
