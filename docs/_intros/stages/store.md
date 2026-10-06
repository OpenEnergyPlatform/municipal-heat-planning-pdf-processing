## Purpose

`docpipe/store` is the database layer the rest of the pipeline is built on:
one core schema of nine tables that describes any PDF corpus, plus room
for a profile to add tables of its own. `docpipe/store/schema.sql`'s header
states the split: a project adds tables through `profiles/<name>/schema.sql`,
applied after the core schema on the same connection, without changing
the tables the core defines. The package exposes two modules: `schema.py`
builds and applies both schemas onto one connection, brings an older
database forward, and keeps the `Meta` table, and `documents.py` is
the only writer it exposes against `Documents`, registering a document,
recording which bytes it is, and computing which of several editions is
current.

Three stages depend on this package, each differently.
[File processing](fileprocessing.md), stage 1, is the only stage that
writes a `Documents` row, calling `schema.apply(connection, profile)`
directly on a plain `sqlite3.connect(db_file)`
(`docpipe/ingest/pipeline.py:122` to `123`), not through this package's
`connect()` (see Method). [Chunking](chunking.md), stage 6, assumes that
schema exists, opening the same file through its own `database.py`'s
separate `connect()` and writing every other core table against it; it
also records the embedding model in `Meta` (see Data model).
[Inference](inference.md) and the [app](app.md) read the finished corpus
back out through a third module, opened read-only. The seam is
deliberate: `upsert_document_meta` builds its `INSERT` from whatever keys
a caller hands it, so core code never learns a project's column names,
and a typo in a profile's field reaches SQLite as a plain error.

## Position in the pipeline

| | |
|---|---|
| In | `DOCPIPE_PROFILE`, or a `Profile` object, for its optional `schema.sql`; the document, section, table, image and embedding values file processing and chunking write |
| Out | one SQLite database at whatever path it is opened at: the nine core tables, plus whichever tables the active profile adds |
| Resumes on | reopening a database of the current format is a no-op, and an older one only gains what it lacks (see Method); a caller resumes by checking what it already holds, not by anything this package tracks |
| Needs | no served model, no GPU: a filesystem path, and a `Profile` object for a profile's own tables |

`docpipe/store` is not one of the numbered links in
[how the parts fit together](../pipeline.md); several stages depend on it,
as they do on [core](core.md), without it appearing as a numbered link.

## Method

### Building the schema

`core_sql()` reads `docpipe/store/schema.sql` verbatim (`CORE_SCHEMA`,
`schema.py:41` to `42`); `profile_sql(profile)` does the same for
`Profile.schema_sql` (`docpipe/profile.py:279` to `288`: the profile's own
`schema.sql`, else that of the nearest profile it extends), returning an
empty string if the file or profile is absent (`schema.py:45` to `48`).
`apply()` turns `PRAGMA foreign_keys = ON` (see Configuration), runs `BEGIN;
<core sql> <profile sql> COMMIT;` in one `executescript` call, core first,
and then calls `migrate()` (`schema.py:51` to `55`; see Bringing an older
database forward). Every statement of both scripts is `CREATE TABLE IF NOT
EXISTS` or `CREATE INDEX IF NOT EXISTS`, so re-applying to an already-built
database creates nothing (`test_apply_is_idempotent`,
`tests/test_store.py:42` to `45`). Core first lets a profile table (kwp's
`DocumentMeta`) carry a foreign key into `Documents`; the core schema
references no profile column.

`tables(connection)` (`schema.py:222` to `224`) returns the set of table
names `sqlite_master` reports for the open connection, and
`columns(connection, table)` (`schema.py:70` to `72`) the set of column names
`PRAGMA table_info` reports for one table. Inside the package `meta` and
`note_embedding` use `tables()` to ask whether `Meta` and `Embeddings` exist
yet, and `migrate` uses `columns()`. Outside it `columns()` is called by
`transcribed_documents` in `docpipe/extraction/trust.py` and by the default
profile's catalog (`_meta_columns` in `docpipe/builtin/default/catalog.py`),
while nothing outside the package calls `tables()` but tests, which use it
to check what `apply()` built, such as
`test_core_alone_creates_only_core_tables` and
`test_profile_adds_its_own_tables` (`tests/test_store.py:23` to `32`) and
`test_works_without_a_profile` (`tests/test_ingest.py:234`).

### Bringing an older database forward

`FORMAT` (`schema.py:35`, currently 1) counts the shape of the core tables
and is raised whenever that shape changes. A database carries it as `PRAGMA
user_version`, and one made before the counter existed reads 0.
`ADDED_COLUMNS` (`schema.py:37` to `38`) lists every `(table, column, type)`
a later format added: `Documents.sha256` and `Documents.bytes`.
`migrate(connection)` (`schema.py:91` to `102`) reads the version the
database had, runs `ALTER TABLE ... ADD COLUMN` for each listed column that
`columns()` does not report, sets `user_version` to `FORMAT` if it was
lower, commits, and returns the version it found. It only ever adds, a
column or a table: nothing an older reader looks at is renamed or removed,
so the code that wrote a database and this code can both read it. It never
lowers a `user_version` that is higher than `FORMAT`.

`apply()` ends with `migrate()`, so a database is brought forward when it is
opened for writing through `apply()`, which `connect()` and file processing's
`ingest` both do. The existing rows keep everything they had and get `NULL`
in the new columns, and a second call finds nothing to add and returns
`FORMAT` (`test_a_database_from_before_is_brought_up_and_loses_nothing`,
`tests/test_identity.py:38` to `55`). Chunking's own `connect()` never calls
`apply()` or `migrate()` (see Failure modes).

`add_missing_column(connection, table, column, kind)` (`schema.py:75` to `89`)
is the same idea for a table of a profile. `CREATE TABLE IF NOT EXISTS` leaves
a table as it was made, so a source that fills a column the table was made
without adds it first: the function adds the column where the table is there
and lacks it, and returns whether it did. A table that is not there is left
alone, so that the write that needed it is the one to fail. The folder source
uses it for `DocumentMeta.created`, so a database made before the date was kept
gets the column on the first run; a profile that extends the built-in one with
a whole `DocumentMeta` table of its own and uses the folder source has to
declare `created` itself.

A reader brings nothing forward. Opened through `readonly_uri` it cannot
alter a table, and the code that reads what a later format added is written
to find it missing: `content_of` returns `(None, None)` when the column or
the row is not there, `meta` returns an empty dict when there is no `Meta`
table, `embedding_mismatch` then says nothing, and `note_documents` in
`docpipe/extraction/runner.py` counts no recorded document when its
`SELECT` fails. The promise, stated in `tests/test_identity.py`'s docstring,
is that a database written before any of this stays readable; an older
database says less, and nothing is compared against it or refused.

### Opening a database

`connect(path, profile)` (`schema.py:212` to `219`) creates `path`'s parent
directory if missing, opens the file, and calls `apply()`
(`test_connect_creates_the_file`, `tests/test_store.py:69` to `73`). It
is the only `connect()` that applies the schema; no production code
calls it (see Purpose). `test_connect_creates_the_file`
(`tests/test_store.py:71`) exercises it, and `tests/test_app_pages.py` uses
it to build a small database. Two later modules define narrower
connections against the same file: chunking's
(`docpipe/chunking/database.py:98` to `108`) adds a busy timeout but
never calls `apply()` or `migrate()`; inference's
(`docpipe/inference/db.py:24` to `36`) opens a `mode=ro` URI so the app can
never take a write lock (see Configuration). That address is built in one
place, `readonly_uri(path)` in `schema.py`, which the package re-exports:
the path is made absolute and percent-encoded. Written into an address as
it is, a `#` in a path starts a fragment and a `?` a query, and SQLite
opens another file than the one that was named. Every read-only opening
goes through it: inference's, the extraction stage's, the word index's, the
`kg.py` of `kwp` and of `scenarios`, and that of `docpipe doctor`.

Closing a connection is left to whoever opened it; this package tracks
no handle. File processing's `with sqlite3.connect(db_file) as
connection:` (`docpipe/ingest/pipeline.py:122`) commits on exit but does
not close it. Chunking's `connect()` is closed by at least ten call
sites: `EmbeddingWriter.close()` (`docpipe/chunking/database.py:813` to
`814`); `_worker_connection`, closing a thread's previous connection
before opening a replacement (`docpipe/chunking/database.py:123` to
`127`); and eight `with closing(connect(db_path)) as conn:` blocks in
`enrich_page_source`, `enrich_caption`, `update_database`, `enrich_bbox`,
`clear_embedding_ids`, `get_document_faiss_ids`,
`drop_embeddings_missing_from_index` and `next_faiss_id`
(`docpipe/chunking/database.py:192`, `252`, `493`, `590`, `693`, `714`,
`753` and `776`). The app caches inference's `connect_readonly()`
connection in a Streamlit `@st.cache_resource`
(`get_db` in `docpipe/app/app.py`) and never closes it.

### Registering one document

`document_exists(filename, connection)` (`documents.py:59` to `62`) is what
file processing checks first; a hit skips the download and quality gate.
`add_document(...)` (`documents.py:65` to `80`) is a plain
`INSERT ... RETURNING id`, no `ON CONFLICT`, so a repeated filename or
`external_id` raises `sqlite3.IntegrityError`
(`test_external_id_is_unique`, `tests/test_store.py:62` to `66`). When
`meta` is given, `add_document` calls `upsert_document_meta`
(`documents.py:83` to `98`), building an `INSERT ... ON CONFLICT(document)
DO UPDATE` from whatever keys `values` carries.

`add_document` does not touch `sha256` or `bytes`. Three helpers in
`documents.py` carry them: `file_sha256(path)` (`documents.py:30` to `37`)
returns the sha256 and the size of a file, read in 1 MiB pieces;
`content_of(filename, connection)` (`documents.py:40` to `49`) returns what
a row holds, `(None, None)` for a row or a database that predates the
record; and `set_content(filename, sha256, size, connection)`
(`documents.py:52` to `56`) writes them. File processing's `register` calls
`note_content` (`docpipe/ingest/pipeline.py`) for every document it meets
whose file is on disk: a new row gets its record at once, and a row from
before the record gets it the first time the document is seen again. A row
that has a record is held against the size of the file as it lies in the
data directory; a different size logs a warning that this is not the file
that was registered, and nothing is stopped or overwritten, so a file
edited to the same length is not seen
(`test_another_file_under_the_old_name_is_said_and_nothing_stops`,
`tests/test_identity.py:75` to `95`). The extraction stage reads the record
back: `note_documents` in `docpipe/extraction/runner.py` puts each
document's `sha256` and `bytes` into the harvest's stamp (`stamp_record`,
key `document`), and `identity.tuple_id` in
`docpipe/extraction/identity.py` documents the name of a row's document as
that sha256, or the file name for a database that recorded none.

### Linking versions

`link_document_versions(connection)` (`documents.py:101` to `132`)
recomputes which document is current for every `group_key` on every
call, safe to re-run after one more version is registered
(`test_idempotent`, `tests/test_document_versions.py:84` to `91`). It
orders every document with a `group_key` by
`group_key, COALESCE(published, ''), id` (`documents.py:115` to `122`)
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

`Documents` (`docpipe/store/schema.sql:18` to `45`) carries identity,
versioning and the record of which bytes the file was:

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
| `sha256` | `TEXT`, the hex sha256 of the PDF file when file processing first recorded it; `NULL` for a row not met since the record existed; filled by `note_content` through `set_content` (see Method) |
| `bytes` | `INTEGER`, the size of that file in bytes, the figure `note_content` compares the file on disk with; `NULL` where `sha256` is |

`sha256` and `bytes` are the two columns a later format added, so a database
built before them gets both from `migrate` (see Bringing an older database
forward).

`Meta` (`docpipe/store/schema.sql:47` to `55`) is the table where a database
says what it is: one row per fact, `key` primary key and `value` text, a
record and never a gate. `set_meta(connection, values)` (`schema.py:201` to
`213`) creates the table if it is missing, upserts each key and commits,
storing values as text. `meta(connection)` (`schema.py:192` to `198`) reads
the whole table as a dict, empty for a database with no `Meta` table. The
only writer is `note_embedding` (`schema.py:117` to `159`), which chunking's
`note_embedding` in `docpipe/chunking/pipeline.py` calls on a plain
connection before it embeds anything; that is why `set_meta` creates the
table itself instead of relying on `apply()`. It records `embedding/model`,
`embedding/dim`, `embedding/backend`, `embedding/max_token_length` and
`docpipe/version`. Vectors of two models do
not compare, so when `Embeddings` already holds vectors and the model
differs, `note_embedding` raises `MixedIndex`, which names the recorded and the
configured model, before anything is written. With `allow_mixed` (chunking
passes `EMBEDDING_ALLOW_MIXED_INDEX`) the first model stays recorded, the new
one is appended to `embedding/also` (newline separated), and `note_embedding`
returns a sentence for the caller to log. An index with no vectors takes the
new model as the recorded one. A database that records no model cannot be
checked, whatever it holds: the configured model is recorded as the one that
built the index, and where vectors are held the returned sentence says nothing
proved them to be its.
`embedding_mismatch(connection, model)` (`schema.py:167` to `176`) is the
query side: a sentence when `model` is not the recorded `embedding/model`,
else `None`, which is also what a database that records no model gives.
`recorded_model(connection)` (`schema.py:162` to `164`) is the recorded model
or `None`, which the chat reads for its own notice. `dimension_mismatch(connection,
dim)` (`schema.py:179` to `189`) is the same question about the length of the
vectors: a sentence when queries are embedded to another length than
`embedding/dim`, else `None`, and `None` for a database that records no
dimension. The same name can be set to another length, and vectors of two
lengths do not compare either. `note_index_model` in
`docpipe/extraction/runner.py` logs the model sentence as a warning when a run
embeds its probes with another model than the index was built with (the
harvest, and `docpipe compile examples` under its own name), the
doctor reads both checks and the chat the model one
(`test_the_database_remembers_what_built_its_index_and_says_both`,
`test_the_length_of_the_vectors_is_compared_like_their_model` and
`test_a_database_without_a_table_of_vectors_holds_none`,
`tests/test_identity.py:276` to `346`). `embedding/also`, where an index went on
with another model, is not looked at by either check. The format is not a
`Meta` row: it is `PRAGMA user_version` (see Bringing an older database
forward).

Seven further core tables hang off `Documents`, directly or through
`Sections`, written by chunking's `database.py`, not by this
package:

| Table | Columns | Role |
|---|---|---|
| `Pages` | `id`, `document` (FK), `page_number` | one physical page; `UNIQUE(document, page_number)` |
| `Sections` | `id`, `document` (FK), `section_number`, `title`, `content`, `page_number` | one retrieval chunk; `UNIQUE(document, section_number)` |
| `SectionPages` | `section` (FK), `page` (FK) | pages a chunk spans, many to many |
| `Segments` | `id`, `section` (FK), `ordinal`, `page` (FK), `kind`, `ref`, `text`, `bbox` | ordered text/table/figure pieces of a section, page-tagged; `kind` `CHECK`-constrained; `UNIQUE(section, ordinal)` |
| `Tables` | `id`, `section` (FK), `block_id`, `path`, `page_number`, `caption`, `markdown`, `bbox`, `caption_source`, `qa` | one detected table, crop path, Markdown transcription, and what stage 5 measured of it |
| `Images` | `id`, `section` (FK), `block_id`, `path`, `page_number`, `caption`, `description`, `bbox`, `caption_source` | one detected figure, crop path, prose description |
| `Embeddings` | `faiss_id` (PK), `embedding_type`, `owner_kind`, `owner_id` | one FAISS vector; `owner_kind` `CHECK`-constrained; `UNIQUE(owner_kind, owner_id, embedding_type)` |

`bbox` is a JSON array of source-PDF rectangles, `NULL` when unknown,
display-only, never embedded (`docpipe/store/schema.sql:85` to `89`).
`caption_source` records what a later backfill did to the stored
caption: `stage` kept, `section_text` replaced, `NULL` untouched
(`docpipe/store/schema.sql:102` to `106`); this package writes neither.
`Tables.qa` is the JSON `{passed, coverage, coverage_assessed, duplication,
has_rows}` stage 5 measured of the transcription it kept, `NULL` for not
checked (a table of an older run, one read only as plain text, one never read),
and never a pass; chunking writes it with the table (see [chunking](chunking.md)).
`Embeddings.owner_id` is polymorphic, pointing at a `Sections`, `Tables` or
`Images` row depending on `owner_kind`, so it carries no real foreign key,
the one core table `ON DELETE CASCADE` does not reach (see Failure modes).

The schema also declares nine indexes, one per foreign key or lookup
column, including `idx_embeddings_owner` on
`Embeddings("owner_kind", "owner_id")` (`docpipe/store/schema.sql:145` to
`153`; see Measured behaviour). `Meta` has none, its key being its primary
key.

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
| `default` | `DocumentMeta` | `document` (PK, FK), `title`, `folder`, `created` | what the folder source knows about a document: the title in the PDF's own information dictionary, else the file name without its ending; the subfolder it was read from; and the PDF's creation date as far as it gives one (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`, `NULL` without one) (`docpipe/builtin/default/schema.sql`) |

Each of the three names its own per-document table `DocumentMeta`, keyed one
to one on `document`; `add_document`/`upsert_document_meta` write into
whichever one is active, by column name alone. A profile that extends
`default` and brings no `schema.sql` of its own gets the `default` one
(`Profile.schema_sql`); `kwp` and `scenarios` each bring their own. See
[kwp](../profiles/kwp.md) and [scenarios](../profiles/scenarios.md).

### Queries the other stages run

Reading the tables back out is not this package's job.

- Chunking's `database.py` writes and reads every table below `Documents`;
  four lookup queries, run once per document, decide what it already has
  embedded, all four `CROSS JOIN` from `Sections` into `Embeddings` rather
  than a plain `JOIN` (`docpipe/chunking/database.py:55` to `88`; see
  Measured behaviour).
- Inference's `db.py` opens the database read-only, mirroring those
  lookups at retrieval time and turning a retrieved
  `(owner_kind, owner_id)` pair, or a placeholder id such as `p17_img1`,
  into citable text (`get_candidate_faiss_ids`, `fetch_owner_content`,
  `request_item`; `docpipe/inference/db.py:66` to `287`).
- Version linking determines what later stages read: extraction (stage 7)
  and the app's document picker both select `is_current = 1` documents by
  default, so a superseded document is never harvested or shown, even
  when named explicitly; the app labels a row with the profile's own words
  for current and old, the `UI` entries `version_current` and `version_old`
  (`kwp` says `(aktuell)` and `(alt)`, the built-in profile and `scenarios`
  say `(current)` and `(old)`), and calls a document by `Profile.document_noun`,
  which is `"document"` unless a profile names its own, falling back to the
  `document_noun_fallback` entry only without a profile object or with an
  empty noun
  (`docpipe/extraction/runner.py:4888` to `4913`, docstrings;
  `docpipe/inference/catalog.py:70` to `75` and `93` to `103`). A profile
  that stands alone and words its own `UI` has to carry those three entries
  and the others `wording.UI_REQUIRED` lists, or the app and the picker raise
  a `LookupError` naming what is missing. The catalogs of the built-in profile
  and of `scenarios` print no tag after a name, so for them the words are
  reached only through the base `Catalog`.

## Configuration

| name | kind | default | effect | where |
|---|---|---|---|---|
| `DOCPIPE_PROFILE` / `--profile` | environment variable / CLI flag | unset / none | selects which profile's `schema.sql` `apply()` layers on the core schema | `docpipe/profile.py:350` to `373` (env var, `load_profile`), `410` to `413` (`--profile`, `add_profile_argument`) and `447` to `470` (`resolve_profile`) |
| `PRAGMA foreign_keys` | fixed connection pragma | `ON` | enables foreign-key enforcement, off by default in SQLite, so `ON DELETE CASCADE`/`SET NULL` fire | `docpipe/store/schema.py:53`; re-set independently by `docpipe/chunking/database.py:101` |
| `PRAGMA busy_timeout` | fixed pragma, chunking's own `connect()` only | 30000 ms | a reader waits for a write lock instead of failing, needed once embedding began preparing documents while writing batches | `docpipe/chunking/database.py:98` to `108` |
| `CORE_TABLES` | module constant | the 9 core table names, as a tuple | names which tables belong to the core, not a profile; used by tests | `docpipe/store/schema.py:27` to `28` |
| `FORMAT` / `PRAGMA user_version` | module constant / pragma | `1` / `0` on a database made before the counter | the shape of the core tables; `migrate` sets the pragma to `FORMAT` when it is lower | `docpipe/store/schema.py:35`, `91` to `102` |
| `ADDED_COLUMNS` | module constant | `Documents.sha256` (`TEXT`) and `Documents.bytes` (`INTEGER`) | the columns a later format added, which `migrate` adds to a database that lacks them | `docpipe/store/schema.py:37` to `38` |

## Failure modes

- A malformed profile `schema.sql` makes `apply()`'s `executescript` call
  raise immediately inside `connect()`; a profile with no `schema.sql` is
  not an error, `profile_sql()` returns an empty string for it
  (`docpipe/store/schema.py:45` to `48`).
- `add_document` has no upsert path (see Method); file processing avoids
  the resulting `sqlite3.IntegrityError` by calling `document_exists()`
  first, but nothing in this package enforces that order.
- `apply()` creates a table it does not find, and `migrate()` adds the
  columns in `ADDED_COLUMNS`, `Documents.sha256` and `Documents.bytes`. A
  column added to an existing table's definition that is not listed there,
  as `bbox`, `page_text_transcribed`, `caption_source` and `Tables.qa` all
  were, needs an `ALTER TABLE` against a database built earlier, and this
  package carries none for them: the four retrofits (`_ensure_bbox_columns`,
  `_ensure_page_source_column`, `_ensure_caption_source_column`,
  `_ensure_table_qa_column`) live in
  `docpipe/chunking/database.py` and run only inside `update_database`,
  `enrich_bbox`, `enrich_page_source` and `enrich_caption` (`_ensure_table_qa_column`
  in `update_database` alone), so a database
  that none of them has opened is never retrofitted. A missing `bbox` column
  then raises `sqlite3.OperationalError`, which
  `docpipe/inference/db.py`'s `section_segments_geo` catches, returning
  bbox-less segments from the older `section_segments` query and leaving
  the phrase-search fallback to its caller
  (`_pdf_link_for` in `docpipe/app/app.py`). A missing
  `page_text_transcribed` column is asked for, not tried:
  `transcribed_documents` in `docpipe/extraction/trust.py` reads `columns()`
  first and names no document for a database that predates it.
- `set_content` writes `sha256` and `bytes` with a plain `UPDATE`, so on a
  database that never went through `apply()` or `migrate()` it raises
  `sqlite3.OperationalError` (no such column), where `content_of` reports the
  same absence as `(None, None)`. File processing applies the schema before
  it registers anything, so the path is not taken there.
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
  (`docpipe/chunking/database.py:47` to `52`, comment).
- The corpus holds on the order of 134,000 `Sections` rows, with far more
  `Segments` beneath them (`tests/test_database.py:80` to `81`,
  docstring). A 150-child test fixture goes out as four `executemany`
  calls, one per child table (`tests/test_database.py:92` to `95`,
  comment and assertion).
- Two processed directories with no `Documents` row put 1,096 dead
  vectors into the FAISS index in one run
  (`docpipe/chunking/pipeline.py:256` to `259`, comment). The embed step
  now checks for a document id before embedding, instead of writing
  vectors no `Embeddings` row can resolve and repeating that work next
  run (`docpipe/chunking/database.py:861` to `866`, comment).
- Eleven plans in the heat-plan corpus carry no PDF text layer; their
  `page_text_transcribed` count is filled by a model reading the
  rendered page instead of the PDF's own text
  (`docpipe/store/schema.sql:31` to `37`, comment).

## Verification

- `test_core_alone_creates_only_core_tables`,
  `test_profile_adds_its_own_tables`,
  `test_documents_carries_no_project_columns`, `test_apply_is_idempotent`
  and `test_connect_creates_the_file`: `apply()` with no profile creates
  the core tables and none of a profile's, `kwp` adds its own on top,
  `Documents` never gains a profile column, a second `apply()` call does
  not raise, and `connect()` creates a missing parent directory
  (`tests/test_store.py:23` to `45` and `69` to `73`).
- `test_a_database_from_before_is_brought_up_and_loses_nothing`: a
  `Documents` table made without `sha256` and `bytes` reads as having no
  `Meta` and no content record, `apply()` sets `user_version` to `FORMAT`
  and adds both columns, the old row survives with `NULL` in them, a second
  `migrate()` returns `FORMAT`, and `set_meta` keeps one row per key, the
  later value winning (`tests/test_identity.py:38` to `55`).
- `test_a_new_document_is_registered_with_its_bytes` and
  `test_another_file_under_the_old_name_is_said_and_nothing_stops`: a new
  row gets the sha256 and size of its file; a row from before the record
  gets them once; the same file says nothing; another file under the same
  name logs a warning and leaves the record as it was
  (`tests/test_identity.py:63` to `95`).
- `test_the_database_remembers_what_built_its_index_and_says_both` and
  `test_a_database_without_a_table_of_vectors_holds_none`: `note_embedding`
  records the model, replaces it while `Embeddings` is empty or absent, and
  with vectors held raises `MixedIndex` and writes nothing, or, with the mixture
  allowed, keeps the first model, records the other under `embedding/also` and
  returns a sentence; `test_an_index_that_records_no_model_cannot_be_checked_and_says_so`
  holds that an index with vectors and no record cannot be checked and says so;
  `embedding_mismatch` is silent
  for the recorded model and for a database that records none, and
  `test_the_length_of_the_vectors_is_compared_like_their_model` holds
  `dimension_mismatch` to the same, naming both lengths where they differ
  (`tests/test_identity.py:276` to `346`).
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

`docpipe/store/__init__.py` re-exports six names from `schema.py`:
`apply`, `connect`, `core_sql`, `profile_sql`, `readonly_uri` and `tables`.
`columns`, `add_missing_column`, `migrate`, `meta`, `set_meta`,
`note_embedding`, `recorded_model`, `embedding_mismatch`,
`dimension_mismatch`, `FORMAT`, `ADDED_COLUMNS` and `CORE_TABLES` are read
from `docpipe.store.schema` directly.

`docpipe/store/schema.py` implements the six functions `__init__.py`
re-exports (see Method for what each does, and Opening a database for
`readonly_uri`) and the rest named above (see Bringing an older database
forward, and `Meta` under Data model). `connect()` is exercised
by `test_connect_creates_the_file` (`tests/test_store.py:71`) and used to
build a database in `tests/test_app_pages.py`; no
production stage calls it (see Purpose and Method). Outside this
package and its own tests, `apply()` is called only by
`ingest` in `docpipe/ingest/pipeline.py` and by
`profiles/kwp/migrate_profile_split.py`, against an existing
pre-refactoring database. Twelve test files call it directly to build a
database for a test: `tests/conftest.py`'s `kwp_db` fixture,
`tests/test_store.py`, `tests/test_document_versions.py`,
`tests/test_ingest.py`, `tests/test_kwp_source.py`,
`tests/test_migrate_convoy_group_keys.py`,
`tests/test_migrate_profile_split.py`, `tests/test_scenarios_catalog.py`,
`tests/test_scenarios_source.py`, `tests/test_identity.py`,
`tests/test_jsonl.py` and `tests/test_default_profile.py`.

`docpipe/store/documents.py` holds `document_exists`, `add_document`,
`upsert_document_meta`, `link_document_versions`, and the three that carry
a document's bytes: `file_sha256`, `content_of` and `set_content` (see
Purpose). Called by [file processing](fileprocessing.md)'s
`docpipe/ingest/pipeline.py`, by
`profiles/kwp/migrate_convoy_group_keys.py`'s call to
`link_document_versions` after repairing a group key, and by
`profiles/scenarios/store.py`, whose `upsert_publication_meta` wraps
`upsert_document_meta`.

`docpipe/store/schema.sql` carries no docstring; it is the core schema
every table and column above draws on, applied by `schema.py`.
