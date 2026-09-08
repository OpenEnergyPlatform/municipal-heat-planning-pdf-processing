# The database

| | |
|---|---|
| **In** | Core `docpipe/store/schema.sql` plus the active profile's own `schema.sql` (via `Profile.schema_sql`), and the document/section/table/image values `docpipe.ingest` and `docpipe.chunking` pass into `documents.py`'s writers. |
| **Out** | One SQLite database per profile, at whatever path `connect()` is given: the core tables (`Documents`, `Pages`, `Sections`, `SectionPages`, `Segments`, `Tables`, `Images`, `Embeddings`) plus the profile's own (e.g. kwp's `DocumentMeta`). |
| **Resumes on** | `connect()`/`apply()` is idempotent (`IF NOT EXISTS`) so any stage can call it on every run; callers resume via `document_exists()` and the `Embeddings` table, and forcing a redo means deleting the document's `Documents` row (which cascades) plus, separately, its `Embeddings` rows and FAISS vectors, which do not cascade. |

`docpipe/store` is the database layer underneath the two stages that need to persist anything: `docpipe.ingest` (stage 1), which creates a `Documents` row for every PDF it takes in, and `docpipe.chunking` (stage 6), which writes that document's `Sections`, `Tables`, `Images` and `Embeddings` once refinement and image processing are done. `docpipe.inference` reads the same database back out when a question comes in against the corpus those two stages built. The module exists so a project only has to describe what is specific to it -- Kommunale Wärmepläne have municipalities, AR6 scenario documents do not -- while the tables that make retrieval possible are the same regardless of which profile is running.

The whole surface is small. `schema.py`'s `core_sql()` reads `docpipe/store/schema.sql`; `profile_sql()` reads the active profile's own `schema.sql` off `Profile.schema_sql`; `apply()` runs both against one `sqlite3.Connection` inside a single `BEGIN`/`COMMIT`; and `connect(path, profile)` is what a stage actually calls -- it creates the parent directory if needed, opens the SQLite file at `path`, and applies the schema before handing back the connection. The core schema defines eight tables, the `CORE_TABLES` tuple: `Documents`, `Pages`, `Sections`, `SectionPages`, `Segments`, `Tables`, `Images`, `Embeddings`. A profile adds whatever is its own on top -- for kwp that includes `DocumentMeta`, the 1:1 table `documents.py` writes a project's per-document fields into. `documents.py` is the only writer this package exposes against the core tables: `document_exists`, `add_document`, `upsert_document_meta`, and `link_document_versions`.

The first decision worth knowing before touching either file is the order `apply()` builds its script in: core first, profile second, in the same transaction. That is what lets a profile's `CREATE TABLE` carry a foreign key into `Documents` or `Sections`, while nothing in `schema.sql` or `documents.py` ever references a column the core does not define -- `upsert_document_meta` builds its `INSERT ... ON CONFLICT` from whatever keys happen to be in the `values` dict it is handed, so the core genuinely never reads a project's column names. The edge that falls out of this: a typo'd field name in a profile's call does not fail against a known schema, it fails as a plain SQLite error against a table the core never looks inside.

The second is that `apply()` is meant to run on every single stage invocation, not once at setup time -- every `CREATE TABLE` and `CREATE INDEX` in `schema.sql` is `IF NOT EXISTS`, so opening an already-populated database re-applies the same schema and changes nothing. It is not a migration tool, though: adding a column to `Documents` needs a hand-written `ALTER TABLE`, because `IF NOT EXISTS` against a table that already exists in an older shape silently does nothing. The other thing `apply()` does before touching the schema is issue `PRAGMA foreign_keys = ON`, once per connection, because SQLite does not turn that on by default. Every `ON DELETE CASCADE` and `ON DELETE SET NULL` in `schema.sql` depends on a connection having come from this module's `connect()` rather than a bare `sqlite3.connect()` opened somewhere else.

The third is in `link_document_versions()`. It recomputes the entire `is_current`/`supersedes` chain on every call instead of touching only new rows, which is exactly what makes it safe to re-run after one more version of a plan is added. It orders `Documents` by `group_key, published, id` before feeding the rows to `itertools.groupby`, and that ordering is load-bearing rather than incidental: `groupby` only merges rows that are already adjacent, so dropping or reordering that clause produces silently wrong groups instead of an error. A document with no `group_key`, or the only one in its group, stays current with `supersedes` left `NULL` -- not chained to a predecessor that does not exist.

Nothing here costs a model, a GPU, or the network. The only external dependency `connect()` has is the profile object it is given. If a profile's `schema.sql` is missing or malformed, `apply()` fails immediately inside `connect()`, before a stage has opened a PDF or a vLLM connection -- a fast, cheap failure at the very start of a run rather than a corrupted state discovered after a GPU has already spent time on it.

The module keeps no stamp files of its own; it is the record other stages check to resume. Stage 1 calls `document_exists(filename)` before downloading a PDF, and stage 6 checks `Embeddings` before re-embedding a section, table, or image, so anything already recorded there is skipped on the next run. To force a document to be reprocessed, delete its `Documents` row: `ON DELETE CASCADE` on `Pages`, `Sections`, `SectionPages`, `Segments`, `Tables`, and `Images` takes the rest of it with it, and the `UNIQUE` constraints on `filename` and `external_id` free up so `add_document` can reinsert. `Embeddings` is the exception -- its `owner_id` points at a `Section`, a `Table`, or an `Image` depending on `owner_kind`, so it cannot carry a single foreign key and is not cascaded. Deleting a document's sections leaves its embedding rows, and the FAISS vectors they name, behind. Those need to be cleared separately.

What the schema defends against on its own, without relying on the application code above it to get things right: `UNIQUE(filename)` and `UNIQUE(external_id)` on `Documents` stop the same PDF being ingested twice (`add_document` has no upsert path, so skipping the `document_exists` check first just raises a constraint error); `UNIQUE(document, section_number)`, `UNIQUE(document, page_number)`, `UNIQUE(section, ordinal)`, and `UNIQUE(owner_kind, owner_id, embedding_type)` stop a duplicate row landing at the same logical position; and the `CHECK` constraints on `Segments.kind` and `Embeddings.owner_kind` reject a value outside their fixed vocabulary before it reaches a query written to assume one of the three. `page_text_transcribed` on `Documents` is a provenance flag rather than a constraint: eleven plans in the heat-plan corpus carry no text layer, so their pages were rendered and read by a model instead of extracted from the PDF, and this column is how a later reader can tell that a section's content -- and every quote checked against it -- came from that model reading rather than from the document's own text.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/store/__init__.py`

Database layer: core schema, profile schema, and the queries over them.

### `docpipe/store/schema.py`

schema.py – Build a database from the core schema plus a profile's own.

The core tables are the same for every corpus; the profile adds its entities
and its per-document fields. Both are applied to one connection, in that
order, so the profile can reference core tables but not the other way round.

Author: Felix Vossel

### `docpipe/store/documents.py`

documents.py – The core's writes against the Documents table.

Nothing here knows what a document is about; the project's own fields go into
DocumentMeta, whose columns the profile defines.

Author: Felix Vossel

[Back to the index](../README.md)
