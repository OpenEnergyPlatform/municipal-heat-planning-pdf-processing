# scripts.annotation.evaluate

`scripts/annotation/evaluate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Score the pre-annotations against the corrected ground truth, export COCO.

Only CONFIRMED pages (editor_state.json) count: labels/ holds the corrected
truth, preann/ the frozen model output. The correction diff IS the evaluation —
no second annotation pass needed.

Matching: greedy by IoU >= 0.5, highest IoU first, one-to-one. A localization
match with a different class counts as a class confusion (reported separately),
not as TP.

Usage:
    python -m scripts.annotation.evaluate --dir data/annotation/kwp250
    python -m scripts.annotation.evaluate --dir data/annotation/kwp250 --coco gt.json

## Functions

### iou

```python
def iou(a: dict, b: dict) -> float
```

IoU of two normalized YOLO boxes.

### match_page

```python
def match_page(gt: list[dict], pred: list[dict]) -> dict
```

Greedy one-to-one IoU matching of one page.

Returns {"tp": [(cls,)], "confused": [(gt_cls, pred_cls)],
         "fn": [cls], "fp": [cls]}.

### evaluate

```python
def evaluate(root: Path) -> dict
```

Aggregate per-class TP/FP/FN + confusions over all confirmed pages.

### report

```python
def report(stats: dict) -> str
```

### export_coco

```python
def export_coco(root: Path, out: Path) -> int
```

Confirmed ground truth as COCO (absolute pixel boxes) for fine-tuning.

### main

```python
def main() -> None
```

[Back to the index](../README.md)
