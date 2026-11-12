"""
mend.py: The two second ways of reading a reply that the owner decided
against on 2026-09-12 ("no JSON is repaired") and that a flow may choose
again: `repair_replies` (what is taken off or put right in a reply before it
is read) and `cut_off` (the complete entries of a list a reply was cut off
in). Both are off: a reply is read as it is, or asked again. Every reply
that went through either is noted in the request log by the caller, with
the rule's name.
"""
import json
import re
from typing import Optional

THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
FENCE_OPEN = re.compile(r"^```(?:json)?\s*")
FENCE_CLOSE = re.compile(r"\s*```$")
DECODER = json.JSONDecoder()


def close_brackets(text: str) -> str:
    """The closers a reply stopped short of, appended. Delimiters only: a
    bracket inside a string is text, a reply that stops inside a string is
    left as it is, and a closer that does not match what is open is
    somebody else's shape."""
    start = text.find("{")
    if start == -1:
        return text
    stack: list = []
    in_string = escaped = False
    for ch in text[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return text
            stack.pop()
    if in_string or not stack:
        return text
    return text + "".join(reversed(stack))


def repaired(text: str, kinds, closes: bool = True) -> tuple:
    """(the object, what was done) of a reply that is no JSON object as it
    stands, read after the repairs *kinds* name: `think` (a think block is
    taken off), `fences` (code fences are taken off), `cut_out` (the one
    object that starts at the first brace is read out of the text around
    it), `close` (the brackets a reply stopped short of are closed, where
    *closes*: a reply cut off at its ceiling is never closed). The object is
    None where no repair made one; the list is what was done to get it."""
    used: list = []
    text = (text or "").strip()
    if "think" in kinds:
        taken = THINK.sub("", text).strip()
        if taken != text:
            used.append("think")
            text = taken
    if "fences" in kinds:
        taken = FENCE_CLOSE.sub("", FENCE_OPEN.sub("", text)).strip()
        if taken != text:
            used.append("fences")
            text = taken
    data: object = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start != -1 and "cut_out" in kinds:
            try:
                data, _end = DECODER.raw_decode(text, start)
                used.append("cut_out")
            except json.JSONDecodeError:
                data = None
        if data is None and start != -1 and "close" in kinds and closes:
            closed = close_brackets(text)
            if closed != text:
                try:
                    data, _end = DECODER.raw_decode(closed, start)
                    used.append("close")
                except json.JSONDecodeError:
                    data = None
    if not isinstance(data, dict):
        return None, []
    return data, used


def rescued(text: str, key: str) -> Optional[dict]:
    """{key: the complete entries} of the list *key* of a reply that was cut
    off, or None where the reply has no such list or no entry of it is
    complete. An entry that was cut is not kept, nor anything after it."""
    found = re.search(r'"' + re.escape(key) + r'"\s*:\s*\[', text or "")
    if found is None:
        return None
    entries: list = []
    at = found.end()
    while True:
        while at < len(text) and text[at] in " \t\r\n,":
            at += 1
        if at >= len(text) or text[at] == "]":
            break
        try:
            entry, at = DECODER.raw_decode(text, at)
        except json.JSONDecodeError:
            break
        entries.append(entry)
    return {key: entries} if entries else None
