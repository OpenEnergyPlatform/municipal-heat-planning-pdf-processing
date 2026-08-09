-- ===========================================================================
-- Kommunale Wärmeplanung — everything the core schema must not know about.
-- Applied after docpipe/store/schema.sql, on the same connection.
-- ===========================================================================

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

-- The project's per-document fields. This is the seam: the core carries
-- identity and versioning, everything municipal lives here.
CREATE TABLE IF NOT EXISTS "DocumentMeta" (
    "document"          INTEGER PRIMARY KEY
                        REFERENCES "Documents"("id") ON DELETE CASCADE,
    "organisation_unit" INTEGER
                        REFERENCES "OrganisationUnits"("id") ON DELETE SET NULL,
    "municipality_ags"  INTEGER
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

CREATE INDEX IF NOT EXISTS "idx_municipalities_ou" ON "Municipalities"("organisation_unit");
CREATE INDEX IF NOT EXISTS "idx_documentmeta_ou"   ON "DocumentMeta"("organisation_unit");
CREATE INDEX IF NOT EXISTS "idx_documentmeta_ags"  ON "DocumentMeta"("municipality_ags");
