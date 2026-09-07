# inference_app — Streamlit RAG chat over a docpipe corpus

A retrieval + question-answering front-end for the corpus produced by the batch pipeline
(the profile's DB + FAISS index). The turn itself lives in `docpipe.inference.answer`; this
package is the UI around it. What the corpus is about comes from `DOCPIPE_PROFILE`: the
profile's catalog supplies the document labels, the sidebar filters and the detail shown for
the selected document (`profiles/<name>/catalog.py`); without a profile the app falls back to
filename-and-date labels and no filters.

## Flow (per query)

1. Filter and pick one document, or up to `COMPARE_MAX_DOCUMENTS` to compare.
2. Pick search scopes (multi-select). Tables and figures are each embedded twice, so each is
   offered as two scopes: `*_vl` ("Bild + Beschreibung") = the rendered image plus its
   caption/description; `*_text` ("nur Beschreibung") = only the caption/description text.
   There is no image-without-text vector. A figure/table-only selection switches the query
   anchor to a caption style.
3. Type an extraction task; optionally attach an image (the image+text / image-only toggle
   affects only how the *query embedding* is formed; the text task always drives the final
   question answering).
4. The LLM condenses the task into a search phrase.
5. The query is embedded locally (Qwen3-VL-Embedding-8B, NF4, on-demand). Identical queries
   hit an on-disk cache and skip the GPU load.
6. A temporary sub-index is built from the global index for just the selected document +
   scopes, then searched top-k=50.
7. The hits are fed to the LLM one chunk at a time (max 10 chunks). The first chunk that
   yields `{"found": true, ...}` produces the answer + citation (document / section / page).
   Otherwise: "not found in the selected scope".
8. With several documents selected, steps 4-7 run once per document, each with its own
   retrieval and its own citations, and one final call compares the finished answers.
   That call is given the labels and the answers only, never a source passage: it is the
   one output on the screen that no citation backs.

## Architecture

| File | Responsibility |
| --- | --- |
| `app.py` | Streamlit UI + orchestration (the only file importing `streamlit`). |
| `config.py` | Env-var configuration; re-exports the core's values, derives the corpus paths from the profile. |
| `pdf_link.py` | Source-PDF deep links: quote → page, bbox rects, viewer URL. |
| `sandbox_service.py` | The code-execution service, deployed on the sandbox host (not here). |
| `../inference_app_smoketest.py` | Standalone embedder verification (run first). |

Everything else is core: `docpipe.inference` (`answer`, `catalog`, `db`, `faiss_store`,
`chunker`, `llm_client`, `query_cache`, `request_log`, `code_exec`) and `docpipe.embedding`.

## The embedding backend

`docpipe.embedding.get_embedder()` returns whatever `EMBEDDING_BACKEND` names, and the app
never learns which it got — it asks for `embed_one(item)` and receives a vector.

| Value | What it is |
| --- | --- |
| `local` | The model is loaded in this process and stays resident. What a batch run wants. |
| `api` | An OpenAI-compatible `/v1/embeddings` endpoint. Text-only, so no `*_vl` scopes. |
| `package.module:Attribut` | Imported and called; anything with `embed` / `embed_one`. |

The third form is how a machine binds its own implementation. A GPU that also serves this
app cannot hold the model resident, so it loads it quantized, embeds, and frees the memory
again — which quantization, which card, how long to hold the GPU lock are properties of that
machine, so the code lives there and not in this repository. The inference server does:

```
EMBEDDING_BACKEND=backends.nf4:Nf4Embedder
```

Such a backend should read `EMBEDDING_MODEL` and `EMBEDDING_MAX_TOKEN_LENGTH` from
`docpipe.embedding.config`: embed a query at a different length than the corpus was built
with and the vectors stop being comparable.

Verify one with `scripts/inference_app_smoketest.py` — it checks dimension, normalization,
image and image+text queries, and batch consistency against whatever backend is configured.

## Code execution (calculations)

When `CODE_EXEC_URL` is set, `answer_from_sources` runs a ReAct loop: the model may reply
`{"action":"python","code":...}`, the app POSTs it to the remote sandbox (`code_exec.py` →
`sandbox_service.py`), feeds the printed output back, and the model then gives the grounded
answer — up to `CODE_EXEC_MAX_ROUNDS` runs, and only when the model asks. The batch's
retrieved tables are injected as a `tables` variable (list of `{caption, markdown}`);
numpy/pandas/pymupdf are available; there is no network inside the sandbox. The executed code
+ output are shown under the answer. The feature is OFF unless `CODE_EXEC_URL` is configured.
`sandbox_service.py` is deployed on the sandbox host, not here — see its module docstring.

## Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `DOCPIPE_PROFILE` | unset | The project profile. Supplies the catalog (labels + filters) and the corpus paths below. |
| `INFERENCE_DB_PATH` | `<profile>.db_path` | SQLite corpus DB (opened read-only). |
| `INFERENCE_INDEX_PATH` | `<profile>.index_path` | Global FAISS index. |
| `INFERENCE_IMAGE_ROOT` | `<profile>.processed_dir` | Root for resolving table/figure PNGs. |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-VL-Embedding-8B` | HF id of the embedding model. |
| `EMBEDDING_BACKEND` | `local` | Where a query vector comes from: `local`, `api`, or `package.module:Attribut` — see below. |
| `LLM_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible `/chat/completions` base URL. |
| `LLM_MODEL` | (see `config.py`) | Answer-generating agent id. List available ids with `GET {LLM_BASE_URL}/models`. |
| `LLM_API_KEY` / `UOS_API_KEY` | from `.env` | The key is read from a `.env` file (`UOS_API_KEY=...`); `LLM_API_KEY` overrides if set. |
| `LLM_TOKENIZER_ID` | = `LLM_MODEL` | Tokenizer for chunk sizing. An agent id is not a HF repo, so this falls back to a char/4 heuristic. |
| `LLM_STUB_MODE` | unset | Truthy → canned answers, for testing retrieval without calling the endpoint. |
| `TOP_K` / `MAX_CHUNK_ATTEMPTS` / `ANSWER_CONTEXT_TOKENS` | 50 / 10 / 10000 | Retrieval depth / max sources examined / per-call source token budget. |
| `QUERY_CACHE_PATH` | `data/inference_app_query_cache.db` | Separate embedding-vector cache DB (never the corpus DB). |
| `REQUEST_LOG_PATH` | `data/inference_app_request_log.db` | Separate request log + response cache DB (never the corpus DB). Text mode only. |
| `PDF_URL_PREFIX` | `/app/static/pdf` | URL prefix where the source PDFs are served. Empty → hide the PDF links. |
| `PDF_VIEWER_PREFIX` | `/app/static/pdfjs/web` | Bundled pdf.js viewer dir. Empty → native browser viewer. |
| `INFERENCE_PDF_ROOT` | `<profile>.pdf_dir` | Filesystem dir holding the source PDFs. |
| `CODE_EXEC_URL` | (empty) | Sandbox `/run` endpoint. **Empty → the calculation feature is OFF.** |
| `CODE_EXEC_TOKEN` | from `.env` | Bearer token for the sandbox (matches its `KWP_SANDBOX_TOKEN`). |
| `CODE_EXEC_MAX_ROUNDS` | `2` | Max code runs the model may request per answer batch. |
| `CODE_EXEC_TIMEOUT` | `45` | HTTP timeout for a sandbox call (s). |
| `COMPARE_MAX_DOCUMENTS` | `5` | Documents one comparison turn may ask; each costs a full retrieval + answer loop. |

## Source-PDF deep links

Each citation links into the original PDF at the right page with the matching passage
highlighted. By default the link goes through a bundled pdf.js viewer so
`#page=N&search=<phrase>&phrase=true` highlights in every browser; setting `PDF_VIEWER_PREFIX`
to `""` falls back to the browser's native viewer, which jumps to the page but only highlights
in Firefox/Adobe.

The chunk text is LLM-refined, so a verbatim `search=` term cannot come from it. Instead
`pdf_link.locate_quote` matches the grounding quote back onto the raw page `Segments` (the
pre-refinement, page-tagged provenance) and takes the longest shared word-run, which is
verbatim in the PDF text layer. **`Segments.page` is a FK to `Pages.id`, not the page number** —
the real page is joined through `Pages`.

**Coordinate overlay (preferred).** When the matched segment carries a stored `bbox`
(`[[x0,y0,x1,y1],…]` in PDF points, top-left origin), the link uses it instead of a text
search: `pdf_link.best_segment_rects` picks the matched segment's rects and the URL carries
`#page=N&mhl=<base64url rects>`. The bundled `pdfjs_overlay.js` companion decodes `mhl` and
draws the highlight box (`fitz-point × viewport.scale`, no y-flip at rotation 0). `&search=`
remains the automatic fallback when no `bbox` is stored or no segment matches.
`pdfjs_overlay.js` must be copied into the pdf.js bundle and referenced from its `viewer.html`.

The PDFs and the pdf.js bundle are exposed via Streamlit static serving. Filenames are stored
raw in the DB (a few are URL-encoded); the link percent-encodes the name once and the static
server decodes it back, so every on-disk name resolves.

## Setup

Install into a dedicated venv, point the data paths at the corpus, then run:

```bash
pip install -r scripts/inference_app/requirements.txt
python scripts/inference_app_smoketest.py --image <some>.png   # verify the embedder first
DOCPIPE_PROFILE=kwp streamlit run scripts/inference_app/app.py
```

The API key is read from a `.env` (`UOS_API_KEY=...`). `LLM_STUB_MODE=1` exercises retrieval
without calling the endpoint.

## Logging and caching

Two separate SQLite DBs are created automatically (never the authoritative corpus DB):

- **`REQUEST_LOG_PATH`:** request metadata (plan_id, query, mode, scopes, timestamp,
  latency_ms, n_hits, n_citations, error_message). Successful text queries are also cached
  (plan_id + query_key → answer + citations), so repeats skip retrieval and the LLM. Errors
  are logged but not cached.
- **`QUERY_CACHE_PATH`:** embedding-vector cache (query hash → vector).

Both grow unbounded; neither requires manual eviction.

## Known limits

- **Serialized GPU use.** A single process-wide lock serializes all embedding across sessions.
  Run as one Streamlit process (not multiple workers), else the lock must become a file lock.
- **No cache eviction.** The query/embedding caches grow unbounded.
- **Precision.** Corpus vectors were built in bf16; queries are embedded NF4/fp16.
