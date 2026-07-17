-- ===========================================================================
-- KWP.db schema (v2) — relational model with foreign keys.
--
-- SQLite does NOT enforce foreign keys unless they are enabled per connection.
-- The application opens every connection with `PRAGMA foreign_keys = ON`
-- (see scripts/chunkingandembedding/database.py); enable it manually too when
-- inspecting the DB by hand.
--
-- Page provenance: a Section (= one retrieval chunk) may span several pages.
-- `SectionPages` lists the pages a chunk covers; `Segments` records the ordered
-- text / table / figure pieces inside a chunk, each tagged with its page, so a
-- retrieved chunk can be cited down to the exact page of each part.
-- ===========================================================================
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS "OrganisationUnits" (
    "id"     INTEGER PRIMARY KEY AUTOINCREMENT,
    "name"   TEXT NOT NULL,
    "state"  TEXT,
    UNIQUE("name", "state")
);

CREATE TABLE IF NOT EXISTS "Municipalities" (
    "id"                INTEGER PRIMARY KEY AUTOINCREMENT,
    "name"              TEXT NOT NULL,
    "ags"               INTEGER NOT NULL UNIQUE,
    "organisation_unit" INTEGER NOT NULL
                        REFERENCES "OrganisationUnits"("id") ON DELETE CASCADE,
    UNIQUE("name", "ags", "organisation_unit")
);

-- KWW source metadata for a municipality (one row per Municipality, keyed by
-- ags). Verbatim from the KWW "Status quo KWP" sheet, minus the corpus-identity
-- columns modelled elsewhere and the KWW-internal workflow fields. Populated by
-- the fileprocessing import (and its --backfill-meta step); orthogonal to
-- retrieval.
CREATE TABLE IF NOT EXISTS "MunicipalityMeta" (
    "ags" INTEGER PRIMARY KEY REFERENCES "Municipalities"("ags") ON DELETE CASCADE,
    "verbandsschluessel"        INTEGER,
    "landkreisschluessel"       INTEGER,
    "ars"                       INTEGER,
    "bundesland_kurz"           TEXT,
    "bundesland_lang"           TEXT,
    "verbandsname"              TEXT,
    "verbandstyp"               TEXT,
    "landkreis"                 TEXT,
    "textkennzeichen"           TEXT,
    "nki_foerderung"            TEXT,
    "konvoi_id"                 TEXT,
    "konvoimitgliedschaft"      TEXT,
    "stand_in_der_kwp"          TEXT,
    "einwohnendenzahl_gvz"      INTEGER,
    "einwohnergroesse"          INTEGER,
    "groesse_nach_wpg"          TEXT,
    "gemeindeflaeche_km2"       INTEGER,
    "bevoelkerungsdichte"       INTEGER,
    "link_waermeplan"           TEXT,
    "datum_veroeffentlichung"   TEXT,
    "jahr_veroeffentlichung"    INTEGER,
    "dienstleister"             TEXT,
    "aktualitaet"               TEXT,
    "vereinfachtes_verfahren"   TEXT,
    "verkuerzte_kwp"            TEXT,
    "pvs_id"                    INTEGER,
    "verbandsangehoerigkeit"    TEXT,
    "anzahl_mitgliedsgemeinden" INTEGER,
    "ew_verbandsgemeinden"      INTEGER
);

CREATE TABLE IF NOT EXISTS "Documents" (
    "id"                INTEGER PRIMARY KEY AUTOINCREMENT,
    "organisation_unit" INTEGER
                        REFERENCES "OrganisationUnits"("id") ON DELETE SET NULL,
    "filename"          TEXT NOT NULL UNIQUE,
    "published"         TEXT,
    "num_pages"         INTEGER,
    "added"             TEXT,
    -- Versioning: a plan can be re-published. Documents sharing a municipality
    -- (`municipality_ags`) are versions of the same plan; the newest published
    -- is the current one (`is_current=1`), older ones point to the version they
    -- replace via `supersedes`.
    "municipality_ags"  INTEGER,
    "is_current"        INTEGER NOT NULL DEFAULT 1,
    "supersedes"        INTEGER REFERENCES "Documents"("id") ON DELETE SET NULL
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
-- `bbox` columns below hold the source-PDF geometry for coordinate-precise
-- source highlighting: a JSON array of one or more [x0, y0, x1, y1] rectangles
-- in PDF points, top-left origin (the layout blocks' bbox from Stage 2/3). A
-- text segment carries one rect per constituent block; a table/figure carries
-- its single region rect. NULL when geometry is unknown. Display/provenance
-- only — orthogonal to retrieval (never embedded).
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
-- Replaces the previous *_embedding id columns on Sections/Tables/Images.
CREATE TABLE IF NOT EXISTS "Embeddings" (
    "faiss_id"       INTEGER PRIMARY KEY,
    "embedding_type" TEXT NOT NULL,   -- section_text|section_title|table_text|table_vl|figure_text|figure_vl
    "owner_kind"     TEXT NOT NULL CHECK ("owner_kind" IN ('section', 'table', 'figure')),
    "owner_id"       INTEGER NOT NULL,
    UNIQUE("owner_kind", "owner_id", "embedding_type")
);

-- Indexes on foreign-key / frequent-lookup columns.
CREATE INDEX IF NOT EXISTS "idx_municipalities_ou" ON "Municipalities"("organisation_unit");
CREATE INDEX IF NOT EXISTS "idx_documents_ou"      ON "Documents"("organisation_unit");
CREATE INDEX IF NOT EXISTS "idx_pages_document"    ON "Pages"("document");
CREATE INDEX IF NOT EXISTS "idx_sections_document" ON "Sections"("document");
CREATE INDEX IF NOT EXISTS "idx_sectionpages_page" ON "SectionPages"("page");
CREATE INDEX IF NOT EXISTS "idx_segments_section"  ON "Segments"("section");
CREATE INDEX IF NOT EXISTS "idx_segments_page"     ON "Segments"("page");
CREATE INDEX IF NOT EXISTS "idx_tables_section"    ON "Tables"("section");
CREATE INDEX IF NOT EXISTS "idx_images_section"    ON "Images"("section");
CREATE INDEX IF NOT EXISTS "idx_embeddings_owner"  ON "Embeddings"("owner_kind", "owner_id");

COMMIT;
