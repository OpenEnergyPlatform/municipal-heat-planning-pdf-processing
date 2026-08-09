"""The ingest step against a fake source — no Excel, no network, no project."""
import sqlite3

import pytest
import requests

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


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def test_a_dead_link_does_not_stop_the_run(monkeypatch, usable, tmp_path):
    """The registers link to municipal sites that reorganise; one 404 must not
    cost the other 800 documents."""
    def fetch(url, data_dir):
        if "gone" in url:
            raise _http_error(404)
        return url.rsplit("/", 1)[-1]

    monkeypatch.setattr(ingest, "download_pdf", fetch)
    source = FakeSource([_doc("a.pdf"), _doc("gone.pdf", group="7133018"),
                         _doc("b.pdf")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, KWP)

    con = sqlite3.connect(tmp_path / "db.sqlite")
    assert [r[0] for r in con.execute("SELECT filename FROM Documents ORDER BY id")] \
        == ["a.pdf", "b.pdf"]
    assert source.accepted == ["a.pdf", "b.pdf"]


def test_the_dead_links_are_written_out_as_a_worklist(monkeypatch, usable, tmp_path):
    monkeypatch.setattr(ingest, "download_pdf",
                        lambda url, d: (_ for _ in ()).throw(_http_error(404)))
    source = FakeSource([_doc("gone.pdf", group="7133018")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, KWP)

    line = (tmp_path / "unreachable_pdfs.txt").read_text(encoding="utf-8").strip()
    ags, filename, reason, url = line.split("\t")
    assert (ags, filename, reason) == ("7133018", "gone.pdf", "HTTP 404")
    assert url == "https://x/gone.pdf"       # so it can be checked by hand


def test_a_missing_override_file_lands_on_the_worklist_too(usable, tmp_path):
    """An override names a file that must be in the data dir; if it is not, that
    belongs on the same list rather than killing the run."""
    source = FakeSource([SourceDoc(external_id="x", filename="nowhere.pdf",
                                   url=None, group_key="8115050")])
    ingest.ingest(source, tmp_path / "db.sqlite", tmp_path, KWP)

    assert "nowhere.pdf" in (tmp_path / "unreachable_pdfs.txt").read_text(
        encoding="utf-8")


def test_one_dead_convoy_link_is_reported_once(monkeypatch, usable, tmp_path, caplog):
    monkeypatch.setattr(ingest, "download_pdf",
                        lambda url, d: (_ for _ in ()).throw(_http_error(404)))
    source = FakeSource([_doc("gone.pdf", group=str(a)) for a in (1, 2, 3)])
    with caplog.at_level("WARNING"):
        ingest.ingest(source, tmp_path / "db.sqlite", usable, KWP)

    warnings = [r for r in caplog.records
                if r.levelname == "WARNING" and "UNREACHABLE" in r.getMessage()]
    assert len(warnings) == 1
    assert len((tmp_path / "unreachable_pdfs.txt").read_text(
        encoding="utf-8").strip().splitlines()) == 1


def test_a_clean_run_clears_the_previous_worklists(usable, tmp_path):
    """Left lying around, an old list reads as this run's result."""
    for name in ("unreachable_pdfs.txt", "rejected_pdfs.txt"):
        (tmp_path / name).write_text("7133018\tgone.pdf\tHTTP 404\t\n", encoding="utf-8")

    ingest.ingest(FakeSource([_doc("a.pdf")]), tmp_path / "db.sqlite", usable, KWP)

    assert not (tmp_path / "unreachable_pdfs.txt").exists()
    assert not (tmp_path / "rejected_pdfs.txt").exists()


def test_works_without_a_profile(usable, tmp_path):
    # no profile: core tables only, and no DocumentMeta to write into
    source = FakeSource([SourceDoc(external_id="a", filename="a.pdf",
                                   url="https://x/a.pdf")])
    ingest.ingest(source, tmp_path / "db.sqlite", usable, None)
    con = sqlite3.connect(tmp_path / "db.sqlite")
    assert con.execute("SELECT COUNT(*) FROM Documents").fetchone()[0] == 1
    assert "DocumentMeta" not in store.tables(con)
