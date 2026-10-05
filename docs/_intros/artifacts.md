## The per-document results directory

Preprocessing, refinement, visuals and chunking each run as their own
command-line invocation (`docpipe/preprocessing/pipeline.py:548`,
`docpipe/refinement/pipeline.py:260`, `docpipe/visuals/pipeline.py:524`,
`docpipe/chunking/pipeline.py:410`, each its own `__main__` entry point).
Nothing survives between invocations except what a stage writes to disk,
so the files below let a later run resume or reuse an earlier one's work.

Every PDF preprocessing takes in gets one directory under a profile's
`processed_dir` (`<data root>/<profile>/pdf/processed`,
`Profile.processed_dir`, `docpipe/profile.py:308-310`), named after the
PDF's filename stem and kept relative to the input folder
(`docpipe/preprocessing/pipeline.py:240-242`). Inside it sit two
subdirectories, named once by `docpipe/artifacts.py` rather than spelled
out again per stage: `results/` (`DIR_RESULTS`) for the JSON files a
stage reads and writes, and `images/` (`DIR_IMAGES`) for the cropped
table and figure PNGs layout detection produces. Each stage's `config.py`
imports the constant it needs from `artifacts.py` and re-exports it, so
the filenames below live in exactly one place
(`docpipe/preprocessing/config.py:13-15`, `docpipe/refinement/
config.py:15-19`, `docpipe/visuals/config.py:12-13`, `docpipe/chunking/
config.py:7-9`).

Later stages list these directories at any depth through `document_dirs` in
`docpipe/artifacts.py` (`:40`): a directory that holds a file the stage reads
is a document and is not searched further, any other directory is searched,
and a document is known by its directory's name. Two directories of one name
under different subfolders are refused with both places named
(`DuplicateDocumentName`, a `ValueError`), and preprocessing refuses two such
PDFs before the layout model has run over either
(`docpipe/preprocessing/pipeline.py:210`). Extraction and the chat still look
for a document's crops at `<processed root>/<name>/images/`, so a document
below a subfolder reaches stages 4 to 6 but shows and attaches no crops there.

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
(`docpipe/preprocessing/pipeline.py:79-80, 101-126`). Separately, only
with `transcribe_missing_text=True` (`--transcribe-missing-text`, off by
default, the only part of preprocessing needing a model server),
preprocessing writes `page_transcription_report.json`, recording how many
pages needed transcription from a rendered image, a count that can be
zero (`docpipe/preprocessing/pipeline.py:75, 134-135, 376-379, 476-480`;
see [preprocessing](stages/preprocessing.md)). Stage 3 reads only the
in-memory pages object, whatever text it holds by then, and writes
`sections.json` (`docpipe/preprocessing/stage3_structure.py:275`); it
never opens `page_transcription_report.json` itself. That file is read
later by chunking's `enrich_page_source`, backfilling a
`page_text_transcribed` database column
(`docpipe/chunking/database.py:158-185`).

[Text refinement](stages/refinement.md) reads `sections.json` as its
only accepted input and writes `sections_refined.json` plus
`refinement_report.json`, recording what it could not refine. A pass in
which the model server did not serve a window writes
`sections_refined.partial.json` instead of `sections_refined.json`; the
partial file names the missing windows, and the report is left as it was
(`docpipe/refinement/refine.py:1123-1223`). A pass whose cut of an oversized
section was not served writes neither. [Reading the pictures](stages/visuals.md) reads
the crops left in `images/` together with whichever section text is
available, preferring `sections_refined.json` over `sections.json`, and
writes `visuals.json` (`docpipe/visuals/pipeline.py:61-70`).
[Chunking](stages/chunking.md)'s merge step folds `sections_refined.json`
and `visuals.json` into `document.json`, which a separate load step reads
into the database (`docpipe/chunking/merge.py:71-147`).

## How a later stage finds them

A later stage never consults an index of what exists elsewhere: it builds
`doc_dir / <constant>` from `artifacts.py` and checks whether that path
is present, so a document's own directory is the only record of how far
it has progressed. That check is safe because every write is atomic,
each stage's `dump_json_atomic` writing a temp file and swapping it in
with `os.replace` (`docpipe/preprocessing/config.py:281-296`,
`docpipe/refinement/config.py:171-191`, `docpipe/visuals/
config.py:16-31`, `docpipe/chunking/merge.py:136-146`), so a killed job
leaves the old file or none, never a partial one.

A missing upstream file is tolerated two different ways. Within a single
run, visuals reads whichever of `sections_refined.json` or
`sections.json` exists, and merge treats `visuals.json` as optional but
requires `sections_refined.json`, returning `None` if that is missing
(`docpipe/visuals/pipeline.py:61-70`,
`docpipe/chunking/merge.py:89-106`). Across a batch, refinement's,
visuals' and merge's batch entry points list the document directories
under the root, at any depth, that already carry the needed file, so a
document without it is
left out of the run rather than counted as a failure; refinement and
visuals warn only when the filter leaves no candidates at all, not once per
excluded document, while merge also warns once, naming up to twenty
directories that carry `sections.json` and no `sections_refined.json`
(`docpipe/refinement/pipeline.py:83-98`,
`docpipe/visuals/pipeline.py:316-334`,
`docpipe/chunking/merge.py:160-181`). A missing and a corrupted file are
not alike: `_load_pages_cache` treats an unreadable
`pages.json` as absent and re-extracts, but the readers of
`sections.json`, `sections_refined.json` and `visuals.json` call
`json.load` unguarded and raise on a truncated file
(`docpipe/preprocessing/pipeline.py:50-61`,
`docpipe/refinement/refine.py:1152-1153, 1154-1155`,
`docpipe/chunking/merge.py:96-102`). The one reader that guards is
`_read_partial`, which treats an unreadable `sections_refined.partial.json`
as absent (`docpipe/refinement/refine.py:1237-1249`).

Merge decides whether its cached `document.json` is reusable by
comparing modification times, not existence, since visuals rewrites
`visuals.json` every run even when every item came from its item-level
cache (`docpipe/chunking/merge.py:49-68`). Refinement and
visuals each also record, in `.prompt_versions.json`, which prompt
produced a cached result, so a later run can tell whether the prompt it
would use has changed; that mechanism belongs to
[the parts every stage uses](stages/core.md).

Every check here can be bypassed, though not by the same knobs.
Refinement and visuals each take a `force` argument, redoing the stage
unconditionally, and a `force_stale` argument, redoing it only when the
prompt has changed, surfaced as `--force`/`--force-stale`
(`docpipe/refinement/pipeline.py:48-49, 62-69`,
`docpipe/visuals/pipeline.py:120-121, 140-148`); a forced refinement
resumes an unfinished pass that agrees with its input, prompts and window
size, instead of discarding it. Merge takes only its own
`force`, surfaced as `--force` (`docpipe/chunking/merge.py:71, 84`); it
has no staleness check to bypass.

Separately, `_index.json` at the processed root records, after every PDF
in a folder run, which output directory holds its results and how many
sections it produced, so an interrupted run leaves a readable record of
what finished (`docpipe/preprocessing/pipeline.py:262, 273-287`).
