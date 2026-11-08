"""
layout_blocks.py: Turns the detections of one page into blocks.

Each surviving box becomes a text suppression, a saved table or image crop,
or a title or caption Block; classes outside those sets are ignored, since
the Stage 1 PyMuPDF text blocks already cover that content. The text in a
footnote box leaves the page like a page number does, and the document's log
says how many text blocks and characters that was.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image

from .config import (
    DIR_IMAGES,
    SUPPRESS_CLASSES,
    FOOTNOTE_CLASSES,
    TABLE_CLASSES,
    IMAGE_CLASSES,
    CAPTION_CLASSES,
    SECTION_TITLE_CLASSES,
    TEXT_SUPPRESS_OVERLAP,
    title_exclude_prefixes,
    TITLE_SAME_ROW_OVERLAP_FRACTION,
    TABLE_BOX_MARGIN_PT,
    IMAGE_BOX_MARGIN_PT,
    MASK_FIGURES_IN_TABLE_CROPS,
)
from .models import Block, PageData
from .rendering import FITZ_LOCK
from .crops import CropJob, extract_crop_rgb
from .layout_model import Detection, boxes_intersect

log = logging.getLogger(__name__)

@dataclass
class FootnoteTally:
    """What the footnote class took off the pages of one document."""
    blocks: int = 0
    chars: int = 0

    def add(self, removed: list[Block]) -> None:
        self.blocks += len(removed)
        self.chars += sum(len(b.content or "") for b in removed)

    def line(self) -> str:
        return (f"Stage 2: the footnote class removed {self.blocks} text "
                f"block(s) with {self.chars} character(s)")


def _bbox_px_to_pt(
    bbox_px: list[float],
    img_w_px: int,
    img_h_px: int,
    page_w_pt: float,
    page_h_pt: float,
) -> list[float]:
    """Scales pixel coordinates to PDF-point coordinates."""
    sx = page_w_pt / img_w_px
    sy = page_h_pt / img_h_px
    return [
        round(bbox_px[0] * sx, 2),
        round(bbox_px[1] * sy, 2),
        round(bbox_px[2] * sx, 2),
        round(bbox_px[3] * sy, 2),
    ]


def _bbox_pt_to_px(
    bbox_pt: list[float],
    page_w_pt: float,
    page_h_pt: float,
    img_w_px: int,
    img_h_px: int,
) -> list[float]:
    """Scales PDF-point coordinates to pixel coordinates (inverse of _bbox_px_to_pt)."""
    sx = img_w_px / page_w_pt
    sy = img_h_px / page_h_pt
    return [
        round(bbox_pt[0] * sx, 2),
        round(bbox_pt[1] * sy, 2),
        round(bbox_pt[2] * sx, 2),
        round(bbox_pt[3] * sy, 2),
    ]


def _expand_bbox_pt(
    bbox_pt: list[float],
    margin_pt: tuple[float, float, float, float],
    page_w_pt: float,
    page_h_pt: float,
) -> list[float]:
    """
    Expands *bbox_pt* by *margin_pt* (left, top, right, bottom), clamped to the
    page bounds.
    """
    x0, y0, x1, y1 = bbox_pt
    ml, mt, mr, mb = margin_pt

    x0_exp = max(0.0, x0 - ml)
    y0_exp = max(0.0, y0 - mt)
    x1_exp = min(page_w_pt, x1 + mr)
    y1_exp = min(page_h_pt, y1 + mb)

    return [x0_exp, y0_exp, x1_exp, y1_exp]


def _overlap_fraction(text_bbox: list[float], region_bbox: list[float]) -> float:
    """
    Fraction of *text_bbox*'s area covered by *region_bbox*. Asymmetric by
    design — the argument order matters.
    """
    ix0 = max(text_bbox[0], region_bbox[0])
    iy0 = max(text_bbox[1], region_bbox[1])
    ix1 = min(text_bbox[2], region_bbox[2])
    iy1 = min(text_bbox[3], region_bbox[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    text_area = max(
        (text_bbox[2] - text_bbox[0]) * (text_bbox[3] - text_bbox[1]), 1e-6
    )
    return inter / text_area


def vertical_overlap_fraction(bbox_a: list[float], bbox_b: list[float]) -> float:
    """Vertical overlap fraction, relative to the shorter of the two boxes."""
    y0_a, y1_a = bbox_a[1], bbox_a[3]
    y0_b, y1_b = bbox_b[1], bbox_b[3]

    iy0 = max(y0_a, y0_b)
    iy1 = min(y1_a, y1_b)

    if iy1 <= iy0:
        return 0.0

    overlap = iy1 - iy0
    shorter_height = min(y1_a - y0_a, y1_b - y0_b)
    return overlap / shorter_height if shorter_height > 0 else 0.0


def _text_from_bbox(fp: fitz.Page, bbox_pt: list[float]) -> str:
    """Text inside *bbox_pt* on the page; "" when empty or on any failure."""
    try:
        x0, y0, x1, y1 = bbox_pt
        rect = fitz.Rect(x0, y0, x1, y1)

        with FITZ_LOCK:      # the prefetch thread renders from the same doc
            text = fp.get_text("text", clip=rect)
        text = text.strip()
        return text if text else ""
    except Exception as e:
        log.debug(f"Text extraction from bbox failed: {e}")
        return ""


def _lies_in(block: Block, boxes: list[list[float]]) -> bool:
    """Whether *boxes* take this block off the page: a text block that lies in
    one of them by TEXT_SUPPRESS_OVERLAP. Removal and the footnote count ask
    this one question, so the count cannot drift from what is removed."""
    return block.type == "text" and any(
        _overlap_fraction(block.bbox, box) >= TEXT_SUPPRESS_OVERLAP
        for box in boxes
    )


def process_page(
    pg: PageData,
    fp: fitz.Page,
    det_w: int,
    det_h: int,
    crop_image: Image.Image,
    detections: list[Detection],
    images_dir: Path,
    footnotes: Optional[FootnoteTally] = None,
) -> tuple[PageData, list[CropJob]]:
    """
    Processes one page through all detection-type branches; returns the updated
    PageData and the crop jobs still to be written.

    *detections* are in detection-image pixel space (det_w x det_h), while
    crops come from *crop_image*, which may be rendered at a different DPI.
    *footnotes*, when given, is told which text blocks the footnote class took
    off this page.
    """
    prefix = f"p{pg.page_number - 1}"

    new_blocks: list[Block] = []
    crop_jobs: list[CropJob] = []
    suppress_bboxes: list[list[float]] = []
    footnote_bboxes: list[list[float]] = []

    title_counter = 0
    cap_counter   = 0
    tbl_counter   = 0
    img_counter   = 0

    # Figure/chart boxes in detection-pixel space, for pre-masking figures
    # embedded in a table crop.
    figure_dets_px = (
        [d.bbox_px for d in detections if d.label in IMAGE_CLASSES]
        if MASK_FIGURES_IN_TABLE_CROPS else []
    )

    for det in detections:
        label = det.label
        bbox_px = det.bbox_px
        bbox_pt = _bbox_px_to_pt(
            bbox_px,
            det_w, det_h,
            pg.width_pt, pg.height_pt,
        )

        if label in SUPPRESS_CLASSES:
            suppress_bboxes.append(bbox_pt)
            if label in FOOTNOTE_CLASSES:
                footnote_bboxes.append(bbox_pt)
            continue

        if label in SECTION_TITLE_CLASSES:
            title_text = _text_from_bbox(fp, bbox_pt)
            if not title_text:
                log.debug(
                    f"Page {pg.page_number}: title block (label={label}) has no text"
                )
                continue

            if any(title_text.lower().startswith(p) for p in title_exclude_prefixes()):
                log.debug(f"Page {pg.page_number}: title rejected (excluded prefix)")
                continue

            overlaps_same_row = any(
                vertical_overlap_fraction(bbox_pt, sb)
                > (1.0 - TITLE_SAME_ROW_OVERLAP_FRACTION)
                for sb in suppress_bboxes
            )
            if overlaps_same_row:
                log.debug(f"Page {pg.page_number}: title on same row, treating as text")
                continue

            block_id = f"{prefix}_title{title_counter}"
            title_counter += 1
            new_blocks.append(Block(
                id=block_id,
                type="text",
                bbox=bbox_pt,
                content=title_text,
                confidence=det.score,
                layout_label=label,
            ))
            suppress_bboxes.append(bbox_pt)
            continue

        if label in CAPTION_CLASSES:
            caption_text = _text_from_bbox(fp, bbox_pt)
            block_id = f"{prefix}_cap{cap_counter}"
            cap_counter += 1
            new_blocks.append(Block(
                id=block_id,
                type="text",
                bbox=bbox_pt,
                content=caption_text,
                confidence=det.score,
                layout_label=label,
            ))
            suppress_bboxes.append(bbox_pt)
            continue

        if label in TABLE_CLASSES:
            bbox_pt_expanded = _expand_bbox_pt(
                bbox_pt, TABLE_BOX_MARGIN_PT, pg.width_pt, pg.height_pt
            )
            bbox_px_expanded = _bbox_pt_to_px(
                bbox_pt_expanded,
                pg.width_pt, pg.height_pt,
                crop_image.width, crop_image.height,
            )

            # White out any figure/chart overlapping this table so its lines are
            # not transcribed as phantom table rows.
            mask_boxes_px: list[list[float]] = []
            for fpx in figure_dets_px:
                fpt = _bbox_px_to_pt(fpx, det_w, det_h, pg.width_pt, pg.height_pt)
                if boxes_intersect(fpt, bbox_pt_expanded):
                    mask_boxes_px.append(_bbox_pt_to_px(
                        fpt, pg.width_pt, pg.height_pt,
                        crop_image.width, crop_image.height,
                    ))

            crop_rgb = extract_crop_rgb(
                crop_image, bbox_px_expanded, mask_bboxes_px=mask_boxes_px
            )
            if crop_rgb is None:
                log.debug(f"Page {pg.page_number}: table crop degenerate, skipped")
                continue
            if mask_boxes_px:
                log.debug(
                    f"Page {pg.page_number}: pre-masked {len(mask_boxes_px)} "
                    f"figure region(s) in table crop"
                )

            block_id = f"{prefix}_tbl{tbl_counter}"
            tbl_counter += 1
            filename = f"{block_id}.png"
            out_path = images_dir / filename

            new_blocks.append(Block(
                id=block_id,
                type="table",
                bbox=bbox_pt_expanded,
                path=f"{DIR_IMAGES}/{filename}",
                confidence=det.score,
                layout_label=label,
                # Native text inside the *unexpanded* box, as a QA reference.
                source_text=(_text_from_bbox(fp, bbox_pt) or None),
            ))
            crop_jobs.append(CropJob(
                block_id=block_id,
                out_path=out_path,
                crop_rgb=crop_rgb,
            ))
            suppress_bboxes.append(bbox_pt_expanded)
            continue

        if label in IMAGE_CLASSES:
            bbox_pt_expanded = _expand_bbox_pt(
                bbox_pt, IMAGE_BOX_MARGIN_PT, pg.width_pt, pg.height_pt
            )
            bbox_px_expanded = _bbox_pt_to_px(
                bbox_pt_expanded,
                pg.width_pt, pg.height_pt,
                crop_image.width, crop_image.height,
            )

            crop_rgb = extract_crop_rgb(crop_image, bbox_px_expanded)
            if crop_rgb is None:
                log.debug(f"Page {pg.page_number}: image crop degenerate, skipped")
                continue

            block_id = f"{prefix}_img{img_counter}"
            img_counter += 1
            filename = f"{block_id}.png"
            out_path = images_dir / filename

            new_blocks.append(Block(
                id=block_id,
                type="image",
                bbox=bbox_pt_expanded,
                path=f"{DIR_IMAGES}/{filename}",
                confidence=det.score,
                layout_label=label,
            ))
            crop_jobs.append(CropJob(
                block_id=block_id,
                out_path=out_path,
                crop_rgb=crop_rgb,
            ))
            suppress_bboxes.append(bbox_pt_expanded)
            continue

    if suppress_bboxes:
        before = len(pg.blocks)
        if footnotes is not None:
            footnotes.add([b for b in pg.blocks if _lies_in(b, footnote_bboxes)])
        pg.blocks = [b for b in pg.blocks if not _lies_in(b, suppress_bboxes)]
        suppressed = before - len(pg.blocks)
        if suppressed:
            log.debug(f"Page {pg.page_number}: {suppressed} text block(s) suppressed")

    pg.blocks.extend(new_blocks)
    pg.blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

    log.debug(
        f"Page {pg.page_number}: {tbl_counter} tables, {img_counter} images, "
        f"{title_counter} title blocks"
    )

    return pg, crop_jobs
