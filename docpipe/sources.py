"""
sources.py: Where a profile's ontology, shapes and graph come from, read
from a file of the profile.

A profile's lists are drawn from an ontology, its graph is written to the
shapes of a knowledge graph, and some of its lists are what that graph
already holds. Until 2026-11-10 the addresses stood in the profile's Python
(`vocabulary.py: SOURCES`, the roots of its lists in `SETS`); since then they
stand beside its spec, so that `docpipe edit` shows them and can fetch them
(owner, 2026-11-10: "einfach die URLs angeben für Ontologie und KG"):

    <profile folder>/sources.json

    {"sources": {name: {"kind": ..., ...}},     what `upstream.fetch` pulls
     "lists": {name: {"kind": "class" | "individual", "root": IRI}},
     "axis_lists": {coordinate: list name}}     which list a coordinate
                                                answers from

A source is one of the kinds `upstream` fetches, with the keys that kind
reads (`KEYS`); a token is never in the file, only the name of the setting
that holds it (`token_env`). The file is read strictly: an unknown kind, a
missing key, a key no kind reads, a list without its root is refused with
the file and the source named. Nothing here fetches anything.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FILE = "sources.json"

# The keys each kind of source reads (`upstream`), those it needs first.
KEYS = {
    "release_asset": (("repo", "asset"), ("until_released",)),
    "release_file": (("repo", "file"), ("until_released",)),
    "repo_files": (("repo", "ref", "files"), ("reviewed",)),
    "repo_tree": (("repo", "ref", "paths"), ("suffix",)),
    "sparql": (("endpoint", "query", "token_env"), ()),
    "url": (("url", "file"), ()),
}
# What a list draws: the subclasses of a class, or the individuals of one.
LIST_KINDS = ("class", "individual")
# Where a source's version comes from, as a page shows it.
STANDS = {"release_asset": "latest release", "release_file":
          "latest release", "repo_files": "head of a branch",
          "repo_tree": "head of a branch", "sparql": "live query",
          "url": "the file at the address"}


class SourcesError(ValueError):
    """A sources file a run cannot read. It names the file and the
    source."""


@dataclass(frozen=True)
class Sources:
    sources: dict = field(default_factory=dict)
    lists: dict = field(default_factory=dict)
    axis_lists: dict = field(default_factory=dict)
    path: Optional[Path] = None
    sha256: str = ""

    def sets(self) -> dict:
        """{list name: (kind, root)}, as the vocabulary builders take it."""
        return {name: (one["kind"], one["root"])
                for name, one in self.lists.items()}


def _nearest(name, known) -> str:
    close = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def source_problem(name: str, source) -> Optional[str]:
    """Why *source* is no source a run can fetch, None where it is."""
    if not isinstance(source, dict):
        return f"source {name} must be an object"
    kind = source.get("kind")
    if kind not in KEYS:
        return (f"source {name}: kind {kind!r} is none of "
                f"{', '.join(KEYS)}{_nearest(kind, KEYS)}")
    needed, optional = KEYS[kind]
    for key in needed:
        value = source.get(key)
        if value is None or value == "" or value == []:
            return f"source {name} ({kind}) needs {key}"
    for key in source:
        if key != "kind" and key not in needed and key not in optional:
            return (f"source {name} ({kind}) has no key {key!r}"
                    f"{_nearest(key, needed + optional)}")
    for key in ("files", "paths"):
        if key in source and not (isinstance(source[key], list) and all(
                isinstance(one, str) and one for one in source[key])):
            return f"source {name}: {key} must be a list of paths"
    for key in ("repo", "asset", "file", "ref", "endpoint", "query",
                "token_env", "url", "reviewed", "suffix"):
        if key in source and not isinstance(source[key], str):
            return f"source {name}: {key} must be a text"
    if "until_released" in source \
            and not isinstance(source["until_released"], bool):
        return f"source {name}: until_released must be true or false"
    return None


def parse(raw: str, where) -> Sources:
    """The sources of the text *raw*, read strictly."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SourcesError(f"{where}: {exc}") from exc
    if not isinstance(data, dict) \
            or set(data) - {"sources", "lists", "axis_lists"}:
        raise SourcesError(f"{where}: a sources file is one JSON object with "
                           f"\"sources\", \"lists\" and \"axis_lists\"")
    sources = data.get("sources") or {}
    lists = data.get("lists") or {}
    axis_lists = data.get("axis_lists") or {}
    if not all(isinstance(one, dict) for one in (sources, lists, axis_lists)):
        raise SourcesError(f"{where}: sources, lists and axis_lists are "
                           f"objects")
    for name, source in sources.items():
        said = source_problem(name, source)
        if said:
            raise SourcesError(f"{where}: {said}")
    for name, one in lists.items():
        if not isinstance(one, dict) or one.get("kind") not in LIST_KINDS \
                or not isinstance(one.get("root"), str) or not one["root"] \
                or set(one) - {"kind", "root"}:
            raise SourcesError(f"{where}: list {name} is {{\"kind\": "
                               f"class or individual, \"root\": an IRI}}")
    for axis, name in axis_lists.items():
        if name not in lists:
            raise SourcesError(f"{where}: {axis} answers from {name!r}, "
                               f"which is no list of the file"
                               f"{_nearest(name, lists)}")
    return Sources(dict(sources), dict(lists), dict(axis_lists), None,
                   hashlib.sha256(raw.encode("utf-8")).hexdigest())


def dump(sources: Sources, newline: str = "\n") -> str:
    text = json.dumps({"sources": sources.sources, "lists": sources.lists,
                       "axis_lists": sources.axis_lists},
                      ensure_ascii=False, indent=2) + "\n"
    return text if newline == "\n" else text.replace("\n", newline)


def path_of(profile) -> Path:
    return Path(profile.package_dir) / FILE


def load(profile) -> Sources:
    """The sources of *profile*: its own file, else that of the nearest
    profile it extends; empty where none writes one."""
    for one in (profile.lineage() if profile is not None else []):
        path = path_of(one)
        if path.is_file():
            made = parse(path.read_text(encoding="utf-8"), path)
            return Sources(made.sources, made.lists, made.axis_lists, path,
                           made.sha256)
    return Sources()


def of(name: str) -> Sources:
    """The sources of the profile called *name*."""
    from .profile import load_profile
    return load(load_profile(name))
