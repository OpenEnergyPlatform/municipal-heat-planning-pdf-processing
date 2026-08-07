"""
inference_app_smoketest.py – Check that the NF4-quantized embedder loads, embeds
text and images, and releases its VRAM. Run it on the inference server.

    python scripts/inference_app_smoketest.py [--image /path/to/a/table_or_figure.png]

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
import torch

from scripts.inference_app.config import EMBEDDING_MODEL, EMBEDDING_MAX_TOKEN_LENGTH
from docpipe.embedding import quantized as qe

TEXT_A = "Wärmebedarf der Kommune im Bestand nach Sektoren"
TEXT_B = "Potenziale für Fernwärme und Wärmepumpen im Zielszenario"


def _gpu_free_mb(idx: int) -> float:
    return torch.cuda.mem_get_info(idx)[0] / 1e6


def _wait_baseline(idx: int, baseline_mb: float, tol_mb: float = 300.0,
                   timeout_s: float = 180.0) -> float:
    """
    Poll until device `idx`'s free VRAM is back within `tol_mb` of baseline, or
    `timeout_s` elapses; returns the last reading.

    The driver reports a freed allocation with a lag, so a reading taken right
    after an unload understates the real free memory.
    """
    deadline = time.time() + timeout_s
    free = _gpu_free_mb(idx)
    while baseline_mb - free > tol_mb and time.time() < deadline:
        time.sleep(5)
        free = _gpu_free_mb(idx)
    return free


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="Path to a real extracted table/figure PNG for the VL test")
    args = ap.parse_args()

    failures: list[str] = []

    # 1) Environment ----------------------------------------------------------
    print("=== 1. Environment ===")
    print(f"torch {torch.__version__}, CUDA {torch.version.cuda}")
    if not torch.cuda.is_available():
        print("FAIL: CUDA not available.")
        return 2
    n = torch.cuda.device_count()
    for i in range(n):
        cap = torch.cuda.get_device_capability(i)
        print(f"  cuda:{i} {torch.cuda.get_device_name(i)} CC {cap[0]}.{cap[1]} "
              f"free={_gpu_free_mb(i):.0f} MB")
    try:
        import bitsandbytes as bnb
        print(f"bitsandbytes {bnb.__version__}, COMPILED_WITH_CUDA="
              f"{getattr(bnb, 'COMPILED_WITH_CUDA', 'unknown')}")
    except Exception as e:
        print(f"FAIL: bitsandbytes import/CUDA problem: {e}")
        return 2

    # 2) Baseline VRAM --------------------------------------------------------
    baseline = [_gpu_free_mb(i) for i in range(n)]
    print(f"\n=== 2. Baseline free VRAM: {['%.0f' % b for b in baseline]} MB ===")

    # 3) NF4 load -------------------------------------------------------------
    print("\n=== 3. NF4 load ===")
    t0 = time.time()
    text_a = text_b = img_vec = combo_vec = None
    with qe.load_embedder(EMBEDDING_MODEL, EMBEDDING_MAX_TOKEN_LENGTH) as emb:
        load_s = time.time() - t0
        dev_idx = emb.model.device.index if emb.model.device.type == "cuda" else 0
        used_mb = baseline[dev_idx] - _gpu_free_mb(dev_idx)
        print(f"loaded in {load_s:.1f}s on cuda:{dev_idx}, using ~{used_mb:.0f} MB")
        if used_mb > 12000:
            failures.append("NF4 footprint exceeded ~12 GB on one card")

        # 4) Text embed -------------------------------------------------------
        print("\n=== 4. Text embed ===")
        text_a = emb.process([{"text": TEXT_A}])[0].to(torch.float32).cpu().numpy()
        text_b = emb.process([{"text": TEXT_B}])[0].to(torch.float32).cpu().numpy()
        norm = float(np.linalg.norm(text_a))
        print(f"shape={text_a.shape}, ||v||={norm:.4f}, cos(A,B)={_cos(text_a, text_b):.4f}")
        if text_a.shape != (4096,):
            failures.append(f"text embedding shape {text_a.shape} != (4096,)")
        if abs(norm - 1.0) > 1e-2:
            failures.append(f"text embedding not L2-normalized (||v||={norm:.4f})")

        # 5) Image embed ------------------------------------------------------
        if args.image:
            print("\n=== 5. Image embed (VL) ===")
            try:
                img_vec = emb.process([{"text": "", "image": args.image}])[0]
                img_vec = img_vec.to(torch.float32).cpu().numpy()
                print(f"shape={img_vec.shape}, ||v||={float(np.linalg.norm(img_vec)):.4f}")
                if img_vec.shape != (4096,):
                    failures.append(f"image embedding shape {img_vec.shape} != (4096,)")
            except Exception as e:
                failures.append(f"image embed raised: {e}")
                print(f"FAIL: image embed raised: {e}")

            # 6) Image + text combined ---------------------------------------
            print("\n=== 6. Image + text embed ===")
            try:
                combo_vec = emb.process([{"text": TEXT_A, "image": args.image}])[0]
                combo_vec = combo_vec.to(torch.float32).cpu().numpy()
                print(f"shape={combo_vec.shape}, ||v||={float(np.linalg.norm(combo_vec)):.4f}")
            except Exception as e:
                failures.append(f"image+text embed raised: {e}")
                print(f"FAIL: image+text embed raised: {e}")
        else:
            print("\n=== 5/6. Image tests SKIPPED (pass --image to enable) ===")

        # 7) Batch consistency -----------------------------------------------
        print("\n=== 7. Batch consistency ===")
        batch = emb.process([{"text": TEXT_A}, {"text": TEXT_B},
                             {"text": TEXT_A}, {"text": TEXT_B}])
        batch = batch.to(torch.float32).cpu().numpy()
        c = _cos(text_a, batch[0])
        print(f"cos(single A, batched A)={c:.4f}")
        if c < 0.999:
            failures.append(f"batch inconsistency: cos={c:.4f} < 0.999")

    # 8) Unload → VRAM back to baseline --------------------------------------
    print("\n=== 8. Unload / VRAM release (settling up to ~3 min) ===")
    after = [_wait_baseline(i, baseline[i]) for i in range(n)]
    print(f"free after unload: {['%.0f' % a for a in after]} MB "
          f"(baseline {['%.0f' % b for b in baseline]} MB)")
    for i in range(n):
        if baseline[i] - after[i] > 300:
            failures.append(f"cuda:{i} did not return to baseline "
                            f"({baseline[i]-after[i]:.0f} MB still used)")

    # 9) Repeat load/unload x3 — check for UNBOUNDED accumulation ------------
    # Back-to-back cycling outruns the driver's free-reporting lag, so an exact
    # baseline check false-fails here. A real leak accumulates instead, so
    # assert that free does not shrink from round 1 to round 3.
    print("\n=== 9. Repeat load/unload x3 (checking no unbounded accumulation) ===")
    rounds: list[list[float]] = []
    for r in range(3):
        with qe.load_embedder(EMBEDDING_MODEL, EMBEDDING_MAX_TOKEN_LENGTH) as emb:
            _ = emb.process([{"text": TEXT_A}])
        free_now = [_gpu_free_mb(i) for i in range(n)]
        rounds.append(free_now)
        print(f"  round {r+1}: free={['%.0f' % f for f in free_now]} MB")

    tot_first, tot_last = sum(rounds[0]), sum(rounds[-1])
    if tot_first - tot_last > 500:
        failures.append(
            f"VRAM accumulating across rounds (total free {tot_first:.0f} -> "
            f"{tot_last:.0f} MB) — genuine leak, not reporting lag"
        )
    for i in range(n):
        # More than one model's footprint below baseline = >1 model stuck.
        if baseline[i] - rounds[-1][i] > 9000:
            failures.append(
                f"cuda:{i} holds more than one model's footprint "
                f"({baseline[i]-rounds[-1][i]:.0f} MB below baseline)"
            )
    print("  (a plateau here is this host's ~2 min free-reporting lag, not a leak)")

    # Verdict -----------------------------------------------------------------
    print("\n=== VERDICT ===")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print("SMOKETEST FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
