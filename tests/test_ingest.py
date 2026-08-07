"""The ingest step against a fake source — no Excel, no network, no project."""
import sqlite3

import pytest

from docpipe import store
from docpipe.ingest import SourceDoc, UnusablePDF
from docpipe.ingest import pipeline as ingest
from docpipe.profile import load_profile

KWP = load_profile("kwp")


class FakeSource:
    """Yields prepared documents and records which ones were accepted."""

    def __init__(self, docs):
        self.docs = docs
        self.accepted = []

    def __len__(self):
        return len(self.docs)

    def documents(self, connection):
        return iter(self.docs)

    def after_document(self, connection, doc):
        self.accepted.append(doc.external_id)


def _doc(name, group=None, published=None):
    return SourceDoc(external_id=name, filename=name, url=f"https://x/{name}",
                     group_key=group, published=published)


@pytest.fixture
def usable(monkeypatch, tmp_path):
    """Every download yields a usable PDF of ten pages."""
    monkeypatch.setattr(ingest, "download_pdf", lambda url, d: url.rsplit("/", 1)[-1])
    monkeypatch.setattr(ingest, "get_num_pages", lambda fn, d: 10)
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda p: (True, ""))
    return tmp_path


def test_registers_documents_and_calls_the_profile_hook(usable, tmp_path):
    source = FakeSource([_doc("a.pdf"), _doc("b.pdf")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, KWP)
    con = sqlite3.connect(tmp_path / "db.sqlite")
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 2
    assert source.accepted == ["a.pdf", "b.pdf"]


def test_a_document_is_registered_once(usable, tmp_path):
    # two entries, same file: one Documents row, but the profile hook runs twice
    source = FakeSource([_doc("same.pdf"), _doc("same.pdf")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, KWP)
    con = sqlite3.connect(tmp_path / "db.sqlite")
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 1
    assert len(source.accepted) == 2


def test_unusable_pdf_leaves_nothing_behind(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "download_pdf", lambda url, d: "scan.pdf")
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda p: (False, "NO_TEXT"))
    source = FakeSource([_doc("scan.pdf")])
    rejected = ingest.ingest(source, tmp_path / "db.sqlite", tmp_path, KWP)

    assert rejected == {"scan.pdf": "NO_TEXT"}
    con = sqlite3.connect(tmp_path / "db.sqlite")
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 0
    assert source.accepted == []            # the profile hook must not have run
    assert (tmp_path / "rejected_pdfs.txt").exists()


def test_missing_local_file_without_url_is_an_error(tmp_path):
    con = sqlite3.connect(":memory:")
    store.apply(con, KWP)
    doc = SourceDoc(external_id="x", filename="nowhere.pdf", url=None)
    with pytest.raises(FileNotFoundError):
        ingest.register(doc, con, tmp_path)


def test_versions_are_linked_after_ingest(usable, tmp_path):
    source = FakeSource([_doc("old.pdf", group="111", published="20230101"),
                         _doc("new.pdf", group="111", published="20250101")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, KWP)
    con = sqlite3.connect(tmp_path / "db.sqlite")
    state = dict(con.execute("SELECT filename, is_current FROM Documents"))
    assert state == {"old.pdf": 0, "new.pdf": 1}


def test_works_without_a_profile(usable, tmp_path):
    # no profile: core tables only, and no DocumentMeta to write into
    source = FakeSource([SourceDoc(external_id="a", filename="a.pdf",
                                   url="https://x/a.pdf")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, None)
    con = sqlite3.connect(tmp_path / "db.sqlite")
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 1
    assert "DocumentMeta" not in store.tables(con)
