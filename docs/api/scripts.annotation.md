# scripts.annotation

`scripts/annotation/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Layout-annotation workspace: sample pages, correct pre-annotations, evaluate.

Workflow:
  1. sample_and_preannotate.py (GPU) builds a workspace of N random corpus
     pages with PP-DocLayoutV3 pre-annotations under production thresholds.
  2. editor.py (local) serves a web editor to confirm/correct the boxes.
  3. evaluate.py scores the pre-annotations against the confirmed ground truth
     and exports it as COCO for fine-tuning.

[Back to the index](../README.md)
