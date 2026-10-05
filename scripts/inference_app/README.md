# inference_app: the chat over a docpipe corpus

A retrieval and question-answering front end for the corpus the batch pipeline produced (the
profile's database and FAISS index). The app is part of the package now, in `docpipe/app/`:

```bash
docpipe --profile kwp chat --server.address 0.0.0.0 --server.port 8501
```

It needs the `app` extra, and what follows `chat` goes to Streamlit. `streamlit run
scripts/inference_app/app.py` still works: that file only hands over to the package. The turn
itself lives in `docpipe.inference.answer`; the app is the UI around it. What the corpus is about
comes from the profile (`--profile`, `docpipe.toml` or `DOCPIPE_PROFILE`): its catalog supplies
the document labels, the sidebar filters and the detail shown for the selected document, and its
`inference.UI` every word on the pages. Without a profile the app runs on the built-in `default`
profile's English words and on filename-and-date labels with no filters.

## Flow (per query)

1. Filter and pick one document, up to `COMPARE_MAX_DOCUMENTS` to compare, or tick the whole
   corpus.
2. Pick search scopes (multi-select). Tables and figures are each embedded twice, so each is
   offered as two scopes: `*_vl` = the rendered image plus its caption/description; `*_text` =
   only the caption/description text. There is no image-without-text vector. A figure/table-only
   selection switches the query anchor to a caption style.
3. Type an extraction task; optionally attach an image (the image+text / image-only toggle
   affects only how the *query embedding* is formed; the text task always drives the final
   question answering).
4. Where a harvest is configured, the values it holds for the question are shown first (see
   below), as they were read and checked.
5. The LLM condenses the task into a search phrase.
6. The query is embedded by the configured backend (`Qwen3-VL-Embedding-8B` by default).
   Identical queries hit an on-disk cache and skip the embedding.
7. Retrieval: a temporary sub-index is built from the global index for just the selected document
   and scopes, or, for the whole corpus, the global index is searched. Where a word index exists
   the question's words are searched too and the two rankings are merged. Top-k = 50.
8. The hits are fed to the LLM one chunk at a time (max 10 chunks). The first chunk that yields
   `{"found": true, ...}` produces the answer and the citation (document / section / page).
   Otherwise: "not found in the selected scope".
9. With several documents selected, steps 5-8 run once per document, each with its own retrieval
   and its own citations, and one final call compares the finished answers. There is no values
   step and no image in a comparison.

The graph route (`docpipe.inference.kg_route`) is not offered while no corpus graph exists.

## Whole-corpus questions

The checkbox in the sidebar asks every document at once. Every source then names its document (the
catalog's label, or the name of the document's file without its ending where it gives none), only the current version
of a document answers (two editions of one plan would otherwise put two numbers for one place into
one answer), and the whole corpus is one conversation of its own. The values from the harvest
(below) are not narrowed that way: they come from every harvested document, older versions
included, and the help text of the checkbox says so.

## Values from the harvest

With `INFERENCE_HARVEST_DIR` set to a harvest directory (`docpipe extract`), a question for a
number is answered from the harvest before the documents are searched
(`docpipe/inference/values_route.py`). The question is turned into the parameter and the
coordinates it names, one closed question each over the spec's own lists; the values the harvest
holds for them are shown as they are, each with document, page, trust level and quote, and a link
into the source PDF. An answer outside a list leaves that coordinate open, and a question that
names no parameter shows nothing here. `INFERENCE_VALUES_LEVEL` (A, B or C) leaves out values
below a trust level, and `INFERENCE_VALUES_LIMIT` caps how many are shown before the count of the
rest.

## The review page

Where a harvest is configured the sidebar offers a second page. A person gives a name and works
through the rows nobody has decided yet: for each field (the value, the unit, every coordinate)
the value, its quote and a link to its page are shown, and the field is marked correct or wrong,
with what is right where it is wrong. Two more forms record that the document states a value the
harvest lacks, and that somebody has read a whole document for one parameter. Everything is
appended to `gold.jsonl` (`INFERENCE_GOLD_PATH`, by default beside the harvest directory) and
changes nothing in the harvest. `docpipe evaluate` counts precision and recall against that file.
Two rows of one document that share a quote and a value are two rows with their own decisions. A
number typed into a form is read with the decimal mark of the profile's documents, and the form
for a missing value is emptied once it is saved.

## The word index

A vector search is weak where a question is most specific: a name, an abbreviation, a number.
`docpipe lexical DB` builds a word index beside the corpus database (`<name>.lexical.db`, never
written into the database), and the chat then searches by word as well as by meaning and merges
the two rankings. `docpipe lexical DB --check` says whether it is there and current; a stale index
is not asked. `INFERENCE_LEXICAL=0` turns the word search off.

## Architecture

| File | Responsibility |
| --- | --- |
| `docpipe/app/app.py` | Streamlit UI and orchestration: the chat page and the review page (the only module importing `streamlit`). |
| `docpipe/app/config.py` | Env-var configuration; re-exports the core's values, derives the corpus paths from the profile. |
| `docpipe/app/pdf_link.py` | Source-PDF deep links: quote to page, bbox rects, viewer URL. |
| `docpipe/app/pdfjs_overlay.js` | pdf.js companion that draws the highlight boxes. |
| `docpipe/app/sandbox_service.py` | The code-execution service (`docpipe sandbox`). |
| `scripts/inference_app/app.py` | Hands `streamlit run scripts/inference_app/app.py` over to the package. |
| `scripts/inference_app/Containerfile` | The image the sandbox runs code in. |
| `scripts/inference_app/requirements.txt` | The app's own pinned set, for a dedicated environment. |
| `scripts/inference_app_smoketest.py` | Standalone embedder verification (run first). |

Everything else is core: `docpipe.inference` (`answer`, `catalog`, `db`, `faiss_store`, `hybrid`,
`lexical`, `values_route`, `chunker`, `llm_client`, `query_cache`, `request_log`, `code_exec`) and
`docpipe.embedding`.

## The embedding backend

`docpipe.embedding.get_embedder()` returns whatever `EMBEDDING_BACKEND` names, and the app never
learns which it got: it asks for `embed_one(item)` and receives a vector.

| Value | What it is |
| --- | --- |
| `local` | The model is loaded in this process and stays resident. What a batch run wants. |
| `api` | An embeddings endpoint (`EMBEDDING_PROVIDER`: OpenAI-compatible, `openai` or `gemini`). Text-only, so no `*_vl` scopes. |
| `package.module:Attribute` | Imported and called; anything with `embed` / `embed_one`. |

The third form is how a machine binds its own implementation. A GPU that also serves this app
cannot hold the model resident, so it loads it quantized, embeds, and frees the memory again.
Which quantization, which card and how long to hold the GPU lock are properties of that machine,
so the code lives there and not in this repository:

```
EMBEDDING_BACKEND=mybackends.nf4:Nf4Embedder
```

Such a backend should read `EMBEDDING_MODEL` and `EMBEDDING_MAX_TOKEN_LENGTH` from
`docpipe.embedding.config`: embed a query at a different length than the corpus was built with and
the vectors stop being comparable.

Verify one with `scripts/inference_app_smoketest.py`. It checks dimension, normalization, image
and image+text queries, and batch consistency against whatever backend is configured.

## Code execution (calculations)

When `CODE_EXEC_URL` is set, `answer_from_sources` runs a ReAct loop: the model may reply
`{"action":"python","code":...}`, the app POSTs it to the sandbox (`code_exec.py` to
`sandbox_service.py`), feeds the printed output back, and the model then gives the grounded
answer, up to `CODE_EXEC_MAX_ROUNDS` runs and only when the model asks. The batch's retrieved
tables are injected as a `tables` variable (list of `{caption, markdown}`); numpy, pandas and
pymupdf are available; there is no network inside the sandbox. The executed code and its output
are shown under the answer. The feature is OFF unless `CODE_EXEC_URL` is configured. The service
is a process of its own (`docpipe sandbox`; see its module docstring), run where a container
runtime is allowed, and the image it runs code in is `Containerfile` here.

## Configuration

Every name is a setting: `docpipe config --stage chat` lists them with their values and where each
comes from, and `docpipe.toml` takes them under `[chat]`.

| Var | Default | Meaning |
| --- | --- | --- |
| `DOCPIPE_PROFILE` | unset | The project profile. Supplies the catalog (labels + filters), the words of the pages and the corpus paths below. |
| `INFERENCE_DB_PATH` | `<profile>.db_path` | SQLite corpus DB (opened read-only). |
| `INFERENCE_INDEX_PATH` | `<profile>.index_path` | Global FAISS index. |
| `INFERENCE_IMAGE_ROOT` | `<profile>.processed_dir` | Root for resolving table/figure PNGs. |
| `INFERENCE_PDF_ROOT` | `<profile>.pdf_dir` | Folder holding the source PDFs. |
| `INFERENCE_HARVEST_DIR` | unset | Harvest directory. Unset: no values step and no review page. |
| `INFERENCE_GOLD_PATH` | `gold.jsonl` beside the harvest directory | File the review page appends decisions to. |
| `INFERENCE_VALUES_LEVEL` | unset | Worst trust level (A, B or C) of a harvested value the chat still shows. Unset: every value. |
| `INFERENCE_VALUES_LIMIT` | `20` | Harvested values one answer shows before it says how many more there are. |
| `INFERENCE_LEXICAL` | `1` | Search by word beside the search by meaning where a word index exists. `0`: by meaning only. |
| `INFERENCE_KG_TTL_PATH` | `<profile>.root/graph.ttl` | The Turtle `--serialize` wrote. Read by nothing while the graph route is not offered. |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-VL-Embedding-8B` | HF id of the embedding model. |
| `EMBEDDING_BACKEND` | `local` | Where a query vector comes from: `local`, `api`, or `package.module:Attribute`. |
| `LLM_PROVIDER` | `openai-compatible` | The API behind the text model: a server of one's own, `openai`, `anthropic` or `gemini`. |
| `LLM_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible `/chat/completions` base URL. |
| `LLM_MODEL` | (see `docpipe config`) | Answer-generating model id. List the ids a server has with `GET {LLM_BASE_URL}/models`. |
| `LLM_API_KEY` | from `.env` | The key is read from a `.env` file (`LLM_API_KEY=...`). |
| `LLM_TOKENIZER_ID` | = `LLM_MODEL` | Tokenizer for chunk sizing. A served model id is not always a HF repo, so this falls back to a char/4 heuristic. |
| `LLM_STUB_MODE` | unset | Truthy: canned answers, for testing retrieval without calling the endpoint. |
| `TOP_K` / `MAX_CHUNK_ATTEMPTS` / `ANSWER_CONTEXT_TOKENS` | 50 / 10 / 10000 | Retrieval depth / max sources examined / per-call source token budget. |
| `QUERY_CACHE_PATH` | `data/inference_app_query_cache.db` | Separate embedding-vector cache DB (never the corpus DB). |
| `REQUEST_LOG_PATH` | `data/inference_app_request_log.db` | Separate request log DB (never the corpus DB). |
| `PDF_URL_PREFIX` | `/app/static/pdf` | URL prefix where the source PDFs are served. Empty: hide the PDF links. |
| `PDF_VIEWER_PREFIX` | `/app/static/pdfjs/web` | Bundled pdf.js viewer dir. Empty: native browser viewer. |
| `CODE_EXEC_URL` | (empty) | Sandbox `/run` endpoint. **Empty: the calculation feature is OFF.** |
| `CODE_EXEC_TOKEN` | from `.env` | Bearer token for the sandbox (matches its `KWP_SANDBOX_TOKEN`). |
| `CODE_EXEC_MAX_ROUNDS` | `2` | Max code runs the model may request per answer batch. |
| `CODE_EXEC_TIMEOUT` | `45` | HTTP timeout for a sandbox call (s). |
| `COMPARE_MAX_DOCUMENTS` | `5` | Documents one comparison turn may ask; each costs a full retrieval and answer loop. |

## Source-PDF deep links

Each citation links into the original PDF at the right page with the matching passage
highlighted. By default the link goes through a bundled pdf.js viewer so
`#page=N&search=<phrase>&phrase=true` highlights in every browser; setting `PDF_VIEWER_PREFIX` to
`""` falls back to the browser's native viewer, which jumps to the page but only highlights in
Firefox/Adobe.

The chunk text is LLM-refined, so a verbatim `search=` term cannot come from it. Instead
`pdf_link.locate_quote` matches the grounding quote back onto the raw page `Segments` (the
pre-refinement, page-tagged provenance) and takes the longest shared word-run, which is verbatim
in the PDF text layer. **`Segments.page` is a FK to `Pages.id`, not the page number**: the real
page is joined through `Pages`.

**Coordinate overlay (preferred).** When the matched segment carries a stored `bbox`
(`[[x0,y0,x1,y1],...]` in PDF points, top-left origin), the link uses it instead of a text search:
`pdf_link.best_segment_rects` picks the matched segment's rects and the URL carries
`#page=N&mhl=<base64url rects>`. The bundled `pdfjs_overlay.js` companion decodes `mhl` and draws
the highlight box (`fitz-point x viewport.scale`, no y-flip at rotation 0). `&search=` remains the
automatic fallback when no `bbox` is stored or no segment matches. `pdfjs_overlay.js` must be
copied into the pdf.js bundle and referenced from its `viewer.html`.

The PDFs and the pdf.js bundle are exposed via Streamlit static serving. Filenames are stored raw
in the DB (a few are URL-encoded); the link percent-encodes the name once and the static server
decodes it back, so every on-disk name resolves.

## Setup

Install into a dedicated environment, point the data paths at the corpus, then run:

```bash
pip install ".[app]"                 # or: pip install -r scripts/inference_app/requirements.txt
python scripts/inference_app_smoketest.py --image <some>.png   # verify the embedder first
docpipe --profile kwp chat
```

A local embedder needs the `embed` extra as well; `requirements.txt` here is the app's own pinned
set and brings the whole stack. The API key is read from a `.env` (`LLM_API_KEY=...`).
`LLM_STUB_MODE=1` exercises retrieval without calling the endpoint.

## Logging and caching

Two separate SQLite DBs are created automatically (never the authoritative corpus DB):

- **`REQUEST_LOG_PATH`:** request metadata (plan_id, which is empty for a question to the whole
  corpus, query, mode, scopes, timestamp, latency_ms, n_hits, n_citations, error_message). A log
  made when every question named a document is brought forward when it is opened. No answer is
  cached: a follow-up depends on the
  conversation, and a cache keyed on the question text would serve an answer written for another
  one.
- **`QUERY_CACHE_PATH`:** embedding-vector cache (query hash to vector).

Both grow unbounded; neither requires manual eviction. The review page appends to `gold.jsonl`,
the one file the app writes that is not a cache or a log.

## Known limits

- **Serialized GPU use.** A single process-wide lock serializes all embedding across sessions.
  Run as one Streamlit process (not multiple workers), else the lock must become a file lock.
- **No cache eviction.** The query/embedding caches grow unbounded.
- **Precision.** If a backend quantizes the query model, query vectors are a little off the
  corpus vectors, which were built in bf16.
