# 5. Reading the pictures

## Purpose

Stage 2 of preprocessing crops every table and figure it detects on a page
into its own PNG under a document's `images/` directory, and Stage 3 leaves a
placeholder token, such as `[p12_tbl0]`, in the section's prose wherever one
of those crops was located (`docpipe/preprocessing/stage2_layout.py` assigns
the id and file name; see [preprocessing](preprocessing.md)). A placeholder
token is not text a retrieval system can search or a model can answer from.
This stage, implemented as `docpipe.visuals`, supplies that text: it sends
every cropped image to a vision language model and writes back a Markdown
transcription for a table, a prose description for a figure, and, wherever
an earlier stage found none, a generated caption. Its output is
`results/visuals.json`, the same section structure the input carried, with
`markdown` added to each table and `description` to each figure.

Two of this stage's parts matter separately to chunking, which builds six
kinds of vector, named by the fixed `embedding_type` values `section_text`,
`section_title`, `table_text`, `table_vl`, `figure_text` and `figure_vl`
(`docpipe/chunking/chunking.py`;
see [chunking](chunking.md) and the [glossary](../glossary.md)). The four
table and figure kinds have nothing to embed unless this stage ran: a crop's
PNG carries no text of its own, and `table_text`/`figure_text` joins the
item's caption with its Markdown or description, not the Markdown or
description alone (`chunking.py`); a `table_vl`/`figure_vl` request is
captioned with that same text, falling back to the bare caption only when
it is empty. A section's own body text still carries the placeholder token
verbatim: at chunking time, `_replace_placeholders` substitutes only the
item's caption for that token, never its full transcription or
description, because folding the whole table into the surrounding text
made up 46 percent of the section-text corpus and pushed the longest
sections past the model's token limit (`_replace_placeholders`'s
docstring in `chunking.py`).

## Position in the pipeline

| | |
|---|---|
| **In** | `results/sections_refined.json` if Stage 4 wrote one, else `results/sections.json` (`_resolve_input`); `sections.json`'s table `source_text` fields, read again for the QA gate since Stage 4 drops them (`_load_source_texts`); the table/figure PNGs named by each item's `path`, under `images/`. |
| **Out** | `results/visuals.json`: the input's section structure, each table gaining `markdown` and each figure gaining `description`, both optionally `caption` or `qa_warning`; an item the model gave no object for has neither and says why in `vlm_why`; `.prompt_versions.json`, the sha256 of this run's prompts, written as a sibling of `results/`, not inside it. |
| **Resumes on** | An item already carrying `markdown` (table) or `description` (figure) is loaded from the cache and never resent; an item without one, a hole with its `vlm_why`, is asked again by the next run; `--force-stale` redoes every item once any tracked prompt no longer matches, behaving like `--force`, and redoes the items an older run stored as a plain-text answer; `--force` redoes every item unconditionally. |
| **Needs** | A vLLM, or other OpenAI-compatible, server serving `VLM_MODEL` at `VLM_BASE_URL`, or a hosted API chosen with `VLM_PROVIDER` (see [the provider layer](providers.md)), that takes the reply schemas of the stage as the `response_format` of a request; a profile, since the core has no prompt of its own: `--profile` or `DOCPIPE_PROFILE`, and a run with neither stops in one line naming the available profiles (`require_profile`; see [profiles](../profiles.md)). |

Stage 3's structuring pass precedes this one; Stage 4's refinement
precedes it only when already finished, since both read `sections.json`,
launched at once against two separate, mutually unaware model servers
(`VLM_BASE_URL` defaults to port 8001, refinement's `LLM_BASE_URL` to port
8000, both serving the same default model name; see
[pipeline](../pipeline.md)). Stage 6 follows:
`docpipe.chunking` merges `sections_refined.json` and `visuals.json` by
item id into `document.json`; a document with no `visuals.json` still
merges, with every table and figure left as Stage 3 or Stage 4 last wrote
it.

## Method

### Resolving the profile and the context budget preflight

`main` requires a profile from `--profile`/`DOCPIPE_PROFILE`
(`require_profile`), falls back to the profile's `processed_dir` when no
input path is given, and, on `--print-context-budget`, prints
`max_request_tokens()` and exits early: the longer, by word count, of the
two system prompts, times `TOKENS_PER_WORD`, plus `IMAGE_TOKENS` for a
full-page crop, plus `VLM_MAX_TOKENS` for the one reply, all over-estimated:
13,992 tokens with the `kwp` profile and 14,163 with `scenarios`. No second
reply is counted. `assert_serving` keeps the window the server reported
(`llm_preflight.served_window`, role `vlm`), and what it holds beyond this
budget is what a reply that was cut off is asked once more with (see The vision
call, its retries and a hole).

Unless `--dry-run` is set, `main` then reads the profile's `reading.PHRASES`
(`reading.phrases()`; a profile that lacks a sentence ends the run with a
`LookupError` before the first request, and a dry run or the budget needs none)
and calls `assert_serving` (`docpipe/llm_preflight.py`; see [core](core.md))
before `run_single` or `run_batch` runs. A smaller `max_model_len` raises
`PreflightError` and the run never starts. The same call puts the two reply
schemas of the stage, `table_reply` and `figure_reply`, to the server once, as
the stage will send them (`assert_reply_schemas`). The stage asks for JSON in
no other way, so a server that refuses a schema with a 4xx other than 429
refuses every request, and the run ends with exit 1 before the first
document; a server that does not answer the probe gives no verdict and the run
goes on.

### Resolving the input, the cache and stale prompts

`_resolve_input` tries `sections_refined.json` first and `sections.json`
second, returning `None` if neither exists. If `visuals.json` already
exists, `prompts.check` compares the seven `PROMPT_IDS` against the
sha256s in `.prompt_versions.json`; a mismatch is only logged unless
`--force-stale` is set, which then behaves like `--force`. Reading the
cache keeps, by id, every table carrying `markdown` and every figure
carrying `description`. An item that an older run stored as the model's
plain-text answer (`"vlm_status": "plain_text"`, which this version writes
nowhere) is no longer taken as read, and is treated like an item described
under older prompts: one warning line names how many such items the cache
holds, and they are asked again only with `--force-stale` (or `--force`).

### Counting the work and starting the client

Every table and figure in the input is counted into `ProcessingStats`, split
into cached and pending. `--dry-run` logs those counts and returns without
opening a connection. When nothing is pending, the run skips the client but
still merges the cache into a fresh copy of the input (`_merge_cache`) and
writes `visuals.json`, so a structural change still reaches the output.
Otherwise `create_client` and `check_model_available` open the server; an
unreachable server, or one not serving `VLM_MODEL`, makes `run_single`
return `None` without writing anything. The input is deep-copied, cached
items are written into it in place, and every remaining item becomes one
entry of a flat `tasks` list.

### Enriching items concurrently

`_load_source_texts` reads `sections.json` once, before the pool starts, for
the QA gate's lookup. A `ThreadPoolExecutor` sized
`VLM_NUM_PARALLEL` maps an internal `_enrich` wrapper over the tasks,
routing each to `process_table` or `process_figure` and catching any
exception a worker raises, so one crash never aborts the document: the item
is kept as it was, with `vlm_why` set to `error`, and counted as an item
without content.

### Transcribing a table and its QA gate

`process_table` fills `table_user_prompt()` and calls `call_vision` at
`TABLE_VLM_TEMPERATURE`. The Markdown returned passes through `qa.assess`,
which fails a table with no data rows, duplicate rows over
`TABLE_QA_MAX_DUPLICATION`, or coverage, when assessable, below
`TABLE_QA_MIN_COVERAGE`. Coverage is the share of the source text's salient
tokens, numbers and words of two or more letters, also found in the Markdown
(`qa.coverage`); it is `None`, reported as unknown rather than a pass, when
the source has fewer than `TABLE_QA_MIN_SOURCE_TOKENS` salient tokens (an
image-only table with no PyMuPDF text layer). A gate failure triggers exactly one retry, with a correction hint, higher
temperature and penalty; a pass beats a fail, otherwise the
higher-coverage attempt is kept, and an unassessable coverage never
displaces the first attempt. Only a table still failing the retry has its consecutive duplicate
rows collapsed (`qa.dedup_consecutive_rows`); a passing table keeps them,
since a real table can legitimately repeat a row. An existing caption is
copied through unchanged; one is generated only where none existed and the
model returned one.

The result of the check is kept. For every table the model transcribed,
`process_table` leaves `qa` on it: `{passed, coverage, coverage_assessed,
duplication, has_rows}`, the metrics of the attempt that was kept, measured on
what the model wrote (a failing table has its repeated neighbouring rows
collapsed afterwards, which the metrics do not see), and whether it passed.
`qa_warning` stays and says the same on a failure. A table the model gave no
object for (it has a `vlm_why`) has no `qa`, and none means not checked, never
passed; so has a table of a `visuals.json` written before this, whose failures carry
`qa_warning` and no `qa`. The merge hands it on and chunking stores it in
`Tables.qa` (see [chunking](chunking.md)).

### Describing a figure

`process_figure` fills `figure_user_prompt()` and calls `call_vision` at the
default `VLM_TEMPERATURE`, higher than a table's, since some paraphrase is
acceptable where a transcription must be verbatim. There is no QA gate for
a figure: no text layer exists to check a description's coverage against.

### Counting a transcription against the PDF

`scripts/table_numbers_in_pdf.py DB PDF_ROOT [--harvest DIR] [--document ID]
[--worst N] [--json FILE] [--profile NAME]` sets what stage 5 transcribed beside
what the PDF itself prints. It counts (a) per table, how many of the distinct
numbers of the stored Markdown stand in the PDF text inside the table's stored
bbox, which is stage 2's frame widened by a few points, so a number printed just
beside the table can count; and (b), given a harvest, per parameter, how many of
the values the harvest read out of a table have their digits in that text. A
number is compared as the harvest compares one (`1.234,5` and `1234.5` are one
number, by the profile's decimal mark) and counts once per table however many
cells hold it.

It is read-only. The database is opened for reading and nothing reads what the
script prints: no trust level, flag or refusal moves. What it cannot judge is
counted apart, with the reason, and left out of every share instead of counted as
a miss: a table with no transcription, no number in it, no bbox or no page; a PDF
not under the root or not readable; a page the PDF does not have or one with no
text layer (a plan a model transcribed); a frame with no text. For values, the
sandbox's computed ones, text that is no number, a table frame that could not be
read, a table not in the database and an id that is another table's, which a
rebuilt database produces since it renews `Tables.id`. A frame that holds text
but no digit is judged, with none of its numbers found, and so cannot be told
from a misread table. The script needs PyMuPDF and no model, and ends 1 only for
an operand it cannot open at all.

### The vision call, its retries and a hole

`call_vision` sends one chat completion carrying the system prompt, the user
prompt, and the image as a base64 `data:` URL. The reply schema of the item
(`replies.TABLE` or `replies.FIGURE`) is the `response_format` of every
request, on every provider (`providers.grammar`), and the request carries the
reasoning settings (`request_extras`; thinking is off unless
`LLM_ENABLE_THINKING` is set) so a `<think>` block cannot spend the answer's
budget. The reply is read as
exactly one JSON object whose one required key (`markdown`, `description`) is
text (`reading.read`; see [core](core.md)). Nothing is stripped, cut out,
closed or salvaged, and no second request without a schema fills in for a
reply that could not be read.

A reply that is not that object is asked again, up to `MAX_RETRIES` attempts
in all: the failed answer is echoed back with the cause named in the profile's
words (`reading.PHRASES`) and the shape that was asked for. A reply that
cannot be read comes back within the second, so this retry does not wait. A
timeout, a 429, a 5xx or any other exception waits `5 * attempt` seconds
(not after the last attempt) and, for a timeout, also escalates the
penalty. A 4xx status other than 429 ends the item at once, with no wait.

A reply that was cut off at its token limit (`finish_reason` `length`) is not
asked again as it stands, and the model is not told its answer was too long:
that would re-run the same loop. The usual cause is a sparse schedule grid,
where the model loses count of its empty cells and keeps emitting them until
the limit. An image has no halves, so the request starts over from the
original prompt with more room and the next step of `RETRY_PENALTIES`. The token
limit of that attempt is the smaller of twice `max_tokens` (`VLM_MAX_TOKENS` for
a table or a figure) and `max_tokens` plus what the served window holds beyond
the stage's budget: `min(2 x max_tokens, max_tokens + window - budget)`, in
tokens (`llm_preflight.further_room`). The budget is the `budget` that
`process_table` and `process_figure` pass to `call_vision`
(`max_request_tokens()`), and the window is the one the server reported at the
preflight. Where the window is not known (no preflight ran, or the server or
hosted API reports none), or the call has no budget, the limit is twice
`max_tokens`. Where the window leaves no more room than the request had, the item
is a hole `cut_off` at once, nothing more is sent, and the log names the served
window in tokens. If the further attempt is cut off too, the item is a hole
`cut_off`; so it is when the cut-off comes on the last attempt and none is left
to ask.

What `call_vision` returns is the object or a `Hole` (`reading.Hole`) with
one of these causes: the causes of an unreadable reply (`reasoning_only`,
`empty`, `no_object`, `syntax`, `outside_text`, `not_an_object`,
`missing_key`, `cut_off`), `refused` for a 4xx the server answered the request
with, `not_served` when the last attempt got no answer (a timeout, a 429, a
5xx, a connection error), and `error` for a failure of the stage's own after
the reply arrived. The last attempt decides. An empty string for the key is an
answer and not a hole.

A hole is an item without content. `process_table` and `process_figure` copy
the item, add `vlm_why` with the cause, count it in `ProcessingStats` (as
`failed_tables` or `failed_figures`, and by cause) and log it at error level;
the item has no `markdown` or `description`, and the next run asks for it
again. A table's QA retry that is a hole keeps the first attempt, which was
read. A worker that raises is caught in `_enrich`, and its item is counted
the same way with the cause `error`. No plain-text request, no unwrapping of a
JSON answer found inside text, no salvage of a cut envelope and no detector of
runaway cells exists any more; the setting `VLM_RUNAWAY_CELL_RUN` went with
them.

### Writing the output and batch mode

`dump_json_atomic` writes the merged document to a temporary file and
replaces the target with `os.replace`, so a killed run still leaves
whatever finished. `_strip_source_text` removes the QA-only
field from every table, on the normal path and the crash-fallback path
alike, and `prompts.record` writes `.prompt_versions.json`. `run_batch`
treats every document directory under a root path, at any depth, with a
resolvable input file as one candidate (`artifacts.document_dirs` over
`INPUT_JSONS`), runs each through a pool sized `DOC_PARALLEL`, and catches one
directory's exception without stopping the rest; total in-flight requests
can reach roughly `DOC_PARALLEL` times `VLM_NUM_PARALLEL` (`pipeline.py`'s
comment on `DOC_PARALLEL`).

## Data model

| file | written by | shape |
|---|---|---|
| `results/visuals.json` | `dump_json_atomic` | `{"version": 1, "sections": [...]}`; each section's `tables`/`figures` lists carry the original item plus this stage's added keys. The shape is `docpipe/schemas/visuals.schema.json`; stage 5 writes the version first and replaces the one its input brought, and no stage checks a file against the schema (see [the files each stage leaves behind](../artifacts.md)) |
| `.prompt_versions.json` | `prompts.record` | `{prompt_id: sha256}`, one entry per id in `PROMPT_IDS`; a sibling of `results/`, not inside it |

A table item keeps `id`, `path`, `page_number`, `caption` and `bbox` from
Stage 2 and Stage 3 (`bbox` is a list of one `[x0, y0, x1, y1]` rect in PDF
points, unused by this stage). It loses `source_text`,
present only in `sections.json` and stripped before every write. It gains
`markdown` (absent when the model gave no object for it), optionally
`caption`, optionally `qa_warning`, a
`{"coverage": float or null, "coverage_assessed": bool, "duplication":
float, "has_rows": bool}` dict present only when the kept attempt did not
pass the QA gate, and `qa`, the same metrics plus `"passed": bool`, present for
every table the model transcribed. An item without content has instead
`vlm_why`, one of the twelve causes of `reading.HOLE_CAUSES` (`cut_off`,
`reasoning_only`, `empty`, `no_object`, `syntax`, `outside_text`,
`not_an_object`, `missing_key`, `wrong_shape`, `refused`, `not_served`,
`error`; this stage never writes `wrong_shape`, which `reading.read` never
gives), written only on an item without content. An item an older run
stored as a plain-text answer has `"vlm_status": "plain_text"` and a content
that may be the first half of a table; this version never writes the key and
no longer takes such an item as read. A figure item
keeps the same inherited fields and gains `description`, optionally
`caption`, and `vlm_why` or `vlm_status`, on the same terms.

`docpipe/visuals/models.py` defines `EnrichedTable` and `EnrichedFigure`
dataclasses that model only part of this shape: `id`, `path`,
`page_number`, `caption`, and `markdown` or `description`, each with a
`to_dict`/`from_dict` pair that omits an unset field rather than writing it
`null`. `bbox`, `qa_warning`, `vlm_why` and `vlm_status` exist only on the plain dicts
the pipeline writes, not on these dataclasses. Neither class is constructed
anywhere in `pipeline.py` or `process.py`: the pipeline passes plain dicts
through `copy.deepcopy` end to end, and the dataclasses serve as a
partial, tested shape rather than objects the code builds.

## Configuration

| name | kind | default | effect | where read |
|---|---|---|---|---|
| `VLM_BASE_URL` | env var | `http://localhost:8001/v1` | vision server's base URL | `config.py`; `--base-url` overrides |
| `VLM_MODEL` | env var | `Qwen/Qwen3.5-122B-A10B-FP8` | served model name requested | `config.py`; `--model` overrides |
| `VLM_API_KEY` | env var | `EMPTY` | bearer key sent, ignored by vLLM | `config.py` |
| `VLM_TIMEOUT` | env var, seconds | `180` | wall-clock bound on one request | `config.py` |
| `VLM_NUM_PARALLEL` | env var | `8` | items enriched concurrently per document | `config.py`, `pipeline.py` |
| `DOC_PARALLEL` | env var | `8` | documents enriched concurrently, `--batch` | `pipeline.py` |
| `MAX_RETRIES` | constant | `4` | attempts at one request, a re-ask after an unreadable reply included | `config.py` |
| `VLM_TEMPERATURE` / `TABLE_VLM_TEMPERATURE` | constant | `0.6` / `0.1` | sampling temperature, figure / table | `config.py` |
| `VLM_MAX_TOKENS` | constant | `8192` | reply token budget; a reply cut off at it is asked once more with more room, and the context budget counts one reply of this size | `config.py` |
| `RETRY_PENALTIES` | constant | `[None, 1.1, 1.3]` | penalty after the indexed attempt failed (a timeout, or a reply cut off) | `config.py` |
| `TABLE_QA_MIN_COVERAGE`/`MAX_DUPLICATION`/`MIN_SOURCE_TOKENS` | constant | `0.5`/`0.4`/`8` | QA gate pass thresholds | `config.py`, `qa.py` |
| `TABLE_QA_RETRY_TEMPERATURE`/`RETRY_PENALTY` | constant | `0.4`/`1.3` | sampling for the QA-failure retry | `config.py` |
| `TOKENS_PER_WORD` | constant | `3.0` | word-to-token factor in the context budget estimate | `config.py` |
| `IMAGE_TOKENS` | constant | `4096` | tokens charged per image crop in the context budget estimate | `config.py` |
| `--batch` | CLI flag | off | input path is a root of output directories | `pipeline.py` |
| `--dry-run` | CLI flag | off | report counts only, no server call | `pipeline.py` |
| `--log-level` | CLI flag | `INFO` | logging level: `DEBUG`/`INFO`/`WARNING`/`ERROR` | `pipeline.py` |
| `--force`/`--force-stale` | CLI flags | off | redo every item / redo every item once any tracked prompt changed | `pipeline.py` |
| `--input-json` | CLI flag | auto-resolved | overrides which JSON to read | `pipeline.py` |
| `--print-context-budget` | CLI flag | off | print `max_request_tokens()` and exit; asks nothing of the model and needs no profile sentence | `pipeline.py` |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | prompts and `processed_dir` this run uses; the stage refuses to run without a profile | `pipeline.py`, `docpipe/profile.py` |

`LLM_SCHEMA` does not govern this stage: its reply schemas are sent with every
request, on every provider, and there is no value that turns that off.

## Failure modes

A missing image file counts into `stats.skipped_missing` and returns the
item unchanged, with no `markdown`/`description` key. A missing input file
logs an error and makes `run_single` return `None`; the CLI exits 1. An
unreachable endpoint, or one not serving the named model, is caught by
`check_model_available` before any request. A server whose context
is smaller than `max_request_tokens()` never gets a document: the preflight
check, skipped only on `--dry-run`, refuses to start the run; so does a server
that refuses a reply schema of the stage, and a profile without a
`reading.PHRASES` sentence stops the run with a `LookupError` before the
first request.

Inside one item's retries, a 4xx fails at once with no wait; a timeout,
429, or 5xx is retried after a backoff; a reply that is not the object is
asked again at once with its cause named; and a reply that was cut off
restarts from the original prompt with more room and a stronger
penalty, once. What still has no object after that is a hole: the item has
no `markdown` or `description`, `vlm_why` names the cause, the document is
written, and a later run asks for the item again. A hole changes no exit
code. The run says so once, in the units each number counts, where it ends:
`Stage 5: 4 table(s) and 1 figure(s) in 2 document(s) have no content; item(s)
by cause: cut_off 3, syntax 2; the next run asks only for those`. The stats
block of each document counts them too, on the line `Items without content`,
with the causes. A worker's exception is caught in `_enrich`
and the item is kept unenriched, as a hole named `error`, rather than aborting
the document;
the same holds one level up for a directory's exception under `--batch`. A
table whose QA gate still fails after its retry is not a failure: it is
kept, best effort, with `qa_warning` attached and its consecutive duplicate
rows collapsed. A cached item whose prompt no longer matches the one on
disk is only logged; nothing changes unless `--force-stale` or `--force` is
given.

## Measured behaviour

On the August 2026 run, sparse Gantt-style tables produced runs of 29 to 75
consecutive empty Markdown cells before the reply hit its token limit, where
no real table exceeded a handful (`config.py`, comment above
`RETRY_PENALTIES`). That reply ends at its limit and says so, so the retry
ladder goes by `finish_reason` and not by what the text looks like; the detector
of empty-cell runs, `VLM_RUNAWAY_CELL_RUN`, was removed. A harder penalty
ladder, 1.4 then 1.8, was tried and reverted: at 1.8 the pipe token is
penalised so hard that a table is barely writable (`config.py`, comment above
`RETRY_PENALTIES`); `test_no_stop_sequence_is_sent` holds that no stop sequence
is sent. Every profile
that ships a `profile.py` states a positive context budget when its config
module is imported in a subprocess and asked for it
(`test_a_profile_states_a_usable_context_budget`,
`tests/test_every_profile_loads.py`).

## Verification

`tests/test_qa.py` pins the QA gate: salient tokens, coverage on a full and
partial match, coverage reported as unknown when it cannot be assessed,
duplication, consecutive-row dedup leaving non-adjacent duplicates alone,
and `assess`'s pass and fail boundaries. `tests/test_vision.py` pins base64
image encoding, the model-availability check, `call_vision`'s happy path, and
that the schema goes out as the grammar under its own name
(`test_call_vision_sends_base64_image_and_the_schema_as_grammar`,
`test_every_reply_is_sent_under_its_own_name`,
`test_a_request_without_its_reply_schema_is_not_made`). It pins the strict
reading too: a reply wrapped in prose is asked again with its cause, a fence, a
think block or a second object is not unwrapped, a missing or non-text key is
`missing_key` and not empty content, an empty string is an answer, four
plain-text answers end as a hole with no second request, a cut envelope is
never content, and an error of the stage's own after the reply is a hole named
`error` and not an outage (`test_a_reply_wrapped_in_prose_is_asked_again_with_its_cause`,
`test_a_fence_a_think_block_or_a_second_object_is_not_unwrapped`,
`test_a_reply_object_without_its_key_is_a_missing_key_not_empty_content`,
`test_an_empty_string_is_an_answer`,
`test_four_plain_text_answers_end_as_a_hole_and_no_second_request_is_made`,
`test_a_cut_envelope_is_never_content`,
`test_an_error_of_our_own_after_the_reply_is_a_hole_and_not_an_outage`;
`test_the_old_readers_and_the_plain_text_request_are_gone` holds that the
removed names are gone). `tests/test_vision_retry.py` pins the retry wait and
what the last attempt makes of the item: a refused 4xx does not sleep and is not
retried, a busy or broken server is waited out on 429, 500 and 503 and ends as
a hole that says it did not serve, the last attempt decides the cause, and a
reply that cannot be read retries at once. `tests/test_vision_cut_off.py`
covers the cut-off reply: it restarts from the original prompt with the next
penalty and, where the window is not known, a limit of twice what the request
asked for, a second cut-off and a cut-off on the last attempt are a hole, a cut reply is never content whatever it
holds, a closed object with empty cells that ended normally is read and not
retried, and the context budget counts one reply
(`test_the_retry_after_a_cut_gets_twice_the_room_where_the_window_is_not_known`,
`test_the_context_budget_counts_one_reply`). `tests/test_room.py` pins the room
itself: the smaller of twice and the reply plus what the window leaves, a hole at
once where the window leaves no more room, twice where the window is not known,
a hosted model that reports its window held to it, the budget of stage 5 as the
prompt, the image and one reply, a server that serves exactly the budget taken
and one token under it refused, the log of the further attempt naming both sizes
in tokens, the `vlm_why` description in the schema allowing for a hole after a
smaller request or none, and every request of the stage carrying its budget
(`test_the_room_is_the_smaller_of_twice_and_the_reply_plus_what_is_left`,
`test_a_window_that_leaves_no_more_room_makes_the_unit_a_hole_at_once`,
`test_a_server_that_reports_no_window_gives_twice_the_room`,
`test_a_hosted_model_that_reports_its_window_is_held_to_it`,
`test_the_budget_of_stage_five_is_the_prompt_the_image_and_one_reply`,
`test_stage_five_takes_a_server_that_serves_exactly_its_budget`,
`test_stage_five_refuses_a_server_one_token_under_its_budget`,
`test_the_log_of_the_further_attempt_says_both_sizes_in_tokens`,
`test_the_schema_does_not_say_a_cut_off_item_had_twice_the_room`,
`test_every_request_of_the_visuals_stage_carries_the_budget_of_that_stage`).
`tests/test_visuals_holes.py` covers the hole end to end: a table or a figure
that could not be read is an item with its cause and no second request fills
it in, a QA retry that is a hole keeps the first attempt, the summary line says
what has no content, a document with holes is written and the next run asks
only those, a crash of our own is counted as a hole named `error`, a run with
holes exits as it did, and an item an older run stored as plain text is said
once and asked again only with `--force-stale`. `tests/test_process.py` pins
the workers: a missing image
counted as skipped rather than failed, a QA retry that recovers, a
persistent QA failure
flagged, a coverage failure the retry fixes, adjacent duplicates left
untouched on a pass, `source_text` stripped, and which caption
instruction is chosen. `tests/test_imageprocessing_pipeline.py` pins the
concurrent run end to end: every item enriched, the cache reused with the
client never created, `source_text` never leaking on a worker crash, and a
dry run writing nothing. `tests/test_imageprocessing_config.py` pins that
the system prompts are injection-hardened and that a table's temperature is
lower than a figure's. `tests/test_imageprocessing_models.py` pins the
`EnrichedTable`, `EnrichedFigure` and `ProcessingStats` shapes.
`tests/test_stage_preflight.py` pins that the visuals command hands the
preflight its own two schemas, that a server that refuses the figure schema
ends the run before the first document, and that a dry run asks the server
nothing. `tests/test_prompts.py` checks that `visuals/table_system`, one of this
stage's prompt ids, resolves for the kwp profile, and that a prompt id a
profile lacks fails by name rather than falling back to another project's
text. All seven of the stage's `PROMPT_IDS` are exercised through their readers
instead: `config.py` reads each through a `prompts.per_profile` function on
first use, and `tests/test_every_profile_loads.py` asks a subprocess for
every one of them per profile, in `test_a_profile_loads_every_config_module`
and `test_a_profile_states_a_usable_context_budget`. `tests/test_segment_bbox.py`'s
`test_imageprocessing_passthrough_preserves_bbox` checks that a `bbox`
survives this stage unchanged.

## Modules

`__init__.py` re-exports `run`, `run_single` and `run_batch` and states, in
one sentence, what the stage adds on top of preprocessing's structured
output. `__main__.py` lets the package run as `python -m docpipe.visuals`,
binding `--profile` before it imports the stage.
`config.py` holds every tuned constant this stage reads, the connection
settings, the retry and QA thresholds, the context budget estimate,
`dump_json_atomic`, and the seven prompt readers (`table_system_prompt()`,
`table_user_prompt()`, `figure_system_prompt()`, `figure_user_prompt()` and
the three `caption_*_instruction()` functions), which read the active profile's prompt on first use. `models.py` defines `EnrichedTable`, `EnrichedFigure`
and `ProcessingStats`, the documented and tested shape of one output item
and of the run's bookkeeping, holes by cause included. `pipeline.py` is the orchestrator:
resolving the profile and input, the per-item cache and staleness check,
the worklist, the thread pool over `process.py`'s workers, the atomic
write, the CLI, `--batch` mode, the preflight, and the one line at the end that
says what the run left without content (`summarise`). `process.py` holds
`process_table` and `process_figure`, turning one item and its section
context into a filled-in copy, including the QA retry and the
caption-instruction choice, or into an item with a `vlm_why` when the model
gave no object. `qa.py` holds the pure, model-free functions
the table worker calls: token salience, coverage, duplication,
consecutive-row dedup. `replies.py` holds the reply schema of each request,
for this stage and for page transcription. `vision.py` is the only module here that talks to
the network: the client, the served-model check, and the chat completion call
with its retry ladder, which reads the reply as one object or returns a hole.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/visuals/__init__.py</code></summary>

__init__.py: Vision-LLM enrichment of tables and figures.

Reads the preprocessing pipeline's structured output plus its images/
directory and adds Markdown tables and figure descriptions.

</details>

<details>
<summary><code>docpipe/visuals/pipeline.py</code></summary>

pipeline.py: Orchestrates the imageprocessing stage.

Enriches one PDF's output directory, or every PDF subdirectory under
a root directory with `--batch`, by sending each table and figure
image to a vision language model. `_build_parser` lists the CLI
flags.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/visuals/vision.py</code></summary>

vision.py: Vision model interaction layer over an OpenAI compatible
API.

Creates the client, checks model availability, and makes the chat
completions call that sends a base64 encoded image and reads the one
JSON object that comes back. The reply schema is the grammar of the
request; the reply is read as exactly one object (see
docpipe/reading.py): nothing is stripped, cut out, closed or salvaged,
and no second, unconstrained request fills in for a reply that could
not be read.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/visuals/qa.py</code></summary>

qa.py: Quality checks for vision model table extraction.

Pure helper functions that judge a vision model's Markdown
transcription of a table. Coverage compares it against the PyMuPDF
source text and catches truncation; duplication counts repeated rows
and catches repetition loops.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/visuals/process.py</code></summary>

process.py: Core processing logic for table and figure enrichment.

Sends one table or figure image to the vision model, together with
its section context, and returns a copy of the item carrying the
model's markdown or description. A table's transcription passes a
quality gate and gets one retry with a stronger prompt on failure. An
image the model could not be read an object for (see vision.call_vision)
has no content: the item carries no markdown or description, says why in
`vlm_why`, and is counted by cause. No plain-text request fills in for it.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/visuals/replies.py</code></summary>

replies.py: The reply each vision request asks for, as a JSON schema.

The grammar of every request of this stage and of page transcription, on
every provider (see `docpipe.providers.grammar`). The prompts state the same
shapes in words; nothing here is a check beyond the one required key, which
`vision.call_vision` reads as text. The key is the single entry of `required`
in each schema.

Author: Felix Vossel

</details>

<details>
<summary><code>scripts/table_numbers_in_pdf.py</code></summary>

table_numbers_in_pdf.py: How much of a stored table the PDF itself prints.

Stage 5 has a vision model read every table off its picture, and the Markdown
it wrote is what the database stores and what a harvest quotes. A PDF with a
text layer prints the same numbers as text, inside the same frame. This sets
the two side by side and counts. It reads a corpus database, the PDFs and,
when it is given one, a harvest directory:

  (a) per table: how many of the distinct numbers of the stored transcription
      stand in the PDF text at the table's place;
  (b) per parameter: of the values the harvest read out of a table, how many
      have their digits in that text.

It judges nothing and changes nothing. No trust level, reason or flag reads
what it prints, the database is opened for reading only, and a table it
cannot judge is listed with the reason and left out of every share, never
counted as a miss.

    python scripts/table_numbers_in_pdf.py data/KWP.db data/pdf
    python scripts/table_numbers_in_pdf.py <db> <pdf root> --harvest data/extraction/corpus
    python scripts/table_numbers_in_pdf.py <db> <pdf root> --document 12 --json counts.json

What the numbers are. A number is compared the way the harvest compares one:
1.234,5 and 1234.5 are one number, and how a point or comma is read is the
profile's decimal mark (--profile or DOCPIPE_PROFILE; with neither the comma,
as everywhere else the harvest reads a number). Each table counts
its DISTINCT numbers, so a number that stands in six cells is one. The table's
place is its stored bbox, which stage 2 widens by a few points on each side:
a number printed just beside a table can stand in its text. The PDF text is
the text layer. A page without one (a plan a model transcribed) cannot be
judged, and neither can a table whose frame holds no text, and both are said
so.

What (b) compares: the value of a numeric parameter, as the harvest wrote it,
against the numbers in the frame text of the table the value was read from.
A value the sandbox computed is not read off a page and is counted apart. A
harvest names its table by Tables.id, which a rebuilt database renews, so a
tuple whose id is not a table of this database, or is one of another document
or block, is counted apart too.

Needs PyMuPDF. No model, no GPU.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
