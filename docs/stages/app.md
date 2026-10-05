# The chat over the corpus

## Purpose

`docpipe/app/` is the Streamlit front end over `docpipe.inference` (see
[Asking the corpus](inference.md)); `app.py` is the only module in `docpipe/`
that imports Streamlit. Where the numbered stages turn PDFs into a corpus once,
offline, this turns that corpus into a running chat: a person opens a
profile's database and FAISS index, asks a question in ordinary language, and
reads back an answer grounded in a citation that traces to a page and, where
possible, to the passage on it. It has two pages:

- the chat, over one document, several (each asked by itself, then compared)
  or the whole corpus;
- the review page, where a person decides whether harvested values are what
  the documents say (see below). It is offered only where a harvest is
  configured.

The app reads the corpus and writes nothing into it. It loads no model of its
own, keeps a conversation only in the running process, and writes two small
files of its own: a cache of query vectors and a log of requests. Every
retrieval and answering decision is made by `docpipe.inference` and
`docpipe.embedding`; this package adds the pickers, the history, the cited
page drawn from the source PDF and the optional calculation sandbox. Every word
on its pages comes from the profile (`inference.UI`). Without a profile the
pages still open, on the built-in `default` profile's English words and
generic labels, but a question cannot be answered, because the answer loop has
no prompts of its own: the app shows one line at the top saying so. A profile
is named with `--profile`, the `profile` key of `docpipe.toml` or
`DOCPIPE_PROFILE`, and the built-in `default` works for any folder.

## Position in the pipeline

| | |
|---|---|
| In | One profile's corpus, read-only: the database and the FAISS index (chunking), the image root and the PDF folder for table, figure and PDF paths. Optionally the word index (`docpipe lexical`) and a harvest directory (`docpipe extract`). One chat turn: a task, an optional image, a selection. |
| Out | Nothing written to the corpus. Two SQLite files on first use, the query cache and the request log; and, from the review page, decisions appended to `gold.jsonl`. History lives only in Streamlit's session state. |
| Resumes on | Nothing: one question is one turn. An identical query skips only the embedding, from the query cache; the model calls always run. |
| Needs | A model endpoint for the search phrase, the answer and the comparison (`LLM_PROVIDER`, `LLM_BASE_URL`), the embedding backend `docpipe.embedding.get_embedder()` returns, and a corpus chunking already wrote. A code sandbox is optional. |

No numbered stage runs after this one. The batch chain has to finish first
(see [Running the pipeline](../running.md)); this starts directly:

```bash
docpipe --profile kwp chat --server.address 0.0.0.0 --server.port 8501
```

`docpipe chat` starts `docpipe/app/app.py` with Streamlit and passes what
follows to it. It needs the `app` extra. The older form, `streamlit run
scripts/inference_app/app.py`, still works: that file only hands over to the
package.

## What a turn does

The sidebar offers the picker the profile's catalog builds (its filters, the
document label, the detail shown for one document), a checkbox for the whole
corpus, the search scopes and the answer format. The scopes are those whose
embedding types the index holds vectors of, in a fixed order, found by one
query over the `Embeddings` table (`db.available_scopes`): an index built
through a text-only backend shows no image scopes. An index with no vectors at
all offers none, and a question then gets the warning to choose a scope. Where
the database records another embedding model than the one that embeds the
questions (`EMBEDDING_MODEL`), a warning in the profile's words stands above
the chat and nothing is refused: the vectors only may not compare. The check
reads the configured model's name, so a backend loaded by import path whose
real model differs from that name is not noticed. Changing the selection
resets the history. A turn then runs in this order:

1. If a harvest is configured (`INFERENCE_HARVEST_DIR`) and the question is
   not only an image, the numbers the harvest holds for it are shown first,
   each with its document, page, trust level and quote, as they were read and
   checked and not as a model writes them now. This is
   `docpipe/inference/values_route.py` over `docpipe/serve/values.py`; a
   question that names no parameter shows nothing here. `INFERENCE_VALUES_LEVEL`
   leaves out values below a trust level and `INFERENCE_VALUES_LIMIT` caps how
   many are shown before the count of the rest.
2. The answer from the documents follows, as before: a search anchor, the
   query embedding, retrieval, and the answer across token-budgeted batches.
   Retrieval is by meaning and, where a word index exists beside the database
   and is current, also by word, and the two rankings are merged
   (`docpipe/inference/hybrid.py`). `INFERENCE_LEXICAL=0` turns the word
   search off.
3. With several documents selected there is no values step and no joint
   search: `run_comparison` asks each document by itself and one more call
   compares the finished answers, since one top-k over several plans would
   give the longest chapter most of the slots.

Over the whole corpus every source names its document (the label of the
catalog, or the name of the document's file without its ending where it gives none), only the
current version of a document answers, and the conversation is one of its own.
The values of step 1 are not narrowed that way: they come from every
harvested document, older versions included, and the help text of the
checkbox (`whole_corpus_help` of the profile) says so.

The graph route is not offered while no corpus graph exists. `kg_route` stays
in the core, and `run_kg_turn` and `_render_kg` stay in the app, for the day
one does.

## The review page

The review page is how the decisions behind
[a harvest's precision and recall](evaluation.md) are made. The person gives
a name and works through the queue of rows nobody has decided yet: for each
field of the row (the value, the unit, every coordinate) the value, its quote
and a button into the source PDF at its page are shown, and the field is
marked correct or wrong, with what is right where it is wrong (the button into
the PDF is the optional external link below, so it is there only where one is
configured). Two more
forms record that the document states a value the harvest lacks, and that
somebody has read a whole document for one parameter. All three append to
`gold.jsonl` (`INFERENCE_GOLD_PATH`, by default beside the harvest directory);
nothing here changes the harvest.

A row is keyed on the page by `gold.row_name`, its name and what it says
beside the value, so two rows of one document that share a quote and a value
are two rows with their own decisions; a row that is skipped stays skipped
under that key. A number typed into the form, what is right or a value that is
missing, is read with the decimal mark of the profile's documents (`_typed`:
`1.234,5` is 1234.5 where they write a decimal comma; a comma where the profile
names none). The form for a missing value is emptied once it is saved (the document and the
parameter stay chosen), so the same value is not saved twice by a second press.

## Showing a citation's page

A section's chunk text is refined and is not byte-identical to the PDF's text
layer. So `pdf_link.locate_quote` matches the quote against the raw,
page-tagged `Segments` and returns a page and a fallback phrase. When a page
is found, `pdf_link.best_quote_rects` derives highlight rectangles from that
page with PyMuPDF and `rapidfuzz`.

Every citation then has a page expander next to its context expander
(`_show_page`). It draws the cited page from the PDF in the profile's PDF
folder (`INFERENCE_PDF_ROOT`) with a highlight over each rectangle found, and
offers the PDF as a download. `pdf_link.render_page` is the one small function
that calls PyMuPDF to draw: it puts the highlights on in memory, which holds
for rotated pages, never writes the file, and draws at most 2600 pixels on the
longest side. Only a section's quote is a passage of the page. The quote of a
table or a figure is a title or a reading, so its page is shown without a mark
and without a note. Where the page shows no mark, the expander says so (UI
word `page_not_located`). Where the file is not in the folder it names the
file and nothing else, the folder going to the log, and where the page cannot
be drawn (PyMuPDF missing, a PDF that does not open, a page the PDF does not
have, a page that did not render) it says which in the profile's words, and the
English cause goes to the log once per failure. The download stays whenever
the file exists. Drawn pages are cached by path and modification time, 128 of
them, and so are the PDF's bytes, 4 of them, so a replaced PDF is drawn again.
Every entry into PyMuPDF holds one lock (`pdf_locate.MUPDF_LOCK`), because the
chat runs every session on its own thread and a rerun starts while the script
it replaced is still drawing.

Its limits: the page is drawn eagerly inside the collapsed
expander of every citation, on every rerun, and the download reads the whole
file for each citation, which is heavy for a plan of 50 to 150 MB. Once the
history holds more distinct cited pages than the cache, each new question
redraws the evicted ones (about 0.2 to 0.5 seconds each). The note "not
located" is also what shows when `rapidfuzz` is missing, the cause being
logged once. Tables and figures get no rectangles. The values block and the
review page still get only the optional external link.

That link is optional and off by default. `PDF_URL_PREFIX` and
`PDF_VIEWER_PREFIX` are both empty, and nothing ships that serves a PDF or a
viewer. Where a deployment sets them, a link button goes into an external
viewer at the cited page: `PDF_URL_PREFIX` is the URL path the PDFs are served
under, and `PDF_VIEWER_PREFIX` the path of a pdf.js viewer, through which the
rectangles reach the browser as the `&mhl=` parameter and
`pdfjs_overlay.js`, which a deployment copies into that viewer, draws the
boxes (assuming an unrotated page). With the viewer prefix empty the link is a
bare page link for the browser's own viewer, and with a missing library or a
match scoring under 55 it loses its phrase or rectangles.

## Configuration

Every name is a setting: `docpipe config --stage chat` lists them with their
values, and the project file takes them under `[chat]`. The paths default to
the profile's own.

| setting | what it is |
|---|---|
| `INFERENCE_DB_PATH`, `INFERENCE_INDEX_PATH`, `INFERENCE_IMAGE_ROOT`, `INFERENCE_PDF_ROOT` | the corpus database (read-only; `docpipe serve` reads it too, for its passage search, and has no default), the FAISS index, the root of table and figure images, the folder of source PDFs the cited page is drawn from |
| `INFERENCE_HARVEST_DIR`, `INFERENCE_GOLD_PATH`, `INFERENCE_VALUES_LEVEL`, `INFERENCE_VALUES_LIMIT` | the harvest the values and the review page read, the decisions file, how many and how trustworthy a value must be to be shown |
| `INFERENCE_LEXICAL` | search by word beside the search by meaning where a word index exists |
| `INFERENCE_KG_TTL_PATH` | the Turtle file a graph route would read; read by nothing while the route is not offered |
| `QUERY_CACHE_PATH`, `REQUEST_LOG_PATH` | the two files of the app's own |
| `PDF_URL_PREFIX`, `PDF_VIEWER_PREFIX` | where an external viewer serves the PDFs and its pdf.js viewer, for the optional link; both are empty by default, and empty means no link and the browser's own viewer |
| `COMPARE_MAX_DOCUMENTS`, `TOP_K`, `MAX_CHUNK_ATTEMPTS`, `ANSWER_CONTEXT_TOKENS` | how many documents one comparison asks, and the retrieval and answer budgets |
| `CODE_EXEC_URL`, `CODE_EXEC_TOKEN`, `CODE_EXEC_MAX_ROUNDS`, `CODE_EXEC_TIMEOUT` | the calculation sandbox; an empty URL turns the feature off |

`config.py` re-exports every retrieval and model setting it shares with
`docpipe.inference.config` and does not redefine one: two copies of a value
like `LLM_BASE_URL` are how a deployment ends up talking to the wrong endpoint.

## Data the app keeps

Chat history lives in `st.session_state["chat_history"]`, a list of
role and content dicts. An assistant entry carries what the turn produced:
`citations`, `phrase`, `values`, `compute`, or `rows` for a comparison.
`turns_by_doc` maps a document id (the whole corpus under `None`) to its last
five turns, kept apart per document so that a "check again" in one plan never
excludes another's sources, and a failed turn is kept because that follow-up
is asked precisely after one.

`QUERY_CACHE_PATH` holds one table, `query_cache` (a key, the vector as a
float32 blob, a timestamp). The key is over the embedding model and the
vector size as well as the query, read from the configuration at the time of
the call, so a vector of another model is never found for the same question
and one file serves whichever model is configured next. Entries written under
a key without them match nothing and are embedded again; a benchmark
recording made earlier whose query vectors live in its own query cache no
longer replays without a model and has to be recorded again. `REQUEST_LOG_PATH` holds one table, `requests`
(plan, query text, mode, scopes, timestamp, latency, hit and citation counts,
a truncated hash of the answer, error, `cache_hit`). No answer is cached: a
follow-up depends on the conversation, and a cache keyed on the question text
would reuse an answer written for another one. The logged `cache_hit` is
always `False`; whether the query vector came from the cache is reported in
the turn's own result.

## Failure modes

- An empty `Documents` table, a filter that matches no document, a selection
  left empty or a turn with no scope each stop before retrieval with a message
  of their own.
- A selection of more documents than `COMPARE_MAX_DOCUMENTS` cannot be made
  in the sidebar; `compare_documents` names what it leaves out as a second
  check for any other caller.
- `sandbox_service.py` refuses to start without `KWP_SANDBOX_TOKEN` and
  answers a wrong bearer token with 401. A container or backend error comes
  back as a structured error, so an outage costs a turn its calculation and
  not its answer.
- The `.env` is loaded in `docpipe/__init__.py`, before any module captures
  its settings. Loaded later, in the app's config, the model key stayed at its
  placeholder and every call failed with 401.

## Modules

`app.py` is the pages and the orchestration, run with `docpipe chat`.
`config.py` reads every path and limit of the app. `pdf_link.py` locates a
quote on its page, draws the page and builds the optional deep link into an
external viewer; it touches no database and imports no Streamlit, so it is
tested alone. `pdfjs_overlay.js` is the client side of the highlight
rectangles in such a viewer. `sandbox_service.py` is a separate HTTP server, not
imported by the app, that a deployment runs and points `CODE_EXEC_URL` at
(`docpipe sandbox`): one authenticated `POST /run` at a time, in a fresh
container with no network, every capability dropped and a memory limit.
`scripts/inference_app_smoketest.py` checks a deployment's embedding backend
by hand: vector dimension, normalisation, image and image-and-text queries,
and batch against single. It is run by a person, not by pytest.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/app/__init__.py</code></summary>

app: The chat over a processed corpus, and the page on which a person
decides about harvested values.

`app.py` is the only module that imports Streamlit; `docpipe chat` runs it.
`config.py` is where every path and limit of the app is read, `pdf_link.py`
draws the cited page of the source PDF and builds the link into an external
viewer, and `sandbox_service.py` is the service that runs code a model wrote
(`docpipe sandbox`), on the machine where that is allowed.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/app/app.py</code></summary>

app.py: The chat over a docpipe corpus and the page on which harvested
values are reviewed. The only module of the package that imports Streamlit.

What the corpus is about comes from the profile: its catalog supplies the
labels, the filters and the detail shown for a selected document, and its
`inference.UI` every word on these pages. A question goes to one document,
to several (each asked by itself, then compared) or to the whole corpus.
Where a harvest is configured, the numbers it holds for a question are
shown first, as they were read and checked, and the answer from the
documents follows.

The graph route is not offered while no corpus graph exists, and
`docpipe.inference.kg_route` stays in the core for the day it does.

Run:
    docpipe --profile kwp chat --server.address 0.0.0.0 --server.port 8501

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/app/config.py</code></summary>

config.py: Central configuration for the chat app.

Every value is overridable through an environment variable; the defaults
are safe placeholders. The corpus paths (the database, the FAISS index,
the image root, the knowledge-graph file) default to the active profile's
own paths, or to the historical `data/` layout when no profile is set; an
explicit environment variable overrides both.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/app/pdf_link.py</code></summary>

pdf_link.py: Where a citation stands in the source PDF: the deep link into
an external viewer, and the page drawn here with the quote marked.

A section's chunk text is refined by the LLM and differs from the raw PDF
text, so a verbatim `#page=N&search=...` term has to come from the raw
page text: the page-tagged `Segments`, or the PDF file itself.

The module is pure: no database access, no Streamlit import. Database
reads live in `db.py`.

</details>

<details>
<summary><code>docpipe/app/sandbox_service.py</code></summary>

sandbox_service.py: Localhost HTTP wrapper around llm-sandbox.

Each request runs the submitted code in a fresh, ephemeral container with
no network, resource limits, every capability dropped and an execution
timeout, so untrusted, possibly prompt-injected LLM code cannot reach the
host or the network. The server binds loopback only and is guarded by a
bearer token; it must not be exposed directly.

    POST /run   Authorization: Bearer <KWP_SANDBOX_TOKEN>
       body: {"code": "<python>", "context": {"var": <json-value>, ...},
              "timeout": <int>}
       ->   {"ok": bool, "stdout": str, "stderr": str,
             "exit_code": int|null, "error": str|null}
    GET  /health -> {"ok": true}    (no auth; readiness probe)

`context` entries are injected as pre-defined variables (JSON-decoded)
before the submitted code runs. Every setting is read from the
environment; see the module below for the names and defaults.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
