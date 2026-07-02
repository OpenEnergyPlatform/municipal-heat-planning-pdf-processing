"""
Configuration settings for file processing module.

This module contains constants and database schema definitions used throughout
the file processing pipeline for handling PDF documents and metadata.
"""

EXCEL_SHEET = "Datensatz Status quo KWP"

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
