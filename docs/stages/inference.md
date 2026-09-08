# Asking the corpus

| | |
|---|---|
| **In** | The read-only corpus SQLite DB (Sections/Segments/Pages/Tables/Images/Embeddings/Documents) and global FAISS index that stage 6 built, the source PDF for quote location, and the configured LLM endpoint plus an optional code-exec sandbox over the network. |
| **Out** | A per-turn result dict (answer, citations, compute, examined, ...) handed back to the caller, plus one appended row per turn in a separate request-log SQLite database (`requests` table) -- the corpus DB itself is never written. |
| **Resumes on** | There is no batch to resume and no answer cache by design; to force fresh sources over the same question, trigger a re-check turn so answer_question's history-walk excludes every source already examined. |

docpipe.inference is the query side of the pipeline. Stages 1 through 6 (see README.md) build a corpus once, offline, on a GPU; this package answers questions against that corpus, one question at a time, with no GPU work of its own. The entry point is answer_question() in answer.py: a caller -- the Streamlit app in scripts/inference_app/, or a batch harvester -- hands it a task string, a document id, a set of scopes, and a Corpus (the open DB connection, the loaded FAISS index, a callable that embeds a query item, a callable that resolves a stored image path to a readable one, and an optional log connection), and gets back a dict with an answer, a list of citations, and enough bookkeeping (n_hits, examined, phrase, compute) for the caller to show its work or drive a follow-up turn. catalog.py answers a different question for the same page: not "what does the plan say" but "which plan am I even asking" -- it builds the picker's list of documents and lets a profile attach its own filters (facets) and detail panel on top of the plain Documents table the core knows about.

What it reads is exactly what stage 6 (docpipe.chunking) wrote. db.connect_readonly opens the corpus SQLite file through a `mode=ro` URI, on purpose: the comment states the reason directly, keeping the app from ever writing to the authoritative database or taking a write lock that would contend with the batch pipeline running against the same file. Every query in this stage only ever SELECTs -- from Sections, Segments, Pages, Tables, Images, Embeddings and Documents (db.get_candidate_faiss_ids, db.fetch_owner_content, db.request_item). Alongside the DB, faiss_store.load_global_index loads the one global FAISS index that stage 6 also built (an IndexIDMap over an IndexFlatIP), plus the id_to_pos table needed to reconstruct a stored vector from its faiss_id. When a citation needs to be shown as a highlighted rectangle rather than just quoted, pdf_locate.py opens the source PDF itself with PyMuPDF and matches the quote against the page's words. Because the corpus connection cannot write, logging goes to a second, separate SQLite file: request_log.connect opens it and request_log.log_request appends one row per turn to its own requests table (plan_id, query_text, mode, scopes, latency_ms, n_hits, n_citations, answer_hash, error_message).

Two things here would surprise someone expecting a normal vector-search service. First, there is no per-document index on disk -- faiss_store.retrieve rebuilds a small in-memory sub-index for the document being asked, on every call, by reconstructing just that document's candidate vectors (build_subindex) out of the global index and searching the result. The module docstring says why: the corpus lives in one global index, and scoping to a document happens by reconstruction, not by a second index file per document. Second, deduplication happens after the search runs, not before it: a table has two embeddings, table_text and table_vl (a figure likewise has figure_text and figure_vl), both pointing at the same Tables or Images row, and which of the two scores higher for a given query is not knowable until the search has actually happened. So retrieve() and rank_prepared() keep the best score per (owner_kind, owner_id) after scoring, rather than picking one embedding type to search up front -- filtering first would silently throw away whichever type happened to answer better.

The third decision sits inside answer_question's handling of a re-check ("schau noch einmal nach"). It does not simply exclude the sources of the turn right before it: it walks backward through history, folding every (owner_kind, owner_id) pair each prior turn examined into one exclude set, and stops only at the first turn along that chain that was not itself a re-check. Stopping one step earlier would exclude only the immediately preceding turn, and a second "look again" would then resurface exactly the sources the first re-check already showed -- the comment above that loop names this failure directly. The accumulated set is passed straight into faiss_store.retrieve as `exclude`, so a re-check is an ordinary retrieval that starts from a longer denylist, not a distinct search path.

Every turn costs at least two network calls to whatever OpenAI-compatible endpoint LLM_BASE_URL names -- a local vLLM server by default, model Qwen/Qwen3.5-122B-A10B-FP8 (the same default model name stages 4 and 5 use), though config.py's own comments are explicit that a hosted API or institutional gateway is the same client with a different URL and key. One call turns the task into a search phrase (llm_client.make_search_phrase); at least one more answers from the retrieved sources (llm_client.answer_from_sources), and there can be several of those, since a turn examines up to MAX_CHUNK_ATTEMPTS (10) sources across as many token-budgeted batches as chunker.pack_chunks needs to fit ANSWER_CONTEXT_TOKENS (10000). Each of those batches can spend up to CODE_EXEC_MAX_ROUNDS (2) calls to the code-exec sandbox and REQUEST_IMAGE_MAX (2) extra crop requests, and every citation flagged as read off an image can trigger up to READOFF_MAX_CALLS (3) more focused re-reads. No GPU is spent inside this package itself: corpus.embed is injected from outside, and per README it is docpipe.embedding's query-side embedder, kept apart from the batch embedder specifically so one question does not need a whole GPU. When the LLM endpoint is unreachable, a single call retries up to LLM_MAX_RETRIES (4 by default) with a short backoff before giving up, but every function that wraps those calls is written to never raise: make_search_phrase falls back to the raw task text, answer_from_sources comes back as {"found": False}, and answer_question ends the turn with an empty citation list and a logged error instead of an exception reaching the caller. code_exec.run_code degrades the same way: a disabled or unreachable sandbox, or a bad HTTP response, comes back as {"ok": False, "error": ...}, which the answer loop reads as "no calculation happened," not as a failed turn.

There is no batch-style resume, because there is no batch: one call is one turn, and nothing about it is checkpointed partway through. What might look like a missing cache is a deliberate choice -- request_log.py's own docstring states it: answers are not cached because a follow-up question is context-dependent, and a cache keyed on the question text alone would hand a later conversation an answer written for a different one. The one cache in the path is the query embedding (corpus.embed returns a cache_hit flag), and it is only ever reported in the result and the log, never used to skip retrieval or the LLM call. The way to make this stage redo work over the same document and question is the re-check path from the paragraph above: ask again in the phrasing make_search_phrase recognizes as a re-check, and the exclusion chain guarantees the next answer is read from sources the earlier pass had not already tried.

A short list of failure modes is defended against by name, not by accident. An empty hit list is logged as "No hits" and returned as answer=None before any LLM call is made on nothing. A quote offered as support for an answer is accepted only if it is a verbatim, whitespace- and case-tolerant span of at least 12 characters taken from the actual excerpt (llm_client._quote_is_grounded) -- short enough to reject a stray common word like "GmbH", long enough to still catch a real quote. An answer with no grounded citation is refused, and the log keeps "No grounded citations" (nothing supported it) distinct from "Answer ignored the response envelope" (the model answered outside the schema it was given): the comment in answer.py notes that collapsing the two would make a model failure indistinguishable from an absent fact after the run. A crop the model asks for by an unknown id, or one whose file is missing, comes back as None from _image_requester and is logged rather than left the model waiting on it. And pdf_locate._have_deps() checks once for PyMuPDF and rapidfuzz and logs loudly if either is missing, because the same check hidden inside a bare except ImportError used to be indistinguishable from a quote genuinely not on the page, and had already cost a whole run's citations their highlight rectangles before anyone noticed.

Since the graph route (kg_route.py) a question has a second answer path that costs no retrieval at all. Where the extraction stage's `--serialize` has written the plan's values as a Turtle graph, `answer_from_graph` first turns the question into coordinates -- one closed question per axis over the spec's own list, the harvest's one-request-per-field rule applied to the reader -- and then asks the graph with the same predicates the serializer wrote, interpolated from the profile's constants so the two cannot drift. What comes back is the number, its unit, the year node and the trust line the serializer left as a comment above the value: that line is not a triple (the shapes are closed, and an extra triple on a value node invalidates it), so `trust_comments` recovers it from the Turtle text by position. The route never guesses: an answer outside the list leaves the axis unbound, an unbound axis adds no constraint, and a value with no trust line withholds the whole answer with the reason `no_trust` rather than showing a bare number. Every way it can decline is one of five machine tokens (`REASONS`) that the profile words in the reader's language, and `check_notes` holds the two lists against each other when the route is built.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/inference/__init__.py`

Retrieval and grounded answering — usable from a UI or from a batch job.

### `docpipe/inference/answer.py`

answer.py – One retrieval-and-answer turn, with no user interface attached.

The chat app and the batch runner ask the same question of the same corpus;
only what they do with the progress and the result differs. So everything the
turn needs from the outside — the open corpus, how to embed a query, where an
image lives, and an optional progress reporter — is passed in.

Author: Felix Vossel

### `docpipe/inference/catalog.py`

catalog.py – How a corpus presents itself for selection.

Retrieval only ever needs a document id. Everything around that id — what a
document is called in the picker, which filters make sense over the corpus,
what to show about the selected one — is project knowledge. The core supplies
a plain default over the Documents table; a profile replaces it with its own
(profiles/<name>/catalog.py: CATALOG) and fills the facets it declared.

Author: Felix Vossel

### `docpipe/inference/faiss_store.py`

faiss_store.py – Global index loading + ephemeral sub-index retrieval.

The corpus is one global FAISS IndexIDMap(IndexFlatIP). A search is scoped to a
document + a set of embedding types by reconstructing just the candidate vectors
into a small in-memory IndexFlatIP and searching that.

Author: Felix Vossel

### `docpipe/inference/pdf_locate.py`

pdf_locate.py – Where a quote sits on the page of the source PDF.

One implementation, two callers: the app highlights the passage it shows, the
extraction stage records the same rectangles as the provenance of a value.
Duplicating it would have meant two answers to "where does this come from",
which is the one question the whole evidence chain exists to answer.

The match is fuzzy on purpose. The corpus text has been through extraction
and refinement, so it is never byte-identical to what PyMuPDF reads off the
page: ligatures, hyphenation, running heads and column order all differ.
Alignment finds the passage anyway; the score floor keeps it from pointing at
something else.

Author: Felix Vossel

### `docpipe/inference/code_exec.py`

code_exec.py – Client for the sandboxed code-execution service: POSTs LLM-written
Python to `sandbox_service.py` at `CODE_EXEC_URL`.

Never raises, so a sandbox outage degrades to "no calculation" rather than
breaking a query. The feature is OFF unless `CODE_EXEC_URL` is set (is_enabled()).

### `docpipe/inference/kg_route.py`

kg_route.py – Answer a question from the graph the harvest wrote, before the
documents are searched.

`--serialize` turns a plan's harvested numbers into Turtle: one value node per
coordinate tuple (the part of the plan it hangs under, the quantity class, the
carrier, the sector, the year, the aggregation), and above each node the
trust line and the evidence the serializer wrote as comments. A question that
names those coordinates has an answer in that graph which no retrieval has to
find and no model has to read off a page: the number, its unit, and how far
the run stands behind it.

What this route does NOT do is guess. Every coordinate is one closed question
over the spec's own list (one request per field, the harvest's own rule), an
answer outside the list leaves the axis unbound, and an unbound axis adds no
constraint. A value with no trust line is not shown with a blank badge: the
route says why it did not answer and the caller falls back to the documents.

Which graph, which query, which axes: the profile's. `Hooks` carries them in
the way `answer.Corpus` carries the corpus, and this module imports neither
`profiles` nor `streamlit`. rdflib is imported inside the functions that need
it, the convention docpipe/ontology.py states: the batch path never touches
this module, and the check that does can run on the cluster without it.

Author: Felix Vossel

[Back to the index](../README.md)
