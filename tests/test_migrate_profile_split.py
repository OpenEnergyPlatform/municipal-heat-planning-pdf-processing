"""Bringing a pre-refactoring corpus database up to the core schema."""
import sqlite3

import pytest

from profiles.kwp import migrate_profile_split as mig

OLD_SCHEMA = """
CREATE TABLE "OrganisationUnits" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" TEXT NOT NULL, "state" TEXT,
    UNIQUE("name", "state"));
CREATE TABLE "Municipalities" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" TEXT NOT NULL,
    "ags" INTEGER NOT NULL UNIQUE, "organisation_unit" INTEGER NOT NULL);
CREATE TABLE "Documents" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "organisation_unit" INTEGER REFERENCES "OrganisationUnits"("id"),
    "filename" TEXT NOT NULL UNIQUE, "published" TEXT, "num_pages" INTEGER,
    "added" TEXT, municipality_ags INTEGER,
    is_current INTEGER NOT NULL DEFAULT 1, supersedes INTEGER);
CREATE TABLE "Sections" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT, "document" INTEGER NOT NULL,
    "section_number" INTEGER NOT NULL, "title" TEXT, "content" TEXT,
    "page_number" INTEGER, UNIQUE("document", "section_number"));
INSERT INTO OrganisationUnits (id, name, state) VALUES (1, 'GVV Besigheim', 'BW');
INSERT INTO Documents (id, organisation_unit, filename, published, municipality_ags)
     VALUES (1, 1, 'waermeplan_a.pdf', '20240101', 8118007),
            (2, 1, 'waermeplan_b.pdf', '20250101', 8118008);
INSERT INTO Sections (document, section_number, title, content)
     VALUES (1, 0, 'Bestandsanalyse', 'Text');
"""


@pytest.fixture
def old_db(tmp_path):
    path = tmp_path / "KWP.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.commit()
    return path


def test_the_old_shape_is_recognised(old_db):
    with sqlite3.connect(old_db) as con:
        state = mig.inspect(con)
    assert not state["migrated"]
    assert state["documents"] == 2
    assert state["legacy"] == ["organisation_unit", "municipality_ags"]
    assert "add Documents.group_key, fill it from municipality_ags" in " ".join(mig.plan(state))


def test_identity_and_versioning_are_carried_over(old_db):
    with sqlite3.connect(old_db) as con:
        mig.migrate(con)
        rows = con.execute(
            "SELECT filename, external_id, group_key FROM Documents ORDER BY id").fetchall()
    # the file name WAS the identity, so a re-import still recognises the document
    assert rows[0] == ("waermeplan_a.pdf", "waermeplan_a.pdf", "8118007")
    assert rows[1] == ("waermeplan_b.pdf", "waermeplan_b.pdf", "8118008")


def test_the_municipal_fields_move_into_documentmeta(old_db):
    with sqlite3.connect(old_db) as con:
        mig.migrate(con)
        meta = con.execute("SELECT document, organisation_unit, municipality_ags "
                           "FROM DocumentMeta ORDER BY document").fetchall()
    assert meta == [(1, 1, 8118007), (2, 1, 8118008)]


def test_nothing_else_is_touched(old_db):
    with sqlite3.connect(old_db) as con:
        before = con.execute("SELECT title, content FROM Sections").fetchall()
        mig.migrate(con)
        after = con.execute("SELECT title, content FROM Sections").fetchall()
        # the legacy columns stay: they are nullable and cannot block an insert
        assert "municipality_ags" in mig.columns(con, "Documents")
    assert before == after


def test_running_it_twice_changes_nothing(old_db):
    with sqlite3.connect(old_db) as con:
        mig.migrate(con)
        first = con.execute("SELECT id, external_id, group_key FROM Documents").fetchall()
        again = mig.migrate(con)
        second = con.execute("SELECT id, external_id, group_key FROM Documents").fetchall()
        assert mig.inspect(con)["migrated"]
    assert first == second
    assert again == {"external_id": 0, "group_key": 0, "document_meta": 0}


def test_a_migrated_database_accepts_a_new_document(old_db):
    """The point of the exercise: the new writer can insert again."""
    from docpipe.store import documents as store_docs

    with sqlite3.connect(old_db) as con:
        mig.migrate(con)
        doc_id = store_docs.add_document(
            filename="waermeplan_c.pdf", external_id="waermeplan_c.pdf",
            group_key="8118009", published="20260101", num_pages=42,
            added="2026-08-07", meta=None, connection=con)
        row = con.execute("SELECT external_id, group_key, num_pages FROM Documents "
                          "WHERE id = ?", (doc_id,)).fetchone()
    assert row == ("waermeplan_c.pdf", "8118009", 42)


def test_the_index_is_not_built_over_a_string_literal(old_db):
    """SQLite treats a double-quoted identifier that matches no column as a
    STRING. Applying the core schema to a table without `group_key` therefore
    builds an index over the constant 'group_key' — after which the column
    reads back as that word and `WHERE group_key IS NULL` matches nothing."""
    with sqlite3.connect(old_db) as con:
        mig.migrate(con)
        values = [r[0] for r in con.execute("SELECT group_key FROM Documents")]
        assert values == ["8118007", "8118008"]
        # and the index still answers truthfully
        n = con.execute("SELECT COUNT(*) FROM Documents WHERE group_key = ?",
                        ("8118007",)).fetchone()[0]
    assert n == 1


def test_a_database_already_carrying_the_constant_index_is_repaired(old_db):
    """Someone may have pointed the new code at the old database once, which
    leaves the constant index behind. Migrating afterwards must still end up
    with a column that answers truthfully."""
    from docpipe import store
    from docpipe.profile import load_profile

    with sqlite3.connect(old_db) as con:
        store.apply(con, load_profile("kwp"))            # builds the bad index
        assert "idx_documents_group" in [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")]
        mig.migrate(con)
        assert [r[0] for r in con.execute("SELECT group_key FROM Documents")] \
            == ["8118007", "8118008"]
        assert con.execute("SELECT COUNT(*) FROM Documents "
                           "WHERE group_key IS NULL").fetchone()[0] == 0
