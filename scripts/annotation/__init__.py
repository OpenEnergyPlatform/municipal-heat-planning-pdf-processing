"""Layout-annotation workspace: sample pages, correct pre-annotations, evaluate.

Workflow:
  1. sample_and_preannotate.py (HPC, GPU) builds a workspace of N random corpus
     pages with PP-DocLayoutV3 pre-annotations under production thresholds.
  2. editor.py (local) serves a web editor to confirm/correct the boxes.
  3. evaluate.py scores the pre-annotations against the confirmed ground truth
     and exports it as COCO for fine-tuning.
"""
