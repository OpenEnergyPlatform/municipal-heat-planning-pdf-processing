"""
columns.py – Reading order on a page that has more than one text column.

Sorting blocks top-to-bottom, then left-to-right is right for a single column
and wrong for two: it reads across the gutter and interleaves the columns line
by line, which scrambles the text beyond repair downstream.

So the gutters are found first — the vertical strips text stays out of — and the
page is then read column by column. Blocks that DO cross a gutter (a full-width
heading, a wide table) are spanning blocks: they end the columns above them and
start new ones below, which is exactly how such a page reads.

The number of columns is not assumed. Two is the common case in a report, but
slide-style pages run to three or four, and one wrong split there is as bad as
no split at all.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Sequence

from .config import (
    COLUMN_ALIGN_TOL_PT,
    COLUMN_GUTTER_WIDTH_PT,
    COLUMN_MAX_COLUMNS,
    COLUMN_MAX_SPAN_FRAC,
    COLUMN_MIN_ALIGNED_FRAC,
    COLUMN_MIN_COLUMN_SHARE,
    COLUMN_MIN_TEXT_BLOCKS,
    COLUMN_MIN_WIDTH_PT,
    COLUMN_SEARCH_STEP_PT,
)

log = logging.getLogger(__name__)

_HALF = COLUMN_GUTTER_WIDTH_PT / 2.0


def _valid(block) -> bool:
    bbox = getattr(block, "bbox", None)
    return bool(bbox) and len(bbox) >= 4 and bbox[2] > bbox[0]


def _bodies(blocks: Sequence) -> list:
    """The blocks that get a vote: text only.

    Tables and figures are routinely full-width even on a two-column page and
    would fill in every gutter.
    """
    return [b for b in blocks if getattr(b, "type", None) == "text" and _valid(b)]


def _reaches_into(block, x: float) -> bool:
    """True when the block overlaps the gutter strip centred on *x*."""
    return block.bbox[0] < x + _HALF and block.bbox[2] > x - _HALF


def _center(block) -> float:
    return (block.bbox[0] + block.bbox[2]) / 2.0


def _clear_runs(bodies: list, left: float, right: float, tolerance: int) -> list:
    """
    Candidate gutters: the midpoints of every run of x positions that at most
    *tolerance* blocks reach into, and that has text on both sides.

    The test is deliberately tolerant rather than a strict empty cut. A page
    whose two-column body sits under a full-width heading has no strictly empty
    column of whitespace anywhere, and would never split.
    """
    runs: list[list[float]] = []
    x = left
    while x <= right:
        blocking = sum(1 for b in bodies if _reaches_into(b, x))
        if blocking <= tolerance and any(b.bbox[2] <= x for b in bodies) \
                and any(b.bbox[0] >= x for b in bodies):
            if runs and x - runs[-1][-1] <= COLUMN_SEARCH_STEP_PT * 1.5:
                runs[-1].append(x)
            else:
                runs.append([x])
        x += COLUMN_SEARCH_STEP_PT
    return [(run[0] + run[-1]) / 2.0 for run in runs]


def _weakest_column(counts: list) -> int:
    return min(range(len(counts)), key=lambda i: counts[i])


def _columns_of(bodies: list, gutters: list) -> list:
    """The non-spanning blocks grouped by column, left to right."""
    grouped: list[list] = [[] for _ in range(len(gutters) + 1)]
    for b in bodies:
        if _spans(b, gutters):
            continue
        centre = _center(b)
        i = 0
        while i < len(gutters) and centre > gutters[i]:
            i += 1
        grouped[i].append(b)
    return grouped


def _column_counts(bodies: list, gutters: list) -> list:
    return [len(c) for c in _columns_of(bodies, gutters)]


def _shares_a_left_edge(column: list) -> bool:
    """
    True when the column's blocks line up on one left edge.

    This is what separates a column of text from the labels scattered around a
    chart: both leave clean vertical gaps, only one of them is typeset.
    """
    if not column:
        return False
    edges: dict = {}
    for b in column:
        key = round(b.bbox[0] / COLUMN_ALIGN_TOL_PT)
        edges[key] = edges.get(key, 0) + 1
    return max(edges.values()) / len(column) >= COLUMN_MIN_ALIGNED_FRAC


def _spans(block, gutters: Sequence) -> bool:
    """True when the block crosses at least one gutter."""
    return any(block.bbox[0] < g - _HALF and block.bbox[2] > g + _HALF for g in gutters)


def find_gutters(blocks: Sequence, page_width: float) -> list:
    """
    The x positions of the gutters between text columns, left to right. Empty
    for a single-column page.
    """
    bodies = _bodies(blocks)
    if len(bodies) < COLUMN_MIN_TEXT_BLOCKS or not page_width:
        return []

    left = min(b.bbox[0] for b in bodies)
    right = max(b.bbox[2] for b in bodies)
    if right - left < 2 * COLUMN_MIN_WIDTH_PT:
        return []

    tolerance = int(COLUMN_MAX_SPAN_FRAC * len(bodies))
    gutters = _clear_runs(bodies, left, right, tolerance)
    # Keep the widest-apart ones if a page somehow offers more splits than any
    # real layout has columns.
    if len(gutters) > COLUMN_MAX_COLUMNS - 1:
        return []

    # Drop splits that produce a column too narrow or too empty to be one. Each
    # removal merges that column into a neighbour, so the check runs again.
    while gutters:
        edges = [left] + list(gutters) + [right]
        widths = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
        counts = _column_counts(bodies, gutters)
        total = sum(counts)
        if not total:
            return []
        weak = _weakest_column(counts)
        too_thin = min(widths) < COLUMN_MIN_WIDTH_PT
        # Scale-free: the weakest column must carry its share of the average
        # load, whether the page has two columns or four.
        floor = max(2.0, COLUMN_MIN_COLUMN_SHARE * total / len(counts))
        if counts[weak] >= floor and not too_thin:
            break
        if too_thin:
            weak = widths.index(min(widths))
        # Merge the offending column into the neighbour it is closest to.
        if weak == 0:
            gutters.pop(0)
        elif weak == len(counts) - 1:
            gutters.pop()
        else:
            gutters.pop(weak if counts[weak + 1] < counts[weak - 1] else weak - 1)

    if not gutters:
        return []
    if sum(1 for b in bodies if _spans(b, gutters)) / len(bodies) > COLUMN_MAX_SPAN_FRAC:
        return []
    if not all(_shares_a_left_edge(c) for c in _columns_of(bodies, gutters)):
        return []
    return gutters


def order_blocks(blocks: Sequence, gutters: Sequence) -> list:
    """
    Blocks in reading order. Without gutters that is top-to-bottom,
    left-to-right; with them it is column by column, band by band.
    """
    by_position = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    if not gutters:
        return by_position

    out: list = []
    band: list = []

    def flush() -> None:
        columns: list[list] = [[] for _ in range(len(gutters) + 1)]
        for b in band:
            # By its centre, so a block that merely reaches into a gutter still
            # lands in exactly one column.
            centre = _center(b) if _valid(b) else 0.0
            i = 0
            while i < len(gutters) and centre > gutters[i]:
                i += 1
            columns[i].append(b)
        for column in columns:
            out.extend(column)
        band.clear()

    for block in by_position:
        if _valid(block) and _spans(block, gutters):
            flush()               # the spanning block closes the columns above it
            out.append(block)
        else:
            band.append(block)
    flush()
    return out


def sort_page(page, column_layout: str = "auto") -> list:
    """
    Put one page's blocks into reading order, in place. Returns the gutters
    used — empty when the page was read as a single column.

        single   never look for columns
        double   look, and fall back to a centre split if nothing is found
        auto     look, and accept one column as the answer
    """
    if column_layout == "single" or not page.blocks:
        page.blocks = sorted(page.blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
        return []

    gutters = find_gutters(page.blocks, page.width_pt)
    if not gutters and column_layout == "double":
        gutters = [page.width_pt / 2.0]
    page.blocks = order_blocks(page.blocks, gutters)
    return gutters


def sort_pages(pages: Sequence, column_layout: str = "auto") -> int:
    """Reading order for every page; returns how many were read as multi-column."""
    n = sum(1 for pg in pages if sort_page(pg, column_layout))
    if n:
        log.info(f"Reading order: {n}/{len(pages)} page(s) read as multi-column")
    return n


def count_multi_column_pages(pages: Sequence) -> tuple:
    """
    (pages with columns, the widest column count seen) without touching a thing.

    For deciding whether a corpus needs column_layout: auto at all — the answer
    costs a pass over the cached pages, not a re-run.
    """
    hits = [len(find_gutters(pg.blocks, pg.width_pt)) for pg in pages]
    found = [n for n in hits if n]
    return len(found), (max(found) + 1 if found else 1)
