## Purpose

`docpipe/app/` is the Streamlit front end over `docpipe.inference` (see
[Asking the corpus](inference.md)); `app.py` is the only module in `docpipe/`
that imports Streamlit. Where the numbered stages turn PDFs into a corpus once,
offline, this turns that corpus into a running chat: a person opens a
profile's database and FAISS index, asks a question in ordinary language, and
reads back an answer made of statements, each grounded in a quote, with
citations that trace to a page and, where possible, to the passage on it. It has
two pages:

- the chat, over one document, several (each asked by itself, side by side, then
  compared) or the whole corpus;
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
chat runs on the built-in `default` profile: its English words, and its prompts
and phrases for the answer loop, so the first question is answered instead of
stopping (`wording.chat_profile`, the one place that falls back, with one
warning per process in the log). The app shows one line at the top saying so.
A profile is named with `--profile`, the `profile` key of `docpipe.toml` or
`DOCPIPE_PROFILE`. Only the chat does this: `prompts.load` and the stages that
write a corpus still need a profile, because a forgotten flag there would start
a real run on the wrong prompts. A profile that is named is never replaced.

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
corpus, the search scopes, the answer format and, where the harvest or the
graph can answer, the answer route. The scopes are those whose
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
   not only an image, the harvest answers, side by side with step 2 and shown
   above its answer. `values_route` finds the
   values the question asks for (`docpipe/serve/values.py`; the parameter is
   chosen with the profile's own question for a person's question,
   `chat_parameter_question`, and not with the extraction's question about a
   number), and `answer.answer_from_values` answers the question from the
   passages those values were read from, each passage once. The model decides
   which of their numbers answer it (the total or a carrier, which variant),
   and every statement stands its check against its passage as in a document
   turn; its citations show their pages the same way. Under the answer stand
   only the values it uses (`values_route.used_values`: a statement quotes the
   value's quote, or a part of it that names the value as the plan writes
   it), one line each in the profile's words (number, coordinates, document
   and page, level), with their coordinates by name and the reasons of their
   level, in words (`AXIS_NAMES`, `reason_*`), in an expander. A question that
   names no parameter gets nothing here. `INFERENCE_VALUES_LEVEL` leaves out
   values below a trust level and `INFERENCE_VALUES_LIMIT` caps how many
   values, and so passages, the answer is given.
2. The answer from the documents, asked at the same time: a search anchor, the
   query embedding, retrieval, and the answer across token-budgeted batches.
   Where the model has more than one place for requests, the next batch is sent
   ahead onto a free place, and one more request drops what a batch sent ahead
   said again; the batches are taken in their order all the same (see [Asking
   the corpus](inference.md)). The two steps are two threads that read the app's
   cached resources and show no stage of their own (`_in_this_run`), so one
   spinner stands for both; the query embedding stays one at a time.
   Retrieval is by meaning and, where a word index exists beside the database
   and is current, also by word, and the two rankings are merged
   (`docpipe/inference/hybrid.py`). `INFERENCE_LEXICAL=0` turns the word
   search off. The model answers in statements, each with its own quote, and a
   statement is shown only if its quote stands in the passage it cites (see
   [Asking the corpus](inference.md)). The page shows of that:
   - The answer, which is the statements that stood. One statement is a
     sentence, two or more are a list, and each ends with the number of its
     citation, `[1]`. A JSON answer has no such marks, and its citations carry
     no number.
   - Directly under the answer, one sentence in the profile's words
     (`statements_dropped`) that says how many of the statements the model made
     were removed because their quote does not stand in the source they cite,
     "2 of 5 statement(s) removed". It does not say which or why: the cause per
     statement goes to the log. It stands also where every statement was
     removed. The number made includes the statements a repeats request took
     out, which the sentence does not count as removed.
   - Where sources were found and no statement stood there is no answer, and the
     page says one of two things. `nothing_backed` says the examined sources hold nothing that backs
     an answer: statements were made and none stood, or the model's replies were
     read and held none. `answer_unreadable` says the model's replies could not
     be read, with the cause of each request (`answer_reply: cut_off`), and that
     nothing can be said about what the sources contain: no statement was made
     and the requests that would have made them stayed unreadable, so the
     sources were not looked at, which is not that they hold nothing.
   - Under the answer, where other requests of the turn stayed unreadable, a
     warning (`replies_unreadable`) with their number and causes: a search anchor
     that fell back to the question, a focused read-off that kept the first
     reading, a batch of sources whose reply could not be read while another
     batch made statements, a JSON answer that could not be made. It says that
     what they would have said is missing from the answer. A request that the
     reply itself names (`answer_unreadable`) is not repeated in it.
   - Each citation shows its number, `[n]`, before its label. A value
     calculated by the sandbox says which run printed it (`computed_from`), and
     the calculation expander numbers its runs in the order the turn made them
     (`run_label`, "Run 1", "Run 2"), so that the number in the caption can be
     found. A value read off a figure keeps its own caption.
3. With several documents selected there is no values step and no joint
   search: `run_comparison` asks each document by itself, all of them side by
   side under one spinner, and one more call compares the finished answers, since one top-k over several plans would
   give the longest chapter most of the slots. The comparison is given only
   the statements that stood, as plain text. Each document's own row carries its
   own caption of removed statements and its own warning of unreadable requests,
   and a row with no answer says `answer_unreadable` where its replies could not
   be read, `no_hits` where nothing was retrieved, and `document_nothing`
   (nothing in this document backs an answer) only where its replies were read.
   The comparison call's own unreadable requests are in a warning above the
   table.

Over the whole corpus every source names its document (the label of the
catalog, or the name of the document's file without its ending where it gives none), only the
current version of a document answers, and the conversation is one of its own.
The values of step 1 are not narrowed that way: they come from every
harvested document, older versions included, and the help text of the
checkbox (`whole_corpus_help` of the profile) says so.

The answer route (`route` of the profile's UI words) chooses where an answer
comes from. Automatic is both of the steps above at once: the harvest's answer
above the answer from the documents. Harvest answers from the harvest alone, and where
it holds nothing it says why in the profile's words (`values_no_parameter`,
`values_no_values`, one per reason of `values_route.REASONS`); the
documents are not asked, because a silent fallback would hide that the
chosen source holds nothing. Knowledge graph answers from the graph
`--serialize` wrote (`INFERENCE_KG_TTL_PATH`) through `kg_route`, or says
why not in the profile's `ROUTE_NOTES`; it is offered only where the profile
contributes to the graph route and the file is there, and only for one
document, because the graph is asked per plan. Documents searches the
documents alone. `routes_offered` decides what is offered, and where only the
documents can answer no switch is shown. A comparison of several documents
always searches the documents.

## The review page

The review page is how the decisions behind
[a harvest's precision and recall](evaluation.md) are made. The person gives
a name and works through the queue of rows nobody has decided yet: for each
field of the row (the value, the unit, every coordinate) the value, its quote
and the page it was read on are shown, drawn as a citation's page is (below),
and the field is marked correct or wrong, with what is right where it is
wrong. Two more
forms record that the document states a value the harvest lacks, and that
somebody has read a whole document for one parameter. All three append to
`gold.jsonl` (`INFERENCE_GOLD_PATH`, by default beside the harvest directory,
where `gold.path_beside` puts it for `evaluate` and `--serialize` too);
nothing here changes the harvest. A graph written later keeps a decision beside
its value only if the file lies beside the harvest (see [the knowledge
graph](graph.md)): `--serialize` does not read `INFERENCE_GOLD_PATH`.

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
logged once. Tables and figures get no rectangles.

The harvest's answer shows its citations' pages the same way, and so does
the review page for the value it asks about (`_value_page`): the value's
provenance names the passage's kind and id, so a value read from a section
has its quote located and marked, and one read from a table or a figure is
shown on its page unmarked. A value whose document the database does not
know shows no page.

Every page the app shows goes through one function, `_source_page`: a
citation of the answer from the documents, a citation of the harvest's
answer and the value the review page asks about. The page is drawn here as
above, and where a PDF area is configured a button opens the whole PDF at
that page in a tab of its own. Where the raw words of a section's quote do
not match its segments, which happens where the text layer glued a stray
mark to a word ("101BAuftraggeber"), `_cited_page` looks for the quote in
the PDF itself on the pages the section's segments stand on, with the same
search that draws its mark, and the first page that holds it is the page;
where none does, the page stays the citation's own and is shown unmarked.

The viewer is off by default. `PDF_URL_PREFIX` and `PDF_VIEWER_PREFIX` are
both empty, and nothing ships that serves a PDF or a viewer. A deployment
sets `PDF_URL_PREFIX` to the URL path the PDFs are served under and
`PDF_VIEWER_PREFIX` to the path of a pdf.js viewer; both must be of the
app's own origin, which pdf.js requires. The button then opens the pdf.js
viewer, and the rectangles reach it as the `&mhl=` parameter:
`pdfjs_overlay.js`, which a deployment copies into the viewer and references
from its `viewer.html`, draws the boxes (assuming an unrotated page). With
only `PDF_URL_PREFIX` set, the button goes into the browser's own viewer,
and with a missing library or a match scoring under 55 the link loses its
phrase or rectangles.

## Configuration

Every name is a setting: `docpipe config --stage chat` lists them with their
values, and the project file takes them under `[chat]`. The paths default to
the profile's own.

| setting | what it is |
|---|---|
| `INFERENCE_DB_PATH`, `INFERENCE_INDEX_PATH`, `INFERENCE_IMAGE_ROOT`, `INFERENCE_PDF_ROOT` | the corpus database (read-only; `docpipe serve` reads it too, for its passage search, and has no default), the FAISS index, the root of table and figure images, the folder of source PDFs the cited page is drawn from |
| `INFERENCE_HARVEST_DIR`, `INFERENCE_GOLD_PATH`, `INFERENCE_VALUES_LEVEL`, `INFERENCE_VALUES_LIMIT` | the harvest the values and the review page read, the decisions file the review page appends to (`--serialize` reads the one beside the harvest and ignores this setting), how many and how trustworthy a value must be to be shown |
| `INFERENCE_LEXICAL` | search by word beside the search by meaning where a word index exists |
| `INFERENCE_KG_TTL_PATH` | the Turtle file the knowledge-graph route reads; the route is offered only where it exists |
| `QUERY_CACHE_PATH`, `REQUEST_LOG_PATH` | the two files of the app's own |
| `PDF_URL_PREFIX`, `PDF_VIEWER_PREFIX` | where the PDFs and a pdf.js viewer are served from the app's own origin; with both set the button beside every drawn page opens the PDF in pdf.js with the quote boxed, with only the first in the browser's own viewer; both are empty by default |
| `COMPARE_MAX_DOCUMENTS`, `TOP_K`, `MAX_CHUNK_ATTEMPTS`, `ANSWER_CONTEXT_TOKENS` | how many documents one comparison asks, and the retrieval and answer budgets |
| `LLM_MODELS`, `LLM_SLOTS_PER_MODEL` | the model names at the endpoint that requests are spread over (empty is `LLM_MODEL` alone) and how many requests each takes at once; the default is one place in all, the plain client and one request after the other |
| `CODE_EXEC_URL`, `CODE_EXEC_TOKEN`, `CODE_EXEC_MAX_ROUNDS`, `CODE_EXEC_TIMEOUT` | the calculation sandbox; an empty URL turns the feature off |

`config.py` re-exports every retrieval and model setting it shares with
`docpipe.inference.config` and does not redefine one: two copies of a value
like `LLM_BASE_URL` are how a deployment ends up talking to the wrong endpoint.

The model requests of a turn carry the reasoning fields the other stages send,
`LLM_ENABLE_THINKING` and `LLM_REASONING_EFFORT`, and always send their reply
schema as the grammar of the request. `LLM_MAX_RETRIES` is the number of
attempts one request gets after a reply that could not be read or a failed call,
and `LLM_SCHEMA` decides only whether a JSON answer in the user's own shape is
asked for (see [Asking the corpus](inference.md)). `docpipe doctor --stage chat`
asks the server whether it takes these fields (see [the
command](command.md)).

## Data the app keeps

Chat history lives in `st.session_state["chat_history"]`, a list of
role and content dicts. An assistant entry carries what the turn produced:
`citations`, `phrase`, `values`, `compute`, the counts (`made`, `dropped`) and
the faults the caption and the warning under the answer are drawn from, or
`rows` for a comparison. `turns_by_doc` maps a document id (the whole corpus
under `None`) to its last five turns, kept apart per document so that a "check
again" in one plan never excludes another's sources, and a failed turn is kept
because that follow-up is asked precisely after one. What a turn keeps for a
follow-up is its question, its anchor, the sources it examined and its answer as
`answer_text`, the statements that stood without list marks and numbers, so a
statement that was removed is in no later request.

`QUERY_CACHE_PATH` holds one table, `query_cache` (a key, the vector as a
float32 blob, a timestamp). The key is over the embedding model and the
vector size as well as the query, read from the configuration at the time of
the call, so a vector of another model is never found for the same question
and one file serves whichever model is configured next. Entries written under
a key without them match nothing and are embedded again; a benchmark
recording made earlier whose query vectors live in its own query cache no
longer replays without a model and has to be recorded again. `REQUEST_LOG_PATH` holds one table, `requests`
(plan, query text, mode, scopes, timestamp, latency, hit and citation counts,
the counts of statements made and removed, a truncated hash of the answer,
error, `cache_hit`). No answer is cached: a
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
- A model whose replies cannot be read does not stop a turn. A reply that is
  not the one JSON object is asked again with its cause named, a reply that was
  cut off is split or given more room, and nothing is repaired; what still
  cannot be read is shown as such, with its cause, and written to the request
  log (`Reply unreadable`, `n request(s) unreadable`), never as "nothing
  found".
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
and batch against single. It is run by a person.
