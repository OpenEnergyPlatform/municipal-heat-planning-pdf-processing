"""
vllm_embedding.py – Embedding backend on vLLM's pooling runner.

Drop-in for :class:`MultiGPUEmbedder`: same ``process(inputs, normalize=True)
-> Tensor``. What changes is who schedules the work.

The transformers path hands 32 items to four replicas, joins all four threads,
then writes FAISS and SQLite on the main thread while every GPU idles — and the
per-item preparation (chat template, PNG decode, patchify) runs *inside* those
GPU threads, so four workers contend for one interpreter. Measured on the August
2026 run: ~1.7 s per batch of which the forward is ~0.6 s, and roughly a fifth
of what four H100 can do.

vLLM removes all three: continuous batching instead of a barrier, preprocessing
in its own workers, and a scheduler that keeps the devices fed.

The prompt is built by the transformers embedder's own ``format_model_input``
and chat template, so both backends see byte-identical text; only the image
travels differently (vLLM takes the decoded image, the HF path a file:// URL).

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import torch

from .qwen3_vl_embedding import MAX_LENGTH, MAX_PIXELS, MIN_PIXELS

log = logging.getLogger(__name__)


class VllmEmbedder:
    """vLLM pooling runner behind the MultiGPUEmbedder interface."""

    def __init__(
        self,
        model_name_or_path: str,
        *,
        max_length: int = MAX_LENGTH,
        min_pixels: int = MIN_PIXELS,
        max_pixels: int = MAX_PIXELS,
        tensor_parallel_size: Optional[int] = None,
        data_parallel_size: int = 1,
        gpu_memory_utilization: float = 0.85,
        default_instruction: str = "Represent the user's input.",
    ):
        from vllm import LLM
        from transformers.models.qwen3_vl.processing_qwen3_vl import Qwen3VLProcessor

        # Data parallelism would suit an 8B model better — four independent
        # replicas, no all-reduce — but vLLM refuses it in a single process
        # ("not supported for single-process usage and may hang"); it needs the
        # multi-process launcher or a served instance. Tensor parallelism is the
        # in-process option, and its all-reduce traffic makes this a floor for
        # what vLLM can do here, not a ceiling.
        if tensor_parallel_size is None:
            tensor_parallel_size = max(1, torch.cuda.device_count() // data_parallel_size)

        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self.default_instruction = default_instruction

        log.info("vLLM pooling runner: dp=%d tp=%d max_len=%d",
                 data_parallel_size, tensor_parallel_size, max_length)

        # convert="embed" wraps the generation checkpoint
        # (architectures: Qwen3VLForConditionalGeneration) via
        # as_embedding_model. LAST reproduces _pooling_last; the L2 step is left
        # to process(), which normalises anyway — one less field whose name
        # differs between vLLM versions.
        self.llm = LLM(
            model=model_name_or_path,
            runner="pooling",
            convert="embed",
            pooler_config={"pooling_type": "LAST"},
            max_model_len=max_length,
            tensor_parallel_size=tensor_parallel_size,
            data_parallel_size=data_parallel_size,
            gpu_memory_utilization=gpu_memory_utilization,
            trust_remote_code=True,
            mm_processor_kwargs={"min_pixels": min_pixels, "max_pixels": max_pixels},
        )
        self.processor = Qwen3VLProcessor.from_pretrained(
            model_name_or_path, padding_side="right"
        )

    # ------------------------------------------------------------------
    # Prompt construction — must match the transformers path token for token
    # ------------------------------------------------------------------

    def _conversation(self, item: dict[str, Any]) -> list[dict]:
        """The same structure format_model_input builds, without the file:// URL."""
        import unicodedata

        instruction = (item.get("instruction") or self.default_instruction).strip()
        if instruction and not unicodedata.category(instruction[-1]).startswith("P"):
            instruction += "."

        content: list[dict] = []
        if item.get("image"):
            content.append({"type": "image"})
        if item.get("text"):
            content.append({"type": "text", "text": item["text"]})
        if not content:
            content.append({"type": "text", "text": "NULL"})

        return [
            {"role": "system", "content": [{"type": "text", "text": instruction}]},
            {"role": "user", "content": content},
        ]

    def _to_prompt(self, item: dict[str, Any]) -> dict:
        text = self.processor.apply_chat_template(
            [self._conversation(item)], add_generation_prompt=True, tokenize=False
        )
        if isinstance(text, list):
            text = text[0]

        prompt: dict[str, Any] = {"prompt": text}
        if item.get("image"):
            from PIL import Image
            prompt["multi_modal_data"] = {"image": Image.open(item["image"]).convert("RGB")}
        return prompt

    # ------------------------------------------------------------------

    def process(self, inputs: list[dict[str, Any]], normalize: bool = True) -> torch.Tensor:
        """
        Embed *inputs* — dicts with 'text' and optionally 'image' — into a
        (len(inputs), hidden_dim) CPU tensor.

        Hand it everything at once: vLLM's scheduler batches better than any
        split we could impose, which is the point of the exercise.
        """
        if not inputs:
            return torch.empty((0, 0))

        outs = self.llm.embed([self._to_prompt(i) for i in inputs], use_tqdm=False)
        vecs = torch.tensor([o.outputs.embedding for o in outs], dtype=torch.float32)

        if not normalize:
            return vecs
        # The pooler already normalises; this is a cheap guard against a pooler
        # config that silently did not take.
        return torch.nn.functional.normalize(vecs, p=2, dim=-1)
