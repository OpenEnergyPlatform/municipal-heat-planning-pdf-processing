"""Build an annotation workspace: N random corpus pages, pre-annotated.

Runs where corpus + GPU live (HPC). Pages are sampled uniformly over all pages
of all current documents with a fixed seed, rendered once, and pre-annotated by
PP-DocLayoutV3 through the SAME post-processing the production pipeline uses
(global filter, per-class thresholds, NMS, cross-class media suppression) — so
correcting these boxes measures exactly the production error rate.

Workspace layout (editor.py compatible):
    <out>/images/<stem>.png    rendered page
    <out>/labels/<stem>.txt    YOLO labels, model class ids — the working copy
    <out>/preann/<stem>.txt    frozen copy of the pre-annotation (for evaluate.py)
    <out>/preds/<stem>.json    per-box confidence, parallel to preann
    <out>/meta/<stem>.json     document id/filename, 1-based page, render size

Usage:
    python -m scripts.annotation.sample_and_preannotate \
        --db data/KWP.db --pdf-dir data/pdf --out data/annotation/kwp250 --n 250
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
from pathlib import Path

import fitz

from scripts.preprocessing.stage1_extract import _render_page_to_pil
from scripts.preprocessing.stage2_layout import load_model, _infer_batch

log = logging.getLogger(__name__)

RENDER_DPI = 200          # legible for annotation; the model resizes to 800x800 anyway


def sample_pages(db_path: Path, n: int, seed: int) -> list[tuple[int, str, int]]:
    """Uniform sample of (document_id, filename, 1-based page) over the corpus."""
    conn = sqlite3.connect(db_path)
    docs = conn.execute(
        "SELECT id, filename, num_pages FROM Documents WHERE is_current = 1"
    ).fetchall()
    conn.close()
    population = [(doc_id, fn, page)
                  for doc_id, fn, num_pages in docs
                  for page in range(1, (num_pages or 0) + 1)]
    rng = random.Random(seed)
    return sorted(rng.sample(population, min(n, len(population))))


def run(db_path: Path, pdf_dir: Path, out: Path, n: int, seed: int,
        batch_size: int) -> None:
    pages = sample_pages(db_path, n, seed)
    log.info("Sampled %d pages from %d candidate documents (seed %d)",
             len(pages), len({p[0] for p in pages}), seed)

    for sub in ("images", "labels", "preann", "preds", "meta"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    processor, model, device = load_model()

    batch: list[tuple[str, object]] = []

    def flush() -> None:
        if not batch:
            return
        detections = _infer_batch([img for _, img in batch], processor, model, device)
        for (stem, img), dets in zip(batch, detections):
            w, h = img.size
            lines = []
            confs = []
            for d in dets:
                x0, y0, x1, y1 = d.bbox_px
                cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
                bw, bh = (x1 - x0) / w, (y1 - y0) / h
                lines.append(f"{d.label_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
                confs.append(round(d.score, 4))
            text = "\n".join(lines) + ("\n" if lines else "")
            (out / "labels" / f"{stem}.txt").write_text(text, encoding="utf-8")
            (out / "preann" / f"{stem}.txt").write_text(text, encoding="utf-8")
            (out / "preds" / f"{stem}.json").write_text(
                json.dumps({"conf": confs}, indent=2) + "\n", encoding="utf-8")
        batch.clear()

    skipped = 0
    for doc_id, filename, page_no in pages:
        pdf_path = pdf_dir / filename
        stem = f"d{doc_id:04d}_p{page_no:04d}"
        try:
            with fitz.open(str(pdf_path)) as doc:
                img = _render_page_to_pil(doc.load_page(page_no - 1), RENDER_DPI)
        except Exception as e:
            log.warning("Page not renderable, skipped: %s p%d (%s)", filename, page_no, e)
            skipped += 1
            continue
        img.save(out / "images" / f"{stem}.png")
        (out / "meta" / f"{stem}.json").write_text(
            json.dumps({"document_id": doc_id, "filename": filename,
                        "page_number": page_no, "dpi": RENDER_DPI,
                        "width": img.size[0], "height": img.size[1]}, indent=2) + "\n",
            encoding="utf-8")
        batch.append((stem, img))
        if len(batch) >= batch_size:
            flush()
            log.info("... %s", stem)
    flush()

    log.info("Workspace ready: %s (%d pages, %d skipped)",
             out, len(pages) - skipped, skipped)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--pdf-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=250)
    p.add_argument("--seed", type=int, default=20260803)
    p.add_argument("--batch-size", type=int, default=8)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    run(args.db, args.pdf_dir, args.out, args.n, args.seed, args.batch_size)


if __name__ == "__main__":
    main()
