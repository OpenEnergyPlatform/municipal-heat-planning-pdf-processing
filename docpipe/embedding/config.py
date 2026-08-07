"""
config.py – Where embeddings come from.

Two backends, chosen by EMBEDDING_BACKEND:

  local  the model runs in this process (needs a GPU; how it is loaded —
         full precision, quantized, one card or several — is a deployment
         detail of the local backend)
  api    an OpenAI-compatible /v1/embeddings endpoint does the work

Author: Felix Vossel
"""
import os

BACKEND = os.environ.get("EMBEDDING_BACKEND", "local").strip().lower()

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "4096"))
EMBEDDING_MAX_TOKEN_LENGTH = int(os.environ.get("EMBEDDING_MAX_TOKEN_LENGTH", "16384"))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))

# local: unload the model after this many idle seconds; 0 = load, embed, free.
EMBED_IDLE_UNLOAD_SECONDS = int(os.environ.get("EMBED_IDLE_UNLOAD_SECONDS", "600"))
# local: how long a caller waits for another one's turn on the GPU.
EMBED_LOCK_TIMEOUT_S = float(os.environ.get("EMBED_LOCK_TIMEOUT_S", "300"))

# api: any OpenAI-compatible embeddings endpoint.
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "EMPTY")
