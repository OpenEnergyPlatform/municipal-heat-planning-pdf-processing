"""The precision the embedding model computes in
(docpipe/chunking/qwen3_vl_embedding.py, docpipe/chunking/embedding.py,
docpipe/embedding/local.py).

Promises:
- a replica computes in bf16 on a GPU AND in fp32 on the CPU, where bf16 is
  slow or missing;
- the data-parallel wrapper gives each replica the precision of its own
  device where none is asked for, AND the one asked for to every replica;
- the index builder (load_embedder) AND the query side (LocalEmbedder) ask
  for none, so without a GPU both compute in fp32.
"""
import pytest
import torch

from docpipe.chunking import qwen3_vl_embedding as qwen
from docpipe.chunking.embedding import load_embedder
from docpipe.embedding.local import LocalEmbedder


class Replica:
    """A replica that notes the device and precision it was built with and
    loads no model."""
    built: list = []

    def __init__(self, model_name_or_path, max_length=None, device=None,
                 torch_dtype=None, **kwargs):
        Replica.built.append((str(device), torch_dtype))

    def process(self, inputs, normalize=True):
        return torch.zeros((len(inputs), 2))


@pytest.fixture
def built(monkeypatch):
    Replica.built = []
    monkeypatch.setattr(qwen, "Qwen3VLEmbedder", Replica)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    monkeypatch.setenv("EMBEDDING_INDEX_BACKEND", "local")
    return Replica.built


def test_a_replica_computes_in_bf16_on_a_gpu_and_in_fp32_on_the_cpu():
    assert qwen.dtype_for("cuda:0") == torch.bfloat16
    assert qwen.dtype_for("cpu") == torch.float32


def test_each_replica_gets_its_devices_precision_unless_one_is_asked_for(built):
    qwen.MultiGPUEmbedder("model", devices=["cpu", "cuda:0"])
    assert built == [("cpu", torch.float32), ("cuda:0", torch.bfloat16)]
    built.clear()
    qwen.MultiGPUEmbedder("model", dtype=torch.float16, devices=["cpu", "cuda:0"])
    assert built == [("cpu", torch.float16), ("cuda:0", torch.float16)]


def test_the_index_and_the_queries_compute_in_fp32_without_a_gpu(built):
    load_embedder("model")
    LocalEmbedder("model").embed([{"text": "Wärmebedarf"}])
    assert built == [("cpu", torch.float32), ("cpu", torch.float32)]
