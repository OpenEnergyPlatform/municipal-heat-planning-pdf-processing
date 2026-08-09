"""Score the pre-annotations against the corrected ground truth, export COCO.

Only CONFIRMED pages (editor_state.json) count: labels/ holds the corrected
truth, preann/ the frozen model output. The correction diff IS the evaluation —
no second annotation pass needed.

Matching: greedy by IoU >= 0.5, highest IoU first, one-to-one. A localization
match with a different class counts as a class confusion (reported separately),
not as TP.

Usage:
    python -m scripts.annotation.evaluate --dir data/annotation/kwp250
    python -m scripts.annotation.evaluate --dir data/annotation/kwp250 --coco gt.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.annotation.common import CLASS_NAMES, read_labels, read_meta

IOU_THRESHOLD = 0.5


def iou(a: dict, b: dict) -> float:
    """IoU of two normalized YOLO boxes."""
    ax0, ay0 = a["cx"] - a["w"] / 2, a["cy"] - a["h"] / 2
    ax1, ay1 = a["cx"] + a["w"] / 2, a["cy"] + a["h"] / 2
    bx0, by0 = b["cx"] - b["w"] / 2, b["cy"] - b["h"] / 2
    bx1, by1 = b["cx"] + b["w"] / 2, b["cy"] + b["h"] / 2
    xi0, yi0 = max(ax0, bx0), max(ay0, by0)
    xi1, yi1 = min(ax1, bx1), min(ay1, by1)
    if xi1 <= xi0 or yi1 <= yi0:
        return 0.0
    inter = (xi1 - xi0) * (yi1 - yi0)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def match_page(gt: list[dict], pred: list[dict]) -> dict:
    """Greedy one-to-one IoU matching of one page.

    Returns {"tp": [(cls,)], "confused": [(gt_cls, pred_cls)],
             "fn": [cls], "fp": [cls]}.
    """
    pairs = sorted(
        ((iou(g, p), gi, pi) for gi, g in enumerate(gt) for pi, p in enumerate(pred)),
        key=lambda t: -t[0])
    used_gt: set[int] = set()
    used_pred: set[int] = set()
    tp: list[tuple] = []
    confused: list[tuple] = []
    for score, gi, pi in pairs:
        if score < IOU_THRESHOLD:
            break
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        if gt[gi]["cls"] == pred[pi]["cls"]:
            tp.append((gt[gi]["cls"],))
        else:
            confused.append((gt[gi]["cls"], pred[pi]["cls"]))
    fn = [g["cls"] for gi, g in enumerate(gt) if gi not in used_gt]
    fp = [p["cls"] for pi, p in enumerate(pred) if pi not in used_pred]
    return {"tp": tp, "confused": confused, "fn": fn, "fp": fp}


def evaluate(root: Path) -> dict:
    """Aggregate per-class TP/FP/FN + confusions over all confirmed pages."""
    state_file = root / "editor_state.json"
    confirmed: list[str] = []
    if state_file.is_file():
        confirmed = json.loads(state_file.read_text(encoding="utf-8")).get("confirmed", [])
    stats = {"pages": len(confirmed), "tp": Counter(), "fp": Counter(),
             "fn": Counter(), "confusions": Counter()}
    for stem in confirmed:
        gt = read_labels(root / "labels" / f"{stem}.txt")
        pred = read_labels(root / "preann" / f"{stem}.txt")
        m = match_page(gt, pred)
        for (cls,) in m["tp"]:
            stats["tp"][cls] += 1
        for cls in m["fn"]:
            stats["fn"][cls] += 1
        for cls in m["fp"]:
            stats["fp"][cls] += 1
        for gt_cls, pred_cls in m["confused"]:
            stats["confusions"][(gt_cls, pred_cls)] += 1
            # A confusion is a miss of the true class AND a spurious detection
            # of the predicted one.
            stats["fn"][gt_cls] += 1
            stats["fp"][pred_cls] += 1
    return stats


def report(stats: dict) -> str:
    lines = [f"Confirmed pages: {stats['pages']}", "",
             f"{'class':16s} {'TP':>5s} {'FP':>5s} {'FN':>5s} {'Prec':>6s} {'Rec':>6s} {'F1':>6s}"]
    classes = sorted(set(stats["tp"]) | set(stats["fp"]) | set(stats["fn"]))
    totals = [0, 0, 0]
    for cls in classes:
        tp, fp, fn = stats["tp"][cls], stats["fp"][cls], stats["fn"][cls]
        totals = [totals[0] + tp, totals[1] + fp, totals[2] + fn]
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        name = CLASS_NAMES[cls] if 0 <= cls < len(CLASS_NAMES) else str(cls)
        lines.append(f"{name:16s} {tp:5d} {fp:5d} {fn:5d} {prec:6.2f} {rec:6.2f} {f1:6.2f}")
    tp, fp, fn = totals
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    lines.append(f"{'GESAMT':16s} {tp:5d} {fp:5d} {fn:5d} {prec:6.2f} {rec:6.2f}")
    if stats["confusions"]:
        lines += ["", "Klassen-Verwechslungen (wahr → vorhergesagt):"]
        for (g, p), n in stats["confusions"].most_common(12):
            gn = CLASS_NAMES[g] if 0 <= g < len(CLASS_NAMES) else str(g)
            pn = CLASS_NAMES[p] if 0 <= p < len(CLASS_NAMES) else str(p)
            lines.append(f"  {gn:16s} → {pn:16s} {n:4d}×")
    return "\n".join(lines)


def export_coco(root: Path, out: Path) -> int:
    """Confirmed ground truth as COCO (absolute pixel boxes) for fine-tuning."""
    state_file = root / "editor_state.json"
    confirmed = []
    if state_file.is_file():
        confirmed = json.loads(state_file.read_text(encoding="utf-8")).get("confirmed", [])
    images, annotations = [], []
    ann_id = 1
    for img_id, stem in enumerate(sorted(confirmed), start=1):
        meta = read_meta(root / "meta" / f"{stem}.json")
        w, h = meta.get("width"), meta.get("height")
        if not w or not h:
            continue
        images.append({"id": img_id, "file_name": f"images/{stem}.png",
                       "width": w, "height": h,
                       "document_id": meta.get("document_id"),
                       "page_number": meta.get("page_number")})
        for b in read_labels(root / "labels" / f"{stem}.txt"):
            bw, bh = b["w"] * w, b["h"] * h
            annotations.append({
                "id": ann_id, "image_id": img_id, "category_id": b["cls"],
                "bbox": [round(b["cx"] * w - bw / 2, 2), round(b["cy"] * h - bh / 2, 2),
                         round(bw, 2), round(bh, 2)],
                "area": round(bw * bh, 2), "iscrowd": 0,
            })
            ann_id += 1
    coco = {"images": images, "annotations": annotations,
            "categories": [{"id": i, "name": n} for i, n in enumerate(CLASS_NAMES)]}
    out.write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
    return len(annotations)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--coco", type=Path, default=None,
                   help="Also export the confirmed ground truth as COCO JSON")
    args = p.parse_args()
    stats = evaluate(args.dir)
    print(report(stats))
    if args.coco:
        n = export_coco(args.dir, args.coco)
        print(f"\nCOCO-Export: {n} Boxen → {args.coco}")


if __name__ == "__main__":
    main()
