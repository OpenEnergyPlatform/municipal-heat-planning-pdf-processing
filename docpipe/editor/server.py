"""
server.py: The local server of `docpipe edit` and the one file guard.

`App` answers a request as plain data (method, path, query and body in, a
status and an object out), so every promise of the endpoints can be held to
without a socket. What an endpoint says comes from the logic beside it
(`specs.py`, `prompts.py`, `phrases.py`, `flow.py`, `measured.py`); this
module only reads the file, asks the logic and, where the logic says so,
writes.

`Files` is the one place the editor touches a file: it may write, and take a
file away, only inside the profile's own folder and read only inside the
folders of the profiles in
effect, the harvest it was given, the page itself, the generated
documentation and the folder the prompt review writes into
(`<temp>/docpipe-prompt-review`). One more guard writes the upstream cache
and nothing else: "Apply" of a fetch puts the fetched files and the lock
there (`sourcespage.apply`); a fetch itself writes only into a folder of its
own in the temp directory (`<temp>/docpipe-sources-fetch`). A path is
resolved first, so `..` and links cannot lead out. A trace is read by the run's own reader after the guard has
checked its path (`Files.checked`).

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
import re
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import parse_qsl, urlsplit

from .. import graphfile
from .. import phrases as phrase_files
from .. import rules as rule_files
from .. import sources as source_files
from .. import upstream
from ..extraction import flow as flow_files
from ..extraction import trace as trace_files
from . import flow as flow_view
from . import (graphpage, measured, phrases, prompts, rulespage,
               sourcespage, specs, trying)
from . import requests as recorded

LOG = logging.getLogger(__name__)

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 64 * 1024 * 1024
GIT_TIMEOUT = 10          # seconds
RUN_TIMEOUT = 600         # seconds, each generating command
LINGER = 2.0              # seconds, reading off a request that was not read
STAMP_GLOB = "*.stamp.json"
EDIT_HEADER = "X-Docpipe-Edit"
REVIEW_FOLDER = "docpipe-prompt-review"     # what render_prompts.py writes to
PROMPT_ID = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+")
PAGE_LIMIT = 500                            # requests in one answer, at most
# the notes of a recorded request the preview shows
PREVIEW_NOTES = ("parameter", "coordinate", "owner", "value", "at", "attempt",
                 "ms", "prompt_tokens", "completion_tokens", "doc")
# what the model of a try is reached with: never sent to the page
SECRET_SETTINGS = ("base_url", "api_key")
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

    def checked(self, path) -> Path:
        """*path* resolved, for a reader that opens the file itself;
        PermissionError where `open` would refuse it."""
        return self._resolve(path, False)

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
        os.makedirs(target.parent, exist_ok=True)   # inside the write root
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

    def remove(self, path) -> None:
        """A file of the profile's own folder is taken away; one that is
        not there is left as it is."""
        target = self._resolve(path, True)
        try:
            target.unlink()
        except FileNotFoundError:
            pass

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
                 root: Optional[Path] = None, cache: Optional[Path] = None,
                 fetch_root: Optional[Path] = None):
        if root is None:
            from ..profile import ROOT
            root = ROOT
        # where "Apply" writes a fetch, and where "Fetch" pulls into
        self.cache = Path(cache or upstream.CACHE).resolve()
        self.fetch_root = Path(fetch_root
                               or sourcespage.fetch_root()).resolve()
        self.cache_files = Files(self.cache, [self.fetch_root])
        self.profile = profile
        self.root = Path(root).resolve()
        self.harvest = Path(harvest).resolve() if harvest else None
        folder = Path(profile.package_dir)
        roots = [Path(p.package_dir) for p in profile.lineage()]
        self.review_root = Path(tempfile.gettempdir()) / REVIEW_FOLDER
        roots += [WEB, self.root / "docs", self.review_root]
        if self.harvest:
            roots.append(self.harvest)
        self.files = Files(folder, roots)
        self.traces = recorded.Traces(
            self.harvest, lines=lambda path: trace_files.lines(
                self.files.checked(path)))
        self.spec_path = profile.component("extraction", "SPEC_PATH")
        self._snapshot: Optional[dict] = None
        self._loaded = False
        # {trace name: (state of its file, what its requests say)}
        self._measured: dict = {}

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
            "/api/prompts": ("GET", self._prompts),
            "/api/prompt": ("GET", self._prompt),
            "/api/prompt/check": ("POST", self._prompt_check),
            "/api/prompt/save": ("POST", self._prompt_save),
            "/api/review": ("POST", self._review),
            "/api/phrases": ("GET", self._phrases),
            "/api/phrases/check": ("POST", self._phrases_check),
            "/api/phrases/save": ("POST", self._phrases_save),
            "/api/phrases/shown": ("POST", self._phrases_shown),
            "/api/requests": ("GET", self._requests),
            "/api/request/preview": ("POST", self._request_preview),
            "/api/request/try": ("POST", self._request_try),
            "/api/flow": ("GET", self._flow),
            "/api/flow/check": ("POST", self._flow_check),
            "/api/flow/save": ("POST", self._flow_save),
            "/api/flow/measured": ("POST", self._flow_measured),
            "/api/rules": ("GET", self._rules),
            "/api/rules/check": ("POST", self._rules_check),
            "/api/rules/save": ("POST", self._rules_save),
            "/api/sources": ("GET", self._sources),
            "/api/sources/check": ("POST", self._sources_check),
            "/api/sources/save": ("POST", self._sources_save),
            "/api/sources/fetch": ("POST", self._sources_fetch),
            "/api/sources/apply": ("POST", self._sources_apply),
            "/api/sources/take": ("POST", self._sources_take),
            "/api/graph": ("GET", self._graph),
            "/api/graph/check": ("POST", self._graph_check),
            "/api/graph/save": ("POST", self._graph_save),
            "/api/graph/probe": ("POST", self._graph_probe),
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
        answer = handler(query, body)
        # a handler that answers with another status gives (status, object)
        return answer if isinstance(answer, tuple) else (200, answer)

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
            "tabs": ["spec", "prompts", "flow", "sources", "graph"],
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

    # -- helpers of the prompts tab --

    @staticmethod
    def _text_of(source, key: str) -> str:
        value = source.get(key) if isinstance(source, dict) else None
        if not isinstance(value, str):
            raise _Refusal(400, f"\"{key}\" is needed, as text")
        return value

    def _prompt_id(self, source) -> str:
        value = self._text_of(source, "id")
        if not PROMPT_ID.fullmatch(value):
            raise _Refusal(404, f"no such prompt: {value!r}")
        return value

    def _disk(self, prompt_id: str) -> dict:
        """The file a run loads for the prompt, with its bytes."""
        try:
            return prompts.on_disk(self.profile, prompt_id, self.files.read)
        except FileNotFoundError:
            raise _Refusal(404, f"profile {self.profile.name!r} has no "
                                f"prompt {prompt_id!r}") from None

    def _module(self, source) -> str:
        value = self._text_of(source, "module")
        if value not in phrase_files.MODULES:
            raise _Refusal(404, f"no such module: {value!r}; one of "
                                f"{list(phrase_files.MODULES)}")
        return value

    def _trace(self, source):
        name = self._text_of(source, "trace")
        try:
            return self.traces.load(name)
        except KeyError:
            raise _Refusal(404, f"no such trace: {name!r}") from None

    @staticmethod
    def _edits(body) -> dict:
        edits = body.get("edits", {})
        if not isinstance(edits, dict) or not all(
                isinstance(text, str) for text in edits.values()):
            raise _Refusal(400, "\"edits\" is an object: prompt id -> its "
                                "text")
        return edits

    @staticmethod
    def _whole(query: dict, key: str, default: int, least: int) -> int:
        try:
            value = int(query.get(key) or default)
        except (TypeError, ValueError):
            raise _Refusal(400, f"{key} must be a whole number") from None
        if value < least:
            raise _Refusal(400, f"{key} must be at least {least}")
        return value

    def _report(self, report: dict) -> dict:
        """A report of the logic for the page: what a save writes is
        dropped, a path is shown."""
        out = {key: value for key, value in report.items() if key != "text"}
        if out.get("creates") is not None:
            out["creates"] = self.shown(out["creates"])
        return out

    @staticmethod
    def _moved(what: str) -> tuple:
        return 409, {"saved": False, "reason": "moved",
                     "message": f"{what} changed on disk since the page "
                                f"loaded it; reload it before saving"}

    # -- the prompts --

    def _no_trace(self) -> Optional[str]:
        """Why the page has no recorded request to show, None where the
        harvest folder holds a trace."""
        if self.traces.names():
            return None
        return ("no harvest folder was given (--harvest)"
                if self.harvest is None
                else "the harvest folder holds no trace (*.trace.jsonl.gz)")

    def _prompts(self, query, body) -> dict:
        found = self.traces.names()
        note = self._no_trace()
        return {
            "profile": self.profile.name,
            "lineage": [one.name for one in self.profile.lineage()],
            "prompts": prompts.listing(self.profile),
            "modules": list(phrase_files.MODULES),
            "try": {key: value for key, value in trying.settings().items()
                    if key not in SECRET_SETTINGS},
            "traces": found, "traces_note": note}

    def _prompt(self, query, body) -> dict:
        prompt_id = self._prompt_id(query)
        self._disk(prompt_id)                   # 404 where nobody has it
        shown = prompts.detail(self.profile, prompt_id, self.files.read)
        for key in ("path", "target"):
            shown[key] = self.shown(shown[key])
        return shown

    def _prompt_check(self, query, body) -> dict:
        prompt_id = self._prompt_id(body)
        raw = self._text_of(body, "raw")
        return self._report(prompts.judge(self.profile, prompt_id, raw,
                                          self._disk(prompt_id)))

    def _prompt_save(self, query, body):
        prompt_id = self._prompt_id(body)
        raw = self._text_of(body, "raw")
        disk = self._disk(prompt_id)
        if body.get("base") != sha256(disk["bytes"]):
            return self._moved("the prompt")
        report, data, target = prompts.save(self.profile, prompt_id, raw,
                                            disk)
        report = self._report(report)
        if data is not None:
            self.files.write(target, data)
            report["sha256"] = sha256(data)
            report["path"] = self.shown(target)
        return report

    def _review(self, query, body) -> dict:
        name = self.profile.name
        steps = [("profile check", [sys.executable, "-m", "docpipe",
                                    "preflight", "--profile", name]),
                 ("before and after",
                  [sys.executable, "scripts/render_prompts.py", "--profile",
                   name, "--before", "HEAD"])]
        environment = dict(os.environ, PYTHONUTF8="1")
        out = []
        for title, command in steps:
            step = {"name": title, "command": " ".join(command[1:])}
            try:
                done = subprocess.run(
                    command, cwd=self.root, env=environment,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=RUN_TIMEOUT)
            except (OSError, subprocess.SubprocessError) as exc:
                step.update(ok=False, stdout="",
                            output=f"{type(exc).__name__}: {exc}")
            else:
                step.update(ok=done.returncode == 0, stdout=done.stdout,
                            output=done.stdout + done.stderr)
            out.append(step)
        out[1]["summary"] = self._summary(out[1].get("stdout", ""))
        for step in out:
            step.pop("stdout", None)
        return {"ok": all(step["ok"] for step in out), "steps": out}

    def _summary(self, printed: str) -> Optional[str]:
        """The summary.md of the folder render_prompts.py names in its last
        line, None where it names none or the file cannot be read."""
        lines = [line for line in printed.splitlines() if line.strip()]
        if not lines or not lines[-1].startswith("written to "):
            return None
        folder = lines[-1][len("written to "):].strip()
        try:
            return self.files.read(Path(folder) / "summary.md").decode(
                "utf-8", errors="replace")
        except OSError:                 # PermissionError among them
            return None

    # -- the sentences --

    def _phrases(self, query, body) -> dict:
        module = self._module(query)
        shown = phrases.detail(self.profile, module, self.files.read)
        shown["path"] = self.shown(shown["path"])
        return shown

    @staticmethod
    def _table(body) -> dict:
        table = body.get("table")
        if not isinstance(table, dict):
            raise _Refusal(400, "\"table\" is an object: the name of a "
                                "sentence -> its words")
        return table

    def _phrases_check(self, query, body) -> dict:
        module = self._module(body)
        return self._report(phrases.judge(self.profile, module,
                                          self._table(body),
                                          self.files.read))

    def _phrases_save(self, query, body):
        module = self._module(body)
        table = self._table(body)
        own = phrase_files.path_of(self.profile, module)
        current = sha256(self.files.read(own)) if own.is_file() else None
        if body.get("base") != current:
            return self._moved("the sentence file")
        report, data, target = phrases.save(
            self.profile, module, table, self.files.read,
            confirm=bool(body.get("confirm")))
        report = self._report(report)
        if data is not None:
            self.files.write(target, data)
            report["sha256"] = sha256(data)
            report["path"] = self.shown(target)
        return report

    def _phrases_shown(self, query, body) -> dict:
        module = self._module(body)
        key = self._text_of(body, "key")
        new = self._text_of(body, "text")
        trace = self._trace(body)
        made = phrases.detail(self.profile, module, self.files.read)
        row = next((one for one in made["sentences"] if one["key"] == key),
                   None)
        if row is None:
            raise _Refusal(404, f"no sentence {key!r} in {module}")
        old = row["text"][0] if isinstance(row["text"], list) \
            else row["text"]
        return phrases.shown_in(trace.requests, old, new)

    # -- the flow --

    def _flow_file(self) -> tuple:
        """(the profile's own flow file, its bytes or None where it has
        none), every file of the flow's line checked by the guard before
        the run's loader reads it."""
        for _name, path in flow_files.line(self.profile):
            self.files.checked(path)
        own = flow_files.path_of(self.profile)
        return own, (self.files.read(own) if own.is_file() else None)

    def _computes(self) -> bool:
        return self.profile.component("compute", "questions") is not None

    def _flow(self, query, body) -> dict:
        own, raw = self._flow_file()
        data = specs.parse(self.files.read(self.spec_path)) \
            if self.spec_path else None
        return {**flow_view.view(self.profile, raw, data, self.shown,
                                 self._computes()),
                "harvest": self.harvest is not None,
                "traces": self.traces.names()}

    def _flow_check(self, query, body) -> dict:
        own, raw = self._flow_file()
        report = flow_view.judge(self.profile, raw, body.get("numbers"),
                                 self.shown(own), body.get("order"),
                                 body.get("off"))
        report.pop("text", None)        # the page gets the diff
        return report

    def _flow_save(self, query, body) -> dict:
        own, raw = self._flow_file()
        report, written, remove = flow_view.save(
            self.profile, raw, body.get("numbers"), body.get("base"),
            self.shown(own), body.get("order"), body.get("off"))
        if written is not None:
            self.files.write(own, written)
        elif remove:
            self.files.remove(own)
        return report

    def _facts(self, name: str) -> dict:
        """What the requests of the trace *name* say (`measured.facts`),
        counted once per state of its file."""
        path = self.traces.path_of(name)
        if path is None:
            raise _Refusal(404, f"no such trace: {name!r}")
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        hit = self._measured.get(name)
        if hit is None or hit[0] != key:
            hit = (key, measured.facts(measured.light(
                trace_files.lines(self.files.checked(path)))))
            self._measured[name] = hit
        return hit[1]

    def _flow_measured(self, query, body) -> dict:
        numbers = body.get("numbers")
        numbers = numbers if isinstance(numbers, dict) else {}
        names = [one["name"] for one in self.traces.names()]
        why = self._no_trace()
        if why:
            return {"harvest": self.harvest is not None, "why": why,
                    "traces": 0, "requests": 0, "says": {}, "steps": {},
                    "notes": []}
        wanted = body.get("trace")
        if wanted is not None and not isinstance(wanted, str):
            raise _Refusal(400, "trace must be the name of a trace or null")
        found = measured.joined([self._facts(name) for name
                                 in ([wanted] if wanted else names)])
        return {"harvest": True, "why": None,
                "traces": 1 if wanted else len(names),
                "requests": found["requests"],
                "says": measured.says(found, numbers),
                "steps": found["steps"], "notes": measured.notes(found)}

    # -- the rules --

    def _rules_file(self) -> tuple:
        """(the profile's own rules file, its bytes or None where it has
        none), every file of the rules' line checked by the guard before
        the run's loader reads it."""
        for _name, path in rule_files.line(self.profile):
            self.files.checked(path)
        own = rule_files.path_of(self.profile)
        return own, (self.files.read(own) if own.is_file() else None)

    def _rules(self, query, body) -> dict:
        tab = query.get("tab") or "spec"
        if tab not in rule_files.TABS:
            raise _Refusal(400, f"tab must be one of "
                                f"{', '.join(rule_files.TABS)}, not {tab!r}")
        own, raw = self._rules_file()
        return rulespage.view(self.profile, tab, raw, self.shown)

    def _rules_check(self, query, body) -> dict:
        own, raw = self._rules_file()
        report = rulespage.judge(self.profile, raw, body.get("values"),
                                 self.shown(own))
        report.pop("text", None)
        return report

    def _rules_save(self, query, body) -> dict:
        own, raw = self._rules_file()
        report, written, remove = rulespage.save(
            self.profile, raw, body.get("values"), body.get("base"),
            self.shown(own))
        if written is not None:
            self.files.write(own, written)
        elif remove:
            self.files.remove(own)
        if written is not None or remove:
            rule_files.reset()
        return report

    # -- the sources --

    def _sources_file(self) -> tuple:
        own = source_files.path_of(self.profile)
        return own, (self.files.read(own) if own.is_file() else None)

    def _spec_raw(self) -> Optional[dict]:
        if self.spec_path is None or not Path(self.spec_path).is_file():
            return None
        return specs.parse(self.files.read(self.spec_path))

    def _sources(self, query, body) -> dict:
        own, raw = self._sources_file()
        return sourcespage.view(self.profile, raw, self.shown, self.cache,
                                self.snapshot(), self._spec_raw())

    def _sources_check(self, query, body) -> dict:
        own, raw = self._sources_file()
        report = sourcespage.judge(self.profile, raw, body.get("data"),
                                   self.shown(own))
        report.pop("text", None)
        return report

    def _sources_save(self, query, body) -> dict:
        own, raw = self._sources_file()
        report, written = sourcespage.save(self.profile, raw,
                                           body.get("data"),
                                           body.get("base"), self.shown(own))
        if written is not None:
            self.files.write(own, written)
        return report

    def _sources_fetch(self, query, body) -> dict:
        try:
            return sourcespage.fetch(self.profile, self.fetch_root,
                                     self.cache, self._spec_raw())
        except (upstream.UpstreamError, OSError) as exc:
            raise _Refusal(502, f"the fetch failed and wrote nothing outside "
                                f"{self.shown(self.fetch_root)}: {exc}")
        except ValueError as exc:
            raise _Refusal(400, str(exc))

    def _fetch_of(self, body) -> Optional[Path]:
        wanted = body.get("fetch")
        if wanted is None:
            return None
        try:
            return sourcespage.fetched(self.fetch_root, wanted)
        except ValueError as exc:
            raise _Refusal(404, str(exc))

    def _sources_apply(self, query, body) -> dict:
        where = self._fetch_of(body)
        if where is None:
            raise _Refusal(400, "the body needs \"fetch\": the id a fetch "
                                "answered with")
        done = sourcespage.apply(self.profile, where, self.files.write,
                                 self.cache_files.write, self.cache)
        forget = self.profile.component("vocabulary", "forget")
        if forget is not None:
            forget()
        self._loaded = False
        done["lock"] = self.shown(done["lock"])
        done["profile_files"] = [self.shown(one)
                                 for one in done["profile_files"]]
        return done

    def _sources_take(self, query, body) -> dict:
        spec_raw = self._spec_raw()
        if spec_raw is None:
            raise _Refusal(404, f"profile {self.profile.name!r} has no "
                                f"extraction spec")
        where = self._fetch_of(body)
        if where is None:
            snapshot = self.snapshot()
            files = sourcespage.shape_files(self.profile, self.cache)
        else:
            snapshot = sourcespage._snapshot_of(
                where / "profile" / "vocabulary.json")
            files = sourcespage.shape_files(self.profile, where / "cache")
        chosen = body.get("chosen")
        if not isinstance(chosen, list):
            raise _Refusal(400, "the body needs \"chosen\": a list of "
                                "{id, action, into}")
        return sourcespage.take(spec_raw, chosen, snapshot, self.profile,
                                files)

    # -- the graph --

    def _graph_file(self) -> tuple:
        for _name, path in graphfile.line(self.profile):
            self.files.checked(path)
        own = graphfile.path_of(self.profile)
        return own, (self.files.read(own) if own.is_file() else None)

    def _graph(self, query, body) -> dict:
        own, raw = self._graph_file()
        return graphpage.view(
            self.profile, raw, self.shown, self._spec_raw(),
            sourcespage.shape_files(self.profile, self.cache),
            self.snapshot())

    def _graph_check(self, query, body) -> dict:
        own, raw = self._graph_file()
        report = graphpage.judge(self.profile, raw, body.get("data"),
                                 self.shown(own))
        report.pop("text", None)
        return report

    def _graph_save(self, query, body) -> dict:
        own, raw = self._graph_file()
        report, written, remove = graphpage.save(
            self.profile, raw, body.get("data"), body.get("base"),
            self.shown(own))
        if written is not None:
            self.files.write(own, written)
        elif remove:
            self.files.remove(own)
        if written is not None or remove:
            graphfile.reset()
        return report

    def _graph_probe(self, query, body) -> dict:
        if self.harvest is None:
            raise _Refusal(400, "the page was started without a harvest "
                                "(docpipe edit --harvest DIR): there is "
                                "nothing to write a graph of")
        db = body.get("db") or getattr(self.profile, "db_path", None)
        if not db or not Path(db).is_file():
            raise _Refusal(400, f"no corpus database at {db}: give \"db\"")
        try:
            return graphpage.probe(self.profile, body.get("data"),
                                   self.harvest, Path(db),
                                   stamp=time.strftime("%Y%m%d-%H%M%S"))
        except graphfile.GraphError as exc:
            raise _Refusal(400, str(exc))
        except (RuntimeError, subprocess.SubprocessError) as exc:
            raise _Refusal(502, str(exc))

    # -- the recorded requests --

    def _requests(self, query, body) -> dict:
        trace = self._trace(query)
        offset = self._whole(query, "offset", 0, 0)
        limit = min(self._whole(query, "limit", 100, 1), PAGE_LIMIT)
        every = trace.requests
        scope = list(range(len(every)))
        wanted = query.get("prompt")
        if wanted:
            if wanted not in {one["id"] for one
                              in prompts.listing(self.profile)}:
                raise _Refusal(404, f"no such prompt: {wanted!r}")
            scope = [i for i in scope
                     if prompts.concerns(wanted, every[i])]
        kind, field = query.get("kind"), query.get("field")
        carries, text = query.get("carries"), query.get("text")
        matching = [i for i in scope
                    if recorded.keep(every[i],
                                     kinds=[kind] if kind else (),
                                     fields=[field] if field else (),
                                     contains=[text] if text else ())
                    and (not carries or carries in trace.carried(i))]
        rows = []
        for i in matching[offset:offset + limit]:
            request = every[i]
            row = {key: request.get(key) for key in (
                "kind", "asked", "parameter", "coordinate", "owner",
                "value", "at", "attempt", "ms", "prompt_tokens",
                "completion_tokens", "check")}
            rows.append({"index": i, **row})
        return {
            "trace": trace_files.name_of(trace.path),
            "total": len(every), "matching": len(matching),
            "kinds": sorted({every[i]["kind"] for i in scope}),
            "fields": sorted({every[i]["parameter"] for i in scope
                              if every[i].get("parameter") is not None}),
            "carried": sorted({name for i in scope
                               for name in trace.carried(i)}),
            "requests": rows}

    def _request_of(self, body) -> tuple:
        """(the trace, the number of the request) a body names."""
        trace = self._trace(body)
        index = body.get("index")
        if type(index) is not int:
            raise _Refusal(400, "\"index\" is a whole number")
        if not 0 <= index < len(trace.requests):
            raise _Refusal(404, f"the trace has no request {index}")
        return trace, index

    def _request_preview(self, query, body) -> dict:
        trace, index = self._request_of(body)
        edits = self._edits(body)
        request = trace.requests[index]
        return {
            "index": index, "kind": request["kind"],
            "asked": request.get("asked"),
            "notes": {key: request[key] for key in PREVIEW_NOTES
                      if key in request},
            "recorded": {
                "system": request["system"], "messages": request["messages"],
                "answer": request["answer"],
                "answer_json": request["answer_json"],
                "finish": request["finish"], "error": request["error"],
                "check": request["check"], "spelled": request["spelled"]},
            "chain": recorded.chain_of(trace.requests, index),
            "preview": prompts.preview(self.profile, request,
                                       trace.sent(index) or {}, edits,
                                       self.files.read)}

    def _request_try(self, query, body) -> dict:
        trace = self._trace(body)
        indexes = body.get("indexes")
        if not isinstance(indexes, list) \
                or any(type(one) is not int for one in indexes):
            raise _Refusal(400, "\"indexes\" is a list of whole numbers")
        edits = self._edits(body)
        try:
            return trying.run(self.profile, trace, indexes, edits,
                              self.files.read)
        except trying.Refused as exc:
            raise _Refusal(400, str(exc)) from None


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
        description="A profile's extraction spec, its prompts, the "
                    "sentences beside them and the numbers of its flow in "
                    "the browser, on a local "
                    "page (127.0.0.1 only). It writes only inside the "
                    "profile's folder. Nothing leaves this machine but "
                    "the requests of a click on Try, which go to the "
                    "model the installation names for it "
                    "(EDIT_TRY_BASE_URL).")
    parser.add_argument("--harvest", metavar="DIR",
                        help="a folder with a harvest, its stamps and "
                             "traces (a local copy): an edit of the spec "
                             "then says which documents it makes stale, "
                             "a prompt is shown with the requests "
                             "recorded there, and the flow says beside its "
                             "numbers what that run measured")
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
