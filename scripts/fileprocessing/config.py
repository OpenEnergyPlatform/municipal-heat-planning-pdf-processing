"""
Constants and the fallback database schema for the fileprocessing module.
"""

EXCEL_SHEET = "Datensatz Status quo KWP"

# Municipalities whose KWW PDF link is broken and for which a correct PDF was
# sourced by hand. Keyed by Gemeindeschlüssel → the local filename to use
# instead of the KWW link. The file must be placed in the data dir by hand; it
# is never downloaded. (Previously the "Ersetzte Datei" column in our own copy
# of the Excel; the KWW export does not carry it.)
PDF_OVERRIDES = {
    1051011: "waermeplan_brunsbuettel_20241210.pdf",             # Brunsbüttel
    1051072: "waermeplan_marne_20241104.pdf",                    # Marne
    1053032: "waermeplan_geesthacht_20241230.pdf",              # Geesthacht
    1061046: "waermeplan_itzehoe_20240930.pdf",                  # Itzehoe
    3352011: "waermeplan_cuxhaven_20251106.pdf",                 # Cuxhaven
    3359038: "waermeplan_stade_20250327_komprimierte_version.pdf",  # Stade
    7143041: "waermeplan_selters_20250711.pdf",                  # Krümmel
    7143044: "waermeplan_selters_20250711.pdf",                  # Marienrachdorf
    7143045: "waermeplan_selters_20250711.pdf",                  # Maroth
    7143046: "waermeplan_selters_20250711.pdf",                  # Maxsain
    7143056: "waermeplan_selters_20250711.pdf",                  # Nordhofen
    7143064: "waermeplan_selters_20250711.pdf",                  # Rückeroth
    7143066: "waermeplan_selters_20250711.pdf",                  # Schenkelberg
    7143067: "waermeplan_selters_20250711.pdf",                  # Selters (Westerwald)
    7143085: "waermeplan_selters_20250711.pdf",                  # Wölferlingen
    8116012: "waermeplan_bissingen_an_der_teck_2024q1.pdf",      # Bissingen an der Teck
}

DATABASE_SCHEMA = """
BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "Documents" (
	"id"	INTEGER NOT NULL UNIQUE,
	"organisation_unit"	INTEGER,
	"filename"	TEXT NOT NULL,
	"published" TEXT,
	"num_pages" INTEGER,
	"added" TEXT,
	"municipality_ags" INTEGER,
	"is_current" INTEGER NOT NULL DEFAULT 1,
	"supersedes" INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "Images" (
	"id"	INTEGER NOT NULL UNIQUE,
	"section"	INTEGER NOT NULL,
	"path"	TEXT NOT NULL,
	"page_number"	INTEGER,
	"caption"	TEXT,
	"description"	TEXT,
	"text_embedding"	INTEGER,
	"image_embedding"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "Municipalities" (
	"id"	INTEGER NOT NULL UNIQUE,
	"name"	TEXT NOT NULL,
	"ags"	INTEGER NOT NULL UNIQUE,
	"organisation_unit"	INTEGER NOT NULL,
	UNIQUE("name", "ags", "organisation_unit"),
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "OrganisationUnits" (
	"id"	INTEGER NOT NULL UNIQUE,
	"name"	TEXT NOT NULL,
	"state" TEXT,
	UNIQUE("name", "state")
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "Sections" (
	"id"	INTEGER NOT NULL UNIQUE,
	"document"	INTEGER NOT NULL,
	"section_number"	INTEGER NOT NULL,
	"page_number"	INTEGER NOT NULL,
	"text_embedding"	INTEGER,
	"title"	TEXT,
	"title_embedding"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "Tables" (
	"id"	INTEGER NOT NULL UNIQUE,
	"section"	INTEGER NOT NULL,
	"path"	TEXT NOT NULL,
	"page_number"	INTEGER,
	"caption"	TEXT,
	"markdown"	TEXT,
	"text_embedding"	INTEGER,
	"image_embedding"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);
COMMIT;
"""
