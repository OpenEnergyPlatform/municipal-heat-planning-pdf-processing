# The database

## Purpose

`docpipe/store` is the database layer the rest of the pipeline is built on:
one core schema of eight tables that describes any PDF corpus, plus room
for a profile to add tables of its own. `docpipe/store/schema.sql`'s header
states the split: a project adds tables through `profiles/<name>/schema.sql`,
applied after the core schema on the same connection, without changing
the tables the core defines. The package exposes two modules: `schema.py`
builds and applies both schemas onto one connection, and `documents.py` is
the only writer it exposes against `Documents`, registering a document and
computing which of several editions is current.

Three stages depend on this package, each differently.
[File processing](fileprocessing.md), stage 1, is the only stage that
writes a `Documents` row, calling `schema.apply(connection, profile)`
directly on a plain `sqlite3.connect(db_file)`
(`docpipe/ingest/pipeline.py:78` to `79`), not through this package's
`connect()` (see Method). [Chunking](chunking.md), stage 6, assumes that
schema exists, opening the same file through its own `database.py`'s
separate `connect()` and writing every other core table against it.
[Inference](inference.md) and the [app](app.md) read the finished corpus
back out through a third module, opened read-only. The seam is
deliberate: `upsert_document_meta` builds its `INSERT` from whatever keys
a caller hands it, so core code never learns a project's column names,
and a typo in a profile's field reaches SQLite as a plain error.

## Position in the pipeline

| | |
|---|---|
| In | `DOCPIPE_PROFILE`, or a `Profile` object, for its optional `schema.sql`; the document, section, table, image and embedding values file processing and chunking write |
| Out | one SQLite database at whatever path it is opened at: the eight core tables, plus whichever tables the active profile adds |
| Resumes on | reopening an already-built database is a no-op (see Method); a caller resumes by checking what it already holds, not by anything this package tracks |
| Needs | no served model, no GPU: a filesystem path, and a `Profile` object for a profile's own tables |

`docpipe/store` is not one of the numbered links in
[how the parts fit together](../pipeline.md); several stages depend on it,
as they do on [core](core.md), without it appearing as a numbered link.

## Method

### Building the schema

`core_sql()` reads `docpipe/store/schema.sql` verbatim (`schema.py:30` to
`31`); `profile_sql(profile)` does the same for `Profile.schema_sql`
(`docpipe/profile.py:93` to `96`), returning an empty string if the file
or profile is absent (`schema.py:34` to `37`). `apply()` turns
`PRAGMA foreign_keys = ON` (see Configuration), then runs `BEGIN; <core
sql> <profile sql> COMMIT;` in one `executescript` call, core first
(`schema.py:40` to `43`); every statement is `CREATE TABLE
IF NOT EXISTS`, so re-applying to an already-built database changes
nothing (`test_apply_is_idempotent`, `tests/test_store.py:42` to `45`).
Core first lets a profile table (kwp's `DocumentMeta`) carry a foreign
key into `Documents`; the core schema references no profile column.
`tables(connection)` (`schema.py:56` to `58`) returns the
set of table names `sqlite_master` reports for the open connection. No
production code calls it; tests use it to check what `apply()` built,
such as `test_core_alone_creates_only_core_tables` and
`test_profile_adds_its_own_tables` (`tests/test_store.py:23` to `32`) and
`test_works_without_a_profile` (`tests/test_ingest.py:234`).

### Opening a database

`connect(path, profile)` (`schema.py:46` to `53`) creates `path`'s parent
directory if missing, opens the file, and calls `apply()`
(`test_connect_creates_the_file`, `tests/test_store.py:69` to `73`). It
is the only `connect()` that applies the schema; no production code
calls it (see Purpose), only `test_connect_creates_the_file`
(`tests/test_store.py:71`). Two later modules define narrower
connections against the same file: chunking's
(`docpipe/chunking/database.py:97` to `108`) adds a busy timeout but
never calls `apply()`; inference's (`docpipe/inference/db.py:21` to
`33`) opens a `mode=ro` URI so the app can never take a write lock (see
Configuration).

Closing a connection is left to whoever opened it; this package tracks
no handle. File processing's `with sqlite3.connect(db_file) as
connection:` (`docpipe/ingest/pipeline.py:78`) commits on exit but does
not close it. Chunking's `connect()` is closed by at least ten call
sites: `EmbeddingWriter.close()` (`docpipe/chunking/database.py:803` to
`804`); `_worker_connection`, closing a thread's previous connection
before opening a replacement (`docpipe/chunking/database.py:122` to
`126`); and eight `with closing(connect(db_path)) as conn:` blocks in
`enrich_page_source`, `enrich_caption`, `update_database`, `enrich_bbox`,
`clear_embedding_ids`, `get_document_faiss_ids`,
`drop_embeddings_missing_from_index` and `next_faiss_id`
(`docpipe/chunking/database.py:184`, `244`, `481`, `580`, `683`, `704`,
`743` and `766`). The app caches inference's `connect_readonly()`
connection in a Streamlit `@st.cache_resource`
(`scripts/inference_app/app.py:65` to `67`) and never closes it.

### Registering one document

`document_exists(filename, connection)` (`documents.py:29` to `32`) is what
file processing checks first; a hit skips the download and quality gate.
`add_document(...)` (`documents.py:35` to `50`) is a plain
`INSERT ... RETURNING id`, no `ON CONFLICT`, so a repeated filename or
`external_id` raises `sqlite3.IntegrityError`
(`test_external_id_is_unique`, `tests/test_store.py:62` to `66`). When
`meta` is given, `add_document` calls `upsert_document_meta`
(`documents.py:53` to `68`), building an `INSERT ... ON CONFLICT(document)
DO UPDATE` from whatever keys `values` carries.

### Linking versions

`link_document_versions(connection)` (`documents.py:71` to `102`)
recomputes which document is current for every `group_key` on every
call, safe to re-run after one more version is registered
(`test_idempotent`, `tests/test_document_versions.py:84` to `91`). It
orders every document with a `group_key` by
`group_key, COALESCE(published, ''), id` (`documents.py:85` to `92`)
into `itertools.groupby`, which only merges adjacent rows, so order
determines correctness. Within a group, the newest `published` gets
`is_current = 1`; each older row gets `is_current = 0` and `supersedes`
set to its predecessor (`test_three_versions_chain`,
`tests/test_document_versions.py:52` to `62`). A document with no
`group_key`, or alone in its own, stays current with `supersedes` left
`NULL` (`test_document_without_group_key_untouched`,
`tests/test_document_versions.py:75` to `81`).

Group membership is a profile's choice: `kwp` uses a municipality's
`ags`, or the smallest among several sharing one PDF
(`profiles/kwp/source.py:99` and `187`), so editions chain together;
`scenarios` sets `group_key` equal to `external_id`
(`profiles/scenarios/source.py:130`), itself `UNIQUE` on `Documents`
(`docpipe/store/schema.sql:22`), so none of its documents ever share one.

## Data model

### The core tables

`Documents` (`docpipe/store/schema.sql:18` to `41`) carries identity and
versioning:

| Column | Meaning |
|---|---|
| `id` | primary key |
| `external_id` | the profile's stable identity (`kwp`: the filename; `scenarios`: the DOI, or a crawl slug); `UNIQUE` |
| `group_key` | ties versions of one work together; group semantics are the profile's choice (see Method) |
| `filename` | where the PDF's bytes live; `NOT NULL`, `UNIQUE` |
| `published` | the profile's publish date, an 8-digit `YYYYMMDD` string, sorted lexically by `link_document_versions` |
| `num_pages` | page count, filled by file processing |
| `page_text_transcribed` | pages a model read instead of the PDF's own text; `NULL` unknown, `0` all native; written by chunking's `enrich-page-source`, never by this package |
| `added` | the date file processing registered the row, `YYYYMMDD` |
| `is_current` | 1 for the newest document in its group, computed by `link_document_versions` |
| `supersedes` | the id of the document this one replaces, or `NULL`; self-reference, `ON DELETE SET NULL` |

The other seven core tables hang off `Documents`, directly or through
`Sections`, written by chunking's `database.py`, not by this
package:

| Table | Columns | Role |
|---|---|---|
| `Pages` | `id`, `document` (FK), `page_number` | one physical page; `UNIQUE(document, page_number)` |
| `Sections` | `id`, `document` (FK), `section_number`, `title`, `content`, `page_number` | one retrieval chunk; `UNIQUE(document, section_number)` |
| `SectionPages` | `section` (FK), `page` (FK) | pages a chunk spans, many to many |
| `Segments` | `id`, `section` (FK), `ordinal`, `page` (FK), `kind`, `ref`, `text`, `bbox` | ordered text/table/figure pieces of a section, page-tagged; `kind` `CHECK`-constrained; `UNIQUE(section, ordinal)` |
| `Tables` | `id`, `section` (FK), `block_id`, `path`, `page_number`, `caption`, `markdown`, `bbox`, `caption_source` | one detected table, crop path, Markdown transcription |
| `Images` | `id`, `section` (FK), `block_id`, `path`, `page_number`, `caption`, `description`, `bbox`, `caption_source` | one detected figure, crop path, prose description |
| `Embeddings` | `faiss_id` (PK), `embedding_type`, `owner_kind`, `owner_id` | one FAISS vector; `owner_kind` `CHECK`-constrained; `UNIQUE(owner_kind, owner_id, embedding_type)` |

`bbox` is a JSON array of source-PDF rectangles, `NULL` when unknown,
display-only, never embedded (`docpipe/store/schema.sql:69` to `75`).
`caption_source` records what a later backfill did to the stored
caption: `stage` kept, `section_text` replaced, `NULL` untouched
(`docpipe/store/schema.sql:88` to `92`); this package writes neither.
`Embeddings.owner_id` is polymorphic, pointing at a `Sections`, `Tables` or
`Images` row depending on `owner_kind`, so it carries no real foreign key,
the one core table `ON DELETE CASCADE` does not reach (see Failure modes).

The schema also declares nine indexes, one per foreign key or lookup
column, including `idx_embeddings_owner` on
`Embeddings("owner_kind", "owner_id")` (`docpipe/store/schema.sql:126` to
`134`; see Measured behaviour).

### The profile tables

| Profile | Table | Columns | Role |
|---|---|---|---|
| `kwp` | `OrganisationUnits` | `id`, `name`, `state` | one administrative unit above a municipality |
| `kwp` | `Municipalities` | `id`, `name`, `ags`, `organisation_unit` (FK) | one municipality, keyed by its official `ags` |
| `kwp` | `DocumentMeta` | `document` (PK, FK), `organisation_unit` (FK), `municipality_ags` | the plan's per-document fields |
| `kwp` | `MunicipalityMeta` | `ags` (PK, FK), 29 further columns | the KWW sheet's fields, copied verbatim (`profiles/kwp/config.py`, `MUNICIPALITY_META_COLUMNS`, counted) |
| `scenarios` | `DocumentMeta` | `document` (PK, FK), `doi`, `title`, `year`, `venue`, `is_oa`, `scenario_count` | the publication's per-document fields |
| `scenarios` | `Scenarios` | `id`, `ar6_id` (`UNIQUE`), `name` | one AR6 scenario |
| `scenarios` | `DocumentScenarios` | `document` (FK), `scenario` (FK) | publication-to-scenario link, many to many; up to 146 scenarios per publication, up to 3 publications per scenario (`profiles/scenarios/schema.sql:27` to `29`, comment) |

Both profiles name their own per-document table `DocumentMeta`, keyed one
to one on `document`; `add_document`/`upsert_document_meta` write into
whichever one is active, by column name alone. See
[kwp](../profiles/kwp.md) and [scenarios](../profiles/scenarios.md).

### Queries the other stages run

Reading the tables back out is not this package's job.

- Chunking's `database.py` writes and reads every table below `Documents`;
  four lookup queries, run once per document, decide what it already has
  embedded, all four `CROSS JOIN` from `Sections` into `Embeddings` rather
  than a plain `JOIN` (`docpipe/chunking/database.py:54` to `92`; see
  Measured behaviour).
- Inference's `db.py` opens the database read-only, mirroring those
  lookups at retrieval time and turning a retrieved
  `(owner_kind, owner_id)` pair, or a placeholder id such as `p17_img1`,
  into citable text (`get_candidate_faiss_ids`, `fetch_owner_content`,
  `request_item`; `docpipe/inference/db.py:35` to `256`).
- Version linking determines what later stages read: extraction (stage 7)
  and the app's document picker both select `is_current = 1` documents by
  default, so a superseded document is never harvested or shown, even
  when named explicitly; the app labels a row `(aktuell)` or `(alt)`
  (`docpipe/extraction/runner.py:3810` to `3829`, docstring;
  `docpipe/inference/catalog.py:61` to `83`).

## Configuration

| name | kind | default | effect | where |
|---|---|---|---|---|
| `DOCPIPE_PROFILE` / `--profile` | environment variable / CLI flag | unset / none | selects which profile's `schema.sql` `apply()` layers on the core schema | `docpipe/profile.py:124` to `142` (env var, `load_profile`) and `172` to `190` (`--profile`, `add_profile_argument`/`resolve_profile`) |
| `PRAGMA foreign_keys` | fixed connection pragma | `ON` | enables foreign-key enforcement, off by default in SQLite, so `ON DELETE CASCADE`/`SET NULL` fire | `docpipe/store/schema.py:42`; re-set independently by `docpipe/chunking/database.py:100` |
| `PRAGMA busy_timeout` | fixed pragma, chunking's own `connect()` only | 30000 ms | a reader waits for a write lock instead of failing, needed once embedding began preparing documents while writing batches | `docpipe/chunking/database.py:97` to `108` |
| `CORE_TABLES` | module constant | the 8 core table names, as a tuple | names which tables belong to the core, not a profile; used by tests | `docpipe/store/schema.py:26` to `27` |

## Failure modes

- A malformed profile `schema.sql` makes `apply()`'s `executescript` call
  raise immediately inside `connect()`; a profile with no `schema.sql` is
  not an error, `profile_sql()` returns an empty string for it
  (`docpipe/store/schema.py:34` to `37`).
- `add_document` has no upsert path (see Method); file processing avoids
  the resulting `sqlite3.IntegrityError` by calling `document_exists()`
  first, but nothing in this package enforces that order.
- `apply()` only ever adds a table it does not find; a column added to an
  existing table's definition, as `bbox`, `page_text_transcribed` and
  `caption_source` all were, needs a hand-written `ALTER TABLE` against a
  database built earlier. This package carries no such migration; the
  three retrofits (`_ensure_bbox_columns`, `_ensure_page_source_column`,
  `_ensure_caption_source_column`) live in `docpipe/chunking/database.py`
  and run only when that module opens the connection, so a database
  opened only via this package or inference is never retrofitted. A
  missing `bbox` column then raises `sqlite3.OperationalError`, which
  `docpipe/inference/db.py`'s `section_segments_geo` catches, returning
  bbox-less segments from the older `section_segments` query and leaving
  the phrase-search fallback to its caller
  (`scripts/inference_app/app.py:537` to `555`).
- `Embeddings.owner_id` carries no foreign key, so deleting a document's
  `Sections` rows never cascades to its `Embeddings` rows; those, and the
  FAISS vectors they name, are left for chunking's force path to clear.
- `upsert_document_meta` assumes the active profile defines a
  `DocumentMeta` table; a profile without one that still passes metadata
  to `add_document` fails with SQLite's "no such table" error.

## Measured behaviour

- The `CROSS JOIN` pattern in chunking's four per-document lookup queries
  stops SQLite driving the query from the whole `Embeddings` table on
  `owner_kind` alone; a plain `JOIN` was measured at 338 ms against
  1.1 ms per document at corpus scale
  (`docpipe/chunking/database.py:46` to `51`, comment).
- The corpus holds on the order of 134,000 `Sections` rows, with far more
  `Segments` beneath them (`tests/test_database.py:80` to `81`,
  docstring). A 150-child test fixture goes out as four `executemany`
  calls, one per child table (`tests/test_database.py:92` to `95`,
  comment and assertion).
- Two processed directories with no `Documents` row put 1,096 dead
  vectors into the FAISS index in one run
  (`docpipe/chunking/pipeline.py:225` to `228`, comment). The embed step
  now checks for a document id before embedding, instead of writing
  vectors no `Embeddings` row can resolve and repeating that work next
  run (`docpipe/chunking/database.py:849` to `859`, comment).
- Eleven plans in the heat-plan corpus carry no PDF text layer; their
  `page_text_transcribed` count is filled by a model reading the
  rendered page instead of the PDF's own text
  (`docpipe/store/schema.sql:31` to `37`, comment).

## Verification

- `test_core_alone_creates_only_core_tables`,
  `test_profile_adds_its_own_tables`,
  `test_documents_carries_no_project_columns`, `test_apply_is_idempotent`
  and `test_connect_creates_the_file`: `apply()` with no profile creates
  exactly the eight core tables, `kwp` adds its own on top, `Documents`
  never gains a profile column, a second `apply()` call does not raise,
  and `connect()` creates a missing parent directory
  (`tests/test_store.py:23` to `45` and `69` to `73`).
- `test_foreign_keys_are_enforced`, `test_document_meta_follows_its_document`
  and `test_external_id_is_unique`: a `Sections` row against a
  nonexistent document, a `Documents` deletion, and a repeated
  `external_id` behave as promised (`tests/test_store.py:48` to `66`).
- Six tests cover `link_document_versions`: one document, two, three in a
  chain, two independent groups, no group at all, and a second call
  changing nothing (`tests/test_document_versions.py:33` to `91`).
- `test_per_document_lookups_drive_from_sections` and
  `test_force_delete_cascades`: chunking's per-document lookups plan
  through `Sections` first, and deleting a document's content empties every
  child table (`tests/test_database.py:172` to `184` and `118` to `125`).

## Modules

`docpipe/store/__init__.py` re-exports the package's public surface,
`apply`, `connect`, `core_sql`, `profile_sql` and `tables`, from
`schema.py`.

`docpipe/store/schema.py` implements the five functions `__init__.py`
re-exports (see Method for what each does). `connect()` is exercised
only by `test_connect_creates_the_file` (`tests/test_store.py:71`); no
production stage calls it (see Purpose and Method). Outside this
package and its own tests, `apply()` is called only by
`profiles/kwp/migrate_profile_split.py`, against an existing
pre-refactoring database. Nine test files call it directly to build a
database for a test: `tests/conftest.py`'s `kwp_db` fixture,
`tests/test_store.py`, `tests/test_document_versions.py`,
`tests/test_ingest.py`, `tests/test_kwp_source.py`,
`tests/test_migrate_convoy_group_keys.py`,
`tests/test_migrate_profile_split.py`, `tests/test_scenarios_catalog.py`
and `tests/test_scenarios_source.py`.

`docpipe/store/documents.py` holds `document_exists`, `add_document`,
`upsert_document_meta` and `link_document_versions` (see Purpose).
Called by [file processing](fileprocessing.md)'s
`docpipe/ingest/pipeline.py`, by
`profiles/kwp/migrate_convoy_group_keys.py`'s call to
`link_document_versions` after repairing a group key, and by
`profiles/scenarios/store.py`, whose `upsert_publication_meta` wraps
`upsert_document_meta`.

`docpipe/store/schema.sql` carries no docstring; it is the core schema
every table and column above draws on, applied by `schema.py`.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/store/__init__.py</code></summary>

__init__.py: Exposes the database layer, its core schema, its
profile schema, and the queries run over them.

</details>

<details>
<summary><code>docpipe/store/schema.py</code></summary>

schema.py: Builds a database from the core schema plus a profile's
own schema.

The core tables (Documents, Pages, Sections, SectionPages, Segments,
Tables, Images, Embeddings) are the same for every corpus. A profile
adds its own entities and its per-document fields through its own
schema.sql. apply() runs both scripts against one connection inside
one transaction, core first and then the profile's, so a profile's
tables can reference the core tables but not the other way round.
connect() opens the database file, creating its parent directory and
applying both schemas if needed, and is idempotent because every
statement is written IF NOT EXISTS.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/store/documents.py</code></summary>

documents.py: Writes and reads the core's Documents table.

Nothing here knows what a document is about; a project's own fields
go into DocumentMeta, whose columns the profile defines. add_document
inserts a row into Documents and, when metadata is given, upserts the
matching DocumentMeta row through upsert_document_meta.

link_document_versions marks which document is the current version of
each group and which it supersedes. Documents that share a group_key
are versions of the same work; what a group is stays the profile's
choice (a municipality for heat plans, a DOI for papers). Within a
group, the document with the newest published date is current
(is_current = 1); every older document is marked is_current = 0 and
points at the next-older document through supersedes, which is NULL
for the oldest. A document with no group_key, or alone in its group,
stays current with no predecessor. The function is idempotent: it
recomputes the whole grouping on every call.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
