# scripts.annotation.sample_and_preannotate

`scripts/annotation/sample_and_preannotate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Build an annotation workspace: N random corpus pages, pre-annotated.

Runs where corpus + GPU live. Pages are sampled uniformly over all pages
of all current documents with a fixed seed, rendered once, and pre-annotated by
PP-DocLayoutV3 through the SAME post-processing the production pipeline uses
(global filter, per-class thresholds, NMS, cross-class media suppression) — so
correcting these boxes measures exactly the production error rate.

Workspace layout (editor.py compatible):
    \<out>/images/\<stem>.png    rendered page
    \<out>/labels/\<stem>.txt    YOLO labels, model class ids — the working copy
    \<out>/preann/\<stem>.txt    frozen copy of the pre-annotation (for evaluate.py)
    \<out>/preds/\<stem>.json    per-box confidence, parallel to preann
    \<out>/meta/\<stem>.json     document id/filename, 1-based page, render size

Usage:
    python -m scripts.annotation.sample_and_preannotate         --db data/KWP.db --pdf-dir data/pdf --out data/annotation/kwp250 --n 250

## Functions

### sample_pages

```python
def sample_pages(db_path: Path, n: int, seed: int) -> list[tuple[int, str, int]]
```

Uniform sample of (document_id, filename, 1-based page) over the corpus.

### run

```python
def run(db_path: Path, pdf_dir: Path, out: Path, n: int, seed: int,
        batch_size: int) -> None
```

### main

```python
def main() -> None
```

[Back to the index](../README.md)
