## Purpose

`scripts/inference_app` is the Streamlit front end over `docpipe.inference`
(see [Asking the corpus](inference.md)), the only package in the
repository importing Streamlit at all (`app.py:1`). Where the eight
numbered stages turn PDFs into a corpus once, offline, this one turns
that corpus into a running chat: a person opens a profile's database
and FAISS index, picks a document (or a few, to compare), asks a
question in ordinary language, and reads back an answer grounded in a
citation that traces to a page and, where possible, to the exact
passage on it. It loads no model of its own, holds no state on disk
beyond two caches, and keeps a conversation only in the running
process, discarded on reload or a new selection. Every
retrieval and answering decision is made by `docpipe.inference` and
`docpipe.embedding`; this page covers what `app.py`, `config.py`,
`pdf_link.py` and `sandbox_service.py` add: a document and scope
picker, chat history, follow-up context, PDF deep links, and an
optional code-execution sandbox.

A few decisions belong to this layer alone. Selecting several documents
does not become one joint retrieval: `run_comparison` asks each
separately, since one top-k search across several plans would give the
longest chapter most of the slots, leaving shorter documents few or no
citations (`app.py:154`). The embedding model is left out of
the `st.cache_resource` set that
covers the database, the index and the two caches: `get_embedder()` is
imported lazily inside `embed_query()` so that a query-cache hit never
imports `torch` (`app.py:112`). Where a profile's graph exists, a
question goes to it first, through `kg_route.answer_from_graph`; the
sidebar's `Antwortweg` radio can force either side (`app.py:271`,
`365`).

## Position in the pipeline

| | |
|---|---|
| In | One profile's read-only corpus: database at `DB_PATH`, FAISS index at `INDEX_PATH` (chunking, stage 6), `IMAGE_ROOT`/`PDF_ROOT` for table, figure and PDF paths, and, once produced, the graph at `KG_TTL_PATH`; one chat turn (task, optional image, document selection). |
| Out | Nothing written to the corpus, read-only here. Its durable output: two SQLite files created on first use, `QUERY_CACHE_PATH` and `REQUEST_LOG_PATH`; chat history lives only in Streamlit's session state. |
| Resumes on | Nothing: one question is one turn, with no per-document stamp. The one thing an identical query skips is re-embedding, served from `QUERY_CACHE_PATH`; the LLM calls always run. |
| Needs | An OpenAI-compatible LLM endpoint at `LLM_BASE_URL`, the embedding backend `docpipe.embedding.get_embedder()` returns, and a corpus chunking already wrote; `KG_TTL_PATH` and a code-exec sandbox are optional. |

No numbered stage runs after this one; it reads what chunking and,
optionally, the graph stage (8) wrote, and writes back into neither.
The batch chain must finish first (see [Running the
pipeline](../running.md)); this one starts directly:

```bash
DOCPIPE_PROFILE=kwp streamlit run scripts/inference_app/app.py \
    --server.address 0.0.0.0 --server.port 8501
```

## Method

### Startup: cached resources

`streamlit run` re-executes `main()` on every widget interaction, so
the database, the FAISS index and the two SQLite caches are each opened
inside `@st.cache_resource` functions (`get_db`, `get_index`,
`get_catalog`, and four more; `app.py:59`), evaluated once per process. Two
import-time guards run first: a MIME-type registration for the pdf.js
viewer's ES modules, since some Python installs otherwise serve them as
`octet-stream`, unexecutable by browsers (`app.py:32`); and a
`sys.path` insert of the repository root, since `streamlit run` gives no
package context for the imports below (`app.py:36-38`).

### Picking a document, a scope and an answer path

The sidebar is built from the active profile's catalog. A `Historische
Versionen einbeziehen` checkbox sets `include_old`, passed to
`cat.entries()` as `include_superseded`; unchecked, the picker is
filtered to `is_current = 1`, so a superseded version is absent
(`app.py:221`; `docpipe/inference/catalog.py:62-64`, `89-92`).
`catalog.facet_options()` and `apply_filters()` then apply whatever
facets the profile declared, and a multiselect picks one document or,
capped at `COMPARE_MAX_DOCUMENTS`, several to compare; with exactly one
selected, its `detail` expanders open below the picker, a per-profile
addition since the base `Catalog` returns none (`app.py:254-257`). A
scope multiselect defaults to
every embedding type; an answer-format radio chooses prose or JSON, and
a third, with a graph configured, offers `Automatik`,
`Wissensgraph` or `Dokumentsuche` (`app.py:219`). Changing the document
selection resets chat history and follow-up memory (`app.py:288`,
`292`).

### The graph route

When the answer path is not `Dokumentsuche`, `run_kg_turn()` asks the
graph first, through `kg_route.answer_from_graph`. A hit ends the turn
there, rendered per value; a miss carries one of `kg_route`'s five
reason tokens, worded by the profile. `Automatik`
shows that sentence as a caption and still runs the document search; the
forced `Wissensgraph` mode shows it and stops, since a silent fallback
would hide that the graph found nothing (`app.py:375-382`). Image upload
and scope apply to the document search only.

### One document, and several

`run_turn()` assembles a `docpipe.inference.answer.Corpus` from the
cached database, index, the app's own `_embed()` closure and
`resolve_image_path()` (`app.py:126-146`), then calls
`answer.answer_question()` with the task, document id, scopes, and up to
five prior turns for that document.
`_embed()` (`app.py:134-141`) builds the cache key from the query mode,
text and image bytes and calls the module-level `embed_query()`, which
checks `QUERY_CACHE_PATH` first and embeds afresh only on a miss
(`app.py:112-123`). `run_comparison()`
builds the same `Corpus` without an image, since one crop would
otherwise anchor every plan to whatever looks similar, then calls
`compare.compare_documents()`, which runs `answer_question` once per
document and makes one further, source-less LLM call to describe where
the answers differ (`app.py:154`).

### Locating a citation in the source PDF

`_pdf_link_for()` builds a citation's deep link in fallback steps
(`app.py:557`). Since a section's chunk text is refined and not
byte-identical to the PDF's text layer, `pdf_link.locate_quote()`
matches the quote against the raw, page-tagged `Segments` instead,
returning a page and a fallback phrase. When a page is found,
`pdf_link.best_quote_rects()` re-derives highlight rectangles live from
that page with PyMuPDF and `rapidfuzz`, through
`docpipe.inference.pdf_locate.quote_rects()` (`pdf_link.py:193`). The
rectangles reach the browser as the deep link's
`&mhl=` parameter (`pdf_link.encode_rects()`, `pdf_link.py:99`);
`pdfjs_overlay.js`, in the pdf.js bundle's `web/` directory and not
imported by `app.py`, decodes them client-side and draws the boxes on
the page (`app.py:578-579`). Either library missing, or the fuzzy match
scoring under 55, degrades the link further: a bare page link, or none
when `PDF_URL_PREFIX` is empty or the filename is unknown.

### Rendering and remembering

`main()` dispatches a finished turn to `_render_answer`,
`_render_citation`, `_render_comparison` or `_render_kg`; a
document-search or comparison answer also shows any sandbox-run code
through `_render_compute()` (`app.py:411`, `425`, `496`), skipped only
for the graph route, a value node having no compute data (`app.py:373`,
`382`). `_remember()` then appends the turn, a failed one included, to
`turns_by_doc[document_id]` and keeps only the last five, because a
"check again" follow-up is asked precisely after a failure and needs it
in context to search past (`app.py:441`).

## Data model

Chat history lives only in `st.session_state["chat_history"]`, a list of
role/content dicts. An assistant entry carries `citations`, `phrase`,
`as_json`, `recheck_note`, `route_note` and `compute` for a
document-search answer, `kg_values` for a graph answer, or `rows` for a
comparison; the render loop dispatches on whichever key is present
(`app.py:296`). `st.session_state["turns_by_doc"]` maps a document id to
its own remembered turns (`task`, `phrase`, `answer`, `examined`,
`recheck`), capped at five and kept separate per document so a re-check
in one plan never excludes another's sources.

`QUERY_CACHE_PATH` holds one table, `query_cache` (`query_key`, `vector`
as a raw float32 blob, `created_at`). `REQUEST_LOG_PATH` holds one table,
`requests` (plan, query text, mode, scopes, timestamp, latency, hit and
citation counts, `answer_hash`, error, `cache_hit`), appended to once per
turn (`docpipe/inference/answer.py:318`); neither stores the answer text
itself, `answer_hash` being a truncated hash of it, used to spot
repeats. `request_log.py`'s docstring gives the reason: a
follow-up is context-dependent, so a cache keyed on the query text alone
would reuse an answer written for a different conversation; only the
embedding vector is cached. That reuse is not what the logged
`cache_hit` column reflects: `answer_question()`
computes the real flag into its in-memory result (`answer.py:155`), but
`_log()` hardcodes `cache_hit=False` on every call (`answer.py:330`)
instead of forwarding it, so the stored column is always `False`
regardless of the query's embedding coming from `QUERY_CACHE_PATH`.

## Configuration

| name | kind | default | effect | where |
|---|---|---|---|---|
| `DOCPIPE_PROFILE` | env var | unset | Profile supplying the catalog, facets and paths below | `config.py:44` |
| `INFERENCE_DB_PATH` | env var | profile `db_path`, else `data/KWP.db` | Corpus database, opened read-only | `config.py:61` |
| `INFERENCE_INDEX_PATH` | env var | profile `index_path`, else `data/faiss_index.bin` | Global FAISS index, loaded once into RAM | `config.py:62` |
| `INFERENCE_IMAGE_ROOT` | env var | profile `processed_dir`, else `data/pdf/processed` | Root `Tables.path`/`Images.path` resolve against | `config.py:64` |
| `INFERENCE_KG_TTL_PATH` | env var | profile `root/graph.ttl`, else `data/graph.ttl` | Turtle file the graph route reads; missing, the route is off | `config.py:66` |
| `QUERY_CACHE_PATH` | env var | `data/inference_app_query_cache.db` | Query-to-vector cache, separate from the corpus | `config.py:103` |
| `REQUEST_LOG_PATH` | env var | `data/inference_app_request_log.db` | Per-turn request log, separate from the corpus | `config.py:108` |
| `PDF_URL_PREFIX` | env var | `/app/static/pdf` | URL prefix PDFs are served under; empty hides every PDF link | `config.py:121` |
| `PDF_VIEWER_PREFIX` | env var | `/app/static/pdfjs/web` | pdf.js viewer directory; empty falls back to the browser's viewer | `config.py:125` |
| `INFERENCE_PDF_ROOT` | env var | profile `pdf_dir`, else `data/pdf` | Filesystem directory holding the source PDFs | `config.py:127` |
| `COMPARE_MAX_DOCUMENTS` | env var | 5 | Documents one comparison may ask, each a full retrieval-and-answer loop | `docpipe/inference/config.py:56`, `app.py:247` |
| `CODE_EXEC_URL` | env var | empty | Sandbox `/run` endpoint; empty turns the calculation feature off | `docpipe/inference/config.py:64` |
| `CODE_EXEC_TOKEN` | env var | falls back to `KWP_SANDBOX_TOKEN` | Bearer token sent with a `/run` request | `docpipe/inference/config.py:65` |
| `CODE_EXEC_MAX_ROUNDS` | env var | 2 | Sandbox calls one answer batch may make | `docpipe/inference/config.py:68` |
| `KWP_SANDBOX_TOKEN` | env var | none, required | Bearer token `sandbox_service.py` demands; absent, it refuses to start | `sandbox_service.py:34` |
| `KWP_SANDBOX_IMAGE` | env var | `localhost/kwp-sandbox:latest` | Container image a run executes in | `sandbox_service.py:35` |
| `KWP_SANDBOX_HOST` / `KWP_SANDBOX_PORT` | env var | `127.0.0.1` / 8600 | Interface and port the sandbox server binds | `sandbox_service.py:36-37` |
| `KWP_SANDBOX_TIMEOUT` | env var | 20 seconds | Ceiling actually enforced on every run today (see Measured behaviour) | `sandbox_service.py:38` |
| `KWP_SANDBOX_MEM` | env var | `512m` | Container memory limit | `sandbox_service.py:40` |

`config.py` re-exports rather than redefines every retrieval and LLM
setting shared with `docpipe.inference.config`, since two copies of a
setting like `LLM_BASE_URL` risk a deployment talking to the wrong
endpoint (`config.py:14`).

## Failure modes

- An empty `Documents` table (`app.py:223`), a filter matching no
  document (`app.py:236`), a document multiselect left empty
  (`app.py:251`), or a turn with no search scope selected (`app.py:337`),
  each stop before retrieval with its own message.
- A comparison naming more documents than `COMPARE_MAX_DOCUMENTS` cannot
  reach `compare_documents` through the sidebar, whose multiselect already
  caps the selection; its own slice and `dropped` list are a second
  check for any caller (`docpipe/inference/compare.py:94`, `97`).
- A profile's `ROUTE_NOTES` missing a reason token, or wording an extra
  one, makes `kg_route.hooks()` raise `LookupError`; cached at the first
  sidebar render, `get_kg_hooks()` turns that into a start-up error, not
  a blank caption mid-conversation (see Verification).
- Forcing `Wissensgraph` against a question the graph cannot answer ends
  the turn without falling back to document search (see Method, The
  graph route; `app.py:375-382`).
- Neither PyMuPDF nor `rapidfuzz` importable makes both PDF-link helpers
  return `None`, degrading the citation as a low fuzzy-match score does
  (see Method, Locating a citation; `pdf_link.py:147`).
- `sandbox_service.py` refuses to start without `KWP_SANDBOX_TOKEN`
  (`sandbox_service.py:122`) and rejects a mismatched bearer token with a
  401 (`sandbox_service.py:105`); a container or backend error returns as
  a structured error rather than raising, so an outage degrades a turn
  to no calculation, not failure (`sandbox_service.py:83`).
- Loading `.env` from the app's config module, after
  `docpipe.inference` had captured `os.environ`, left the LLM API key at
  its fallback, every answer call failing with 401. The
  load now happens in `docpipe/__init__.py`, before any submodule (see
  Verification).

## Measured behaviour

- `COMPARE_MAX_DOCUMENTS` is 5; each extra document costs one full
  retrieval-and-answer loop, a latency budget, not a modelling limit
  (`docpipe/inference/config.py:56`).
- One turn examines up to `MAX_CHUNK_ATTEMPTS` (10) sources from a
  `TOP_K` (50) candidate set, each answer call budgeted to
  `ANSWER_CONTEXT_TOKENS` (10000) tokens (`docpipe/inference/config.py:37`,
  `39`, `42`).
- A single LLM call retries up to `LLM_MAX_RETRIES` (4) times under a
  `LLM_TIMEOUT` of 180 seconds (`docpipe/inference/config.py:22`, `30`).
- `code_exec.run_code()`, the sandbox's only caller (`answer.py:209`),
  never sends a `timeout` field (`docpipe/inference/code_exec.py:39`);
  `CODE_EXEC_TIMEOUT` (45 seconds, `code_exec.py:46`) bounds only the
  HTTP client, so every run falls back to the tighter
  `KWP_SANDBOX_TIMEOUT` (20 seconds, `sandbox_service.py:38`, `115`);
  `KWP_SANDBOX_MAX_TIMEOUT` (30 seconds, `sandbox_service.py:39`) only
  clamps a caller-supplied `timeout`, which none is.
- Each sandbox run is hardened with `network_mode: none`, every Linux
  capability dropped, a 512 megabyte memory limit and a 128-process
  limit, a single `threading.Lock` serializing containers
  (`sandbox_service.py:42`).
- `pdf_link`'s two PDF-page fallbacks both accept a fuzzy match only at a
  `rapidfuzz` score of 55 or above (`pdf_link.py:148`).

## Verification

- `test_locate_quote_finds_page_and_verbatim_phrase` and
  `test_locate_quote_keeps_punctuation_verbatim`: the phrase
  `locate_quote()` returns is a literal substring of the raw page segment,
  since only a verbatim string drives the viewer's text search.
- `test_locate_quote_returns_none_when_no_shared_run`,
  `test_locate_quote_none_for_too_short_quote` and
  `test_best_search_phrase_graceful_on_missing_file`: a quote sharing no
  three-word run with any segment, one shorter than that, and an
  unreadable PDF path each return `None` rather than raising.
- `test_pdf_page_url_encodes_raw_umlaut_filename`: a filename stored raw
  in the database, umlauts included, is percent-encoded exactly once.
- `test_pdf_viewer_url_rects_overlay_supersedes_search`: a rectangle
  overlay replaces the `search=` term rather than combining with it.
- `test_the_caption_tells_a_carrier_from_a_sector_by_the_specs_own_lists`
  (`tests/test_kg_route.py`): reads `app.py`'s source to confirm
  `_render_kg` calls `kg_route.by_axis()` rather than keeping its own
  vocabulary list.
- `test_a_route_note_nobody_worded_stops_the_route_being_built`
  (`tests/test_kg_route.py`): a `ROUTE_NOTES` table missing one of
  `kg_route.REASONS` makes `kg_route.hooks()` raise `LookupError`.
- `test_the_value_reaches_the_config_that_reads_it`
  (`tests/test_dotenv.py`): a config module under `docpipe` already sees
  a value from `.env` in a fresh interpreter, pinning that
  `docpipe/__init__.py` loads it before any submodule captures
  `os.environ`.

## Modules

`__init__.py` marks the package, its one-line docstring calling it a
Streamlit retrieval and question-answering chat front end over a
`docpipe` corpus; it carries no other logic.

`app.py` is the Streamlit UI and orchestration layer detailed above, the
only module in the repository that imports `streamlit`, run directly
with `streamlit run`.

`config.py` centralizes this app's configuration: it re-exports every
value `docpipe.embedding.config` and `docpipe.inference.config` define,
and adds this app's own paths, derived from the active profile.
Imported by `app.py` and `scripts/inference_app_smoketest.py`.

`pdf_link.py` builds a citation's deep link into the source PDF:
matching a refined quote onto raw, page-tagged text, resolving
highlight rectangles, and assembling a pdf.js viewer or plain page URL.
It touches no database and imports no Streamlit, so it is testable
alone, called from `_pdf_link_for()` and exercised directly by
`tests/test_inference_app.py`.

`sandbox_service.py` is a standalone HTTP server, not imported by
`app.py`, that a deployment runs separately and points `CODE_EXEC_URL`
at. It accepts one authenticated `POST /run` at a time, runs the code in
a fresh, network-isolated podman container through `llm_sandbox`, and
returns a structured result or error, shipped here alongside `app.py`
for a chat deployment.

`scripts/inference_app_smoketest.py` sits beside this package, checking
a deployment's embedding backend by hand: vector dimension, L2
normalization, image and image+text queries, and batch-vs-singly
agreement. Run manually on the serving machine, not by pytest.
