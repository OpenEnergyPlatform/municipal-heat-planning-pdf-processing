"""
strips.py: A table image whose transcription does not fit its reply, read in
strips (owner request 2026-11-19, on the rule of 2026-09-12 that a request
whose reply does not fit its limit is split and its reply never salvaged, and
on that of 2026-11-17: "Nichts kürzen, einfach ggf. clever aufteilen").

The image is cut where a pixel row carries no writing, between two rows of the
table and never through one: in the run of blank pixel rows nearest its middle
that has writing above and below. The first strip is asked as the whole table
was; each later strip as a part that continues it, with the prompt of a table
that may continue the table before it, shown the caption and head the table
was read with. A strip whose reply is cut off again is cut again; one with no
blank row left between writing has no halves, and then the table has no
content (`reading.Hole` "cut_off"), as before. The table is the first strip's
reply with the rows of every later strip under its head
(`continuation.body_rows`), as the merge joins the parts of a table the layout
cut (`continuation.join`).

Author: Felix Vossel
"""
from __future__ import annotations

import io
import logging
from typing import Callable, Optional, Union

from docpipe.reading import Hole

from .config import STRIP_BLANK_PIXELS, STRIP_INK_CONTRAST, STRIP_RULE_DRIFT
from .continuation import body_rows

log = logging.getLogger(__name__)


def ink_rows(image) -> list:
    """For each pixel row of *image* (a PIL image), how many of its pixels
    are writing: darker by STRIP_INK_CONTRAST than both what their column
    holds in most rows and what their own row holds in most columns. A rule
    across the table (a row of one colour), a shaded row and a vertical rule
    (a column of one colour, also where a scan tilts it by up to
    STRIP_RULE_DRIFT pixels) are no writing."""
    import numpy as np
    gray = np.asarray(image.convert("L"), dtype=np.int16)
    if gray.ndim != 2 or not gray.size:
        return []
    column = np.median(gray, axis=0)
    drift = max(0, int(STRIP_RULE_DRIFT))
    padded = np.pad(column, drift, mode="edge")
    near = column.copy()
    for shift in range(-drift, drift + 1):
        near = np.minimum(near, padded[drift + shift:
                                       drift + shift + len(column)])
    row = np.median(gray, axis=1)
    level = np.minimum(near[None, :], row[:, None])
    return [int(n) for n in (gray < level - int(STRIP_INK_CONTRAST)).sum(axis=1)]


def cut_at(ink: list) -> Optional[int]:
    """The pixel row to cut an image with these *ink* rows (`ink_rows`) at:
    the middle of the run of blank rows (at most STRIP_BLANK_PIXELS pixels of
    writing) nearest the image's middle that has writing right above and
    right below it; None where there is no such run."""
    height = len(ink)
    blank = [n <= int(STRIP_BLANK_PIXELS) for n in ink]
    runs: list = []
    y = 0
    while y < height:
        if not blank[y]:
            y += 1
            continue
        start = y
        while y < height and blank[y]:
            y += 1
        if start > 0 and y < height:
            runs.append((start, y))
    if not runs:
        return None
    middle = height / 2
    start, end = min(runs, key=lambda run: (abs((run[0] + run[1]) / 2
                                                - middle), run[0]))
    return (start + end) // 2


def halves(png: bytes) -> Optional[tuple]:
    """The image *png* cut in two at `cut_at`, as two PNGs, top first; None
    where it has no blank row between writing to cut at."""
    from PIL import Image
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        at = cut_at(ink_rows(image))
        if at is None:
            return None
        width, height = image.size
        parts = []
        for box in ((0, 0, width, at), (0, at, width, height)):
            out = io.BytesIO()
            image.crop(box).save(out, format="PNG")
            parts.append(out.getvalue())
    return tuple(parts)


def height_of(png: bytes) -> int:
    """The height of the image *png* in pixels."""
    from PIL import Image
    with Image.open(io.BytesIO(png)) as image:
        return image.size[1]


Ask = Callable[[bytes, Optional[dict]], Union[dict, Hole]]


def read(png: bytes, ask: Ask, name: str = "") -> tuple:
    """(reply or Hole, requests) of a table image *png* read in strips.

    *ask(strip, first)* is one request for a strip: *first* is None for the
    first strip, which is asked as the whole table was, else the reply of the
    first strip, whose caption and head a later strip is shown. The reply is
    the first strip's with the rows of each later strip that stand under its
    head, and "strips", how many strips it was read in. A Hole of another
    cause than "cut_off" ends the reading with that hole; a strip cut off
    again is cut again, and one that cannot be cut is the Hole "cut_off"."""
    parts = halves(png)
    if parts is None:
        return Hole("cut_off", "no blank row to cut the image at"), 0
    pending = list(parts)
    replies: list = []
    asked = 0
    while pending:
        strip = pending.pop(0)
        got = ask(strip, replies[0] if replies else None)
        asked += 1
        if isinstance(got, Hole):
            if got.cause != "cut_off":
                return got, asked
            more = halves(strip)
            if more is None:
                log.warning("  %s: a strip of %d pixels was cut off and has "
                            "no blank row left to cut at: no content", name,
                            height_of(strip))
                return Hole("cut_off", "a strip with no blank row left to "
                                       "cut at"), asked
            pending[:0] = list(more)
            continue
        replies.append(got)
    first = replies[0]
    rows = list(first.get("rows") or [])
    for later in replies[1:]:
        rows += body_rows("\n".join(str(r) for r in later.get("rows") or []))
    log.info("  %s: read in %d strips (%d requests)", name, len(replies),
             asked)
    return {**first, "rows": rows, "strips": len(replies)}, asked
