"""
upstream.py: Pulls the files a profile is written against, at the version
upstream currently calls its own.

A profile names its sources in `profiles/<name>/vocabulary.py: SOURCES`. This
module resolves each one to a version, downloads it into a cache keyed by that
version, and returns a record of what it got. What a file is for (a closure to
snapshot, shapes to validate against, regions to offer) is the profile's.

Three kinds:

  release_asset  An asset of the repository's latest GitHub release. A
                 repository without a release is an error, unless the source
                 says `until_released`: then it is skipped with a note.
  repo_files     Files at the head of a branch. The version is a digest over
                 their bytes. A source may name the commit its profile was
                 `reviewed` against, and the record then lists every file that
                 differs from that commit.
  sparql         A query against the OEKG endpoint. The token comes from the
                 environment variable `token_env` names and is written nowhere.

Only github.com and raw.githubusercontent.com are asked, never
api.github.com: the API allows 60 unauthenticated requests an hour per
address, and every user of a shared machine shares one address.

Network access goes through urllib with the proxy settings the environment
already has. A source that cannot be fetched raises. A run against an old
ontology that believes it has the current one is what this module prevents.

Author: Felix Vossel
"""
from __future__ import annotations

import datetime
import hashlib
import http.client
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from docpipe.profile import ROOT

CACHE = Path(os.environ.get("DOCPIPE_UPSTREAM_CACHE")
             or ROOT / "data" / "upstream")
GITHUB = "https://github.com"
RAW = "https://raw.githubusercontent.com"
TIMEOUT = 120
AGENT = {"User-Agent": "docpipe-upstream"}


class UpstreamError(RuntimeError):
    """A source that could not be resolved or fetched.

    `status` is the HTTP status when there was one, so a file that does not
    exist (404) can be told apart from a server or a network that failed.
    """

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url: str, *, data: Optional[bytes] = None,
         headers: Optional[dict] = None) -> bytes:
    request = urllib.request.Request(url, data=data,
                                     headers={**AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"{url}: HTTP {exc.code}", exc.code) from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        # HTTPException covers IncompleteRead: a transfer the connection cut
        # short is neither an OSError nor a URLError.
        raise UpstreamError(f"{url}: {exc!r}") from exc


def _location(url: str) -> Optional[str]:
    """Where `url` redirects to, without following it; None if it does not."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=AGENT)
    try:
        with opener.open(request, timeout=TIMEOUT):
            return None
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc.headers.get("Location")
        raise UpstreamError(f"{url}: HTTP {exc.code}", exc.code) from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise UpstreamError(f"{url}: {exc!r}") from exc


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _store(url: str, target: Path, *, reuse: bool) -> dict:
    """Download `url` to `target` and describe the file.

    `reuse` for a file whose name already fixes its content (a release tag, a
    commit): it is kept if present. A branch head is always fetched again.
    """
    if not (reuse and target.is_file()):
        body = _get(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(body)
        partial.replace(target)
    return {"url": url, "path": str(target), "sha256": sha256(target),
            "bytes": target.stat().st_size}


def latest_release(repo: str) -> Optional[str]:
    """The tag of the latest release, or None if the repository has none.

    github.com answers /releases/latest with a redirect to the release's tag
    page, and a repository without a release with one to /releases.
    """
    target = _location(f"{GITHUB}/{repo}/releases/latest") or ""
    marker = "/releases/tag/"
    if marker in target:
        return target.split(marker, 1)[1].strip("/")
    if target.rstrip("/").endswith("/releases"):
        return None
    raise UpstreamError(f"{repo}: unexpected answer for the latest release: "
                        f"{target or 'no redirect'}")


def _release_asset(name: str, source: dict, cache: Path) -> dict:
    repo, asset = source["repo"], source["asset"]
    tag = latest_release(repo)
    if tag is None:
        if source.get("until_released"):
            return {"version": None, "files": [],
                    "note": f"{repo} has no release yet, skipped"}
        raise UpstreamError(f"{repo} has no release")
    url = f"{GITHUB}/{repo}/releases/download/{tag}/{asset}"
    try:
        record = _store(url, cache / name / tag / asset, reuse=True)
    except UpstreamError as exc:
        if exc.status != 404:
            raise
        raise UpstreamError(f"{repo} {tag} has no asset {asset!r} "
                            f"({exc})", 404) from exc
    return {"version": tag, "files": [record]}


def _repo_files(name: str, source: dict, cache: Path) -> dict:
    repo, ref = source["repo"], source["ref"]
    files, digest = [], hashlib.sha256()
    for path in source["files"]:
        target = cache / name / "head" / ref / path
        record = _store(f"{RAW}/{repo}/{ref}/{path}", target, reuse=False)
        files.append({"repo_path": path, **record})
        digest.update(f"{path}\0{record['sha256']}\n".encode())
    out = {"version": digest.hexdigest()[:12], "ref": ref, "files": files}
    reviewed = source.get("reviewed")
    if reviewed:
        changed = []
        for record in files:
            path = record["repo_path"]
            try:
                old = _store(f"{RAW}/{repo}/{reviewed}/{path}",
                             cache / name / reviewed / path, reuse=True)
            except UpstreamError as exc:
                if exc.status != 404:
                    raise
                changed.append(f"{path} (new since {reviewed[:7]})")
                continue
            if old["sha256"] != record["sha256"]:
                changed.append(path)
        out["reviewed"] = reviewed
        out["changed_since_reviewed"] = changed
        if changed:
            out["compare"] = f"{GITHUB}/{repo}/compare/{reviewed}...{ref}"
    return out


def sparql(endpoint: str, query: str, token: str) -> list:
    """[{variable: value}] from the OEKG endpoint.

    The endpoint answers with a JSON string that itself holds the JSON result,
    so the body is decoded twice.
    """
    body = _get(endpoint,
                data=json.dumps({"query": query, "format": "json"}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Token {token}"})
    result = json.loads(body)
    if isinstance(result, str):
        result = json.loads(result)
    return [{key: cell.get("value") for key, cell in binding.items()}
            for binding in result["results"]["bindings"]]


def _sparql(name: str, source: dict, cache: Path) -> dict:
    variable = source["token_env"]
    token = os.environ.get(variable, "").strip()
    if not token:
        raise UpstreamError(f"{name}: {variable} is not set; this source is "
                            f"read live from {source['endpoint']}")
    rows = sparql(source["endpoint"], source["query"], token)
    target = cache / name / "rows.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=1,
                                 sort_keys=True) + "\n", encoding="utf-8")
    return {"version": sha256(target)[:12], "rows": len(rows),
            "files": [{"path": str(target), "sha256": sha256(target),
                       "bytes": target.stat().st_size}]}


KINDS = {"release_asset": _release_asset, "repo_files": _repo_files,
         "sparql": _sparql}


def fetch(sources: dict, cache: Path = CACHE) -> dict:
    """{name: record} for every source, in the order the profile names them."""
    out = {}
    for name, source in sources.items():
        kind = KINDS.get(source.get("kind"))
        if kind is None:
            raise UpstreamError(f"{name}: unknown kind {source.get('kind')!r}")
        out[name] = {"kind": source["kind"], **kind(name, source, Path(cache))}
    return out


def lock_path(profile: str, cache: Path = CACHE) -> Path:
    return Path(cache) / f"{profile}.lock.json"


def write_lock(profile: str, records: dict, cache: Path = CACHE) -> Path:
    path = lock_path(profile, cache)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"fetched_at": datetime.datetime.now(datetime.timezone.utc)
               .isoformat(timespec="seconds"), "sources": records}
    path.write_text(json.dumps(stamped, ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_lock(profile: str, cache: Path = CACHE) -> Optional[dict]:
    path = lock_path(profile, cache)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def files(record: Optional[dict], suffix: str = "") -> list:
    """The local paths of a record's files, optionally by suffix."""
    return [Path(f["path"]) for f in (record or {}).get("files") or ()
            if f["path"].endswith(suffix)]


def summary(name: str, record: dict) -> str:
    """One English log line per source."""
    if record.get("note"):
        return f"{name}: {record['note']}"
    line = f"{name}: {record['kind']} {record['version']}"
    if "rows" in record:
        line += f", {record['rows']} row(s)"
    if record.get("reviewed"):
        changed = record.get("changed_since_reviewed") or []
        line += (f", {len(changed)} file(s) changed since reviewed "
                 f"{record['reviewed'][:7]}: {', '.join(changed)} "
                 f"({record.get('compare')})" if changed
                 else f", unchanged since reviewed {record['reviewed'][:7]}")
    return line
