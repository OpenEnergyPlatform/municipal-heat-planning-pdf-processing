"""
quantized_embedder.py – On-demand, NF4-quantized Qwen3-VL embedder.

Wraps the shared Qwen3VLEmbedder (scripts/qwen3_vl_embedding.py) WITHOUT editing
it. The shared class is production HPC code (4×H100, bf16, a deliberate
`.to(device)` for replica placement); here we need the opposite: a single 12 GB
Pascal card, the LM backbone loaded in bitsandbytes NF4 (4-bit), the vision
tower left fp32 (image queries must stay full quality), and the whole model
loaded on demand and freed again after every request so it never sits resident
in VRAM on a shared server.

NF4 is chosen over 8-bit because bitsandbytes LLM.int8() requires compute
capability >= 7.5 (Turing+); the TITAN X (Pascal) cards are CC 6.1. NF4 requires
only CC >= 6.0.

Author: Felix Vossel
"""
from __future__ import annotations

import gc
import logging
import threading
from contextlib import contextmanager
from typing import Optional

import torch
import torch.nn.functional as F
from transformers import BitsAndBytesConfig

# Reuse everything from the shared embedder except the two spots that are
# incompatible with a quantized, on-demand load (see class docstring).
from scripts.qwen3_vl_embedding import (
    Qwen3VLEmbedder,
    Qwen3VLForEmbedding,
    MAX_LENGTH,
    MIN_PIXELS,
    MAX_PIXELS,
    MAX_TOTAL_PIXELS,
    FPS,
    MAX_FRAMES,
)
from transformers.models.qwen3_vl.processing_qwen3_vl import Qwen3VLProcessor

log = logging.getLogger(__name__)


class QuantizedQwen3VLEmbedder(Qwen3VLEmbedder):
    """
    NF4-quantized variant of Qwen3VLEmbedder for 12 GB Pascal cards.

    Overrides only __init__ (quantized load, no `.to(device)`, fp32 vision
    tower) and process() (the pixel_values dtype fix). Every other method —
    format_model_input, _preprocess_inputs, _pooling_last, _truncate_tokens,
    forward — is inherited unchanged, so behaviour matches the parent for the
    text path and the HPC pipeline is entirely untouched.
    """

    def __init__(
        self,
        model_name_or_path: str,
        device: torch.device,
        max_length: int = MAX_LENGTH,
        min_pixels: int = MIN_PIXELS,
        max_pixels: int = MAX_PIXELS,
        total_pixels: int = MAX_TOTAL_PIXELS,
        fps: float = FPS,
        num_frames: int = MAX_FRAMES,
        max_frames: int = MAX_FRAMES,
        default_instruction: str = "Represent the user's input.",
        **kwargs,
    ):
        # --- attribute setup: mirrors Qwen3VLEmbedder.__init__ (qwen3_vl_embedding.py:176-185) ---
        self.device = torch.device(device)
        self.max_length = max_length
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self.total_pixels = total_pixels
        self.fps = fps
        self.num_frames = num_frames
        self.max_frames = max_frames
        self.default_instruction = default_instruction

        # --- quantized load: NF4 LM backbone, fp32 vision tower ---
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,   # Pascal-friendly (no bf16 tensor cores)
            bnb_4bit_use_double_quant=True,
            llm_int8_skip_modules=["visual"],        # keep the vision tower unquantized
        )
        self.model = Qwen3VLForEmbedding.from_pretrained(
            model_name_or_path,
            trust_remote_code=True,
            quantization_config=bnb_config,
            device_map={"": self.device},   # REQUIRED for quantized models instead of .to(device)
            torch_dtype=torch.float16,       # dtype of the unquantized (vision) submodules
            **kwargs,
        )
        # Upcast the (skipped) vision tower to fp32 for image-query quality; the
        # torch_dtype above would otherwise leave it in fp16.
        self.model.visual.to(torch.float32)

        # Compute dtype for LM-path floating inputs. pixel_values are handled
        # separately (fp32) in the overridden process() below.
        self.param_dtype = torch.float16

        self.processor = Qwen3VLProcessor.from_pretrained(
            model_name_or_path, padding_side="right"
        )
        self.model.eval()

    def process(self, inputs, normalize: bool = True) -> torch.Tensor:
        """
        Same as Qwen3VLEmbedder.process, but casts pixel_values to fp32 (for the
        unquantized vision tower) while other floating inputs follow the LM
        compute dtype (fp16). The parent casts *everything* to param_dtype, which
        would send pixel_values into the fp32 tower as fp16 and raise a dtype
        mismatch on image queries.
        """
        conversations = [
            self.format_model_input(
                text=ele.get("text"),
                image=ele.get("image"),
                video=ele.get("video"),
                instruction=ele.get("instruction"),
                fps=ele.get("fps"),
                max_frames=ele.get("max_frames"),
            )
            for ele in inputs
        ]

        processed_inputs = self._preprocess_inputs(conversations)
        dev = self.model.device
        cast: dict = {}
        for k, v in processed_inputs.items():
            if not torch.is_floating_point(v):
                cast[k] = v.to(dev)
            elif k in ("pixel_values", "pixel_values_videos"):
                cast[k] = v.to(device=dev, dtype=torch.float32)
            else:
                cast[k] = v.to(device=dev, dtype=self.param_dtype)

        outputs = self.forward(cast)
        embeddings = self._pooling_last(outputs["last_hidden_state"], outputs["attention_mask"])
        if normalize:
            embeddings = F.normalize(embeddings, p=2, dim=-1)
        return embeddings


# ---------------------------------------------------------------------------
# On-demand load / unload with a process-wide lock
# ---------------------------------------------------------------------------
# One lock serializes ALL embedding work in this process (across Streamlit
# sessions/threads), held for the whole load→embed→unload span, so we never run
# two GPU forwards or two loads at once on the shared box. A single
# threading.Lock suffices because one Streamlit server process hosts all
# sessions; if ever run as multiple worker processes this must become a file
# lock.
_EMBED_LOCK = threading.Lock()

# Keep-warm state (only used when idle_unload_seconds > 0).
_STATE: dict = {"embedder": None, "device": None, "timer": None}


def _pick_gpu() -> int:
    """Return the index of the visible GPU with the most free VRAM right now."""
    n = torch.cuda.device_count()
    if n == 0:
        raise RuntimeError("No CUDA device visible to this process.")
    free = [torch.cuda.mem_get_info(i)[0] for i in range(n)]
    idx = max(range(n), key=lambda i: free[i])
    log.info("Selected GPU cuda:%d (free VRAM: %.1f GB)", idx, free[idx] / 1e9)
    return idx


def _free_current() -> None:
    """Delete the cached embedder and release its VRAM. Caller holds the lock."""
    embedder = _STATE.get("embedder")
    device = _STATE.get("device")
    _STATE["embedder"] = None
    _STATE["device"] = None
    if embedder is not None:
        try:
            del embedder.model
        except Exception:
            pass
        del embedder
    gc.collect()
    if device is not None and torch.cuda.is_available():
        with torch.cuda.device(device):
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    log.info("Embedder unloaded, VRAM freed on %s", device)


def _idle_unload() -> None:
    """Timer callback: unload the warm model after the idle window elapsed."""
    with _EMBED_LOCK:
        _STATE["timer"] = None
        _free_current()


@contextmanager
def load_embedder(
    model_name: str,
    max_length: int,
    timeout_s: float = 300.0,
    idle_unload_seconds: int = 0,
):
    """
    Acquire the process-wide embed lock, ensure the NF4 embedder is loaded on
    the currently-freest GPU, yield it, then either free it immediately
    (strict on-demand, idle_unload_seconds == 0) or keep it warm and schedule an
    idle unload. The lock is held across the whole with-block, so the caller's
    .process() call is serialized against every other session.

    Raises TimeoutError if another session's request does not finish within
    timeout_s.
    """
    if not _EMBED_LOCK.acquire(timeout=timeout_s):
        raise TimeoutError(
            f"Server ausgelastet: {timeout_s:.0f}s auf die vorherige "
            f"Embedding-Anfrage gewartet."
        )
    try:
        # Cancel any pending idle-unload so we reuse the warm model.
        if _STATE["timer"] is not None:
            _STATE["timer"].cancel()
            _STATE["timer"] = None

        if _STATE["embedder"] is None:
            import time
            gpu_idx = _pick_gpu()
            device = torch.device(f"cuda:{gpu_idx}")
            log.info("Loading %s (NF4) onto %s", model_name, device)
            t0 = time.time()
            _STATE["embedder"] = QuantizedQwen3VLEmbedder(
                model_name, device=device, max_length=max_length
            )
            _STATE["device"] = device
            log.info("Embedder loaded in %.1fs on %s", time.time() - t0, device)

        yield _STATE["embedder"]
    finally:
        if idle_unload_seconds and idle_unload_seconds > 0:
            # Keep the model warm; unload it after the idle window.
            timer = threading.Timer(idle_unload_seconds, _idle_unload)
            timer.daemon = True
            _STATE["timer"] = timer
            timer.start()
        else:
            _free_current()
        _EMBED_LOCK.release()


def embed_query(item: dict, model_name: str, max_length: int,
                timeout_s: float = 300.0, idle_unload_seconds: int = 0):
    """
    Convenience: embed a single query item ({"text":...} / {"image":...} /
    both) and return an L2-normalized float32 numpy vector, loading/unloading
    the model on demand.
    """
    with load_embedder(model_name, max_length, timeout_s, idle_unload_seconds) as emb:
        vec = emb.process([item])[0]
        return vec.detach().to(torch.float32).cpu().numpy()
