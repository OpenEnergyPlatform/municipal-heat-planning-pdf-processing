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
    BACKEND as EMBEDDING_BACKEND,
    EMBEDDING_DIM, EMBEDDING_MAX_TOKEN_LENGTH, EMBEDDING_MODEL,
)
from docpipe.inference.config import (  # noqa: F401
    ALL_SCOPES, ANSWER_CONTEXT_TOKENS, ANSWER_IMAGE_MAX_SIDE, ANSWER_MAX_IMAGES,
    CODE_EXEC_MAX_ROUNDS, CODE_EXEC_TIMEOUT, CODE_EXEC_TOKEN, CODE_EXEC_URL,
    COMPARE_MAX_DOCUMENTS,
    FIGURE_EMBEDDING_TYPES, LLM_API_KEY, LLM_BASE_URL, LLM_MAX_RETRIES,
    LLM_MAX_TOKENS, LLM_MODEL, LLM_STUB_MODE, LLM_TEMPERATURE, LLM_TIMEOUT,
    LLM_TOKENIZER_ID, MAX_CHUNK_ATTEMPTS, READOFF_IMAGE_MAX_SIDE, READOFF_MAX_CALLS,
    SCOPE_FIGURES_TEXT, SCOPE_FIGURES_VL, SCOPE_HEADINGS, SCOPE_TABLES_TEXT,
    SCOPE_TABLES_VL, SCOPE_TEXT, SCOPE_TO_EMBEDDING_TYPES, SECTION_EMBEDDING_TYPES,
    TABLE_EMBEDDING_TYPES, TOP_K, VISUAL_SCOPES,
)
from pathlib import Path


# The .env is read by docpipe/__init__.py, which the imports above already
# triggered — early enough that every config module above saw its values.
# Doing it here would be too late: app.py imports docpipe.inference first.

# The profile decides what the corpus is about — its catalog supplies the
# picker labels and filters, its data root the paths below. None is allowed:
# without DOCPIPE_PROFILE the app still runs, on generic labels and the
# historical data/ paths.
from docpipe.profile import active_profile

PROFILE = active_profile()


def _path(env_var: str, from_profile, fallback: str) -> Path:
    """An explicit env var wins over the profile, the profile over the default."""
    explicit = os.environ.get(env_var)
    if explicit:
        return Path(explicit)
    if PROFILE is not None:
        return Path(from_profile(PROFILE))
    return Path(fallback)


# ---------------------------------------------------------------------------
# Corpus data (read-only for this app)
# ---------------------------------------------------------------------------
# The batch pipeline is the single writer of these; the app only ever reads.
DB_PATH    = _path("INFERENCE_DB_PATH", lambda p: p.db_path, "data/KWP.db")
INDEX_PATH = _path("INFERENCE_INDEX_PATH", lambda p: p.index_path, "data/faiss_index.bin")
# Paths stored in Tables.path / Images.path are resolved against this root.
IMAGE_ROOT = _path("INFERENCE_IMAGE_ROOT", lambda p: p.processed_dir, "data/pdf/processed")

# ---------------------------------------------------------------------------
# Embedding backend
# ---------------------------------------------------------------------------
# EMBEDDING_BACKEND decides where a query vector comes from: `local`, `api`, or
# an import path to whatever the machine provides. A card that also serves this
# app wants the model loaded on demand and freed again — that implementation is
# deployment code and lives next to the deployment, not here; the app only ever
# sees docpipe.embedding.get_embedder(). Its own knobs (idle window, lock
# timeout) belong to it and are read there.

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
PDF_ROOT = _path("INFERENCE_PDF_ROOT", lambda p: p.pdf_dir, "data/pdf")

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
# search targets ONLY these (see answer.scopes_are_visual).

# Which embedding types belong to each owner kind (used to split a scope
# selection across the three UNION branches of the candidate query).
