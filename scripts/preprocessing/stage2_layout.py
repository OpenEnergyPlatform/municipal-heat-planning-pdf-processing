"""
stage2_layout.py – Layout detection via PP-DocLayoutV3 (HuggingFace Transformers).

IMPROVEMENTS:
  - Non-Maximum Suppression (NMS) removes duplicate/overlapping detections
  - Box expansion for tables/images to capture full content + captions
  - Optimized confidence thresholds for better recall
  - Better handling of edge cases

Model: PaddlePaddle/PP-DocLayoutV3_safetensors

Receives the open fitz pages from Stage 1 and renders them per batch (so the
whole document's page images are never resident at once), then:

1.  Runs batch object-detection inference using AutoModelForObjectDetection.
2.  Applies per-class NMS, then cross-class suppression between table and
    image/chart boxes over the same region.
3.  For every detected box:
      - SUPPRESS_CLASSES: overlapping text blocks are removed from the page.
      - TABLE_CLASSES / IMAGE_CLASSES: crop saved to images/, Block added.
      - SECTION_TITLE_CLASSES: text extracted via fitz.Page.get_textbox().
      - CAPTION_CLASSES: same text extraction strategy as titles.
      - All other classes: ignored, PyMuPDF text blocks cover this content.
4.  Each crop is encoded and written to disk immediately (per page).

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import fitz
import numpy as np
import torch
from PIL import Image

from .config import (
    DIR_IMAGES,
    LAYOUT_BATCH_SIZE,
    LAYOUT_DETECT_DPI,
    PAGE_RENDER_DPI,
    PP_CLASS_THRESHOLDS,
    PP_DOCLAYOUT_MODEL_ID,
    PP_GLOBAL_MIN_CONF,
    PP_ID2LABEL,
    SUPPRESS_CLASSES,
    TABLE_CLASSES,
    IMAGE_CLASSES,
    CAPTION_CLASSES,
    SECTION_TITLE_CLASSES,
    TEXT_SUPPRESS_OVERLAP,
    CAPTION_MAX_DIST_PT,
    CAPTION_REJECT_ACROSS_TITLE,
    TITLE_EXCLUDE_PREFIXES,
    TITLE_SAME_ROW_OVERLAP_FRACTION,
    TABLE_BOX_MARGIN_PT,
    IMAGE_BOX_MARGIN_PT,
    NMS_OVERLAP_THRESHOLD,
    MASK_FIGURES_IN_TABLE_CROPS,
    FONT_HEADING_ENABLE,
    FONT_HEADING_SIZE_RATIO,
    FONT_HEADING_MIN_CHARS,
    FONT_HEADING_MAX_CHARS,
    FONT_HEADING_ALLCAPS_MIN_CHARS,
)
from .models import Block, PageData
from .stage1_extract import _render_page_to_pil

# Media classes whose detections produce a saved crop; used for cross-class
# suppression so a region detected as both a table and an image/chart does not
# yield two overlapping crops.
MEDIA_LABELS = TABLE_CLASSES | IMAGE_CLASSES

log = logging.getLogger(__name__)


def load_model():
    """
    Downloads (first run) and returns (processor, model, device).

    Call once at pipeline start and pass the tuple to
    detect_layout_all_pages() so the weights are never reloaded between PDFs.
    """
    try:
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
    except ImportError:
        raise ImportError(
            "transformers not installed.\n"
            "  pip install 'transformers>=4.50' torch"
        )

    log.info(f"Loading PP-DocLayoutV3: {PP_DOCLAYOUT_MODEL_ID}")

    processor = AutoImageProcessor.from_pretrained(PP_DOCLAYOUT_MODEL_ID)
    model     = AutoModelForObjectDetection.from_pretrained(PP_DOCLAYOUT_MODEL_ID)
    model.config.id2label = PP_ID2LABEL

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model  = model.to(device)
    model.eval()

    log.info(f"PP-DocLayoutV3 ready on device: {device}")
    return processor, model, device


@dataclass
class _CropJob:
    """Everything needed to encode and write one detected region as PNG."""
    block_id: str
    out_path: Path
    crop_rgb: np.ndarray


@dataclass
class _Detection:
    """A single post-processed detection box for one page."""
    label: str
    label_id: int
    score: float
    bbox_px: list[float]


def _compute_iou(box_a: list[float], box_b: list[float]) -> float:
    """
    Computes Intersection over Union (IoU) between two boxes in pixel coordinates.
    
    Args:
        box_a, box_b: [x0, y0, x1, y1]
    
    Returns:
        IoU value in [0, 1].
    """
    x0_a, y0_a, x1_a, y1_a = box_a
    x0_b, y0_b, x1_b, y1_b = box_b
    
    # Intersection
    xi0 = max(x0_a, x0_b)
    yi0 = max(y0_a, y0_b)
    xi1 = min(x1_a, x1_b)
    yi1 = min(y1_a, y1_b)
    
    if xi1 <= xi0 or yi1 <= yi0:
        return 0.0
    
    inter = (xi1 - xi0) * (yi1 - yi0)
    
    # Union
    area_a = (x1_a - x0_a) * (y1_a - y0_a)
    area_b = (x1_b - x0_b) * (y1_b - y0_b)
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def _boxes_intersect(box_a: list[float], box_b: list[float]) -> bool:
    """True if the two [x0, y0, x1, y1] boxes overlap (touching edges excluded)."""
    return not (
        box_a[2] <= box_b[0] or box_b[2] <= box_a[0]
        or box_a[3] <= box_b[1] or box_b[3] <= box_a[1]
    )


def _apply_nms(detections: list[_Detection], iou_threshold: float) -> list[_Detection]:
    """
    Applies Non-Maximum Suppression to remove overlapping detections.
    
    Keeps detections with highest confidence; removes lower-confidence detections
    that overlap significantly with kept ones. Applies NMS per-class.
    
    Args:
        detections: List of detection objects
        iou_threshold: IoU threshold for suppression (0-1)
    
    Returns:
        Filtered list of detections.
    """
    if not detections or iou_threshold >= 1.0:
        return detections
    
    # Group by class
    by_class: dict[str, list[_Detection]] = {}
    for det in detections:
        if det.label not in by_class:
            by_class[det.label] = []
        by_class[det.label].append(det)
    
    kept: list[_Detection] = []
    
    for label, class_dets in by_class.items():
        # Sort by score descending
        class_dets.sort(key=lambda d: d.score, reverse=True)
        
        kept_in_class: list[_Detection] = []
        for det in class_dets:
            # Check if this detection overlaps significantly with any kept detection
            overlaps_with_kept = False
            for kept_det in kept_in_class:
                iou = _compute_iou(det.bbox_px, kept_det.bbox_px)
                if iou > iou_threshold:
                    overlaps_with_kept = True
                    break
            
            if not overlaps_with_kept:
                kept_in_class.append(det)
        
        kept.extend(kept_in_class)

    return kept


def _suppress_cross_class_media(
    detections: list[_Detection], iou_threshold: float
) -> list[_Detection]:
    """
    Removes a media detection (table/image/chart) that overlaps a
    higher-confidence media detection of a DIFFERENT class.

    Per-class NMS already dedups within a class; this handles the case where
    the model emits e.g. both a 'table' and an 'image' box over the same
    region, which would otherwise produce two crops for one region. The
    original detection order is preserved (only suppressed boxes are dropped).
    """
    if iou_threshold >= 1.0:
        return detections
    media = [d for d in detections if d.label in MEDIA_LABELS]
    if len(media) < 2:
        return detections

    kept_boxes: list[list[float]] = []
    suppressed: set[int] = set()
    for det in sorted(media, key=lambda d: d.score, reverse=True):
        if any(_compute_iou(det.bbox_px, kb) > iou_threshold for kb in kept_boxes):
            suppressed.add(id(det))
        else:
            kept_boxes.append(det.bbox_px)
    return [d for d in detections if id(d) not in suppressed]


def _infer_batch(
    images: list,
    processor,
    model,
    device: str,
) -> list[list[_Detection]]:
    """
    Runs PP-DocLayoutV3 on one batch of page images and returns per-image
    detections (global pre-filter, per-class thresholds, per-class NMS, and
    cross-class media suppression all applied).
    """
    inputs = processor(images=images, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)

    target_sizes = torch.tensor(
        [[img.size[1], img.size[0]] for img in images],
        device="cpu",
    )
    raw_results = processor.post_process_object_detection(
        outputs,
        threshold=PP_GLOBAL_MIN_CONF,
        target_sizes=target_sizes,
    )

    per_image: list[list[_Detection]] = []
    for result in raw_results:
        dets: list[_Detection] = []
        for score_t, label_t, box_t in zip(
            result["scores"], result["labels"], result["boxes"]
        ):
            lid   = int(label_t.item())
            score = float(score_t.item())
            label = PP_ID2LABEL.get(lid, "unknown")

            if score < PP_CLASS_THRESHOLDS.get(lid, 0.4):
                continue

            dets.append(_Detection(
                label=label,
                label_id=lid,
                score=score,
                bbox_px=[float(v) for v in box_t.tolist()],
            ))

        dets = _apply_nms(dets, NMS_OVERLAP_THRESHOLD)
        dets = _suppress_cross_class_media(dets, NMS_OVERLAP_THRESHOLD)
        per_image.append(dets)

    return per_image


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
    Expands a bounding box by the given margins while staying within page bounds.
    
    Args:
        bbox_pt: [x0, y0, x1, y1] in points
        margin_pt: (left, top, right, bottom) in points
        page_w_pt, page_h_pt: Page dimensions in points
    
    Returns:
        Expanded bounding box, clamped to page bounds.
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
    Returns the fraction of *text_bbox* area that is covered by *region_bbox*.

    Asymmetric by design: a small text block fully inside a large region
    yields 1.0, while a large text block that only partially overlaps yields
    a low value.
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


def _vertical_overlap_fraction(bbox_a: list[float], bbox_b: list[float]) -> float:
    """
    Returns the vertical overlap fraction relative to the shorter of the two boxes.

    Used to detect whether a paragraph_title sits on the same row as another
    detected element.
    """
    y0_a, y1_a = bbox_a[1], bbox_a[3]
    y0_b, y1_b = bbox_b[1], bbox_b[3]

    iy0 = max(y0_a, y0_b)
    iy1 = min(y1_a, y1_b)

    if iy1 <= iy0:
        return 0.0

    overlap = iy1 - iy0
    shorter_height = min(y1_a - y0_a, y1_b - y0_b)
    return overlap / shorter_height if shorter_height > 0 else 0.0


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    """Returns the (x, y) center of a bounding box."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _euclidean_dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Returns the Euclidean distance between two 2D points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _text_from_bbox(fp: fitz.Page, bbox_pt: list[float]) -> str:
    """
    Extracts text from a region of a fitz.Page using its bounding box.

    Handles edge cases like empty regions or invalid coordinates.
    """
    try:
        x0, y0, x1, y1 = bbox_pt
        rect = fitz.Rect(x0, y0, x1, y1)

        text = fp.get_text("text", clip=rect).strip()
        return text if text else ""
    except Exception as e:
        log.debug(f"Text extraction from bbox failed: {e}")
        return ""


def _extract_crop_rgb(
    image: Image.Image,
    bbox_px: list[float],
    mask_bboxes_px: Optional[list[list[float]]] = None,
) -> Optional[np.ndarray]:
    """
    Extracts an RGB crop from a PIL image.

    If *mask_bboxes_px* is given (boxes in the same image-pixel space as
    *bbox_px*), the pixels of each box that fall inside the crop are
    overwritten with white (255). This is the semantic pre-masking step that
    erases embedded figures/charts from a table crop before vision inference.

    Returns None if the crop would be degenerate.
    """
    x0, y0, x1, y1 = [int(round(v)) for v in bbox_px]
    w = image.width
    h = image.height

    x0 = max(0, min(x0, w - 1))
    x1 = max(x0 + 1, min(x1, w))
    y0 = max(0, min(y0, h - 1))
    y1 = max(y0 + 1, min(y1, h))

    if x1 <= x0 or y1 <= y0:
        return None

    crop = image.crop((x0, y0, x1, y1))
    arr = np.array(crop.convert("RGB"))

    if mask_bboxes_px:
        ch, cw = arr.shape[:2]
        for mb in mask_bboxes_px:
            mx0, my0, mx1, my1 = [int(round(v)) for v in mb]
            # Translate into crop-local coordinates and clamp to the crop.
            lx0 = max(0, mx0 - x0)
            ly0 = max(0, my0 - y0)
            lx1 = min(cw, mx1 - x0)
            ly1 = min(ch, my1 - y0)
            if lx1 > lx0 and ly1 > ly0:
                arr[ly0:ly1, lx0:lx1] = 255

    return arr


def _encode_crop(job: _CropJob) -> tuple[str, Path, bytes]:
    """Encodes a crop RGB array as PNG bytes."""
    success, buffer = cv2.imencode(".png", job.crop_rgb[:, :, ::-1])
    if not success:
        raise RuntimeError(f"PNG encoding failed for {job.block_id}")
    return job.block_id, job.out_path, buffer.tobytes()


def _write_crop(job: _CropJob) -> bool:
    """
    Encodes one crop as PNG and writes it to disk immediately.

    Encoding and writing per crop (instead of buffering every crop's RGB array
    and every PNG byte-string for the whole document before flushing) keeps the
    peak memory at one crop at a time.
    """
    try:
        _, out_path, pngdata = _encode_crop(job)
    except Exception as e:
        log.error(f"Crop encoding failed for {job.block_id}: {e}")
        return False
    try:
        with open(out_path, "wb") as f:
            f.write(pngdata)
        return True
    except Exception as e:
        log.error(f"Failed to write {out_path}: {e}")
        return False


def _process_page(
    pg: PageData,
    fp: fitz.Page,
    det_w: int,
    det_h: int,
    crop_image: Image.Image,
    detections: list[_Detection],
    images_dir: Path,
) -> tuple[PageData, list[_CropJob]]:
    """
    Processes one page through all detection-type branches.

    Detections are in detection-image pixel coordinates (det_w x det_h); crops
    are extracted from *crop_image*, which may be rendered at a different DPI
    than the detection input.

    Returns the updated PageData and a list of crop jobs to be written later.
    """
    prefix = f"p{pg.page_number - 1}"

    new_blocks: list[Block] = []
    crop_jobs: list[_CropJob] = []
    suppress_bboxes: list[list[float]] = []

    title_counter = 0
    cap_counter   = 0
    tbl_counter   = 0
    img_counter   = 0

    # Figure/chart boxes (detection-pixel space) for semantic pre-masking of
    # any figure embedded in a table crop.
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
            continue

        if label in SECTION_TITLE_CLASSES:
            title_text = _text_from_bbox(fp, bbox_pt)
            if not title_text:
                log.debug(
                    f"Page {pg.page_number}: title block (label={label}) has no text"
                )
                continue

            # Reject titles with excluded prefixes
            if any(title_text.lower().startswith(p) for p in TITLE_EXCLUDE_PREFIXES):
                log.debug(f"Page {pg.page_number}: title rejected (excluded prefix)")
                continue

            # Check for same-row overlap with other elements
            overlaps_same_row = any(
                _vertical_overlap_fraction(bbox_pt, sb)
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
            # Expand bbox for better content capture
            bbox_pt_expanded = _expand_bbox_pt(
                bbox_pt, TABLE_BOX_MARGIN_PT, pg.width_pt, pg.height_pt
            )
            bbox_px_expanded = _bbox_pt_to_px(
                bbox_pt_expanded,
                pg.width_pt, pg.height_pt,
                crop_image.width, crop_image.height,
            )

            # Semantic pre-masking: white out any figure/chart overlapping this
            # table so its lines are not transcribed as phantom table rows.
            mask_boxes_px: list[list[float]] = []
            for fpx in figure_dets_px:
                fpt = _bbox_px_to_pt(fpx, det_w, det_h, pg.width_pt, pg.height_pt)
                if _boxes_intersect(fpt, bbox_pt_expanded):
                    mask_boxes_px.append(_bbox_pt_to_px(
                        fpt, pg.width_pt, pg.height_pt,
                        crop_image.width, crop_image.height,
                    ))

            crop_rgb = _extract_crop_rgb(
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
                # Native PDF text inside the (unexpanded) table box, kept as a
                # QA reference for the downstream vision extraction.
                source_text=(_text_from_bbox(fp, bbox_pt) or None),
            ))
            crop_jobs.append(_CropJob(
                block_id=block_id,
                out_path=out_path,
                crop_rgb=crop_rgb,
            ))
            suppress_bboxes.append(bbox_pt_expanded)
            continue

        if label in IMAGE_CLASSES:
            # Expand bbox for better content capture
            bbox_pt_expanded = _expand_bbox_pt(
                bbox_pt, IMAGE_BOX_MARGIN_PT, pg.width_pt, pg.height_pt
            )
            bbox_px_expanded = _bbox_pt_to_px(
                bbox_pt_expanded,
                pg.width_pt, pg.height_pt,
                crop_image.width, crop_image.height,
            )

            crop_rgb = _extract_crop_rgb(crop_image, bbox_px_expanded)
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
            crop_jobs.append(_CropJob(
                block_id=block_id,
                out_path=out_path,
                crop_rgb=crop_rgb,
            ))
            suppress_bboxes.append(bbox_pt_expanded)
            continue

    if suppress_bboxes:
        before = len(pg.blocks)
        pg.blocks = [
            b for b in pg.blocks
            if b.type != "text" or not any(
                _overlap_fraction(b.bbox, sb) >= TEXT_SUPPRESS_OVERLAP
                for sb in suppress_bboxes
            )
        ]
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
    if any(text.lower().startswith(p) for p in TITLE_EXCLUDE_PREFIXES):
        return False
    # Prose guard: a heading rarely ends in sentence punctuation or contains a
    # sentence boundary — this filters bold/emphasised body lines.
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
    Promotes plain Stage-1 text blocks that look like headings (by font size /
    bold / all-caps) to section titles, so Stage 3 opens a section there.

    Only blocks PP-DocLayout did NOT already classify (layout_label is None)
    are considered, so this acts purely as a recall booster for headings the
    layout model missed. Disabled via FONT_HEADING_ENABLE.
    """
    if not FONT_HEADING_ENABLE:
        return pages

    body = _body_font_size(pages)
    promoted = 0
    for pg in pages:
        # Regions already occupied by other content; a candidate that shares a
        # row (vertically overlaps) one of these is likely an inline label, not
        # a section heading — mirrors the same-row title demotion in
        # _process_page and avoids re-promoting a deliberately demoted title.
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
                _vertical_overlap_fraction(b.bbox, ob)
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


def _title_between(y_a: float, y_b: float, title_ys: list[float]) -> bool:
    """True if any title y-center lies strictly between the two y values."""
    lo, hi = (y_a, y_b) if y_a <= y_b else (y_b, y_a)
    return any(lo < ty < hi for ty in title_ys)


def resolve_captions(pages: list[PageData]) -> list[PageData]:
    """
    Attaches captions to table and image blocks.

    Resolution priority per figure/table block:
      1. Nearest block with layout_label in CAPTION_CLASSES – no distance
         limit since the model classification is already a strong signal.
      2. Nearest plain text block within CAPTION_MAX_DIST_PT as fallback
         when no caption-class block is available.

    The winning caption block's content is written into Block.caption and the
    caption block is removed from the page so it does not appear in section content.
    """
    for pg in pages:
        media_blocks  = [b for b in pg.blocks if b.type in ("table", "image")]
        caption_pool  = [
            b for b in pg.blocks
            if b.layout_label in CAPTION_CLASSES and b.content
        ]
        fallback_pool = [
            b for b in pg.blocks
            if b.type == "text"
            and b.layout_label not in SECTION_TITLE_CLASSES
            and b.layout_label not in CAPTION_CLASSES
            and b.content
        ]

        # Section-heading y-centers act as boundaries: a caption candidate is
        # rejected if a heading lies vertically between it and the media block.
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


def detect_layout_all_pages(
    pages: list[PageData],
    fitz_pages: list[fitz.Page],
    output_dir: Path,
    model_tuple,
) -> list[PageData]:
    """
    Runs PP-DocLayoutV3 layout detection on all pages, rendering per batch.

    Pages are rendered (and crops cut) chunk by chunk of LAYOUT_BATCH_SIZE and
    freed after each chunk, so the whole document's page images are never
    resident at once. Detection input is rendered at LAYOUT_DETECT_DPI and
    crops at PAGE_RENDER_DPI (one render per page when the two are equal).

    Args:
        pages:        PageData objects from Stage 1.
        fitz_pages:   Open fitz.Page objects from Stage 1, same order as pages.
        output_dir:   Root output directory; crop PNGs go into DIR_IMAGES/.
        model_tuple:  (processor, model, device) from load_model().

    Returns:
        Updated PageData list with suppressed text blocks removed, and
        table/image/title blocks added.
    """
    processor, model, device = model_tuple

    if not pages:
        log.warning("Stage 2: no pages – skipping inference")
        return pages
    if len(pages) != len(fitz_pages):
        raise ValueError(
            f"List length mismatch: {len(pages)} PageData, "
            f"{len(fitz_pages)} fitz pages"
        )

    same_dpi = LAYOUT_DETECT_DPI == PAGE_RENDER_DPI
    log.info(
        f"Stage 2: PP-DocLayoutV3 – {len(pages)} pages | batch {LAYOUT_BATCH_SIZE} | "
        f"detect DPI {LAYOUT_DETECT_DPI} | crop DPI {PAGE_RENDER_DPI} | "
        f"NMS {NMS_OVERLAP_THRESHOLD}"
    )

    page_by_number: dict[int, PageData] = {pg.page_number: pg for pg in pages}

    images_dir = output_dir / DIR_IMAGES
    images_dir.mkdir(parents=True, exist_ok=True)

    n         = len(pages)
    n_batches = math.ceil(n / LAYOUT_BATCH_SIZE)
    written     = 0
    total_crops = 0

    for b_idx in range(n_batches):
        start = b_idx * LAYOUT_BATCH_SIZE
        end   = min(start + LAYOUT_BATCH_SIZE, n)
        chunk_pages = pages[start:end]
        chunk_fitz  = fitz_pages[start:end]

        log.info(
            f"Stage 2: batch {b_idx + 1}/{n_batches} "
            f"(pages {chunk_pages[0].page_number}–{chunk_pages[-1].page_number})"
        )

        # Render this chunk's detection images; skip pages that fail to render.
        rendered: list[tuple[PageData, fitz.Page, Image.Image]] = []
        for pg, fp in zip(chunk_pages, chunk_fitz):
            try:
                rendered.append((pg, fp, _render_page_to_pil(fp, LAYOUT_DETECT_DPI)))
            except Exception as e:
                log.error(f"Page {pg.page_number}: render failed, skipping detection: {e}")
        if not rendered:
            continue

        det_images = [r[2] for r in rendered]
        try:
            dets_per_page = _infer_batch(det_images, processor, model, device)
        except Exception as e:
            log.error(f"Stage 2: inference failed for batch {b_idx + 1}: {e}", exc_info=True)
            del det_images, rendered
            continue

        for (pg, fp, det_img), dets in zip(rendered, dets_per_page):
            try:
                crop_img = det_img if same_dpi else _render_page_to_pil(fp, PAGE_RENDER_DPI)
                updated_pg, crop_jobs = _process_page(
                    pg, fp, det_img.width, det_img.height, crop_img, dets, images_dir
                )
                page_by_number[updated_pg.page_number] = updated_pg
                # Encode + write each crop right away and drop its RGB array.
                for job in crop_jobs:
                    total_crops += 1
                    if _write_crop(job):
                        written += 1
            except Exception as e:
                log.error(
                    f"Page {pg.page_number} processing failed: {e}",
                    exc_info=True,
                )

        # Free this chunk's rendered images before rendering the next.
        del det_images, rendered

    updated_pages = [page_by_number[pg.page_number] for pg in pages]
    updated_pages = promote_headings_by_font(updated_pages)
    updated_pages = resolve_captions(updated_pages)

    log.info(f"Stage 2: {written}/{total_crops} crops written")

    total_tables = sum(sum(1 for b in pg.blocks if b.type == "table") for pg in updated_pages)
    total_images = sum(sum(1 for b in pg.blocks if b.type == "image") for pg in updated_pages)
    total_titles = sum(
        sum(1 for b in pg.blocks if b.layout_label in SECTION_TITLE_CLASSES)
        for pg in updated_pages
    )
    log.info(
        f"Stage 2: done – {total_tables} tables | {total_images} images | "
        f"{total_titles} title blocks"
    )

    return updated_pages