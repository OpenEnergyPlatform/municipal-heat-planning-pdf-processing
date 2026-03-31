"""
stage2_layout.py – Layout detection via PP-DocLayoutV3 (HuggingFace Transformers).

IMPROVEMENTS:
  - Non-Maximum Suppression (NMS) removes duplicate/overlapping detections
  - Box expansion for tables/images to capture full content + captions
  - Optimized confidence thresholds for better recall
  - Better handling of edge cases

Model: PaddlePaddle/PP-DocLayoutV3_safetensors

Receives PIL images and open fitz pages directly from Stage 1.

1.  Runs batch object-detection inference using AutoModelForObjectDetection.
2.  Applies NMS to remove overlapping detections of the same class.
3.  For every detected box:
      - SUPPRESS_CLASSES: overlapping text blocks are removed from the page.
      - TABLE_CLASSES / IMAGE_CLASSES: crop saved to images/, Block added.
      - SECTION_TITLE_CLASSES: text extracted via fitz.Page.get_textbox().
      - CAPTION_CLASSES: same text extraction strategy as titles.
      - All other classes: ignored, PyMuPDF text blocks cover this content.
4.  All pending PNG crops are flushed to disk in one pass.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import math
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
    TITLE_EXCLUDE_PREFIXES,
    TABLE_BOX_MARGIN_PT,
    IMAGE_BOX_MARGIN_PT,
    NMS_OVERLAP_THRESHOLD,
)
from .models import Block, PageData

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
class _PageImage:
    """Pairs a PageData record with its PIL image and the originating fitz page."""
    page_data: PageData
    pil_image: Image.Image
    fitz_page: fitz.Page


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


def _pair_pages_with_images(
    pages: list[PageData],
    pil_images: list[Image.Image],
    fitz_pages: list[fitz.Page],
) -> list[_PageImage]:
    """
    Zips PageData, PIL images, and fitz pages into _PageImage records.

    All three lists must be in the same order, as guaranteed by Stage 1.
    Non-RGB PIL images are converted to RGB defensively.
    """
    if not (len(pages) == len(pil_images) == len(fitz_pages)):
        raise ValueError(
            f"List length mismatch: {len(pages)} PageData, "
            f"{len(pil_images)} PIL images, {len(fitz_pages)} fitz pages"
        )
    paired = []
    for pg, pil, fp in zip(pages, pil_images, fitz_pages):
        img = pil if pil.mode == "RGB" else pil.convert("RGB")
        paired.append(_PageImage(page_data=pg, pil_image=img, fitz_page=fp))
    log.info(f"Stage 2: {len(paired)} pages paired")
    return paired


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


def _run_batch_inference(
    page_images: list[_PageImage],
    processor,
    model,
    device: str,
    batch_size: int,
) -> list[list[_Detection]]:
    """
    Runs PP-DocLayoutV3 inference in batches and returns per-page detections.

    The global PP_GLOBAL_MIN_CONF pre-filter is applied first; per-class
    thresholds from PP_CLASS_THRESHOLDS are applied afterwards.
    NMS is applied per-page to remove overlapping detections.
    """
    all_detections: list[list[_Detection]] = []
    total     = len(page_images)
    n_batches = math.ceil(total / batch_size)

    for b_idx in range(n_batches):
        start  = b_idx * batch_size
        end    = min(start + batch_size, total)
        batch  = page_images[start:end]
        images = [pi.pil_image for pi in batch]

        log.info(
            f"Stage 2: batch {b_idx + 1}/{n_batches} "
            f"(pages {batch[0].page_data.page_number}–{batch[-1].page_data.page_number})"
        )

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
            
            # Apply NMS per page
            dets = _apply_nms(dets, NMS_OVERLAP_THRESHOLD)
            all_detections.append(dets)

    return all_detections


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


def _extract_crop_rgb(image: Image.Image, bbox_px: list[float]) -> Optional[np.ndarray]:
    """
    Extracts an RGB crop from a PIL image.

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
    return np.array(crop.convert("RGB"))


def _encode_crop(job: _CropJob) -> tuple[str, Path, bytes]:
    """Encodes a crop RGB array as PNG bytes."""
    success, buffer = cv2.imencode(".png", job.crop_rgb[:, :, ::-1])
    if not success:
        raise RuntimeError(f"PNG encoding failed for {job.block_id}")
    return job.block_id, job.out_path, buffer.tobytes()


def _flush_crops(
    buffers: list[tuple[str, Path, bytes]],
    images_dir: Path,
) -> int:
    """Writes all crop buffers to disk and returns the count written."""
    images_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for block_id, out_path, pngdata in buffers:
        try:
            with open(out_path, "wb") as f:
                f.write(pngdata)
            written += 1
        except Exception as e:
            log.error(f"Failed to write {out_path}: {e}")
    return written


def _process_page(
    page_image: _PageImage,
    detections: list[_Detection],
    images_dir: Path,
) -> tuple[PageData, list[_CropJob]]:
    """
    Processes one page through all detection-type branches.

    Returns the updated PageData and a list of crop jobs to be encoded later.
    """
    pg    = page_image.page_data
    img   = page_image.pil_image
    fp    = page_image.fitz_page
    prefix = f"p{pg.page_number - 1}"

    new_blocks: list[Block] = []
    crop_jobs: list[_CropJob] = []
    suppress_bboxes: list[list[float]] = []

    tbl_counter = 0
    img_counter = 0

    for det_idx, det in enumerate(detections):
        label = det.label
        bbox_px = det.bbox_px
        bbox_pt = _bbox_px_to_pt(
            bbox_px,
            img.width, img.height,
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
                _vertical_overlap_fraction(bbox_pt, sb) > (1.0 - 0.2)
                for sb in suppress_bboxes
            )
            if overlaps_same_row:
                log.debug(f"Page {pg.page_number}: title on same row, treating as text")
                continue

            block_id = f"{prefix}_title{det_idx}"
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
            block_id = f"{prefix}_cap{det_idx}"
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
            bbox_px_expanded = _bbox_px_to_pt(
                bbox_pt_expanded,
                pg.width_pt, pg.height_pt,
                img.width, img.height,
            )
            
            crop_rgb = _extract_crop_rgb(page_image.pil_image, bbox_px_expanded)
            if crop_rgb is None:
                log.debug(f"Page {pg.page_number}: table crop degenerate, skipped")
                continue

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
            bbox_px_expanded = _bbox_px_to_pt(
                bbox_pt_expanded,
                pg.width_pt, pg.height_pt,
                img.width, img.height,
            )
            
            crop_rgb = _extract_crop_rgb(page_image.pil_image, bbox_px_expanded)
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
        f"{len([b for b in new_blocks if b.layout_label in SECTION_TITLE_CLASSES])} "
        f"title blocks"
    )

    return pg, crop_jobs


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

        used_caption_ids: set[str] = set()

        for mb in media_blocks:
            mb_center = _bbox_center(mb.bbox)
            best_cap: Optional[Block] = None
            best_dist = float("inf")

            for cap in caption_pool:
                if cap.id in used_caption_ids:
                    continue
                dist = _euclidean_dist(mb_center, _bbox_center(cap.bbox))
                if dist < best_dist:
                    best_cap  = cap
                    best_dist = dist

            if best_cap is None:
                for fb in fallback_pool:
                    if fb.id in used_caption_ids:
                        continue
                    dist = _euclidean_dist(mb_center, _bbox_center(fb.bbox))
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
    pil_images: list[Image.Image],
    fitz_pages: list[fitz.Page],
    output_dir: Path,
    model_tuple,
) -> list[PageData]:
    """
    Runs PP-DocLayoutV3 layout detection on all pages.

    Args:
        pages:        PageData objects from Stage 1.
        pil_images:   In-memory PIL images from Stage 1, same order as pages.
        fitz_pages:   Open fitz.Page objects from Stage 1, same order as pages.
        output_dir:   Root output directory; crop PNGs go into DIR_IMAGES/.
        model_tuple:  (processor, model, device) from load_model().

    Returns:
        Updated PageData list with suppressed text blocks removed, and
        table/image/title blocks added.
    """
    processor, model, device = model_tuple

    log.info(
        f"Stage 2: PP-DocLayoutV3 – {len(pages)} pages | "
        f"batch size: {LAYOUT_BATCH_SIZE} | NMS threshold: {NMS_OVERLAP_THRESHOLD}"
    )

    page_by_number: dict[int, PageData] = {pg.page_number: pg for pg in pages}

    page_images = _pair_pages_with_images(pages, pil_images, fitz_pages)
    if not page_images:
        log.warning("Stage 2: no page images available – skipping inference")
        return pages

    all_detections = _run_batch_inference(
        page_images, processor, model, device, LAYOUT_BATCH_SIZE
    )

    images_dir    = output_dir / DIR_IMAGES
    all_crop_jobs: list[_CropJob] = []

    for page_image, dets in zip(page_images, all_detections):
        try:
            updated_pg, crop_jobs = _process_page(page_image, dets, images_dir)
            page_by_number[updated_pg.page_number] = updated_pg
            all_crop_jobs.extend(crop_jobs)
        except Exception as e:
            log.error(
                f"Page {page_image.page_data.page_number} processing failed: {e}",
                exc_info=True,
            )

    updated_pages = [page_by_number[pg.page_number] for pg in pages]
    updated_pages = resolve_captions(updated_pages)

    buffers: list[tuple[str, Path, bytes]] = []
    for job in all_crop_jobs:
        try:
            buffers.append(_encode_crop(job))
        except Exception as e:
            log.error(f"Crop encoding failed for {job.block_id}: {e}")

    written = _flush_crops(buffers, images_dir)
    log.info(f"Stage 2: {written}/{len(buffers)} crops written")

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