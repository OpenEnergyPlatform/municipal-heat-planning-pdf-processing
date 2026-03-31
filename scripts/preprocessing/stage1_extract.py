"""
stage1_extract.py – Text extraction with PyMuPDF (rawdict) + in-memory rendering.

For each PDF page, text blocks are extracted via page.get_text("rawdict"),
filtered, and returned as PageData objects. No paragraph merging is performed
so that block boundaries remain precise enough for Stage 2 suppression to
work correctly against model-predicted bounding boxes.

Image blocks (type=1) are ignored – they are detected in Stage 2.

Each page is also rendered to a PIL RGB image in memory so that Stage 2
(PP-DocLayoutV3) can run inference without any intermediate files on disk.
No PNGs are written to disk.

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
import numpy as np
from PIL import Image

from .config import (
    PAGE_RENDER_DPI,
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

        block_id = f"{prefix}_t{text_counter}"
        page_data.blocks.append(
            Block(id=block_id, type="text", bbox=bbox, content=text)
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
    img  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
    return Image.fromarray(img)


def extract_all_pages(
    pdf_path: str | Path,
    page_range: Optional[tuple[int, int]] = None,
) -> tuple[list[PageData], list[Image.Image], list[fitz.Page], fitz.Document]:
    """
    Extracts text, renders pages, and returns open fitz pages for Stage 2.

    Both operations share one fitz.Document open/close pair so the file is
    read exactly once. Everything stays in memory – no files are written.

    The returned fitz.Document must be closed by the caller after Stage 2
    has finished, since fitz.Page objects are only valid while their parent
    document remains open.

    Args:
        pdf_path:   Path to the source PDF file.
        page_range: Optional (start, end) tuple (0-indexed, end exclusive).
                    Defaults to the full document.

    Returns:
        A tuple (pages, pil_images, fitz_pages, fitz_doc) where:
          pages:      list[PageData]    – one entry per processed page.
          pil_images: list[Image.Image] – one RGB PIL image per page.
          fitz_pages: list[fitz.Page]   – open fitz pages for Stage 2 text extraction.
          fitz_doc:   fitz.Document     – must be closed by the caller.
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
        f"Stage 1: '{pdf_path.name}' – {len(page_indices)} pages "
        f"(text + render in-memory, DPI={PAGE_RENDER_DPI})"
    )

    pages:      list[PageData]    = []
    pil_images: list[Image.Image] = []
    fitz_pages: list[fitz.Page]   = []

    for i, page_index in enumerate(page_indices):
        try:
            fitz_page = doc[page_index]
            pages.append(_extract_page_text(fitz_page, page_index))
            pil_images.append(_render_page_to_pil(fitz_page, PAGE_RENDER_DPI))
            fitz_pages.append(fitz_page)
        except Exception as e:
            log.error(f"Page {page_index + 1} failed: {e}")

        done = i + 1
        if done % 20 == 0 or done == len(page_indices):
            log.info(f"Stage 1: {done}/{len(page_indices)} pages done")

    log.info(f"Stage 1: done – {len(pages)}/{len(page_indices)} pages")
    return pages, pil_images, fitz_pages, doc