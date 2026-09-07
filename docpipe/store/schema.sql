-- ===========================================================================
-- docpipe core schema — everything that holds for any PDF corpus.
--
-- A project adds its own tables through profiles/<name>/schema.sql; it must
-- not change the tables below. Per-document project fields belong in a 1:1
-- table of the profile's own (see profiles/kwp/schema.sql, "DocumentMeta"),
-- so core code never meets a column it does not know.
--
-- SQLite does not enforce foreign keys unless enabled per connection; the
-- application opens every connection with PRAGMA foreign_keys = ON.
--
-- Page provenance: a Section (= one retrieval chunk) may span several pages.
-- `SectionPages` lists the pages a chunk covers; `Segments` records the ordered
-- text / table / figure pieces inside a chunk, each tagged with its page, so a
-- retrieved chunk can be cited down to the exact page of each part.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS "Documents" (
    "id"          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The profile's stable identity for this document (KWP: the file name,
    -- AR6: the DOI). Distinct from `filename`, which is where the bytes live.
    "external_id" TEXT UNIQUE,
    -- Documents sharing a `group_key` are versions of the same work; the newest
    -- `published` is the current one (`is_current`=1) and every older one points
    -- at its predecessor via `supersedes`. The profile decides what groups
    -- (KWP: the municipality key, AR6: the DOI).
    "group_key"   TEXT,
    "filename"    TEXT NOT NULL UNIQUE,
    "published"   TEXT,
    "num_pages"   INTEGER,
    -- How many of this document's pages a MODEL read rather than the PDF.
    -- Eleven plans of the heat-plan corpus carry no text layer: their pages
    -- are rendered and transcribed, and from there everything runs unchanged.
    -- So their section text is itself a model reading, and so is every quote
    -- verified against it. NULL means nobody looked, 0 means the PDF had its
    -- own text.
    "page_text_transcribed" INTEGER,
    "added"       TEXT,
    "is_current"  INTEGER NOT NULL DEFAULT 1,
    "supersedes"  INTEGER REFERENCES "Documents"("id") ON DELETE SET NULL
);

-- One row per physical page of a document; referenced by the provenance tables.
CREATE TABLE IF NOT EXISTS "Pages" (
    "id"          INTEGER PRIMARY KEY AUTOINCREMENT,
    "document"    INTEGER NOT NULL REFERENCES "Documents"("id") ON DELETE CASCADE,
    "page_number" INTEGER NOT NULL,
    UNIQUE("document", "page_number")
);

-- A retrieval chunk.
CREATE TABLE IF NOT EXISTS "Sections" (
    "id"             INTEGER PRIMARY KEY AUTOINCREMENT,
    "document"       INTEGER NOT NULL REFERENCES "Documents"("id") ON DELETE CASCADE,
    "section_number" INTEGER NOT NULL,
    "title"          TEXT,
    "content"        TEXT,
    "page_number"    INTEGER,   -- first/primary page (denormalised convenience)
    UNIQUE("document", "section_number")
);

-- Which pages a section spans (m:n) → "this chunk covers pages X–Y".
CREATE TABLE IF NOT EXISTS "SectionPages" (
    "section" INTEGER NOT NULL REFERENCES "Sections"("id") ON DELETE CASCADE,
    "page"    INTEGER NOT NULL REFERENCES "Pages"("id")    ON DELETE CASCADE,
    PRIMARY KEY("section", "page")
);

-- Ordered content pieces inside a section, each tagged with its page → the
-- fine-grained provenance used to cite "which part of the chunk is on page N".
-- `bbox` holds the source-PDF geometry for coordinate-precise highlighting: a
-- JSON array of one or more [x0, y0, x1, y1] rectangles in PDF points, top-left
-- origin (the layout blocks' bbox from Stage 2/3). A text segment carries one
-- rect per constituent block; a table/figure carries its single region rect.
-- NULL when geometry is unknown. Display only — never embedded.
CREATE TABLE IF NOT EXISTS "Segments" (
    "id"      INTEGER PRIMARY KEY AUTOINCREMENT,
    "section" INTEGER NOT NULL REFERENCES "Sections"("id") ON DELETE CASCADE,
    "ordinal" INTEGER NOT NULL,
    "page"    INTEGER NOT NULL REFERENCES "Pages"("id") ON DELETE CASCADE,
    "kind"    TEXT NOT NULL CHECK ("kind" IN ('text', 'table', 'figure')),
    "ref"     TEXT,   -- block id for table/figure segments (e.g. p12_tbl0)
    "text"    TEXT,   -- raw text for text segments
    "bbox"    TEXT,   -- JSON [[x0,y0,x1,y1], …] in PDF points (top-left origin)
    UNIQUE("section", "ordinal")
);

CREATE TABLE IF NOT EXISTS "Tables" (
    "id"          INTEGER PRIMARY KEY AUTOINCREMENT,
    "section"     INTEGER NOT NULL REFERENCES "Sections"("id") ON DELETE CASCADE,
    "block_id"    TEXT,
    "path"        TEXT NOT NULL,
    "page_number" INTEGER,
    "caption"     TEXT,
    "markdown"    TEXT,
    "bbox"        TEXT   -- JSON [[x0,y0,x1,y1]] region in PDF points
);

CREATE TABLE IF NOT EXISTS "Images" (
    "id"          INTEGER PRIMARY KEY AUTOINCREMENT,
    "section"     INTEGER NOT NULL REFERENCES "Sections"("id") ON DELETE CASCADE,
    "block_id"    TEXT,
    "path"        TEXT NOT NULL,
    "page_number" INTEGER,
    "caption"     TEXT,
    "description" TEXT,
    "bbox"        TEXT   -- JSON [[x0,y0,x1,y1]] region in PDF points
);

-- One row per embedded vector. `faiss_id` is the id in the FAISS IDMap index.
CREATE TABLE IF NOT EXISTS "Embeddings" (
    "faiss_id"       INTEGER PRIMARY KEY,
    "embedding_type" TEXT NOT NULL,   -- section_text|section_title|table_text|table_vl|figure_text|figure_vl
    "owner_kind"     TEXT NOT NULL CHECK ("owner_kind" IN ('section', 'table', 'figure')),
    "owner_id"       INTEGER NOT NULL,
    UNIQUE("owner_kind", "owner_id", "embedding_type")
);

CREATE INDEX IF NOT EXISTS "idx_documents_group"   ON "Documents"("group_key");
CREATE INDEX IF NOT EXISTS "idx_pages_document"    ON "Pages"("document");
CREATE INDEX IF NOT EXISTS "idx_sections_document" ON "Sections"("document");
CREATE INDEX IF NOT EXISTS "idx_sectionpages_page" ON "SectionPages"("page");
CREATE INDEX IF NOT EXISTS "idx_segments_section"  ON "Segments"("section");
CREATE INDEX IF NOT EXISTS "idx_segments_page"     ON "Segments"("page");
CREATE INDEX IF NOT EXISTS "idx_tables_section"    ON "Tables"("section");
CREATE INDEX IF NOT EXISTS "idx_images_section"    ON "Images"("section");
CREATE INDEX IF NOT EXISTS "idx_embeddings_owner"  ON "Embeddings"("owner_kind", "owner_id");
