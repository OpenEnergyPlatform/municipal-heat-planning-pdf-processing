"""
config.py – Central configuration for the inference_app module.

Every value is overridable via an environment variable; the defaults are safe
placeholders.

Author: Felix Vossel
"""
import os
from pathlib import Path


def _load_dotenv() -> None:
    """
    Populate os.environ from a .env file (`KEY=VALUE` lines).

    Only keys not already set are added, so an explicit env var always wins.
    First readable file wins: $INFERENCE_ENV_FILE, ./.env, ~/projects/embedding/.env.
    """
    candidates = [
        os.environ.get("INFERENCE_ENV_FILE"),
        ".env",
        os.path.expanduser("~/projects/embedding/.env"),
    ]
    for path in candidates:
        if not path:
            continue
        p = Path(path)
        if not p.is_file():
            continue
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except OSError:
            continue
        break  # first readable .env wins


_load_dotenv()

# ---------------------------------------------------------------------------
# Corpus data (read-only for this app)
# ---------------------------------------------------------------------------
# The batch pipeline is the single writer of these; the app only ever reads.
DB_PATH    = Path(os.environ.get("INFERENCE_DB_PATH", "data/KWP.db"))
INDEX_PATH = Path(os.environ.get("INFERENCE_INDEX_PATH", "data/faiss_index.bin"))
# Paths stored in Tables.path / Images.path are resolved against this root.
IMAGE_ROOT = Path(os.environ.get("INFERENCE_IMAGE_ROOT", "data/pdf/processed"))

# ---------------------------------------------------------------------------
# Embedding model (local, NF4-quantized, loaded on demand)
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
EMBEDDING_DIM   = 4096
EMBEDDING_MAX_TOKEN_LENGTH = int(os.environ.get("EMBEDDING_MAX_TOKEN_LENGTH", "16384"))
# Unload the model after this many idle seconds; 0 = load → embed → free on
# every request.
EMBED_IDLE_UNLOAD_SECONDS = int(os.environ.get("EMBED_IDLE_UNLOAD_SECONDS", "600"))
# How long a request waits for another session's embedding call (the embed lock
# serializes GPU use) before giving up.
EMBED_LOCK_TIMEOUT_S = float(os.environ.get("EMBED_LOCK_TIMEOUT_S", "300"))

# ---------------------------------------------------------------------------
# LLM (remote, OpenAI-compatible)
# ---------------------------------------------------------------------------
# "Models" are preconfigured agents; list them with GET {LLM_BASE_URL}/models.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://kiwi-secure.uni-osnabrueck.de/api/agents/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "agent_xzXlgfmSwiaWCuvtRFCq5")
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

# ---------------------------------------------------------------------------
# Query→vector cache (separate SQLite file – NEVER the authoritative KWP.db)
# ---------------------------------------------------------------------------
QUERY_CACHE_PATH = Path(os.environ.get("QUERY_CACHE_PATH", "data/inference_app_query_cache.db"))

# ---------------------------------------------------------------------------
# Request logging and response cache (separate SQLite file)
# ---------------------------------------------------------------------------
REQUEST_LOG_PATH = Path(os.environ.get("REQUEST_LOG_PATH", "data/inference_app_request_log.db"))

# ---------------------------------------------------------------------------
# Code-execution sandbox (optional) — a remote service the LLM can call for
# calculations. An EMPTY CODE_EXEC_URL turns the whole feature OFF.
# ---------------------------------------------------------------------------
CODE_EXEC_URL = os.environ.get("CODE_EXEC_URL", "")
CODE_EXEC_TOKEN = os.environ.get("CODE_EXEC_TOKEN") or os.environ.get("KWP_SANDBOX_TOKEN", "")
CODE_EXEC_TIMEOUT = float(os.environ.get("CODE_EXEC_TIMEOUT", "45"))
# Max code runs the model may request while answering ONE batch.
CODE_EXEC_MAX_ROUNDS = int(os.environ.get("CODE_EXEC_MAX_ROUNDS", "2"))

# ---------------------------------------------------------------------------
# Source-PDF deep links
# ---------------------------------------------------------------------------
# URL path prefix under which the source PDFs are reachable. Set to "" to hide
# the PDF links.
PDF_URL_PREFIX = os.environ.get("PDF_URL_PREFIX", "/app/static/pdf")
# Bundled pdf.js viewer directory (contains viewer.html). When set, PDF links go
# through pdf.js so #page + #search highlight in every browser (Chrome's native
# viewer ignores #search). Set to "" to use the browser's own PDF viewer.
PDF_VIEWER_PREFIX = os.environ.get("PDF_VIEWER_PREFIX", "/app/static/pdfjs/web")
# Filesystem directory holding the source PDFs. Not required for building links.
PDF_ROOT = Path(os.environ.get("INFERENCE_PDF_ROOT", "data/pdf"))

# ---------------------------------------------------------------------------
# Scopes: the UI-selectable search areas → underlying embedding types.
# ---------------------------------------------------------------------------
# Tables and figures are each embedded TWICE:
#   *_vl   = the rendered image PLUS its caption/description
#   *_text = only the caption/description text (no image)
# There is NO image-without-text vector. Selecting both types of one owner kind
# relies on the retrieval dedup by (owner_kind, owner_id), since one Table/Image
# row is then hit via both its types in the same search.
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
