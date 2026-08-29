-- ===========================================================================
-- AR6 scenario literature — everything the core schema must not know about.
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
    "is_oa"          INTEGER,
    "scenario_count" INTEGER
);

-- A scenario of the AR6 database. `ar6_id` is its id there, and the identity
-- the index links against; `id` is ours.
CREATE TABLE IF NOT EXISTS "Scenarios" (
    "id"     INTEGER PRIMARY KEY AUTOINCREMENT,
    "ar6_id" INTEGER NOT NULL UNIQUE,
    "name"   TEXT NOT NULL
);

-- Which publication documents which scenario. Many-to-many in both directions:
-- one publication documents up to 146 scenarios, and a scenario is documented
-- by up to three publications.
CREATE TABLE IF NOT EXISTS "DocumentScenarios" (
    "document" INTEGER REFERENCES "Documents"("id") ON DELETE CASCADE,
    "scenario" INTEGER REFERENCES "Scenarios"("id") ON DELETE CASCADE,
    PRIMARY KEY("document", "scenario")
);

-- The primary key already serves publication → scenarios; this is the other
-- direction ("who documents this scenario"). Year is a declared facet.
CREATE INDEX IF NOT EXISTS "idx_documentscenarios_scenario"
    ON "DocumentScenarios"("scenario");
CREATE INDEX IF NOT EXISTS "idx_documentmeta_year" ON "DocumentMeta"("year");
