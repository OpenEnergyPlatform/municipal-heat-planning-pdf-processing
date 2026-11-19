"""
datafiles.py: The data files of a profile that no other tab edits.

Owner request 2026-11-19, point A2 of the review of that day ("Daten eines
Profils ohne Platz in der Seite"): the regions of the scenario profile and
their spellings, the exceptions of the KWP register. A profile names them in
its `profile.py` (`DATA_FILES`): the file in its folder, what it holds
(`about`), and whether a person keeps it (`kept`) or a fetch writes it. A
kept one also says what a key has to be (`key`, a pattern) and what an entry
has to be (`value`, a JSON schema).

Each file is one JSON object, a key -> its entry. The Sources tab lists them
and shows the entries of one; a kept one is checked and written here. A
file that changed on disk since the page read it is not overwritten, and a
written file keeps its form: the indent, the order of its keys (sorted where
the file on disk has them sorted, else as the page holds them) and its line
ends. A file a fetch writes is shown and not written: a change of it would
be gone at the next fetch.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Optional

from . import specs


class Refused(ValueError):
    """A data file the editor does not write, said in one sentence."""


def declared(profile) -> list:
    """The data files *profile* names itself, each {name, path, about,
    kept, key, value}."""
    folder = Path(profile.package_dir)
    out = []
    for entry in profile.own("profile", "DATA_FILES") or ():
        out.append({"name": entry["file"], "path": folder / entry["file"],
                    "about": entry.get("about", ""),
                    "kept": bool(entry.get("kept")),
                    "key": entry.get("key"), "value": entry.get("value")})
    return out


def find(profile, name: str) -> dict:
    """The declared data file *name*; KeyError for one the profile does not
    name."""
    for one in declared(profile):
        if one["name"] == name:
            return one
    raise KeyError(name)


def _form(raw: str) -> tuple:
    """(indent, keys sorted) of the JSON object *raw* as it is written."""
    indent = 1
    for line in raw.split("\n")[1:]:
        if line.strip():
            indent = len(line) - len(line.lstrip(" ")) or 1
            break
    keys = list(json.loads(raw)) if raw.strip() else []
    return indent, keys == sorted(keys) and len(keys) > 1


def _read(one: dict, read: Callable) -> tuple:
    """(bytes, text with "\\n" line ends, entries) of a data file on disk;
    (b"", "", {}) for one not written yet."""
    if not one["path"].is_file():
        return b"", "", {}
    data = read(one["path"])
    raw = data.decode("utf-8").replace("\r\n", "\n")
    return data, raw, json.loads(raw)


def listing(profile, read: Callable) -> list:
    """What the page lists of each data file: its name, what it holds,
    whether a person keeps it, whether it is there, and how many entries
    it has."""
    out = []
    for one in declared(profile):
        data, _raw, entries = _read(one, read)
        out.append({"name": one["name"], "about": one["about"],
                    "kept": one["kept"], "exists": bool(data),
                    "entries": len(entries), "bytes": len(data)})
    return out


def detail(profile, name: str, read: Callable) -> dict:
    """One data file with its entries in the order of the file, and the
    sha256 of its bytes that a save names as its base."""
    one = find(profile, name)
    data, _raw, entries = _read(one, read)
    return {"name": one["name"], "path": one["path"], "about": one["about"],
            "kept": one["kept"], "key": one["key"], "value": one["value"],
            "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "entries": entries}


def problems(one: dict, entries) -> list:
    """Why *entries* cannot be written as the data file *one*: each key that
    does not match its pattern, each entry its schema does not take; [] for
    entries it takes."""
    import jsonschema
    if not isinstance(entries, dict):
        return ["the entries are one object, a key -> its entry"]
    out = []
    pattern = re.compile(one["key"]) if one.get("key") else None
    checker = (jsonschema.Draft202012Validator(one["value"])
               if one.get("value") else None)
    for key, value in entries.items():
        if not key:
            out.append("an entry has no key")
            continue
        if pattern is not None and not pattern.search(key):
            out.append(f"{key}: the key does not match {one['key']}")
        if checker is not None:
            for error in sorted(checker.iter_errors(value),
                                key=lambda error: list(error.path)):
                where = "/".join(str(part) for part in error.path)
                out.append(f"{key}{'/' + where if where else ''}: "
                           f"{error.message}")
    return out


def kept(profile, name: str) -> dict:
    """The data file *name* where a person keeps it; `Refused` for one a
    fetch writes."""
    one = find(profile, name)
    if not one["kept"]:
        raise Refused(f"{name} is written by a fetch; a change of it would "
                      f"be gone at the next fetch")
    return one


def judge(profile, name: str, entries, read: Callable) -> dict:
    """Everything the page shows after "Check" for *entries*, the data file
    *name* as the page holds it; nothing is written."""
    one = kept(profile, name)
    data, raw, old = _read(one, read)
    said = problems(one, entries)
    out = {"ok": not said, "problems": said, "text": None,
           "changed": False, "added": [], "removed": [], "edited": []}
    if said:
        return out
    indent, ordered = _form(raw) if raw else (1, False)
    text = json.dumps(entries, indent=indent, ensure_ascii=False,
                      sort_keys=ordered) + "\n"
    newline = specs.newline_of(data) if data else "\n"
    out.update({
        "text": text.replace("\n", newline),
        "changed": text != raw,
        "added": [key for key in entries if key not in old],
        "removed": [key for key in old if key not in entries],
        "edited": [key for key in entries
                   if key in old and old[key] != entries[key]]})
    return out


def current(profile, name: str, read: Callable) -> Optional[str]:
    """The sha256 of the data file *name* on disk, None where it is not
    written yet: what a save is held against (the page's `base`)."""
    data, _raw, _entries = _read(find(profile, name), read)
    return hashlib.sha256(data).hexdigest() if data else None


def save(profile, name: str, entries, read: Callable) -> tuple:
    """(report, bytes to write, path) of a save of *entries* as the data
    file *name*; `Refused` where they are not taken. The caller holds the
    file against what the page read first (`current`)."""
    report = judge(profile, name, entries, read)
    if not report["ok"]:
        raise Refused("; ".join(report["problems"][:5]))
    text = report.pop("text").encode("utf-8")
    report["sha256"] = hashlib.sha256(text).hexdigest()
    return report, text, find(profile, name)["path"]
