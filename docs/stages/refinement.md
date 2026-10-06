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

A request asks inside its schema, a reply is read as exactly one object, and
the cause of a bad one is said to the model in the profile's words:
`test_call_llm_asks_inside_the_schema_on_its_own_server`,
`test_the_corrections_mode_asks_inside_its_own_schema`,
`test_the_cut_request_asks_inside_the_schema_too`,
`test_a_reply_that_is_not_the_object_is_asked_again_with_its_cause`,
`test_each_cause_is_named_to_the_model_in_the_profiles_words`,
`test_the_answer_that_is_echoed_back_is_bounded`,
`test_call_llm_exhausts_to_a_hole_with_its_cause`,
`test_a_reply_that_breaks_in_our_own_code_is_a_hole_and_not_an_outage`,
`test_the_name_of_the_old_reader_is_gone`
(`tests/test_textrefinement_refine.py`).

A reply that was cut off is never used or asked again as it stands: the
window is asked in halves down to one section, which is asked once more with more
room (twice what it asked where the window is not known), and a window is
assembled part by part when a part is a hole:
`test_a_cut_reply_is_a_hole_and_is_not_used_or_asked_again`,
`test_a_cut_window_is_asked_in_halves`,
`test_halves_are_asked_again_down_to_one_section`,
`test_a_lone_section_that_is_cut_off_gets_twice_the_room_once_where_the_window_is_not_known_and_is_a_hole`,
`test_the_extra_room_is_spent_once_on_a_section_that_then_fits`,
`test_a_window_with_one_part_that_is_a_hole_is_assembled_by_parts`,
`test_a_part_that_is_not_served_makes_the_whole_window_not_served`,
`test_a_cut_request_for_one_segment_is_asked_again_with_twice_the_room_where_the_window_is_not_known`,
`test_a_cut_request_for_one_segment_that_is_cut_off_twice_is_a_hole`
(`tests/test_textrefinement_refine.py`).

The room a unit that cannot be split is asked once more with is the smaller of
twice what it asked and the reply the budget counts plus what the served window
holds beyond the budget; where the window leaves no more room the unit is a hole
at once and no second request is sent; the budget is the prompt, the largest
input and one largest reply; and the window is kept for the role that asked:
`test_a_cut_off_unit_is_asked_once_more_with_more_room_and_then_no_more`,
`test_the_room_is_twice_what_was_asked_where_the_window_leaves_that_much`,
`test_the_room_is_what_the_window_leaves_where_that_is_less_than_twice`,
`test_the_room_is_the_smaller_of_twice_and_the_reply_plus_what_is_left`,
`test_a_window_that_leaves_no_more_room_makes_the_unit_a_hole_at_once`,
`test_one_token_of_room_is_room_and_the_second_request_is_sent`,
`test_the_hole_of_a_lone_window_keeps_the_size_of_the_request_that_was_cut`,
`test_a_window_of_two_sections_is_asked_in_halves_whatever_the_window_leaves`,
`test_an_outline_of_two_segments_is_asked_in_halves_whatever_the_window_leaves`,
`test_a_caller_that_asked_no_server_gives_twice_the_room`,
`test_a_server_that_reports_no_window_gives_twice_the_room`,
`test_the_budget_of_stage_four_is_the_prompt_the_largest_input_and_one_reply`,
`test_a_longer_reply_moves_the_budget_of_stage_four_by_that_reply_once`,
`test_stage_four_takes_a_server_that_serves_exactly_its_budget`,
`test_stage_four_refuses_a_server_one_token_under_its_budget`,
`test_the_command_hands_the_window_it_found_to_the_units_it_asks`,
`test_the_log_of_the_further_attempt_says_both_sizes_in_tokens`
(`tests/test_room.py`).

A hole is written with its original text and named with its cause, and the next
plain run asks exactly the windows the report lists:
`test_a_hole_is_written_with_its_original_text_and_named_with_its_cause`,
`test_every_cause_a_window_can_end_with_is_in_the_report`,
`test_a_reply_with_no_section_in_it_is_a_hole_named_wrong_shape`,
`test_the_next_plain_run_asks_exactly_the_windows_the_report_lists`,
`test_a_resume_writes_what_a_single_pass_writes`,
`test_a_window_that_stays_a_hole_is_asked_again_and_the_others_are_not`,
`test_a_hole_does_not_make_the_next_run_ask_a_window_that_was_read`,
`test_a_pass_that_is_not_served_after_a_hole_keeps_the_output_it_had`,
`test_a_window_asked_in_halves_lists_only_the_part_that_is_a_hole`,
`test_a_run_with_a_hole_exits_as_it_did_and_says_what_it_left_unread`,
`test_a_request_the_server_did_not_serve_still_ends_the_run_non_zero`,
`test_the_summary_counts_windows_sections_and_documents`,
`test_a_cut_the_model_did_not_place_is_named_and_not_made_again`,
`test_a_partial_file_from_before_the_cuts_were_recorded_is_still_read`
(`tests/test_refinement_holes.py`).

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

A window the server did not serve is not written as unchanged text, and
the next run asks only for it: `test_a_window_nobody_answered_is_not_served`,
`test_the_last_attempt_decides`,
`test_a_reply_without_a_choice_was_served_and_is_an_empty_reply`,
`test_a_refused_window_is_the_requests_fault`,
`test_a_setting_nobody_can_read_is_not_an_outage`,
`test_a_cut_nobody_answered_is_asked_again_and_then_not_served`,
`test_a_cut_that_is_cut_off_is_asked_in_halves_not_again`,
`test_a_refused_cut_is_not_asked_twice_and_is_a_hole`,
`test_a_document_whose_cut_was_not_served_is_not_refined`,
`test_an_outage_writes_nothing_as_refined`,
`test_the_next_run_asks_only_for_what_was_not_served`,
`test_a_forced_pass_that_is_not_served_keeps_the_old_output`,
`test_an_unfinished_pass_over_another_input_is_not_resumed`,
`test_an_unfinished_pass_asked_with_another_prompt_is_not_resumed`,
`test_an_unfinished_pass_asked_of_another_model_is_not_resumed`,
`test_an_unfinished_pass_with_another_window_size_is_not_resumed`,
`test_a_setting_nobody_can_read_ends_the_run_before_the_first_document`,
`test_a_batch_counts_an_unserved_document_as_failed` and
`test_the_merge_names_the_documents_it_leaves_out`
(`tests/test_refinement_unserved.py`).

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
`test_the_split_calls_go_out_together` (`tests/test_split.py`). A cut-off
outline is asked in halves with the numbers its segments have, a half that is a
hole makes the whole cut one, and a hole is cut mechanically and named:
`test_a_cut_off_outline_is_asked_in_halves_with_the_numbers_it_has`,
`test_the_merged_cuts_are_the_two_halves_and_the_cut_between_them`,
`test_a_half_that_is_a_hole_makes_the_whole_cut_a_hole`,
`test_an_outline_of_one_segment_gets_more_room_once_and_then_is_a_hole`,
`test_a_hole_is_cut_mechanically_and_named_with_its_cause`,
`test_an_answer_of_no_cuts_is_an_answer_and_no_hole` (`tests/test_split.py`).
Its cut
never exceeds `SECTION_MAX_WORDS`; the context budget reacts to the
knobs it names and covers the largest possible reply; and the preflight
stops a run before the first document, not after a mid-run rejection:
`test_split_holds_its_own_limit`,
`test_one_huge_segment_is_subdivided_not_surrendered`,
`test_budget_reacts_to_the_knobs_it_names`,
`test_the_budget_covers_the_largest_reply_it_would_ask_for`,
`test_the_budget_is_the_prompt_the_largest_input_and_one_largest_reply`,
`test_preflight_rejects_a_server_with_too_little_context`,
`test_preflight_rejects_a_server_serving_another_model`
(`tests/test_context_budget.py`). The shapes the preflight is given are those the
requests send, and a server that refuses one ends the run before the first
document: `test_the_refinement_command_hands_the_preflight_its_own_shapes`,
`test_the_refinement_entry_point_hands_it_over_too`,
`test_a_server_that_refuses_the_cut_schema_ends_refinement_before_any_document`,
`test_a_server_that_takes_every_schema_lets_refinement_go_on`
(`tests/test_stage_preflight.py`).

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
splitting are positional. Every request sends its reply schema as the
grammar, and a reply is read as exactly one JSON object (see
docpipe/reading.py): nothing is stripped, cut out or closed. A reply
that is not that object is asked again with its cause named, up to
MAX_RETRIES times, except on a 4xx response, which is not retried
because the server has refused the request itself. A reply that was
cut off at its token limit is never asked again as it stands: the
window is asked in halves by sections, and a lone section gets more
room once (twice what it asked, or as much as the window the server
reported leaves, whichever is smaller; a window that leaves none makes
it a hole at once). What is still unread is a hole with its cause: the
window keeps its original, unrefined text and is recorded in the
refinement report written next to the output, and the next plain run
asks exactly those windows again.

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
When no cut is asked for, or the model's cuts could not be read (a
hole, with its cause), a mechanical fallback cuts at even word-count
intervals instead, dropping a cut that would leave a sliver under
about 100 words; the section is named in the refinement report with
the cause. A request whose reply was cut off is asked again for half
of the outline, since the outline has one line per segment.

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

<details>
<summary><code>docpipe/refinement/replies.py</code></summary>

replies.py: The reply each refinement request asks for, as a JSON schema.

The grammar of every request of this stage, on every provider (see
`docpipe.providers.grammar`). The prompts state the same shapes in words;
nothing here is a check beyond the one key the reader needs (`sections`,
`cuts`).

The corrections reply is small and fixed. The full reply hands every section
back, with the keys the request carried, so its schema is built from the
window that is sent: what a section or one of its tables carried under a key
decides what may come back under it.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
