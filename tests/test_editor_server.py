"""
test_editor_server.py: what `docpipe edit` promises about files, saves and
the network.

Each test states one promise and holds a case that breaks it by
construction: a path that leads out, a spec the loader refuses, a removal
nobody confirmed, a file that moved, a stamp that is not current, a request
from another site.

Author: Felix Vossel
"""
from __future__ import annotations

import ast
import copy
import http.client
import json
import os
import select
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from docpipe.editor import server, specs
from docpipe.extraction import spec as spec_module

REPO = Path(__file__).resolve().parent.parent
REAL_SPEC = REPO / "profiles" / "scenarios" / "extraction_spec.json"
WEB = REPO / "docpipe" / "editor" / "web"
SNAPSHOT = {"terms": {"OEO_00050016": {
    "label": "energy consumption", "definition": "a definition",
    "alt_labels": ["use"], "deprecated": False}}}


class Stand:
    """The part of a profile the editor uses."""

    name = "scenarios"

    def __init__(self, folder: Path, spec: Path, vocabulary=None):
        self.package_dir = folder
        self._spec = spec
        self._vocabulary = vocabulary

    def lineage(self) -> list:
        return [self]

    def component(self, module: str, attr: str):
        return {("extraction", "SPEC_PATH"): self._spec,
                ("vocabulary", "load"): self._vocabulary
                }.get((module, attr))


def make_app(tmp_path: Path, harvest=None, vocabulary=lambda: SNAPSHOT):
    folder = tmp_path / "profile"
    folder.mkdir()
    spec = folder / "extraction_spec.json"
    shutil.copy(REAL_SPEC, spec)
    root = tmp_path / "repo"
    root.mkdir()
    return server.App(Stand(folder, spec, vocabulary), harvest, root), spec


def get(app, path: str, **query):
    return app.call("GET", path, query, None)


def post(app, path: str, body):
    return app.call("POST", path, {}, body)


def a_list(data: dict):
    """(field, coordinate or None, the list) of a list with several
    entries."""
    for parameter in data["parameters"]:
        if len(parameter.get("vocabulary") or {}) > 1:
            return parameter["uri"], None, parameter["vocabulary"]
        for name, axis in (parameter.get("axes") or {}).items():
            if len(axis.get("vocabulary") or {}) > 1:
                return parameter["uri"], name, axis["vocabulary"]
    raise AssertionError("the spec has no list of several entries")


def removable(data: dict):
    """(field, coordinate, entry) of an entry the spec loads without."""
    for parameter in data["parameters"]:
        for name, axis in (parameter.get("axes") or {}).items():
            for entry in axis.get("vocabulary") or {}:
                made = specs.remove(data, "entry", field=parameter["uri"],
                                    coordinate=name, entry=entry)
                if specs.problem(made) is None:
                    return parameter["uri"], name, entry
    raise AssertionError("no entry can be removed")


def add_spelling(data: dict) -> dict:
    out = copy.deepcopy(data)
    _, _, listed = a_list(out)
    entry = next(iter(listed.values()))
    if isinstance(entry, list):
        entry.insert(1, "an added spelling")
    else:
        entry.setdefault("spellings", []).insert(0, "an added spelling")
    return out


# -- 1. the editor writes only into the profile --------------------------------

def test_files_write_only_inside_the_write_root(tmp_path):
    write, read = tmp_path / "w", tmp_path / "r"
    write.mkdir()
    read.mkdir()
    files = server.Files(write, [read])
    files.write(write / "a.json", b"{}")
    assert (write / "a.json").read_bytes() == b"{}"
    # by construction: elsewhere, a read root, and a path that leaves by ..
    for target in (tmp_path / "elsewhere.json", read / "b.json",
                   write / ".." / "escaped.json",
                   write / "sub" / ".." / ".." / "escaped.json"):
        with pytest.raises(PermissionError):
            files.open(target, "wb")
        with pytest.raises(PermissionError):
            files.write(target, b"x")
    assert not (tmp_path / "elsewhere.json").exists()
    assert not (tmp_path / "escaped.json").exists()
    assert not (read / "b.json").exists()
    # A file is taken away only there too: one of a read root or one
    # reached by .. stays, one of the write root goes, and one that is not
    # there is left alone.
    (read / "kept.json").write_bytes(b"{}")
    for target in (read / "kept.json", write / ".." / "r" / "kept.json"):
        with pytest.raises(PermissionError):
            files.remove(target)
    assert (read / "kept.json").read_bytes() == b"{}"
    files.remove(write / "a.json")
    assert not (write / "a.json").exists()
    files.remove(write / "a.json")


def test_files_read_only_inside_the_roots(tmp_path):
    write, read, other = tmp_path / "w", tmp_path / "r", tmp_path / "o"
    for folder in (write, read, other):
        folder.mkdir()
    (read / "x.stamp.json").write_text("{}")
    (other / "secret.txt").write_text("no")
    files = server.Files(write, [read])
    assert files.read(read / "x.stamp.json") == b"{}"
    assert files.stamps(read) == [(read / "x.stamp.json").resolve()]
    with pytest.raises(PermissionError):
        files.read(other / "secret.txt")
    with pytest.raises(PermissionError):
        files.read(read / ".." / "o" / "secret.txt")
    with pytest.raises(PermissionError):
        files.stamps(other)
    with pytest.raises(PermissionError):
        files.digest(other / "secret.txt")


def test_a_failed_write_leaves_the_old_file_whole(tmp_path, monkeypatch):
    files = server.Files(tmp_path, [])
    target = tmp_path / "spec.json"
    target.write_bytes(b"old")

    def broken(*_):
        raise OSError("disk full")

    monkeypatch.setattr(server.os, "replace", broken)
    with pytest.raises(OSError):
        files.write(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["spec.json"]


def test_server_opens_files_in_one_place_only():
    """One call of the builtin open, in Files.open; no other way to touch a
    file (read_text and the like, os.open, io.open, Path.open)."""
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    builtin, others = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            builtin.append(node.lineno)
        elif isinstance(func, ast.Attribute) and func.attr in (
                "open", "read_bytes", "read_text", "write_bytes",
                "write_text", "touch", "mkdir", "unlink"):
            owner = func.value
            if not (func.attr == "open" and isinstance(owner, ast.Name)
                    and owner.id in ("self", "webbrowser")):
                others.append((func.attr, node.lineno))
    guard = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.ClassDef) and n.name == "Files")
    opening = next(n for n in guard.body
                   if isinstance(n, ast.FunctionDef) and n.name == "open")
    assert len(builtin) == 1
    assert opening.lineno <= builtin[0] <= opening.end_lineno
    # the temporary file of a failed write and a file that is taken away
    # (`Files.remove`) are removed by their own path, inside the guard: the
    # only other file calls, and ones that create nothing
    assert [name for name, _ in others] == ["unlink", "unlink"]
    assert all(guard.lineno <= line <= guard.end_lineno
               for _, line in others)


# -- 2. a save writes only what the check passes -------------------------------

def test_save_refuses_what_the_loader_refuses(tmp_path):
    app, spec = make_app(tmp_path)
    before = spec.read_bytes()
    status, loaded = get(app, "/api/spec")
    assert status == 200
    data = copy.deepcopy(loaded["data"])
    data["parameters"][0]["value_type"] = "no_such_type"
    status, report = post(app, "/api/spec/save",
                          {"data": data, "base": loaded["base"]})
    assert status == 200
    assert report["saved"] is False and report["reason"] == "check"
    assert report["ok"] is False
    assert data["parameters"][0]["uri"] in (report["error"]["where"]
                                            + report["error"]["message"]) \
        or "parameters[0]" in report["error"]["where"]
    assert spec.read_bytes() == before


def test_save_writes_a_valid_edit(tmp_path):
    app, spec = make_app(tmp_path)
    _, loaded = get(app, "/api/spec")
    data = add_spelling(loaded["data"])
    status, report = post(app, "/api/spec/save",
                          {"data": data, "base": loaded["base"]})
    assert report["saved"] is True, report
    assert report["lines"]["added"] >= 1
    assert specs.parse(spec.read_bytes()) == data
    assert report["base"] == server.sha256(spec.read_bytes())
    assert "text" not in report


def test_check_writes_nothing_and_hides_the_file_text(tmp_path):
    app, spec = make_app(tmp_path)
    before = spec.read_bytes()
    _, loaded = get(app, "/api/spec")
    status, report = post(app, "/api/spec/check",
                          {"data": add_spelling(loaded["data"])})
    assert status == 200 and report["ok"] is True
    assert "text" not in report and report["diff"]
    assert spec.read_bytes() == before


# -- 3. a removal needs confirmation -------------------------------------------

def test_a_removal_is_written_only_when_confirmed(tmp_path):
    app, spec = make_app(tmp_path)
    before = spec.read_bytes()
    _, loaded = get(app, "/api/spec")
    uri, coordinate, entry = removable(loaded["data"])
    status, made = post(app, "/api/spec/remove", {
        "data": loaded["data"], "kind": "entry", "field": uri,
        "coordinate": coordinate, "list": "vocabulary", "entry": entry})
    assert status == 200 and made["ok"] is True
    body = {"data": made["data"], "base": loaded["base"]}
    _, report = post(app, "/api/spec/save", body)
    assert report["saved"] is False and report["reason"] == "confirm"
    assert any(entry in line for line in report["removed"])
    assert spec.read_bytes() == before
    _, report = post(app, "/api/spec/save", {**body, "confirm": True})
    assert report["saved"] is True
    assert specs.parse(spec.read_bytes()) == made["data"]


def test_a_refused_removal_is_an_answer_not_an_error(tmp_path):
    app, _ = make_app(tmp_path)
    _, loaded = get(app, "/api/spec")
    status, made = post(app, "/api/spec/remove", {
        "data": loaded["data"], "kind": "field", "field": "no_such_field"})
    assert status == 200 and made["ok"] is False
    assert "no_such_field" in made["error"]["where"]
    status, made = post(app, "/api/spec/copy", {
        "data": loaded["data"], "kind": "field",
        "field": loaded["data"]["parameters"][0]["uri"],
        "key": loaded["data"]["parameters"][0]["uri"]})
    assert status == 200 and made["ok"] is False


# -- 4. a file that moved is not overwritten -----------------------------------

def test_a_file_that_moved_is_not_overwritten(tmp_path):
    app, spec = make_app(tmp_path)
    _, loaded = get(app, "/api/spec")
    spec.write_bytes(spec.read_bytes() + b"\n")        # someone else saved
    moved = spec.read_bytes()
    _, report = post(app, "/api/spec/save", {
        "data": add_spelling(loaded["data"]), "base": loaded["base"]})
    assert report["saved"] is False and report["reason"] == "moved"
    assert report["message"]
    assert spec.read_bytes() == moved


# -- 5. the documents an edit makes stale --------------------------------------

def test_without_a_harvest_no_documents_are_counted(tmp_path):
    app, _ = make_app(tmp_path)
    _, loaded = get(app, "/api/spec")
    data = copy.deepcopy(loaded["data"])
    data["parameters"][0]["description"] += " and a few more words"
    _, report = post(app, "/api/spec/check", {"data": data})
    assert report["changes"], "an edited description is a changed question"
    assert all(c["documents"] is None for c in report["changes"])
    assert report["documents_note"]
    _, state = get(app, "/api/state")
    assert state["harvest"] is None and state["harvest_documents"] is None


def test_a_harvest_names_the_documents_an_edit_makes_stale(tmp_path):
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    app, spec = make_app(tmp_path, harvest)
    on_disk = specs.parse(spec.read_bytes())
    prints = spec_module.fingerprints(spec_module.load(on_disk))
    (harvest / "doc1.stamp.json").write_text(json.dumps(prints))
    _, state = get(app, "/api/state")
    assert state["harvest_documents"] == 1
    data = copy.deepcopy(on_disk)
    data["parameters"][0]["description"] += " and a few more words"
    _, report = post(app, "/api/spec/check", {"data": data})
    assert report["documents_note"] is None
    hit = [c for c in report["changes"] if c["documents"]]
    assert hit and all(c["documents"] == ["doc1"] for c in hit)
    # by construction: an edit that changes no question makes none stale
    quiet = copy.deepcopy(on_disk)
    quiet["_comment"] = ["a note"]
    _, report = post(app, "/api/spec/check", {"data": quiet})
    assert report["changes"] == []


# -- 6. nothing leaves the machine ---------------------------------------------

def test_the_endpoints_need_no_network(tmp_path, monkeypatch):
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    app, _ = make_app(tmp_path, harvest)

    def refuse(*_a, **_k):
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert get(app, "/api/state")[0] == 200
    status, loaded = get(app, "/api/spec")
    assert status == 200
    data = add_spelling(loaded["data"])
    assert post(app, "/api/spec/check", {"data": data})[0] == 200
    status, report = post(app, "/api/spec/save",
                          {"data": data, "base": loaded["base"]})
    assert status == 200 and report["saved"] is True
    status, found = get(app, "/api/terms", q="energy", limit="5")
    assert status == 200 and found["total"] == 1


def test_the_page_loads_nothing_from_outside():
    for name in ("index.html", "app.js", "style.css"):
        text = (WEB / name).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, name


# -- the answers around the endpoints ------------------------------------------

def test_requests_that_do_not_fit_are_refused_with_a_sentence(tmp_path):
    app, _ = make_app(tmp_path)
    assert post(app, "/api/spec/check", ["not", "an", "object"])[0] == 400
    assert post(app, "/api/spec/check", {"no": "data"})[0] == 400
    status, obj = post(app, "/api/spec/remove",
                       {"data": {"parameters": []}})
    assert status == 400 and obj["error"]
    assert get(app, "/api/nothing")[0] == 404
    assert get(app, "/api/spec/check")[0] == 405


def test_a_profile_without_a_spec_or_snapshot(tmp_path):
    folder = tmp_path / "profile"
    folder.mkdir()
    app = server.App(Stand(folder, None, None), None, tmp_path)
    status, obj = get(app, "/api/spec")
    assert status == 404 and obj["error"]
    assert post(app, "/api/spec/check", {"data": {}})[0] == 404
    assert get(app, "/api/terms", q="x") == (200, {"terms": [], "total": 0})
    assert get(app, "/api/state")[1]["spec"] is None


def test_an_error_inside_an_endpoint_is_a_500_with_its_type(tmp_path):
    def broken():
        raise RuntimeError("no snapshot today")

    app, _ = make_app(tmp_path, vocabulary=broken)
    status, obj = get(app, "/api/terms", q="x")
    assert status == 500 and obj["error"] == "RuntimeError: no snapshot today"


def test_generate_lists_the_files_the_commands_changed(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path)
    docs = app.root / "docs"
    docs.mkdir()
    (docs / "same.md").write_text("same")
    (docs / "moves.md").write_text("old")
    schema = app.files.write_root / "extraction_schema.json"
    seen = []

    class Done:
        def __init__(self, code):
            self.returncode, self.stdout, self.stderr = code, "out", ""

    def fake(command, **kwargs):
        seen.append((command, kwargs["cwd"]))
        schema.write_text("{}")
        (docs / "moves.md").write_text("new")
        (docs / "fresh.md").write_text("fresh")
        return Done(0)

    monkeypatch.setattr(server.subprocess, "run", fake)
    status, report = post(app, "/api/generate", {})
    assert status == 200 and report["ok"] is True
    # a file outside the repository is shown by its absolute path
    assert report["changed"] == sorted(["docs/fresh.md", "docs/moves.md",
                                        schema.resolve().as_posix()])
    assert report["changed"] == sorted(report["changed"])
    assert seen[0][0][1:] == ["-m", "docpipe.extraction.schema",
                              "scenarios", "--write"]
    assert all(cwd == app.root for _, cwd in seen)
    # by construction: a command that fails makes the answer not ok
    monkeypatch.setattr(server.subprocess, "run",
                        lambda *a, **k: Done(1))
    assert post(app, "/api/generate", {})[1]["ok"] is False


# -- 7. the HTTP layer ---------------------------------------------------------

@pytest.fixture
def served(tmp_path):
    app, _ = make_app(tmp_path)
    httpd = server.serve(app, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(10)


@pytest.fixture
def running(served):
    return served.server_address[1]


def fetch(port: int, method: str, path: str, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        reply = connection.getresponse()
        return reply.status, dict(reply.getheaders()), reply.read()
    finally:
        connection.close()


def test_a_foreign_host_is_refused(running):
    status, _, _ = fetch(running, "GET", "/api/state",
                         {"Host": "evil.example"})
    assert status == 403
    status, _, _ = fetch(running, "GET", "/api/state",
                         {"Host": f"localhost:{running}"})
    assert status == 200
    status, _, _ = fetch(running, "GET", "/", {"Host": "evil.example"})
    assert status == 403


def test_a_post_needs_the_pages_header_and_json(running):
    body = json.dumps({"data": {}})
    status, _, _ = fetch(running, "POST", "/api/spec/check",
                         {"Content-Type": "application/json"}, body)
    assert status == 403
    status, _, _ = fetch(running, "POST", "/api/spec/check",
                         {"Content-Type": "text/plain",
                          "X-Docpipe-Edit": "1"}, body)
    assert status == 403
    status, _, raw = fetch(running, "POST", "/api/spec/check",
                           {"Content-Type": "application/json",
                            "X-Docpipe-Edit": "1"}, "not json")
    assert status == 400 and json.loads(raw)["error"]
    status, _, _ = fetch(running, "POST", "/api/spec/check",
                         {"Content-Type": "application/json",
                          "X-Docpipe-Edit": "1",
                          "Content-Length": str(server.MAX_BODY + 1)}, b"{}")
    assert status == 413


def test_a_refusal_reaches_a_client_that_is_still_sending(served,
                                                           monkeypatch):
    """A refusal is answered before the request's body is read. A socket
    closed with unread input is reset, and a reset takes the answer with it
    where the client has not read it yet. So the server reads what the
    client still sends before it closes."""
    port = served.server_address[1]
    unread, closed = [], threading.Event()
    close = served.shutdown_request

    def closing(request):
        # what the server has left unread at the moment it closes
        ready, _, _ = select.select([request], [], [], 0.5)
        try:
            unread.append(len(request.recv(1 << 20, socket.MSG_PEEK))
                          if ready else 0)
        except OSError:
            unread.append(0)
        close(request)
        closed.set()

    monkeypatch.setattr(served, "shutdown_request", closing)

    def refused() -> bytes:
        body = b"x" * 100_000
        head = (f"POST /api/spec/check HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: text/plain\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", port),
                                      timeout=10) as sock:
            sock.sendall(head + body)
            time.sleep(0.2)                 # the client reads late
            reply = b""
            while chunk := sock.recv(65536):
                reply += chunk
        return reply

    assert refused().startswith(b"HTTP/1.0 403")
    assert closed.wait(10) and unread == [0]
    # by construction: a server that closes at once leaves the body unread,
    # which is what resets the connection
    unread.clear()
    closed.clear()
    monkeypatch.setattr(server, "LINGER", 0)
    try:
        refused()
    except OSError:
        pass
    assert closed.wait(10) and unread[0] > 0


def test_state_and_the_page_are_served(running):
    status, headers, raw = fetch(running, "GET", "/api/state")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(raw)["profile"] == "scenarios"
    status, headers, raw = fetch(running, "GET", "/")
    assert status == 200 and raw == (WEB / "index.html").read_bytes()
    assert headers["Content-Type"].startswith("text/html")
    status, headers, raw = fetch(running, "GET", "/app.js")
    assert status == 200 and headers["Content-Type"].startswith(
        "text/javascript")
    assert fetch(running, "GET", "/style.css")[0] == 200
    assert fetch(running, "GET", "/server.py")[0] == 404
    assert fetch(running, "GET", "/../server.py")[0] == 404


def test_the_server_binds_only_to_the_loopback(tmp_path):
    app, _ = make_app(tmp_path)
    httpd = server.serve(app, 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()


def test_a_taken_port_is_not_shared(tmp_path):
    app, _ = make_app(tmp_path)
    first = server.serve(app, 0)
    try:
        with pytest.raises(OSError):
            server.serve(app, first.server_address[1])
    finally:
        first.server_close()


def test_the_command_is_registered():
    from docpipe import cli
    assert "edit" in cli.OWN
    assert os.path.exists(server.WEB / "index.html")
