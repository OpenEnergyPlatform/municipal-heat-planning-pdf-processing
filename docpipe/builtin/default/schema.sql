-- ===========================================================================
-- What the folder source knows about a document. Applied after
-- docpipe/store/schema.sql, on the same connection.
--
-- A profile that extends this one and knows more about its documents writes
-- its own schema.sql with the whole table: its columns are then the ones its
-- source fills and its facets filter by.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS "DocumentMeta" (
    "document" INTEGER PRIMARY KEY
               REFERENCES "Documents"("id") ON DELETE CASCADE,
    -- the file name without its ending, until somebody knows a better one
    "title"    TEXT,
    -- the subfolder the file was read from; NULL for the folder itself
    "folder"   TEXT
);

CREATE INDEX IF NOT EXISTS "idx_documentmeta_folder" ON "DocumentMeta"("folder");
