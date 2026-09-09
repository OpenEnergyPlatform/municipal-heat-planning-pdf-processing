# 2-3. Reading the page

## Purpose

Preprocessing turns one PDF into two cached JSON artifacts. `results/pages.json`
(Stages 1 and 2) stays internal to this stage, a per-page inventory of
content blocks read only by Stage 3, `--rebuild-stage3`, and
`--report-columns`; no module outside `docpipe/preprocessing/` imports
`PAGES_JSON` (`docpipe/artifacts.py:15`). `results/sections.json` (Stage 3),
the flat list of assembled sections, is what every later stage eventually
reads. Stage 1 reads the PDF's own text layer with PyMuPDF. Stage 2 runs
PP-DocLayoutV3, an object-detection model, over rendered pages to find
tables, figures, titles and captions. Stage 3 walks the annotated pages in
reading order and assembles them into sections carrying prose content, table
and figure references, and placeholders marking where each one sits.
Refinement reads `sections.json` directly. Image processing prefers
`sections_refined.json` but falls back to `sections.json` itself whenever
refinement has not produced it yet; only chunking, which imports
`SECTIONS_REFINED_JSON` and `VISUALS_JSON` but never `SECTIONS_JSON`, reaches
`sections.json` exclusively through the merged `document.json`
(`docpipe/refinement/pipeline.py:44-45`; `docpipe/visuals/pipeline.py:56-65`,
152-155; `docpipe/chunking/merge.py:22`).

Everything here is deterministic, PyMuPDF text extraction, the
PP-DocLayoutV3 forward pass, and rule-based section assembly, with one
exception: transcribing a page that carries no PDF text layer through a
vision model. That path runs only when a caller asks for it with
`--transcribe-missing-text`; a run that skips the flag makes no model call
(`docpipe/preprocessing/pipeline.py:82-85`, pinned by
`tests/test_page_text_fallback.py: test_the_fallback_is_off_unless_asked_for`).
Both artifacts are cached under the document's own output directory and
reused automatically; `--force-reextract` and `--rebuild-stage3` bypass or
narrow that resumption.

## Position in the pipeline

| | |
|---|---|
| **In** | A PDF file, or a directory of PDF files (`run()`, `docpipe/preprocessing/pipeline.py:391-438`). An active profile supplies the caption, hyphenation and directory word lists plus `Profile.column_layout` (see Configuration). An optional page range (`--pages START END`) narrows a single-PDF run; the optional text fallback needs a reachable vision model server. |
| **Out** | `results/pages.json` (Stage 1+2 cache), `results/sections.json` (Stage 3 output), `results/page_transcription_report.json` (only, but then always, with `--transcribe-missing-text`), one PNG crop per table or image under `images/`, and, in folder mode, `_index.json`. |
| **Resumes on** | `results/pages.json` and `results/sections.json`. A run whose Stage 1/2 leaves any page failed does not write the pages cache, and, within that same run, deletes a pre-existing `sections.json` before the Stage 3 cache-hit check runs (`pipeline.py:151-159`). An unreadable cache file is treated as absent. `--rebuild-stage3` resumes only from `pages.json`, skipping the PDF and the layout model. |
| **Needs** | A GPU for PP-DocLayoutV3 when available, else CPU. `load_model()` fetches the weights via `from_pretrained()`, needing network unless they are already cached (`stage2_layout.py:95,104-105`). Stage 1 and Stage 3 need neither model nor network. |

File processing precedes this stage
([Getting the documents in](fileprocessing.md)); refinement follows,
reading `sections.json` and writing `sections_refined.json`
([Repairing the text](refinement.md)).

## Method

### Resolving the profile and choosing a mode

`resolve_profile(args)` (`docpipe/profile.py:178-197`) loads the `Profile`
named by `--profile` or `$DOCPIPE_PROFILE`; naming one only after
prompt-binding import time raises `SystemExit` instead of silently running
with the core prompts. `run()` (`docpipe/preprocessing/pipeline.py:391-438`)
dispatches to `run_single()` for a `.pdf` file, `run_folder()` for a
directory, or, with `rebuild_stage3` set, `rebuild_stage3_from_cache()`,
which ignores the input path.

### Stage 1: extracting text blocks

`run_single()` calls `_load_pages_cache(output_dir)` unless
`force_reextract` is set; a missing or unreadable `pages.json` returns
`None` and falls through to re-extraction
(`docpipe/preprocessing/pipeline.py:49-60,97-98`). Extraction itself,
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
to each table or image (`docpipe/preprocessing/stage2_layout.py:997-1041`).

### Caching Stage 1+2

If no page failed, `_save_pages_cache()` writes the cleaned `PageData` list
to `results/pages.json` atomically, via a temporary file and
`os.replace()`; an incomplete extraction is never cached
(`docpipe/preprocessing/pipeline.py:118-126`).

### Optional: filling in missing page text

When `transcribe_missing_text` is set, `_fill_missing_page_text()` builds
a page renderer and a profile-bound transcriber and calls
`fill_missing_page_text()` (`docpipe/preprocessing/page_text_fallback.py:161`),
which selects pages where `needs_transcription()` finds under
`MIN_PAGE_CHARS` (60) characters of Stage 1 text and, for each, replaces its
text blocks with the list `synthesize_blocks()` returns
(`page_text_fallback.py:110-158` builds the blocks; line 250 is the
replacement). `results/page_transcription_report.json` is written
unconditionally, and the pages cache is rewritten if any page changed. This
runs after Stage 2, since the media blocks are already known, and before
Stage 3 (`docpipe/preprocessing/pipeline.py:133-134,353-390`).

### Loading, invalidating, or rebuilding the Stage 3 cache

If Stage 1/2 failed, an existing `sections.json` is deleted first, since it
was built from an incomplete extraction; otherwise it is reused unless
`force_reextract`, and on a cache miss `build_sections()` runs and
`save_output()` writes the result (`docpipe/preprocessing/pipeline.py:151-173`).

### Stage 3: assembling sections

`build_sections()` first calls `sort_pages()`, which, per page, calls
`find_gutters()` and `order_blocks()` from `columns.py`, then
`strip_running_headers()`, then walks every block: a
`SECTION_TITLE_CLASSES` block opens a new `Section`, a table or image
block becomes a `TableRef` or `FigureRef` plus a `[block_id]` placeholder
whose caption is settled by `docpipe.captions.resolve_title()`, and text
accumulates into `Section.content` and `Section.segments`.
`drop_directory_sections()` removes table-of-contents-like sections
(`docpipe/preprocessing/stage3_structure.py:275-468`).

### Folder-mode iteration

`run_folder()` iterates the PDFs under a directory, sorted by relative path.
It loads the layout model once, up front, only if at least one PDF still
needs (re-)extraction; when every PDF already has a cached `pages.json`,
folder mode skips the load entirely and logs that it did so
(`docpipe/preprocessing/pipeline.py:215-224`). Once loaded, the model is
reused across every document (not thread-safe, so processing stays
sequential); `run_folder()` calls `run_single()` per document inside a
`try`/`except` turning any exception into `status="error"`, and rewrites
`_index.json` after every document so partial progress survives an
interruption (`docpipe/preprocessing/pipeline.py:187-266`).

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
(`docpipe/preprocessing/models.py:152-175`): `title`, `content` (joined
prose with `[block_id]` placeholders), `page_number`, `tables`
(`list[TableRef]`), `figures` (`list[FigureRef]`), `segments` (reading-order
content units), and `pages` (sorted distinct page numbers, derived from
`segments`). A `TableRef`/`FigureRef` carries `id`, `path`, `caption`,
`page_number`, and `bbox` (one rect, matching a segment's own `bbox`);
`TableRef` additionally carries `source_text`. One segment is
`{"page": int, "kind": "text"|"table"|"figure", "text": str, "ref":
block_id}`; `stage3_structure.py` also attaches an optional `"bbox"` key to
every segment kind (`docpipe/preprocessing/stage3_structure.py:318,404,427`),
a field the `Section` docstring in `models.py:159-161` omits.

| File | Written by | Holds |
|---|---|---|
| `results/pages.json` | Stage 1+2 | a list of `PageData.to_dict()` |
| `results/sections.json` | Stage 3 | `{"sections": [Section.to_dict(), ...]}` |
| `results/page_transcription_report.json` | text fallback | `{pages_total, pages_missing_text, pages_transcribed, pages_empty, pages_failed, blocks_added}` |
| `images/<block_id>.png` | Stage 2 | one PNG crop per table or image block |
| `_index.json` | folder mode | `{relative_pdf_path: {status, output_dir, sections}}` |

(`docpipe/artifacts.py:12-22`; `docpipe/preprocessing/page_text_fallback.py:161-265`.)

## Configuration

| Name | Kind | Default | Effect |
|---|---|---|---|
| `input`, `output` (positional) | CLI | none; `output` falls back to the profile's processed directory | PDF file or folder (omitted only with `--rebuild-stage3`), and the output directory |
| `--force-reextract` / `--rebuild-stage3` | CLI flags | off | ignore both caches and rerun Stages 1 to 3, or rerun only Stage 3 from cached `pages.json` |
| `--report-columns` | CLI flag | off | read-only report of multi-column pages, changes nothing |
| `--transcribe-missing-text` | CLI flag | off | turns on the vision-model fallback; needs a running vision server |
| `--pages START END` | CLI flag, 2 ints | whole document | 0-indexed, end-exclusive page range; single-PDF only |
| `--glob` | CLI flag | `*.pdf` | pattern `run_folder()` matches PDFs against in folder mode (`pipeline.py:482`) |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | names the active profile |
| `--log-level` | CLI flag | `INFO` | logging verbosity: `DEBUG`/`INFO`/`WARNING`/`ERROR` (`pipeline.py:485-486`) |
| `DOCPIPE_LAYOUT_AUTOCAST` | env var | `off` | `bf16`, `fp16`, or `off`: reduced-precision Stage 2 pass on CUDA |
| `DOCPIPE_LAYOUT_PREFETCH` | env var | `1` | Stage 2 batches rendered ahead of the running forward pass, as `LAYOUT_PREFETCH_BATCHES` (`config.py:58`) |
| `PAGE_TRANSCRIBE_WORKERS` / `PAGE_RENDER_WORKERS` | env vars | `64` / `4` | concurrent transcription calls and page renders in the fallback, bounded separately |

`Profile.column_layout` (`docpipe/profile.py:37`) is optional: it defaults
to `"auto"`, `run()` falls back to `"auto"` even with no active profile
(`pipeline.py:537`), and there is no dedicated `--column-layout` CLI flag.
`Profile.__post_init__` raises
`ValueError` only if it is set to something outside `auto`/`single`/`double`
(`profile.py:46-50`). `auto` looks for a gutter and accepts one column as
the answer, `double` falls back to a centre split if none is found, and
`single` never looks.

A profile must additionally supply the following, or a
`LookupError`/`SystemExit` follows:

| Name | Default | Effect |
|---|---|---|
| `preprocessing.HYPHEN_EXCEPTIONS` | none | words that keep a line-ending hyphen from gluing to the next line |
| `preprocessing.CAPTION_MAX_WORDS` | none; kwp = 45, scenarios = 160 | word-count ceiling for a caption |
| `preprocessing.TITLE_EXCLUDE_PREFIXES` | none | prefixes that keep a block from being read as a heading |
| `preprocessing.DIRECTORY_FIGTAB_WORDS` | none | words opening a figure/table list entry, for directory-section detection |
| `preprocessing.BIBLIOGRAPHY_TITLE_WORDS` | none | title words routing a section to the literature path instead of directory-stripping |

A selection of the module constants that tune detection and assembly:

| Name | Default | Effect |
|---|---|---|
| `LAYOUT_DETECT_DPI` / `PAGE_RENDER_DPI` | 150 / 300 | render resolution for the detection pass and for saved table/figure crops; a page is re-rendered only when the two differ (`stage2_layout.py:959-1020`) |
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
| A Stage 1 page raises during extraction, or `n_failed > 0` after Stage 1/2 | the page is skipped and counted; `pages.json` is not written, so the next run retries extraction from scratch (`stage1_extract.py:224-234`; `pipeline.py:118-126`) |
| A Stage 2 batch's forward pass raises | recorded in `failed_batches`, its pages get no layout; once every batch has run, `detect_layout_all_pages` raises `LayoutDetectionFailed` naming the batch numbers and affected page count (`stage2_layout.py:1005-1012,1061-1068`) |
| `LayoutDetectionFailed` reaches `run_folder`'s per-document handler | the document is marked `status="error"` in `_index.json` and the run continues; called directly, the exception propagates unhandled (`pipeline.py:237-256,529-544`) |
| A page fails to render for Stage 2, its post-detection processing raises, or a crop fails to encode or write | logged and skipped; the page keeps its Stage-1-only data, and a written `Block` can still reference a failed crop (`stage2_layout.py:491-552,992,1032`) |
| `pages.json` or `sections.json` is unreadable, or a Stage 3 cache was built while `n_failed` was set, or the input path is neither a `.pdf` file nor a directory | treated as absent and rebuilt, deleted before the cache-hit check runs, or `run()` raises `ValueError` and `main()` exits with status 1 (`pipeline.py:58-59,154-168,438,542-544`) |
| No profile is active but a profile-gated function is called, or `--profile` resolves after prompt-binding import time | a `LookupError` propagates uncaught, or `resolve_profile` raises `SystemExit` (`stage1_extract.py:41-43`; `profile.py:76-82,155-169,178-197`) |
| A page-transcription call raises, returns an empty markdown string, or more candidates need transcription than `max_pages` | counted in `pages_failed` or `pages_empty`, or truncated with `pages_missing_text` still reporting the true total (`page_text_fallback.py:196-204`); unreachable through the CLI or `run()`, since `_fill_missing_page_text()` never passes `max_pages` (`pipeline.py:369-374`) |
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
  (`stage2_layout.py:293-312`;
  `tests/test_stage2_perf.py: test_boxes_come_back_as_float32`).
- Real text columns measure an aligned-left-edge fraction of at least 0.90,
  labels scattered around a chart at most 0.43, the gap
  `COLUMN_ALIGN_TOL_PT`/`COLUMN_MIN_ALIGNED_FRAC` are set to separate
  (`docpipe/preprocessing/config.py:133-137`). A bulleted list on one
  two-column page produced 0.71 against the 0.75 single-edge threshold;
  allowing alignment on one or two edges instead of one keeps it from
  reading across the gutter (`docpipe/preprocessing/columns.py:132-150`).
- 423 sections across 99 documents in a corpus snapshot carry Unicode
  Private Use Area glyphs from a symbol font; `STRIP_PRIVATE_USE` drops
  them (`docpipe/preprocessing/config.py:189-196`).
- Captions run to a median of 8 words on the kwp corpus, 24 at the 99th
  percentile, so `CAPTION_MAX_WORDS` is 45 there
  (`profiles/kwp/preprocessing.py:28-32`); scenarios panel descriptions and
  legends routinely run 60 to 150 words, so `CAPTION_MAX_WORDS` is 160
  there (`profiles/scenarios/preprocessing.py:31-35`).
- Eleven plans in the heat-plan corpus carry no PDF text layer, together
  holding 1,270 tables and figures Stage 2 transcribed with no surrounding
  text (`docpipe/preprocessing/page_text_fallback.py:1-11`). Treating the
  fallback's legitimate empty-page answer as a failure once reported 106
  broken calls for a run where none actually broke; `pages_empty` and
  `pages_failed` are counted apart to avoid that
  (`docpipe/preprocessing/page_text_fallback.py:184-187`). Caption
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
  no model call.
- `tests/test_preprocessing_config.py`: `test_dump_json_atomic_keeps_old_file_on_error`
  pins that a failed atomic write leaves the original file untouched.
- `tests/test_preprocessing_pipeline.py`: `test_write_index_keys_by_relative_path_no_collision`
  pins that `_index.json` is keyed by relative path, and
  `test_a_lone_path_with_rebuild_stage3_is_the_processed_root` pins the
  CLI's positional-argument remapping.

## Modules

`docpipe/preprocessing/pipeline.py` orchestrates Stages 1 to 3 for one PDF
or a folder of PDFs, and owns both resumable caches, the optional
text-fallback wiring, folder-mode indexing, and the command line.
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
`PageData`. Called only from `pipeline._fill_missing_page_text()` when
`--transcribe-missing-text` is set.

Two more modules define the shapes this stage produces without a chapter
of their own: `models.py` (the dataclasses) and `config.py` (most tunable
constants; `page_text_fallback.py` holds its own set outside it:
`MIN_PAGE_CHARS`, `PAGE_WORKERS`, `PAGE_RENDER_WORKERS`, `TEXT_AREA` and
`RENDER_DPI`). Three cross-cutting modules this stage calls into are
documented on [The parts every stage uses](core.md): `docpipe/artifacts.py`,
`docpipe/captions.py` for `resolve_title()`, and `docpipe/profile.py`.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/preprocessing/pipeline.py</code></summary>

pipeline.py: Orchestrates the PDF preprocessing pipeline, Stages 1 to 3.

Stage 1 reads text blocks with PyMuPDF, as rawdict. Stage 2 runs PP-DocLayoutV3
to detect table and image crops, layout labels, and caption resolution. Stage 3
assembles sections and writes sections.json. LLM-based section refinement lives
in docpipe.refinement, not in this module.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/preprocessing/stage1_extract.py</code></summary>

stage1_extract.py: Extracts text with PyMuPDF, as rawdict.

Text blocks are extracted per page and returned as PageData. Paragraphs are
deliberately not merged: Stage 2 suppression needs block boundaries precise
enough to match model-predicted boxes. Bboxes are [x0, y0, x1, y1] in points,
origin top-left, stored without coordinate flipping.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/preprocessing/stage2_layout.py</code></summary>

stage2_layout.py: Detects page layout with PP-DocLayoutV3 and turns
detections into tables, images, section titles and text suppressions
for Stage 3.

Renders the open fitz pages from Stage 1 in batches and runs object
detection. Each surviving box becomes a text suppression, a saved
table or image crop, or a title or caption Block; classes outside
those sets are ignored, since the Stage 1 PyMuPDF text blocks already
cover that content. A detection passes a global confidence filter,
then a per-class threshold, then per-class non-maximum suppression
and cross-class suppression among table and image boxes, so one
region never yields two crops.

Two passes run over the whole document afterward. Font-based heading
promotion turns a plain text block into a section title when the
layout model missed it, using the document's dominant body font size
as the reference. Caption resolution attaches the nearest
caption-like block to each table or image, first among the blocks
the layout model labelled as captions, then, within a fixed distance,
among plain text; the claimed block is removed from the page so it
is not also read as section prose.

A batch whose pages never reached the detection model is reported as
LayoutDetectionFailed rather than left with text and no layout, so
the caller drops the document for the next run to retry.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/preprocessing/stage3_structure.py</code></summary>

stage3_structure.py: Assembles document sections deterministically
from pages that carry the layout labels Stage 2 attached.

Walks every block in reading order. A block labelled as a section
title opens a new Section; a table or figure block becomes a
TableRef or FigureRef plus a [block_id] placeholder in the section
content; plain text is appended as prose. Reading order across a
multi-column page is settled first, by columns.sort_pages.

Two passes run before assembly. strip_running_headers drops text
blocks whose page-number-normalized text recurs in the same header
or footer band on enough pages to be a running header or footer,
without touching a section title. drop_directory_sections removes
table-of-contents, list-of-figures and index sections by scoring how
much of a section's text is directory-listing entries, while keeping
a section that still references a real table or figure and routing a
bibliography title to the Stage 4 literature path instead of
dropping it.

A table's or figure's caption is settled during assembly, where the
section text and its placeholder are both available: resolve_title
(docpipe.captions) chooses between the caption block Stage 2 attached
by distance and a nearby sentence in the section text, for plans
whose tables carry a rounding footnote that would otherwise be read
as the caption.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/preprocessing/page_text_fallback.py</code></summary>

page_text_fallback.py: Synthesizes text blocks for pages that carry
no usable PDF text layer.

Stage 1 reads the PDF's own text layer. Some plans have none: the
pages are vector graphics or images end to end, get_text returns
nothing, and every section Stage 3 assembles from them is a body of
bare [pNN_tbl0] markers. Eleven plans in the heat-plan corpus are
like that, together holding 1270 tables and figures that Stage 2
transcribed and that then had no text to explain them
(tests/test_page_text_fallback.py).

This module fills the gap at the level where it opens: a page's text
blocks. The page is rendered, one model call transcribes it, and the
reply becomes Block(type="text") entries on the same PageData every
other page carries. Stage 2, Stage 3, refinement, chunking and
embedding then run unchanged and read nothing about where the text
came from.

Each call does one job. Transcription is not cleanup: the model is
asked to read what is on the page and nothing else, and refinement
does its own work afterward, in its own calls. Asking for both at
once is how a model starts inventing the tidy version of a page it
cannot quite read.

The model call is an injected callable, so the loop, the thresholds
and the block synthesis are testable without a GPU.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/preprocessing/columns.py</code></summary>

columns.py: Determines reading order on a page with more than one
text column.

Sorting blocks top-to-bottom, then left-to-right is correct for a
single column and wrong for two: it reads across the gutter and
interleaves the columns line by line, which scrambles the text
beyond repair downstream.

Gutters, the vertical strips that text stays out of, are found
first; the page is then read column by column. A block that crosses
a gutter (a full-width heading, a wide table) is a spanning block: it
ends the columns above it and starts new ones below it, matching how
such a page is read.

The number of columns is not assumed. Two is the common case in a
report, but slide-style pages run to three or four columns, and a
wrong split is as bad as no split at all.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
