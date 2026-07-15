"""
quantized_embedder.py – On-demand, NF4-quantized Qwen3-VL embedder.

Subclasses the shared Qwen3VLEmbedder (scripts/qwen3_vl_embedding.py) WITHOUT
editing it: the LM backbone is loaded in bitsandbytes NF4, the vision tower left
fp32, and the model is loaded on demand and freed again so it does not sit
resident in VRAM.

NF4 rather than 8-bit is forced by the deployment GPUs: bitsandbytes LLM.int8()
requires a newer compute capability than they have. NF4 does not.

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
    NF4-quantized variant of Qwen3VLEmbedder.

    Overrides only __init__ (quantized load, no `.to(device)`, fp32 vision tower)
    and process() (the pixel_values dtype fix); every other method is inherited
    unchanged.
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
        # --- attribute setup: mirrors Qwen3VLEmbedder.__init__ ---
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
            bnb_4bit_compute_dtype=torch.float16,   # not bf16: unsupported on the deployment GPUs
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
        # torch_dtype above would leave the skipped vision tower in fp16.
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
        compute dtype. The parent casts *everything* to param_dtype, which raises
        a dtype mismatch on image queries here.
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
# sessions/threads), held for the whole load→embed→unload span, so two GPU
# forwards or loads never run at once. A threading.Lock suffices only because one
# server process hosts every session; under multiple worker processes this must
# become a file lock.
_EMBED_LOCK = threading.Lock()

# Keep-warm state (only used when idle_unload_seconds > 0).
_STATE: dict = {"embedder": None, "device": None, "timer": None}


def _pick_gpu() -> int:
    """Index of the visible GPU with the most free VRAM right now."""
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
        model = getattr(embedder, "model", None)
        if model is not None:
            # A model loaded with device_map has accelerate AlignDevicesHooks
            # attached to its submodules; these hold references that keep the
            # (multi-GB) weights alive after a plain `del`, so VRAM is never
            # returned. Strip them first, then drop every reference.
            try:
                from accelerate.hooks import remove_hook_from_module
                remove_hook_from_module(model, recurse=True)
            except Exception:
                pass
            try:
                del embedder.model
            except Exception:
                pass
            del model
        try:
            del embedder.processor
        except Exception:
            pass
        del embedder
    gc.collect()
    if device is not None and torch.cuda.is_available():
        with torch.cuda.device(device):
            torch.cuda.synchronize()
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
    Yield the NF4 embedder, loaded on the currently-freest GPU. On exit it is
    either freed immediately (idle_unload_seconds == 0) or kept warm with an idle
    unload scheduled.

    The process-wide embed lock is held across the whole with-block, so the
    caller's .process() call is serialized against every other session. Raises
    TimeoutError if another session's request does not finish within timeout_s.
    """
    if not _EMBED_LOCK.acquire(timeout=timeout_s):
        raise TimeoutError(
            f"Server ausgelastet: {timeout_s:.0f}s auf die vorherige "
            f"Embedding-Anfrage gewartet."
        )
    try:
        # Cancel any pending idle-unload so the warm model is reused.
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
    Embed a single query item ({"text":...} / {"image":...} / both) and return an
    L2-normalized float32 numpy vector, loading/unloading the model on demand.
    """
    with load_embedder(model_name, max_length, timeout_s, idle_unload_seconds) as emb:
        vec = emb.process([item])[0]
        return vec.detach().to(torch.float32).cpu().numpy()
