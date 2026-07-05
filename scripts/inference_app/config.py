"""
config.py – Central configuration for the inference_app module.

Every value is overridable via an environment variable so the app can be
deployed to the inference server without code changes (mirrors the pattern used
by scripts/textrefinement/config.py). The real LLM endpoint / API key are
supplied at deploy time; the defaults below are safe placeholders.

Author: Felix Vossel
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Corpus data (read-only for this app)
# ---------------------------------------------------------------------------
# The batch pipeline is the single writer of these; the app only ever reads.
DB_PATH    = Path(os.environ.get("INFERENCE_DB_PATH", "data/KWP.db"))
INDEX_PATH = Path(os.environ.get("INFERENCE_INDEX_PATH", "data/faiss_index.bin"))
# Root under which extracted table/figure PNGs live (for image display + image
# queries). Paths stored in Tables.path / Images.path are resolved against this.
IMAGE_ROOT = Path(os.environ.get("INFERENCE_IMAGE_ROOT", "data/pdf/processed"))

# ---------------------------------------------------------------------------
# Embedding model (local, NF4-quantized, loaded on demand)
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
EMBEDDING_DIM   = 4096
EMBEDDING_MAX_TOKEN_LENGTH = int(os.environ.get("EMBEDDING_MAX_TOKEN_LENGTH", "16384"))
# 0 = strict on-demand (load → embed → free every request). >0 = keep the model
# resident and unload it only after this many idle seconds (opt-in keep-warm).
EMBED_IDLE_UNLOAD_SECONDS = int(os.environ.get("EMBED_IDLE_UNLOAD_SECONDS", "0"))
# How long a request will wait for another session's embedding call to finish
# (the embed lock serializes GPU use) before giving up with a clear error.
EMBED_LOCK_TIMEOUT_S = float(os.environ.get("EMBED_LOCK_TIMEOUT_S", "300"))

# ---------------------------------------------------------------------------
# LLM (remote, OpenAI-compatible – university-hosted, filled in at deploy time)
# ---------------------------------------------------------------------------
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
LLM_API_KEY  = os.environ.get("LLM_API_KEY", "EMPTY")
LLM_TIMEOUT  = float(os.environ.get("LLM_TIMEOUT", "180"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS  = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
# HF tokenizer id used only for token-budget accounting (small download, no
# model weights). May differ from the served model name; falls back to a
# char/4 heuristic if it cannot be loaded.
LLM_TOKENIZER_ID = os.environ.get("LLM_TOKENIZER_ID", LLM_MODEL)
# Per-chunk retry budget for malformed-JSON / transport errors on a single LLM
# call. Distinct from MAX_CHUNK_ATTEMPTS below (see llm_client.py).
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "4"))
# When set (truthy), llm_client returns canned answers instead of calling the
# remote endpoint – lets the retrieval half be tested before the endpoint exists.
LLM_STUB_MODE = os.environ.get("LLM_STUB_MODE", "").strip() not in ("", "0", "false", "False")

# ---------------------------------------------------------------------------
# Retrieval / QA
# ---------------------------------------------------------------------------
TOP_K = int(os.environ.get("TOP_K", "50"))
# Hard cap on how many retrieved content chunks are shown to the LLM, one at a
# time, before giving up ("answer not found in the selected scope").
MAX_CHUNK_ATTEMPTS = int(os.environ.get("MAX_CHUNK_ATTEMPTS", "10"))
# Token budget per chunk fed to the LLM (leaves room for system prompt, the
# question, and the response within the model's context window).
CHUNK_TOKEN_BUDGET = int(os.environ.get("CHUNK_TOKEN_BUDGET", "6000"))

# ---------------------------------------------------------------------------
# Query→vector cache (separate SQLite file – NEVER the authoritative KWP.db)
# ---------------------------------------------------------------------------
QUERY_CACHE_PATH = Path(os.environ.get("QUERY_CACHE_PATH", "data/inference_app_query_cache.db"))

# ---------------------------------------------------------------------------
# Scopes: the four UI-selectable search areas → underlying embedding types.
# ---------------------------------------------------------------------------
# Tables and figures each map to TWO embedding types (text + vision-language),
# which is exactly why retrieval must dedup by (owner_kind, owner_id): one Table
# row can be hit via both table_text and table_vl in the same search.
SCOPE_HEADINGS = "Überschriften"
SCOPE_TEXT     = "Textinhalte"
SCOPE_TABLES   = "Tabellen"
SCOPE_FIGURES  = "Bilder"

SCOPE_TO_EMBEDDING_TYPES: dict[str, list[str]] = {
    SCOPE_HEADINGS: ["section_title"],
    SCOPE_TEXT:     ["section_text"],
    SCOPE_TABLES:   ["table_text", "table_vl"],
    SCOPE_FIGURES:  ["figure_text", "figure_vl"],
}

# Ordered list for the UI multiselect (and as the default = everything).
ALL_SCOPES: list[str] = [SCOPE_HEADINGS, SCOPE_TEXT, SCOPE_TABLES, SCOPE_FIGURES]

# Which embedding types belong to each owner kind (used to split a scope
# selection across the three UNION branches of the candidate query).
SECTION_EMBEDDING_TYPES = {"section_text", "section_title"}
TABLE_EMBEDDING_TYPES   = {"table_text", "table_vl"}
FIGURE_EMBEDDING_TYPES  = {"figure_text", "figure_vl"}
