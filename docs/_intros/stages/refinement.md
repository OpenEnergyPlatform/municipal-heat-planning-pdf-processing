## Purpose

Stage 3 (`docpipe.preprocessing`) builds `sections.json` mechanically
from PyMuPDF text extraction and PP-DocLayoutV3 layout boxes; its
cleanup pass already strips repeated header and footer lines and drops
obvious directory pages (see [Preprocessing](preprocessing.md)). What survives that
pass is the kind of defect a fixed rule cannot resolve reliably: a caption
on the wrong table, a heading split across a page break into two
sections, an unstructured bibliography, an ALL-CAPS title. Stage 4
hands each document's sections to an LLM, in windows, to resolve those
cases (`docpipe/refinement/refine.py`). The same call also cleans
text-level artefacts: broken hyphenation, leaked headers and footers,
garbled Unicode. The scenarios profile's prompt adds one case by
example, a preprint's line numbers landing inside a sentence: a number
counting up line after line is removed, one the sentence itself states
stays.

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
| Out | `results/sections_refined.json`, `results/refinement_report.json`, `results/.prompt_versions.json`, and `results/sections_refined.partial.json`: in place of the first while a window the server did not serve is outstanding (that pass leaves the report as it is), and beside it while a window of the output is a hole |
| Resumes on | the presence of `sections_refined.json` with no `sections_refined.partial.json` beside it; a partial file is resumed window by window, asking only the windows it holds no reply for (not served, or a hole); `--force` redoes every candidate document, `--force-stale` only those whose prompt hash no longer matches |
| Needs | a model server reachable at `LLM_BASE_URL` (an OpenAI-compatible one, or a hosted API chosen with `LLM_PROVIDER`; see [the provider layer](providers.md)) that takes the stage's reply schemas as the `response_format` of a request, checked before the first document by `assert_serving` |

Stage 4 follows Stage 3's structuring pass and precedes two consumers
that treat `sections_refined.json` differently. [Visuals](visuals.md)
(Stage 5) prefers it but falls back to `sections.json` when absent
(`_resolve_input` in `docpipe/visuals/pipeline.py`), so the two stages
can run against separate model servers without waiting on each other.
[Chunking](chunking.md)'s merge step has no such fallback and requires
`sections_refined.json` outright (`docpipe/chunking/merge.py`), so an
unrefined document is not a merge candidate, and `merge_batch` names such
documents in one warning. The stage imports no GPU
library; its only external dependency is the `openai` client reaching
`LLM_BASE_URL`.

## Method

### Preflight and caching

`run()` calls `assert_serving` once, before the first document, with the
worst case one window could cost (`max_request_tokens()`); an undersized
or wrong server stops the run at once rather than letting individual
requests fail mid-batch. The same call puts every reply schema the stage
will send to the server once, as the stage will send it (`reply_shapes()`:
`refined_sections`, built from a sample section of the shape Stage 3 writes
(or the edit list's schema in edit mode), and `section_cuts`;
`assert_reply_schemas` asks one request of 32 tokens per schema). The stage
asks for JSON in no other way, so a server that refuses a schema with a 4xx
other than 429 would refuse every request of the run, and the run ends with
exit 1 before the first document. A server that does not answer the probe
(busy, down, a 5xx, a 429) gives no verdict, and the run goes on. `main`
also reads the profile's `reading.PHRASES` before the first document
(`reading.phrases()`, after `--print-context-budget`, which asks nothing of
the model): a profile that lacks one of the sentences ends the run there
with a `LookupError`, not in the middle of the first document.

`max_request_tokens()` is the worst case of one window: the prompt, a full
window of maximum-size sections and one largest reply
(`largest_reply_tokens()`). That reply is `REFINE_REPLY_CEILING` tokens (16,384
by default) in window mode and `LLM_MAX_TOKENS` tokens (8,192 by default) in
edit mode, whose replies are sized by that setting and not by the window. It
prints 28,543 tokens with the `kwp` profile and 29,065 with `scenarios`.
`assert_serving` checks the served window against it and keeps the window for
the run (`llm_preflight.served_window`; none where the server reports none, or
where no preflight ran). What the window holds beyond the budget is what a unit
that was cut off and cannot be split is asked once more with (see The LLM call).

When `results/sections_refined.json` exists,
`run_single` compares its recorded prompt hashes against the prompts now
in use with `prompts.check`: a moved hash sets `force` under
`--force-stale`, otherwise it only logs a warning. `run_single` always
calls `run_refine`, and it is `run_refine`, not `run_single`, that reads
that file back without calling the LLM whenever it exists, `force` is
false and no partial file sits beside it (see A window the model could not
read and A window the server did not serve), so an unforced stale prompt is
still served from cache. `prompts.record` writes the new hashes once a pass
finishes.

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
whole, with a warning, rather than cut at a guessed position. A resumed
pass skips this step: its sections are the ones the unfinished pass cut.

The request is read like a window's: the schema `section_cuts` is its grammar,
the reply is exactly one object with a `cuts` list, and a reply that is not
that is asked again with its cause named. A reply that was cut off is asked
again for half of the outline, since the outline has one line per segment:
`_ask_range` asks for the first and the second half of the segments, the
second half keeping the numbers its segments have in the section, and joins
the cuts with the cut between the halves; an outline of one segment has no
halves and is asked once more with more room, by the rule for a unit that
cannot be split (see The LLM call), counted from `split_max_tokens()`. A reply
that stays unreadable, a request the server refused, a reply cut off again, a
served window that leaves no more room, or a half that is itself a hole makes
the cut a hole: the
section is cut mechanically at even word counts, and the report names it
under `mechanical_cuts` with the cause. An answer of no cuts at all is an
answer, and no hole. A split request the server does not answer is asked
again like a window's, and a pass whose cut stays unanswered ends without
output (see A window the server did not serve).

### Windowed dispatch

`refine_sections` groups the bounded sections into consecutive windows of
`WINDOW_SIZE` and submits each to `_ask_window`, which calls `_call_llm`, on a `ThreadPoolExecutor`
sized to `LLM_NUM_PARALLEL`. Every window but the first also receives
`prev_ctx`, the previous window's last section, passed read-only so the
model can recognise a heading split across the boundary and mark the new
window's first section `merge_into_previous` instead of a new section.

### The LLM call

`_call_llm` strips `segments` and `pages` from the payload before it is
sent (the model must not see or rewrite them) and, in edit mode, adds
each section's index and reduces its tables and figures to `id` and
`caption` only. The reply schema is the `response_format` of every
request, on every provider (`providers.grammar`): `replies.window`, built
per window from the keys its sections carry, or `replies.CORRECTIONS` in
edit mode. `reading.read` takes the reply as exactly one JSON object with a
`sections` list, and as nothing else: no code fence or `<think>` block is
stripped, no object is cut out of surrounding text, no bracket is closed,
and nothing is salvaged from a reply that was cut off (see [the parts every
stage uses](core.md)). The stage checks no more of the list than that it is
one; an entry that is no object is dropped before the window is assembled,
and a list with no object in it (an empty one too) is a hole named
`wrong_shape`.

A reply that is not that object is asked again, up to `MAX_RETRIES`
attempts in all, with `_backoff` between them (`min(2 * attempt, 10)`
seconds). The next request is the original one, then an assistant turn with
a bounded echo of the bad reply (`_echo`, at most 400 leading and 200
trailing characters; empty when the reply had no text), then a user turn
that names the cause in the profile's words (`reading.PHRASES`) and repeats
the shape that was asked for. The cause is one of:

| cause | the reply was |
|---|---|
| `reasoning_only` | without text, the answer having gone into the reasoning |
| `empty` | empty |
| `no_object` | text with no `{` in it |
| `syntax` | text with a `{` from which no complete object can be read; the position of the break is named |
| `outside_text` | one well-formed object with text before or after it |
| `not_an_object` | well-formed JSON that is a list, a string or a number |
| `missing_key` | an object without `sections`, or with a `sections` that is no list |
| `cut_off` | not readable, and ended at its token limit (no sentence: see below) |

A reply that was cut off (`finish_reason` is `length`) has no sentence and is
never asked again as it stands. `_call_llm` returns a hole, and `_ask_window`
answers it. A window of several sections is asked again as its first half
and its second half, by sections, and a half that is cut off is halved the
same way; the second half is given the last section of the first as its
context, which is what the next window would see. A unit that cannot be split
(a window of one section, and in a cut request an outline of one segment) has no
halves and is asked once more, once, with more room (`again`). The token limit of
that attempt is the smaller of twice what the request asked for and the largest
reply the budget counts plus what the served window holds beyond the budget:
`min(2 x asked, reply + window - budget)`, in tokens (`further_room` in
`refinement/config.py`, which asks `llm_preflight.further_room`;
`refine._further_tokens` logs both numbers). The window is the one the server
reported at the preflight. Where it is not known, because the caller ran no
preflight or the server reports none, the limit is twice what the request
asked. Where the window leaves no more room than the request already had, the
unit is a hole `cut_off` at once, no second request is sent, and the log names
the served window in tokens. A second cut-off is a hole `cut_off`. The reply
that was cut off is not used. Parts that were all read are laid end to end and
the window is assembled as one that was never cut; when a part is a hole the
window is assembled part by part (`Halved`).

A 4xx status other than 429 is not retried, since an identical retry would be
refused identically; the window is a hole `refused`. A "maximum context
length" error says so at error level, since the window then stays unrefined.
429, 5xx, connection and timeout errors are retried with backoff. An error of
the stage's own while it reads the reply is a hole `error`, with the
traceback in the log, and is not retried.

The sampling temperature and the reply budget are read before the retry
loop and outside its `try` (`refine.py:367-380`). Read inside it, a setting
that cannot be read would fail every attempt and end as `NOT_SERVED`, as if
the server had not answered; read outside it, the call raises, and the
dispatch loop makes the window a hole `error` (`refine.py:1093-1100`). `main`
therefore reads `llm_temperature()` and `llm_max_tokens()` once, right after
the profile is resolved (`docpipe/refinement/pipeline.py:268-272`), so an
unparseable value ends the run at the start and does not fail inside every
request.

### A window the model could not read

A window whose attempts all ended on a reply that could not be read, whose
request the server refused, that was cut off with no more room to give, or
whose reading failed in the stage's own code is a hole (`reading.Hole`), and
its cause is one of the causes above plus `refused` and `error`. The window
keeps its original sections verbatim, `_action` stripped (of a window asked
in halves, only the part that is a hole), and is listed in `failed_windows`
of the refinement report with that cause. The stage still writes
`sections_refined.json`, with that text in place of the refined text: the
output alone cannot tell such a window from one that needed no change, the
report can.

`results/sections_refined.partial.json` stays beside the output for as long
as a window is a hole. It holds the sections as the pass cut them and the
replies of the windows that were read, and no reply for the holes. A plain
run finds the partial file beside a final file, so it does not take the
final file as a cache hit: it asks exactly the windows the report lists and
no other, does not cut the sections again, and replaces the output when it
is done. The partial file goes when no window is left as a hole. A window
whose list held no section (`wrong_shape`) is asked again too, and so is a
window asked in halves of which only one part is a hole: the report lists the
sections of that part, the next run asks the whole window. The key check
below applies as it does to an unserved pass. `docpipe status` counts a
document with a partial file beside its output as not refined, `docpipe
estimate` counts only the windows the partial file holds no reply for, and
`--force` resumes it like any unfinished pass.

A hole changes no exit code: a document whose windows are holes is written and
is a success to the run. The run says so once, in the units each number counts, at
its end: `Stage 4: 3 window(s) (7 section(s)) in 2 document(s) kept their
original text; hole(s) by cause: cut_off 2, syntax 1`. A request the server did
not serve still ends the run non-zero, as it did.

### A window the server did not serve

`_call_llm` ends one of three ways. It returns the parsed sections; or it
returns a hole, above; or it returns `NOT_SERVED`
(`docpipe/refinement/refine.py:102`) when its last attempt got no answer at
all: no connection, a timeout, a 429 or a 5xx. The last attempt decides: a
503 followed by replies nobody can read is a window the model got and could
not do; the other way round it is a window nobody answered. A `NOT_SERVED`
window cannot be told from one that needed no change, so `refine_sections`
raises `Unfinished` before it assembles anything (`refine.py:1102-1109`).

`run_refine` then writes no `sections_refined.json`. The sections as cut,
the usable replies by window index and, as `total_windows` and
`unserved_windows`, the number of windows and the 1-based numbers of those
the server did not serve go to `results/sections_refined.partial.json`
(`refine.py:1412-1419`). `refinement_report.json` is not touched: it
describes the refined output beside it, and this pass wrote none. An error
is logged and the call returns `None`, so `run_batch` counts the document
as failed and `main` exits 1; `prompts.record` is not called
(`refine.py:1404-1424`). The next run, forced or not, reads the partial file
(`_read_partial`; one that cannot be read counts as absent), does not cut
the sections again and asks only for the windows without a usable reply
(`refine.py:1352-1353`, `1386-1391`). It does so only if the unfinished
pass agrees with this one: `_partial_key` hashes the input sections (after
`run_refine` has stripped `source_text` from their tables, before the key is
taken), the prompt hashes (`PROMPT_IDS`), `WINDOW_SIZE` and the model name
`LLM_MODEL` (`refine.py:1372-1375`, `1453-1461`). On a mismatch the partial
file is deleted with a warning and the pass starts over, an existing
`sections_refined.json` being served from cache unless `--force` is given
(`refine.py:1377-1385`). A `sections_refined.json` from an earlier pass
stays in place until a pass finishes, and a finished pass with no hole left
deletes the partial file (`refine.py:1441-1445`).

The cut of an oversized section is the other request whose outage ends a
pass. `_make_splitter` asks again while the server does not answer, up to
`MAX_RETRIES` attempts with the backoff a window gets, and raises
`split.NotServed` when it stays that way (`refine.py:911-988`,
`docpipe/refinement/split.py:59`). A refused request (a 4xx) or a reply that
stays unreadable is a hole and falls back to the mechanical cut at once
(see Splitting oversized sections), and `NotServed` is raised out of `_ask_cuts`
(`split.py:227-243`), not turned into a mechanical cut. `refine_sections` turns it into
`Unfinished(None, {}, [], 0)` (`refine.py:1043-1048`), and `run_refine` then
writes nothing at all, neither a refined output nor a partial file, logs an
error and returns `None` (`refine.py:1405-1409`). The next run starts with
the cut. Nothing is kept because a section cut mechanically for the want of
an answer would keep those cuts: the windows of a partial are cut from the
sections as they were split, and a resumed pass does not cut again. A pass
that was not served after the cut was made keeps the sections as cut and the
cuts the model did not place (`mechanical_cuts`), which a resumed pass does
not cut again and so could not find out.

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
warning. The text of a removed section goes, its heading stays behind as
a bare heading for the cleanup below to hand on, since a contents page or
an authors' block can be headed by the document's title; the profile's
`FRONT_SECTION_TITLE` is not a heading of the document and is not kept.
`merge_into_previous` folds a section's content, tables,
figures, and segments into the previous kept section (never into a heading
left behind by a removal), whether that
section came from the same window or, via `previous_kept`, the window
before it. `keep` and `replace` pass the section through as is.

### Cleanup and reporting

Once every window is assembled, `_reattach_media_bbox` restamps each
table's and figure's `bbox` from the Stage 3 input, since the model
re-emits those objects and may drop or alter the field. A section that
is a heading and nothing else, such as a paper's title set apart from
its authors, hands that heading to the next section, as the first line
of its text and followed by that section's own heading
(`_fold_bare_headings`), so the title stays readable and quotable and a
title broken over several headings reads in its order. Sections left with no content, tables, or figures are then
dropped (`_is_empty_section`); a heading with no text after it, or one
before a literature list, goes with them.
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

`sections_refined.partial.json` exists while a pass is unfinished (a window
the server did not serve; there is no output beside it then) and while a
window of the output is a hole (it sits beside the output):
`{"key": ..., "sections": [...], "total_windows": N, "unserved_windows":
[...], "mechanical_cuts": [...], "windows": {...}}`. `key` is the hash
`_partial_key` computes over the input sections, the prompt hashes,
`WINDOW_SIZE` and `LLM_MODEL`; `sections` are the sections as cut;
`total_windows` is the number of windows of the pass and `unserved_windows`
the 1-based numbers of those the server did not serve (empty beside an
output); `mechanical_cuts` are the sections whose cut the model did not
place, as in the report; `windows` holds the replies of the windows that
were read by 0-based window index, and none for a hole
(`REFINEMENT_PARTIAL_JSON`, named in `docpipe/artifacts.py`). A file written
before `mechanical_cuts` was recorded has no such key, and a resume reads
that as none recorded. The file is written through `clean_data`
(`refine.py:1412-1419`).

`refinement_report.json` is written by every pass that finishes, whether or
not anything failed: an empty `failed_windows` list means the pass checked
and found nothing wrong, while a missing file means nobody has looked yet.
A pass that does not finish leaves the report as it was, and the partial
file carries what the report would not. Its shape:

| field | type | notes |
|---|---|---|
| `total_windows` | int | windows attempted for this document |
| `failed_windows` | list of objects | one entry per window, or per part of a window asked in halves, that kept its original text |
| `mechanical_cuts` | list of objects | one entry per section cut mechanically because the model's cut was not read |

Each `failed_windows` entry carries `window` (1-based), `reason` (the cause
of the hole: `cut_off`, `reasoning_only`, `empty`, `no_object`, `syntax`,
`outside_text`, `not_an_object`, `missing_key`, `wrong_shape`, `refused` or
`error`; a report an earlier version wrote has `no usable reply` or `no usable
sections` instead), `sections` (0-based indices into the pre-refinement
list) and `titles` (each truncated to 80 characters). Each `mechanical_cuts`
entry carries `title` and `why`, a cause of the same kind.

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
| `MAX_RETRIES` | constant | `4` | attempts at one request (a window, a cut of a section), a re-ask after an unreadable reply included | `config.py` |
| `REFINE_WINDOW_SIZE` | env, int, or profile hook `refinement.WINDOW_SIZE` | `3` | sections sent to the LLM per call (`WINDOW_SIZE`) | `config.py` |
| `SECTION_SPLIT_ENABLE` | constant | `True` | whether oversized sections are split at all | `config.py` |
| `SECTION_MAX_WORDS` | constant | `1000` | threshold above which a section is split | `config.py` |
| `SECTION_TARGET_WORDS` | constant | `600` | size a split aims each part at | `config.py` |
| `SECTION_OUTLINE_WORDS` | constant | `14` | words per segment shown in the split outline | `config.py` |
| `split_temperature()` | prompt front matter, float | `0.1` (both profiles) | sampling temperature for the section-split LLM call | `split.py` |
| `split_max_tokens()` | prompt front matter, int | `1024` (both profiles) | reply token ceiling for the section-split LLM call | `split.py` |
| `TITLE_CLEANUP_ENABLE` | constant | `True` | whether the prefix strip and ALL-CAPS capitalization run | `config.py` |
| `REFINE_RETURN_CORRECTIONS` | env, bool | off | switches the reply from a full rewrite to a find-and-replace edit list | `config.py` |
| `MAX_SHRINK` | constant | `0.30` | ceiling on how much edit mode may shrink a section | `corrections.py` |
| `REFINE_REPLY_CEILING` | env, int | `16384` | ceiling on one request's reply token budget (`REPLY_TOKENS_CEILING`); the context budget counts it once, as the largest reply, see Preflight and caching | `config.py` |
| `LLM_TEMPERATURE` | env, float, or the prompt's front matter | `0.1` (both profiles) | sampling temperature, read by `llm_temperature()`; `main` reads it once at the start, so an unparseable value ends the run there | `config.py` |
| `LLM_MAX_TOKENS` | env, int, or the prompt's front matter | `8192` (both profiles) | floor for the reply token budget on small windows, read by `llm_max_tokens()`, which `main` also reads once at the start | `config.py` |
| `--force` | CLI flag | off | ignores an existing `sections_refined.json` and re-refines | `pipeline.py` |
| `--force-stale` | CLI flag | off | re-refines only documents whose recorded prompt hash changed | `pipeline.py` |
| `--print-context-budget` | CLI flag | off | prints `max_request_tokens()` and exits, for sizing the server's `--max-model-len`; asks nothing of the model and needs no profile sentence | `pipeline.py` |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | names the profile whose prompts the run reads and whose `processed_dir` is the default input path; the stage refuses to run without one, since it has no prompt of its own | `pipeline.py` |
| `--log-level` | CLI flag | `INFO` | logging level: `DEBUG`/`INFO`/`WARNING`/`ERROR` | `pipeline.py` |

`LLM_SCHEMA` does not govern this stage: its reply schemas are sent with every
request, on every provider, and there is no value that turns that off. Neither
current profile overrides `WINDOW_SIZE` (see
[Profiles](../profiles.md)), so both run at the default of 3. Flipping
`REFINE_RETURN_CORRECTIONS` changes which prompt id `PROMPT_IDS` names, so
a document cached under the other mode reads as stale on the next run.

## Failure modes

`_call_llm` asks again a reply that is not the one JSON object (empty,
reasoning only, no object, broken syntax, text beside the object, not an
object, `sections` missing or no list) up to `MAX_RETRIES` (4) attempts in
all, naming the cause in the re-ask (see Method for the echo and for what a
cut-off reply does instead); a 4xx status other than 429 is not retried, and
a "maximum context length" error is logged at error level. 429, 5xx,
connection and timeout errors retry with backoff (`_backoff`, capped at 10
seconds); a window whose last attempt still ended on one of them is
`NOT_SERVED`, not a hole.

A window that is a hole (a reply that stayed unreadable, a request the server
refused, a reply that was cut off with no room left to give, a list with no
section in it, an error of the stage's own) keeps its original sections
verbatim, `_action` stripped, and is recorded under `failed_windows` in
`refinement_report.json` with its cause. The refined output is written, the
partial file stays beside it, and the next plain run asks exactly the
windows the report lists. A hole changes no exit code. A window that is not
served keeps nothing: the document is not written as refined, the usable
replies wait in `sections_refined.partial.json` together with the numbers of
the missing windows under `unserved_windows`, the report is left as it was,
and the stage exits non-zero (see Method). The same holds for the cut of an
oversized section that the server does not answer, except that nothing is
kept and the next run starts with the cut.
A `remove` action on a
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
document rather than mid-run: an undersized or wrong server, and a server that
refuses a reply schema of the stage, end the run with exit 1 there, and a
profile without a `reading.PHRASES` sentence ends it with a `LookupError`. A document with no
`results/sections.json`
is not a `--batch`-mode candidate (`run_batch` lists the document directories
that hold `sections.json` through `artifacts.document_dirs`). A killed `--force` run,
or one the server did not serve, never leaves a document without refined
output, since `dump_json_atomic` replaces the old file in one step and
only a finished pass replaces it. `dump_json_atomic` removes its temporary
file and re-raises when a write fails (`docpipe/refinement/config.py:190-210`),
so a file that could not be written is a failed document and not a silent
one; a refinement report that fails to write is the exception, logged and
swallowed rather than failing an already-successful run.

## Measured behaviour

Across 60 ar6 documents, 28% of sections came back byte-identical from a
full rewrite, the median section was 99% unchanged, and only 166 of 4887
sections were real conversions (`docpipe/refinement/corrections.py:6-8`,
`docpipe/refinement/config.py:64-65`): the stage spent output tokens, a
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
way (`docpipe/refinement/refine.py:548-550`). Before every section of a
window carried through by default rather than only what a reply named, a
reply naming only some of a window's sections cost one book 123 of its
2697 sections, and another run 237 (`docpipe/refinement/refine.py:209-210`).

Before the context-size preflight existed, 42 windows silently kept raw
text against a server whose `max_model_len` was smaller than a request
could need (`docpipe/llm_preflight.py:8-9`). Under a flat, non-scaling
reply budget, 24 of 1030 windows in one ar6 book run had their JSON reply
truncated mid-string, each an "Unterminated string" error
(`docpipe/refinement/config.py:111`).

Before segments could be subdivided, 51 sections in one ar6 run stayed
oversized however often the split was asked, up to 1409 words against the
1000-word `SECTION_MAX_WORDS` limit, since their whole text sat in one
segment with no boundary to cut on (`docpipe/refinement/split.py:333-334`).
The model's proposed cut is a suggestion, not a bound: an 11596-word
section came back as 10 parts, one still 2392 words, which is what
`_enforce_max` exists to correct (`docpipe/refinement/split.py:363-364`).

## Modules

`config.py` holds the stage's tunable constants and the readers of its
prompt: the LLM connection settings, `WINDOW_SIZE`, the oversized-section
thresholds, the reply-budget arithmetic (`max_request_tokens()` counts the prompt,
a full window and one largest reply, `largest_reply_tokens()`; `further_room` is
the room a unit that cannot be split is asked once more with), and `system_prompt()`,
`llm_temperature()` and `llm_max_tokens()`, which read the profile's
prompt on first use. `pipeline.py`, `refine.py`,
and `split.py` import from it; `corrections.py` keeps its own
`MAX_SHRINK` and placeholder-pattern constants independently.

`corrections.py` holds `apply_corrections`, checking one section's
find-and-replace edits against the text the model was given: a single,
exact match per edit, placeholders intact, `MAX_SHRINK` held on the whole
list. Called from `refine.py`'s `_materialise_corrections` in edit mode.

`split.py` cuts a section over `SECTION_MAX_WORDS` at segment boundaries:
`split_oversized` drives the pass, `_ask_all_cuts` dispatches every
document's requests concurrently, and `_enforce_max` with
`_subdivide_segments` re-cut any part still oversized; its prompt and
sampling come from `split_prompt()`, `split_temperature()` and
`split_max_tokens()`. A cut is asked through `_ask_cuts` and `_ask_range`,
which halve a cut-off outline and answer with the object read or a `Hole`; a
`Hole` is cut mechanically and named in the report. `NotServed` is its
exception for a split request the server did not answer: it is raised out of
`_ask_cuts` and not turned into a mechanical cut. Called by `refine.py`'s
`refine_sections`, before windowing, and not at all on a resumed pass.

`refine.py` is the stage's core: `refine_sections` dispatches the
windows, `_call_llm` makes one window's request and `_ask_window` halves a
window whose reply was cut off, `_further_tokens` gives the room of the one
further attempt at a lone section or an outline of one segment and says it in the
log, `_make_splitter` makes the cut requests,
`reply_shapes` names the schemas the preflight puts to the server,
`_thread_provenance` and
`_redistribute_segments` reattach page provenance, `_apply_actions`
applies the LLM's actions, and `_normalize_title` and
`_report_dropped_text` finish the pass. `run_refine` is its file-level
entry point: it reads and writes the partial file, the output and the
report, and `Unfinished` carries a pass the server did not finish back to it,
with the sections and replies to keep or, for an unanswered cut, with nothing.
Called by `pipeline.py`'s `run_single`.

`pipeline.py` orchestrates the stage: `run_single` decides between a
cache hit and a fresh run, `run_batch` runs every document directory under
the root, at any depth, concurrently, and `run` calls `assert_serving` first,
with the stage's reply schemas. `main` resolves the
profile, reads `llm_temperature()` and `llm_max_tokens()` once, checks the
profile's reading sentences, and says once at the end what the run left as
holes (`summarise`). Entry point for
`python -m docpipe.refinement`, whose `__main__.py` binds `--profile`
before it imports the stage, and for library callers of `run()`.
