# 4. Repairing the text

## Purpose

Stage 3 (`docpipe.preprocessing`) builds `sections.json` mechanically
from PyMuPDF text extraction and PP-DocLayoutV3 layout boxes; its
cleanup pass already strips repeated header and footer lines and drops
obvious directory pages (see [Preprocessing](preprocessing.md)). What survives that
pass is the kind of defect a fixed rule cannot resolve reliably: a caption
on the wrong table, a heading split across a page break into two
sections, an unstructured bibliography, an ALL-CAPS title. Stage 4
hands each document's sections to an LLM, in windows, to resolve those
cases (`docpipe/refinement/refine.py`).

Stage 4 also enforces the size limit the embedding step needs: a
retrieval chunk is one section and one vector, so a section long enough
that its embedding no longer represents one topic, or long enough to
exceed the embedding model's token limit, must become several before
reaching chunking. That cut (`docpipe/refinement/split.py`) is asked of
the model but performed mechanically, at segment boundaries, so nothing in
the split text is rephrased, dropped, or invented. Skipping Stage 4 leaves
both jobs undone; its two downstream consumers cope with that
differently (see Position in the pipeline).

## Position in the pipeline

| | |
|---|---|
| In | `results/sections.json`, written by [Preprocessing](preprocessing.md) (Stage 3) |
| Out | `results/sections_refined.json`, `results/refinement_report.json`, `results/.prompt_versions.json` |
| Resumes on | the presence of `sections_refined.json`; `--force` redoes every candidate document, `--force-stale` only those whose prompt hash no longer matches |
| Needs | an OpenAI-compatible LLM server reachable at `LLM_BASE_URL`, checked before the first document by `assert_serving` |

Stage 4 follows Stage 3's structuring pass and precedes two consumers
that treat `sections_refined.json` differently. [Visuals](visuals.md)
(Stage 5) prefers it but falls back to `sections.json` when absent
(`_resolve_input` in `docpipe/visuals/pipeline.py`), so the two stages
can run against separate model servers without waiting on each other.
[Chunking](chunking.md)'s merge step has no such fallback and requires
`sections_refined.json` outright (`docpipe/chunking/merge.py`), so an
unrefined document is not a merge candidate. The stage imports no GPU
library; its only external dependency is the `openai` client reaching
`LLM_BASE_URL`.

## Method

### Preflight and caching

`run()` calls `assert_serving` once, before the first document, with the
worst case one window could cost (`max_request_tokens()`); an undersized
or wrong server stops the run at once rather than letting individual
requests fail mid-batch. When `results/sections_refined.json` exists,
`run_single` compares its recorded prompt hashes against the prompts now
in use with `prompts.check`: a moved hash sets `force` under
`--force-stale`, otherwise it only logs a warning. `run_single` always
calls `run_refine`, and it is `run_refine`, not `run_single`, that reads
that file back without calling the LLM whenever it exists and `force` is
false, so an unforced stale prompt is still served from cache. `prompts.record`
writes the new hashes once refinement finishes.

### Splitting oversized sections

Before any window is built, `refine_sections` calls `split_oversized`.
`needs_split` flags every section over `SECTION_MAX_WORDS` words;
`_rebuild_matches` then checks that its `segments` still reproduce its
`content` exactly, the precondition for a safe cut along a segment
boundary. `_ask_all_cuts` fires every document's split requests at once,
concurrently, before the refinement windows are dispatched. The model sees only
the section's title and `outline()`, a compact per-segment listing, and
answers with cut positions and part titles; `split_section` applies them,
and `_enforce_max` re-cuts any part still over the limit, subdividing an
oversized segment with `_subdivide_segments` when there is no boundary to
cut on. A section whose provenance no longer matches its content is left
whole, with a warning, rather than cut at a guessed position.

### Windowed dispatch

`refine_sections` groups the bounded sections into consecutive windows of
`WINDOW_SIZE` and submits each to `_call_llm` on a `ThreadPoolExecutor`
sized to `LLM_NUM_PARALLEL`. Every window but the first also receives
`prev_ctx`, the previous window's last section, passed read-only so the
model can recognise a heading split across the boundary and mark the new
window's first section `merge_into_previous` instead of a new section.

### The LLM call

`_call_llm` strips `segments` and `pages` from the payload before it is
sent (the model must not see or rewrite them) and, in edit mode, adds
each section's index and reduces its tables and figures to `id` and
`caption` only. The reply is parsed with `_loads_json_object`, which
falls back to the outermost `{...}` block when the model wraps its JSON
in other text. An empty reply is retried up to `MAX_RETRIES` times with an empty
assistant turn appended rather than an echo; invalid JSON or a missing
`sections` key is retried the same number of times, with a bounded echo
of the bad answer (`_echo`, at most 400 leading and 200 trailing
characters) rather than the whole thing. A 4xx status other than 429 is
not retried, since an identical retry would be refused identically.
A "maximum context length" error abandons the window with an error-level
log line instead, since the caller then keeps that window's raw text,
indistinguishable from a window that needed no change.

### Materialising an edit-mode reply

When `REFINE_RETURN_CORRECTIONS` is set, the model returns
find-and-replace edits instead of a rewritten section, and
`_materialise_corrections` rebuilds each output section from the
original, not the reply: every section starts as itself, and only what
the reply supplies (a title, a caption, an edit list) is applied on top.
`apply_corrections` (`corrections.py`) checks each edit before applying
it (see Failure modes for what gets one refused); a rejected edit is
dropped and logged, the original passage kept.

### Reattaching page provenance

`_thread_provenance` restores `segments`, and from them `pages`, onto the
LLM's cleaned output before `_apply_actions` runs, since
`merge_into_previous` needs a kept section's segments already attached. A
same-length, positionally-consistent window (`_positional_consistent`)
reattaches one-to-one; otherwise `_redistribute_segments` re-homes each
input segment onto whichever output contains it: a table or figure by its
globally unique block id, a text segment by whichever output's tokens
contain most of it, ties broken toward the output already holding its
own page. An unmatched text segment, or an unmatched table or
figure segment on a shrink, is dropped rather than attached to an
arbitrary survivor that would then cite a page it does not hold; on a
split, an unmatched table or figure segment instead gets a best-effort
home at the nearest surviving output.

### Applying the model's actions

`_apply_actions` reads each section's `_action`, once its provenance is
reattached. `remove` drops the section unless it still carries tables or
figures, in which case the removal is refused and the section kept with a
warning. `merge_into_previous` folds a section's content, tables,
figures, and segments into the previous kept section, whether that
section came from the same window or, via `previous_kept`, the window
before it. `keep` and `replace` pass the section through as is.

### Cleanup and reporting

Once every window is assembled, `_reattach_media_bbox` restamps each
table's and figure's `bbox` from the Stage 3 input, since the model
re-emits those objects and may drop or alter the field. Sections left
with no content, tables, or figures are dropped (`_is_empty_section`).
`_finalize_pages` recomputes each section's `pages` from its segments and
media; `_backfill_empty_pages` gives a still-empty one its nearest
neighbour's page rather than leaving it uncitable. With
`TITLE_CLEANUP_ENABLE`, `_normalize_title` strips leading numbering
prefixes and capitalizes an ALL-CAPS title word-by-word (first letter
kept, rest lowercased; short acronyms excepted). `_report_dropped_text`
then compares input and output text by word-shingle overlap, logging the
count and size of every section that vanished, naming only the largest
six; a falling count is not itself a fault, since removing an index or an
abbreviations list is expected here.

## Data model

`sections_refined.json` is `{"sections": [...]}`. Each element:

| field | type | notes |
|---|---|---|
| `title` | string | `"[LITERATURE]"` marks a converted bibliography |
| `content` | string, or list of strings | a list only for a `[LITERATURE]` section, one BibTeX entry per item |
| `page_number` | int or null | the section's first page |
| `pages` | list of int | every page the section's segments or media touch |
| `tables` | list of objects | `id`, `path`, `caption`, `page_number`, `bbox` |
| `figures` | list of objects | same shape as `tables` |
| `segments` | list of objects | `page`, `kind` (`text`, `table`, or `figure`), and `text` or `ref` |

A table's or figure's `id` is the block id a placeholder such as
`[p5_tbl0]` refers to; the placeholder survives refinement verbatim, the
only anchor `_thread_provenance` has between an input segment and the
output section that ends up owning it.

`refinement_report.json` is written on every run, whether or not anything
failed: an empty `failed_windows` list means the pass checked and found
nothing wrong, while a missing file means nobody has looked yet. Its shape:

| field | type | notes |
|---|---|---|
| `total_windows` | int | windows attempted for this document |
| `failed_windows` | list of objects | one entry per window that kept its original text |

Each `failed_windows` entry carries `window` (1-based), `reason` (`no usable
reply` or `no usable sections`), `sections` (0-based indices into the
pre-refinement list), and `titles` (each truncated to 80 characters).

`.prompt_versions.json` is written by `docpipe.prompts.record` and maps a
prompt id to its sha256, for the two `PROMPT_IDS`: `refinement/refine` or
`refinement/refine_corrections` per `REFINE_RETURN_CORRECTIONS`, plus
`refinement/split` (see [Artifacts](../artifacts.md) for every stage's
file layout).

## Configuration

| name | kind | default | effect | where read |
|---|---|---|---|---|
| `LLM_BASE_URL` | env, string | `http://localhost:8000/v1` | the OpenAI-compatible endpoint the stage calls | `config.py` |
| `LLM_MODEL` | env, string | `Qwen/Qwen3.5-122B-A10B-FP8` | model name checked against the server's served models | `config.py` |
| `LLM_API_KEY` | env, string | `EMPTY` | sent as the API key; ignored by vLLM | `config.py` |
| `LLM_TIMEOUT` | env, seconds | `180` | per-request timeout of the OpenAI client | `config.py` |
| `LLM_NUM_PARALLEL` | env, int | `8` | windows dispatched concurrently per document | `config.py` |
| `DOC_PARALLEL` | env, int | `8` | documents refined concurrently in `--batch` mode | `pipeline.py` |
| `MAX_RETRIES` | constant | `4` | retry attempts inside one window's LLM call | `config.py` |
| `REFINE_WINDOW_SIZE` | env, int, or profile hook `refinement.WINDOW_SIZE` | `3` | sections sent to the LLM per call (`WINDOW_SIZE`) | `config.py` |
| `SECTION_SPLIT_ENABLE` | constant | `True` | whether oversized sections are split at all | `config.py` |
| `SECTION_MAX_WORDS` | constant | `1000` | threshold above which a section is split | `config.py` |
| `SECTION_TARGET_WORDS` | constant | `600` | size a split aims each part at | `config.py` |
| `SECTION_OUTLINE_WORDS` | constant | `14` | words per segment shown in the split outline | `config.py` |
| `SPLIT_TEMPERATURE` | prompt front matter, float | `0.1` (both profiles) | sampling temperature for the section-split LLM call | `split.py` |
| `SPLIT_MAX_TOKENS` | prompt front matter, int | `1024` (both profiles) | reply token ceiling for the section-split LLM call | `split.py` |
| `TITLE_CLEANUP_ENABLE` | constant | `True` | whether the prefix strip and ALL-CAPS capitalization run | `config.py` |
| `REFINE_RETURN_CORRECTIONS` | env, bool | off | switches the reply from a full rewrite to a find-and-replace edit list | `config.py` |
| `MAX_SHRINK` | constant | `0.30` | ceiling on how much edit mode may shrink a section | `corrections.py` |
| `REFINE_REPLY_CEILING` | env, int | `16384` | ceiling on one request's reply token budget (`REPLY_TOKENS_CEILING`) | `config.py` |
| `LLM_TEMPERATURE` | env, float, or the prompt's front matter | `0.1` (both profiles) | sampling temperature | `config.py` |
| `LLM_MAX_TOKENS` | env, int, or the prompt's front matter | `8192` (both profiles) | floor for the reply token budget on small windows | `config.py` |
| `--force` | CLI flag | off | ignores an existing `sections_refined.json` and re-refines | `pipeline.py` |
| `--force-stale` | CLI flag | off | re-refines only documents whose recorded prompt hash changed | `pipeline.py` |
| `--print-context-budget` | CLI flag | off | prints `max_request_tokens()` and exits, for sizing the server's `--max-model-len` | `pipeline.py` |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | supplies the default input path (`profile.processed_dir`) when none is given | `pipeline.py` |
| `--log-level` | CLI flag | `INFO` | logging level: `DEBUG`/`INFO`/`WARNING`/`ERROR` | `pipeline.py` |

Neither current profile overrides `WINDOW_SIZE` (see
[Profiles](../profiles.md)), so both run at the default of 3. Flipping
`REFINE_RETURN_CORRECTIONS` changes which prompt id `PROMPT_IDS` names, so
a document cached under the other mode reads as stale on the next run.

## Failure modes

`_call_llm` retries an empty reply, invalid JSON, or a missing `sections`
key up to `MAX_RETRIES` (4) times (see Method for echo and abandonment
details); a 4xx status other than 429 is not retried, and a "maximum
context length" error abandons the window outright. 429, 5xx, connection,
and timeout errors retry with backoff (`_backoff`, capped at 10 seconds).

A window that exhausts its retries, or is abandoned, keeps its original
sections verbatim, `_action` stripped, and is recorded under
`failed_windows` in `refinement_report.json`. A `remove` action on a
section still carrying tables or figures is refused; the section is kept,
with a warning naming how many of each it holds. A `merge_into_previous`
with no previous section available (a document's first window) is kept
rather than dropped.

In edit mode, an edit is refused, original text kept, when its quoted
text is absent, occurs more than once, touches a placeholder, or the
edits together shrink the section by more than `MAX_SHRINK`. A
section whose `segments` no longer reproduce its `content` is left
oversized rather than split at a guessed position; a split reply still
over `SECTION_MAX_WORDS` is re-cut mechanically by `_enforce_max`.

`run()`'s preflight (see Method) refuses to start before the first
document rather than mid-run. A document with no `results/sections.json`
is not a `--batch`-mode candidate (`_has_input`). A killed `--force` run
never leaves a document without refined output, since `dump_json_atomic`
replaces the old file in one step; a refinement report that
fails to write is logged and swallowed rather than failing an
already-successful run.

## Measured behaviour

Across 60 ar6 documents, 28% of sections came back byte-identical from a
full rewrite, the median section was 99% unchanged, and only 166 of 4887
sections were real conversions (`docpipe/refinement/corrections.py:6-8`,
`docpipe/refinement/config.py:63-64`): the stage spent output tokens, a
request's costliest part, retyping input it was not changing, which is
why `REFINE_RETURN_CORRECTIONS` exists.

Isolating each edit's quoted text against the original, rather than
against the text left by earlier edits in the same section, changed how
often a correction was refused: of 4828 corrections on one book, 1144
were refused for overlapping a passage a preceding correction had just
rewritten (`docpipe/refinement/corrections.py:28-29`).

Before the check refusing `remove` on a section carrying tables or
figures existed, eleven plans with no text layer, their section bodies
placeholder markers only, lost 1270 transcribed tables and figures that
way (`docpipe/refinement/refine.py:432-434`). Before every section of a
window carried through by default rather than only what a reply named, a
reply naming only some of a window's sections cost one book 123 of its
2697 sections, and another run 237 (`docpipe/refinement/refine.py:159-160`).

Before the context-size preflight existed, 42 windows silently kept raw
text against a server whose `max_model_len` was smaller than a request
could need (`docpipe/llm_preflight.py:8-9`). Under a flat, non-scaling
reply budget, 24 of 1030 windows in one ar6 book run had their JSON reply
truncated mid-string, each an "Unterminated string" error
(`docpipe/refinement/config.py:97`).

Before segments could be subdivided, 51 sections in one ar6 run stayed
oversized however often the split was asked, up to 1409 words against the
1000-word `SECTION_MAX_WORDS` limit, since their whole text sat in one
segment with no boundary to cut on (`docpipe/refinement/split.py:254-256`).
The model's proposed cut is a suggestion, not a bound: an 11596-word
section came back as 10 parts, one still 2392 words, which is what
`_enforce_max` exists to correct (`docpipe/refinement/split.py:285-286`).

## Verification

The retry and abandonment behaviour of `_call_llm`, and that a repair turn
never resends the whole failed answer:
`test_an_oversized_window_is_abandoned_not_retried`,
`test_the_abandoned_window_is_named_out_loud`,
`test_any_other_client_error_also_stops_at_once`,
`test_a_busy_or_broken_server_is_still_retried`,
`test_a_short_answer_is_echoed_whole`,
`test_a_long_answer_is_bounded_before_it_goes_back`
(`tests/test_textrefinement_refine.py`).

Page provenance survives a split, a merge across a window boundary, and a
section a reply silently omitted: `test_thread_provenance_split_in_middle_of_window_keeps_siblings_exact`,
`test_redistribute_drops_unanchored_text_orphan_no_phantom_page`,
`test_omission_shrink_does_not_leak_removed_section_pages`,
`test_cross_window_merge_spans_both_windows` (`tests/test_textrefinement_provenance.py`).

A `remove` action never discards a section's tables or figures:
`test_remove_is_refused_for_a_section_that_carries_media`
(`tests/test_refinement_force_keeps_output.py`).

Title cleanup strips numbering prefixes and de-shouts ALL-CAPS titles,
sparing acronyms and `[LITERATURE]`: `test_numbering_prefix_is_stripped`,
`test_all_caps_is_deshouted_keeping_acronyms`,
`test_literature_sentinel_and_years_untouched`
(`tests/test_stage_cleanup.py`). `_reattach_media_bbox` restamps `bbox`
from the Stage 3 input by block id across a split, a no-op without
geometry: `test_reattach_media_bbox_stamps_by_id_across_split`,
`test_reattach_media_bbox_noop_without_geometry`
(`tests/test_segment_bbox.py`).

A forced re-refine never leaves a document with no refined output, and
`refinement_report.json` tells "checked, nothing failed" apart from
"nobody has looked": `test_a_forced_run_that_dies_leaves_the_previous_refinement`,
`test_run_single_passes_force_through_instead_of_unlinking`,
`test_a_clean_run_records_an_empty_list_not_a_missing_file`,
`test_the_stage_records_which_windows_kept_their_originals`
(`tests/test_refinement_force_keeps_output.py`).

Every edit in correction mode is checked against the text the model
actually saw: `test_edits_are_checked_against_the_text_the_model_was_given`,
`test_two_corrections_to_one_sentence_keep_the_longer_one`,
`test_a_wholesale_deletion_is_refused`, `test_a_whitespace_only_miss_is_named_as_such`
(`tests/test_corrections.py`).

Splitting a section keeps its text intact and each part's own media and
pages, drops slivers, and leaves an unreproducible section untouched:
`test_the_parts_together_are_the_original_text`,
`test_each_part_keeps_only_its_own_media_and_pages`,
`test_a_cut_that_would_leave_a_sliver_is_dropped`,
`test_a_section_whose_segments_do_not_match_its_content_is_not_touched`,
`test_a_section_that_cannot_be_cut_is_not_asked_about`,
`test_the_split_calls_go_out_together` (`tests/test_split.py`). Its cut
never exceeds `SECTION_MAX_WORDS`; the context budget reacts to the
knobs it names and covers the largest possible reply; and the preflight
stops a run before the first document, not after a mid-run rejection:
`test_split_holds_its_own_limit`,
`test_one_huge_segment_is_subdivided_not_surrendered`,
`test_budget_reacts_to_the_knobs_it_names`,
`test_the_budget_covers_the_largest_reply_it_would_ask_for`,
`test_preflight_rejects_a_server_with_too_little_context`,
`test_preflight_rejects_a_server_serving_another_model`
(`tests/test_context_budget.py`).

## Modules

`config.py` holds the stage's tunable constants and compiled system
prompt: the LLM connection settings, `WINDOW_SIZE`, the oversized-section
thresholds, and the reply-budget arithmetic. `pipeline.py`, `refine.py`,
and `split.py` import from it; `corrections.py` keeps its own
`MAX_SHRINK` and placeholder-pattern constants independently.

`corrections.py` holds `apply_corrections`, checking one section's
find-and-replace edits against the text the model was given: a single,
exact match per edit, placeholders intact, `MAX_SHRINK` held on the whole
list. Called from `refine.py`'s `_materialise_corrections` in edit mode.

`split.py` cuts a section over `SECTION_MAX_WORDS` at segment boundaries:
`split_oversized` drives the pass, `_ask_all_cuts` dispatches every
document's requests concurrently, and `_enforce_max` with
`_subdivide_segments` re-cut any part still oversized. Called by
`refine.py`'s `refine_sections`, before windowing.

`refine.py` is the stage's core: `refine_sections` dispatches the
windows, `_call_llm` makes one window's request, `_thread_provenance` and
`_redistribute_segments` reattach page provenance, `_apply_actions`
applies the LLM's actions, and `_normalize_title` and
`_report_dropped_text` finish the pass. Called by `pipeline.py`'s
`run_refine`.

`pipeline.py` orchestrates the stage: `run_single` decides between a
cache hit and a fresh run, `run_batch` runs every document subdirectory
concurrently, and `run` calls `assert_serving` first. Entry point for
`python -m docpipe.refinement` and library callers of `run()`.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/refinement/pipeline.py</code></summary>

pipeline.py: Orchestrates the textrefinement stage.

Refines one document directory, or every document subdirectory under
a processed root with `--batch`, sending each document's Stage 3
sections through the LLM refinement pass in refine.py.
`_build_parser` lists the CLI flags.

Before refining, `assert_serving` (docpipe.llm_preflight) checks that
the configured LLM server accepts a request of the worst-case size
this stage can send, so an undersized server is caught before the
first document rather than mid-run.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/refinement/refine.py</code></summary>

refine.py: Runs Stage 4, the LLM-based refinement of Stage 3
sections.

The LLM is asked, per window of sections, to clean extraction
artefacts and titles, drop directory sections, convert bibliographies
to BibTeX, and merge or split sections; each returned action is
applied by refine_sections. A section longer than the split threshold
is cut before windowing (see split.py), since a window has to echo
every section it carries, and an oversized section could never be
echoed.

Windows are dispatched in parallel, up to LLM_NUM_PARALLEL requests
at once, then assembled in the original order, since merging and
splitting are positional. A request is retried up to MAX_RETRIES
times, except on a 4xx response, which is not retried because the
server has refused the request itself. A window that never returns a
usable reply keeps its original, unrefined text, and is recorded in
the refinement report written next to the output.

Page provenance travels with the rewritten text: an unchanged window
reattaches its segments one to one, and a window that split, merged
or dropped sections is redistributed by which output section's
tokens a segment's text is found in, or by which output claims a
table's or figure's block id. A "remove" action is refused when the
section still carries a table or figure, since those are Stage 2
artefacts with their own transcriptions and not the model's to
discard; a section made of nothing but reference markers can
otherwise look empty to a reader of the text alone.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/refinement/split.py</code></summary>

split.py: Cuts a section too long to be one retrieval chunk into
several, each a self-contained citation unit.

A section is one chunk and one vector. Past a certain length that
vector stops meaning anything in particular, and past the embedding
model's token limit the tail is not indexed at all, so an oversized
section has to become several.

The model is asked only where it would cut and what to call the
parts, never to reproduce the text. The cut itself happens
mechanically at segment boundaries, which is what makes it safe:
nothing is rephrased, dropped or invented, and each part keeps
exactly the pages, tables and figures that belong to its own text.
Asking only for an outline also keeps the call small, since a section
long enough to need splitting is by definition too long to echo.
When no cut is asked for, or the reply is unusable, a mechanical
fallback cuts at even word-count intervals instead, dropping a cut
that would leave a sliver under about 100 words.

A part still over the configured word limit after this pass is cut
again against a lower target; a single segment carrying the whole
overflow is first divided into smaller ones so that a boundary exists
to cut at. A section whose segments no longer reproduce its own
content, because refinement rewrote it, is left oversized rather than
cut at a guessed position.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/refinement/corrections.py</code></summary>

corrections.py: Applies a model's edit list to a section and refuses
the edits that do not hold up.

Refinement used to have the model return the whole section, which is
mostly retyping: measured over 60 ar6 documents, 28% of sections came
back byte-identical, the median similarity was 99%, and only 166 of
4887 sections were real conversions, so the stage spent the expensive
part of the call, the tokens it writes, on copying its own input.

Asking for the changes instead is cheap, and unsafe unless every one
of them is checked against the original first: a find or replace the
model half-remembered would otherwise rewrite a sentence nobody asked
it to touch, or match in two places and change the wrong one. Nothing
here is applied on trust. The text to find must be present, exactly
once, in the section as the model received it, the only text it can
honestly be quoting. Where two corrections cover the same passage,
the longer one wins and the other is reported as overlapping. An
edit may not add, drop or alter a [pN_tblM] or [pN_imgM] placeholder.
The edits together may not remove more than MAX_SHRINK of the
section.

The first two rules used to be one: each find was looked up in the
text left by its predecessors. That punished the model for following
the instruction to quote whole sentences, since two fixes to one
sentence then overlap by construction, and the second was reported as
quoting text absent from the document when the text had in fact been
edited away moments earlier by the first. Of 4828 corrections checked
this way on one book, 1144 were refused for that reason.

A rejected edit is dropped and reported, never guessed at. If the
caller finds anything in the returned report, keeping the original
section is the safe choice, since the model's picture of it evidently
did not match.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
