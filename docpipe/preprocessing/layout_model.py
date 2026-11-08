"""
layout_model.py: The PP-DocLayoutV3 model of Stage 2 and the boxes it
detects.

A detection passes a global confidence filter, then a per-class threshold,
then per-class non-maximum suppression and cross-class suppression among
table and image boxes, so one region never yields two crops.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import torch

from .config import (
    LAYOUT_AUTOCAST,
    PP_CLASS_THRESHOLDS,
    PP_DOCLAYOUT_MODEL_ID,
    PP_GLOBAL_MIN_CONF,
    PP_ID2LABEL,
    TABLE_CLASSES,
    IMAGE_CLASSES,
    NMS_OVERLAP_THRESHOLD,
)

log = logging.getLogger(__name__)

# Classes whose detections produce a saved crop.
MEDIA_LABELS = TABLE_CLASSES | IMAGE_CLASSES


def load_model():
    """
    Returns (processor, model, device), downloading the weights on first run.
    Call once and pass the tuple to detect_layout_all_pages() — reloading per
    PDF re-reads the weights.
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
class Detection:
    """A single post-processed detection box for one page."""
    label: str
    label_id: int
    score: float
    bbox_px: list[float]


def _compute_iou(box_a: list[float], box_b: list[float]) -> float:
    """IoU in [0, 1] of two [x0, y0, x1, y1] boxes in pixel coordinates."""
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


def boxes_intersect(box_a: list[float], box_b: list[float]) -> bool:
    """True if the two [x0, y0, x1, y1] boxes overlap (touching edges excluded)."""
    return not (
        box_a[2] <= box_b[0] or box_b[2] <= box_a[0]
        or box_a[3] <= box_b[1] or box_b[3] <= box_a[1]
    )


def _apply_nms(detections: list[Detection], iou_threshold: float) -> list[Detection]:
    """
    Per-class Non-Maximum Suppression: of two same-class boxes overlapping by
    more than *iou_threshold*, only the higher-confidence one survives.
    iou_threshold >= 1.0 is a no-op.
    """
    if not detections or iou_threshold >= 1.0:
        return detections

    by_class: dict[str, list[Detection]] = {}
    for det in detections:
        if det.label not in by_class:
            by_class[det.label] = []
        by_class[det.label].append(det)

    kept: list[Detection] = []

    for label, class_dets in by_class.items():
        class_dets.sort(key=lambda d: d.score, reverse=True)

        kept_in_class: list[Detection] = []
        for det in class_dets:
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
    detections: list[Detection], iou_threshold: float
) -> list[Detection]:
    """
    Removes a media detection that overlaps a higher-confidence media detection
    of a DIFFERENT class, so one region never yields two crops. Run after
    per-class NMS; the original detection order is preserved.
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


_AUTOCAST_DTYPES = {"bf16": torch.bfloat16, "fp16": torch.float16}


def _autocast_dtype(device: str):
    """The dtype for the detection forward pass, or None to run in fp32."""
    if device != "cuda":
        return None
    return _AUTOCAST_DTYPES.get(LAYOUT_AUTOCAST)


# What post-processing turns into geometry and scores. `out_masks` is by far the
# largest output (batch x 300 queries x 200 x 200) and is only ever thresholded,
# so upcasting it would double the biggest allocation of the stage for nothing.
_GEOMETRY_OUTPUTS = ("logits", "pred_boxes")


def _to_float32(outputs):
    """
    Cast the geometry-bearing outputs back to fp32.

    Post-processing turns `pred_boxes` into pixel coordinates, and bf16 carries
    8 mantissa bits: on a 1700 px page one representable step is several pixels,
    enough to move a crop's edge into the neighbouring text. The matmuls may run
    reduced, the geometry may not.
    """
    for name in _GEOMETRY_OUTPUTS:
        value = outputs.get(name)
        if isinstance(value, torch.Tensor) and value.is_floating_point():
            outputs[name] = value.float()
    return outputs


def model_inputs(processor, images: list):
    """The model's input tensors for *images*, resized and normalized on the
    CPU. Built ahead of the batch in the prefetch thread, so the main thread
    does not wait for it: 0.018 s a page on 8 cores."""
    return processor(images=images, return_tensors="pt")


def _reading_order(order_logits: torch.Tensor) -> torch.Tensor:
    """The rank of each query in the model's reading order, per image, as
    the processor's post-processing computes it."""
    scores = torch.sigmoid(order_logits)
    batch, length, _ = scores.shape
    votes = (scores.triu(diagonal=1).sum(dim=1)
             + (1.0 - scores.transpose(1, 2)).tril(diagonal=-1).sum(dim=1))
    pointers = torch.argsort(votes, dim=1)
    order = torch.empty_like(pointers)
    ranks = torch.arange(length, device=pointers.device,
                         dtype=pointers.dtype).expand(batch, -1)
    order.scatter_(1, pointers, ranks)
    return order


def kept_detections(outputs, target_sizes: torch.Tensor,
                     threshold: float) -> list[tuple[list, list, list]]:
    """(scores, labels, boxes) per image, of the queries scoring at least
    *threshold*, in the model's reading order, boxes in the pixels of
    *target_sizes* (height, width): what the processor's
    post_process_object_detection returns for them. It also traces a polygon
    around every box from the model's masks, one at a time on one core,
    0.037 s a page, and Stage 2 never reads a polygon. Returned as Python
    lists, so a page's detections cross from the GPU once."""
    order = _reading_order(outputs.order_logits)
    centers, dims = torch.split(outputs.pred_boxes, 2, dim=-1)
    boxes = torch.cat([centers - 0.5 * dims, centers + 0.5 * dims], dim=-1)
    height, width = target_sizes.unbind(1)
    scale = torch.stack([width, height, width, height], dim=1).to(boxes.device)
    boxes = boxes * scale[:, None, :]
    queries, classes = outputs.logits.shape[1], outputs.logits.shape[2]
    scores, index = torch.topk(torch.sigmoid(outputs.logits).flatten(1), queries, dim=-1)
    labels = index % classes
    index = index // classes
    boxes = boxes.gather(dim=1, index=index.unsqueeze(-1).repeat(1, 1, boxes.shape[-1]))
    order = order.gather(dim=1, index=index)

    kept = []
    for score, label, box, rank in zip(scores, labels, boxes, order):
        keep = score >= threshold
        _, by_rank = torch.sort(rank[keep])
        kept.append((score[keep][by_rank].tolist(), label[keep][by_rank].tolist(),
                     box[keep][by_rank].tolist()))
    return kept


def infer_batch(
    images: list,
    processor,
    model,
    device: str,
    inputs=None,
) -> list[list[Detection]]:
    """
    Detections per input image, with the global pre-filter, per-class
    thresholds, per-class NMS and cross-class media suppression applied.
    Boxes are in the input images' pixel space. *inputs* are the batch's
    `model_inputs` when they were built ahead, or the exception that
    stopped them.
    """
    if inputs is None:
        inputs = model_inputs(processor, images)
    elif isinstance(inputs, BaseException):
        raise inputs
    inputs = {k: v.to(device) for k, v in inputs.items()}

    dtype = _autocast_dtype(device)
    with torch.no_grad():
        if dtype is None:
            outputs = model(**inputs)
        else:
            with torch.autocast("cuda", dtype=dtype):
                outputs = model(**inputs)
            outputs = _to_float32(outputs)

    target_sizes = torch.tensor(
        [[img.size[1], img.size[0]] for img in images],
        device="cpu",
    )
    per_image: list[list[Detection]] = []
    for scores, labels, boxes in kept_detections(outputs, target_sizes,
                                                  PP_GLOBAL_MIN_CONF):
        dets: list[Detection] = []
        for score, lid, box in zip(scores, labels, boxes):
            lid   = int(lid)
            score = float(score)
            label = PP_ID2LABEL.get(lid, "unknown")

            if score < PP_CLASS_THRESHOLDS.get(lid, 0.4):
                continue

            dets.append(Detection(
                label=label,
                label_id=lid,
                score=score,
                bbox_px=[float(v) for v in box],
            ))

        dets = _apply_nms(dets, NMS_OVERLAP_THRESHOLD)
        dets = _suppress_cross_class_media(dets, NMS_OVERLAP_THRESHOLD)
        per_image.append(dets)

    return per_image
