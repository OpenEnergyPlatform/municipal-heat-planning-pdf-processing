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
| **Out** | `results/visuals.json`: the input's section structure, each table gaining `markdown` and each figure gaining `description`, both optionally `caption`, `qa_warning` or `vlm_status`; `.prompt_versions.json`, the sha256 of this run's prompts, written as a sibling of `results/`, not inside it. |
| **Resumes on** | An item already carrying `markdown` (table) or `description` (figure) is loaded from the cache and never resent; `--force-stale` redoes every item once any tracked prompt no longer matches, behaving like `--force`; `--force` redoes every item unconditionally. |
| **Needs** | A vLLM, or other OpenAI-compatible, server serving `VLM_MODEL` at `VLM_BASE_URL`; a profile, since this stage has no default prompt and `DOCPIPE_PROFILE` must be set before import for its prompts to bind (`resolve_profile`; see [profiles](../profiles.md)). |

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

`main` resolves the profile from `--profile`/`DOCPIPE_PROFILE`
(`resolve_profile`), falls back to the profile's `processed_dir` when no
input path is given, and, on `--print-context-budget`, prints
`max_request_tokens()` and exits early: the longer, by word count, of the
two system prompts, times `TOKENS_PER_WORD`, plus `IMAGE_TOKENS` for a
full-page crop, plus `VLM_MAX_TOKENS` for the reply, all over-estimated.
Unless `--dry-run` is set, `main` then calls `assert_serving`
(`docpipe/llm_preflight.py`; see [core](core.md)) before `run_single` or
`run_batch` runs; a smaller `max_model_len` raises `PreflightError` and the
run never starts.

### Resolving the input, the cache and stale prompts

`_resolve_input` tries `sections_refined.json` first and `sections.json`
second, returning `None` if neither exists. If `visuals.json` already
exists, `prompts.check` compares the seven `PROMPT_IDS` against the
sha256s in `.prompt_versions.json`; a mismatch is only logged unless
`--force-stale` is set, which then behaves like `--force`. Reading the
cache keeps, by id, every table carrying `markdown` and every figure
carrying `description`.

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
exception a worker raises, substituting the original item so one crash
never aborts the document.

### Transcribing a table and its QA gate

`process_table` fills `TABLE_USER_PROMPT` and calls `call_vision` at
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

### Describing a figure

`process_figure` fills `FIGURE_USER_PROMPT` and calls `call_vision` at the
default `VLM_TEMPERATURE`, higher than a table's, since some paraphrase is
acceptable where a transcription must be verbatim. There is no QA gate for
a figure: no text layer exists to check a description's coverage against.

### The vision call, its retry ladder and the plain text rescue

`call_vision` sends one chat completion carrying the system prompt, the user
prompt, and the image as a base64 `data:` URL, with `response_format` set
to `json_object` and reasoning disabled, so a `<think>` block cannot spend
the answer's budget. `_parse_json_response` tries a direct parse, then a
fenced block, then the first brace-delimited span. On a parse failure,
`looks_runaway` checks for a run of empty pipe-delimited cells at least
`RUNAWAY_CELL_RUN` long, the shape a sparse schedule grid produces when
row tracking fails and empty cells keep emitting until the reply cuts off
mid-JSON; a runaway restarts from the original prompt with
the next step of `RETRY_PENALTIES`, while a formatting slip gets a
correction turn that echoes the failed answer back. A 4xx status other than
429 fails the item at once, with no wait; a timeout, 429, 5xx, or any other
exception waits `5 * attempt` seconds and, for a timeout, also escalates
the penalty. `_rescue_plain` runs whenever `call_vision` returns nothing,
whether every `MAX_RETRIES` attempt was spent or a single 4xx ended the
loop at once with no retries spent (`process.py`'s `if not response:` check
does not distinguish the two), asking once more, unconstrained, for the
content with no JSON envelope. A JSON answer is still unwrapped by key
rather than stored whole, and a truncated envelope is salvaged character by
character (`_salvage_truncated`) rather than discarded. A rescued item is
marked `"vlm_status": "plain_text"`; only a rescue that also comes back
empty is a hard failure.

### Writing the output and batch mode

`dump_json_atomic` writes the merged document to a temporary file and
replaces the target with `os.replace`, so a killed run still leaves
whatever finished. `_strip_source_text` removes the QA-only
field from every table, on the normal path and the crash-fallback path
alike, and `prompts.record` writes `.prompt_versions.json`. `run_batch`
treats every subdirectory of a root path with a resolvable input file as one
candidate, runs each through a pool sized `DOC_PARALLEL`, and catches one
directory's exception without stopping the rest; total in-flight requests
can reach roughly `DOC_PARALLEL` times `VLM_NUM_PARALLEL` (`pipeline.py`'s
comment on `DOC_PARALLEL`).

## Data model

| file | written by | shape |
|---|---|---|
| `results/visuals.json` | `dump_json_atomic` | `{"sections": [...]}`; each section's `tables`/`figures` lists carry the original item plus this stage's added keys |
| `.prompt_versions.json` | `prompts.record` | `{prompt_id: sha256}`, one entry per id in `PROMPT_IDS`; a sibling of `results/`, not inside it |

A table item keeps `id`, `path`, `page_number`, `caption` and `bbox` from
Stage 2 and Stage 3 (`bbox` is a list of one `[x0, y0, x1, y1]` rect in PDF
points, unused by this stage). It loses `source_text`,
present only in `sections.json` and stripped before every write. It gains
`markdown` (absent only if the item failed even the rescue), optionally
`caption`, optionally `qa_warning`, a
`{"coverage": float or null, "coverage_assessed": bool, "duplication":
float, "has_rows": bool}` dict present only when the kept attempt did not
pass the QA gate, and optionally `"vlm_status": "plain_text"`. A figure item
keeps the same inherited fields and gains `description`, optionally
`caption`, and optionally `vlm_status`, on the same terms.

`docpipe/visuals/models.py` defines `EnrichedTable` and `EnrichedFigure`
dataclasses that model only part of this shape: `id`, `path`,
`page_number`, `caption`, and `markdown` or `description`, each with a
`to_dict`/`from_dict` pair that omits an unset field rather than writing it
`null`. `bbox`, `qa_warning` and `vlm_status` exist only on the plain dicts
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
| `VLM_RUNAWAY_CELL_RUN` | env var | `25` | empty cells marking a lost-count runaway | `config.py`, `looks_runaway` |
| `MAX_RETRIES` | constant | `4` | attempts before giving up on one item | `config.py` |
| `VLM_TEMPERATURE` / `TABLE_VLM_TEMPERATURE` | constant | `0.6` / `0.1` | sampling temperature, figure / table | `config.py` |
| `VLM_MAX_TOKENS` | constant | `8192` | reply token budget | `config.py` |
| `RETRY_PENALTIES` | constant | `[None, 1.1, 1.3]` | penalty after the indexed attempt failed | `config.py` |
| `TABLE_QA_MIN_COVERAGE`/`MAX_DUPLICATION`/`MIN_SOURCE_TOKENS` | constant | `0.5`/`0.4`/`8` | QA gate pass thresholds | `config.py`, `qa.py` |
| `TABLE_QA_RETRY_TEMPERATURE`/`RETRY_PENALTY` | constant | `0.4`/`1.3` | sampling for the QA-failure retry | `config.py` |
| `TOKENS_PER_WORD` | constant | `3.0` | word-to-token factor in the context budget estimate | `config.py` |
| `IMAGE_TOKENS` | constant | `4096` | tokens charged per image crop in the context budget estimate | `config.py` |
| `--batch` | CLI flag | off | input path is a root of output directories | `pipeline.py` |
| `--dry-run` | CLI flag | off | report counts only, no server call | `pipeline.py` |
| `--log-level` | CLI flag | `INFO` | logging level: `DEBUG`/`INFO`/`WARNING`/`ERROR` | `pipeline.py` |
| `--force`/`--force-stale` | CLI flags | off | redo every item / redo every item once any tracked prompt changed | `pipeline.py` |
| `--input-json` | CLI flag | auto-resolved | overrides which JSON to read | `pipeline.py` |
| `--print-context-budget` | CLI flag | off | print `max_request_tokens()` and exit | `pipeline.py` |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | prompts and `processed_dir` this run uses | `docpipe/profile.py` |

## Failure modes

A missing image file counts into `stats.skipped_missing` and returns the
item unchanged, with no `markdown`/`description` key. A missing input file
logs an error and makes `run_single` return `None`; the CLI exits 1. An
unreachable endpoint, or one not serving the named model, is caught by
`check_model_available` before any request. A server whose context
is smaller than `max_request_tokens()` never gets a document: the preflight
check, skipped only on `--dry-run`, refuses to start the run.

Inside one item's retries, a 4xx fails at once with no wait; a timeout,
429, or 5xx is retried after a backoff, and a runaway table restarts with
an escalating penalty rather than repairing JSON that could never parse. Once every JSON attempt and the rescue have failed or come
back empty, the item is a hard failure with no content, so a later run
still sees it as pending. A worker's exception is caught in `_enrich`
and the item is substituted unenriched rather than aborting the document;
the same holds one level up for a directory's exception under `--batch`. A
table whose QA gate still fails after its retry is not a failure: it is
kept, best effort, with `qa_warning` attached and its consecutive duplicate
rows collapsed. A cached item whose prompt no longer matches the one on
disk is only logged; nothing changes unless `--force-stale` or `--force` is
given.

## Measured behaviour

On the August 2026 run, sparse Gantt-style tables produced runs of 29 to 75
consecutive empty Markdown cells before the reply was cut off mid-JSON,
against the runaway threshold of 25 (`config.py`, comment above
`RUNAWAY_CELL_RUN`). Of 112 parse failures, 111 read "No JSON object found
in response" on a request already back 200 OK within the second, the
measurement the rescue exists to answer (`vision.py`, the
`call_vision_plain` docstring). Before the JSON-in-plain-text unwrap step,
7 of the 12 items the rescue recovered had stored the envelope itself as
their content (`test_a_json_answer_to_the_plain_request_is_unwrapped`);
before `_salvage_truncated`, a truncated envelope stored raw had corrupted
13 items on a later redo run
(`test_a_truncated_envelope_yields_its_content_not_itself`, both in
`tests/test_vision_rescue.py`). Two reverted designs are noted beside the
constant each would have changed: a harder penalty ladder, 1.4 then 1.8,
made a table barely writable; a stop sequence on the empty-cell run cut a
reply open mid-JSON without saving anything new (`config.py`, comments
above `RETRY_PENALTIES` and `RUNAWAY_CELL_RUN`; also
`test_no_stop_sequence_is_sent`). Every profile
that ships a `profile.py` states a positive context budget when its config
module is imported in a subprocess
(`test_a_profile_states_a_usable_context_budget`,
`tests/test_every_profile_loads.py`).

## Verification

`tests/test_qa.py` pins the QA gate: salient tokens, coverage on a full and
partial match, coverage reported as unknown when it cannot be assessed,
duplication, consecutive-row dedup leaving non-adjacent duplicates alone,
and `assess`'s pass and fail boundaries. `tests/test_vision.py` pins JSON
extraction across its fallback shapes, base64 image encoding, the
model-availability check, and `call_vision`'s happy path.
`tests/test_vision_retry.py` pins the retry wait: a refused 4xx does not
sleep, a busy or broken server is retried after a backoff on 429, 500 and
503, and a parse failure retries at once.
`tests/test_vision_rescue.py` covers the rescue end to end: envelope-free
replies, `<think>`/fence stripping, an empty answer not counted as a
rescue, both workers routing through it, a JSON-wrapped reply unwrapped by
field name, a truncated envelope salvaged rather than discarded, the
runaway pattern, and the penalty ladder's exact sequence across four
attempts. `tests/test_process.py` pins the workers: a missing image
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
`tests/test_prompts.py` checks that `visuals/table_system`, one of this
stage's prompt ids, resolves for the kwp profile, and that a prompt id a
profile lacks fails by name rather than falling back to another project's
text. All seven of the stage's `PROMPT_IDS` are exercised through import
instead: `config.py` evaluates `prompts.text` for each at import time, which
`tests/test_every_profile_loads.py` triggers per profile, in
`test_a_profile_loads_every_config_module` and
`test_a_profile_states_a_usable_context_budget`. `tests/test_segment_bbox.py`'s
`test_imageprocessing_passthrough_preserves_bbox` checks that a `bbox`
survives this stage unchanged.

## Modules

`__init__.py` re-exports `run`, `run_single` and `run_batch` and states, in
one sentence, what the stage adds on top of preprocessing's structured
output. `__main__.py` lets the package run as `python -m docpipe.visuals`.
`config.py` holds every tuned constant this stage reads, the connection
settings, the retry and QA thresholds, the context budget estimate,
`dump_json_atomic`, and the seven prompt texts bound at import time from
the active profile. `models.py` defines `EnrichedTable`, `EnrichedFigure`
and `ProcessingStats`, the documented and tested shape of one output item
and of the run's bookkeeping. `pipeline.py` is the orchestrator:
resolving the profile and input, the per-item cache and staleness check,
the worklist, the thread pool over `process.py`'s workers, the atomic
write, the CLI, `--batch` mode, and the preflight. `process.py` holds
`process_table` and `process_figure`, turning one item and its section
context into a filled-in copy, including the QA retry and the
caption-instruction choice. `qa.py` holds the pure, model-free functions
the table worker calls: token salience, coverage, duplication,
consecutive-row dedup. `vision.py` is the only module here that talks to
the network: the client, the served-model check, the chat completion call
with its retry and runaway-penalty ladder, the plain text rescue and its
truncated-envelope salvage, and the JSON parser.

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
completions call that sends a base64 encoded image and parses the
JSON response.

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
quality gate and gets one retry with a stronger prompt on failure; a
call that never returns valid JSON falls back to a plain text
request before the item is marked failed.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
