"""migrate_v2: data-preserving migration of an old (FK-less) DB to the v2 schema."""
import pathlib
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "data" / "KWP.db.sql"

# Minimal subset of the old FK-less schema (the columns migrate_v2 reads).
_OLD_SCHEMA = """
CREATE TABLE "OrganisationUnits" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL, "state" TEXT, UNIQUE("name","state"));
CREATE TABLE "Municipalities" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL, "ags" INTEGER NOT NULL UNIQUE, "organisation_unit" INTEGER NOT NULL);
CREATE TABLE "Documents" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "organisation_unit" INTEGER, "filename" TEXT NOT NULL, "published" TEXT,
    "num_pages" INTEGER, "added" TEXT);
CREATE TABLE "Sections" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "document" INTEGER NOT NULL,
    "section_number" INTEGER NOT NULL, "page_number" INTEGER NOT NULL,
    "text_embedding" INTEGER, "title" TEXT, "title_embedding" INTEGER);
CREATE TABLE "Tables" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "section" INTEGER NOT NULL,
    "path" TEXT NOT NULL, "page_number" INTEGER, "caption" TEXT, "markdown" TEXT,
    "text_embedding" INTEGER, "image_embedding" INTEGER);
CREATE TABLE "Images" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "section" INTEGER NOT NULL,
    "path" TEXT NOT NULL, "page_number" INTEGER, "caption" TEXT, "description" TEXT,
    "text_embedding" INTEGER, "image_embedding" INTEGER);
"""


def _make_old_db(path, *, dangling_section=False):
    con = sqlite3.connect(path)
    con.executescript(_OLD_SCHEMA)
    con.execute("INSERT INTO OrganisationUnits (id, name, state) VALUES (1, 'OU Eins', 'NDS')")
    # one valid municipality + one whose OU (99) was deleted in the old DB (legal there).
    con.execute("INSERT INTO Municipalities (id, name, ags, organisation_unit) VALUES (1, 'Stadt A', 100, 1)")
    con.execute("INSERT INTO Municipalities (id, name, ags, organisation_unit) VALUES (2, 'Stadt B', 200, 99)")
    # one valid document + one with a dangling OU (88).
    con.execute("INSERT INTO Documents (id, organisation_unit, filename, num_pages) VALUES (1, 1, 'a.pdf', 5)")
    con.execute("INSERT INTO Documents (id, organisation_unit, filename, num_pages) VALUES (2, 88, 'b.pdf', 3)")
    con.execute("INSERT INTO Sections (id, document, section_number, page_number, title, text_embedding) "
                "VALUES (1, 1, 0, 2, 'Bestand', 1000)")
    con.execute("INSERT INTO Tables (id, section, path, page_number, text_embedding) "
                "VALUES (1, 1, 'images/p2_tbl0.png', 2, 1001)")
    con.execute("INSERT INTO Images (id, section, path, page_number, image_embedding) "
                "VALUES (1, 1, 'images/p2_img0.png', 2, 1002)")
    if dangling_section:
        # a Section pointing at a non-existent Document — unreconcilable, must abort.
        con.execute("INSERT INTO Sections (id, document, section_number, page_number, title) "
                    "VALUES (2, 999, 0, 1, 'Orphan')")
    con.commit()
    con.close()


def test_migration_preserves_data_and_reconciles_dangling_org_refs(tmp_path, capsys):
    from data import migrate_v2

    old = tmp_path / "old.db"
    new = tmp_path / "new.db"
    _make_old_db(old)

    migrate_v2.migrate(old, new, SCHEMA)
    assert new.exists()

    con = sqlite3.connect(new)
    con.execute("PRAGMA foreign_keys = ON")
    # No integrity violations remain.
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    # Data preserved.
    assert con.execute("SELECT count(*) FROM Documents").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM Municipalities").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM Sections").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM Embeddings").fetchone()[0] == 3
    # Dangling Document OU nulled (lossless).
    assert con.execute("SELECT organisation_unit FROM Documents WHERE id = 2").fetchone()[0] is None
    # Dangling Municipality repointed to a real (placeholder) OU.
    repointed = con.execute("SELECT organisation_unit FROM Municipalities WHERE id = 2").fetchone()[0]
    assert con.execute("SELECT count(*) FROM OrganisationUnits WHERE id = ?", (repointed,)).fetchone()[0] == 1
    # Pages/SectionPages derived from old page numbers.
    assert con.execute("SELECT page_number FROM Pages WHERE document = 1").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM SectionPages").fetchone()[0] == 1
    con.close()


def test_migration_never_mutates_the_old_db(tmp_path):
    from data import migrate_v2

    old = tmp_path / "old.db"
    new = tmp_path / "new.db"
    _make_old_db(old)
    before = old.read_bytes()
    migrate_v2.migrate(old, new, SCHEMA)
    assert old.read_bytes() == before


def test_migration_cleans_up_partial_file_on_failure(tmp_path):
    from data import migrate_v2

    old = tmp_path / "old.db"
    new = tmp_path / "new.db"
    _make_old_db(old, dangling_section=True)  # unreconcilable FK violation

    with pytest.raises(SystemExit):
        migrate_v2.migrate(old, new, SCHEMA)
    # The half-built file must be removed so a corrected re-run is not blocked.
    assert not new.exists()
