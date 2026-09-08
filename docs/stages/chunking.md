# 6. Chunking, embedding, indexing

| | |
|---|---|
| **In** | Per document: sections_refined.json + visuals.json (merge), document.json (db and embed); plus sections.json and the page-transcription report for the standalone enrich-* steps, and the existing DB/FAISS index for resume checks. |
| **Out** | document.json per PDF; Documents/Sections/SectionPages/Segments/Tables/Images/Embeddings rows in the SQLite database; vectors in the FAISS index file. |
| **Resumes on** | Each step treats its own prior output as the cache (document.json mtime, existing Sections rows, or an (embedding_type, section_index, item_id) already in Embeddings), and --force clears exactly that step's earlier work before redoing it. |

Stage 6 is where the pipeline's per-document JSON artifacts stop being files and become a corpus. Everything before it -- layout detection, text extraction, LLM refinement, image enrichment -- produces one JSON per PDF that only that PDF's own machinery can read. This stage merges those JSONs, writes their content into SQLite with page-level provenance, and embeds it into a FAISS index, which is what `docpipe.inference` actually queries downstream. Skip it and a plan sits fully processed and fully invisible: nothing before this stage is searchable, and nothing after it exists except through the two files this stage produces.

The module runs as three steps -- merge, db, embed -- each reading the previous step's output rather than the pipeline's raw stage outputs directly. `merge.py` reads `sections_refined.json` (Stage 4) and `visuals.json` (Stage 5) out of each PDF's output directory and writes `document.json`, replacing each table/figure's Stage-4 stub with its enriched counterpart from `visuals.json`, matched by block id. `database.py` reads that `document.json` and inserts `Sections`, `SectionPages`, `Segments`, `Tables` and `Images` rows for a `Documents` row that must already exist -- fileprocessing/ingest owns that table, this stage only fills in what hangs off it. `embedding.py` reads `document.json` again, through `chunking.build_embedding_inputs`, and writes `Embeddings` rows (`faiss_id`, `embedding_type`, `owner_kind`, `owner_id`) alongside the vectors themselves in the FAISS index file named on the command line. Three more standalone steps read narrower inputs and touch only the database: `enrich-bbox` reads Stage 3's `sections.json` for the geometry that refinement drops, `enrich-page-source` reads the preprocessing page-transcription report, and `enrich-caption` reads nothing but the database itself.

Three decisions inside this module are easy to get backwards. First, a `[p13_tbl0]`-style placeholder in a section's text is replaced with the table or figure's *caption*, never with its Markdown transcription or its VL description -- those are embedded separately as their own `table_text`/`table_vl`/`figure_text`/`figure_vl` vectors and retrieved as their own sources. Inlining the full content used to make up 46% of the whole section-text corpus, diluted every section vector, pushed the longest sections past the model's token limit, and promised content the section itself cannot deliver, since what an answering LLM later reads back is the stored section content, where the placeholder is still a placeholder. Second, `pipeline.py` prepares documents (reading their JSON, diffing against the DB) in a thread pool that runs concurrently with embedding rather than ahead of it, but bounds how far ahead it is allowed to get -- `EMBED_PREPARE_AHEAD = 32` documents. Letting `ThreadPoolExecutor.map` submit every document at once was measured, on this codebase, to prepare a whole run's worth of documents -- on the order of a million section texts -- into memory before the first GPU batch ran, which is what an earlier run's OOM kill at 194 GB traces back to. Third, the per-document lookup SQL in `database.py` uses `CROSS JOIN` where a plain `JOIN` would read the same, because a plain join lets SQLite drive the query from the whole `Embeddings` table instead of from the one document's `Sections` rows -- 338 ms instead of 1.1 ms per document at corpus scale. `test_database.py` asserts the query plan for exactly this reason.

The embed step's only external dependency is GPU time: `load_embedder` loads Qwen3-VL-Embedding-8B in bfloat16, one model replica per visible GPU, and nothing in this stage makes a network call. If a single embedding batch raises inside `create_embeddings`, the batch is logged and skipped rather than failing the run, and because no `Embeddings` row was written for those items, they are simply re-attempted on the next invocation -- a batch failure degrades to a resume, not a crash. Merge and db cost only disk and SQLite writes. A document with no `visuals.json` merges without enrichment, its tables and figures falling back to Stage 4's stubs with a warning logged, rather than failing outright.

Each step decides for itself what still needs doing, so resuming is mostly a matter of running the same command again. Merge treats an existing `document.json` as valid unless one of its two inputs has a newer mtime, because Stage 5 rewrites its JSON on every run including a fully cached one, and content comparison would have to reparse both files just to find out nothing changed. Db skips a document whose `Sections` rows already exist. Embed's resume lives in the database: `get_existing_embeddings` reads the `(embedding_type, section_index, item_id)` triples a document already has, and `build_embedding_inputs`'s output is filtered against that set before anything reaches a GPU. `--force` redoes the corresponding step: merge re-merges past its cache; db deletes a document's `Embeddings` rows explicitly, since they are polymorphic and carry no foreign key for a cascade to reach, then deletes `Sections`/`Pages` (whose children do cascade) and reinserts; embed clears a document's `Embeddings` rows and evicts its old ids from the FAISS index. Running `--force` across both `db` and `embed` needs the ids to evict read before the db step's delete removes the very rows that name them, which is why `pipeline.run` snapshots `get_document_faiss_ids` for every candidate up front in that combination. The three `enrich-*` steps use their own resume markers -- a `NULL` `bbox`, `page_text_transcribed`, or `caption_source` column -- and their own `--force`.

Several of the remaining checks exist because a specific run once failed with nothing in the log to explain it. `drop_embeddings_missing_from_index`, run at the start of every embed step, deletes `Embeddings` rows whose `faiss_id` is not actually present in the loaded index -- the gap a crash between a batch's DB write and the next index save leaves, which on resume would otherwise read as "already embedded" and make the item permanently unsearchable without a single error line. It refuses to run at all when the index it was handed holds zero vectors, since that is indistinguishable from a mistyped index path and would otherwise delete every embedding row in the database. `document_id()` is checked before a directory is embedded, so a processed directory with no matching `Documents` row is skipped rather than spending GPU time on vectors nothing can ever own -- two such directories once put 1,096 dead vectors into the index per run before this check existed, and `EmbeddingWriter.write` still logs a backstop warning for the case where a batch's owner row cannot be resolved even though its document is registered. A table or figure with an empty image path is skipped with a warning instead of silently resolving `output_dir / ""` back to the directory itself and embedding that as if it were the image. And merge's write is temp-file-plus-`os.replace`, with a zero-byte `document.json` treated as absent rather than cached, so a job killed mid-write cannot leave a truncated file that the next run's cache check accepts as finished.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/chunking/__init__.py`

chunking – Merge the preprocessing and visuals outputs, embed them, index them.

Usage:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db /path/to/faiss.index

### `docpipe/chunking/pipeline.py`

pipeline.py – Orchestration of the chunkingandembedding module: merge → db → embed.

CLI:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db /path/to/faiss.index

Author: Felix Vossel

### `docpipe/chunking/merge.py`

merge.py – Step 1: Merge preprocessing and imageprocessing outputs.

Author: Felix Vossel

### `docpipe/chunking/database.py`

database.py – Insert sections/tables/images from merged data, and write FAISS
embedding IDs back. Documents themselves are populated by fileprocessing.

The DB is the source of truth for what has been embedded and for FAISS id
allocation. Its schema lives in the file itself (`sqlite3 KWP.db .schema`):
the checked-in copy is gone, because nothing read it and a second copy of a
schema with no check against the first one only tells you what was true once.

Author: Felix Vossel

### `docpipe/chunking/chunking.py`

chunking.py – Build embedding inputs from merged section data.

Author: Felix Vossel

### `docpipe/chunking/embedding.py`

embedding.py – Step 3: Create text + VL embeddings and build the FAISS index.

All embeddings live in one FAISS IDMap(IndexFlatIP) keyed by globally unique
ids allocated from the DB.

Author: Felix Vossel

[Back to the index](../README.md)
