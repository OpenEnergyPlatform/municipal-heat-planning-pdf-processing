"""
config.py – Where embeddings come from.

EMBEDDING_BACKEND picks one:

  local                 the model runs in this process and stays resident
                        (needs GPUs; this is what a batch run wants)
  api                   an OpenAI-compatible /v1/embeddings endpoint
  package.module:Klasse an implementation supplied by the deployment

The model name and the length/batch limits below are shared: an external
backend is free to read them, and should, so that one deployment does not
silently embed at a different length than the corpus was built with.

Author: Felix Vossel
"""
import os

BACKEND = os.environ.get("EMBEDDING_BACKEND", "local").strip()

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "4096"))
EMBEDDING_MAX_TOKEN_LENGTH = int(os.environ.get("EMBEDDING_MAX_TOKEN_LENGTH", "16384"))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))

# api: any OpenAI-compatible embeddings endpoint.
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "EMPTY")
