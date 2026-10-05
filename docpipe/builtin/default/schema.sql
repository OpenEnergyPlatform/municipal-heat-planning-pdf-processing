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
    -- the title in the PDF's own information dictionary, else the file name
    -- without its ending
    "title"    TEXT,
    -- the subfolder the file was read from; NULL for the folder itself
    "folder"   TEXT,
    -- the creation date in the same dictionary, as far as it gives one
    -- (YYYY, YYYY-MM or YYYY-MM-DD); NULL when it gives none
    "created"  TEXT
);

CREATE INDEX IF NOT EXISTS "idx_documentmeta_folder" ON "DocumentMeta"("folder");
