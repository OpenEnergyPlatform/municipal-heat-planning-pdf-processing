"""
inference_app_smoketest.py – Check that the configured embedding backend
produces usable vectors. Run it on the machine that will serve the app.

    python scripts/inference_app_smoketest.py [--image /path/to/a/table_or_figure.png]
    EMBEDDING_BACKEND=api python scripts/inference_app_smoketest.py

What it asserts is what docpipe.embedding promises and the corpus depends on:
the right dimension, L2-normalized vectors, image and image+text queries that
go through, and a batch that agrees with the same items embedded singly. How
the backend gets there — quantized, resident, over HTTP — is none of this
test's business; whether a particular one gives its VRAM back is checked next
to that implementation.

Exit code 0 = all checks passed; non-zero = a check failed (see printed VERDICT).

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Put the repo root on sys.path so `scripts.*` resolves when run by path.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np

from scripts.inference_app.config import EMBEDDING_BACKEND, EMBEDDING_DIM, EMBEDDING_MODEL
from docpipe.embedding import get_embedder

TEXT_A = "Wärmebedarf der Kommune im Bestand nach Sektoren"
TEXT_B = "Potenziale für Fernwärme und Wärmepumpen im Zielszenario"


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def _vec(v) -> np.ndarray:
    """Whatever the backend returned, as a float32 numpy vector."""
    return np.asarray(v, dtype=np.float32).reshape(-1)


def _report_gpus() -> None:
    """Informational only — an api backend needs no GPU at all."""
    try:
        import torch
    except ImportError:
        print("torch not importable (fine for an api backend)")
        return
    print(f"torch {torch.__version__}, CUDA {torch.version.cuda}")
    if not torch.cuda.is_available():
        print("  no CUDA device visible")
        return
    for i in range(torch.cuda.device_count()):
        cap = torch.cuda.get_device_capability(i)
        free = torch.cuda.mem_get_info(i)[0] / 1e6
        print(f"  cuda:{i} {torch.cuda.get_device_name(i)} CC {cap[0]}.{cap[1]} "
              f"free={free:.0f} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="Path to a real extracted table/figure PNG for the VL test")
    args = ap.parse_args()

    failures: list[str] = []

    # 1) Environment ----------------------------------------------------------
    print("=== 1. Environment ===")
    print(f"EMBEDDING_BACKEND={EMBEDDING_BACKEND}")
    print(f"EMBEDDING_MODEL={EMBEDDING_MODEL}  EMBEDDING_DIM={EMBEDDING_DIM}")
    _report_gpus()

    # 2) Resolve the backend --------------------------------------------------
    print("\n=== 2. Backend ===")
    try:
        embedder = get_embedder()
    except Exception as e:
        print(f"FAIL: get_embedder() raised: {e}")
        return 2
    print(f"{type(embedder).__module__}.{type(embedder).__name__}")

    # 3) Text embed -----------------------------------------------------------
    print("\n=== 3. Text embed ===")
    t0 = time.time()
    try:
        text_a = _vec(embedder.embed_one({"text": TEXT_A}))
        text_b = _vec(embedder.embed_one({"text": TEXT_B}))
    except Exception as e:
        print(f"FAIL: text embed raised: {e}")
        return 2
    norm = float(np.linalg.norm(text_a))
    print(f"shape={text_a.shape}, ||v||={norm:.4f}, cos(A,B)={_cos(text_a, text_b):.4f}, "
          f"{time.time() - t0:.1f}s for two")
    if text_a.shape != (EMBEDDING_DIM,):
        failures.append(f"text embedding shape {text_a.shape} != ({EMBEDDING_DIM},)")
    if abs(norm - 1.0) > 1e-2:
        failures.append(f"text embedding not L2-normalized (||v||={norm:.4f})")
    if _cos(text_a, text_b) > 0.999:
        failures.append("two different texts embed to the same vector")

    # 4) Image embed ----------------------------------------------------------
    if args.image:
        print("\n=== 4. Image embed (VL) ===")
        try:
            img_vec = _vec(embedder.embed_one({"text": "", "image": args.image}))
            print(f"shape={img_vec.shape}, ||v||={float(np.linalg.norm(img_vec)):.4f}")
            if img_vec.shape != (EMBEDDING_DIM,):
                failures.append(f"image embedding shape {img_vec.shape} != ({EMBEDDING_DIM},)")
        except Exception as e:
            failures.append(f"image embed raised: {e}")
            print(f"FAIL: image embed raised: {e}")

        # 5) Image + text combined -------------------------------------------
        print("\n=== 5. Image + text embed ===")
        try:
            combo = _vec(embedder.embed_one({"text": TEXT_A, "image": args.image}))
            print(f"shape={combo.shape}, ||v||={float(np.linalg.norm(combo)):.4f}")
            if combo.shape != (EMBEDDING_DIM,):
                failures.append(f"image+text shape {combo.shape} != ({EMBEDDING_DIM},)")
        except Exception as e:
            failures.append(f"image+text embed raised: {e}")
            print(f"FAIL: image+text embed raised: {e}")
    else:
        print("\n=== 4/5. Image tests SKIPPED (pass --image to enable) ===")

    # 6) Batch consistency ----------------------------------------------------
    # A batch that disagrees with single calls means padding or pooling leaks
    # between items — the corpus was embedded in batches, the query is not.
    print("\n=== 6. Batch consistency ===")
    try:
        batch = [_vec(v) for v in embedder.embed(
            [{"text": TEXT_A}, {"text": TEXT_B}, {"text": TEXT_A}, {"text": TEXT_B}])]
        c = _cos(text_a, batch[0])
        print(f"cos(single A, batched A)={c:.4f}")
        if c < 0.999:
            failures.append(f"batch inconsistency: cos={c:.4f} < 0.999")
        if _cos(batch[0], batch[2]) < 0.9999:
            failures.append("the same text twice in one batch gave different vectors")
    except Exception as e:
        failures.append(f"batch embed raised: {e}")
        print(f"FAIL: batch embed raised: {e}")

    # Verdict -----------------------------------------------------------------
    print("\n=== VERDICT ===")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print("SMOKETEST FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
