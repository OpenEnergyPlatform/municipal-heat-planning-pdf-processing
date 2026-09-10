## Purpose

`docpipe.inference` is the query side of the pipeline. Stages 1 through 6
(see [How the parts fit together](../pipeline.md)) build a corpus once,
offline, mostly on a GPU; this package answers a question against that
finished corpus, one turn at a time, with no GPU work. Its
entry point is `answer_question()` in `answer.py`: a caller hands it a
task, a document id, a set of scopes and a `Corpus` (see Data model),
and receives an answer, its citations, and follow-up bookkeeping.
`answer_question` is called directly from two places: the Streamlit app
documented on [Chatting with the corpus](./app.md) (`app.py:147`), and
`compare.compare_documents` (`compare.py:100`), once per document,
itself reached only from the app. Nothing here imports a UI toolkit.

A question answered here is not the same finding as a value the
extraction stage (see [Extraction](./extraction.md)) writes to its
harvest: extraction reads a document once, exhaustively, against a closed
spec and stamps what it verified, while this package grounds one
free-text answer in a citation resolved at ask time. A second answer
path exists once the extraction stage's `--serialize` step has written a
plan's numbers as a graph (see [The knowledge graph](./graph.md)):
`kg_route.answer_from_graph` reads that graph directly, with no
retrieval or free-text generation.

## Position in the pipeline

| | |
|---|---|
| **In** | The read-only corpus SQLite database and global FAISS index stage 6, chunking (see [Chunking, embedding, database](./chunking.md)), wrote; the source PDF; the profile's wording and prompts; and, where configured, the graph stage's Turtle file (see [The knowledge graph](./graph.md)) and a code-execution sandbox. |
| **Out** | A per-turn result dict, plus one appended row per turn in a request-log database apart from the corpus; the corpus is never written. |
| **Resumes on** | Nothing. There is no batch and, by design, no answer cache (see Failure modes). |
| **Needs** | The LLM endpoint at `LLM_BASE_URL`; a query embedder supplied through `Corpus.embed` (this package runs no embedding model, `faiss_store.py:22`); optionally `CODE_EXEC_URL` and a profile's knowledge-graph hooks. |

This package sits downstream of stage 6, the last stage to write under
`results/` (see [How the parts fit together](../pipeline.md)); it has no
stage after it in the batch chain, a terminal, on-demand read path.

## Method

### Building the query item and its search anchor

`answer_question` (`answer.py:95`) picks one of three modes: `image_only`
searches on an uploaded image alone, an image with text adds a
caption-style anchor, and text alone anchors on the plain task
(`answer.py:118-135`). The anchor, `llm_client.make_search_phrase`, is a
HyDE-style construction: a short hypothetical passage written as it
would appear in the corpus, not a question. Whatever non-empty phrase the
model writes is used as the anchor; the function falls back to the raw
task text only on a transport or parse error, or an empty reply, and it
never raises (`llm_client.py:273-309`). The same call sets `recheck`, true
only when the model marks the task a repetition and history is
non-empty (`llm_client.py:307`); when true, `answer_question` walks
history backward, folding every `(owner_kind, owner_id)` pair each turn
examined into one exclude set, stopping at the first non-recheck turn
(`answer.py:144-150`).

### Retrieval narrowed to one document

`faiss_store.retrieve` rebuilds a small in-memory `IndexFlatIP` from the
document's own candidate vectors (`build_subindex`,
`faiss_store.py:60-94`), reconstructed out of the one global FAISS index
stage 6 wrote; no per-document index exists on disk. A table's two
embeddings (`table_text`, `table_vl`) can both surface for one row;
dedup after the search keeps the higher-scoring one per
`(owner_kind, owner_id)` (`faiss_store.py:308-365`); results are capped
at `TOP_K`.

### Packing sources into token-budgeted batches

The top `MAX_CHUNK_ATTEMPTS` hits are packed by `chunker.pack_chunks`
into batches under `ANSWER_CONTEXT_TOKENS` tokens each
(`chunker.py:94-116`), greedily, one oversized hit getting its own chunk
instead of truncation. Token counts come from the tokenizer
named by `LLM_TOKENIZER_ID`; a char/4 heuristic serves as an offline
fallback only, since German prose runs 3.0 to 3.5 characters per token,
denser than a flat divide by 4 assumes (`answer.py:178-181`).

### Answering across batches, with computation and image requests

For each batch, `llm_client.answer_from_sources` extends a running
answer with crops of up to `ANSWER_MAX_IMAGES` items, so a chart value
can be read. `code_exec.py` runs the calculation feature: when
`CODE_EXEC_URL` is set, `run_code` posts the model's Python plus
markdown context built by `answer._code_context` (`answer.py:62-74`)
and parses back `{"ok", "stdout", "stderr", "exit_code", "error"}`
(`code_exec.py:22-54`), never raising (see Failure modes). An image
requester may separately return a crop the section text only points at,
through `db.request_item`. Both draw one shared round budget,
`CODE_EXEC_MAX_ROUNDS` plus `REQUEST_IMAGE_MAX` (`llm_client.py:577`); a
repeated crop id stops the loop and forces an answer
(`llm_client.py:598-605`). The loop stops once a batch reports complete
with a citation accepted (`answer.py:249-250`).

### Grounding, image refinement and finishing the turn

Every claim must point at a batch index and either a verbatim quote or,
for an attached image, a reading. A text quote is accepted only through
`llm_client.grounded_quote`, a match of at least 12 characters against
the excerpt shown (`_quote_is_grounded`, `llm_client.py:145-156`). An
image-based support, `visual_reading` (`llm_client.py:499-516`), is
accepted only when its index was among the crops attached to the call
and the reading is at least 8 characters, so background knowledge alone
cannot count as grounded evidence. Citations are deduplicated by
`(owner_kind, owner_id)` (`answer.py:241-244`); an answer with no
accepted citation is refused outright, and the log distinguishes "No
grounded citations" from "Answer ignored the response envelope"
(`answer.py:299-306`).

Every visual citation is then re-read in a focused, single-image call,
`llm_client.read_off_image`, up to `READOFF_MAX_CALLS` per turn: a first
pass often misreads a chart (`llm_client.py:439-444`). Readings fold
back through `revise_with_readings`, unchanged on failure
(`llm_client.py:482-496`).
A JSON answer then goes through `llm_client.format_as_json`
(`llm_client.py:656-663`), the only call here with no failure handling
of its own (see Failure modes); every turn is logged through
`request_log.log_request` (`answer.py:325-330`).

### The profile's wording contract

Every phrase and label the loop wraps around the model comes from the
active profile through `wording.py`. `phrases()` checks a profile's
`PHRASES` dict against `REQUIRED`, a frozenset of 29 keys
(`wording.py:22-32`). `llm_client.py` calls `phrases()` at module level
(`llm_client.py:47`), so this package needs an active profile to import
(see Failure modes).

### The knowledge-graph route

`kg_route.answer_from_graph` (see Purpose) is offered once the
extraction stage's `--serialize` step has written a plan's numbers as a
Turtle graph. `hooks(profile)` reads a profile's SPARQL query,
coordinate axes, loaded spec, plan-IRI lookup, value-binding builder,
and trust/reason wording, returning `None` where `kg.VALUE_QUERY` is
absent, so `scenarios` gets no route at all (`kg_route.py:95-122`).
`to_coordinates` asks one closed
question per axis over the spec's own vocabulary, through
`llm_client.choose` in the app (`llm_client.py:202-225`,
`app.py:191-194`); an answer outside the vocabulary leaves the axis
unbound (`kg_route.py:174-204`), and the route proceeds only once a
coordinate lands on one of the `DECIDING_AXES`, quantity, scenario or
year (`kg_route.py:61`). It runs the profile's SPARQL and reads a
value's evidence and trust from the serializer's comment lines,
recovered from the raw Turtle text (`kg_route.py:148-171`); a value with
no trust comment withholds the whole answer (see Failure modes, and
[How much of a value the run can stand
behind](../contract/trust.md)). Every decline is one of five closed
tokens, `REASONS` (`kg_route.py:57`) (see Failure modes);
`answer_from_graph` returns only four, the fifth, `no_graph`, left to
the caller.

### Comparing several documents

`compare.compare_documents` asks the same question of up to
`COMPARE_MAX_DOCUMENTS` documents (`config.py:56`); documents beyond the
cap are named in `dropped`, not silently left out (`compare.py:93-97`).
Each document keeps its own retrieval. Once at least two produced a
grounded answer, `llm_client.compare_answers` compares the finished
prose, given only each label and its `answer_text`, never a source
passage (`compare.py:64-75`, `compare.py:108-113`). A document that
answered nothing keeps its row (see [What a coordinate's state
means](../contract/states.md)).

## Data model

`Corpus` (`answer.py:37-47`) is the bundle every turn works on, a
dataclass this package never builds:

| field | holds |
|---|---|
| `conn` | the read-only corpus connection, opened by `db.connect_readonly` |
| `index`, `id_to_pos` | the global FAISS index and its faiss_id-to-position map |
| `embed` | a callable, a query item to `(vector, came_from_cache)` |
| `resolve_image` | a callable, a stored image path to a readable path or `None` |
| `log_conn` | an optional connection to the request-log database |

`answer_question()` returns one dict per turn, most keys fixed in the
function's own docstring (`answer.py:99-107`); `requested` is not among
them (`answer.py:111`, populated `answer.py:269`):

| key | holds |
|---|---|
| `answer`, `answer_text` | the final answer (JSON or prose) and the prose kept for follow-up; both `None` when nothing was grounded |
| `citations` | the accepted, deduplicated citation list, below |
| `n_findings` | the number of accepted citations, `len(citations)` |
| `as_json` | whether the caller asked for a JSON-formatted answer |
| `phrase`, `recheck`, `n_excluded` | the search anchor, whether this is a recheck, and how many prior sources it excluded |
| `n_hits`, `n_batches`, `examined` | retrieval and batching bookkeeping; `examined` feeds a later recheck's exclude set |
| `compute`, `requested` | the sandbox runs made, and the block ids of delivered crop requests |
| `cache_hit` | whether the query embedding came from `query_cache` |

One citation carries `db.fetch_owner_content`'s fields (`db.py:176-256`)
plus what `answer.py` adds:

| field | holds |
|---|---|
| `owner_kind`, `owner_id` | `section`, `table` or `figure`, and that row's id |
| `title`, `text` | the resolved title and body; a section's placeholders are annotated with their caption, a table's or figure's body is unchanged |
| `page_number`, `image_path`, `section_number`, `section_title`, `document_id` | citation/scoping fields; `image_path` relative to `IMAGE_ROOT`, `None` for a section |
| `caption_stored`, `section_id`, `block_id` | table/figure owners only: the stored caption before title resolution, the section's id, and the block id (`db.py:242, 246-247`) |
| `quote`, `visual`, `requested` | the accepted quote or reading, whether from an image or crop request, added in `answer.py` |

`kg_route.answer_from_graph` returns `{route, reason, values,
coordinates}` (`kg_route.py:260-293`): `route` is `"kg"` or `"rag"`,
`reason` one of `REASONS` or `None`, `values` one dict per matching row
with its `evidence` and `trust`.

Two more SQLite files stay apart from the corpus: `request_log.py`'s
`requests` (`request_log.py:17-32`, one row per turn: `plan_id`,
`query_text`, `mode`, `scopes`, `latency_ms`, `n_hits`, `n_citations`,
`answer_hash`, `error_message`, `cache_hit`), and `query_cache.py`'s
`query_cache` (`query_cache.py:18-24`: `query_key`, a sha256 of the
query mode, text and image bytes, `vector`, `created_at`).

The logged `cache_hit` column is not the turn's own value: `_log` always
calls `request_log.log_request` with `cache_hit=False` (`answer.py:330`),
so a persisted row never reflects the returned dict's `cache_hit` key.

## Configuration

Every name is read once, at import, from `docpipe/inference/config.py`
unless "where" names another file: env vars and module constants only,
nothing tied to a host name or shared drive.

| name | kind | default | effect | where |
|---|---|---|---|---|
| `LLM_BASE_URL`, `LLM_MODEL` | env vars | `http://localhost:8000/v1`; `Qwen/Qwen3.5-122B-A10B-FP8` | the endpoint every call reaches; the model name per completion | `config.py:19-20` |
| `LLM_API_KEY`, `LLM_TIMEOUT` | env vars | `EMPTY` (or `UOS_API_KEY`), `180` s | bearer key and client HTTP timeout | `config.py:21-22` |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` | env vars | `0.1`, `2048` | sampling temperature and `max_tokens` per completion | `config.py:23-24` |
| `LLM_TOKENIZER_ID` | env var | equal to `LLM_MODEL` | tokenizer for token-budget accounting | `config.py:27` |
| `LLM_MAX_RETRIES`, `LLM_STUB_MODE` | env vars | `4`, off | retries of one failed call; canned replies with no endpoint call | `config.py:30, 32` |
| `SCOPE_*` (6), `SCOPE_TO_EMBEDDING_TYPES`, `ALL_SCOPES`, `VISUAL_SCOPES` | module constants | 6 fixed strings, e.g. `"Body text"` | the `scopes` vocabulary, its embedding-type map, and the visual-only subset `scopes_are_visual` (`answer.py:50-52`) checks | `config.py:73-99` |
| `TOP_K`, `MAX_CHUNK_ATTEMPTS` | env vars | `50`, `10` | candidates kept per retrieval; sources examined per turn | `config.py:37, 39` |
| `ANSWER_CONTEXT_TOKENS`, `ANSWER_MAX_IMAGES` | env vars | `10000`, `4` | token budget per answer batch; crops attached to one answer call | `config.py:42, 45` |
| `ANSWER_IMAGE_MAX_SIDE`, `READOFF_IMAGE_MAX_SIDE` | env vars | `1280`, `1600` | crop downscale side, answer call and read-off | `config.py:46, 59` |
| `REQUEST_IMAGE_MAX`, `READOFF_MAX_CALLS` | env vars | `2` (`0` off), `3` | crop requests per batch; focused re-reads of an image value | `config.py:52, 58` |
| `COMPARE_MAX_DOCUMENTS` | env var | `5` | documents one comparison may ask | `config.py:56` |
| `CODE_EXEC_URL` | env var | empty | sandbox address; empty means off | `config.py:64` |
| `CODE_EXEC_TOKEN`, `CODE_EXEC_TIMEOUT` | env vars | empty (or `KWP_SANDBOX_TOKEN`), `45` s | bearer token and HTTP timeout for the sandbox | `config.py:65-66` |
| `CODE_EXEC_MAX_ROUNDS` | env var | `2` | sandbox runs per batch, shared with `REQUEST_IMAGE_MAX` | `config.py:68` |
| `COORDINATE_PROMPT_ID`, `DECIDING_AXES` | module constants | `"kg/coordinate"`, (quantity, scenario, year) | the axis-question prompt id and the axes that gate the graph route | `kg_route.py:45, 61` |
| `MIN_SCORE`, `MAX_LINES` | module constants | `55.0`, `10` | fuzzy-match floor and highlight-rectangle cap for a located quote | `pdf_locate.py:26-27` |

## Failure modes

An empty hit list is logged as "No hits" and `answer` returns `None`
before any LLM call runs (`answer.py:170-173`); where hits exist but
nothing could be grounded, `answer` comes back `None` (see Method;
`answer.py:299-306`). An unknown or missing crop id comes back
`None` and is logged (`answer.py:77-92`); a repeated id stops the loop
and forces an answer (`llm_client.py:598-605`).

`pdf_locate._have_deps()` checks once for PyMuPDF and rapidfuzz and logs
an error (`log.error`) if either is missing; when it fails, quote
location is off for the whole run and every citation loses its
highlight rectangles (`pdf_locate.py:33-56`).

Inside `llm_client._chat_json`, a malformed reply or transport error is
retried up to `LLM_MAX_RETRIES` with backoff capped at 10 seconds before
raising `RuntimeError` (`llm_client.py:119-199`); callers above it
degrade instead: `make_search_phrase` falls back to the raw task, and
`answer_from_sources` comes back `{"found": False}`. `format_as_json`
has no such wrapper and can raise past this package
(`llm_client.py:656-663`; `answer.py:308-314`). `code_exec.run_code`
degrades without raising: any transport or JSON failure comes back
`{"ok": False, "error": ...}`, read as no calculation, not a failed turn
(`code_exec.py:36-62`).

`kg_route` fails closed on missing trust, withholding the whole answer
with reason `no_trust` (`kg_route.py:286-291`). A profile that leaves a
`REASONS` token unworded, or words an extra one, raises `LookupError`
when the route is built (`kg_route.py:80-92`); a Turtle fragment with no
`@prefix` line is refused outright (`kg_route.py:139-141`).

The wording contract fails the same way: a profile whose `PHRASES` dict
is missing a required key raises `LookupError` at the first check
(`wording.py:56-58`), and no active profile raises `LookupError` from
`wording._component` (`wording.py:35-39`) for any lookup a turn needs.
`llm_client.py` resolves its own phrases at import
(`llm_client.py:47`), so the
missing-profile case can surface as an import error before a turn is
asked.

Answers are deliberately not cached: a follow-up is context-dependent,
and a cache keyed on the question text alone would misfit a later
conversation (`request_log.py:1-8`). The only cache in the path is the
query embedding, reported in `cache_hit` but never used to skip
retrieval or the LLM call.

## Measured behaviour

Reconstructing a document's candidate vectors as one batched call rather
than one `reconstruct()` per vector matters at scale: a plan carries
about 470 candidate vectors, and the batched call measured 0.421 to
0.277 seconds over 50 repetitions, 8.4 milliseconds per document instead
of 5.5 (`faiss_store.py:76-81`).

The grounding gate's floor of 12 characters (`llm_client.py:145-156`) and
the image-reading floor of 8 characters (`llm_client.py:499-516`) are
sized the same way, long enough to reject a short stray word standing
in for evidence; the code names "GmbH" as the concrete case the
12-character floor rejects.

`pdf_locate`'s match floor, `MIN_SCORE = 55.0` (`pdf_locate.py:26`), is a
`rapidfuzz.fuzz.partial_ratio_alignment` score, not a percentage of the
page: the corpus text is never byte-identical to what PyMuPDF reads off
the page, and the floor is tuned to survive that drift, not to demand
an exact match.

## Verification

The turn's core contract:
`test_no_hits_returns_an_empty_answer`,
`test_grounded_answer_carries_its_citation`,
`test_an_ungrounded_answer_is_refused`,
`test_visual_scopes_ask_for_a_caption_style_anchor`,
`test_progress_is_optional_and_silent_by_default`
(`tests/test_answer_core.py`).

The recheck exclusion chain: `test_recheck_excludes_what_earlier_turns_read`
(`tests/test_answer_core.py`);
`test_batched_retrieval_matches_probe_by_probe`,
`test_batched_retrieval_honours_a_prior_exclusion`,
`test_no_probes_and_no_candidates_are_both_empty`
(`tests/test_faiss_retrieve_many.py`).

Crop requests:
`test_the_model_can_ask_for_a_crop_and_gets_it`,
`test_an_unavailable_crop_still_lets_the_model_answer`,
`test_asking_twice_for_the_same_crop_stops_the_loop`,
`test_the_action_is_not_offered_when_it_is_switched_off`
(`tests/test_image_request.py`).

Comparing documents:
`test_every_selected_document_gets_its_own_row_and_its_own_retrieval`,
`test_a_document_that_answered_nothing_keeps_its_row`,
`test_the_comparison_call_never_sees_a_source_passage`,
`test_one_answer_is_not_a_comparison`,
`test_more_documents_than_the_budget_are_named_not_dropped_quietly`,
`test_a_follow_up_searches_past_what_that_document_showed`
(`tests/test_answer_core.py`).

The picker's filters and its fallback:
`test_current_documents_only_unless_asked`,
`test_a_document_covering_several_values_matches_any_of_them`,
`test_without_a_profile_the_generic_catalog_is_used`
(`tests/test_catalog.py`).

The wording contract: `test_a_profile_that_answers_provides_all_of_it`
(`tests/test_wording.py`). The search anchor is the sentence the model
wrote: `test_the_search_phrase_is_the_sentence_the_model_wrote`
(`tests/test_inference_app.py`).

The graph route:
`test_the_query_names_only_predicates_the_serializer_writes`,
`test_the_trust_line_is_not_in_the_graph_and_is_recovered_from_the_text`,
`test_a_value_without_a_trust_line_falls_back_instead_of_rendering`,
`test_the_answer_space_is_the_specs_own_list`,
`test_a_synonym_resolves_through_the_axis_not_by_string_match`,
`test_unstated_leaves_the_axis_unbound`,
`test_an_out_class_is_never_bound_as_a_coordinate`,
`test_every_reason_the_route_gives_is_reached`,
`test_every_fallback_reason_has_a_sentence`,
`test_a_fragment_without_its_prefix_header_is_refused_on_load`
(`tests/test_kg_route.py`).

## Modules

`__init__.py` re-exports `Corpus` and `answer_question`, the package's
only public surface; `answer.py` holds both, the turn's entry point and
the dataclass every step reads. `answer_question` is called directly by
`scripts/inference_app/app.py` and by `compare.py`'s
`compare_documents`, itself reached only from the app.

`catalog.py` holds the generic `Catalog` class, `load_catalog`,
`facet_options` and `apply_filters`. `profiles/kwp/catalog.py` and
`profiles/scenarios/catalog.py` each extend `Catalog` with their own
facets; the app calls `load_catalog` to pick between them.

`chunker.py` holds `pack_chunks`, the token-budgeted batching,
`citation_label`, the source label the answer text and model's excerpt
prompt use, and `get_tokenizer`, the real tokenizer `pack_chunks`
prefers over the char-count heuristic. `answer.py` calls all three; the
app also calls `citation_label` directly.

`llm_client.py` holds every call to the LLM endpoint: `make_search_phrase`,
`answer_from_sources`, the grounding checks `grounded_quote` and
`visual_reading`, `read_off_image`, `revise_with_readings`,
`format_as_json`, `compare_answers`, and `choose`. `answer.py` calls all
but the last two; `compare.py` calls `compare_answers`, and the app
calls `choose` directly (see Method).

`faiss_store.py` holds `load_global_index`, `retrieve` and
`build_subindex`, the only code touching the global FAISS index. The app
calls `load_global_index` at startup; `answer.py` calls `retrieve`, and
so does the extraction stage's `runner.py`.

`db.py` holds the SQL: `connect_readonly`, the candidate-vector query
`faiss_store.py` reconstructs from, `fetch_owner_content` and
`request_item`. Called by `faiss_store.py`, `answer.py`, the app, and
the extraction stage's `runner.py` (as `inference_db`).

`wording.py` holds `REQUIRED`, `phrases` and `readoff`, the profile's
phrase contract described in Method and Failure modes. Called by
`answer.py`, `chunker.py` and, at module level, `llm_client.py`.

`code_exec.py` holds `is_enabled` and `run_code`, the sandbox client.
Called by `answer.py` and, for the same feature, `runner.py`.

`compare.py` holds `compare_documents` and `summary`, the multi-document
path. Called only by the app.

`kg_route.py` holds `hooks`, `answer_from_graph`, `load_graph`,
`by_axis`, `trust_level` and `REASONS`, the graph-route contract
described in Method. Called only by the app.

`request_log.py` holds the `requests` table and `log_request`. Called by
`answer.py`'s `_log` helper and directly by the app.

`query_cache.py` holds the `query_cache` table, `get`, `put` and
`make_key`. Called by the app and, for the same lookup, `runner.py`.

`pdf_locate.py` holds `_have_deps`, `quote_rects`, `page_words` and
`rects_from_words`, the quote-to-rectangle match described in Failure
modes. Called by `scripts/inference_app/pdf_link.py` and the extraction
stage's `runner.py`.

`config.py` holds every name in the Configuration table above, read once
at import by every module in the package;
`scripts/inference_app/config.py` re-exports the names the app reads.
