# 2-3. Reading the page

| | |
|---|---|
| **In** | A PDF path (Stages 1-2) or a cached results/pages.json (Stage 3 alone); Stage 1's fallback also reads the profile's page-transcription prompt. |
| **Out** | results/pages.json (Stage 1+2 cache), results/sections.json (Stage 3, the hand-off to refinement), page_transcription_report.json when the text fallback ran, and PNG crops under images/. |
| **Resumes on** | A run reuses results/pages.json and results/sections.json when present and readable; --force-reextract redoes Stages 1+2, --rebuild-stage3 redoes only Stage 3, and an incomplete extraction is never cached so the next run retries it on its own. |

This stage turns a PDF into the structured document that every later stage reads: a flat list of sections, each with a title, a page number, prose content, and placeholders where a table or figure sits in the reading order. Nothing upstream of it knows what a "section" is -- Stage 1 sees character-level text, Stage 2 sees bounding boxes with class labels -- so this is where a PDF stops being a page image and starts being a document with structure an LLM or a retrieval index can reason over. Skip it and refinement, image processing, and chunking have nothing to consume: they all take `sections.json` as their input.

Concretely, it reads the PDF file itself for a fresh run, or `results/pages.json` when a previous run already extracted it. It writes two caches: `results/pages.json` after Stage 1 (PyMuPDF `rawdict` text blocks) and Stage 2 (PP-DocLayoutV3 layout detections merged in -- tables, images, titles, captions, with suppressed text removed), and `results/sections.json` after Stage 3 assembles those blocks into sections. Table and image crops go to `images/<block_id>.png` as a side effect of Stage 2. When `--transcribe-missing-text` is set, a page whose PyMuPDF text layer is empty or too thin (under 60 characters -- a scanned map still carries a stamped page number, which is text by the letter and nothing by the meaning) is rendered and sent to the vision model instead, and its reply becomes that page's text blocks; the outcome is written to `page_transcription_report.json` regardless of whether any page needed it, so a report that exists at all means the corpus was checked.

Three decisions here are easy to get wrong if you have not read the code. First, paragraphs are never merged in Stage 1 -- each PyMuPDF block stays its own `Block`, deliberately, because Stage 2's text suppression matches model-predicted boxes against block boundaries, and a merged paragraph would blur that match. Second, reading order is not simply top-to-bottom: `columns.py` looks for vertical gutters the text stays clear of and, when it finds them, reads the page column by column, with a spanning block (a full-width heading, a wide table) closing the columns above it and opening new ones below. This only fires when the page's text blocks pass an alignment check on two left edges, not one, because a bulleted list is typeset on two edges (the bullet and its continuation indent) and a single-edge test rejected list-carrying columns outright. Third, a table's caption is not simply "the nearest caption block" -- Stage 2 attaches by distance, which occasionally attaches a rounding footnote instead of the real caption sitting a few words earlier in the text; `resolve_title` in Stage 3 corrects this using the section content and the placeholder together, and the sentence that actually names the table is left in place in the section body so a quote of it stays findable there.

Cost is asymmetric across the three stages. Stage 1 is pure CPU (PyMuPDF) and touches no network. Stage 2 needs PP-DocLayoutV3 loaded on GPU if one is available (it falls back to CPU otherwise) and runs in batches of 12 pages, rendered at 150 DPI for detection and 300 DPI for the saved crops; loading the model is the expensive part, which is why `run_folder` loads it once and reuses it across every PDF in a folder rather than per document. Stage 3 is deterministic and needs neither model nor network. The optional text fallback is the one part of this whole stage that talks to a server: it needs the profile's vision model up, runs up to 64 pages concurrently (bounded separately from page rendering, which runs 4 at a time under the GIL), and is off by default specifically so that a normal preprocessing run has no server dependency. If a Stage 2 batch never reaches the model at all, `detect_layout_all_pages` raises `LayoutDetectionFailed` rather than letting those pages continue on with text blocks but no layout -- silently blank tables and missing headings would otherwise look like a complete, cacheable document to everything downstream.

Resumption is cache-based at each of the two boundaries. `run_single` loads `results/pages.json` if it exists and skips Stages 1+2 entirely; `--force-reextract` discards that cache and redoes them. Stage 3 likewise checks `results/sections.json` before rebuilding, unless `--rebuild-stage3` is passed, which redoes only Stage 3 from the cached pages for every document under an output root, without touching a PDF or loading the layout model at all -- useful when you only changed section-assembly logic. Folder mode rewrites `_index.json` after every single document, so an interrupted batch run leaves a readable record of what finished. Stage 1+2 deliberately never cache a partial result: if any page failed extraction, `pages.json` is not written, and if a stale `sections.json` exists from a prior, complete-looking run built on that same incomplete extraction, it is deleted rather than reused -- the alternative is a run that looks done, isn't, and never gets picked up by a retry.

The code visibly defends against a handful of concrete failure shapes beyond that one. A too-short or non-alphanumeric text block from Stage 1 is dropped rather than kept as noise (`TEXT_BLOCK_MIN_CHARS = 3` plus an alphanumeric check). Private-use-area glyphs from a symbol font are stripped and counted, not silently thinned into the text, so a document typeset that way shows up in the log instead of just looking short on content. Two overlapping detections of the same class are resolved by per-class non-maximum suppression, and two overlapping detections of different classes (a "table" and a "figure" box on the same region) are resolved by cross-class suppression, so one region on the page cannot yield two crops. A title block whose predicted box sits on the same text row as another block is treated as inline text rather than opening a spurious new section. And Stage 3's directory-detection guard only drops a section that reads as a listing from its very start and leaves almost no prose behind, specifically so a content section that merely references a couple of figures, or ends with a short list, survives.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/preprocessing/pipeline.py`

pipeline.py – Orchestration of the PDF preprocessing pipeline (Stages 1-3).

  1. PyMuPDF        → Text blocks (rawdict)
  2. PP-DocLayoutV3 → Table / image crops + layout labels + caption resolution
  3. Section assembly → sections.json

LLM-based section refinement lives in ``docpipe.refinement``.

Author: Felix Vossel

### `docpipe/preprocessing/stage1_extract.py`

stage1_extract.py – Text extraction with PyMuPDF (rawdict).

Text blocks are extracted per page and returned as PageData. Paragraphs are
deliberately NOT merged: Stage 2 suppression needs block boundaries precise
enough to match model-predicted boxes. Bboxes are [x0, y0, x1, y1] in points,
origin top-left, stored without coordinate flipping.

Author: Felix Vossel

### `docpipe/preprocessing/stage2_layout.py`

stage2_layout.py – Layout detection via PP-DocLayoutV3 (HuggingFace Transformers).

Renders the open fitz pages from Stage 1 per batch, runs object detection, and
turns each surviving box into either a text suppression, a saved table/image
crop, or a title/caption Block. Classes outside those sets are ignored — the
Stage-1 PyMuPDF text blocks already cover that content.

Author: Felix Vossel

### `docpipe/preprocessing/stage3_structure.py`

stage3_structure.py – Deterministic section assembly from layout-annotated pages.

Walks all blocks in reading order: SECTION_TITLE_CLASSES blocks open a new
Section, tables/figures become a TableRef/FigureRef plus a [block_id]
placeholder in the section content, and plain text is appended as prose.

Author: Felix Vossel

### `docpipe/preprocessing/page_text_fallback.py`

page_text_fallback.py – Text for pages that carry no text layer.

Stage 1 reads the PDF's own text layer. Some plans have none: the pages are
vector graphics or images end to end, `get_text` returns nothing, and every
section Stage 3 assembles is a body of bare [pNN_tbl0] markers. Eleven plans in
the heat-plan corpus are like that, together holding 1270 tables and figures
that Stage 2 transcribed and that then had no text to hang off.

This module fills that gap at the level where it opens: a page's text BLOCKS.
The page is rendered, one model call transcribes it, and the reply becomes
Block(type="text") entries on the same PageData every other page carries. From
there Stage 2, Stage 3, refinement, chunking and embedding run unchanged and
know nothing about where the text came from.

Deliberately ONE job per call. Transcription is not cleanup: the model is asked
to read what is on the page and nothing else, and the refinement stage does its
own work afterwards in its own calls. Asking for both at once is how a model
starts inventing the tidy version of a page it cannot quite read.

The model call is an injected callable, so the loop, the thresholds and the
block synthesis are testable without a GPU.

Author: Felix Vossel

### `docpipe/preprocessing/columns.py`

columns.py – Reading order on a page that has more than one text column.

Sorting blocks top-to-bottom, then left-to-right is right for a single column
and wrong for two: it reads across the gutter and interleaves the columns line
by line, which scrambles the text beyond repair downstream.

So the gutters are found first — the vertical strips text stays out of — and the
page is then read column by column. Blocks that DO cross a gutter (a full-width
heading, a wide table) are spanning blocks: they end the columns above them and
start new ones below, which is exactly how such a page reads.

The number of columns is not assumed. Two is the common case in a report, but
slide-style pages run to three or four, and one wrong split there is as bad as
no split at all.

Author: Felix Vossel

[Back to the index](../README.md)
