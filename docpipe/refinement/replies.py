"""
replies.py: The reply each refinement request asks for, as a JSON schema.

For an API that generates inside a schema (see `docpipe.providers`). The
prompts state the same shapes in words; nothing here is a check.

The corrections reply is small and fixed. The full reply hands every section
back, with the keys the request carried, so its schema is built from the
window that is sent: what a section or one of its tables carried under a key
decides what may come back under it.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

TEXT = {"type": "string"}

SPLIT = {
    "type": "object",
    "properties": {
        "first_title": {"type": ["string", "null"]},
        "cuts": {"type": "array",
                 "items": {"type": "object",
                           "properties": {"at": {"type": "integer"},
                                          "title": TEXT},
                           "required": ["at", "title"],
                           "additionalProperties": False}}},
    "required": ["cuts"], "additionalProperties": False}

CORRECTIONS = {
    "type": "object",
    "properties": {"sections": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "title": TEXT,
            # caption per table or figure id of that section
            "captions": {"type": "object",
                         "additionalProperties": {"type": ["string", "null"]}},
            "corrections": {"type": "array", "items": {
                "type": "object",
                "properties": {"find": TEXT, "replace": TEXT},
                "required": ["find", "replace"],
                "additionalProperties": False}},
            "content": {"type": "array", "items": TEXT},
            "_action": TEXT},
        "required": ["index"], "additionalProperties": False}}},
    "required": ["sections"], "additionalProperties": False}

_SCALARS = ((bool, "boolean"), (int, "integer"), (float, "number"),
            (str, "string"))


def _scalar(value) -> Optional[str]:
    for kind, name in _SCALARS:
        if isinstance(value, kind):
            return name
    return None


def _carried(values) -> Optional[dict]:
    """The schema of what was sent under one key, or None when it cannot be
    handed back inside a schema (an object of its own, a list of lists)."""
    kinds, items, listed = set(), set(), False
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            listed = True
            for item in value:
                kind = _scalar(item)
                if kind is None:
                    return None
                items.add(kind)
            continue
        kind = _scalar(value)
        if kind is None:
            return None
        kinds.add(kind)
    options = [{"type": kind} for kind in sorted(kinds)]
    if listed:
        options.append({"type": "array",
                        "items": {"type": sorted(items) or ["string"]}})
    options.append({"type": "null"})
    return {"anyOf": options}


def _echo(items: list, fixed: dict) -> dict:
    """An object with the keys *items* carried, *fixed* ones as given."""
    properties = dict(fixed)
    for name in sorted({key for item in items for key in item}):
        if name in properties:
            continue
        carried = _carried([item.get(name) for item in items])
        if carried is not None:
            properties[name] = carried
    return {"type": "object", "properties": properties,
            "additionalProperties": False}


def window(sections: list) -> dict:
    """The full reply to one window: its sections, handed back."""
    media = [item for section in sections for key in ("tables", "figures")
             for item in (section.get(key) or ()) if isinstance(item, dict)]
    medium = {"type": "array", "items": _echo(media, {
        "id": TEXT, "caption": {"type": ["string", "null"]}})}
    section = _echo(sections, {
        "title": TEXT,
        # prose, or the entries of a bibliography
        "content": {"anyOf": [TEXT, {"type": "array", "items": TEXT}]},
        "tables": medium, "figures": medium,
        "_action": TEXT})
    return {"type": "object",
            "properties": {"sections": {"type": "array", "items": section}},
            "required": ["sections"], "additionalProperties": False}
