"""
server.py: The local server of `docpipe edit` and the one file guard.

`App` answers a request as plain data (method, path, query and body in, a
status and an object out), so every promise of the endpoints can be held to
without a socket. What an endpoint says comes from `specs.py`; this module
only reads the file, asks the logic and, where the logic says so, writes.

`Files` is the one place the editor touches a file: it may write only inside
the profile's own folder and read only inside the folders of the profiles in
effect, the harvest it was given, the page itself and the generated
documentation. A path is resolved first, so `..` and links cannot lead out.

The HTTP layer binds 127.0.0.1 only, answers only a `Host` it knows (a page
of another site cannot reach the server by a name of its own) and takes a
POST only with the header the page sends (a form on another site cannot send
it). A request it answers without having read it to the end, a refusal, is
read off before the connection closes, so that the answer arrives. The
standard library is all this needs.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import parse_qsl, urlsplit

from . import specs

LOG = logging.getLogger(__name__)

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 64 * 1024 * 1024
GIT_TIMEOUT = 10          # seconds
RUN_TIMEOUT = 600         # seconds, each generating command
LINGER = 2.0              # seconds, reading off a request that was not read
STAMP_GLOB = "*.stamp.json"
EDIT_HEADER = "X-Docpipe-Edit"
# what is served at "/": path -> (file in WEB, content type)
PAGES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/style.css": ("style.css", "text/css; charset=utf-8")}


# -- the one file guard --------------------------------------------------------

class Files:
    """Every byte the editor reads or writes itself goes through `open`."""

    def __init__(self, write_root: Path, read_roots: Sequence[Path]):
        self.write_root = Path(write_root).resolve()
        self.read_roots = [Path(root).resolve() for root in read_roots]

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        return path == root or root in path.parents

    def _allowed(self, path: Path, writing: bool) -> bool:
        if self._inside(path, self.write_root):
            return True
        return not writing and any(self._inside(path, root)
                                   for root in self.read_roots)

    def _resolve(self, path, writing: bool) -> Path:
        resolved = Path(path).resolve()
        if not self._allowed(resolved, writing):
            raise PermissionError(
                f"{path} is outside what the editor may "
                f"{'write' if writing else 'read'}")
        return resolved

    def open(self, path, mode: str = "rb"):
        writing = any(flag in mode for flag in "wax+")
        return open(self._resolve(path, writing), mode)

    def read(self, path) -> bytes:
        with self.open(path, "rb") as handle:
            return handle.read()

    def write(self, path, data: bytes) -> None:
        """The whole file or the old one: written beside it, then put in its
        place."""
        target = self._resolve(path, True)
        temporary = target.with_name(target.name + ".editing")
        try:
            with self.open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def digest(self, path) -> str:
        """The sha256 of a file's bytes, as hex."""
        sha = hashlib.sha256()
        with self.open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                sha.update(block)
        return sha.hexdigest()

    def stamps(self, folder) -> list:
        """The stamp files directly in a folder, sorted."""
        resolved = self._resolve(folder, False)
        return sorted(resolved.glob(STAMP_GLOB))

    def tree(self, folder) -> list:
        """Every file below a folder, sorted; [] where there is none."""
        resolved = self._resolve(folder, False)
        if not resolved.is_dir():
            return []
        return sorted(path for path in resolved.rglob("*")
                      if path.is_file())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- the application -----------------------------------------------------------

class _Refusal(Exception):
    """An answer the endpoint gives instead of a result."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class App:
    """The endpoints of CONTRACT section 3, without a socket."""

    def __init__(self, profile, harvest: Optional[Path] = None,
                 root: Optional[Path] = None):
        if root is None:
            from ..profile import ROOT
            root = ROOT
        self.profile = profile
        self.root = Path(root).resolve()
        self.harvest = Path(harvest).resolve() if harvest else None
        folder = Path(profile.package_dir)
        roots = [Path(p.package_dir) for p in profile.lineage()]
        roots += [WEB, self.root / "docs"]
        if self.harvest:
            roots.append(self.harvest)
        self.files = Files(folder, roots)
        self.spec_path = profile.component("extraction", "SPEC_PATH")
        self._snapshot: Optional[dict] = None
        self._loaded = False

    # -- helpers --

    def shown(self, path) -> str:
        """A path as the user sees it: relative to the repository with
        forward slashes where it lies under it, else absolute."""
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError:
            return resolved.as_posix()

    def snapshot(self) -> Optional[dict]:
        """The ontology snapshot of the profile, loaded once; None where the
        profile has none."""
        if not self._loaded:
            load = self.profile.component("vocabulary", "load")
            self._snapshot = load() if load else None
            self._loaded = True
        return self._snapshot

    def _stamps(self) -> Optional[list]:
        return None if self.harvest is None \
            else self.files.stamps(self.harvest)

    def _git(self, *args: str) -> Optional[str]:
        try:
            done = subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=GIT_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    def _need_spec(self) -> Path:
        if self.spec_path is None:
            raise _Refusal(404, f"profile {self.profile.name!r} has no "
                                f"extraction spec")
        return Path(self.spec_path)

    @staticmethod
    def _need_data(body) -> dict:
        if not isinstance(body, dict):
            raise _Refusal(400, "the body must be a JSON object")
        if not isinstance(body.get("data"), dict):
            raise _Refusal(400, "the body needs \"data\": the spec as an "
                                "object")
        return body["data"]

    # -- the request --

    def call(self, method: str, path: str, query: dict,
             body) -> tuple:
        """(status, object) of a request: nothing is raised."""
        try:
            return self._route(method.upper(), path, query or {}, body)
        except _Refusal as exc:
            return exc.status, {"error": exc.message}
        except PermissionError as exc:
            return 403, {"error": str(exc)}
        except Exception as exc:
            LOG.exception("%s %s failed", method, path)
            return 500, {"error": f"{type(exc).__name__}: {exc}"}

    def _route(self, method: str, path: str, query: dict, body) -> tuple:
        routes = {
            "/api/state": ("GET", self._state),
            "/api/spec": ("GET", self._spec),
            "/api/spec/check": ("POST", self._check),
            "/api/spec/save": ("POST", self._save),
            "/api/spec/copy": ("POST", self._copy),
            "/api/spec/remove": ("POST", self._remove),
            "/api/terms": ("GET", self._terms),
            "/api/generate": ("POST", self._generate),
        }
        if path not in routes:
            raise _Refusal(404, f"no such endpoint: {path}")
        wanted, handler = routes[path]
        if method != wanted:
            raise _Refusal(405, f"{path} takes {wanted}")
        if wanted == "POST" and not isinstance(body, dict):
            raise _Refusal(400, "the body must be a JSON object")
        if path.startswith("/api/spec"):
            self._need_spec()
        return 200, handler(query, body)

    # -- endpoints --

    def _state(self, query, body) -> dict:
        folder = Path(self.profile.package_dir)
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        status = self._git("status", "--porcelain", "--", str(folder))
        changed: list = []
        for line in (status or "").splitlines():
            name = line[3:].split(" -> ")[-1].strip().strip('"')
            if name:
                changed.append(name)
        return {
            "profile": self.profile.name,
            "spec": self.shown(self.spec_path) if self.spec_path else None,
            "branch": branch.strip() if branch else None,
            "changed": changed,
            "harvest": self.harvest.as_posix() if self.harvest else None,
            "harvest_documents": (len(self.files.stamps(self.harvest))
                                  if self.harvest else None),
            "tabs": ["spec"],
        }

    def _spec(self, query, body) -> dict:
        raw = self.files.read(self._need_spec())
        data = specs.parse(raw)
        snapshot = self.snapshot()
        return {"data": data, "base": sha256(raw), "form": specs.form(),
                "pin": specs.pin(data, snapshot) if snapshot else {},
                "notes": specs.notes(data, snapshot) if snapshot else []}

    def _check(self, query, body) -> dict:
        data = self._need_data(body)
        spec = self._need_spec()
        report = specs.judge(self.files.read(spec), data, self._stamps(),
                             self.snapshot(), self.shown(spec))
        report.pop("text", None)        # the page gets the diff
        return report

    def _save(self, query, body) -> dict:
        data = self._need_data(body)
        spec = self._need_spec()
        raw = self.files.read(spec)
        if body.get("base") != sha256(raw):
            return {"saved": False, "reason": "moved",
                    "message": "the file changed on disk since the page "
                               "loaded it; reload it before saving"}
        report, written = specs.save(
            raw, data, confirm=bool(body.get("confirm")),
            stamps=self._stamps(), snapshot=self.snapshot(),
            name=self.shown(spec))
        if written is not None:
            self.files.write(spec, written)
            report["base"] = sha256(written)
        return report

    def _copy(self, query, body) -> dict:
        data = self._need_data(body)
        kind = body.get("kind")
        try:
            if kind == "field":
                made = specs.copy_field(data, body.get("field"),
                                        body.get("key"))
            elif kind == "coordinate":
                made = specs.copy_coordinate(
                    data, body.get("field"), body.get("coordinate"),
                    body.get("key"))
            else:
                raise _Refusal(400, f"kind must be field or coordinate, "
                                    f"not {kind!r}")
        except specs.Refused as exc:
            return {"ok": False, "error": exc.said()}
        return {"ok": True, "data": made}

    def _remove(self, query, body) -> dict:
        data = self._need_data(body)
        kind = body.get("kind")
        if not isinstance(kind, str):
            raise _Refusal(400, "the body needs \"kind\"")
        named = {key: value for key, value in body.items()
                 if key not in ("data", "kind")}
        try:
            made = specs.remove(data, kind, **named)
        except specs.Refused as exc:
            return {"ok": False, "error": exc.said()}
        return {"ok": True, "data": made}

    def _terms(self, query, body) -> dict:
        snapshot = self.snapshot()
        if not snapshot:
            return {"terms": [], "total": 0}
        try:
            limit = int(query.get("limit", 50))
        except (TypeError, ValueError):
            raise _Refusal(400, "limit must be a whole number") from None
        return specs.terms(snapshot, query.get("q", ""), limit)

    def _generated(self) -> dict:
        """{path: sha256} of what the generating commands write."""
        paths = self.files.tree(self.root / "docs")
        schema = Path(self.profile.package_dir) / "extraction_schema.json"
        if schema.is_file():
            paths.append(schema)
        return {path.resolve(): self.files.digest(path) for path in paths}

    def _generate(self, query, body) -> dict:
        commands = [[sys.executable, "-m", "docpipe.extraction.schema",
                     self.profile.name, "--write"]]
        if (self.root / "scripts" / "build_docs.py").exists():
            commands.append([sys.executable, "scripts/build_docs.py",
                             "--out", "docs"])
        before = self._generated()
        environment = dict(os.environ, PYTHONUTF8="1")
        ok, printed = True, []
        for command in commands:
            try:
                done = subprocess.run(
                    command, cwd=self.root, env=environment,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=RUN_TIMEOUT)
            except (OSError, subprocess.SubprocessError) as exc:
                ok = False
                printed.append(f"{' '.join(command[1:])}: "
                               f"{type(exc).__name__}: {exc}")
                continue
            ok = ok and done.returncode == 0
            printed.append(done.stdout + done.stderr)
        after = self._generated()
        changed = sorted(self.shown(path) for path, digest in after.items()
                         if before.get(path) != digest)
        return {"ok": ok, "changed": changed,
                "output": "\n".join(text for text in printed if text)}


# -- HTTP ----------------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server take a port that is in
    # use, so a taken port would not be noticed.
    allow_reuse_address = False
    daemon_threads = True
    app: App


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    body_read = False

    def log_message(self, format, *args):
        LOG.debug(format, *args)

    def finish(self) -> None:
        if not self._request_read():
            self._read_off()
        super().finish()

    def _request_read(self) -> bool:
        """Whether nothing the client sent for its request is unread: its
        headers were parsed, and its body was read or it has none."""
        headers = getattr(self, "headers", None)
        if headers is None:
            return False
        if self.body_read:
            return True
        return not headers.get("Transfer-Encoding") and (
            headers.get("Content-Length") or "0").strip() == "0"

    def _read_off(self) -> None:
        """Ends the answer and reads what the client still sends, for at
        most LINGER seconds. A socket closed with unread input is reset, and
        a reset takes the answer with it where the client has not read it
        yet (Windows drops what it had received)."""
        end = time.monotonic() + LINGER
        try:
            self.connection.shutdown(socket.SHUT_WR)
            while (left := end - time.monotonic()) > 0:
                self.connection.settimeout(left)
                if not self.connection.recv(65536):
                    break
        except OSError:
            pass

    def _send(self, status: int, payload: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False)
                   .encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}",
                                            f"localhost:{port}")

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "unknown Host"})
        parts = urlsplit(self.path)
        if parts.path.startswith("/api/"):
            status, obj = self.server.app.call(
                "GET", parts.path, dict(parse_qsl(parts.query,
                                                  keep_blank_values=True)),
                None)
            return self._json(status, obj)
        if parts.path not in PAGES:
            return self._json(404, {"error": f"not found: {parts.path}"})
        name, kind = PAGES[parts.path]
        try:
            payload = self.server.app.files.read(WEB / name)
        except (OSError, PermissionError) as exc:
            return self._json(500, {"error": f"{type(exc).__name__}: "
                                             f"{exc}"})
        self._send(200, payload, kind)

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "unknown Host"})
        kind = (self.headers.get("Content-Type") or "").split(";")[0]
        if kind.strip().lower() != "application/json" \
                or self.headers.get(EDIT_HEADER) != "1":
            return self._json(403, {"error": f"a POST needs Content-Type: "
                                             f"application/json and the "
                                             f"header {EDIT_HEADER}: 1"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            return self._json(400, {"error": "bad Content-Length"})
        if length > MAX_BODY:
            self.close_connection = True
            return self._json(413, {"error": "the body is over 64 MB"})
        raw = self.rfile.read(length)
        self.body_read = True
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = None                 # the app answers 400
        parts = urlsplit(self.path)
        status, obj = self.server.app.call("POST", parts.path, {}, body)
        self._json(status, obj)


def serve(app: App, port: int) -> ThreadingHTTPServer:
    """The server bound to 127.0.0.1 (port 0: a free one), not yet
    running."""
    httpd = _Server(("127.0.0.1", port), _Handler)
    httpd.app = app
    return httpd


# -- the command ---------------------------------------------------------------

def command(rest: Sequence[str]) -> int:
    from ..profile import ENV_VAR, active_profile
    parser = argparse.ArgumentParser(
        prog="docpipe edit",
        description="A profile's extraction spec in the browser, on a "
                    "local page (127.0.0.1 only). Nothing leaves this "
                    "machine; the only file written is the spec.")
    parser.add_argument("--harvest", metavar="DIR",
                        help="a folder with a harvest, its stamps and "
                             "traces (a local copy): an edit then says "
                             "which documents it makes stale")
    parser.add_argument("--port", type=int, default=8765,
                        help="default 8765; a free one if it is taken")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open the page")
    args = parser.parse_args(list(rest))
    harvest = None
    if args.harvest:
        harvest = Path(args.harvest).expanduser()
        if not harvest.is_dir():
            parser.error(f"--harvest {args.harvest}: no such folder")
    profile = active_profile()
    if profile is None:
        raise SystemExit(f"docpipe edit needs a profile: pass --profile "
                         f"NAME (or set ${ENV_VAR})")
    app = App(profile, harvest)
    try:
        httpd = serve(app, args.port)
    except OSError:
        httpd = serve(app, 0)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"docpipe edit: profile {profile.name} at {url} "
          f"(Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
