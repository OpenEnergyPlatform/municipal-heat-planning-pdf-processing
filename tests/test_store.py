"""Core schema and profile schema: the seam between them."""
import sqlite3

import pytest

from docpipe import store
from docpipe.profile import load_profile
from docpipe.store.schema import CORE_TABLES

KWP = load_profile("kwp")


def _con(profile=None):
    con = sqlite3.connect(":memory:")
    store.apply(con, profile)
    return con


def _columns(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def test_core_alone_creates_only_core_tables():
    tables = store.tables(_con())
    assert set(CORE_TABLES) <= tables
    assert not {"Municipalities", "OrganisationUnits", "DocumentMeta"} & tables


def test_profile_adds_its_own_tables():
    tables = store.tables(_con(KWP))
    assert {"Municipalities", "OrganisationUnits", "MunicipalityMeta",
            "DocumentMeta"} <= tables


def test_documents_carries_no_project_columns():
    # the whole point of the split: core code never meets an unknown column
    cols = _columns(_con(KWP), "Documents")
    assert "municipality_ags" not in cols and "organisation_unit" not in cols
    assert {"external_id", "group_key", "is_current", "supersedes"} <= cols


def test_apply_is_idempotent():
    con = _con(KWP)
    store.apply(con, KWP)      # a second run must not raise
    assert "Documents" in store.tables(con)


def test_foreign_keys_are_enforced():
    con = _con(KWP)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO Sections (document, section_number) VALUES (999, 0)")


def test_document_meta_follows_its_document():
    con = _con(KWP)
    con.execute("INSERT INTO Documents (id, filename) VALUES (1, 'a.pdf')")
    con.execute("INSERT INTO DocumentMeta (document, municipality_ags) VALUES (1, 12345)")
    con.execute("DELETE FROM Documents WHERE id = 1")
    assert con.execute("SELECT COUNT(*) FROM DocumentMeta").fetchone()[0] == 0


def test_external_id_is_unique():
    con = _con(KWP)
    con.execute("INSERT INTO Documents (filename, external_id) VALUES ('a.pdf', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO Documents (filename, external_id) VALUES ('b.pdf', 'x')")


def test_connect_creates_the_file(tmp_path):
    path = tmp_path / "sub" / "corpus.db"
    con = store.connect(path, KWP)
    assert path.exists()
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 0


@pytest.mark.parametrize("name", ["plain.db", "run#5.db", "x%41.db",
                                  "a b.db", "why?.db"])
def test_a_read_only_address_names_the_file_it_was_given(tmp_path, name,
                                                         monkeypatch):
    """`#`, `?` and `%` are part of a file name. In the address they are
    escaped, so the database that is opened is the one that was named, and
    reading only: nothing is created where there is no file."""
    import sqlite3

    from docpipe.store.schema import readonly_uri
    path = tmp_path / name
    try:
        sqlite3.connect(path).close()
    except sqlite3.OperationalError:
        pytest.skip(f"this file system has no file named {name}")
    if not path.is_file():
        pytest.skip(f"this file system has no file named {name}")
    made = sqlite3.connect(path)
    made.execute("CREATE TABLE t (x)")
    made.execute("INSERT INTO t VALUES (7)")
    made.commit()
    made.close()
    before = sorted(entry.name for entry in tmp_path.iterdir())
    conn = sqlite3.connect(readonly_uri(path), uri=True)
    try:
        assert conn.execute("SELECT x FROM t").fetchone() == (7,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (8)")
    finally:
        conn.close()
    assert sorted(entry.name for entry in tmp_path.iterdir()) == before
    # relative to where the process stands, and also for a file not there
    monkeypatch.chdir(tmp_path)
    assert readonly_uri(name) == readonly_uri(path)
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(readonly_uri("nowhere.db"), uri=True)
    assert not (tmp_path / "nowhere.db").exists()
