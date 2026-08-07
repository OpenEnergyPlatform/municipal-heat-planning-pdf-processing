"""
config.py – Inference settings the core needs: the LLM endpoint, the retrieval
budget and the scopes.

Nothing here is domain knowledge, and nothing names a particular deployment:
the LLM is whatever OpenAI-compatible endpoint LLM_BASE_URL points at — a local
vLLM server, an institutional gateway or a hosted API.

Author: Felix Vossel
"""
import os

# ---------------------------------------------------------------------------
# LLM — any OpenAI-compatible endpoint
# ---------------------------------------------------------------------------
# Defaults point at a local vLLM server. A hosted endpoint or an
# institutional gateway is the same thing with a different URL and key;
# put those in the deployment's .env, not here.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
LLM_API_KEY  = os.environ.get("LLM_API_KEY") or os.environ.get("UOS_API_KEY", "EMPTY")
LLM_TIMEOUT  = float(os.environ.get("LLM_TIMEOUT", "180"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS  = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
# HF tokenizer id used only for token-budget accounting. May differ from the
# served model name; falls back to a char/4 heuristic if it cannot be loaded.
LLM_TOKENIZER_ID = os.environ.get("LLM_TOKENIZER_ID", LLM_MODEL)
# Retry budget for malformed-JSON / transport errors on a SINGLE LLM call.
# Distinct from MAX_CHUNK_ATTEMPTS below.
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "4"))
# When truthy, llm_client returns canned answers instead of calling the endpoint.
LLM_STUB_MODE = os.environ.get("LLM_STUB_MODE", "").strip() not in ("", "0", "false", "False")

# ---------------------------------------------------------------------------
# Retrieval / QA
# ---------------------------------------------------------------------------
TOP_K = int(os.environ.get("TOP_K", "50"))
# Hard cap on how many retrieved sources are examined per turn.
MAX_CHUNK_ATTEMPTS = int(os.environ.get("MAX_CHUNK_ATTEMPTS", "10"))
# Token budget per answer call, so the prompt stays inside the model's context
# window with room for the instructions + the generated answer.
ANSWER_CONTEXT_TOKENS = int(os.environ.get("ANSWER_CONTEXT_TOKENS", "10000"))
# Crop images attached to the (multimodal) answer call, so values that exist
# only in a chart can be read off. Capped per call; longest side downscaled.
ANSWER_MAX_IMAGES = int(os.environ.get("ANSWER_MAX_IMAGES", "4"))
ANSWER_IMAGE_MAX_SIDE = int(os.environ.get("ANSWER_IMAGE_MAX_SIDE", "1280"))
# Focused single-image re-reads of the values the answer call flagged as
# image-derived — one short call per figure, mirroring the setting in which the
# model demonstrably reads charts correctly.
READOFF_MAX_CALLS = int(os.environ.get("READOFF_MAX_CALLS", "3"))
READOFF_IMAGE_MAX_SIDE = int(os.environ.get("READOFF_IMAGE_MAX_SIDE", "1600"))

# ---------------------------------------------------------------------------
# Code-execution sandbox (optional)
# ---------------------------------------------------------------------------
CODE_EXEC_URL = os.environ.get("CODE_EXEC_URL", "")
CODE_EXEC_TOKEN = os.environ.get("CODE_EXEC_TOKEN") or os.environ.get("KWP_SANDBOX_TOKEN", "")
CODE_EXEC_TIMEOUT = float(os.environ.get("CODE_EXEC_TIMEOUT", "45"))
# Max code runs the model may request while answering ONE batch.
CODE_EXEC_MAX_ROUNDS = int(os.environ.get("CODE_EXEC_MAX_ROUNDS", "2"))

# ---------------------------------------------------------------------------
# Scopes: the selectable search areas -> underlying embedding types
# ---------------------------------------------------------------------------
SCOPE_HEADINGS      = "Überschriften"
SCOPE_TEXT          = "Textinhalte"
SCOPE_TABLES_VL     = "Tabellen (Bild + Beschreibung)"
SCOPE_TABLES_TEXT   = "Tabellen (nur Beschreibung)"
SCOPE_FIGURES_VL    = "Bilder (Bild + Beschreibung)"
SCOPE_FIGURES_TEXT  = "Bilder (nur Beschreibung)"

SCOPE_TO_EMBEDDING_TYPES: dict[str, list[str]] = {
    SCOPE_HEADINGS:     ["section_title"],
    SCOPE_TEXT:         ["section_text"],
    SCOPE_TABLES_VL:    ["table_vl"],
    SCOPE_TABLES_TEXT:  ["table_text"],
    SCOPE_FIGURES_VL:   ["figure_vl"],
    SCOPE_FIGURES_TEXT: ["figure_text"],
}

# Ordered list for the UI multiselect (and as the default = everything).
ALL_SCOPES: list[str] = [
    SCOPE_HEADINGS, SCOPE_TEXT,
    SCOPE_TABLES_VL, SCOPE_TABLES_TEXT,
    SCOPE_FIGURES_VL, SCOPE_FIGURES_TEXT,
]

# Figure/table scopes: the query anchor switches to caption style when the
# search targets ONLY these (see app._scopes_are_visual).
VISUAL_SCOPES = frozenset({SCOPE_TABLES_VL, SCOPE_TABLES_TEXT,
                           SCOPE_FIGURES_VL, SCOPE_FIGURES_TEXT})

# Which embedding types belong to each owner kind (used to split a scope
# selection across the three UNION branches of the candidate query).
SECTION_EMBEDDING_TYPES = {"section_text", "section_title"}
TABLE_EMBEDDING_TYPES   = {"table_text", "table_vl"}
FIGURE_EMBEDDING_TYPES  = {"figure_text", "figure_vl"}

