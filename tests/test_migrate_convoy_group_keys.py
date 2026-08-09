"""Regrouping convoy documents by their smallest ags."""
import sqlite3

import pytest

from docpipe import store
from docpipe.profile import load_profile
from profiles.kwp import migrate_convoy_group_keys as mig

KWP = load_profile("kwp")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "KWP.db"
    con = sqlite3.connect(path)
    store.apply(con, KWP)
    con.executemany(
        "INSERT INTO Documents (filename, external_id, group_key, published, is_current)"
        " VALUES (?, ?, ?, ?, 1)",
        [("konvoi_2025.pdf", "konvoi_2025.pdf", "7133103", "20250101"),
         ("konvoi_2026.pdf", "konvoi_2026.pdf", "7133054", "20260101"),
         ("einzeln.pdf", "einzeln.pdf", "8325049", "20240101")],
    )
    con.commit()
    return con


WANTED = {"konvoi_2025.pdf": "7133018", "konvoi_2026.pdf": "7133018",
          "einzeln.pdf": "8325049"}


def test_only_the_documents_whose_key_moves_are_reported(db):
    moved = mig.changes(db, WANTED)
    assert [(m[1], m[2], m[3]) for m in moved] == [
        ("konvoi_2025.pdf", "7133103", "7133018"),
        ("konvoi_2026.pdf", "7133054", "7133018"),
    ]


def test_the_two_editions_end_up_in_one_group_and_the_older_is_superseded(db):
    mig.migrate(db, WANTED)
    rows = dict((r[0], (r[1], r[2])) for r in db.execute(
        "SELECT filename, group_key, is_current FROM Documents"))
    assert rows["konvoi_2025.pdf"] == ("7133018", 0)     # older edition
    assert rows["konvoi_2026.pdf"] == ("7133018", 1)     # current
    assert rows["einzeln.pdf"] == ("8325049", 1)         # untouched


def test_the_older_edition_points_at_nothing_and_the_newer_at_the_older(db):
    mig.migrate(db, WANTED)
    ids = dict(db.execute("SELECT filename, id FROM Documents"))
    sup = dict(db.execute("SELECT filename, supersedes FROM Documents"))
    assert sup["konvoi_2025.pdf"] is None
    assert sup["konvoi_2026.pdf"] == ids["konvoi_2025.pdf"]


def test_running_it_twice_changes_nothing(db):
    mig.migrate(db, WANTED)
    first = db.execute("SELECT id, group_key, is_current, supersedes "
                       "FROM Documents ORDER BY id").fetchall()
    assert mig.migrate(db, WANTED) == []
    assert db.execute("SELECT id, group_key, is_current, supersedes "
                      "FROM Documents ORDER BY id").fetchall() == first


def test_a_document_the_register_no_longer_lists_keeps_its_key(db):
    """Dresden was withdrawn from the register; its row must survive untouched
    rather than lose the grouping it has."""
    db.execute("INSERT INTO Documents (filename, external_id, group_key, published,"
               " is_current) VALUES ('weg.pdf', 'weg.pdf', '14612000', '20250929', 1)")
    mig.migrate(db, WANTED)
    assert db.execute("SELECT group_key, is_current FROM Documents "
                      "WHERE filename = 'weg.pdf'").fetchone() == ("14612000", 1)
