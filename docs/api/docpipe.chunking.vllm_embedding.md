# docpipe.chunking.vllm_embedding

`docpipe/chunking/vllm_embedding.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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

## Classes

### VllmEmbedder

```python
class VllmEmbedder
```

vLLM pooling runner behind the MultiGPUEmbedder interface.

#### VllmEmbedder.\_\_init\_\_

```python
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
)
```

#### VllmEmbedder.process

```python
def process(self, inputs: list[dict[str, Any]], normalize: bool = True) -> torch.Tensor
```

Embed *inputs* — dicts with 'text' and optionally 'image' — into a
(len(inputs), hidden_dim) CPU tensor.

Hand it everything at once: vLLM's scheduler batches better than any
split we could impose, which is the point of the exercise.

[Back to the index](../README.md)
