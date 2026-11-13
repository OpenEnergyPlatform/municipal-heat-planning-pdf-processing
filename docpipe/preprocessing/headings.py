"""
headings.py: Font-based heading promotion, a pass over the whole document
after Stage 2's batches. A plain text block becomes a section title when the
layout model missed it, using the document's dominant body font size as the
reference.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from .config import (
    CAPTION_CLASSES,
    SECTION_TITLE_CLASSES,
    title_exclude_prefixes,
    TITLE_SAME_ROW_OVERLAP_FRACTION,
    FONT_HEADING_ENABLE,
    FONT_HEADING_SIZE_RATIO,
    FONT_HEADING_MIN_CHARS,
    FONT_HEADING_MAX_CHARS,
    FONT_HEADING_ALLCAPS_MIN_CHARS,
)
from .models import PageData
from .layout_blocks import vertical_overlap_fraction

log = logging.getLogger(__name__)

def _body_font_size(pages: list[PageData]) -> Optional[float]:
    """The char-weighted most common font size across plain text blocks (= body)."""
    weights: dict[float, int] = {}
    for pg in pages:
        for b in pg.blocks:
            if b.type == "text" and b.font_size and b.content:
                weights[b.font_size] = weights.get(b.font_size, 0) + len(b.content)
    if not weights:
        return None
    return max(weights, key=weights.get)


def _looks_like_heading(
    text: str, font_size: Optional[float], bold: bool, body_size: Optional[float]
) -> bool:
    """Conservative font/style test for whether a text block is a section heading."""
    n = len(text)
    if n < FONT_HEADING_MIN_CHARS or n > FONT_HEADING_MAX_CHARS:
        return False
    if any(text.lower().startswith(p) for p in title_exclude_prefixes()):
        return False
    # Prose guard: filters bold/emphasised body lines.
    if text.endswith((".", "!", "?")):
        return False
    if re.search(r"[.!?]\s+[A-ZÄÖÜ]", text):
        return False

    if font_size and body_size:
        if font_size >= body_size * FONT_HEADING_SIZE_RATIO:
            return True
        if bold and font_size > body_size:   # bold AND strictly larger than body
            return True

    letters = [c for c in text if c.isalpha()]
    is_allcaps = bool(letters) and all(c.isupper() for c in letters)
    if (is_allcaps and n >= FONT_HEADING_ALLCAPS_MIN_CHARS
            and (not body_size or not font_size or font_size >= body_size)):
        return True
    return False


def promote_headings_by_font(pages: list[PageData]) -> list[PageData]:
    """
    Promotes heading-looking plain text blocks to "paragraph_title" so Stage 3
    opens a section there. Only blocks the layout model left unclassified
    (layout_label is None) are considered. Mutates *pages* in place.
    """
    if not FONT_HEADING_ENABLE:
        return pages

    body = _body_font_size(pages)
    promoted = 0
    for pg in pages:
        # A candidate sharing a row with one of these is an inline label, not a
        # heading — mirrors the same-row demotion in process_page, so a
        # deliberately demoted title is not re-promoted here.
        occupied = [
            b.bbox for b in pg.blocks
            if b.type in ("table", "image")
            or b.layout_label in SECTION_TITLE_CLASSES
            or b.layout_label in CAPTION_CLASSES
        ]
        for b in pg.blocks:
            if not (b.type == "text" and b.layout_label is None and b.content):
                continue
            if not _looks_like_heading(
                b.content.strip(), b.font_size, bool(b.font_bold), body
            ):
                continue
            if any(
                vertical_overlap_fraction(b.bbox, ob)
                > (1.0 - TITLE_SAME_ROW_OVERLAP_FRACTION)
                for ob in occupied
            ):
                continue
            b.layout_label = "paragraph_title"
            promoted += 1
    if promoted:
        log.info(
            f"Stage 2: font-promoted {promoted} block(s) to headings "
            f"(body font ≈ {body}pt)"
        )
    return pages
