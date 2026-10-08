# 6. Chunking, embedding, indexing

## Purpose

`docpipe.chunking` is Stage 6, the pipeline's last stage. Its `config.py`,
along with `preprocessing/config.py`, `refinement/config.py` and
`visuals/config.py`, imports the shared result filenames from
`docpipe/artifacts.py` rather than redeclaring them; fileprocessing does not
import that module,
writing its `Documents` row directly instead. Everything upstream produces
one JSON per PDF, readable only by that PDF's own further processing step.
This module merges the refined section text from
[refinement](refinement.md) (Stage 4) with the enriched table and figure data
from [visuals](visuals.md) (Stage 5) into one `document.json` per document,
loads it into the shared SQLite corpus database as `Sections`, `Pages`,
`SectionPages`, `Segments`, `Tables` and `Images` rows, and embeds each
section, table and figure as up to six typed vectors into one FAISS index. It
runs as `python -m docpipe.chunking` (`docpipe/chunking/__main__.py`).

It runs as three steps, merge, then db, then embed, run in sequence but
independently resumable and invocable through `--step`, plus three
standalone, additive maintenance steps, `enrich-bbox`, `enrich-page-source` and
`enrich-caption`, that backfill one column family on an already built corpus
without touching sections, embeddings or the index (`pipeline.py:148`).
Skipping this stage leaves a plan processed but absent from the database and
index everything downstream reads.

## Position in the pipeline

The db and embed steps require a `Documents` row
[fileprocessing](fileprocessing.md) has written; this module never creates one
itself (`database.py:5`). Nothing later in the pipeline reads
chunking's output as input to a further processing step: the database and
index are read at query time instead, by [extraction](extraction.md) and the
[inference](inference.md) package.

| | |
|---|---|
| **In** | `sections_refined.json` + `visuals.json` (merge); `document.json` (db, embed); `sections.json` (standalone `enrich-bbox`); `page_transcription_report.json` (standalone `enrich-page-source`); an existing FAISS index file, if present (embed). |
| **Out** | `document.json` per PDF; `Sections`, `Pages`, `SectionPages`, `Segments`, `Tables`, `Images` rows in the database; `Embeddings` rows and their vectors in the FAISS index file. |
| **Resumes on** | Merge: `document.json` newer than both its inputs. Db: a document already has `Sections` rows. Embed: an `(embedding_type, section_index, item_id)` triple already in `Embeddings`; an input whose batch failed has none, so a document with missing vectors is not done. `--force` clears exactly the step it is passed for. |
| **Needs** | A `Documents` row already written by fileprocessing, to resolve a processed directory (db, embed). One GPU replica per visible device (embed), or with `EMBEDDING_INDEX_BACKEND=api` an embeddings endpoint and no GPU. No other network call. |

## Method

### CLI entry and step selection

`main()` parses argv, resolves `--profile` into default `data_dir`, `db_path`
and `index_path` when omitted, calls `run()`, and exits 1 with a logged
traceback on any uncaught exception and with a logged `Embedding incomplete:`
sentence when the embed step left inputs without a vector (`pipeline.py:379`).
`run()` dispatches on
`--step`: the three `enrich-*` steps return after their own work; otherwise
merge, db and embed run in order, or only the named step (`pipeline.py:125`).

### Merge

For each document directory carrying `sections_refined.json`, found at any
depth under the root through `artifacts.document_dirs` (a directory that holds
the file is a document and is not searched further; two of one name under
different subfolders are refused with both places named), `merge_single` deep
copies its sections and replaces each table or figure dict, matched by id, with
its Stage 5 counterpart wherever that carries a `markdown` or `description`
key, writing the result to `document.json` through a `.part` file and
`os.replace` so a killed write leaves no truncated file for the cache to
accept (`merge.py:71`). `merge_batch` runs this over every candidate and
reports one success or failure per directory (`merge.py:160`). A
directory that carries `sections.json` and no `sections_refined.json` is
not a candidate, and the batch names up to twenty of them in one warning,
since an unfinished refinement leaves a document exactly there and the
database would otherwise just lack it (`merge.py:168-177`). The db step, the
embed step and the three `enrich-*` backfills list their directories the same
way, by the file each of them needs. A document below a subfolder therefore
reaches stages 4 to 6, but extraction and the chat still look for its crops at
`<processed root>/<document name>/images/`, so such a document shows and
attaches no crops there.

### Database insertion

When `--force` covers both the db and embed steps, `run()` first snapshots
every candidate's current FAISS ids through `get_document_faiss_ids`, before
the forced delete below removes the `Embeddings` rows that would otherwise name
them (`pipeline.py:180`; `database.py:706`). `update_database` then resolves
each directory to a `Documents.id`, skips it if `Sections` rows already exist
and `--force` is unset, or under `--force` deletes and reinserts, then
`_insert_sections` creates each `Pages` row via the get-or-create helper
`_page_id` (`execute()`/`SELECT` per distinct page number, cached in a dict
built once per document and shared across all its sections, `database.py:407`)
and bulk inserts `SectionPages`, `Segments`, `Tables` and `Images`,
one `executemany` each: four per section, not five (`database.py:329`,
`393`). `enrich_page_source` and `enrich_caption` then run automatically.

### Caption and page-source backfill

`enrich_page_source` reads each directory's `page_transcription_report.json`
and writes `Documents.page_text_transcribed`, the count of pages a model read
because the PDF had no text layer, skipping an already-marked document unless
forced (`database.py:167`). `enrich_caption` runs the shared rule
`docpipe.captions.resolve_title` over each unmarked table or image's caption,
section content and block id, recording the outcome in `caption_source`
(`database.py:222`; rule at `captions.py:42`).

### Embed: index load and reconciliation

`load_or_create_index` opens the FAISS file or creates a new
`IndexIDMap(IndexFlatIP)` (`embedding.py:76`); `index_ids` reads every id it
holds (`embedding.py:97`); `drop_embeddings_missing_from_index` deletes any
`Embeddings` row whose `faiss_id` is absent from that set; `next_id` becomes
the maximum of the index's count, the database's high-water mark, and one past
the largest held id (`pipeline.py:222`; `database.py:734`). `load_embedder`
then builds the embedder, and `note_embedding` in `pipeline.py` records its
model, dimension, backend and token limit in the database's `Meta` table (see
[store](store.md)). An index that already holds vectors of another model is not
continued with this one: vectors of two models do not compare. The run stops
before it writes a vector, ends 1 with one error line naming both models and no
traceback, and a second line that says the ways out: set `EMBEDDING_MODEL` to
the recorded model, run without `--step` and with `--force`, which embeds the
whole corpus with the new one, or set `EMBEDDING_ALLOW_MIXED_INDEX=1`, which
allows the mixture on purpose, records the other model beside the first
(`embedding/also`) and logs a warning. An index that holds no vectors may
change its model. An index with vectors and no recorded model, built before the
model was recorded, cannot be checked: the configured model is recorded as its
builder, and the log line says nothing proved the vectors to be its. The
default run with `--force` is not stopped, because its database step has
dropped the vectors first; `--step embed --force` over a mixed index is
stopped, since the check runs before the eviction. The embedder has been loaded
by then, so a stopped run still takes the model onto the GPU once, and rows
whose vector is missing from the index were reconciled before the check. No
vector or `Meta` row is written.
`load_embedder` reads `EMBEDDING_INDEX_BACKEND` (`index_backend()` in
`embedding.py`). With `local`, the default, it imports
`qwen3_vl_embedding.MultiGPUEmbedder` and loads the model data-parallel on
every visible GPU in bf16. With `api` it returns an `ApiIndexEmbedder`, which
wraps `docpipe.embedding.api.ApiEmbedder` (see [embedding](embedding.md)) and
needs no GPU; `load_embedder` returns before it imports torch or the model
module. The query side's `EMBEDDING_BACKEND` is a separate setting and changes
nothing here.

### Prepare and flush loop

`candidates` are the document directories carrying `document.json`, at any
depth. `prepared_ahead` streams
them through `prepare()` in a `ThreadPoolExecutor` bounded to
`EMBED_PREPARE_WORKERS` threads, keeping at most `EMBED_PREPARE_AHEAD`
documents' work in flight (`pipeline.py:105`). `prepare()` resolves the document
id and filters `build_embedding_inputs`' output against
`get_existing_embeddings`; an unresolved document contributes nothing and is
named in one warning at the run's end (`pipeline.py:250`, `321`). At
`EMBED_FLUSH_ITEMS` pending items, `create_embeddings` runs and the index saves
past `EMBED_SAVE_VECTORS` growth; a final flush and save close the run
(`pipeline.py:286-314`, `331`). One `Unembedded` tally runs through every
flush, and `embedded` counts the vectors actually created, not the inputs
handed over. Each prepare thread reuses one connection across calls:
`_worker_connection` caches it per thread for `document_id()` and
`get_existing_embeddings()`, replacing it only when a different `db_path` is
requested (`database.py:114`). Every connection, opened by `connect()`, sets
`PRAGMA busy_timeout = 30000`, raised from SQLite's five-second default so a
reader waits out a batch write on a half-gigabyte database over shared
storage instead of failing (`database.py:98`).

### Create embeddings

One flush splits its inputs into a text-only group and an image-bearing (VL)
group, sorts each by text length so a batch pads to its own spread, batches at
`EMBEDDING_BATCH_SIZE`, calls the embedder's `process()`, adds vectors to the
index under newly allocated contiguous ids, and writes the matching
`Embeddings` rows, grouped per document, through one shared `EmbeddingWriter`
(`embedding.py:193`). An embedder that sets `text_only`, which
`ApiIndexEmbedder` does, never sees the image-bearing group: those inputs are
dropped with one warning that counts them and get no `Embeddings` row, so an
index built through the api holds the text vectors of a corpus only. An
`ApiIndexEmbedder` scales each vector it returns to length one, as the local
model's are, because the index is an inner-product index.

### Standalone bbox backfill

`enrich_bbox` reads a re-run Stage 3 `sections.json`, builds a lookup from
block id and from (page, normalised text) to a bbox, and updates matching
`Segments`, `Tables` and `Images` rows, by default only where `bbox` is unset,
without touching embeddings, content or the index (`database.py:569`).

## Data model

`document.json` has the same shape as `sections_refined.json`: a list of
sections, each with a title, content, page numbers, segments, tables and
figures, with every table or figure dict swapped for its `visuals.json`
counterpart wherever one carries enriched content (`merge.py:5`).

`EmbeddingInput` (`chunking.py:38`) is one vector's input: `embedding_type`,
`pdf_name`, `section_index`, `item_id` (a table or figure block id, or `None`
for a section-level input), `text`, and `image` (set only for a VL input whose
crop exists on disk).

The six tables below live in the shared core schema (see [store](store.md)):

| DB table | Holds | Written from | Key constraint |
|---|---|---|---|
| `Pages` | One row per page. | `_page_id`, get-or-create, cached per document. | `UNIQUE(document, page_number)` |
| `Sections` | One retrieval chunk: title, content, primary page number. | One `INSERT` per section, in list order. | `UNIQUE(document, section_number)` |
| `SectionPages` | The distinct pages a section spans. | One `executemany` per section. | `PRIMARY KEY(section, page)` |
| `Segments` | Ordered, page-tagged text/table/figure pieces of a section. | One `executemany` per section. | `UNIQUE(section, ordinal)` |
| `Tables` / `Images` | One row per table or figure: caption, markdown or description, bbox; for a table also the result of stage 5's check of its transcription (`qa`). | One `executemany` per section. | none beyond the primary key |
| `Embeddings` | One row per stored vector: `faiss_id`, `embedding_type`, `owner_kind`, `owner_id`. | `EmbeddingWriter.write`, per flush. | `UNIQUE(owner_kind, owner_id, embedding_type)` |

`Segments`, `Tables` and `Images` each carry `bbox`: a JSON array of one or
more `[x0, y0, x1, y1]` rectangles in PDF points, top-left origin, `NULL` when
unknown, set at insertion when the merged JSON carries geometry and backfilled
additively by `enrich-bbox` (`docpipe/store/schema.sql:85`). `Tables` and
`Images` also carry `caption_source`: `stage` when the stored caption was kept,
`section_text` when `enrich_caption` replaced it (`schema.sql:102`). `Tables` also
carries `qa`, the JSON `{passed, coverage, coverage_assessed, duplication,
has_rows}` that stage 5 measured of the transcription it kept
(`_qa_json`), and `NULL` where nothing was measured, which reads as not checked
and not as passed: a table of an older run, one the model answered only in plain
text and one it never read. The column is added to an older database by
`_ensure_table_qa_column`, which `update_database` calls like the `bbox`
retrofit, and it is filled only when a document is inserted again. A document
already in the database is skipped, so an existing database gets its values
only through a forced re-chunk, which also renews the `Tables` ids that a
harvest and its decisions name a table by. There is no backfill that leaves the
ids alone; until then `scripts/table_numbers_in_pdf.py` recomputes the check
from the stored transcription. A table whose stage 5 run failed the check in an
older `visuals.json` carries `qa_warning` there but no `qa`, so its column stays
`NULL`.

The FAISS index is one `IndexIDMap` wrapping an `IndexFlatIP` of dimension
`EMBEDDING_DIM`, holding all six embedding types together, keyed by
database-allocated ids rather than insertion position (`embedding.py:76`).
`get_existing_embeddings` returns a document's embedded items as
`(embedding_type, section_index, item_id_or_None)` tuples (`database.py:648`);
a flush's writeback records `(embedding_type, section_index, item_id,
faiss_id)` tuples per document (`database.py:850`).

## Configuration

| Name | Kind | Default | Effect | Where read |
|---|---|---|---|---|
| `EMBEDDING_MODEL` | env var | `Qwen/Qwen3-VL-Embedding-8B` | model `load_embedder` loads, or the endpoint is asked for under `EMBEDDING_INDEX_BACKEND=api`, for every vector this run produces | `docpipe/embedding/config.py:21`, re-exported at `chunking/config.py:17` |
| `EMBEDDING_DIM` | env var | `4096` | vector dimension of a new FAISS index | `embedding/config.py:22`; `chunking/config.py:17` |
| `EMBEDDING_MAX_TOKEN_LENGTH` (as `MAX_TOKEN_LENGTH`) | env var | `16384` | `max_length` passed to the embedder; longer inputs truncate | `embedding/config.py:23`; `chunking/config.py:19` |
| `EMBEDDING_ALLOW_MIXED_INDEX` | env var / `embedding.allow_mixed_index` | `0` | `0` stops an append to an index of another embedding model before any vector is written (exit 1, one error line); a value other than `0` allows the mixture and records both models | `docpipe/chunking/config.py`, declared in `docpipe/settings.py` (stage `chunk`) |
| `EMBEDDING_INDEX_BACKEND` | env var | `local` | what builds the index: `local` makes `load_embedder` return a `MultiGPUEmbedder` on the visible GPUs; `api` makes it return an `ApiIndexEmbedder` over `docpipe.embedding.api.ApiEmbedder`, which needs an `EMBEDDING_BASE_URL` (or a hosted `EMBEDDING_PROVIDER`) and no GPU, takes text only and so leaves inputs that carry a picture out; recorded in `Meta` as `embedding/backend` | `index_backend()` in `chunking/embedding.py`; declared in `docpipe/settings.py` |
| `EMBEDDING_BACKEND` | env var | `local` | picks the query-time embedder in `docpipe.embedding`; `load_embedder` here does not read it, `EMBEDDING_INDEX_BACKEND` decides what builds the index | `embedding/config.py:19` |
| `SECTION_EMBED_MAX_WORDS` | code constant | `1800` | last-resort word cap on a section's embedding text, logged when it fires | `chunking/config.py:30`; `chunking.py:64` |
| `EMBEDDING_BATCH_SIZE` | code constant | `32` | items per model batch in `create_embeddings`; a same-named, env-driven constant in `embedding/config.py` (default `8`) is not read here, except by `ApiEmbedder` under the api backend, which splits each batch into requests of that size | `chunking/config.py:32` |
| `EMBED_PREPARE_WORKERS` | code constant | `8` | threads reading merged JSON and querying the DB while the GPUs work | `chunking/config.py:38`; `pipeline.py:286` |
| `EMBED_PREPARE_AHEAD` | code constant | `32` | documents' prepared input allowed to sit unconsumed | `chunking/config.py:45`; `pipeline.py:105` |
| `EMBED_FLUSH_ITEMS` | code constant | `4096` | pending-item threshold for one `create_embeddings` call; checked only after a document's inputs are appended, so a flush can exceed it | `chunking/config.py:50`; `pipeline.py:292` |
| `EMBED_SAVE_VECTORS` | code constant | `50000` | vectors added since the last save before the index file rewrites mid-run; the run's end saves once more | `chunking/config.py:57`; `pipeline.py:300`, `331` |
| `FAISS_INDEX_FILE` | code constant | `faiss_index.bin` | declared but unread elsewhere; the real filename comes from the CLI argument or `Profile.index_path`, hardcoding the same literal separately | `chunking/config.py:59`; `docpipe/profile.py:324` |
| `--step` | CLI flag | none (merge, db, embed) | restrict the run to one of `merge`, `db`, `embed`, `enrich-bbox`, `enrich-page-source`, `enrich-caption` | `pipeline.py:358-369` |
| `--force` | CLI flag | off | merge: ignore the cache. db: delete and reinsert. embed: evict old vectors instead of skipping. enrich-*: re-derive already-answered rows. | `pipeline.py:371`; used throughout |
| `--profile` / `DOCPIPE_PROFILE` | CLI flag / env var | none / unset | supplies default `data_dir`, `db_path`, `index_path` when a positional argument is omitted | `profile.py:314-324`, `417`; `pipeline.py:370`, `393-395` |
| `--log-level` | CLI flag | `INFO` | logging level for the run | `pipeline.py:372-375`, `384` |
| `data_dir`, `db_path`, `index_path` | positional args | none (fall back to the profile's paths) | processed root, database path, index path | `pipeline.py:351-357`, `393-395` |

## Failure modes

Invalid JSON, or any other exception, in `merge_single` is caught by
`merge_batch`, logged, recorded as a failure for that directory, and the
batch continues (`merge.py:197`). A missing `visuals.json`
is not an error: the merge proceeds without enrichment and logs a warning
(`merge.py:106`). A failed atomic write of `document.json` deletes its `.part`
file and re-raises, leaving the previous cached file untouched
(`merge.py:136`). An `OSError` while stat-ing a directory during the cache
probe reads as uncached rather than propagating, so one bad entry does not
abort the batch (`merge.py:49`). A document with `sections.json` and no
`sections_refined.json` is left out of the merge, and so out of the database,
with one warning that names it and says to run the refinement
(`merge.py:168-177`).

A directory whose `Documents` row cannot be resolved during the db step is
skipped with a warning (`database.py:500`); reached during the embed step, it
contributes no inputs and is named in one end-of-run warning, so no GPU time
is spent on unownable vectors (`pipeline.py:250`, `321`). `enrich_bbox` and
`enrich_page_source` instead `continue` silently on the same case
(`database.py:594`, `196`), and `enrich_bbox` reads `sections.json` with a
plain `open()`/`json.load()`, no per-directory `try`/`except`
(`database.py:597`): a malformed file aborts the whole run rather than being
skipped for one document.

Listing a crop directory raises for anything but a missing directory: only
`FileNotFoundError` and `NotADirectoryError` read as "no crops", so an I/O or
permission error surfaces instead of silently dropping every VL input
(`chunking.py:49`). A table or figure with no (or empty) `path` is skipped with
a warning naming its id, rather than resolving to the containing directory
itself and embedding that (`chunking.py:175`, `209`). A section past
`SECTION_EMBED_MAX_WORDS` is truncated and the cut logged, since refinement
should already have split it (`chunking.py:64`).

A model batch that raises inside `create_embeddings` is logged with its item
range, and its inputs are collected in an `Unembedded` tally by embedding type
and by document: nothing in the batch reaches the index or database, and the
other batches are finished. The stage then saves the index with the vectors
that were made and ends 1 with `Embedding incomplete: N input(s) of M
document(s) have no vector (type=n, ...); a rerun embeds them`
(`IncompleteIndex`, `embedding.py:268-273`; `pipeline.py:332`). Since no
`Embeddings` row was written for those inputs, the next run picks up exactly
them. The log line `Embedded %d new item(s) across %d/%d docs that had open
items; %d item(s) failed` says how many, and `Embedding complete` is logged
only for a whole index. `create_embeddings` called without a tally raises
`IncompleteIndex` itself once every batch has been tried. Inputs that an
embedder with `text_only` leaves out on purpose, the image-bearing ones, are
not failures, so an index built through the api still ends 0. Two cases are
not covered: a batch whose embedder returns fewer vectors than inputs is not
collected, it raises `IndexError` at the database write, after the vectors are
in the index, and the stage ends non-zero without saving; and the embed step
needs `faiss` at its start, the lazy import freeing only the import of the
package and of `create_embeddings`. A
record whose owner row cannot be resolved in `EmbeddingWriter.write` is skipped
and counted, though its vector is already indexed, and logged with per-type
counts (`database.py:908-914`); that is a warning and the stage still ends 0, and
since the record has no `Embeddings` row a rerun embeds it again and adds
another orphan vector. Writing for a `pdf_name` with no `Documents` row at
all writes nothing and logs an error naming the orphaned vector count
(`database.py:867-871`).

An `Embeddings` row whose `faiss_id` is absent from the loaded index, left by a
crash between a batch's write and the next index save, is dropped at the start
of every embed run and logged, so the item is redone (`database.py:734`). An
empty known-ids set is refused as a reconciliation base rather than read as
"nothing is embedded", since that would delete every `Embeddings` row
(`database.py:748`).

Unresolved `data_dir`, `db_path` or `index_path`, with no `--profile` given,
raises `SystemExit` naming the missing argument, before `run()` is called
(`pipeline.py:396`).

## Measured behaviour

Reading a merged `document.json` and querying the database cost 6.6 seconds per
document in the last full run, 91 of 184 minutes with every GPU idle, since
all 800 documents were prepared before the first batch embedded
(`pipeline.py:245`). That run's unbounded queue held roughly a million
`EmbeddingInput` records for 1078 plans, traced to an out-of-memory kill at 194
GB peak resident memory, the reason `EMBED_PREPARE_AHEAD` exists
(`chunking/config.py:40`).

A million 4096-dimensional vectors is roughly a 16 GB file; saving it once per
`EMBED_FLUSH_ITEMS` chunk cost roughly 244 full rewrites over one build, every
one GPU-idle (`chunking/config.py:52`). The threshold is checked only after a
document's inputs are appended, so it can be exceeded: forty documents of a
thousand items each flush in chunks of 5000, not 4096
(`tests/test_embedding_batching.py:265`).

Two directories with no `Documents` row once put 1096 orphaned vectors into
the index, before the check that skips an unresolved directory existed
(`pipeline.py:256-259`; `database.py:861`).

Over one plan (Kassel), 15 of 89 tables were captioned with a rounding-footnote
sentence instead of their real title (`docpipe/captions.py:8`); across its
twelve titled target tables, 240 of 379 value tuples carried a year read off
another table's caption, and 88 of Kassel's 100 contested value identities were
exactly that (`captions.py:85`). Over the corpus's three plans with no text
layer, 23 of 169 tables resolved a title this way (`captions.py:116`).

Eleven plans have no PDF text layer, their pages rendered and transcribed by
a model instead; preprocessing through embedding runs unchanged, not
distinguishing the two kinds of plan (`database.py:171`; `schema.sql:31`).

`Sections` holds on the order of 134,000 rows, far more `Segments` beneath
them, why children go out one `executemany` per statement, not one `execute`
per row (`tests/test_database.py:81`). The corpus holds on the order of
85,000 crops, why `build_embedding_inputs` lists each directory once rather
than checking every path (`chunking.py:127`).

A plain `JOIN` instead of `CROSS JOIN` drives SQLite from the whole
`Embeddings` table on `owner_kind` alone, rescanning that partition per
document: 338 versus 1.1 milliseconds per document at corpus scale
(`database.py:47`).

Pulling a placeholder's referenced content directly into a section's embedding
text once made up 46% of the section-text corpus, before this changed to
substitute only the item's caption (`chunking.py:100`).

## Verification

Merge caching and failure handling:
`test_merge_batch_skips_cached_dirs_without_parsing`,
`test_merge_batch_force_remerges_cached_dir`,
`test_merge_batch_remerges_when_final_json_is_newer`,
`test_merge_batch_remerges_when_images_json_is_newer`,
`test_merge_batch_remerges_a_zero_byte_output`,
`test_merge_keeps_the_previous_output_when_the_write_fails`,
`test_merge_batch_reports_failure_for_invalid_final_json`,
`test_merge_batch_contains_an_unreadable_cache_entry`, and
`test_merge_preserves_segments_and_pages_and_enriches_media`.

Database insertion and resume bookkeeping:
`test_insert_sections_writes_pages_segments_sectionpages`,
`test_section_children_go_out_per_statement_not_per_row`,
`test_embeddings_roundtrip_and_clear`, `test_force_delete_cascades`,
`test_next_faiss_id_advances_past_max`,
`test_faiss_id_snapshot_survives_forced_content_delete`,
`test_per_document_lookups_drive_from_sections` (the query plan itself, not
only its results),
`test_existing_embeddings_covers_all_types_of_one_document_only`,
`test_one_writer_keeps_two_documents_block_ids_apart`,
`test_a_prepare_worker_asks_both_questions_over_one_connection`, and
`test_existing_embeddings_resolves_document_without_pdf_suffix`.

Caption and page-source backfill:
`test_page_source_is_additive_and_says_which_plans_a_model_read`,
`test_enrich_caption_takes_the_title_from_the_section_text`,
`test_enrich_caption_is_additive_and_never_runs_twice`, and
`test_enrich_caption_leaves_a_table_with_no_sentence_alone`.

Embedding-input construction:
`test_build_inputs_emits_vl_only_for_crops_on_disk`,
`test_build_inputs_reads_each_crop_directory_once`,
`test_build_inputs_does_not_hide_an_unreadable_crop_directory`, and
`test_build_inputs_survives_a_missing_crop_directory`.

Batching, flushing and crash recovery in the embed step:
`test_a_batch_no_longer_mixes_titles_with_full_sections`,
`test_every_input_is_embedded_exactly_once`,
`test_ids_stay_unique_and_contiguous`,
`test_text_and_image_inputs_stay_in_separate_batches`,
`test_the_db_writeback_opens_one_connection_for_the_whole_call`,
`test_the_gpus_start_before_the_last_document_is_read`,
`test_every_document_is_embedded_exactly_once_across_the_chunks`,
`test_the_index_is_not_written_once_per_flush`,
`test_a_crash_mid_run_never_loses_more_than_the_insurance_interval`,
`test_preparation_never_runs_the_whole_corpus_ahead_of_the_gpus`,
`test_the_window_still_yields_every_item_exactly_once`,
`test_rows_without_a_vector_in_the_index_are_dropped`,
`test_an_empty_index_never_wipes_the_table`, `test_a_clean_run_drops_nothing`,
`test_a_directory_without_a_documents_row_is_skipped_not_embedded`, and
`test_the_writer_shouts_instead_of_returning_in_silence`.

The api backend of the index build: `test_the_api_backend_hands_the_index_unit_vectors`,
`test_an_input_with_a_picture_is_left_out_and_gets_no_row`,
`test_an_embedder_that_takes_pictures_gets_the_input_that_carries_one`,
`test_a_vector_of_another_size_never_reaches_the_index`,
`test_the_backend_setting_decides_and_the_api_needs_no_model`,
`test_the_query_side_setting_does_not_move_the_index_build`,
`test_a_hosted_embedding_provider_needs_no_address` and
`test_a_hosted_endpoint_that_says_not_now_is_asked_again`.

The embedding model wrapper: `test_the_result_comes_back_in_the_caller_order`,
`test_one_long_item_does_not_land_in_a_shard_of_short_ones`, and
`test_a_single_replica_needs_no_sharding`.

The bbox backfill: `test_insert_sections_writes_bbox`,
`test_ensure_bbox_columns_adds_and_is_idempotent`,
`test_enrich_bbox_backfills_without_touching_embeddings`, and
`test_enrich_bbox_default_skips_rows_already_set`.

## Modules

`__init__.py` carries the package docstring and re-exports `run` for library
callers. `__main__.py` binds a `--profile` from the command line into
`DOCPIPE_PROFILE`, then imports `pipeline` and calls `pipeline.main()`,
enabling `python -m docpipe.chunking`.

`config.py` holds the module's constants: `EMBEDDING_MODEL`, `EMBEDDING_DIM`
and `MAX_TOKEN_LENGTH` re-exported from `docpipe/embedding/config.py`, plus
`SECTION_EMBED_MAX_WORDS`, `EMBEDDING_BATCH_SIZE`, the `EMBED_*` tuning
constants, `FAISS_INDEX_FILE`, and the six embedding-type strings, imported by
every other module here; the embedding-model wrappers declare their own
constants instead.

`models.py` holds `MergeStats`, used only by `merge.py`.

`merge.py` implements the merge step, `merge_single` and `merge_batch`,
combining Stage 4 and Stage 5 output into `document.json` with an mtime cache.
Called by `pipeline.run()` and directly by `tests/test_merge.py`.

`database.py` is all SQLite access: section, table and image insertion, the
three `enrich-*` backfills, embedding-id bookkeeping (`EmbeddingWriter`,
`get_existing_embeddings`, `next_faiss_id`,
`drop_embeddings_missing_from_index`), and the bbox backfill. Called by
`pipeline.py`, by `embedding.py` through `EmbeddingWriter`, and by most of
`tests/test_database.py`, `tests/test_embedding_batching.py` and
`tests/test_segment_bbox.py`. Its docstring's claim that no schema copy is
checked in is stale: `docpipe/store/schema.sql` is a checked-in, code-applied
schema declaring `bbox`, `page_text_transcribed` and `caption_source`.

`chunking.py` builds one document's `EmbeddingInput` records: section, title,
table and figure inputs in text and VL form, replacing placeholders with
captions and capping oversized section text. Called by `pipeline.py`'s
`prepare()` and directly by `tests/test_chunking.py`.

`embedding.py` is the embed step: FAISS lifecycle (`load_or_create_index`,
`index_ids`, `save_index`, `remove_ids_from_index`, each importing `faiss` where
it uses it), `index_backend` and
`load_embedder` with the `ApiIndexEmbedder` it returns for the api backend, and
`create_embeddings`, which batches, embeds, allocates ids and writes the
database back for one flush, and `IncompleteIndex` and `Unembedded` for the
inputs a failed batch leaves without a vector. Called by `pipeline.py` and directly by
`tests/test_embedding_batching.py` and `tests/test_embedding_api_index.py`.

`qwen3_vl_embedding.py` is the embedding model wrapper: `Qwen3VLForEmbedding`
(hidden-state output head), `Qwen3VLEmbedder` (single-device embedding), and
`MultiGPUEmbedder`, a data-parallel wrapper sharding a `process()` call across
replicas by length and reassembling results in order. Called by
`embedding.py`'s `load_embedder` for corpus building, only when
`EMBEDDING_INDEX_BACKEND` is `local`, and by
`docpipe/embedding/local.py`'s `LocalEmbedder` for query-time embedding.
Exercised directly by `tests/test_multigpu_embedder.py`.

`pipeline.py` orchestrates merge, db and embed (or a single `--step`), owns the
CLI including `--profile` resolution and logging setup, and implements the
prepare/flush loop, `prepared_ahead` and `peak_rss_gb`, overlapping preparation
with GPU embedding. Entry point for `python -m docpipe.chunking` and library
callers of `run()`.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/chunking/__init__.py</code></summary>

__init__.py: Merges the preprocessing and visuals outputs, embeds
them, and indexes them.

Runs as a command line module:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db
      /path/to/faiss.index

</details>

<details>
<summary><code>docpipe/chunking/pipeline.py</code></summary>

pipeline.py: Orchestrates the chunkingandembedding stage: merge, then
the database step, then embedding.

Runs as a command line module:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db
      /path/to/faiss.index

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/chunking/merge.py</code></summary>

merge.py: Merges the preprocessing and imageprocessing outputs as
chunking's first step.

Replaces each table and figure in sections_refined.json with its
enriched counterpart from visuals.json, matched by item id, and
writes the result to document.json with an atomic replace. A
directory is cached and skipped on rerun once document.json is newer
than both inputs, unless force is set.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/chunking/database.py</code></summary>

database.py: Inserts sections, tables and images from merged data,
and writes FAISS embedding ids back to the database.

Documents themselves are populated by fileprocessing. The database
is the source of truth for what has been embedded and for FAISS id
allocation. Its schema lives only in the database file itself,
readable with `sqlite3 KWP.db .schema`: a checked-in copy of the
schema was removed because nothing read it, and an unchecked second
copy would only record what was once true.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/chunking/chunking.py</code></summary>

chunking.py: Builds embedding inputs from merged section data.

For each section, produces a text input and, when the section has a
title, a title input; for each table and figure, a text input and,
when its image file exists on disk, a vision-language input. Table
and figure placeholders inside a section's text are replaced by the
referenced item's caption before the section is embedded. A section
longer than the configured word budget is truncated, and the cut is
logged rather than left silent.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/chunking/embedding.py</code></summary>

embedding.py: Creates text and vision-language embeddings and builds
the FAISS index, as chunking's third step.

Every embedding lives in one FAISS IDMap(IndexFlatIP), keyed by
globally unique ids allocated from the database.

Where the vectors come from is EMBEDDING_INDEX_BACKEND: `local` runs the
model in this process on the visible GPUs; `api` asks an embeddings endpoint
and needs none. A setting of its own beside the query side's
EMBEDDING_BACKEND, because the two differ in a common setup: the index is
built once with the model on GPUs and queried through an endpoint ever
after. An endpoint takes text only, so with it the inputs that carry a
picture are left out and the index holds the text vectors of a corpus.

A batch the embedder could not serve leaves its inputs without a vector. The
other batches are finished first; the inputs left over are counted by
embedding type and by document, and the run ends with them named, not with
them forgotten.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
