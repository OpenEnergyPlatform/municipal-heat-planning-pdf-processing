"""
inference_app_smoketest.py – Standalone NF4-on-Pascal verification.

Run this on the actual inference server BEFORE wiring up the Streamlit app. Its
whole purpose is to prove that bitsandbytes NF4 quantization of
Qwen3-VL-Embedding-8B's LM backbone (vision tower left fp32) works on the exact
Pascal / CC 6.1 hardware, that image queries survive the fp32-vision / fp16-LM
dtype boundary, and that VRAM is fully released after each on-demand load.

    python scripts/inference_app_smoketest.py [--image /path/to/a/table_or_figure.png]

Exit code 0 = all checks passed; non-zero = a check failed (see the printed
VERDICT). If NF4 does not load on CC 6.1 here, STOP and evaluate the fp16-over-
both-cards fallback before building any UI on top of it.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import torch

from scripts.inference_app.config import EMBEDDING_MODEL, EMBEDDING_MAX_TOKEN_LENGTH
from scripts.inference_app import quantized_embedder as qe

TEXT_A = "Wärmebedarf der Kommune im Bestand nach Sektoren"
TEXT_B = "Potenziale für Fernwärme und Wärmepumpen im Zielszenario"


def _gpu_free_mb(idx: int) -> float:
    return torch.cuda.mem_get_info(idx)[0] / 1e6


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="Path to a real extracted table/figure PNG for the VL test")
    args = ap.parse_args()

    failures: list[str] = []

    # 1) Environment sanity ---------------------------------------------------
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

        # 5) Image embed (the fp32-vision / fp16-LM dtype boundary) -----------
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
    print("\n=== 8. Unload / VRAM release ===")
    after = [_gpu_free_mb(i) for i in range(n)]
    print(f"free after unload: {['%.0f' % a for a in after]} MB "
          f"(baseline {['%.0f' % b for b in baseline]} MB)")
    for i in range(n):
        if baseline[i] - after[i] > 300:  # >300 MB not reclaimed = leak
            failures.append(f"cuda:{i} did not return to baseline "
                            f"({baseline[i]-after[i]:.0f} MB still used)")

    # 9) Repeat load/unload + concurrency ------------------------------------
    print("\n=== 9. Repeat load/unload x3 ===")
    for r in range(3):
        with qe.load_embedder(EMBEDDING_MODEL, EMBEDDING_MAX_TOKEN_LENGTH) as emb:
            _ = emb.process([{"text": TEXT_A}])
        free_now = [_gpu_free_mb(i) for i in range(n)]
        print(f"  round {r+1}: free={['%.0f' % f for f in free_now]} MB")
        for i in range(n):
            if baseline[i] - free_now[i] > 300:
                failures.append(f"leak after round {r+1} on cuda:{i}")

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
