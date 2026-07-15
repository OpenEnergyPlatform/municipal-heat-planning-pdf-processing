# inference_app — Streamlit RAG chat over the KWP knowledge base

A user-facing retrieval + question-answering front-end for the corpus produced
by the batch pipeline (`KWP.db` + the global FAISS index). The multimodal
embedding model is loaded **NF4-quantized on demand** and unloaded again once
idle; the answer-generating LLM (Qwen-122B) is called over a remote
OpenAI-compatible API.

## Flow (per query)

1. Pick one Wärmeplan (document).
2. Pick search scopes (multi-select). Tables and figures are each embedded twice, so each
   is offered as two scopes: **Überschriften**, **Textinhalte**, **Tabellen (Bild + Beschreibung)** /
   **Tabellen (nur Beschreibung)**, **Bilder (Bild + Beschreibung)** / **Bilder (nur Beschreibung)**.
   `*_vl` ("Bild + Beschreibung") = the rendered image plus its caption/description; `*_text`
   ("nur Beschreibung") = only the caption/description text (no image). There is no
   image-without-text vector. A figure/table-only selection also switches the query anchor
   to a caption style.
3. Type an extraction task; optionally attach an image (toggle: image+text / image-only —
   this only affects how the *query embedding* is formed; the text task always drives the
   final question answering).
4. The LLM condenses the task into a search phrase.
5. The query is embedded locally (Qwen3-VL-Embedding-8B, NF4, on-demand). Identical queries
   hit an on-disk cache and skip the GPU load entirely.
6. A temporary sub-index is built from the global index for just the selected document +
   scopes, then searched top-k=50.
7. The hits are fed to the LLM **one chunk at a time** (max 10 chunks). The first chunk that
   yields `{"found": true, ...}` produces the answer + citation (document / section / **page**,
   straight from the DB). Otherwise: "not found in the selected scope".

## Architecture

| File | Responsibility |
| --- | --- |
| `config.py` | All env-var configuration (paths, LLM endpoint, embedder, retrieval, scopes). |
| `db.py` | Read-only DB access: document list, candidate-faiss-id UNION query, content + citation. |
| `faiss_store.py` | Global index load (+`make_direct_map`), sub-index build + search, `retrieve()` with per-owner dedup. |
| `quantized_embedder.py` | NF4 subclass of the shared embedder + on-demand load/unload context manager, GPU auto-select, process lock. |
| `query_cache.py` | SQLite cache (separate file): query hash → embedding vector. |
| `request_log.py` | SQLite request logger + response cache: request metadata + query-response pairs (text-only). Errors logged but not cached (retried on next occurrence). |
| `chunker.py` | Tokenizer + greedy chunk packing + citation labels. |
| `llm_client.py` | OpenAI-compatible client: search-phrase generation + strict-JSON chunk QA + retry loop. |
| `app.py` | Streamlit UI + orchestration (the only file importing `streamlit`). |
| `../inference_app_smoketest.py` | Standalone embedder verification (run first). |

`quantized_embedder.py` **imports** the shared `scripts/qwen3_vl_embedding.py` but never edits
it — it subclasses `Qwen3VLEmbedder`, overriding only `__init__` (NF4 load, no `.to(device)`,
fp32 vision tower) and `process()` (pixel_values→fp32 dtype fix). The batch pipeline is
therefore entirely untouched. The LM backbone is quantized to NF4; the vision tower is left
fp32 so image queries keep full quality.

## Code execution (calculations)

The answer LLM can offload real arithmetic (sums, ratios, kWh↔MWh, aggregations over table
values) instead of doing unreliable mental math. When `CODE_EXEC_URL` is set, `answer_from_sources`
runs a **ReAct loop**: the model may reply `{"action":"python","code":...}`, the app POSTs it to the
hardened remote sandbox (`code_exec.py` → `sandbox_service.py` on a podman host, reached over an SSH
remote-forward), feeds the printed output back, and the model then gives the grounded answer — up to
`CODE_EXEC_MAX_ROUNDS` runs, and **only when the model asks** (a retrieval-only query makes zero
extra calls). The batch's retrieved tables are injected as a `tables` variable (list of
`{caption, markdown}`); numpy/pandas/pymupdf are available; there is **no network** inside the
sandbox. The executed code + output are shown under the answer (🧮 expander). The feature is OFF
unless `CODE_EXEC_URL` is configured, so a plain deployment is unaffected. `sandbox_service.py` is
deployed on the sandbox host, not here — see its module docstring.

## Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `INFERENCE_DB_PATH` | `data/KWP.db` | SQLite corpus DB (opened read-only). |
| `INFERENCE_INDEX_PATH` | `data/faiss_index.bin` | Global FAISS index. |
| `INFERENCE_IMAGE_ROOT` | `data/pdf/processed` | Root for resolving table/figure PNGs. |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-VL-Embedding-8B` | HF id of the embedding model. |
| `EMBED_IDLE_UNLOAD_SECONDS` | `600` | Keep the model warm, unload after this many idle seconds; 0 = strict on-demand. |
| `EMBED_LOCK_TIMEOUT_S` | `300` | Max wait for another session's embed to finish. |
| `LLM_BASE_URL` | UOS agents gateway | `https://kiwi-secure.uni-osnabrueck.de/api/agents/v1` (OpenAI-compatible `/chat/completions`). |
| `LLM_MODEL` | `agent_xzXlgfmSwiaWCuvtRFCq5` | The "DB4KWP" qwen3.5 agent. Alternative: `agent_7qE8YPFNPQ9KQQInK9FNc` ("Test", plain passthrough). List with `GET {LLM_BASE_URL}/models`. |
| `LLM_API_KEY` / `UOS_API_KEY` | from `.env` | The key is read from a `.env` file (`UOS_API_KEY=...`); `LLM_API_KEY` overrides if set. |
| `LLM_TOKENIZER_ID` | = `LLM_MODEL` | Tokenizer for chunk sizing. The agent id is not a HF repo, so this falls back to a char/4 heuristic (fine). |
| `LLM_STUB_MODE` | unset | Truthy → canned answers, for testing retrieval without calling the endpoint. |
| `TOP_K` / `MAX_CHUNK_ATTEMPTS` / `ANSWER_CONTEXT_TOKENS` | 50 / 10 / 10000 | Retrieval depth / max sources examined / per-call source token budget (context-safe batching). |
| `QUERY_CACHE_PATH` | `data/inference_app_query_cache.db` | Separate embedding-vector cache DB (never KWP.db). |
| `REQUEST_LOG_PATH` | `data/inference_app_request_log.db` | Separate request log + response cache DB (never KWP.db). Persists request metadata + successful query-response pairs (text mode only). |
| `PDF_URL_PREFIX` | `/app/static/pdf` | URL path prefix where the source PDFs are served (Streamlit static). Empty → hide the PDF links. |
| `PDF_VIEWER_PREFIX` | `/app/static/pdfjs/web` | Bundled pdf.js viewer dir. Empty → native browser viewer. |
| `INFERENCE_PDF_ROOT` | `data/pdf` | Filesystem dir holding the source PDFs. |
| `CODE_EXEC_URL` | (empty) | Sandbox `/run` endpoint (`sandbox_service.py`). **Empty → the calculation feature is OFF.** |
| `CODE_EXEC_TOKEN` | from `.env` | Bearer token for the sandbox (matches its `KWP_SANDBOX_TOKEN`). |
| `CODE_EXEC_MAX_ROUNDS` | `2` | Max code runs the model may request per answer batch. |
| `CODE_EXEC_TIMEOUT` | `45` | HTTP timeout for a sandbox call (s). |

## Source-PDF deep links

Each citation carries a **"📄 Seite N im PDF öffnen"** link into the original PDF at the right
page, with the matching passage highlighted. By default the link goes through a **bundled pdf.js
viewer** so `#page=N&search=<phrase>&phrase=true` highlights **deterministically in every browser**
(`PDF_VIEWER_PREFIX`; set it to `""` to fall back to the browser's native viewer, which jumps to the
page but only highlights in Firefox/Adobe — Chrome's PDFium ignores `search`).

The chunk text is LLM-refined, so a verbatim `search=` term cannot come from it. Instead
`pdf_link.locate_quote` matches the grounding quote back onto the **raw page `Segments`** (the
pre-refinement, page-tagged provenance) and takes the longest shared word-run — verbatim in the
PDF text layer (extraction is PyMuPDF, not OCR), hence a reliable highlight anchor. The page is the
segment's real `page_number` (**`Segments.page` is a FK to `Pages.id`, not the page number** — it
is joined through `Pages`).

**Coordinate overlay (preferred).** When the matched segment carries a stored `bbox` (the pipeline
now writes per-segment geometry, `[[x0,y0,x1,y1],…]` in PDF points, top-left origin), the link uses
it instead of a text search: `pdf_link.best_segment_rects` picks the same matched segment's rects
and the URL carries `#page=N&mhl=<base64url rects>`. The bundled **`pdfjs_overlay.js`** companion
decodes `mhl` and draws a highlight box on the page (`fitz-point × viewport.scale`, no y-flip at
rotation 0), which is exact and resolution-independent — no dependence on the text layer at all.
`&search=` remains the automatic fallback when no `bbox` is stored (old DB) or no segment matches,
so nothing regresses. The `pdfjs_overlay.js` companion must be copied into the pdf.js bundle and
referenced from its `viewer.html`.

The PDFs and the pdf.js bundle are exposed via Streamlit static serving. Filenames are stored raw
in the DB (a few are URL-encoded); the link percent-encodes the name once and the static server
decodes it back, so every on-disk name resolves.

## Setup

Install into a dedicated venv, point the data paths at the corpus, then run:

```bash
pip install -r scripts/inference_app/requirements.txt
python scripts/inference_app_smoketest.py --image <some>.png   # verify the embedder first
streamlit run scripts/inference_app/app.py
```

The LLM endpoint/model default to the UOS agents gateway and the API key is read from a `.env`
(`UOS_API_KEY=...`). `LLM_STUB_MODE=1` exercises retrieval without calling the endpoint.

## Logging and caching

Two separate SQLite DBs are created automatically (never the authoritative KWP.db):

- **`REQUEST_LOG_PATH` (`data/inference_app_request_log.db`):** Every request is logged with metadata (plan_id, query, mode, scopes, timestamp, latency_ms, n_hits, n_citations, error_message). **Successful text queries are also cached** (plan_id + query_key → answer + citations), so repeats skip both retrieval and LLM (cost ≈ 0 ms, logged with `cache_hit=true`). Errors are logged but **not cached** — failed queries retry on next occurrence.
- **`QUERY_CACHE_PATH` (`data/inference_app_query_cache.db`):** Embedding-vector cache (query hash → vector). Identical queries skip the on-demand NF4 model load.

Both grow unbounded; neither requires manual eviction.

## Known limits (deliberate for v1)

- **Serialized GPU use.** A single process-wide lock serializes all embedding across sessions.
  Right for an interactive single-user-at-a-time tool; not a high-QPS service. Run as one
  Streamlit process (not multiple workers), else the lock must become a file lock.
- **No cache eviction.** The query/embedding caches grow unbounded. Add an LRU trim if needed.
- **Precision.** Corpus vectors were built in bf16; queries are embedded NF4/fp16. Cosine
  retrieval is robust to this; the smoke test's retrieval-sanity step confirms relevance.
