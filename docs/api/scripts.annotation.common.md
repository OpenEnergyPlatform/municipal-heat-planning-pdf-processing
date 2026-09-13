# scripts.annotation.common

`scripts/annotation/common.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Shared class metadata + YOLO label IO for the annotation workspace.

Class ids are the MODEL's ids (0-24, scripts/preprocessing/config.PP_ID2LABEL),
so pre-annotations, corrections and any later fine-tune stay in one id space.

## Functions

### read_labels

```python
def read_labels(path: Path) -> list[dict[str, Any]]
```

Read a YOLO label file into a list of {cls, cx, cy, w, h} boxes.

### write_labels

```python
def write_labels(path: Path, boxes: list[dict[str, Any]]) -> None
```

Write boxes in YOLO format — exactly five columns, nothing else.

### read_meta

```python
def read_meta(path: Path) -> dict[str, Any]
```

Sidecar written by the sampler: document, page, render size.

[Back to the index](../README.md)
