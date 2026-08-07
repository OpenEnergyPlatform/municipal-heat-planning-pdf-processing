"""Tests for ags-based document version linking (utils.database)."""
import sqlite3

import pytest

from docpipe import store
from docpipe.profile import load_profile
from utils import database as DB


def _db():
    """Core schema plus the kwp profile — the same tables the pipeline creates."""
    con = sqlite3.connect(":memory:")
    store.apply(con, load_profile("kwp"))
    con.execute("INSERT INTO OrganisationUnits (id, name, state) VALUES (1, 'OU', 'NI')")
    return con


def _insert(con, filename, ags, published):
    DB.add_document(filename, 1, published, 10, "20260101", ags, con)


def _state(con):
    return {
        fn: (cur, sup)
        for fn, cur, sup in con.execute(
            "SELECT filename, is_current, supersedes FROM Documents"
        )
    }


def test_single_document_stays_current():
    con = _db()
    _insert(con, "a.pdf", 111, "20240101")
    DB.link_document_versions(con)
    assert _state(con)["a.pdf"] == (1, None)


def test_two_versions_newest_is_current():
    con = _db()
    _insert(con, "old.pdf", 111, "20230101")
    _insert(con, "new.pdf", 111, "20250101")
    DB.link_document_versions(con)
    st = _state(con)
    old_id = con.execute("SELECT id FROM Documents WHERE filename='old.pdf'").fetchone()[0]
    assert st["new.pdf"][0] == 1            # newest current
    assert st["old.pdf"] == (0, None)       # oldest superseded, no predecessor
    assert st["new.pdf"][1] == old_id       # new supersedes old


def test_three_versions_chain():
    con = _db()
    _insert(con, "v1.pdf", 222, "20230101")
    _insert(con, "v3.pdf", 222, "20250101")
    _insert(con, "v2.pdf", 222, "20240101")
    DB.link_document_versions(con)
    ids = {fn: i for i, fn in con.execute("SELECT id, filename FROM Documents")}
    st = _state(con)
    assert st["v3.pdf"] == (1, ids["v2.pdf"])
    assert st["v2.pdf"] == (0, ids["v1.pdf"])
    assert st["v1.pdf"] == (0, None)


def test_different_ags_are_independent():
    con = _db()
    _insert(con, "townA.pdf", 111, "20240101")
    _insert(con, "townB.pdf", 222, "20240101")
    DB.link_document_versions(con)
    st = _state(con)
    assert st["townA.pdf"] == (1, None)
    assert st["townB.pdf"] == (1, None)


def test_document_without_group_key_untouched():
    con = _db()
    con.execute(
        "INSERT INTO Documents (filename, group_key, is_current) VALUES ('x.pdf', NULL, 1)"
    )
    DB.link_document_versions(con)
    assert _state(con)["x.pdf"] == (1, None)


def test_idempotent():
    con = _db()
    _insert(con, "old.pdf", 111, "20230101")
    _insert(con, "new.pdf", 111, "20250101")
    DB.link_document_versions(con)
    first = _state(con)
    DB.link_document_versions(con)
    assert _state(con) == first
