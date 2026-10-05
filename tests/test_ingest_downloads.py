"""A download is named, bounded and streamed.

Promised: a second URL that ends in the file name of a download that came from
another URL is refused with both URLs named, and the file keeps the first
one's bytes; AND the refusal is listed with the other files that could not be
fetched, the run goes on, and the ingest command says how many pairs are
missing and ends as it always did; AND a body is
streamed to disk and a file over the size limit is refused with its size,
leaving nothing behind; AND the User-Agent and the size limit are settings
whose defaults are what they were before they were settings.
"""
import sqlite3
from types import SimpleNamespace

import pytest
import requests

from docpipe.ingest import SourceDoc, fetch, cli
from docpipe.ingest import pipeline as ingest
from docpipe.ingest.models import Source

PLAN_A = "https://a.example/x/plan.pdf"
PLAN_B = "https://b.example/y/plan.pdf"
# The browser string the download sent before it was a setting.
THE_FORMER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def pdf(tag: str = "", size: int = 0) -> bytes:
    body = b"%PDF-1.4 " + tag.encode()
    return body + b"0" * max(0, size - len(body))


class Response:
    """What requests.get hands back with stream=True: a body that is
    handed out in pieces, and that says how much of it was taken."""

    def __init__(self, body: bytes, headers=None, status=200, pieces=None):
        self.body, self.headers, self.status_code = body, dict(headers or {}), status
        self.pieces = pieces
        self.taken = 0
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def iter_content(self, chunk_size=1):
        pieces = self.pieces or [self.body[i:i + chunk_size]
                                 for i in range(0, len(self.body), chunk_size)]
        for piece in pieces:
            self.taken += len(piece)
            yield piece

    def close(self):
        self.closed = True


class Web:
    def __init__(self):
        self.pages: dict = {}
        self.calls: list = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        page = self.pages[url]
        return page if isinstance(page, Response) else Response(page)


@pytest.fixture
def web(monkeypatch):
    for name in (fetch.USER_AGENT_ENV, fetch.MAX_DOWNLOAD_ENV):
        monkeypatch.delenv(name, raising=False)
    site = Web()
    monkeypatch.setattr(requests, "get", site.get)
    return site


def left_in(folder):
    return sorted(p.name for p in folder.iterdir())


# -- one name, two URLs ------------------------------------------------------

def test_a_second_url_for_a_taken_name_is_refused_and_both_are_named(web, tmp_path):
    web.pages = {PLAN_A: pdf("first"), PLAN_B: pdf("second")}
    assert fetch.download_pdf(PLAN_A, tmp_path) == "plan.pdf"
    with pytest.raises(fetch.NameTaken) as refused:
        fetch.download_pdf(PLAN_B, tmp_path)
    assert PLAN_A in str(refused.value) and PLAN_B in str(refused.value)
    assert "plan.pdf" in str(refused.value)
    assert (tmp_path / "plan.pdf").read_bytes() == pdf("first")
    # refused before it cost a request
    assert [url for url, _ in web.calls] == [PLAN_A]
    # an OSError, so that ingest lists it with the files it could not fetch
    assert isinstance(refused.value, OSError)


def test_the_same_url_again_is_not_a_second_url(web, tmp_path):
    """The other half of the promise: a check that refused every second call
    would also refuse the convoy, where one file serves many entries."""
    web.pages = {PLAN_A: pdf("first")}
    fetch.download_pdf(PLAN_A, tmp_path)
    assert fetch.download_pdf(PLAN_A, tmp_path) == "plan.pdf"
    # a spelling the server does not tell apart: the host's case, a fragment
    assert fetch.download_pdf("HTTPS://A.Example/x/plan.pdf#page=3",
                              tmp_path) == "plan.pdf"
    assert len(web.calls) == 1
    # but another query is another URL
    with pytest.raises(fetch.NameTaken):
        fetch.download_pdf(PLAN_A + "?version=2", tmp_path)


def test_check_name_holds_a_name_only_for_a_file_that_is_there(tmp_path):
    """The one question both callers ask: does this file, in this folder,
    come from another URL than the one asking?"""
    fetch.source_file("plan.pdf", tmp_path).write_text(PLAN_A + "\n",
                                                       encoding="utf-8")
    fetch.check_name("plan.pdf", PLAN_B, tmp_path)         # no file: free
    (tmp_path / "plan.pdf").write_bytes(pdf("first"))
    fetch.check_name("plan.pdf", PLAN_A, tmp_path)         # its own URL
    with pytest.raises(fetch.NameTaken) as refused:
        fetch.check_name("plan.pdf", PLAN_B, tmp_path)     # another one
    assert PLAN_A in str(refused.value) and PLAN_B in str(refused.value)
    fetch.source_file("plan.pdf", tmp_path).unlink()
    fetch.check_name("plan.pdf", PLAN_B, tmp_path)         # nobody wrote it down


def test_a_file_put_there_by_hand_is_not_refused(web, tmp_path):
    """Nobody wrote a URL down for it, so there is nothing to disagree with:
    what a hand-sourced override and an older data directory rely on."""
    (tmp_path / "plan.pdf").write_bytes(pdf("by hand"))
    assert fetch.download_pdf(PLAN_B, tmp_path) == "plan.pdf"
    assert web.calls == []
    assert (tmp_path / "plan.pdf").read_bytes() == pdf("by hand")


def test_a_failed_download_does_not_take_the_name(web, tmp_path):
    """The URL is written down with the file, not before it: a body that is
    no PDF leaves neither, and the name is free for the next URL."""
    web.pages = {PLAN_A: b"<html>moved</html>", PLAN_B: pdf("second")}
    with pytest.raises(IOError, match="not a PDF"):
        fetch.download_pdf(PLAN_A, tmp_path)
    assert left_in(tmp_path) == []
    assert fetch.download_pdf(PLAN_B, tmp_path) == "plan.pdf"
    assert fetch.source_of("plan.pdf", tmp_path) == PLAN_B


def _source(*docs):
    class Listed(Source):
        def __init__(self):
            self.accepted = []

        def __len__(self):
            return len(docs)

        def documents(self, connection):
            return iter(docs)

        def after_document(self, connection, doc):
            self.accepted.append(doc.external_id)
    return Listed()


def _doc(external_id, url, filename=None):
    return SourceDoc(external_id=external_id, url=url,
                     filename=filename or url.rsplit("/", 1)[-1],
                     group_key=external_id)


@pytest.fixture
def readable(monkeypatch):
    monkeypatch.setattr(ingest, "get_num_pages", lambda name, folder: 3)
    monkeypatch.setattr(ingest.pdf_quality, "check", lambda path: (True, ""))


def _worklist(folder):
    path = folder / "unreachable_pdfs.txt"
    return [line.split("\t") for line in
            path.read_text(encoding="utf-8").splitlines()] \
        if path.exists() else []


def test_the_refused_url_is_listed_and_the_run_goes_on(web, readable, tmp_path):
    web.pages = {PLAN_A: pdf("first"), PLAN_B: pdf("second"),
                 "https://a.example/c.pdf": pdf("c")}
    source = _source(_doc("one", PLAN_A), _doc("two", PLAN_B),
                     _doc("three", "https://a.example/c.pdf"))
    unreachable: dict = {}
    ingest.ingest(source, tmp_path / "db.sqlite", tmp_path, None,
                  unreachable=unreachable)

    names = [r[0] for r in sqlite3.connect(tmp_path / "db.sqlite").execute(
        "SELECT filename FROM Documents ORDER BY id")]
    assert names == ["plan.pdf", "c.pdf"]
    assert (tmp_path / "plan.pdf").read_bytes() == pdf("first")
    assert source.accepted == ["one", "three"]      # no hook for the refused
    ((group, name, reason, url),) = _worklist(tmp_path)
    assert (group, name, url) == ("two", "plan.pdf", PLAN_B)
    assert PLAN_A in reason and PLAN_B in reason and "NameTaken" in reason
    assert list(unreachable) == [("plan.pdf", PLAN_B)]


def test_a_registered_document_does_not_hide_the_second_url(web, readable,
                                                           tmp_path):
    """The second run finds plan.pdf in the database already, which is where
    register used to say 'nothing to do' without asking whose it was."""
    web.pages = {PLAN_A: pdf("first"), PLAN_B: pdf("second")}
    ingest.ingest(_source(_doc("one", PLAN_A)), tmp_path / "db.sqlite",
                  tmp_path, None)
    assert _worklist(tmp_path) == []

    later = _source(_doc("two", PLAN_B))
    unreachable: dict = {}
    ingest.ingest(later, tmp_path / "db.sqlite", tmp_path, None,
                  unreachable=unreachable)
    assert list(unreachable) == [("plan.pdf", PLAN_B)]
    assert later.accepted == []
    assert [r[3] for r in _worklist(tmp_path)] == [PLAN_B]
    # and the same URL on a third run is the document that is there
    again = _source(_doc("one", PLAN_A))
    ingest.ingest(again, tmp_path / "db.sqlite", tmp_path, None)
    assert again.accepted == ["one"] and _worklist(tmp_path) == []


def test_a_url_left_by_a_killed_job_without_its_file_takes_no_name(
        web, readable, tmp_path):
    """The URL goes down before the PDF does, so a job killed between the two
    leaves a URL and no file. Nothing holds the name then, and a refusal
    that says "kept" would name a file that is not there."""
    fetch.source_file("plan.pdf", tmp_path).write_text(PLAN_A + "\n",
                                                       encoding="utf-8")
    assert not (tmp_path / "plan.pdf").exists()
    web.pages = {PLAN_B: pdf("second")}
    unreachable: dict = {}
    source = _source(_doc("two", PLAN_B))

    ingest.ingest(source, tmp_path / "db.sqlite", tmp_path, None,
                  unreachable=unreachable)

    assert unreachable == {} and source.accepted == ["two"]
    assert (tmp_path / "plan.pdf").read_bytes() == pdf("second")
    assert fetch.source_of("plan.pdf", tmp_path) == PLAN_B
    # the same name with its file there is held, as before
    refused = _source(_doc("three", PLAN_A))
    ingest.ingest(refused, tmp_path / "db.sqlite", tmp_path, None,
                  unreachable=unreachable)
    assert list(unreachable) == [("plan.pdf", PLAN_A)]


def test_every_refused_url_of_a_name_is_on_the_worklist(web, readable, tmp_path):
    third = "https://c.example/z/plan.pdf"
    web.pages = {PLAN_A: pdf("first")}
    ingest.ingest(_source(_doc("one", PLAN_A), _doc("two", PLAN_B),
                          _doc("three", third), _doc("four", PLAN_B)),
                  tmp_path / "db.sqlite", tmp_path, None)
    # PLAN_B twice is one entry, as one broken file under a convoy is
    assert sorted(r[3] for r in _worklist(tmp_path)) == sorted([PLAN_B, third])


def _fake_profile(source):
    return SimpleNamespace(
        name="fake", schema_sql=None,
        component=lambda module, name: source if (module, name) == (
            "source", "SOURCE") else None)


def _run_command(monkeypatch, tmp_path, *docs):
    source = _source(*docs)
    monkeypatch.setattr(cli, "require_profile",
                        lambda args: _fake_profile(lambda location: source))
    cli.main(["--source", str(tmp_path / "list"), "--db",
              str(tmp_path / "db.sqlite"), "--data-dir", str(tmp_path / "pdf")])
    return source


def _said(caplog):
    return [r.getMessage() for r in caplog.records
            if "pair(s) could not be fetched" in r.getMessage()]


def test_the_command_says_a_refused_url_and_ends_as_it_always_did(
        web, readable, monkeypatch, tmp_path, caplog):
    web.pages = {PLAN_A: pdf("first"), PLAN_B: pdf("second")}
    with caplog.at_level("WARNING"):
        _run_command(monkeypatch, tmp_path, _doc("one", PLAN_A),
                     _doc("two", PLAN_B))                    # no exit
    said, = _said(caplog)
    assert said.startswith("1 (file name, URL) pair(s)")
    assert "unreachable_pdfs.txt" in said
    # the run went on to the end: the first document is in
    assert sqlite3.connect(tmp_path / "db.sqlite").execute(
        "SELECT COUNT(*) FROM Documents").fetchone()[0] == 1


def test_the_command_counts_pairs_not_file_names(web, readable, monkeypatch,
                                                 tmp_path, caplog):
    """One file name that two other URLs claim is one name and two entries
    of the worklist: the number says which it counts."""
    third = "https://c.example/z/plan.pdf"
    web.pages = {PLAN_A: pdf("first")}
    with caplog.at_level("WARNING"):
        _run_command(monkeypatch, tmp_path, _doc("one", PLAN_A),
                     _doc("two", PLAN_B), _doc("three", third))
    said, = _said(caplog)
    assert said.startswith("2 (file name, URL) pair(s)")
    assert len(_worklist(tmp_path)) == 2


def test_a_clean_run_says_nothing_and_a_dead_link_is_said(
        web, readable, monkeypatch, tmp_path, caplog):
    web.pages = {PLAN_A: pdf("first"),
                 "https://a.example/gone.pdf": Response(b"", status=404)}
    with caplog.at_level("WARNING"):
        _run_command(monkeypatch, tmp_path, _doc("one", PLAN_A))
    assert _said(caplog) == []
    with caplog.at_level("WARNING"):
        _run_command(monkeypatch, tmp_path / "second",          # no exit
                     _doc("two", "https://a.example/gone.pdf"))
    assert len(_said(caplog)) == 1


# -- the size limit and the stream ------------------------------------------

def test_a_download_is_streamed_to_disk_and_kept_whole(web, tmp_path):
    body = pdf("whole", size=3 * fetch.MEGABYTE + 17)
    web.pages = {PLAN_A: body}
    fetch.download_pdf(PLAN_A, tmp_path)
    (_, kwargs), = web.calls
    assert kwargs["stream"] is True
    assert (tmp_path / "plan.pdf").read_bytes() == body
    assert left_in(tmp_path) == ["plan.pdf", "plan.pdf.url"]


def test_a_file_over_the_limit_is_refused_with_its_size_and_never_read(
        web, tmp_path, monkeypatch):
    monkeypatch.setenv(fetch.MAX_DOWNLOAD_ENV, "1")
    size = fetch.MEGABYTE + 10
    page = Response(pdf(size=size), headers={"Content-Length": str(size)})
    web.pages = {PLAN_A: page}
    with pytest.raises(fetch.TooLarge) as refused:
        fetch.download_pdf(PLAN_A, tmp_path)
    assert str(size) in str(refused.value)
    assert str(fetch.MEGABYTE) in str(refused.value)
    assert page.taken == 0 and page.closed
    assert left_in(tmp_path) == []


def test_a_body_that_announces_no_size_is_stopped_while_it_streams(
        web, tmp_path, monkeypatch):
    monkeypatch.setenv(fetch.MAX_DOWNLOAD_ENV, "1")
    size = 3 * fetch.MEGABYTE
    page = Response(pdf(size=size))                   # no Content-Length
    web.pages = {PLAN_A: page}
    with pytest.raises(fetch.TooLarge) as refused:
        fetch.download_pdf(PLAN_A, tmp_path)
    assert str(2 * fetch.MEGABYTE) in str(refused.value)     # what was counted
    # whole in memory would have taken all of it
    assert page.taken == 2 * fetch.MEGABYTE < size
    assert page.closed
    assert left_in(tmp_path) == [], "no partial file, no URL for a file that is not there"


def test_the_limit_itself_is_kept_and_one_byte_more_is_not(web, tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv(fetch.MAX_DOWNLOAD_ENV, "1")
    web.pages = {PLAN_A: pdf(size=fetch.MEGABYTE),
                 "https://a.example/more.pdf": pdf(size=fetch.MEGABYTE + 1)}
    assert fetch.download_pdf(PLAN_A, tmp_path) == "plan.pdf"
    with pytest.raises(fetch.TooLarge):
        fetch.download_pdf("https://a.example/more.pdf", tmp_path)
    assert not (tmp_path / "more.pdf").exists()


def test_the_size_limit_is_a_setting_with_a_default(monkeypatch):
    monkeypatch.delenv(fetch.MAX_DOWNLOAD_ENV, raising=False)
    assert fetch.max_download_bytes() == 500 * fetch.MEGABYTE
    monkeypatch.setenv(fetch.MAX_DOWNLOAD_ENV, "7")
    assert fetch.max_download_bytes() == 7 * fetch.MEGABYTE
    for wrong in ("0", "-3", "many", "1.5"):
        monkeypatch.setenv(fetch.MAX_DOWNLOAD_ENV, wrong)
        with pytest.raises(ValueError, match=fetch.MAX_DOWNLOAD_ENV):
            fetch.max_download_bytes()


def test_a_body_is_a_pdf_by_its_first_bytes_however_they_arrive(web, tmp_path):
    web.pages = {
        PLAN_A: Response(b"", pieces=[b"%P", b"", b"DF", b"-1.7 rest"]),
        PLAN_B: Response(b"", pieces=[b"%P", b"XF", b"-1.7 rest"]),
        "https://a.example/empty.pdf": Response(b""),
        "https://a.example/short.pdf": Response(b"", pieces=[b"%PD"]),
    }
    assert fetch.download_pdf(PLAN_A, tmp_path) == "plan.pdf"
    assert (tmp_path / "plan.pdf").read_bytes() == b"%PDF-1.7 rest"
    for url in ("https://b.example/other.pdf", "https://a.example/empty.pdf",
                "https://a.example/short.pdf"):
        web.pages.setdefault(url, web.pages[PLAN_B])
        with pytest.raises(IOError, match="not a PDF"):
            fetch.download_pdf(url, tmp_path)
    assert left_in(tmp_path) == ["plan.pdf", "plan.pdf.url"]


def test_a_page_that_is_no_pdf_is_not_read_to_its_end(web, tmp_path):
    """A server that answers a dead link with a long page costs the first
    chunk, not the page."""
    page = Response(b"<html>" + b"x" * (3 * fetch.MEGABYTE))
    web.pages = {PLAN_A: page}
    with pytest.raises(IOError, match="not a PDF"):
        fetch.download_pdf(PLAN_A, tmp_path)
    assert page.taken == fetch.MEGABYTE
    assert left_in(tmp_path) == []


def test_a_failed_request_is_an_http_error_and_leaves_nothing(web, tmp_path):
    page = Response(b"", status=503)
    web.pages = {PLAN_A: page}
    with pytest.raises(requests.HTTPError):
        fetch.download_pdf(PLAN_A, tmp_path)
    assert page.closed and left_in(tmp_path) == []


# -- the User-Agent ----------------------------------------------------------

def test_the_user_agent_is_a_setting_that_defaults_to_the_browser_it_was(
        web, tmp_path, monkeypatch):
    web.pages = {PLAN_A: pdf("a"), "https://b.example/b.pdf": pdf("b")}
    fetch.download_pdf(PLAN_A, tmp_path)
    assert web.calls[0][1]["headers"] == {"User-Agent": THE_FORMER_USER_AGENT}

    monkeypatch.setenv(fetch.USER_AGENT_ENV, "docpipe-test/1")
    fetch.download_pdf("https://b.example/b.pdf", tmp_path)
    assert web.calls[1][1]["headers"] == {"User-Agent": "docpipe-test/1"}

    # an empty value is no User-Agent at all, and a plain client gets a 403
    monkeypatch.setenv(fetch.USER_AGENT_ENV, "")
    assert fetch.user_agent() == THE_FORMER_USER_AGENT
