# inference_app — Streamlit RAG chat over the KWP knowledge base

A user-facing retrieval + question-answering front-end for the corpus produced
by the batch pipeline (`KWP.db` + the global FAISS index). Runs on a **separate,
shared, resource-constrained** server. The multimodal embedding model is loaded
**NF4-quantized on demand** (and freed again after every request) so it never
sits resident in VRAM; the answer-generating LLM (Qwen-122B) is called over a
remote OpenAI-compatible API.

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
| `../inference_app_smoketest.py` | Standalone NF4-on-Pascal verification (run first). |

`quantized_embedder.py` **imports** the shared `scripts/qwen3_vl_embedding.py` but never edits
it — it subclasses `Qwen3VLEmbedder`, overriding only `__init__` (NF4 load, no `.to(device)`,
fp32 vision tower) and `process()` (pixel_values→fp32 dtype fix). The HPC batch pipeline is
therefore entirely untouched.

## Why NF4 (not 8-bit)

bitsandbytes `LLM.int8()` requires compute capability ≥ 7.5 (Turing+); the TITAN X (Pascal)
cards are CC 6.1, so 8-bit would fail at runtime. NF4 (4-bit) requires only CC ≥ 6.0. The LM
backbone is quantized to NF4 (`bnb_4bit_compute_dtype=torch.float16`), the vision tower is
left fp32 so image queries keep full quality. Footprint: ~4–5 GB (LM) + fp32 vision tower,
comfortably within one 12 GB card.

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
| `EMBED_IDLE_UNLOAD_SECONDS` | `0` | 0 = strict on-demand; >0 = keep warm, unload after idle. |
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
so nothing regresses. Install the companion once into the bundle:
`cp scripts/inference_app/pdfjs_overlay.js <static>/pdfjs/web/` and add
`<script src="pdfjs_overlay.js"></script>` before `</body>` in the bundle's `viewer.html`.

**Serving (on the server, not in the repo):** everything is exposed via Streamlit static serving —
`--server.enableStaticServing=true` on the ExecStart. The PDFs are **hard-linked** into
`scripts/inference_app/static/pdf/` (`ln data/pdf/*.pdf scripts/inference_app/static/pdf/`); hard
links share the same inodes, so this adds **no** disk (one copy of the bytes; a symlink is rejected
by Streamlit's path-traversal guard). Filenames are stored raw in the DB (a few are URL-encoded,
e.g. `m%c3%b6nchengladbach`); the link percent-encodes the name once and the static server decodes
it back, so every on-disk name resolves. The **pdf.js viewer** is unzipped into
`scripts/inference_app/static/pdfjs/` (Mozilla `pdfjs-<ver>-legacy-dist.zip`); its `.mjs` are served
as JS (`mimetypes.add_type("text/javascript", ".mjs")` in app.py guards installs that don't map it).

## Setup & run on the inference server

Two gotchas on this specific box, already baked into the steps below:
- **`/tmp` is a 1 GB tmpfs** — pip's torch extract overflows it. Point `TMPDIR` at the home
  partition (2.5 TB) for every install/download.
- **The default PyPI torch is a CUDA-13 build** the 555 driver rejects. Install torch from the
  **cu124** index first (sm_60 kernels cover the sm_61 Pascal cards).

```bash
export TMPDIR=~/projects/embedding/tmp && mkdir -p "$TMPDIR"

# 1) data (copied over separately): KWP.db, faiss_index.bin, and the table/figure PNGs
#    land under ~/projects/embedding/data/. Page numbers come from the DB — no JSON needed.

# 2) dedicated venv
python3 -m venv ~/projects/embedding/.venv
source ~/projects/embedding/.venv/bin/activate

# 3) torch FIRST, from the CUDA 12.4 index (driver 555 = CUDA 12.5; default PyPI wheel is cu130)
pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu124 torch==2.6.0
#    quick check: torch.cuda.is_available() True, get_device_capability(0) == (6,1)

# 4) the rest
pip install --no-cache-dir -r scripts/inference_app/requirements.txt
pip check

# 5) pre-download the embedding model into the HF cache (~16 GB, once)
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-VL-Embedding-8B')"

# 6) SMOKE TEST FIRST — proves NF4 works on these Pascal cards + VRAM is freed.
#    Any PNG works to exercise the vision path (a synthetic one if no corpus PNG is present yet).
python scripts/inference_app_smoketest.py --image data/pdf/processed/<doc>/results/images/<some>.png
#    Expect "ALL CHECKS PASSED". If NF4 fails to load on CC 6.1, STOP and evaluate the
#    fp16-over-both-cards fallback before running the app.

# 7) run the app. LLM base_url/model default to the UOS agents gateway and the
#    API key is read from ~/projects/embedding/.env (UOS_API_KEY=...). Only the
#    data paths need pointing at the copied-over corpus. LLM_STUB_MODE=1 tests
#    the retrieval half without calling the endpoint.
export INFERENCE_DB_PATH=~/projects/embedding/data/KWP.db
export INFERENCE_INDEX_PATH=~/projects/embedding/data/faiss_index.bin
export INFERENCE_IMAGE_ROOT=~/projects/embedding/data/pdf/processed
streamlit run scripts/inference_app/app.py --server.address 0.0.0.0 --server.port 8501
```

Deploy edits from the repo the same way as the HPC modules: `scp` the files over,
LF-normalize (`sed -i 's/\r$//' ...`), `python -m py_compile` to check.

## Logging and caching

Two separate SQLite DBs are created automatically (never the authoritative KWP.db):

- **`REQUEST_LOG_PATH` (`data/inference_app_request_log.db`):** Every request is logged with metadata (plan_id, query, mode, scopes, timestamp, latency_ms, n_hits, n_citations, error_message). **Successful text queries are also cached** (plan_id + query_key → answer + citations), so repeats skip both retrieval and LLM (cost ≈ 0 ms, logged with `cache_hit=true`). Errors are logged but **not cached** — failed queries retry on next occurrence.
- **`QUERY_CACHE_PATH` (`data/inference_app_query_cache.db`):** Embedding-vector cache (query hash → vector). Identical queries skip the on-demand NF4 model load.

Both grow unbounded; neither requires manual eviction.

## Known limits (deliberate for v1)

- **Serialized GPU use.** A single process-wide lock serializes all embedding across sessions
  (held for the whole load→embed→unload span). Right for an interactive single-user-at-a-time
  tool; not a high-QPS service. Run as one Streamlit process (not multiple workers), else the
  lock must become a file lock.
- **No cache eviction.** The query/embedding caches grow unbounded; trivial against the
  server's disk (embedding cache ~16 KB/entry, response cache varies by answer length).
  Add an LRU trim later if ever needed.
- **Precision.** Corpus vectors were built in bf16 on H100; queries here are NF4/fp16 on
  Pascal. Cosine retrieval is robust to this, but the smoke test's retrieval-sanity step is
  the place to confirm topical relevance.
