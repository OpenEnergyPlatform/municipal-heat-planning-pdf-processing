"""
crops.py: Cuts a table or image out of its page and writes it as PNG.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

@dataclass
class CropJob:
    """Everything needed to encode and write one detected region as PNG."""
    block_id: str
    out_path: Path
    crop_rgb: np.ndarray


def extract_crop_rgb(
    image: Image.Image,
    bbox_px: list[float],
    mask_bboxes_px: Optional[list[list[float]]] = None,
) -> Optional[np.ndarray]:
    """
    RGB crop of *bbox_px* from *image*, or None if the crop would be
    degenerate. Boxes in *mask_bboxes_px* — which must be in the same
    image-pixel space as *bbox_px*, not crop-local — are whited out.
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


def encode_crop(job: CropJob) -> tuple[str, Path, bytes]:
    """Encodes a crop RGB array as PNG bytes."""
    success, buffer = cv2.imencode(".png", job.crop_rgb[:, :, ::-1])
    if not success:
        raise RuntimeError(f"PNG encoding failed for {job.block_id}")
    return job.block_id, job.out_path, buffer.tobytes()


def write_crop(job: CropJob) -> bool:
    """Encodes one crop as PNG and writes it to disk; True on success."""
    try:
        _, out_path, pngdata = encode_crop(job)
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
