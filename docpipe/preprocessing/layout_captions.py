"""
layout_captions.py: Caption resolution, a pass over the whole document after
Stage 2's batches. It attaches the nearest caption-like block to each table
or image, first among the blocks the layout model labelled as captions,
then, within a fixed distance, among plain text; the claimed block is removed
from the page so it is not also read as section prose. What a caption looks
like is `docpipe/captions.py`.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from .config import (
    CAPTION_CLASSES,
    SECTION_TITLE_CLASSES,
    CAPTION_MAX_DIST_PT,
    caption_like,
    CAPTION_REJECT_ACROSS_TITLE,
)
from .models import Block, PageData

log = logging.getLogger(__name__)

def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    """Returns the (x, y) center of a bounding box."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _euclidean_dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Returns the Euclidean distance between two 2D points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _title_between(y_a: float, y_b: float, title_ys: list[float]) -> bool:
    """True if any title y-center lies strictly between the two y values."""
    lo, hi = (y_a, y_b) if y_a <= y_b else (y_b, y_a)
    return any(lo < ty < hi for ty in title_ys)


def resolve_captions(pages: list[PageData]) -> list[PageData]:
    """
    Attaches captions to table/image blocks: nearest CAPTION_CLASSES block (no
    distance limit), else nearest plain text block within CAPTION_MAX_DIST_PT.

    The winning block's content goes into Block.caption and the block itself is
    removed from the page, so it never reaches section content. Each caption is
    claimed by at most one media block. Mutates *pages* in place.
    """
    for pg in pages:
        media_blocks  = [b for b in pg.blocks if b.type in ("table", "image")]
        # A block too long to be a label is body prose, whatever its distance
        # to the figure — and adopting it would delete it from the page.
        caption_pool  = [
            b for b in pg.blocks
            if b.layout_label in CAPTION_CLASSES and caption_like(b.content)
        ]
        fallback_pool = [
            b for b in pg.blocks
            if b.type == "text"
            and b.layout_label not in SECTION_TITLE_CLASSES
            and b.layout_label not in CAPTION_CLASSES
            and caption_like(b.content)
        ]

        # Heading y-centers act as boundaries: a candidate is rejected if a
        # heading lies vertically between it and the media block.
        title_ys = (
            [_bbox_center(b.bbox)[1] for b in pg.blocks
             if b.layout_label in SECTION_TITLE_CLASSES]
            if CAPTION_REJECT_ACROSS_TITLE else []
        )

        used_caption_ids: set[str] = set()

        for mb in media_blocks:
            mb_center = _bbox_center(mb.bbox)
            best_cap: Optional[Block] = None
            best_dist = float("inf")

            for cap in caption_pool:
                if cap.id in used_caption_ids:
                    continue
                cap_center = _bbox_center(cap.bbox)
                if _title_between(mb_center[1], cap_center[1], title_ys):
                    continue
                dist = _euclidean_dist(mb_center, cap_center)
                if dist < best_dist:
                    best_cap  = cap
                    best_dist = dist

            if best_cap is None:
                for fb in fallback_pool:
                    if fb.id in used_caption_ids:
                        continue
                    fb_center = _bbox_center(fb.bbox)
                    if _title_between(mb_center[1], fb_center[1], title_ys):
                        continue
                    dist = _euclidean_dist(mb_center, fb_center)
                    if dist < best_dist and dist <= CAPTION_MAX_DIST_PT:
                        best_cap  = fb
                        best_dist = dist

            if best_cap is not None:
                mb.caption = best_cap.content
                used_caption_ids.add(best_cap.id)

        pg.blocks = [
            b for b in pg.blocks
            if b.id not in used_caption_ids or b.type in ("table", "image")
        ]

    return pages
