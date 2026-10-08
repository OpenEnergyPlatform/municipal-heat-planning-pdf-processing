## Purpose

Preprocessing turns one PDF into two cached JSON artifacts. `results/pages.json`
(Stages 1 and 2) stays internal to this stage, a per-page inventory of
content blocks read only by Stage 3, `--rebuild-stage3`, and
`--report-columns`; no module outside `docpipe/preprocessing/` imports
`PAGES_JSON` (`docpipe/artifacts.py:24`). `results/sections.json` (Stage 3),
the flat list of assembled sections, is what every later stage eventually
reads. Stage 1 reads the PDF's own text layer with PyMuPDF. Stage 2 runs
PP-DocLayoutV3, an object-detection model, over rendered pages to find
tables, figures, titles and captions. Stage 3 walks the annotated pages in
reading order and assembles them into sections carrying prose content, table
and figure references, and placeholders marking where each one sits.
Refinement reads `sections.json` directly. Image processing prefers
`sections_refined.json` but falls back to `sections.json` itself whenever
refinement has not produced it yet. Chunking's merge step requires
`sections_refined.json` and looks at `sections.json` only to warn about a
document that has one and no refined output, so the content reaches the
database through the merged `document.json`; only the standalone
`enrich-bbox` step reads `sections.json` itself, for its geometry
(`docpipe/refinement/pipeline.py:95`; `docpipe/visuals/pipeline.py:62-71`,
193-196; `docpipe/chunking/merge.py:24-25`, `165-177`;
`docpipe/chunking/database.py:597`).

Everything here is deterministic, PyMuPDF text extraction, the
PP-DocLayoutV3 forward pass, and rule-based section assembly, with one
exception: transcribing a page that carries no PDF text layer through a
vision model. That path runs only when a caller asks for it with
`--transcribe-missing-text`; a run that skips the flag makes no model call
(`docpipe/preprocessing/pipeline.py:87-90`, pinned by
`tests/test_page_text_fallback.py: test_the_fallback_is_off_unless_asked_for`).
Both artifacts are cached under the document's own output directory and
reused automatically; `--force-reextract` and `--rebuild-stage3` bypass or
narrow that resumption.

## Position in the pipeline

| | |
|---|---|
| **In** | A PDF file, or a directory of PDF files (`run()`, `docpipe/preprocessing/pipeline.py:483-536`). An active profile supplies the caption, hyphenation and directory word lists plus `Profile.column_layout` (see Configuration). An optional page range (`--pages START END`) narrows a single-PDF run; the optional text fallback needs a reachable vision model server, which is asked before the first page that lacks its text and not before. |
| **Out** | `results/pages.json` (Stage 1+2 cache), `results/sections.json` (Stage 3 output), `results/page_transcription_report.json` (only, but then always, with `--transcribe-missing-text`; it names the pages that failed and why), one PNG crop per table or image under `images/`, and, in folder mode, `_index.json`. |
| **Resumes on** | `results/pages.json` and `results/sections.json`. A run whose Stage 1/2 leaves any page failed does not write the pages cache, and, within that same run, deletes a pre-existing `sections.json` before the Stage 3 cache-hit check runs, and so does a run that transcribed a page with `--transcribe-missing-text` (`pipeline.py:165-181`). An unreadable cache file is treated as absent. `--rebuild-stage3` resumes only from `pages.json`, skipping the PDF and the layout model. |
| **Needs** | A GPU for PP-DocLayoutV3 when available, else CPU. `load_model()` fetches the weights via `from_pretrained()`, needing network unless they are already cached (`stage2_layout.py:98,107-108`). Stage 1 and Stage 3 need neither model nor network. With `--transcribe-missing-text`, a vision server that serves `VLM_MODEL`, has room for a page request and takes the page reply schema, asked before the first page that lacks its text (see Optional: filling in missing page text). |

File processing precedes this stage
([Getting the documents in](fileprocessing.md)); refinement follows,
reading `sections.json` and writing `sections_refined.json`
([Repairing the text](refinement.md)).

## Method

### Resolving the profile and choosing a mode

`resolve_profile(args)` (`docpipe/profile.py:452-475`) loads the `Profile`
named by `--profile` or `$DOCPIPE_PROFILE`; `__main__.py` copies the flag
into the environment before the stage is imported, and a profile named
after the stage was imported under another one raises `SystemExit` instead
of running on a mix of both. `run()` (`docpipe/preprocessing/pipeline.py:483-536`)
dispatches to `run_single()` for a `.pdf` file, `run_folder()` for a
directory, or, with `rebuild_stage3` set, `rebuild_stage3_from_cache()`,
which ignores the input path and, like `--report-columns`, finds the document
directories under the output root at any depth (`artifacts.document_dirs`, by
`pages.json`). `run_folder` refuses two PDFs that would be documents of one
name before the layout model has run over either, with both places named
(`DuplicateDocumentName`).

### Stage 1: extracting text blocks

`run_single()` calls `_load_pages_cache(output_dir)` unless
`force_reextract` is set; a missing or unreadable `pages.json` returns
`None` and falls through to re-extraction
(`docpipe/preprocessing/pipeline.py:52-63,108-109`). Extraction itself,
`extract_all_pages()`, opens the PDF with `fitz` and, per page, calls
`_extract_page_text()`, which reads `page.get_text("rawdict")`, joins each
block's spans into text through `_spans_to_text()` (rejoining a
line-ending hyphen unless the following word is a profile exception or
starts uppercase), and measures the block's dominant font with
`_dominant_font()`. `_is_valid_text_block()` drops a block under
`TEXT_BLOCK_MIN_CHARS` characters or with no alphanumeric content, and a
page whose extraction raises is skipped and counted in `n_failed`
(`docpipe/preprocessing/stage1_extract.py:144-252`).

### Stage 2: detecting layout

`detect_layout_all_pages()` renders the open `fitz` pages at
`LAYOUT_DETECT_DPI` (150) in `LAYOUT_BATCH_SIZE` batches, prefetched one
batch ahead on a worker thread, and runs `_infer_batch()`: a PP-DocLayoutV3
forward pass, a global confidence floor, per-class thresholds, per-class
non-maximum suppression, and a cross-class pass suppressing a
lower-confidence overlapping table/image detection of a different class.
`_process_page()` turns each surviving detection into a suppression, a title or caption
`Block`, or a saved crop, whiting out any figure region overlapping a table
crop; a crop is re-rendered at the higher `PAGE_RENDER_DPI` only when that
differs from the detection resolution. Once every batch has run,
`promote_headings_by_font()` upgrades heading-styled text to
`paragraph_title`, and `resolve_captions()` attaches the nearest caption
to each table or image (`docpipe/preprocessing/stage2_layout.py:1028-1073`).

A text block of the PDF's text layer that lies 90 percent or more inside a box
of a suppressed class (header, footer, page number, footnote and their image
forms) is taken off the page, as before. Of those, the footnote class is
counted: once per document, after the refusal check, stage 2 logs `Stage 2: the
footnote class removed N text block(s) with M character(s)`, zero included, so
that "none found" is told from "not counted". `_lies_in` is the one test both
the removal and the count ask, so the count cannot drift from what is removed.
The line is logged only for a document stage 2 ran on: none for one loaded
from `pages.json`, one with no pages, or one the stage refuses. A table's own
note, class `vision_footnote`, is a caption class and not part of it. Footnote
text therefore stays out of `pages.json`, `sections.json`, the database, the
vectors and every harvest passage, as it did, and the count is the only new
thing.
### Caching Stage 1+2

If no page failed, `_save_pages_cache()` writes the cleaned `PageData` list
to `results/pages.json` atomically, via a temporary file and
`os.replace()`; an incomplete extraction is never cached
(`docpipe/preprocessing/pipeline.py:128-136`).

### Optional: filling in missing page text

When `transcribe_missing_text` is set, `_fill_missing_page_text()` builds
a page renderer and a profile-bound transcriber and calls
`fill_missing_page_text()` (`docpipe/preprocessing/page_text_fallback.py:163`),
which selects pages where `needs_transcription()` finds under
`MIN_PAGE_CHARS` (60) characters of Stage 1 text and, for each, replaces its
text blocks with the list `synthesize_blocks()` returns
(`page_text_fallback.py:112-160` builds the blocks; line 268 is the
replacement). `results/page_transcription_report.json` is written
unconditionally, and the pages cache is rewritten if any page changed. This
runs after Stage 2, since the media blocks are already known, and before
Stage 3 (`docpipe/preprocessing/pipeline.py:144-148,383-432`).

A page is one request: the page image and the prompt
`preprocessing/page_transcribe`, with the reply schema `page_reply`
(`visuals.replies.PAGE`) as the `response_format`. `vision.call_vision` reads
the reply as exactly one JSON object whose `markdown` is text, as it does for a
table (see [Reading the pictures](visuals.md)): nothing is stripped, cut out,
closed or salvaged, a reply that is not that object is asked again with its
cause named, a reply cut off at its limit is asked once more with more room, and
the key `text` is no alias for `markdown` any more. The empty
string is an answer: a page that is one large map holds no prose, and counts in
`pages_empty`. A page for which `call_vision` returns a hole (an object that
stayed unreadable, one cut off twice, a request the server refused or did not
answer, a failure of the stage's own, a page that could not be rendered)
counts in `pages_failed`, keeps its empty text layer, and is listed in the
report with the cause. Run again with the flag, the pages that still have no
text are asked again.

A page cannot be split, so a cut-off reply is asked once more, once, with the
room the served window allows: the smaller of twice the prompt's `max_tokens`
(4,096 by default) and `max_tokens` plus what the window holds beyond the budget
of the page request, `min(2 x max_tokens, max_tokens + window - budget)`, in
tokens (`llm_preflight.further_room`, reached through `call_vision`'s `budget`
argument, which `make_transcriber` sets to `page_request_tokens`). The window is
the one the server reported at the check below, kept for the run
(`llm_preflight.served_window`, role `vlm`). Where it is not known (the server
reports none) the limit is twice `max_tokens`. Where the window leaves no more
room than the request had, the page is a hole `cut_off` at once, no second
request is sent, and the log names the served window in tokens.

The vision server is not asked before the first document. `main` first checks
that the profile has its reading sentences (`reading.phrases()`, only with
`--transcribe-missing-text` and not with `--rebuild-stage3`), then hands the run
a check (`_assert_page_server`, wrapped by `_once` and passed down as
`page_server` through `run`, `run_folder`, `run_single` and
`_fill_missing_page_text` into `fill_missing_page_text(before_first=...)`).
`fill_missing_page_text` calls it once, when there is a page to send and before
any is sent, and the check runs once per run. It asks `assert_serving` that the
server serves `VLM_MODEL`, that its window holds a page request
(`page_request_tokens(profile)`: the page prompt's words times
`TOKENS_PER_WORD`, `IMAGE_TOKENS`, and one reply, the prompt's `max_tokens`
(4,096 by default), no second reply being counted: 9,260 tokens with the `kwp`
profile and 9,449 with `scenarios`; there is no print flag for it) and that it
takes the page reply schema. A run in which every page has its text asks no server and ends
0 whether or not one is up. A server that is not there, does not serve the
model, has too small a window or refuses the schema ends the run with exit 1 when
the first page needs it, with the folder loop letting the error through instead
of counting one failed document: every later document would meet it too.
Before this check the stage asked no server, so a server that could not take
the schema failed page by page and the run ended 0 with every page failed.

A page that failed does not change the exit code. The run says so once, in
pages and documents, where it ends: `Page transcription: 5 page(s) in 2
document(s) could not be read; page(s) by cause: cut_off 3, syntax 2; the next
run with --transcribe-missing-text asks for them again`.

### Loading, invalidating, or rebuilding the Stage 3 cache

If Stage 1/2 failed, an existing `sections.json` is deleted first, since it
was built from an incomplete extraction. It is deleted too by a run that
transcribed a page: a page that failed in an earlier run and is read now is in
`pages.json`, and a `sections.json` built before that has none of its text and
would be reused for good. Otherwise it is reused unless `force_reextract`, and on
a cache miss `build_sections()` runs and `save_output()` writes the result
(`docpipe/preprocessing/pipeline.py:165-194`). The later stages are not
touched: stage 4 serves a `sections_refined.json` it already wrote from its
cache, so a document whose `sections.json` was rebuilt this way is refined again
only by running stage 4 with `--force`.

### Stage 3: assembling sections

`build_sections()` first calls `sort_pages()`, which, per page, calls
`find_gutters()` and `order_blocks()` from `columns.py`, then
`strip_running_headers()`, then walks every block: a
`SECTION_TITLE_CLASSES` block opens a new `Section`, a table or image
block becomes a `TableRef` or `FigureRef` plus a `[block_id]` placeholder
whose caption is settled by `docpipe.captions.resolve_title()`, and text
accumulates into `Section.content` and `Section.segments`.
`drop_directory_sections()` removes table-of-contents-like sections
(`docpipe/preprocessing/stage3_structure.py:291-487`).

### Folder-mode iteration

`run_folder()` iterates the PDFs under a directory, sorted by relative path.
It loads the layout model once, up front, only if at least one PDF still
needs (re-)extraction; when every PDF already has a cached `pages.json`,
folder mode skips the load entirely and logs that it did so
(`docpipe/preprocessing/pipeline.py:245-254`). Once loaded, the model is
reused across every document (not thread-safe, so processing stays
sequential); `run_folder()` calls `run_single()` per document inside a
`try`/`except` turning any exception into `status="error"`, and rewrites
`_index.json` after every document so partial progress survives an
interruption (`docpipe/preprocessing/pipeline.py:209-300`).

## Data model

`docpipe/preprocessing/models.py:17-68` defines `Block`, the unit both Stage
1 and Stage 2 write:

| Field | Meaning |
|---|---|
| `id`, `type` | block id, and `text`/`table`/`image` |
| `bbox` | `[x0, y0, x1, y1]` in PDF points, origin top-left |
| `content`, `path` | text content, or a saved crop path |
| `caption` | the resolved caption |
| `confidence` | detection score, rounded to 3 decimals |
| `layout_label` | the raw PP-DocLayout class; `None` on a Stage-1-only text block |
| `source_text` | native PDF text under a table's bbox, a QA reference |
| `bbox_approx` | `True` only on a fallback block: the rectangle was stacked, not measured |

`font_size` and `font_bold` also live on the in-memory `Block` but are
never serialised. A `PageData` (`models.py:75-100`) holds `page_number`,
`width_pt`, `height_pt`, and a list of `Block`.

Stage 3 turns pages into `Section` objects
(`docpipe/preprocessing/models.py:152-177`): `title`, `content` (joined
prose with `[block_id]` placeholders), `page_number`, `tables`
(`list[TableRef]`), `figures` (`list[FigureRef]`), `segments` (reading-order
content units), and `pages` (sorted distinct page numbers, derived from
`segments`). A `TableRef`/`FigureRef` carries `id`, `path`, `caption`,
`page_number`, and `bbox` (one rect, matching a segment's own `bbox`);
`TableRef` additionally carries `source_text`. One segment is
`{"page": int, "kind": "text"|"table"|"figure", "text": str, "ref":
block_id}`; `stage3_structure.py` also attaches an optional `"bbox"` key, a
list of rectangles, to every segment kind where the geometry is known
(`docpipe/preprocessing/stage3_structure.py:334,423,446`), which the comment on
`Section.segments` in `models.py:159-163` names too.

| File | Written by | Holds |
|---|---|---|
| `results/pages.json` | Stage 1+2 | a list of `PageData.to_dict()` |
| `results/sections.json` | Stage 3 | `{"version": 1, "sections": [Section.to_dict(), ...]}`; the shape is `docpipe/schemas/sections.schema.json` and a file without `version` is version 1; no stage checks a file against it (see [the files each stage leaves behind](../artifacts.md)) |
| `results/page_transcription_report.json` | text fallback | `{pages_total, pages_missing_text, pages_transcribed, pages_empty, pages_failed, failed_pages, blocks_added}`; `failed_pages` is a list of `{page, why}`, one per failed page, `why` being the cause of its hole, and as long as `pages_failed`; a pass that wrote it with no failure has an empty list |
| `images/<block_id>.png` | Stage 2 | one PNG crop per table or image block |
| `_index.json` | folder mode | `{relative_pdf_path: {status, output_dir, sections}}` |

(`docpipe/artifacts.py:21-33`; `docpipe/preprocessing/page_text_fallback.py:163-287`.)

## Configuration

| Name | Kind | Default | Effect |
|---|---|---|---|
| `input`, `output` (positional) | CLI | none; `output` falls back to the profile's processed directory | PDF file or folder (omitted only with `--rebuild-stage3`), and the output directory |
| `--force-reextract` / `--rebuild-stage3` | CLI flags | off | ignore both caches and rerun Stages 1 to 3, or rerun only Stage 3 from cached `pages.json` |
| `--report-columns` | CLI flag | off | read-only report of multi-column pages, changes nothing |
| `--transcribe-missing-text` | CLI flag | off | turns on the vision-model fallback; needs a running vision server, which is asked before the first page that lacks its text, and the profile's `reading.PHRASES` (checked first); ignored by `--rebuild-stage3` |
| `--pages START END` | CLI flag, 2 ints | whole document | 0-indexed, end-exclusive page range; single-PDF only |
| `--glob` | CLI flag | `*.pdf` | pattern `run_folder()` matches PDFs against in folder mode (`pipeline.py:580`) |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | names the active profile |
| `--log-level` | CLI flag | `INFO` | logging verbosity: `DEBUG`/`INFO`/`WARNING`/`ERROR` (`pipeline.py:583-584`) |
| `DOCPIPE_LAYOUT_AUTOCAST` | env var | `off` | `bf16`, `fp16`, or `off`: reduced-precision Stage 2 pass on CUDA |
| `DOCPIPE_LAYOUT_PREFETCH` | env var | `1` | Stage 2 batches rendered ahead of the running forward pass, as `LAYOUT_PREFETCH_BATCHES` (`config.py:58`) |
| `PAGE_TRANSCRIBE_WORKERS` / `PAGE_RENDER_WORKERS` | env vars | `64` / `4` | concurrent transcription calls and page renders in the fallback, bounded separately |

`Profile.column_layout` (`docpipe/profile.py:172`) is optional: it defaults
to `"auto"`, `run()` falls back to `"auto"` even with no active profile
(`pipeline.py:642`), and there is no dedicated `--column-layout` CLI flag.
`Profile.__post_init__` raises
`ValueError` only if it is set to something outside `auto`/`single`/`double`
(`profile.py:188-194`). `auto` looks for a gutter and accepts one column as
the answer, `double` falls back to a centre split if none is found, and
`single` never looks.

A profile must additionally supply the following, or a
`LookupError`/`SystemExit` follows:

| Name | Default | Effect |
|---|---|---|
| `preprocessing.HYPHEN_EXCEPTIONS` | none | words that keep a line-ending hyphen from gluing to the next line |
| `preprocessing.CAPTION_MAX_WORDS` | none; kwp = 45, scenarios = 160 | word-count ceiling for a caption |
| `preprocessing.CAPTION_START` | none; each profile lists its own | a non-empty list of regular expressions, each with its own anchor, that open a caption; `docpipe/captions.py` joins them and compiles once per profile. kwp and scenarios list one pattern (a word, a number, a colon); the built-in profile adds letter-numbered forms (`Table A.1:`) and the colon-less ones (`Figure 3.`, `Fig. 2`, `Table 1`), the latter only where a text, a line or a sentence begins, so `see Table 1.` and `Table 1 shows` stay prose. An empty list, a bare string or a pattern that does not compile or matches the empty text is a `ValueError`, a missing list a `LookupError` |
| `preprocessing.TITLE_EXCLUDE_PREFIXES` | none | prefixes that keep a block from being read as a heading |
| `preprocessing.DIRECTORY_FIGTAB_WORDS` | none | words opening a figure/table list entry, for directory-section detection |
| `preprocessing.DIRECTORY_TITLE_WORDS` | none; "inhalt", "verzeichnis", "contents", "directory" in kwp, scenarios and the built-in profile | the words by which a section title says it is a directory (a table of contents, a list of figures): fragments of a pattern, joined with `\|` and matched case-insensitively anywhere in the title, so a section so titled is dropped at the lower directory score. An empty list gives a pattern that never matches. The core fixes none, and a profile outside this repository that extends nothing and has none stops with a `LookupError` at the first directory candidate |
| `preprocessing.BIBLIOGRAPHY_TITLE_WORDS` | none | title words routing a section to the literature path instead of directory-stripping |

The colon-less forms of the built-in profile cannot tell every prose line from
a caption: `Table 1 Germany leads ...` at the start of a sentence counts as a
caption, an indented line after a line break does not.

A selection of the module constants that tune detection and assembly:

| Name | Default | Effect |
|---|---|---|
| `LAYOUT_DETECT_DPI` / `PAGE_RENDER_DPI` | 150 / 300 | render resolution for the detection pass and for saved table/figure crops; a page is re-rendered only when the two differ (`stage2_layout.py:989-1051`) |
| `LAYOUT_BATCH_SIZE` | 12 | pages per Stage 2 forward pass |
| `PP_GLOBAL_MIN_CONF` / `PP_CLASS_THRESHOLDS` | 0.4 / per class, 0.40 to 0.85 | confidence floors before and after per-class filtering |
| `NMS_OVERLAP_THRESHOLD` | 0.5 | IoU above which two overlapping same-class (or cross-class table/image) boxes collapse to the higher-confidence one |
| `STRIP_PRIVATE_USE` / `MASK_FIGURES_IN_TABLE_CROPS` | `True` / `True` | drops Unicode Private Use Area glyphs, and whites out figure pixels inside a table crop |
| `FONT_HEADING_ENABLE`, `HEADER_FOOTER_STRIP_ENABLE`, `DIRECTORY_STRIP_ENABLE` and their thresholds | all `True` | gate font-based heading promotion, running-header/footer stripping, and directory-section removal |
| `COLUMN_*` thresholds | gutter 8.0 pt, align tolerance 4.0 pt, aligned fraction 0.75 | tune gutter finding and column-validity checks |

(`docpipe/preprocessing/config.py`.)

## Failure modes

| Condition | Behaviour |
|---|---|
| A Stage 1 page raises during extraction, or `n_failed > 0` after Stage 1/2 | the page is skipped and counted; `pages.json` is not written, so the next run retries extraction from scratch (`stage1_extract.py:224-234`; `pipeline.py:128-136`) |
| A Stage 2 batch's forward pass raises | recorded in `failed_batches`, its pages get no layout; once every batch has run, `detect_layout_all_pages` raises `LayoutDetectionFailed` naming the batch numbers and affected page count (`stage2_layout.py:1036-1043,1093-1100`) |
| `LayoutDetectionFailed` reaches `run_folder`'s per-document handler | the document is marked `status="error"` in `_index.json` and the run continues; called directly, the exception propagates unhandled (`pipeline.py:267-292,632-656`) |
| A page fails to render for Stage 2, its post-detection processing raises, or a crop fails to encode or write | logged and skipped; the page keeps its Stage-1-only data, and a written `Block` can still reference a failed crop (`stage2_layout.py:509-570,1023,1064`) |
| `pages.json` or `sections.json` is unreadable, or a Stage 3 cache was built while `n_failed` was set, or the input path is neither a `.pdf` file nor a directory | treated as absent and rebuilt, deleted before the cache-hit check runs, or `run()` raises `ValueError` and `main()` exits with status 1 (`pipeline.py:60-62,170-189,536,654-656`) |
| No profile is active but a profile-gated function is called, or a profile is named after the stage was imported under another one | a `LookupError` propagates uncaught, or `resolve_profile` raises `SystemExit` (`stage1_extract.py:41-43`; `profile.py:261-271,392-406,452-475`) |
| A page's transcription ends in a hole (a reply that stayed unreadable, one cut off twice, a request refused or not answered, a page that could not be rendered, an error of the stage's own), returns an empty markdown string, or more candidates need transcription than `max_pages` | a hole is counted in `pages_failed` and listed in `failed_pages` with its cause, an empty string in `pages_empty`, and the exit code does not change; a run with candidates over `max_pages` is truncated with `pages_missing_text` still reporting the true total (`page_text_fallback.py:205-213`); unreachable through the CLI or `run()`, since `_fill_missing_page_text()` never passes `max_pages` (`pipeline.py:406-412`) |
| The vision server a page needs is not there, does not serve the model, has too small a window or refuses the page reply schema | the check `_assert_page_server` raises `PreflightError` before the first page that lacks its text; `run_folder` lets it through and `main` exits with status 1 (`pipeline.py:280-283,461-480,654-656`); a run in which no page lacks its text never asks |
| The profile lacks a sentence of `reading.PHRASES`, with `--transcribe-missing-text` | `LookupError` from `reading.phrases()` before the first document, with a traceback and a non-zero exit (`pipeline.py:631-634`) |
| `find_gutters()` cannot support a confident column split | returns `[]`; the page reads as a single column, or, under `column_layout="double"`, falls back to a hard centre split (`columns.py:158-267`) |

## Measured behaviour

- 30 pages in one Stage 2 batch asked for about 8 GiB and destabilized a
  third worker on a shared H100; `LAYOUT_BATCH_SIZE = 12` keeps that under
  about 3.5 GiB, since the forward pass is 6 percent of the stage
  (`docpipe/preprocessing/config.py:40-45`). The pass measures 4.7 of about
  80 ms per page; autocast is 1.15 times faster, a 0.7 percent stage-wide
  gain for a precision change on box coordinates, so `LAYOUT_AUTOCAST`
  defaults to off (`config.py:47-53`;
  `tests/test_stage2_perf.py: test_autocast_is_off_by_default`). Its 8
  mantissa bits make one representable step span several pixels on a
  roughly 1700-pixel page, enough to shift a crop's edge into neighbouring
  text, so Stage 2 casts `logits`/`pred_boxes` back to fp32 after autocast
  while leaving `out_masks`, its largest tensor, in the reduced dtype
  (`stage2_layout.py:311-330`;
  `tests/test_stage2_perf.py: test_boxes_come_back_as_float32`).
- Real text columns measure an aligned-left-edge fraction of at least 0.90,
  labels scattered around a chart at most 0.43, the gap
  `COLUMN_ALIGN_TOL_PT`/`COLUMN_MIN_ALIGNED_FRAC` are set to separate
  (`docpipe/preprocessing/config.py:139-143`). A bulleted list on one
  two-column page produced 0.71 against the 0.75 single-edge threshold;
  allowing alignment on one or two edges instead of one keeps it from
  reading across the gutter (`docpipe/preprocessing/columns.py:132-150`).
- 423 sections across 99 documents in a corpus snapshot carry Unicode
  Private Use Area glyphs from a symbol font; `STRIP_PRIVATE_USE` drops
  them (`docpipe/preprocessing/config.py:195-202`).
- Captions run to a median of 8 words on the kwp corpus, 24 at the 99th
  percentile, so `CAPTION_MAX_WORDS` is 45 there
  (`profiles/kwp/preprocessing.py:35-39`); scenarios panel descriptions and
  legends routinely run 60 to 150 words, so `CAPTION_MAX_WORDS` is 160
  there (`profiles/scenarios/preprocessing.py:39-43`).
- Eleven plans in the heat-plan corpus carry no PDF text layer, together
  holding 1,270 tables and figures Stage 2 transcribed with no surrounding
  text (`docpipe/preprocessing/page_text_fallback.py:1-11`). Treating the
  fallback's legitimate empty-page answer as a failure once reported 106
  broken calls for a run where none actually broke; `pages_empty` and
  `pages_failed` are counted apart to avoid that
  (`docpipe/preprocessing/page_text_fallback.py:191-194`). Caption
  resolution's own measured behaviour is documented on
  [The parts every stage uses](core.md).

## Verification

- `tests/test_columns.py`: `test_two_columns_are_found_at_their_gutter` and
  `test_too_few_blocks_is_not_enough_evidence` pin gutter detection and its
  refusal on weak evidence. `test_single_never_looks_for_columns`,
  `test_auto_detects_per_page`, and
  `test_double_falls_back_to_the_page_centre_when_nothing_is_detected` pin
  the three `column_layout` modes, and `test_a_bulleted_column_is_still_a_column`
  and `test_labels_scattered_around_a_chart_are_not_a_column` pin the
  alignment test.
- `tests/test_stage1_extract.py`: `test_dehyphenates_german_compound_across_line_break`
  pins the hyphenation rule, `test_each_profile_gets_its_own_list` pins
  that `HYPHEN_EXCEPTIONS` does not leak between profiles, and
  `test_is_valid_text_block` pins the minimum-length rule.
- `tests/test_stage2_layout.py`: `test_apply_nms_per_class_keeps_highest`
  and `test_cross_class_suppresses_lower_confidence_overlap` pin
  non-maximum suppression within and across classes.
- `tests/test_stage2_perf.py`: `test_it_really_runs_ahead` pins that the
  prefetch thread runs ahead, `test_boxes_come_back_as_float32` pins the
  selective upcast after autocast, and
  `test_a_failed_batch_refuses_the_whole_document` pins what triggers
  `LayoutDetectionFailed`.
- `tests/test_stage3_structure.py`: `test_empty_leading_dokument_section_is_dropped`
  pins the synthetic "Dokument" section, and
  `test_the_sentence_that_names_the_table_beats_the_linked_footnote` pins
  `resolve_title`'s precedence.
- `tests/test_stage3_segments.py` pins the segments/pages a `Section`
  carries: `test_section_spanning_pages_gets_segments_and_pages`,
  `test_consecutive_same_page_text_merges_into_one_segment`,
  `test_text_run_splits_into_per_page_segments`, and
  `test_dokument_page_number_derived_from_first_content_page`, pinning its
  `page_number` derivation.
- `tests/test_preprocessing_models.py` pins `Block`/`PageData`/`Section`
  round-trip and confidence rounding:
  `test_block_roundtrip_rounds_confidence_and_omits_none`,
  `test_pagedata_roundtrip`, `test_block_source_text_roundtrip_and_omit`,
  `test_tableref_source_text_roundtrip_and_omit`, and
  `test_section_to_dict_includes_and_omits_refs`.
- `tests/test_page_text_fallback.py`: `test_a_stamped_page_number_is_not_a_text_layer`
  pins `needs_transcription`'s threshold, `test_headings_carry_the_label_stage_three_opens_sections_on`
  pins that a synthesized heading opens a real section,
  `test_every_synthesized_box_says_it_was_not_measured` pins
  `bbox_approx = True` on every synthesized block, and
  `test_the_fallback_is_off_unless_asked_for` pins that a normal run makes
  no model call. A page's reply is the one object with its `markdown`, and the
  empty string is an answer (`test_the_object_with_its_markdown_is_the_pages_text`,
  `test_an_empty_markdown_is_an_answer_and_not_a_failure`); a reply that is not
  that object leaves the page without text and says why, a reply cut off twice is
  a hole after one request with more room, and a transcriber that answers
  neither text nor a hole is an error hole
  (`test_a_reply_that_is_not_the_object_leaves_the_page_without_text_and_says_why`,
  `test_a_reply_cut_off_twice_is_a_hole_after_one_request_with_more_room`,
  `test_the_failed_pages_are_the_pages_that_were_counted_failed`,
  `test_a_transcriber_that_answers_neither_text_nor_a_hole_is_an_error_hole`,
  `test_a_page_that_cannot_be_rendered_is_an_error_hole`). A run that
  transcribed pages does not reuse the Stage 3 file built before, and one that
  transcribed nothing keeps it
  (`test_a_run_that_transcribed_pages_does_not_reuse_the_stage_three_built_before`,
  `test_a_run_that_transcribed_nothing_keeps_the_stage_three_cache`). The
  server is asked by the first page that needs it and once, a run whose pages
  all have their text asks none and ends 0, a server that is not there ends the
  run when a page needs it and a folder is not left running past it, and the
  sentences are checked first
  (`test_the_server_is_asked_by_the_first_page_that_needs_it_and_once`,
  `test_a_server_that_is_not_there_ends_the_run_when_a_page_needs_it`,
  `test_a_server_that_is_not_there_is_no_matter_to_a_run_without_such_pages`,
  `test_a_missing_server_ends_the_folder_and_is_not_one_failed_document`,
  `test_the_sentences_are_checked_first_and_a_run_without_such_pages_asks_no_server`,
  `test_the_page_check_asks_the_vision_server_for_the_page_schema_and_room`,
  `test_a_rebuild_of_stage_three_asks_the_model_nothing_even_with_the_flag`).
  Failed pages reach the report and the one line at the end of the run, and the
  budget of a page request counts one reply
  (`test_a_document_with_failed_pages_adds_one_entry_in_pages_and_causes`,
  `test_pages_without_text_leave_the_exit_code_at_zero_and_are_said_once`,
  `test_the_budget_of_the_page_request_counts_one_reply`). `tests/test_room.py`
  pins that the page budget is the prompt, the image and one reply and is not
  the visuals stage's, that a server that serves exactly the budget is taken and
  one token under it refused, and that the window the check found reaches the
  pages
  (`test_the_budget_of_a_page_request_is_the_prompt_the_image_and_one_reply`,
  `test_the_page_budget_is_not_the_budget_of_the_visuals_stage`,
  `test_the_page_transcription_takes_a_server_that_serves_exactly_its_budget`,
  `test_the_page_transcription_refuses_a_server_one_token_under_its_budget`,
  `test_the_page_check_hands_the_window_it_found_to_the_pages`).
- `tests/test_preprocessing_config.py`: `test_dump_json_atomic_keeps_old_file_on_error`
  pins that a failed atomic write leaves the original file untouched.
- `tests/test_preprocessing_pipeline.py`: `test_write_index_keys_by_relative_path_no_collision`
  pins that `_index.json` is keyed by relative path, and
  `test_a_lone_path_with_rebuild_stage3_is_the_processed_root` pins the
  CLI's positional-argument remapping.

## Modules

`docpipe/preprocessing/pipeline.py` orchestrates Stages 1 to 3 for one PDF
or a folder of PDFs, and owns both resumable caches, the optional
text-fallback wiring (the check that asks the vision server before the first page
that needs it, and the line that says at the end which pages could not be read),
folder-mode indexing, and the command line.
Called directly through `python -m docpipe.preprocessing.pipeline`;
otherwise only `run_folder()` (calling `run_single()`) and the test suite
call into it.

`docpipe/preprocessing/stage1_extract.py` performs PyMuPDF `rawdict` text
extraction into `PageData`/`Block` objects, including hyphenation repair
and dominant-font measurement. Called by `pipeline.run_single()`; its page
renderer is reused by `stage2_layout.py` and `page_text_fallback.py`.

`docpipe/preprocessing/stage2_layout.py` runs PP-DocLayoutV3 object
detection, classifies detections into suppression, title, caption, table
and image blocks, writes crops, promotes font-styled headings, and
resolves captions. Called by `pipeline.run_single()`.

`docpipe/preprocessing/stage3_structure.py` deterministically assembles
`PageData` into `Section`/`TableRef`/`FigureRef` objects: reading order,
header/footer stripping, title-driven section boundaries, placeholder and
caption resolution, and directory-section removal. Called by
`pipeline.run_single()` and `pipeline.rebuild_stage3_from_cache()`.

`docpipe/preprocessing/columns.py` finds text-column gutters on a page and
orders blocks column by column instead of by raw top-to-bottom position.
Called by `stage3_structure.build_sections()`, and directly by
`pipeline.report_columns()`.

`docpipe/preprocessing/page_text_fallback.py` provides optional
vision-model transcription for pages with no usable PDF text layer, turning
a markdown reply into synthesized, `bbox_approx` text blocks on the same
`PageData`, and naming the pages it could not read, with the cause. It sizes the
page request (`page_request_tokens`) for the check that asks the server. Called
only from `pipeline._fill_missing_page_text()` when `--transcribe-missing-text`
is set.

Two more modules define the shapes this stage produces without a chapter
of their own: `models.py` (the dataclasses) and `config.py` (most tunable
constants; `page_text_fallback.py` holds its own set outside it:
`MIN_PAGE_CHARS`, `PAGE_WORKERS`, `PAGE_RENDER_WORKERS`, `TEXT_AREA` and
`RENDER_DPI`). Three cross-cutting modules this stage calls into are
documented on [The parts every stage uses](core.md): `docpipe/artifacts.py`,
`docpipe/captions.py` for `resolve_title()`, and `docpipe/profile.py`.
