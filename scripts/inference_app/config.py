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


def _load_dotenv() -> None:
    """
    Populate os.environ from a .env file (zero-dependency, no python-dotenv).

    Only keys not already set in the environment are added, so an explicit env
    var always wins. Searched, first hit used: $INFERENCE_ENV_FILE, ./.env,
    ~/projects/embedding/.env. Lines are `KEY=VALUE`; surrounding quotes on the
    value are stripped; `#` comment lines and blanks are ignored.
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
# LLM (remote, OpenAI-compatible — University of Osnabrück "agents" gateway)
# ---------------------------------------------------------------------------
# A LibreChat agents API exposing an OpenAI-compatible /chat/completions
# (base_url + "/chat/completions"). "Models" are preconfigured agents on
# qwen3.5; list them with GET {LLM_BASE_URL}/models. Two exist:
#   agent_7qE8YPFNPQ9KQQInK9FNc  "Test"    (plain passthrough; DEFAULT)
#   agent_xzXlgfmSwiaWCuvtRFCq5  "DB4KWP"  (project-named; reasoning FORCED on)
# The "DB4KWP" agent has reasoning hard-wired at the agent level: enable_thinking
# and reasoning_effort are IGNORED, so it generates ~1300–2000 reasoning chars
# per call → ~6x slower (measured: 1.0s vs 5.9s on a trivial call). We fold all
# instructions into the user turn anyway, so the passthrough "Test" agent (no
# reasoning) is faster AND sufficient — hence the default. message.content is
# clean JSON. The API key lives in .env as UOS_API_KEY (loaded above).
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://kiwi-secure.uni-osnabrueck.de/api/agents/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "agent_7qE8YPFNPQ9KQQInK9FNc")
LLM_API_KEY  = os.environ.get("LLM_API_KEY") or os.environ.get("UOS_API_KEY", "EMPTY")
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
# Hard cap on how many retrieved sources are examined (one grounded partial is
# extracted from each; information may be spread across several) before the
# findings are synthesised into the final answer.
MAX_CHUNK_ATTEMPTS = int(os.environ.get("MAX_CHUNK_ATTEMPTS", "10"))
# Token budget for the sources packed into the single answer call. The top
# retrieved sources are included up to this budget (char/4 heuristic) so the
# prompt stays safely inside the model's context window (leaves room for the
# instructions + the generated answer). Sources beyond the budget are dropped
# (reported to the user), so a very wide spread is a known limitation.
ANSWER_CONTEXT_TOKENS = int(os.environ.get("ANSWER_CONTEXT_TOKENS", "10000"))

# ---------------------------------------------------------------------------
# Query→vector cache (separate SQLite file – NEVER the authoritative KWP.db)
# ---------------------------------------------------------------------------
QUERY_CACHE_PATH = Path(os.environ.get("QUERY_CACHE_PATH", "data/inference_app_query_cache.db"))

# ---------------------------------------------------------------------------
# Code-execution sandbox (optional) — a hardened remote service (sandbox_service.py
# on a podman host) the LLM can call for calculations. EMPTY CODE_EXEC_URL = the
# whole feature is OFF (the answer flow behaves exactly as before).
# ---------------------------------------------------------------------------
CODE_EXEC_URL = os.environ.get("CODE_EXEC_URL", "")
CODE_EXEC_TOKEN = os.environ.get("CODE_EXEC_TOKEN") or os.environ.get("KWP_SANDBOX_TOKEN", "")
CODE_EXEC_TIMEOUT = float(os.environ.get("CODE_EXEC_TIMEOUT", "45"))
# Max code runs the model may request while answering ONE batch (keeps the slow
# gateway round-trips bounded).
CODE_EXEC_MAX_ROUNDS = int(os.environ.get("CODE_EXEC_MAX_ROUNDS", "2"))

# ---------------------------------------------------------------------------
# Source-PDF deep links
# ---------------------------------------------------------------------------
# URL path prefix under which the source PDFs are reachable. Served via
# Streamlit static serving (the PDFs hard-linked into static/pdf), so the
# default is the Streamlit static route. Set to "" to hide the PDF links.
PDF_URL_PREFIX = os.environ.get("PDF_URL_PREFIX", "/app/static/pdf")
# Bundled pdf.js viewer directory (contains viewer.html). When set, PDF links go
# through pdf.js so #page + #search highlight DETERMINISTICALLY in every browser
# (Chrome's native viewer ignores #search). Set to "" to use the browser's own
# PDF viewer (native #page jump; highlight only in Firefox/Adobe).
PDF_VIEWER_PREFIX = os.environ.get("PDF_VIEWER_PREFIX", "/app/static/pdfjs/web")
# Filesystem directory holding the source PDFs (for existence checks / the
# static hard-link target). Not required for building links.
PDF_ROOT = Path(os.environ.get("INFERENCE_PDF_ROOT", "data/pdf"))

# ---------------------------------------------------------------------------
# Scopes: the UI-selectable search areas → underlying embedding types.
# ---------------------------------------------------------------------------
# Tables and figures are each embedded TWICE (see chunking.py:94):
#   *_vl   = the rendered image PLUS its caption/description  (the visual vector)
#   *_text = only the caption/description text                (no image)
# There is NO image-without-text vector. So the meaningful user choice is
# "Bild + Beschreibung (VL)" vs. "nur Beschreibung (Text)" — each exposed as its
# own scope so either, or both, can be searched. Selecting both still needs the
# retrieval dedup by (owner_kind, owner_id): one Table/Image row is then hit via
# both its types in the same search.
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

# Figure/table scopes. A caption-style search anchor matches these far better
# than a prose-passage anchor, so the query anchor switches to visual mode when
# the search targets ONLY these (see app._scopes_are_visual).
VISUAL_SCOPES = frozenset({SCOPE_TABLES_VL, SCOPE_TABLES_TEXT,
                           SCOPE_FIGURES_VL, SCOPE_FIGURES_TEXT})

# Which embedding types belong to each owner kind (used to split a scope
# selection across the three UNION branches of the candidate query).
SECTION_EMBEDDING_TYPES = {"section_text", "section_title"}
TABLE_EMBEDDING_TYPES   = {"table_text", "table_vl"}
FIGURE_EMBEDDING_TYPES  = {"figure_text", "figure_vl"}
