"""Shared class metadata + YOLO label IO for the annotation workspace.

Class ids are the MODEL's ids (0-24, scripts/preprocessing/config.PP_ID2LABEL),
so pre-annotations, corrections and any later fine-tune stay in one id space.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.preprocessing.config import PP_ID2LABEL

CLASS_NAMES: list[str] = [PP_ID2LABEL[i] for i in sorted(PP_ID2LABEL)]

# Classes offered on the editor's hotkeys (1-9); everything else stays visible
# and editable via the class dropdown.
EDITOR_CLASS_IDS: list[int] = [22, 17, 21, 3, 14, 7, 6, 12, 8]

CLASS_COLORS: dict[int, str] = {
    3:  "#e6194b",   # chart
    6:  "#911eb4",   # doc_title
    7:  "#f58231",   # figure_title
    8:  "#808000",   # footer
    9:  "#9a6324",   # footer_image
    12: "#469990",   # header
    13: "#000075",   # header_image
    14: "#3cb44b",   # image
    17: "#4363d8",   # paragraph_title
    21: "#ffe119",   # table
    22: "#a9a9a9",   # text
}
DEFAULT_COLOR = "#666666"


def read_labels(path: Path) -> list[dict[str, Any]]:
    """Read a YOLO label file into a list of {cls, cx, cy, w, h} boxes."""
    if not path.is_file():
        return []
    boxes: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            boxes.append({"cls": int(parts[0]), "cx": float(parts[1]),
                          "cy": float(parts[2]), "w": float(parts[3]),
                          "h": float(parts[4])})
        except ValueError:
            continue
    return boxes


def write_labels(path: Path, boxes: list[dict[str, Any]]) -> None:
    """Write boxes in YOLO format — exactly five columns, nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for b in boxes:
        vals = [min(1.0, max(0.0, float(b[k]))) for k in ("cx", "cy", "w", "h")]
        if vals[2] <= 0.0 or vals[3] <= 0.0:
            continue
        lines.append(f"{int(b['cls'])} " + " ".join(f"{v:.6f}" for v in vals))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_meta(path: Path) -> dict[str, Any]:
    """Sidecar written by the sampler: document, page, render size."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
