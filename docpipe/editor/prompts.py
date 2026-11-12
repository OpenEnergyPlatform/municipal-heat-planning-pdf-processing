"""
prompts.py: What the editor does with a profile's prompts.

It lists them with the profile each file belongs to, cuts a file into the
pieces a person edits (the settings on top, what every request is told, each
part only some requests are told), checks a text before it is written, and
makes the instruction of a recorded request from a text that is not written
yet, so that a changed sentence is seen in the requests that would carry it.

Nothing here knows how a prompt is read or put together: that is the
loader's (`docpipe.prompts.made`), the cut at the markers is the run's
(`extraction.thread.cut`), and the instruction of a request is made by the
two functions every request of the harvest passes (`runner.request_prompt`,
`runner.system_text`). The one thing a record does not carry is the example
reply the run wrote into the instruction; it is read back out of the
recorded instruction (`_places`).

A text is refused where a run would fail on it: a front matter the loader
cannot read, a parts file its template does not take, a part marked twice, a
follow-up part the file had and lost, and a `{{name}}` the file on disk does
not have or one it has that is gone, since the code fills exactly the names
that are there. And where a run would send what was not meant: a marker of a
part that the text adds and the run would take for text, because it does not
stand on a line of its own.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Optional

from .. import prompts as prompt_files
from . import sentences as by_sentence
from . import specs

# What a changed prompt costs a harvest (rule of 2026-09-10).
NO_STALE = ("A changed prompt leaves the harvests that are already written "
            "valid. Only a change of the questions in the Spec tab makes a "
            "document be read again.")
# The requests whose instruction is the part of the prompt their message
# carries (`runner.request_prompt`), and those sent the prompt whole.
CUT = ("find", "docfield", "coord", "list", "names", "search", "check",
       "work", "phrase")
WHOLE = ("transcribe",)
# The request asked again goes under the prompt of the one it follows;
# the words after its payload are those of this prompt.
FOLLOW = "follow"
# What is written as the marker of a part or of a way, wherever it stands.
# The run reads one only on a line of its own (`thread.MARK`, `thread.WAY`);
# any other is text, and what was meant as a part or a way goes to the
# model with the words before it.
_MARKER = re.compile(r"<!--[ \t]*(?:(?:with|follow-up|way)[ \t]*:[^\n]*?"
                     r"|/way[ \t]*)-->")


class Refused(ValueError):
    """Something the editor does not do, said in one sentence."""


# -- which prompts there are -----------------------------------------------------

def concerns(prompt_id: str, request: dict) -> bool:
    """Whether the prompt has a say in a recorded request: it makes its
    instruction, or it is the follow-up prompt and the request is one
    asked again."""
    from ..extraction import addressed
    if prompt_id == addressed.PROMPT_IDS[FOLLOW]:
        return request.get("kind") == FOLLOW
    return prompt_of(request) == prompt_id


def kinds_of(prompt_id: str) -> list:
    """The kinds of recorded requests a prompt has a say in: the requests
    of its own kind, and for the follow-up prompt those asked again."""
    from ..extraction import addressed
    stage, _, name = prompt_id.partition("/")
    if stage != "extraction" or name not in addressed.KINDS:
        return []
    if name == FOLLOW or name in CUT or name in WHOLE:
        return [name]
    return []


def listing(profile) -> list:
    """Every prompt the profile runs with, its own and those of the
    profiles it extends, by stage and name."""
    found: dict = {}
    for owner in reversed(profile.lineage()):
        folder = owner.prompts_dir
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*/*.md")):
            found[f"{path.parent.name}/{path.stem}"] = owner
    out = []
    for prompt_id in sorted(found):
        owner = found[prompt_id]
        stage, _, name = prompt_id.partition("/")
        out.append({"id": prompt_id, "stage": stage, "name": name,
                    "owner": owner.name, "own": owner.name == profile.name,
                    "kinds": kinds_of(prompt_id)})
    return out


# -- one file, cut for editing ----------------------------------------------------

def segments(raw: str) -> dict:
    """*raw* cut without loss: `front` (the settings between the two rules,
    "" where the file has none), `common` (what every request is told) and
    `parts`, each with the line that marks it (`mark`), its kind, the
    fields it is about and its text. `joined` puts them back character for
    character."""
    from ..extraction import thread
    match = prompt_files._FRONT_MATTER.match(raw)
    front = raw[:match.end()] if match else ""
    body = raw[len(front):]
    marks = list(thread.MARK.finditer(body))
    parts = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) \
            else len(body)
        after = mark.end() + (body[mark.end():mark.end() + 1] == "\n")
        parts.append({"mark": body[mark.start():after],
                      "kind": mark.group(1), "keys": mark.group(2).split(),
                      "text": body[after:end]})
    return {"front": front,
            "common": body[:marks[0].start()] if marks else body,
            "parts": parts}


def joined(cut: dict) -> str:
    return cut["front"] + cut["common"] + "".join(
        part["mark"] + part["text"] for part in cut["parts"])


def on_disk(profile, prompt_id: str, read: Callable) -> dict:
    """The file a run loads for *prompt_id*: the profile that owns it, its
    path, its bytes (*read(path)*), its text with "\\n" line ends and the
    line ends it has. FileNotFoundError where no profile of the line has
    it."""
    owner, path = prompt_files._find(prompt_id, profile)
    if not path.is_file():
        raise FileNotFoundError(f"profile {profile.name!r} has no prompt "
                                f"{prompt_id!r} ({path})")
    data = read(path)
    return {"owner": owner, "path": path, "bytes": data,
            "newline": specs.newline_of(data),
            "raw": data.decode("utf-8").replace("\r\n", "\n")}


def target_of(profile, prompt_id: str) -> Path:
    """Where the profile's own file of *prompt_id* is, or would be."""
    stage, _, name = prompt_id.partition("/")
    return profile.prompts_dir / stage / f"{name}.md"


def detail(profile, prompt_id: str, read: Callable) -> dict:
    """What the page shows of one prompt."""
    disk = on_disk(profile, prompt_id, read)
    prompt = prompt_files.made(prompt_id, profile, disk["owner"],
                               disk["path"], disk["raw"])
    stage, _, name = prompt_id.partition("/")
    composed = prompt.composition is not None
    return {"id": prompt_id, "stage": stage, "name": name,
            "owner": disk["owner"].name,
            "own": disk["owner"].name == profile.name,
            "path": disk["path"], "target": target_of(profile, prompt_id),
            "sha256": hashlib.sha256(disk["bytes"]).hexdigest(),
            "raw": disk["raw"], "cut": segments(disk["raw"]),
            "meta": dict(prompt.meta),
            "placeholders": sorted(prompt.placeholders),
            "composed": composed, "sent": prompt.text if composed else None,
            "kinds": kinds_of(prompt_id)}


# -- the check before a save -------------------------------------------------------

def _numbers(prompt) -> None:
    """The two settings a request reads as numbers are numbers."""
    for key, kind in (("temperature", float), ("max_tokens", int)):
        if key not in prompt.meta:
            continue
        value = prompt.meta[key]
        try:
            if isinstance(value, bool):
                raise ValueError
            kind(value)
        except (TypeError, ValueError):
            raise Refused(f"{key}: {value!r} is not a number") from None
    if "max_tokens" in prompt.meta and int(prompt.meta["max_tokens"]) < 1:
        raise Refused("max_tokens: a reply needs at least one token")


def _loose(text: str) -> list:
    """What *text* writes as a marker and the run would not read as one."""
    from ..extraction import thread
    read = {mark.start() for marks in (thread.MARK, thread.WAY)
            for mark in marks.finditer(text)}
    return [hit.group(0) for hit in _MARKER.finditer(text)
            if hit.start() not in read]


def _made(profile, prompt_id: str, owner, path: Path, raw: str):
    """The prompt *raw* would be, with what the loader says where it
    refuses it."""
    import yaml
    try:
        return prompt_files.made(prompt_id, profile, owner, path, raw)
    except yaml.YAMLError as exc:
        raise Refused(f"the settings on top are not readable: {exc}") \
            from exc
    except (ValueError, LookupError, OSError) as exc:
        raise Refused(str(exc)) from exc


def problem(profile, prompt_id: str, raw: str, disk: dict) -> Optional[str]:
    """Why the text *raw* is not written as the profile's file of
    *prompt_id*: a run would fail on it, or send what was not meant. None
    where neither holds. *disk* is the file a run loads today
    (`on_disk`)."""
    from ..extraction import thread
    try:
        old = _made(profile, prompt_id, disk["owner"], disk["path"],
                    disk["raw"])
        new = _made(profile, prompt_id, profile,
                    target_of(profile, prompt_id), raw)
        _numbers(new)
        was = _loose(disk["raw"])
        loose = [mark for mark in _loose(raw) if mark not in was]
        if loose:
            raise Refused(
                f"{' '.join(loose[0].split())} opens no part: the run reads "
                f"a marker only on a line of its own, written as "
                f"<!-- with: name -->, <!-- follow-up: name -->, "
                f"<!-- way: rule=choice --> or <!-- /way -->; here its "
                f"text would go to the model with the words before it")
        try:
            cut = thread.cut(new)
        except LookupError as exc:
            raise Refused(str(exc)) from exc
        had = {key for part in thread.cut(old).of(thread.FOLLOW_UP)
               for key in part.keys}
        has = {key for part in cut.of(thread.FOLLOW_UP) for key in part.keys}
        if had - has:
            raise Refused(
                f"the follow-up part for {sorted(had - has)} is gone; the "
                f"code sends a follow-up with it and would have no words "
                f"for it")
        added = sorted(new.placeholders - old.placeholders)
        missing = sorted(old.placeholders - new.placeholders)
        if added or missing:
            said = []
            if added:
                said.append("{{" + "}}, {{".join(added) + "}} is not in "
                            "the file on disk, so no code fills it")
            if missing:
                said.append("{{" + "}}, {{".join(missing) + "}} is gone, "
                            "and the code that fills it would have no "
                            "place for it")
            raise Refused("; ".join(said))
    except Refused as exc:
        return str(exc)
    return None


def judge(profile, prompt_id: str, raw: str, disk: dict) -> dict:
    """Everything the page shows after "Check" for the text *raw*; nothing
    is written."""
    raw = raw.replace("\r\n", "\n")
    error = problem(profile, prompt_id, raw, disk)
    own = disk["owner"].name == profile.name
    changed = raw != disk["raw"]
    name = f"{prompt_id}.md"
    diff = list(difflib.unified_diff(
        disk["raw"].splitlines(), raw.splitlines(),
        f"a/{name}", f"b/{name}", lineterm="", n=2))
    body = [line for line in diff if not line.startswith(("+++", "---"))]
    report = {
        "ok": error is None, "error": error, "changed": changed,
        "creates": None if own or not changed
        else target_of(profile, prompt_id),
        "lines": {"added": sum(line.startswith("+") for line in body),
                  "removed": sum(line.startswith("-") for line in body)},
        "diff": "\n".join(diff), "sentences": "", "size": None,
        "meta": None, "note": NO_STALE,
        "text": raw.replace("\n", disk["newline"])}
    if error is None:
        old = prompt_files.made(prompt_id, profile, disk["owner"],
                                disk["path"], disk["raw"])
        new = prompt_files.made(prompt_id, profile, profile,
                                target_of(profile, prompt_id), raw)
        report["sentences"] = "\n".join(by_sentence.unified(
            by_sentence.units(old.text), by_sentence.units(new.text)))
        report["size"] = {"before": len(old.text), "after": len(new.text)}
        report["meta"] = {"before": dict(old.meta), "after": dict(new.meta)}
    return report


def save(profile, prompt_id: str, raw: str, disk: dict) -> tuple:
    """(the report of `judge`, the bytes to write or None, where to write
    them). Nothing to write where the check fails (`reason: "check"`) or
    the text is the file's (`reason: "same"`)."""
    report = judge(profile, prompt_id, raw, disk)
    target = target_of(profile, prompt_id)
    if not report["ok"]:
        return {**report, "saved": False, "reason": "check"}, None, target
    if not report["changed"]:
        return {**report, "saved": False, "reason": "same"}, None, target
    return ({**report, "saved": True, "reason": None},
            report["text"].encode("utf-8"), target)


# -- the instruction of a recorded request ------------------------------------------

def prompt_of(request: dict) -> Optional[str]:
    """The prompt that makes the instruction of a recorded request (one of
    `requests.requests_of`): that of its kind, for a request asked once
    more that of the request it follows; None for a kind the editor cannot
    put together again."""
    from ..extraction import addressed
    kind = request.get("asked") if request.get("kind") == FOLLOW \
        else request.get("kind")
    if kind in CUT or kind in WHOLE:
        return addressed.PROMPT_IDS[kind]
    return None


def payload_of(sent: dict) -> tuple:
    """(the payload the first user message of *sent* shows, where it ends
    in that message's text, that text); (None, 0, "") where it shows
    none."""
    for message in sent.get("messages") or ():
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = next((part.get("text") for part in content
                            if isinstance(part, dict)
                            and part.get("type") == "text"), None)
        if not isinstance(content, str):
            break
        try:
            payload, end = json.JSONDecoder().raw_decode(content)
        except ValueError:
            break
        if isinstance(payload, dict):
            return payload, end, content
        break
    return None, 0, ""


def _compact(line: str) -> bool:
    """Whether *line* is one JSON object as the run writes an example."""
    if not (line.startswith("{") and line.endswith("}")):
        return False
    try:
        value = json.loads(line)
    except ValueError:
        return False
    return isinstance(value, dict) and json.dumps(
        value, ensure_ascii=False, separators=(",", ":")) == line


def _places(text: str, recorded: str) -> tuple:
    """(how, {place: its text in *recorded*}) for the `{{places}}` of the
    prompt text *text*.

    "record": *recorded* is *text* with its places filled in, each with one
    line, so what fills them is known exactly. "lines": it is not (the
    prompt was worded differently when the request was sent), and the
    record has as many lines that are one JSON object as *text* has places,
    which are taken in order. (None, {}) where neither holds."""
    names: list = []
    pattern: list = []
    at = 0
    for hit in prompt_files._PLACEHOLDER.finditer(text):
        pattern.append(re.escape(text[at:hit.start()]))
        name = hit.group(1)
        if name in names:
            pattern.append(f"(?P={name})")
        else:
            names.append(name)
            pattern.append(f"(?P<{name}>[^\\n]*?)")
        at = hit.end()
    pattern.append(re.escape(text[at:]))
    match = re.fullmatch("".join(pattern), recorded)
    if match:
        return "record", match.groupdict()
    lines = [line for line in recorded.split("\n") if _compact(line)]
    if names and len(lines) == len(names):
        return "lines", dict(zip(names, lines))
    return None, {}


def _template(prompt, kind: str, payload: dict):
    """The prompt of one request as the run makes it, before its example
    is written in."""
    from ..extraction import runner, thread
    if kind in WHOLE:
        return prompt
    return runner.request_prompt(thread.cut(prompt), payload)


def _system(template, kind: str, filled: dict) -> str:
    """The instruction a request sends: *template* with the example
    replies *filled* written in by the run's own function."""
    from ..extraction import runner
    if kind == "phrase":
        return template.text            # the run sends it as it is cut
    examples = tuple(json.loads(filled[name])
                     for name in (runner.EXAMPLE_PLACE, runner.NOTHING_PLACE)
                     if name in filled)
    return runner.system_text(template, examples or None)


def _follow_words(prompt) -> str:
    from ..extraction import thread
    return thread.chosen(thread.cut(prompt).common, prompt.id).strip()


def marked(before: str, after: str) -> dict:
    """*after* by line and sentence, each sentence with whether *before*
    does not have it there (`lines`), and the sentences of *before* that
    *after* lost (`gone`). A sentence stands in `lines` with the blanks
    that follow it, so the pieces of a line are the line character for
    character."""
    def rows_of(text: str) -> list:
        return [by_sentence.sentences(line) if line.strip() else [line]
                for line in text.split("\n")]

    def pieces(line: str, row: list) -> list:
        out, at = [], 0
        for index, unit in enumerate(row):
            end = at + len(unit)
            if index + 1 == len(row):
                end = len(line)
            else:
                while end < len(line) and line[end].isspace():
                    end += 1            # the blanks the cut left out
            out.append(line[at:end])
            at = end
        return out
    old = [unit for row in rows_of(before) for unit in row]
    rows = rows_of(after)
    new = [unit for row in rows for unit in row]
    changed: set = set()
    gone: list = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            changed.update(range(j1, j2))
        if tag in ("replace", "delete"):
            gone += [unit for unit in old[i1:i2] if unit.strip()]
    lines, at = [], 0
    for line, row in zip(after.split("\n"), rows):
        lines.append([[piece, at + index in changed]
                      for index, piece in enumerate(pieces(line, row))])
        at += len(row)
    return {"lines": lines, "gone": gone}


def _prompt(profile, prompt_id: str, edits: dict, read: Callable) -> tuple:
    """(the prompt as the file on disk makes it, as the edit makes it):
    the same where *edits* holds no text for it."""
    disk = on_disk(profile, prompt_id, read)
    old = prompt_files.made(prompt_id, profile, disk["owner"], disk["path"],
                            disk["raw"])
    if prompt_id not in edits:
        return old, old
    raw = edits[prompt_id].replace("\r\n", "\n")
    return old, _made(profile, prompt_id, profile,
                      target_of(profile, prompt_id), raw)


def preview(profile, request: dict, sent: dict, edits: dict,
            read: Callable) -> dict:
    """What a recorded request would be sent with: the instruction, and for
    a request asked again its message, as the files on disk make them
    (`file`) and as the texts in *edits* ({prompt id: text}) make them
    (`edit`).

    `same_as_recorded` says whether the files on disk give the record
    character for character, `changed` whether the edit changes this
    request at all, `lines` the edit's instruction by line and sentence
    with the changed ones marked. Where the request cannot be put together
    again, `why` says so and the rest is None."""
    from ..extraction import addressed
    out = {"prompt": prompt_of(request), "why": None, "file": None,
           "edit": None, "changed": False, "lines": None, "gone": [],
           "example": None, "same_as_recorded": None, "meta": None}
    if out["prompt"] is None:
        out["why"] = (f"the instruction of a {request.get('kind')!r} "
                      f"request is not put together from one prompt file, "
                      f"so it is shown as it was sent")
        return out
    kind = request.get("asked") if request["kind"] == FOLLOW \
        else request["kind"]
    payload, end, content = payload_of(sent)
    recorded = next((message.get("content") for message
                     in sent.get("messages") or ()
                     if message.get("role") == "system"), None)
    if payload is None or not isinstance(recorded, str):
        out["why"] = "the record of this request holds no payload to read"
        return out
    try:
        old, new = _prompt(profile, out["prompt"], edits, read)
        how, filled = _places(_template(old, kind, payload).text, recorded)
        if how is None and _template(old, kind, payload).placeholders:
            out["why"] = (
                "the example reply of this request cannot be read from its "
                "record: the prompt was worded differently when it was "
                "sent, and the record does not show as many example "
                "replies as the prompt has places for")
            return out
        file_system = _system(_template(old, kind, payload), kind, filled)
        edit_system = _system(_template(new, kind, payload), kind, filled)
        file_user = edit_user = content
        if request["kind"] == FOLLOW:
            follow = addressed.PROMPT_IDS[FOLLOW]
            was, now = _prompt(profile, follow, edits, read)
            file_user = f"{content[:end]}\n\n{_follow_words(was)}"
            edit_user = f"{content[:end]}\n\n{_follow_words(now)}"
    except (Refused, FileNotFoundError, LookupError, KeyError,
            ValueError) as exc:
        out["why"] = str(exc)
        return out
    cut = marked(file_system, edit_system)
    out.update({
        "file": {"system": file_system, "user": file_user},
        "edit": {"system": edit_system, "user": edit_user},
        "changed": (file_system, file_user) != (edit_system, edit_user),
        "lines": cut["lines"], "gone": cut["gone"], "example": how,
        "same_as_recorded": (file_system, file_user) == (recorded, content),
        "meta": dict(new.meta)})
    return out
