"""
config.py – Central configuration for the inference_app module.

Every value is overridable via an environment variable; the defaults are safe
placeholders.

Author: Felix Vossel
"""
import os

# Everything the core owns is re-exported, never redefined: two copies of
# LLM_BASE_URL is how a deployment ends up talking to the wrong endpoint.
from docpipe.embedding.config import (  # noqa: F401
    EMBEDDING_DIM, EMBEDDING_MAX_TOKEN_LENGTH, EMBEDDING_MODEL,
    EMBED_IDLE_UNLOAD_SECONDS, EMBED_LOCK_TIMEOUT_S,
)
from docpipe.inference.config import (  # noqa: F401
    ALL_SCOPES, ANSWER_CONTEXT_TOKENS, ANSWER_IMAGE_MAX_SIDE, ANSWER_MAX_IMAGES,
    CODE_EXEC_MAX_ROUNDS, CODE_EXEC_TIMEOUT, CODE_EXEC_TOKEN, CODE_EXEC_URL,
    FIGURE_EMBEDDING_TYPES, LLM_API_KEY, LLM_BASE_URL, LLM_MAX_RETRIES,
    LLM_MAX_TOKENS, LLM_MODEL, LLM_STUB_MODE, LLM_TEMPERATURE, LLM_TIMEOUT,
    LLM_TOKENIZER_ID, MAX_CHUNK_ATTEMPTS, READOFF_IMAGE_MAX_SIDE, READOFF_MAX_CALLS,
    SCOPE_FIGURES_TEXT, SCOPE_FIGURES_VL, SCOPE_HEADINGS, SCOPE_TABLES_TEXT,
    SCOPE_TABLES_VL, SCOPE_TEXT, SCOPE_TO_EMBEDDING_TYPES, SECTION_EMBEDDING_TYPES,
    TABLE_EMBEDDING_TYPES, TOP_K, VISUAL_SCOPES,
)
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
# Unload the model after this many idle seconds; 0 = load → embed → free on
# every request.
# How long a request waits for another session's embedding call (the embed lock
# serializes GPU use) before giving up.

# ---------------------------------------------------------------------------
# LLM (remote, OpenAI-compatible)
# ---------------------------------------------------------------------------
# "Models" are preconfigured agents; list them with GET {LLM_BASE_URL}/models.
# HF tokenizer id used only for token-budget accounting. May differ from the
# served model name; falls back to a char/4 heuristic if it cannot be loaded.
# Retry budget for malformed-JSON / transport errors on a SINGLE LLM call.
# Distinct from MAX_CHUNK_ATTEMPTS below.
# When truthy, llm_client returns canned answers instead of calling the endpoint.

# ---------------------------------------------------------------------------
# Retrieval / QA
# ---------------------------------------------------------------------------
# Hard cap on how many retrieved sources are examined per turn.
# Token budget per answer call, so the prompt stays inside the model's context
# window with room for the instructions + the generated answer.
# Crop images attached to the (multimodal) answer call, so values that exist
# only in a chart can be read off. Capped per call; longest side downscaled.
# Focused single-image re-reads of the values the answer call flagged as
# image-derived — one short call per figure, mirroring the setting in which the
# model demonstrably reads charts correctly.

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
# Max code runs the model may request while answering ONE batch.

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


# Ordered list for the UI multiselect (and as the default = everything).

# Figure/table scopes: the query anchor switches to caption style when the
# search targets ONLY these (see app._scopes_are_visual).

# Which embedding types belong to each owner kind (used to split a scope
# selection across the three UNION branches of the candidate query).
