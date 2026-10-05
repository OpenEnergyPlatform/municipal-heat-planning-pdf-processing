"""
settings.py: What an installation can set, in one list, and where each value
came from.

A stage reads its settings from the environment, most of them when it is
imported. That stays the interface: a variable set there wins over
everything else. Underneath it sits the project file, `docpipe.toml`. Its
values are put into the environment, for the names not set there, before a
stage is imported. A stage reads what it always read, and a project is one
file instead of a hundred variables.

    profile = "kwp"                 # top level: the DOCPIPE_* names
    data_root = "data"              # a relative path is relative to the file
    [llm]
    base_url = "http://localhost:8000/v1"
    [extract]
    batch_sources = 2
    [env]                           # a profile's own names, verbatim
    MY_SETTING = "x"
    [prices]                        # per million tokens, in one currency
    "some-model" = { input = 2.0, output = 10.0 }

A key that names no setting is refused with the nearest ones. So is a secret:
a key or a token belongs in `.env` or the environment, not in a file that is
checked in. That holds for the [env] table too, by the name's ending.

SETTINGS is that list. A test holds it against every environment name the
code reads, so a new setting cannot be added without a line here.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import dotenv

PROJECT_FILE = "docpipe.toml"
CONFIG_ENV = "DOCPIPE_CONFIG"
FREE_TABLE = "env"
# How the name of a secret ends, for the names of the [env] table.
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS)$")
PRICES_TABLE = "prices"
PRICED = ("input", "output", "embedding", "cached")
KINDS = ("str", "int", "float", "flag", "path", "list")


class ConfigError(ValueError):
    """A project file that cannot be turned into settings."""


@dataclass(frozen=True)
class Setting:
    env: str                    # the environment name: the stable interface
    key: str                    # where it lives in docpipe.toml: "llm.model"
    kind: str                   # one of KINDS
    default: Optional[str]      # as the environment would carry it, or None
    help: str
    secret: bool = False        # a key or a token: never from the project file
    bootstrap: bool = False     # read before any file is: environment only
    on: str = "1"               # how this flag is spelled in the environment
    off: str = "0"
    sep: str = ","              # what joins this list in the environment
    stages: tuple = ()          # the commands that read it


def S(env: str, key: str, kind: str, default: Optional[str], help: str,
      **options) -> Setting:
    if kind not in KINDS:
        raise ValueError(f"{env}: unknown kind {kind!r}")
    return Setting(env, key, kind, default, help, **options)


# Every command, for the names that are read before a stage is chosen.
ALL = ("ingest", "preprocess", "refine", "visuals", "chunk", "extract",
       "chat")

SETTINGS = (
    S("DOCPIPE_CASSETTE_RECORD", "cassette.record", "path", None,
      "File a run writes every model answer to, to be replayed without a "
      "model.",
      stages=("preprocess", "refine", "visuals", "chunk", "extract", "chat")),
    S("DOCPIPE_CASSETTE_REPLAY", "cassette.replay", "path", None,
      "File a run takes its model answers from, in place of a server.",
      stages=("preprocess", "refine", "visuals", "chunk", "extract", "chat")),
    S("ANSWER_CONTEXT_TOKENS", "chat.answer_context_tokens", "int", "10000",
      "Token budget for the retrieved passages in one answer call.",
      stages=("chat",)),
    S("ANSWER_IMAGE_MAX_SIDE", "chat.answer_image_max_side", "int", "1280",
      "Longest side in pixels of a crop sent with an answer call.",
      stages=("chat",)),
    S("ANSWER_MAX_IMAGES", "chat.answer_max_images", "int", "4",
      "Crops attached to one answer call.",
      stages=("chat",)),
    S("COMPARE_MAX_DOCUMENTS", "chat.compare_max_documents", "int", "5",
      "Documents one comparison question may cover; each costs a full "
      "answer loop.",
      stages=("chat",)),
    S("INFERENCE_DB_PATH", "chat.db_path", "path", None,
      "Corpus database, opened read-only; default: the profile's, else "
      "data/KWP.db (chat; `serve` has none).",
      stages=("chat", "serve")),
    S("INFERENCE_ENV_FILE", "chat.env_file", "path", None,
      "Older name for DOCPIPE_ENV_FILE: the .env-style file to load when "
      "that one is unset.",
      bootstrap=True, stages=ALL),
    S("INFERENCE_GOLD_PATH", "chat.gold_path", "path", None,
      "File the review page appends decisions to; default: gold.jsonl "
      "beside the harvest directory.",
      stages=("chat",)),
    S("INFERENCE_HARVEST_DIR", "chat.harvest_dir", "path", None,
      "Harvest directory the chat takes verified values from and the review "
      "page reads; unset: neither.",
      stages=("chat",)),
    S("INFERENCE_IMAGE_ROOT", "chat.image_root", "path", None,
      "Folder that stored table and figure image paths are relative to; "
      "default: the profile's.",
      stages=("chat",)),
    S("INFERENCE_INDEX_PATH", "chat.index_path", "path", None,
      "FAISS index file; default: the profile's index, else "
      "data/faiss_index.bin.",
      stages=("chat",)),
    S("INFERENCE_KG_TTL_PATH", "chat.kg_ttl_path", "path", None,
      "Knowledge graph (Turtle) for the graph route; default: <profile "
      "folder>/graph.ttl.",
      stages=("chat",)),
    S("INFERENCE_LEXICAL", "chat.lexical", "flag", "1",
      "Search by word beside the search by meaning where a word index "
      "exists; 0 searches by meaning only.",
      stages=("chat",)),
    S("MAX_CHUNK_ATTEMPTS", "chat.max_chunk_attempts", "int", "10",
      "Most retrieved passages examined per question.",
      stages=("chat",)),
    S("INFERENCE_PDF_ROOT", "chat.pdf_root", "path", None,
      "Folder holding the source PDFs; default: the profile's PDF folder, "
      "else data/pdf.",
      stages=("chat",)),
    S("PDF_URL_PREFIX", "chat.pdf_url_prefix", "str", "",
      "URL path the source PDFs are served under, for a link into an "
      "external viewer; empty: no link.",
      stages=("chat",)),
    S("PDF_VIEWER_PREFIX", "chat.pdf_viewer_prefix", "str", "",
      "Path of a pdf.js viewer for that link; empty: the browser's own PDF "
      "viewer.",
      stages=("chat",)),
    S("QUERY_CACHE_PATH", "chat.query_cache_path", "path", None,
      "SQLite cache of query vectors; default: "
      "data/inference_app_query_cache.db, beside the project file.",
      stages=("chat",)),
    S("READOFF_IMAGE_MAX_SIDE", "chat.readoff_image_max_side", "int", "1600",
      "Longest side in pixels of a crop sent for a focused chart read-off.",
      stages=("chat",)),
    S("READOFF_MAX_CALLS", "chat.readoff_max_calls", "int", "3",
      "Focused re-reads of image-derived values per answer.",
      stages=("chat",)),
    S("REQUEST_IMAGE_MAX", "chat.request_image_max", "int", "2",
      "Crops the model may ask for per answer batch; 0 turns the requests "
      "off.",
      stages=("chat",)),
    S("REQUEST_LOG_PATH", "chat.request_log_path", "path", None,
      "SQLite log of every chat turn; default: "
      "data/inference_app_request_log.db, beside the project file.",
      stages=("chat",)),
    S("TOP_K", "chat.top_k", "int", "50",
      "Passages kept per retrieval in chat.",
      stages=("chat",)),
    S("INFERENCE_VALUES_LEVEL", "chat.values_level", "str", None,
      "Worst trust level (A, B or C) of a harvested value the chat still "
      "shows; unset: every value.",
      stages=("chat",)),
    S("INFERENCE_VALUES_LIMIT", "chat.values_limit", "int", "20",
      "Harvested values one answer shows before it says how many more there "
      "are.",
      stages=("chat",)),
    S("DOCPIPE_CONFIG", "config", "path", None,
      "The project file to read instead of the nearest docpipe.toml; empty "
      "for none.",
      bootstrap=True, stages=ALL),
    S("DOCPIPE_DATA_ROOT", "data_root", "path", None,
      "Base folder of all profile data, one subfolder per profile; default: "
      "<repo>/data.",
      stages=("preprocess", "refine", "visuals", "chunk", "extract", "chat")),
    S("EMBEDDING_API_KEY", "embedding.api_key", "str", "EMPTY",
      "API key of the embedding endpoint (api backend only).",
      secret=True, stages=("extract", "chat")),
    S("EMBEDDING_BACKEND", "embedding.backend", "str", "local",
      "Where query vectors come from: local, api, or "
      "package.module:attribute.",
      stages=("extract", "chat")),
    S("EMBEDDING_BASE_URL", "embedding.base_url", "str", "",
      "Endpoint of the embedding service (api backend only); required "
      "there.",
      stages=("extract", "chat")),
    S("EMBEDDING_BATCH_SIZE", "embedding.batch_size", "int", "8",
      "Texts per request to the embedding endpoint (api backend only; "
      "chunking uses 32).",
      stages=("extract", "chat")),
    S("EMBEDDING_DIM", "embedding.dim", "int", "4096",
      "Width of the embedding vectors; must match the FAISS index.",
      stages=("chunk", "extract", "chat")),
    S("EMBEDDING_INDEX_BACKEND", "embedding.index_backend", "str", "local",
      "What builds the index in stage 6: local (the model on this machine) "
      "or api (text only).",
      stages=("chunk",)),
    S("EMBEDDING_MAX_TOKEN_LENGTH", "embedding.max_token_length",
      "int", "16384",
      "Longest input in tokens the local embedder reads; longer input is "
      "cut.",
      stages=("chunk", "extract", "chat")),
    S("EMBEDDING_MODEL", "embedding.model",
      "str", "Qwen/Qwen3-VL-Embedding-8B",
      "Embedding model; index building and queries must use the same one.",
      stages=("chunk", "extract", "chat")),
    S("EMBEDDING_PROVIDER", "embedding.provider", "str", "openai-compatible",
      "API behind the api embedding backend: openai-compatible, openai or "
      "gemini.",
      stages=("chunk", "extract", "chat")),
    S("DOCPIPE_ENV_FILE", "env_file", "path", None,
      "The one .env-style file to load before anything else; default: .env "
      "in the working folder.",
      bootstrap=True, stages=ALL),
    S("EXTRACT_ANCHORS", "extract.anchors", "flag", "1",
      "Ask the model once per question for a search anchor; 0 searches "
      "without anchors.",
      stages=("extract",)),
    S("EXTRACT_ATTACH_IMAGES", "extract.attach_images", "flag", "1",
      "Send table and figure crops along with extraction requests; 0 sends "
      "text only.",
      stages=("extract",)),
    S("EXTRACT_BATCH_CHARS", "extract.batch_chars", "int", "14000",
      "Characters of passage text one value request may carry in total.",
      stages=("extract",)),
    S("EXTRACT_BATCH_DOCS", "extract.batch_docs", "int", "64",
      "Documents kept in flight at once during extraction.",
      stages=("extract",)),
    S("EXTRACT_BATCH_SOURCES", "extract.batch_sources", "int", "6",
      "Passages sharing one value request; lowered at start if the context "
      "window is small.",
      stages=("extract",)),
    S("EXTRACT_CODE_ROUNDS", "extract.code_rounds", "int", "2",
      "Sandbox calculation rounds one value request may use.",
      stages=("extract",)),
    S("EXTRACT_FIELD_ATTEMPTS", "extract.field_attempts", "int", "3",
      "Times one window is asked again when its answers could not be backed "
      "by a quote.",
      stages=("extract",)),
    S("EXTRACT_FIELD_MAX_WINDOWS", "extract.field_max_windows", "int", "24",
      "Most windows one coordinate may cost (own plus retrieval) before it "
      "counts as exhausted.",
      stages=("extract",)),
    S("EXTRACT_FIELD_OVERLAP", "extract.field_overlap", "int", "1",
      "Passages of one rest-stage window repeated at the start of the next.",
      stages=("extract",)),
    S("EXTRACT_FIELD_PARALLEL", "extract.field_parallel", "int", "192",
      "Field-sweep threads under the row requests; a ceiling for the "
      "adaptive request limit.",
      stages=("extract",)),
    S("EXTRACT_FIELD_RE_ENTRY", "extract.field_re_entry", "int", "3",
      "Already-read passages carried to the front of a coordinate's next "
      "window.",
      stages=("extract",)),
    S("EXTRACT_FIELD_ROUNDS", "extract.field_rounds", "int", "4",
      "Retrieval rounds of a coordinate's sweep before it falls back to the "
      "rest stage.",
      stages=("extract",)),
    S("EXTRACT_FIELD_ROWS", "extract.field_rows", "int", "32",
      "Most rows one field request answers at once.",
      stages=("extract",)),
    S("EXTRACT_FIELD_WINDOW", "extract.field_window", "int", "2",
      "Passages in one window of the field sweep.",
      stages=("extract",)),
    S("EXTRACT_FIELDWISE", "extract.fieldwise", "flag", "1",
      "One request per coordinate of a value; 0 asks for whole tuples at "
      "once.",
      stages=("extract",)),
    S("EXTRACT_FOLLOWUP_ROUNDS", "extract.followup_rounds", "int", "1",
      "Times the model may ask for more passages on a topic and receive "
      "them.",
      stages=("extract",)),
    S("EXTRACT_FRAME_CHARS", "extract.frame_chars", "int", None,
      "Characters of passage text per frame request; default: the "
      "batch_chars value.",
      stages=("extract",)),
    S("EXTRACT_FRAME_ROUNDS", "extract.frame_rounds", "int", "3",
      "Rounds the frame search (which scenarios and years a document has) "
      "may ask for more.",
      stages=("extract",)),
    S("EXTRACT_FRAME_SOURCES", "extract.frame_sources", "int", "12",
      "Passages one frame request reads.",
      stages=("extract",)),
    S("EXTRACT_FRAME_YEAR_MAX", "extract.frame_year_max", "int", "2100",
      "Latest number the frame cross-check counts as a calendar year.",
      stages=("extract",)),
    S("EXTRACT_FRAME_YEAR_MIN", "extract.frame_year_min", "int", "1990",
      "Earliest number the frame cross-check counts as a calendar year.",
      stages=("extract",)),
    S("EXTRACT_IMAGE_MAX_SIDE", "extract.image_max_side", "int", "1280",
      "Longest side in pixels of a crop attached to an extraction request.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_ADAPTIVE", "extract.limit_adaptive", "flag", "1",
      "Steer the open requests by the server's queue; 0 turns the adaptive "
      "limit off.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_BACKOFF", "extract.limit_backoff", "float", "0.8",
      "Factor the request limit is multiplied by on a step down.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_KV_GROW", "extract.limit_kv_grow", "float", "0.80",
      "Server cache fraction below which the request limit may grow.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_KV_HIGH", "extract.limit_kv_high", "float", "0.92",
      "Server cache fraction at or above which the request limit steps "
      "down.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_MAX", "extract.limit_max", "int", "512",
      "Most requests the adaptive limit may open at once.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_MIN", "extract.limit_min", "int", "16",
      "Fewest requests the adaptive limit backs off to.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_POLL", "extract.limit_poll", "float", "5",
      "Seconds between samples of the server's queue.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_START", "extract.limit_start", "int", "128",
      "Requests the adaptive limit opens with.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_STEP", "extract.limit_step", "int", "8",
      "Requests added on each growth step of the adaptive limit.",
      stages=("extract",)),
    S("EXTRACT_LIMIT_TPOT_MAX", "extract.limit_tpot_max", "float", None,
      "Seconds per output token above which the limit steps down; unset: "
      "never.",
      stages=("extract",)),
    S("EXTRACT_LLM_PARALLEL", "extract.llm_parallel", "int", "128",
      "Model requests in flight at once over the whole extraction run.",
      stages=("extract",)),
    S("EXTRACT_LOCATE", "extract.locate", "flag", "1",
      "Place each quote on its PDF page for highlighting; 0 skips it and "
      "needs no PDFs.",
      stages=("extract",)),
    S("EXTRACT_LOCATE_CACHE_PAGES", "extract.locate_cache_pages", "int", "512",
      "Pages of words kept in memory for placing quotes, across documents.",
      stages=("extract",)),
    S("EXTRACT_LOCATE_MAX_PAGES", "extract.locate_max_pages", "int", "3",
      "Pages of a section tried when placing a quote before giving up.",
      stages=("extract",)),
    S("EXTRACT_MAX_MODEL_LEN", "extract.max_model_len", "int", "32768",
      "Context window assumed when the server does not report one.",
      stages=("extract",)),
    S("EXTRACT_MAX_RETRIES", "extract.max_retries", "int", "3",
      "Attempts per extraction request before it is given up.",
      stages=("extract",)),
    S("EXTRACT_MAX_SOURCE_CHARS", "extract.max_source_chars", "int", "16000",
      "Longest passage one request carries; longer sections are split into "
      "windows.",
      stages=("extract",)),
    S("EXTRACT_PARENT_CHARS", "extract.parent_chars", "int", "4000",
      "Characters of a table's parent section sent along with the table.",
      stages=("extract",)),
    S("EXTRACT_PLAN_PARALLEL", "extract.plan_parallel", "int", "8",
      "Threads for retrieval planning and quote verification.",
      stages=("extract",)),
    S("EXTRACT_PLAN_TOP", "extract.plan_top", "int", "100",
      "Passages (tables, figures and prose) a document's plan keeps, in "
      "rank order.",
      stages=("extract",)),
    S("EXTRACT_PRIOR_MAX", "extract.prior_max", "int", "24",
      "Earlier values listed to the model so that it does not repeat them.",
      stages=("extract",)),
    S("EXTRACT_PROSE_TOP", "extract.prose_top", "int", "200",
      "Prose cap of an older plan rule; the normal run plans by plan_top "
      "and ignores it.",
      stages=("extract",)),
    S("EXTRACT_PROVENANCE", "extract.provenance", "flag", "1",
      "Write the provenance of every value beside the graph "
      "(<graph>.prov.ttl); 0 writes the graph only.",
      stages=("extract",)),
    S("EXTRACT_REST_MAX_WINDOWS", "extract.rest_max_windows", "int", "12",
      "Windows the last search stage may spend per coordinate.",
      stages=("extract",)),
    S("EXTRACT_RETRY_TEMPERATURE_STEP", "extract.retry_temperature_step",
      "float", "0.1",
      "Temperature added per unreadable reply on the next attempt, capped "
      "at 1.0.",
      stages=("extract",)),
    S("EXTRACT_RETRY_TIMEOUT", "extract.retry_timeout", "int", "600",
      "Seconds a retry may wait for a reply after a request timed out.",
      stages=("extract",)),
    S("EXTRACT_RETRY_WAIT", "extract.retry_wait", "float", "2",
      "Seconds per attempt to wait after a bad reply, up to retry_wait_max.",
      stages=("extract",)),
    S("EXTRACT_RETRY_WAIT_MAX", "extract.retry_wait_max", "float", "6",
      "Longest wait in seconds after a bad reply.",
      stages=("extract",)),
    S("EXTRACT_SERVER_DEAD_AFTER", "extract.server_dead_after", "float", "180",
      "Seconds without any reply from the server before the run ends.",
      stages=("extract",)),
    S("EXTRACT_SHOW_UNPARSABLE", "extract.show_unparsable", "int", "20",
      "How many unreadable model replies are shown in the log.",
      stages=("extract",)),
    S("EXTRACT_SPLIT_DEPTH", "extract.split_depth", "int", "3",
      "Times a request that keeps failing may be halved.",
      stages=("extract",)),
    S("EXTRACT_TRACE", "extract.trace", "flag", "1",
      "Write a per-document event trace beside the harvest; 0 turns tracing "
      "off.",
      stages=("extract",)),
    S("EXTRACT_TRANSPORT_WAIT", "extract.transport_wait", "float", "15",
      "Seconds before retrying a request that never reached the server; "
      "doubles each time.",
      stages=("extract",)),
    S("EXTRACT_TRANSPORT_WAIT_MAX", "extract.transport_wait_max",
      "float", "120",
      "Longest wait in seconds between retries to an unreachable server.",
      stages=("extract",)),
    S("EXTRACT_VISUAL_SHARE", "extract.visual_share", "float", "0.5",
      "Share of a document's plan held for tables and figures before prose "
      "fills the rest.",
      stages=("extract",)),
    S("GEMINI_API_KEY", "gemini.api_key", "str", None,
      "Key of the Gemini API, for a role that has no key of its own.",
      secret=True,
      stages=("preprocess", "refine", "visuals", "chunk", "extract", "chat")),
    S("GOOGLE_API_KEY", "gemini.google_api_key", "str", None,
      "The Gemini key under its other name, read when GEMINI_API_KEY is not "
      "set.",
      secret=True,
      stages=("preprocess", "refine", "visuals", "chunk", "extract", "chat")),
    S("DOCPIPE_MAX_DOWNLOAD_MB", "ingest.max_download_mb", "int", "500",
      "Largest PDF a download keeps, in megabytes; a larger one is refused "
      "and listed as unreachable.",
      stages=("ingest",)),
    S("DOCPIPE_USER_AGENT", "ingest.user_agent", "str",
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "User-Agent a PDF download sends; municipal sites answer a plain "
      "client with 403.",
      stages=("ingest",)),
    S("DOCPIPE_LAYOUT_AUTOCAST", "layout_autocast", "str", "off",
      "Reduced precision for page layout detection on a GPU: bf16, fp16 or "
      "off.",
      stages=("preprocess",)),
    S("DOCPIPE_LAYOUT_PREFETCH", "layout_prefetch", "int", "1",
      "Page batches rendered ahead of layout detection; 0 turns the "
      "prefetch off.",
      stages=("preprocess",)),
    S("LLM_API_KEY", "llm.api_key", "str", "EMPTY",
      "API key of the text model endpoint; the placeholder works where none "
      "is checked.",
      secret=True, stages=("refine", "extract", "chat")),
    S("LLM_BASE_URL", "llm.base_url", "str", "http://localhost:8000/v1",
      "OpenAI-compatible endpoint of the text model.",
      stages=("refine", "extract", "chat")),
    S("LLM_ENABLE_THINKING", "llm.enable_thinking", "flag", "0",
      "Allow a thinking phase before each reply; off keeps replies short "
      "and complete.",
      stages=("preprocess", "refine", "visuals", "extract")),
    S("LLM_MAX_RETRIES", "llm.max_retries", "int", "4",
      "Chat only: retries of one model call after a malformed reply or a "
      "transport error.",
      stages=("chat",)),
    S("LLM_MAX_TOKENS", "llm.max_tokens", "int", None,
      "Reply token limit. chat: 2048; refinement: from the prompt, else "
      "8192.",
      stages=("refine", "chat")),
    S("LLM_MODEL", "llm.model", "str", "Qwen/Qwen3.5-122B-A10B-FP8",
      "Name the text model is served under.",
      stages=("refine", "extract", "chat")),
    S("LLM_NUM_PARALLEL", "llm.num_parallel", "int", "8",
      "Refinement only: windows sent to the model at once per document.",
      stages=("refine",)),
    S("LLM_PROVIDER", "llm.provider", "str", "openai-compatible",
      "API of the text model: openai-compatible (a server of one's own), "
      "openai, anthropic or gemini.",
      stages=("refine", "extract", "chat")),
    S("LLM_REASONING_EFFORT", "llm.reasoning_effort", "str", "low",
      "Reasoning effort sent with every request; empty, off or none sends "
      "none.",
      stages=("preprocess", "refine", "visuals", "extract")),
    S("LLM_REQUEST_OPTIONS", "llm.request_options", "str", None,
      "JSON object laid over every request body of a hosted text model: "
      "what only that API takes.",
      stages=("refine", "extract", "chat")),
    S("LLM_SCHEMA", "llm.schema", "str", "auto",
      "auto: one's own server gets a reply schema where it always did; all: "
      "with every JSON request.",
      stages=("preprocess", "refine", "visuals", "extract", "chat")),
    S("LLM_STUB_MODE", "llm.stub_mode", "flag", None,
      "Chat answers with canned replies and never calls the model, for "
      "testing.",
      stages=("chat",)),
    S("LLM_TEMPERATURE", "llm.temperature", "float", None,
      "Sampling temperature. chat: 0.1; refinement: from the prompt, else "
      "0.1.",
      stages=("refine", "chat")),
    S("LLM_THINKING_ROOM", "llm.thinking_room", "int", "8192",
      "Tokens a hosted model may think in, on top of the answer room of "
      "each request.",
      stages=("preprocess", "refine", "visuals", "extract", "chat")),
    S("LLM_TIMEOUT", "llm.timeout", "int", "180",
      "Seconds before one text model request is given up.",
      stages=("refine", "extract", "chat")),
    S("LLM_TOKENIZER_ID", "llm.tokenizer_id", "str", None,
      "Tokenizer that counts chat prompt tokens; default: the model name.",
      stages=("chat",)),
    S("OEP_API_TOKEN", "oekg.api_token", "str", None,
      "Token for the OEKG SPARQL endpoint; the scenarios vocabulary refresh "
      "stops without it.",
      secret=True, stages=("extract",)),
    S("OEKG_EVIDENCE", "oekg.evidence", "flag", "0",
      "scenarios profile: write each passage as a provenance node instead "
      "of a comment.",
      stages=("extract",)),
    S("OEKG_ID_BASE", "oekg.id_base",
      "str", "https://openenergyplatform.org/ontology/oekg/",
      "scenarios profile: IRI prefix of every graph node; changing it "
      "changes all identifiers.",
      stages=("extract",)),
    S("PAGE_RENDER_WORKERS", "preprocess.page_render_workers", "int", "4",
      "Pages rendered at once when pages without a text layer are "
      "transcribed.",
      stages=("preprocess",)),
    S("PAGE_TRANSCRIBE_WORKERS", "preprocess.page_transcribe_workers",
      "int", "64",
      "Transcription requests in flight at once for pages without a text "
      "layer.",
      stages=("preprocess",)),
    S("DOCPIPE_PROFILE", "profile", "str", None,
      "The project profile to run (a folder under profiles/); the same as "
      "--profile.",
      stages=ALL),
    S("DOCPIPE_PROFILE_PATH", "profile_path", "str", None,
      "Directories searched for profiles before the built-in ones, "
      "separated like PATH.",
      bootstrap=True, stages=ALL),
    S("REFINE_REPLY_CEILING", "refine.reply_ceiling", "int", "16384",
      "Upper limit of the reply token budget of one refinement request.",
      stages=("refine",)),
    S("REFINE_RETURN_CORRECTIONS", "refine.return_corrections", "flag", "0",
      "Ask for a list of corrections, not rewritten sections; switching "
      "marks results stale.",
      stages=("refine",)),
    S("REFINE_WINDOW_SIZE", "refine.window_size", "int", None,
      "Sections per refinement request; default: the profile's setting, "
      "else 3.",
      stages=("refine",)),
    S("DOC_PARALLEL", "run.doc_parallel", "int", "8",
      "Documents processed at once in batch mode of refinement and visuals.",
      stages=("refine", "visuals")),
    S("CODE_EXEC_MAX_ROUNDS", "sandbox.code_exec_max_rounds", "int", "2",
      "Chat: code runs the model may request while answering one batch.",
      stages=("chat",)),
    S("CODE_EXEC_TIMEOUT", "sandbox.code_exec_timeout", "float", "45",
      "Seconds the client waits for one sandbox run.",
      stages=("extract", "chat")),
    S("CODE_EXEC_TOKEN", "sandbox.code_exec_token", "str", None,
      "Token sent to the sandbox service; default: the sandbox token "
      "(KWP_SANDBOX_TOKEN).",
      secret=True, stages=("extract", "chat")),
    S("CODE_EXEC_URL", "sandbox.code_exec_url", "str", "",
      "Address of the sandbox service; empty turns the calculation feature "
      "off.",
      stages=("extract", "chat")),
    S("KWP_SANDBOX_HOST", "sandbox.host", "str", "127.0.0.1",
      "Interface the sandbox service listens on.",
      stages=("sandbox",)),
    S("KWP_SANDBOX_IMAGE", "sandbox.image",
      "str", "localhost/kwp-sandbox:latest",
      "Container image every sandbox run executes in.",
      stages=("sandbox",)),
    S("KWP_SANDBOX_MAX_TIMEOUT", "sandbox.max_timeout", "int", "30",
      "Longest execution time in seconds one run may be given.",
      stages=("sandbox",)),
    S("KWP_SANDBOX_MEM", "sandbox.mem", "str", "512m",
      "Memory limit of each sandbox container.",
      stages=("sandbox",)),
    S("KWP_SANDBOX_PORT", "sandbox.port", "int", "8600",
      "Port the sandbox service listens on.",
      stages=("sandbox",)),
    S("KWP_SANDBOX_TIMEOUT", "sandbox.timeout", "int", "20",
      "Execution time in seconds of a run that asks for none.",
      stages=("sandbox",)),
    S("KWP_SANDBOX_TOKEN", "sandbox.token", "str", None,
      "Bearer token the sandbox service requires and its clients send; "
      "needed to start it.",
      secret=True, stages=("sandbox", "extract", "chat")),
    S("DOCPIPE_API_TOKEN", "serve.api_token", "str", None,
      "Token every request to `docpipe serve --http` has to carry; required "
      "to listen beyond this machine.",
      secret=True, stages=("serve",)),
    S("DOCPIPE_UPSTREAM_CACHE", "upstream_cache", "path", None,
      "Cache of downloaded ontology files; default: data/upstream beside "
      "the project file, else in the checkout.",
      stages=("extract",)),
    S("DOCPIPE_USAGE_DB", "usage_db", "path", None,
      "Token counts of all runs (SQLite); default: data/usage.db beside the "
      "project file, else in the working folder.",
      stages=("refine", "visuals", "chunk", "extract")),
    S("VLM_API_KEY", "vlm.api_key", "str", "EMPTY",
      "API key of the vision model endpoint; the placeholder works where "
      "none is checked.",
      secret=True, stages=("preprocess", "visuals")),
    S("VLM_BASE_URL", "vlm.base_url", "str", "http://localhost:8001/v1",
      "OpenAI-compatible endpoint of the vision model.",
      stages=("preprocess", "visuals")),
    S("VLM_MODEL", "vlm.model", "str", "Qwen/Qwen3.5-122B-A10B-FP8",
      "Name the vision model is served under.",
      stages=("preprocess", "visuals")),
    S("VLM_NUM_PARALLEL", "vlm.num_parallel", "int", "8",
      "Tables and figures sent to the vision model at once per document.",
      stages=("visuals",)),
    S("VLM_PROVIDER", "vlm.provider", "str", "openai-compatible",
      "API of the vision model: openai-compatible (a server of one's own), "
      "openai, anthropic or gemini.",
      stages=("preprocess", "visuals")),
    S("VLM_REQUEST_OPTIONS", "vlm.request_options", "str", None,
      "JSON object laid over every request body of a hosted vision model: "
      "what only that API takes.",
      stages=("preprocess", "visuals")),
    S("VLM_RUNAWAY_CELL_RUN", "vlm.runaway_cell_run", "int", "25",
      "Empty table cells in a row that mark a runaway transcription to "
      "retry.",
      stages=("visuals",)),
    S("VLM_TIMEOUT", "vlm.timeout", "float", "180",
      "Seconds before one vision request is given up.",
      stages=("preprocess", "visuals")),
)

BY_ENV = {setting.env: setting for setting in SETTINGS}
BY_KEY = {setting.key: setting for setting in SETTINGS}

# What the last `apply` did: the file, what it says, which of those names
# it put into the environment itself, and the project's .env it read.
_file: Optional[Path] = None
_said: dict = {}
_set: set = set()
_env_file: Optional[Path] = None


def find(start: Optional[Path] = None) -> Optional[Path]:
    """The project file that applies, or None.

    The one $DOCPIPE_CONFIG names; else the nearest docpipe.toml from the
    working directory upwards, so a command run in a subdirectory of a
    project is run in that project. An empty $DOCPIPE_CONFIG means no file.
    """
    named = os.environ.get(CONFIG_ENV)
    if named is not None:
        if not named.strip():
            return None
        path = Path(named).expanduser()
        if not path.is_file():
            raise ConfigError(f"${CONFIG_ENV} names {named!r}, which is not "
                              f"a file")
        return path.resolve()
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def _parse(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:                 # Python before 3.11
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            raise ConfigError(
                f"{path}: reading it needs Python 3.11 or the `tomli` "
                f"package (pip install tomli)") from None
    try:
        # utf-8-sig: an editor's byte order mark is not part of the file
        return tomllib.loads(path.read_bytes().decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}: must be UTF-8 ({exc})") from exc
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _nearest(key: str) -> str:
    close = difflib.get_close_matches(key, list(BY_KEY), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def _spell(setting: Setting, value, path: Path) -> str:
    """One value of the file, as the environment carries it."""

    def refuse(wanted: str):
        raise ConfigError(f"{path}: {setting.key} must be {wanted}, "
                          f"not {value!r}")

    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if setting.kind == "flag":
        if not isinstance(value, bool):
            refuse("true or false")
        return setting.on if value else setting.off
    if setting.kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            refuse("a whole number")
        return str(value)
    if setting.kind == "float":
        if not number:
            refuse("a number")
        return str(value)
    if setting.kind == "list":
        if isinstance(value, str):
            return value
        if not isinstance(value, list) or not all(
                isinstance(item, str)
                or (isinstance(item, (int, float))
                    and not isinstance(item, bool)) for item in value):
            refuse("a list of strings or numbers")
        return setting.sep.join(str(item) for item in value)
    if not isinstance(value, str):
        refuse("a string")
    if setting.kind == "path" and value:
        target = Path(value).expanduser()
        return str(target if target.is_absolute() else path.parent / target)
    return value


def _prices(path: Path, table) -> dict:
    """{model: {"input": .., "output": .., "embedding": .., "cached": ..}} of
    the file's price table, per million tokens. `cached` is what an input
    token costs that the provider served from its cache."""
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [{PRICES_TABLE}] must be a table")
    out: dict = {}
    for model, price in table.items():
        if not isinstance(price, dict) or not price:
            raise ConfigError(
                f"{path}: [{PRICES_TABLE}] {model} must be a table such as "
                f"{{ input = 2.0, output = 10.0 }}")
        for kind, amount in price.items():
            if kind not in PRICED:
                raise ConfigError(
                    f"{path}: [{PRICES_TABLE}] {model}.{kind} is no price; "
                    f"one of: {', '.join(PRICED)}")
            if isinstance(amount, bool) or not isinstance(
                    amount, (int, float)) or amount < 0:
                raise ConfigError(f"{path}: [{PRICES_TABLE}] {model}.{kind} "
                                  f"must be a number, not {amount!r}")
        out[str(model)] = {kind: float(amount)
                           for kind, amount in price.items()}
    return out


def prices() -> dict:
    """What a million tokens of each model cost, as the project file says.

    Empty without a project file or without its [prices] table. The currency
    is whichever the file's author meant: nothing here converts one.
    """
    if _file is None:
        return {}
    return _prices(_file, _parse(_file).get(PRICES_TABLE) or {})


def read(path: Path) -> dict:
    """{environment name: value as the environment carries it} of one file."""
    path = Path(path)
    out: dict = {}

    def take(key: str, value):
        setting = BY_KEY.get(key)
        if setting is None:
            raise ConfigError(f"{path}: {key} is no setting{_nearest(key)}")
        if setting.secret:
            raise ConfigError(
                f"{path}: {key} is a secret and is not read from this file; "
                f"set {setting.env} in .env or in the environment")
        if setting.bootstrap:
            raise ConfigError(
                f"{path}: {key} decides which files are read and has to be "
                f"set in the environment ({setting.env})")
        out[setting.env] = _spell(setting, value, path)

    for name, value in _parse(path).items():
        if name == PRICES_TABLE:
            _prices(path, value)
        elif name == FREE_TABLE:
            if not isinstance(value, dict):
                raise ConfigError(f"{path}: [{FREE_TABLE}] must be a table")
            for env, text in value.items():
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env):
                    raise ConfigError(f"{path}: [{FREE_TABLE}] {env} is not "
                                      f"an environment name")
                if env in BY_ENV:
                    raise ConfigError(f"{path}: [{FREE_TABLE}] {env} is the "
                                      f"setting {BY_ENV[env].key}")
                if SECRET_NAME.search(env):
                    raise ConfigError(
                        f"{path}: [{FREE_TABLE}] {env} is a secret by its "
                        f"name and is not read from this file; set it in "
                        f".env or in the environment")
                if isinstance(text, bool) or not isinstance(
                        text, (str, int, float)):
                    raise ConfigError(f"{path}: [{FREE_TABLE}] {env} must be "
                                      f"a string or a number")
                out[env] = str(text)
        elif isinstance(value, dict):
            for inner, item in value.items():
                take(f"{name}.{inner}", item)
        else:
            take(name, value)
    return out


def apply(path: Optional[Path] = None) -> Optional[Path]:
    """Put the project file's values into the environment, for every name
    that is not set there. Returns the file, or None when there is none.

    Called once when the package is imported, and again by the command line
    for a file named with --config: what an earlier call put into the
    environment is taken back first, the first project's own .env included,
    so the two projects do not mix.
    """
    global _file, _said, _set, _env_file
    for name in _set:
        if os.environ.get(name) == _said.get(name):
            os.environ.pop(name, None)
    if _env_file is not None:
        dotenv.unload(_env_file)
    _file, _said, _set, _env_file = None, {}, set(), None
    path = Path(path).resolve() if path else find()
    if path is None:
        return None
    said = read(path)
    # A project's own .env, for a command run in one of its subdirectories.
    # Not beside a file the environment names as the one to load.
    if not any(os.environ.get(name) for name in dotenv.NAMED):
        _env_file = dotenv.load_dotenv(path.parent / ".env")
    _file, _said = path, said
    for name, value in said.items():
        if name not in os.environ:
            os.environ[name] = value
            _set.add(name)
    return path


def project_file() -> Optional[Path]:
    return _file


def project_dir() -> Path:
    """Where the project is: beside its file, else the working directory."""
    return _file.parent if _file else Path.cwd()


def origin(env: str) -> str:
    """Where the value of `env` in effect comes from."""
    if env in _set and os.environ.get(env) == _said.get(env):
        return PROJECT_FILE
    if env in os.environ:
        loaded = dotenv.LOADED.get(env)
        if loaded and loaded[1] == os.environ[env]:
            return Path(loaded[0]).name
        return "environment"
    return "default"


def rows(stage: Optional[str] = None) -> list:
    """[(setting, value in effect or None, origin, what the file says or
    None)], for the settings one command reads or for all of them."""
    out = []
    for setting in SETTINGS:
        if stage and stage not in setting.stages:
            continue
        value = os.environ.get(setting.env, setting.default)
        shadowed = _said.get(setting.env)
        if origin(setting.env) == PROJECT_FILE:
            shadowed = None
        out.append((setting, value, origin(setting.env), shadowed))
    return out
