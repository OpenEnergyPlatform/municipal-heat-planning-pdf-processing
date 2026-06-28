"""
stage1_extract.py – Text extraction with PyMuPDF (rawdict) + in-memory rendering.

For each PDF page, text blocks are extracted via page.get_text("rawdict"),
filtered, and returned as PageData objects. No paragraph merging is performed
so that block boundaries remain precise enough for Stage 2 suppression to
work correctly against model-predicted bounding boxes.

Image blocks (type=1) are ignored – they are detected in Stage 2.

Pages are NOT rendered here. Stage 2 renders them per batch from the open
fitz pages so the whole document's page images are never resident at once.
The `_render_page_to_pil` helper lives here and is imported by Stage 2.

Coordinate system: PyMuPDF provides BBoxes as fitz.Rect with the origin at the
top-left in points (pt). [x0, y0, x1, y1] is stored without coordinate flipping.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image

from .config import (
    TEXT_BLOCK_MIN_CHARS,
    HYPHEN_EXCEPTIONS,
)
from .models import Block, PageData

log = logging.getLogger(__name__)


def _rect_to_bbox(rect: fitz.Rect) -> list[float]:
    return [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]


def _spans_to_text(block: dict) -> str:
    """
    Extracts text from a rawdict block and resolves hyphenation across line
    breaks using structural and linguistic heuristics.
    """
    lines_text: list[str] = []

    for line in block.get("lines", []):
        line_chars: list[str] = []
        for span in line.get("spans", []):
            for char in span.get("chars", []):
                c = char.get("c", "")
                if c:
                    line_chars.append(c)
        line_str = "".join(line_chars).strip()
        if line_str:
            lines_text.append(line_str)

    result: list[str] = []

    for line in lines_text:
        if not result:
            result.append(line)
            continue

        prev = result[-1]

        if prev.endswith("-") and line:
            before_dash = prev[-2] if len(prev) >= 2 else ""
            after_dash  = line[0]

            exception_match = any(
                re.match(rf"^{ex}\b", line, re.IGNORECASE)
                for ex in HYPHEN_EXCEPTIONS
            )

            if (
                before_dash.isalpha()
                and before_dash.islower()
                and after_dash.isalpha()
                and after_dash.islower()
                and not exception_match
            ):
                result[-1] = prev[:-1] + line
                continue

        result.append(" " + line)

    return "".join(result)


def _dominant_font(block: dict) -> tuple[Optional[float], bool]:
    """
    Returns the (char-weighted) dominant font size and a bold-majority flag for
    a rawdict text block, used downstream for font-based heading promotion.
    """
    sizes: dict[float, int] = {}
    bold_chars = 0
    total_chars = 0
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            n = len(span.get("chars", []))
            if n == 0:
                continue
            size = round(float(span.get("size", 0.0)), 1)
            sizes[size] = sizes.get(size, 0) + n
            flags = int(span.get("flags", 0))
            font = str(span.get("font", ""))
            if (flags & 16) or "bold" in font.lower():  # bit 4 = bold
                bold_chars += n
            total_chars += n
    if total_chars == 0:
        return None, False
    dominant_size = max(sizes, key=sizes.get)
    return dominant_size, bold_chars >= total_chars / 2


def _is_valid_text_block(text: str) -> bool:
    """Returns True if the text block contains enough content to be useful."""
    stripped = text.strip()
    if len(stripped) < TEXT_BLOCK_MIN_CHARS:
        return False
    if not any(c.isalnum() for c in stripped):
        return False
    return True


def _extract_page_text(page: fitz.Page, page_index: int) -> PageData:
    """Extracts text blocks from a single fitz.Page via rawdict."""
    page_num  = page_index + 1
    rect      = page.rect
    page_data = PageData(
        page_number=page_num,
        width_pt=round(rect.width,  2),
        height_pt=round(rect.height, 2),
    )

    prefix       = f"p{page_index}"
    text_counter = 0

    raw = page.get_text("rawdict", flags=0)

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue

        bbox = _rect_to_bbox(fitz.Rect(block["bbox"]))
        text = _spans_to_text(block)

        if not _is_valid_text_block(text):
            continue

        font_size, font_bold = _dominant_font(block)
        block_id = f"{prefix}_t{text_counter}"
        page_data.blocks.append(
            Block(id=block_id, type="text", bbox=bbox, content=text,
                  font_size=font_size, font_bold=font_bold)
        )
        text_counter += 1

    page_data.blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

    log.debug(f"Page {page_num}: {len(page_data.blocks)} text blocks extracted")
    return page_data


def _render_page_to_pil(page: fitz.Page, dpi: int) -> Image.Image:
    """Renders a fitz.Page to a PIL RGB image in memory without any disk I/O."""
    zoom = dpi / 72.0
    mat  = fitz.Matrix(zoom, zoom)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.w, pix.h), pix.samples)


def extract_all_pages(
    pdf_path: str | Path,
    page_range: Optional[tuple[int, int]] = None,
) -> tuple[list[PageData], list[fitz.Page], fitz.Document, int]:
    """
    Extracts text and returns the open fitz pages for Stage 2.

    Pages are NOT rendered here: Stage 2 renders them per batch (see
    detect_layout_all_pages) so the whole document's page images are never
    resident in memory at once.

    The returned fitz.Document must be closed by the caller after Stage 2
    has finished, since fitz.Page objects are only valid while their parent
    document remains open.

    Args:
        pdf_path:   Path to the source PDF file.
        page_range: Optional (start, end) tuple (0-indexed, end exclusive).
                    Defaults to the full document.

    Returns:
        A tuple (pages, fitz_pages, fitz_doc, n_failed) where:
          pages:      list[PageData]  – one entry per successfully processed page.
          fitz_pages: list[fitz.Page] – open fitz pages, index-aligned with pages.
          fitz_doc:   fitz.Document   – must be closed by the caller.
          n_failed:   int             – number of pages that failed and were
                                        skipped; the two lists stay aligned.
    """
    pdf_path = Path(pdf_path)
    doc      = fitz.open(str(pdf_path))
    total    = len(doc)

    start = 0
    end   = total
    if page_range:
        start, end = page_range
        end = min(end, total)

    page_indices = list(range(start, end))

    log.info(
        f"Stage 1: '{pdf_path.name}' – {len(page_indices)} pages (text extraction)"
    )

    pages:      list[PageData]  = []
    fitz_pages: list[fitz.Page] = []
    n_failed = 0

    for i, page_index in enumerate(page_indices):
        try:
            fitz_page = doc[page_index]
            # Build then append together so a failure can never leave the two
            # lists at mismatched lengths.
            page_data = _extract_page_text(fitz_page, page_index)
            pages.append(page_data)
            fitz_pages.append(fitz_page)
        except Exception as e:
            n_failed += 1
            log.error(f"Page {page_index + 1} failed: {e}")

        done = i + 1
        if done % 20 == 0 or done == len(page_indices):
            log.info(f"Stage 1: {done}/{len(page_indices)} pages done")

    if n_failed:
        log.warning(
            f"Stage 1: {n_failed}/{len(page_indices)} page(s) FAILED – "
            f"extraction is incomplete"
        )
    log.info(f"Stage 1: done – {len(pages)}/{len(page_indices)} pages")
    return pages, fitz_pages, doc, n_failed