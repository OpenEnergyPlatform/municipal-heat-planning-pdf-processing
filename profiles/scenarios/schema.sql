-- ===========================================================================
-- Scenario literature — everything the core schema must not know about.
-- Applied after docpipe/store/schema.sql, on the same connection.
-- ===========================================================================

-- The project's per-document fields. `doi` is NULL for the agency reports and
-- roadmaps that have none; those are identified by the crawl's slug instead.
CREATE TABLE IF NOT EXISTS "DocumentMeta" (
    "document"       INTEGER PRIMARY KEY
                     REFERENCES "Documents"("id") ON DELETE CASCADE,
    "doi"            TEXT,
    "title"          TEXT,
    "year"           INTEGER,
    "venue"          TEXT,
    "is_oa"          INTEGER
);

-- Year is a declared facet.
CREATE INDEX IF NOT EXISTS "idx_documentmeta_year" ON "DocumentMeta"("year");
