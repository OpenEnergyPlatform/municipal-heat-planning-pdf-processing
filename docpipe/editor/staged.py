"""
staged.py: A recorded request of stage 4 or 5, put together again from the
prompt files and sent once more.

The refinement (stage 4) and the visuals (stage 5) write the request log the
harvest writes (owner request 2026-11-19, A3: "Dann gelten Vorschau,
Ausprobieren und die Messsätze auch für sie"). Each request in it names what
its messages are made of (`made`: the parts of `docpipe.prompts.composed`),
and the head of the log holds the text of every prompt as the run read it
(`trace.stage_head`). What filled the parts is read back from the recorded
messages with those texts (`prompts.values_in`), and the messages are made
again with the files on disk and with the texts being edited: the preview
(`preview`, in the form `editor.prompts.preview` gives) and the try (`once`).

A picture is recorded as the file it is cut from (`vision.logged`) and read
from the document's folder again, a strip cut from it the same way
(`strips.strip_of`). The reply is read as the stage reads it, by the first
required key of its reply form (`requests.reply_key`, `reading.read`).

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Callable, Optional

from .. import prompts as prompt_files
from . import prompts
from .requests import reply_key

# The messages a request is made of, by role: the first of each role.
ROLES = ("system", "user")
# The model a stage asks, by the stage its log names in its head.
ROLE_OF = {"visuals": "vlm", "refinement": "llm"}


def is_staged(request: dict) -> bool:
    """Whether *request* is one of a stage before the harvest: it names
    what its messages are made of."""
    return isinstance(request.get("made"), dict)


def _shows_picture(sent: dict) -> bool:
    return any(isinstance(part, dict) and part.get("type") == "image_url"
               for message in sent.get("messages") or ()
               if isinstance(message.get("content"), list)
               for part in message["content"])


def role_of(head: Optional[dict], sent: Optional[dict] = None) -> str:
    """Which model a request of a stage log asks: "vlm" for the visuals,
    "llm" for the refinement; where the head names no stage, "vlm" for a
    request that shows a picture."""
    stage = (head or {}).get("stage")
    if stage in ROLE_OF:
        return ROLE_OF[stage]
    return "vlm" if sent and _shows_picture(sent) else "llm"


def recorded(sent: dict) -> dict:
    """{role: the text of the first message of that role} of the request
    *sent*; a message made of parts gives its one text part. None for a
    role whose text cannot be read."""
    out: dict = {}
    for message in sent.get("messages") or ():
        role = message.get("role")
        if role not in ROLES or role in out:
            continue
        content = message.get("content")
        if isinstance(content, list):
            texts = [part.get("text") for part in content
                     if isinstance(part, dict) and part.get("type") == "text"]
            content = texts[0] if len(texts) == 1 else None
        out[role] = content if isinstance(content, str) else None
    return out


def preview(profile, request: dict, sent: dict, edits: dict, read: Callable,
            head: Optional[dict] = None) -> dict:
    """What a recorded request of a stage would be sent with, in the form of
    `editor.prompts.preview`: its instruction and its message as the files
    on disk make them (`file`) and as the texts in *edits* ({prompt id:
    text}) make them (`edit`). What filled them is read back from the
    record with the texts the run read (the `prompts` of its log's *head*,
    the files on disk for a prompt the head lacks). `lines` and `gone` mark
    the changed sentences of the instruction, `user_lines` and `user_gone`
    those of the message. Where the request cannot be put together again,
    `why` says so and the rest is None."""
    made = request.get("made") or {}
    ids = prompt_files.prompts_of(made)
    own = prompt_files.prompts_of({"system": made.get("system") or []})
    out = {"prompt": (own or ids or [None])[0], "prompts": ids, "why": None,
           "file": None, "edit": None, "changed": False, "lines": None,
           "gone": [], "user_lines": None, "user_gone": [], "example": None,
           "same_as_recorded": None, "meta": None, "made": True}
    if not ids:
        out["why"] = ("the record of this request names no prompt file its "
                      "messages were made of")
        return out
    texts = recorded(sent)
    then = (head or {}).get("prompts")
    then = then if isinstance(then, dict) else {}
    try:
        pairs = {one: prompts._prompt(profile, one, edits, read)
                 for one in ids}
    except (prompts.Refused, FileNotFoundError, LookupError, KeyError,
            ValueError) as exc:
        out["why"] = str(exc)
        return out

    def as_run(one: str) -> str:
        text = then.get(one)
        return text if isinstance(text, str) else pairs[one][0].text

    file, edit = {}, {}
    for role in ROLES:
        parts = made.get(role) or []
        message = texts.get(role)
        if message is None:
            out["why"] = (f"the record of this request holds no {role} "
                          f"text to read")
            return out
        values = prompt_files.values_in(parts, as_run, message)
        if values is None:
            out["why"] = (f"the {role} text of this request is not what its "
                          f"prompt files make, so what filled them cannot "
                          f"be read back from it")
            return out
        try:
            file[role] = prompt_files.composed(
                parts, lambda one: pairs[one][0].text, values)
            edit[role] = prompt_files.composed(
                parts, lambda one: pairs[one][1].text, values)
        except (KeyError, IndexError, ValueError) as exc:
            out["why"] = (f"the {role} text cannot be made with these prompt "
                          f"files: {exc}")
            return out
    system = prompts.marked(file["system"], edit["system"])
    user = prompts.marked(file["user"], edit["user"])
    main = pairs.get(out["prompt"])
    out.update({
        "file": file, "edit": edit, "changed": file != edit,
        "lines": system["lines"], "gone": system["gone"],
        "user_lines": user["lines"], "user_gone": user["gone"],
        "same_as_recorded": file == {role: texts[role] for role in ROLES},
        "meta": dict(main[1].meta) if main else None})
    return out


# -- sending ----------------------------------------------------------------------------

def picture(shown: dict, folder: Path, read_bytes: Callable) -> str:
    """The data URL of a picture as a stage log names it (`vision.logged`):
    the file *shown* names in the document's folder *folder*, read with
    *read_bytes*, the strip cut from it where it names one. LookupError
    where the strip cannot be cut again (the file changed since the run)."""
    from ..visuals import strips
    name = shown.get("file") if isinstance(shown, dict) else None
    if not isinstance(name, str) or not name:
        raise LookupError("the record names no file for its picture")
    png = read_bytes(folder / name)
    sha = shown.get("strip")
    if sha:
        png = strips.strip_of(png, sha)
        if png is None:
            raise LookupError(f"the strip of {name} that was sent cannot be "
                              f"cut from the file again: it changed since "
                              f"the run")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def messages_of(sent: dict, view: dict, folder: Path,
                read_bytes: Callable) -> list:
    """The messages of the recorded request *sent* with the instruction and
    the message of *view* (`preview`) in place of the first of each role,
    every picture read again (`picture`); the later messages of an attempt
    (a reply and what was said about it) as they were sent."""
    out = []
    first = set(ROLES)
    for message in sent.get("messages") or ():
        message = dict(message)
        role = message.get("role")
        content = message.get("content")
        mine = role in first
        first.discard(role)
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" \
                        and mine:
                    part = {**part, "text": view["edit"][role]}
                elif isinstance(part, dict) \
                        and part.get("type") == "image_url":
                    part = {"type": "image_url", "image_url": {
                        "url": picture(part.get("image_url") or {}, folder,
                                       read_bytes)}}
                parts.append(part)
            content = parts
        elif mine and isinstance(content, str):
            content = view["edit"][role]
        message["content"] = content
        out.append(message)
    return out


def once(client, model: str, sent: dict, view: dict, folder: Path,
         read_bytes: Callable, profile=None) -> dict:
    """One call: the recorded request *sent* with the instruction and the
    message of *view*, its reply form, room and settings as recorded, and
    what came back, read as the stage reads it."""
    from .. import reading
    out = {"answer": None, "answer_json": None, "finish": None,
           "error": None, "ms": None, "prompt_tokens": None,
           "completion_tokens": None, "max_tokens": sent.get("max_tokens"),
           "in_form": False, "fault": None}
    messages = messages_of(sent, view, folder, read_bytes)
    given = {key: sent[key] for key in ("temperature", "max_tokens",
                                        "response_format", "extra_body")
             if sent.get(key) is not None}
    started = time.time()
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, **given)
        choice = response.choices[0]
    except Exception as exc:        # whatever the server or the wire says
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["ms"] = int((time.time() - started) * 1000)
        return out
    out["ms"] = int((time.time() - started) * 1000)
    usage = getattr(response, "usage", None)
    out["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
    out["completion_tokens"] = getattr(usage, "completion_tokens", None)
    out["finish"] = getattr(choice, "finish_reason", None)
    out["answer"] = getattr(choice.message, "content", None)
    out["answer_json"] = reading.loads_object(out["answer"])
    from .requests import stage_check
    check = stage_check({"answer": out["answer"], "finish": out["finish"],
                         "_reply": reply_key(sent.get("response_format"))},
                        profile)
    out["in_form"] = check == "taken"
    out["fault"] = None if out["in_form"] else check.partition(": ")[2]
    return out


__all__ = ["ROLES", "ROLE_OF", "is_staged", "role_of", "recorded", "preview",
           "picture", "messages_of", "once"]
