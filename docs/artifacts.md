# What each stage leaves behind

Generated from `docpipe/artifacts.py` by `scripts/build_docs.py`: the names below and the stage against each are that module's own constants and its own comments.

## The per-document results directory

Preprocessing, refinement, visuals and chunking each run as their own
command-line invocation (`docpipe/preprocessing/pipeline.py:547`,
`docpipe/refinement/pipeline.py:263`, `docpipe/visuals/pipeline.py:516`,
`docpipe/chunking/pipeline.py:369`, each its own `__main__` entry point).
Nothing survives between invocations except what a stage writes to disk,
so the files below let a later run resume or reuse an earlier one's work.

Every PDF preprocessing takes in gets one directory under a profile's
`processed_dir` (`<data root>/<profile>/pdf/processed`,
`Profile.processed_dir`, `docpipe/profile.py:111-113`), named after the
PDF's filename stem and kept relative to the input folder so two
same-named PDFs in different subfolders never collide
(`docpipe/preprocessing/pipeline.py:233-235`). Inside it sit two
subdirectories, named once by `docpipe/artifacts.py` rather than spelled
out again per stage: `results/` (`DIR_RESULTS`) for the JSON files a
stage reads and writes, and `images/` (`DIR_IMAGES`) for the cropped
table and figure PNGs layout detection produces. Each stage's `config.py`
imports the constant it needs from `artifacts.py` and re-exports it, so
the filenames below live in exactly one place
(`docpipe/preprocessing/config.py:13-15`, `docpipe/refinement/
config.py:15-18`, `docpipe/visuals/config.py:12-13`, `docpipe/chunking/
config.py:7-9`).

## Which stage writes which file

Layout detection, the second step of preprocessing, writes first: it
crops every detected table and figure into `images/<block id>.png` and
records that path on the block itself
(`docpipe/preprocessing/stage2_layout.py:571, 684-693, 722-731`).
Preprocessing's own JSON output follows in two files. `pages.json` is
written only once Stage 1 (text extraction) and Stage 2 (layout
detection) have both completed with no failed page; it caches their
combined result, Stage 1's text blocks together with Stage 2's table and
image blocks, and doubles as a resume cache so a `--rebuild-stage3` run
or a later re-run can skip both stages
(`docpipe/preprocessing/pipeline.py:78-79, 100-125`). Separately, only
with `transcribe_missing_text=True` (`--transcribe-missing-text`, off by
default, the only part of preprocessing needing a model server),
preprocessing writes `page_transcription_report.json`, recording how many
pages needed transcription from a rendered image, a count that can be
zero (`docpipe/preprocessing/pipeline.py:74, 133-134, 375-378, 475-479`;
see [preprocessing](stages/preprocessing.md)). Stage 3 reads only the
in-memory pages object, whatever text it holds by then, and writes
`sections.json` (`docpipe/preprocessing/stage3_structure.py:275`); it
never opens `page_transcription_report.json` itself. That file is read
later by chunking's `enrich_page_source`, backfilling a
`page_text_transcribed` database column
(`docpipe/chunking/database.py:157-186`).

[Text refinement](stages/refinement.md) reads `sections.json` as its
only accepted input and writes `sections_refined.json` plus
`refinement_report.json`, recording what it could not refine
(`docpipe/refinement/pipeline.py:43-45`, `docpipe/refinement/
refine.py:1026-1087`). [Reading the pictures](stages/visuals.md) reads
the crops left in `images/` together with whichever section text is
available, preferring `sections_refined.json` over `sections.json`, and
writes `visuals.json` (`docpipe/visuals/pipeline.py:56-65`).
[Chunking](stages/chunking.md)'s merge step folds `sections_refined.json`
and `visuals.json` into `document.json`, which a separate load step reads
into the database (`docpipe/chunking/merge.py:68-144`).

## How a later stage finds them

A later stage never consults an index of what exists elsewhere: it builds
`doc_dir / <constant>` from `artifacts.py` and checks whether that path
is present, so a document's own directory is the only record of how far
it has progressed. That check is safe because every write is atomic,
each stage's `dump_json_atomic` writing a temp file and swapping it in
with `os.replace` (`docpipe/preprocessing/config.py:281-296`,
`docpipe/refinement/config.py:157-172`, `docpipe/visuals/
config.py:16-31`, `docpipe/chunking/merge.py:133-143`), so a killed job
leaves the old file or none, never a partial one.

A missing upstream file is tolerated two different ways. Within a single
run, visuals reads whichever of `sections_refined.json` or
`sections.json` exists, and merge treats `visuals.json` as optional but
requires `sections_refined.json`, returning `None` if that is missing
(`docpipe/visuals/pipeline.py:56-65`,
`docpipe/chunking/merge.py:86-103`). Across a batch, refinement's,
visuals' and merge's batch entry points filter candidate subdirectories
to those already carrying the needed file, so a document without it is
left out of the run rather than counted as a failure; each batch warns
only when the filter leaves no candidates at all, not once per excluded
document (`docpipe/refinement/pipeline.py:43-45, 87-99`,
`docpipe/visuals/pipeline.py:304-324`,
`docpipe/chunking/merge.py:157-169`). A missing and a corrupted file are
not alike: `_load_pages_cache` treats an unreadable
`pages.json` as absent and re-extracts, but the readers of
`sections.json`, `sections_refined.json` and `visuals.json` call
`json.load` unguarded and raise on a truncated file
(`docpipe/preprocessing/pipeline.py:49-60`,
`docpipe/refinement/refine.py:1052-1059`,
`docpipe/chunking/merge.py:93-99`).

Merge decides whether its cached `document.json` is reusable by
comparing modification times, not existence, since visuals rewrites
`visuals.json` every run even when every item came from its item-level
cache (`docpipe/chunking/merge.py:46-65`). Refinement and
visuals each also record, in `.prompt_versions.json`, which prompt
produced a cached result, so a later run can tell whether the prompt it
would use has changed; that mechanism belongs to
[the parts every stage uses](stages/core.md).

Every check here can be bypassed, though not by the same knobs.
Refinement and visuals each take a `force` argument, redoing the stage
unconditionally, and a `force_stale` argument, redoing it only when the
prompt has changed, surfaced as `--force`/`--force-stale`
(`docpipe/refinement/pipeline.py:52-53, 66-73`,
`docpipe/visuals/pipeline.py:102-103, 122-130`). Merge takes only its own
`force`, surfaced as `--force` (`docpipe/chunking/merge.py:68, 81`); it
has no staleness check to bypass.

Separately, `_index.json` at the processed root records, after every PDF
in a folder run, which output directory holds its results and how many
sections it produced, so an interrupted run leaves a readable record of
what finished (`docpipe/preprocessing/pipeline.py:255, 266-280`).

## What `docpipe/artifacts.py` says

<details>
<summary><code>docpipe/artifacts.py</code></summary>

artifacts.py: Names the per-document result files under `<doc>/results/`,
in the order the pipeline writes them.

One definition serves all five pipeline modules: a filename spelled out in
four separate config.py files drifts, and the module that reads a file is
rarely the one that wrote it.

Author: Felix Vossel

</details>

## Directories

| name | path |
|---|---|
| `DIR_RESULTS` | `results` |
| `DIR_IMAGES` | `images` |

## Files

| name | path | written by |
|---|---|---|
| `PAGES_JSON` | `results/pages.json` | preprocessing (extract) |
| `SECTIONS_JSON` | `results/sections.json` | preprocessing (structure) |
| `PAGE_TRANSCRIPTION_REPORT_JSON` | `results/page_transcription_report.json` | preprocessing (model-read pages) |
| `SECTIONS_REFINED_JSON` | `results/sections_refined.json` | refinement |
| `REFINEMENT_REPORT_JSON` | `results/refinement_report.json` | refinement (what failed) |
| `VISUALS_JSON` | `results/visuals.json` | visuals |
| `DOCUMENT_JSON` | `results/document.json` | chunking (merge) → database |

[Back to the index](README.md)
