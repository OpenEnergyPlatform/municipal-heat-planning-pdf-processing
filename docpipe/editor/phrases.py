"""
phrases.py: What the editor does with the sentences a stage says outside its
prompts (`docpipe/phrases.py`: `prompts/<module>/phrases.json`).

It shows, per module, every sentence the profile runs with: its own wording
or the one it takes from the profile it extends. The page edits the
profile's own table; a sentence it does not word itself is not in it. A
table is checked before it is written:

- a name no stage reads is refused, and a sentence a stage cannot run
  without may not go missing (`REQUIRED` of the stage);
- a sentence stays what it is, a text or a list of as many texts;
- a sentence is a template for `str.format`, and the code fills the names
  the wordings on disk use. So a changed sentence may use those names and no
  other, and where no wording of a sentence has a brace, a changed one has
  none either: whether such a sentence is run through `str.format` is not
  to be seen from here.

A sentence is seen in recorded requests where they show it: a follow-up
names why an answer did not hold in these sentences. `shown_in` finds them
and says each as the changed wording would.

Author: Felix Vossel
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import string
from pathlib import Path
from typing import Callable, Optional

from .. import phrases as phrase_files
from . import specs

NO_STALE = ("A changed sentence makes no harvest stale: a stamp rests on "
            "the questions of the spec alone.")
SHOWN_LIMIT = 20


def stage_of(module: str):
    """The module that reads the sentences of *module*: its `REQUIRED`
    names and its `NOTES`."""
    if module == "extraction":
        from ..extraction import wording
        return wording
    if module == "inference":
        from ..inference import wording
        return wording
    if module == "reading":
        from .. import reading
        return reading
    raise KeyError(f"no module {module!r} speaks outside its prompts; one "
                   f"of {phrase_files.MODULES}")


def layers(profile, module: str, read: Callable) -> list:
    """[(profile, its path, its table, its bytes)] along the line of
    profiles, nearest first, for those that have a file (*read(path)*)."""
    out = []
    for one in profile.lineage():
        path = phrase_files.path_of(one, module)
        if not path.is_file():
            continue
        data = read(path)
        out.append((one, path, phrase_files.parse(
            data.decode("utf-8"), path), data))
    return out


def _merged(found: list) -> dict:
    out: dict = {}
    for _, _, table, _ in reversed(found):
        out.update(table)
    return out


def _shown(value):
    return list(value) if isinstance(value, tuple) else value


def _texts(value) -> list:
    return list(value) if isinstance(value, (tuple, list)) else [value]


def _fields(text: str) -> Optional[set]:
    """The names `str.format` fills in *text*; None where it cannot read
    it or a field has no name."""
    names: set = set()
    try:
        for _, field, _, _ in string.Formatter().parse(text):
            if field is None:
                continue
            if not field or field.isdigit():
                return None
            names.add(field)
    except ValueError:
        return None
    return names


def _allowed(wordings: list) -> Optional[set]:
    """The names the wordings of one sentence use; None where none of them
    has a brace."""
    texts = [text for value in wordings for text in _texts(value)]
    if not any("{" in text or "}" in text for text in texts):
        return None
    names: set = set()
    for text in texts:
        names |= _fields(text) or set()
    return names


def detail(profile, module: str, read: Callable) -> dict:
    """What the page shows of the sentences of one module."""
    stage = stage_of(module)
    found = layers(profile, module, read)
    own = next((row for row in found if row[0].name == profile.name), None)
    rest = [row for row in found if row[0].name != profile.name]
    inherited = _merged(rest)
    table = _merged(found)
    sentences = []
    for key, value in table.items():
        source = next((one.name for one, _, got, _ in rest if key in got),
                      None)
        allowed = _allowed([got[key] for _, _, got, _ in found
                            if key in got])
        sentences.append({
            "key": key, "text": _shown(value),
            "own": own is not None and key in own[2],
            "inherited": _shown(inherited[key]) if key in inherited
            else None,
            "from": source,
            "names": sorted(allowed) if allowed is not None else None,
            "required": key in stage.REQUIRED,
            "note": stage.NOTES.get(key)})
    return {"module": module,
            "path": phrase_files.path_of(profile, module),
            "own_file": own is not None,
            # the profile's own table in the order of its file: what the
            # page edits and sends back, so a save moves no line
            "table": {key: _shown(value) for key, value in own[2].items()}
            if own else {},
            "sha256": hashlib.sha256(own[3]).hexdigest() if own else None,
            "sentences": sentences}


def _problem(key: str, value, known: list) -> Optional[str]:
    """Why the wording *value* of the sentence *key* cannot be written,
    given the wordings on disk *known*."""
    was = known[0]
    if isinstance(value, str) != isinstance(was, str):
        return (f"is a list of {len(was)} texts" if not isinstance(was, str)
                else "is one text, not a list")
    texts = _texts(value)
    if not all(isinstance(text, str) for text in texts):
        return "holds something that is no text"
    if len(texts) != len(_texts(was)):
        return f"is a list of {len(_texts(was))} texts"
    allowed = _allowed(known)
    for text in texts:
        if allowed is None:
            if "{" in text or "}" in text:
                return ("has a brace, and no wording of this sentence on "
                        "disk has one; whether the code fills a name there "
                        "is not known")
            continue
        fields = _fields(text)
        if fields is None:
            return ("is no template the code can fill: a brace that is "
                    "meant as a brace is doubled, and a name stands in "
                    "single braces")
        extra = sorted(fields - allowed)
        if extra:
            return (f"uses {{{'}, {'.join(extra)}}}, which the code does "
                    f"not fill; the names of this sentence are "
                    f"{sorted(allowed) or 'none'}")
    return None


def judge(profile, module: str, table, read: Callable) -> dict:
    """Everything the page shows after "Check" for *table*, the profile's
    own sentences of *module* as the page holds them (name -> text or list
    of texts); nothing is written."""
    stage = stage_of(module)
    found = layers(profile, module, read)
    own = next((row for row in found if row[0].name == profile.name), None)
    rest = [row for row in found if row[0].name != profile.name]
    inherited = _merged(rest)
    old = dict(own[2]) if own else {}
    error = where = None
    new: dict = {}
    if not isinstance(table, dict):
        error = "the sentences are one object, name -> words"
        table = {}
    for key, value in table.items():
        value = tuple(value) if isinstance(value, list) else value
        new[key] = value
        if error is not None or old.get(key) == value:
            continue
        known = [got[key] for _, _, got, _ in found if key in got]
        if not known:
            error, where = (f"{key}: no stage reads a sentence of this "
                            f"name"), key
            continue
        said = _problem(key, value, known)
        if said:
            error, where = f"{key}: {said}", key
    if error is None:
        missing = sorted(stage.REQUIRED - set(inherited) - set(new))
        if missing:
            error, where = (f"the stage cannot run without {missing}, and "
                            f"no profile this one extends words them"), \
                missing[0]
    changes = []
    for key in list(old) + [key for key in new if key not in old]:
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        changes.append({
            "key": key, "state": "added" if before is None
            else "removed" if after is None else "changed",
            "before": _shown(before if before is not None
                             else inherited.get(key)),
            "after": _shown(after if after is not None
                            else inherited.get(key))})
    newline = specs.newline_of(own[3]) if own else "\n"
    text = json.dumps({key: _shown(value) for key, value in new.items()},
                      indent=2, ensure_ascii=False) + "\n"
    before_text = own[3].decode("utf-8").replace("\r\n", "\n") if own else ""
    name = f"{module}/{phrase_files.FILE}"
    diff = list(difflib.unified_diff(
        before_text.splitlines(), text.splitlines(),
        f"a/{name}", f"b/{name}", lineterm="", n=2))
    body = [line for line in diff if not line.startswith(("+++", "---"))]
    return {"ok": error is None, "error": error, "where": where,
            "changed": bool(changes) or text != before_text,
            "changes": changes,
            "removed": [change for change in changes
                        if change["state"] == "removed"],
            "creates": None if own or not new
            else phrase_files.path_of(profile, module),
            "lines": {"added": sum(line.startswith("+") for line in body),
                      "removed": sum(line.startswith("-") for line in body)},
            "diff": "\n".join(diff), "note": NO_STALE,
            "text": text.replace("\n", newline)}


def save(profile, module: str, table, read: Callable,
         confirm: bool = False) -> tuple:
    """(the report of `judge`, the bytes to write or None, where). Nothing
    to write where the check fails (`reason: "check"`), nothing changed
    (`"same"`), or a sentence the profile worded itself is taken away and
    that is not confirmed (`"confirm"`)."""
    report = judge(profile, module, table, read)
    target = phrase_files.path_of(profile, module)

    def held(reason: str) -> tuple:
        return {**report, "saved": False, "reason": reason}, None, target
    if not report["ok"]:
        return held("check")
    if not report["changed"]:
        return held("same")
    if report["removed"] and not confirm:
        return held("confirm")
    return ({**report, "saved": True, "reason": None},
            report["text"].encode("utf-8"), target)


# -- a sentence in recorded requests ----------------------------------------------

def _pattern(template: str) -> Optional[tuple]:
    """(a pattern that finds *template* filled in, {group: (name,
    conversion)}); None for a template without words of its own or one
    `str.format` cannot read."""
    try:
        cut = list(string.Formatter().parse(template))
    except ValueError:
        return None
    if not any(literal.strip() for literal, _, _, _ in cut):
        return None
    groups: dict = {}
    seen: dict = {}
    parts = []
    for index, (literal, field, _, conversion) in enumerate(cut):
        parts.append(re.escape(literal))
        if field is None:
            continue
        if (field, conversion) in seen:
            parts.append(f"(?P={seen[(field, conversion)]})")
            continue
        group = f"g{len(groups)}"
        seen[(field, conversion)] = group
        groups[group] = (field, conversion)
        last = index == len(cut) - 1
        parts.append(f"(?P<{group}>.+)" if last else f"(?P<{group}>.+?)")
    return re.compile("".join(parts), re.S), groups


def _said(template: str, caught: dict) -> tuple:
    """(*template* filled with what a record showed, the names it could
    not fill). *caught* is {(name, conversion): the text shown}."""
    out, lacking = [], []
    for literal, field, _, conversion in string.Formatter().parse(template):
        out.append(literal)
        if field is None:
            continue
        if (field, conversion) in caught:
            out.append(caught[(field, conversion)])
        elif conversion is None and (field, "r") in caught:
            try:                        # shown as the model wrote it
                out.append(str(ast.literal_eval(caught[(field, "r")])))
            except (ValueError, SyntaxError):
                lacking.append(field)
        elif conversion == "r" and (field, None) in caught:
            out.append(repr(caught[(field, None)]))
        else:
            lacking.append(field)
    return "".join(out), lacking


def _strings(node) -> list:
    """Every text a message shows: its values where it is JSON, else
    itself."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return []


def _message_texts(content) -> list:
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", "")) for part in content
                            if isinstance(part, dict)
                            and part.get("type") == "text")
    if not isinstance(content, str):
        return []
    out = [content]
    try:
        payload, end = json.JSONDecoder().raw_decode(content)
    except ValueError:
        return out
    return _strings(payload) + [content[end:]]


def shown_in(requests: list, old: str, new: str,
             limit: int = SHOWN_LIMIT) -> dict:
    """Where the recorded *requests* (`requests.requests_of`) show the
    sentence worded *old*, each as it stood and as the wording *new* would
    say it: `searched`, `found` and the first *limit* of them (`shown`)."""
    out = {"searched": len(requests), "found": 0, "shown": [], "why": None}
    made = _pattern(old)
    if made is None:
        out["why"] = ("this sentence has no words of its own to find in a "
                      "record")
        return out
    pattern, groups = made
    for index, request in enumerate(requests):
        hits = []
        for role, content in request.get("messages") or ():
            if role != "user":
                continue
            for text in _message_texts(content):
                hits += list(pattern.finditer(text))
        if not hits:
            continue
        out["found"] += 1
        if len(out["shown"]) >= limit:
            continue
        hit = hits[0]
        caught = {groups[group]: value
                  for group, value in hit.groupdict().items()}
        after, lacking = _said(new, caught)
        out["shown"].append({
            "index": index, "kind": request.get("kind"),
            "asked": request.get("asked"),
            "parameter": request.get("parameter"),
            "before": hit.group(0),
            "after": None if lacking else after,
            "why": (f"the record does not show {sorted(set(lacking))}, "
                    f"which the new wording uses") if lacking else None})
    return out
