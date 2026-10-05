"""
replies.py: The reply each extraction request asks for, as a JSON schema.

The prompts state these shapes in words. Here they are once more as schemas,
for an API that generates inside one: a hosted model is asked for JSON in no
other way, and a server of one's own can be (LLM_SCHEMA=all). The field
request has had its schema since the grammar was introduced for it
(`runner.field_response_format`); these are the other five.

Nothing here is a check. A schema says which keys a reply can have and what
kind of thing stands under each, as the prompt does. Every key the prompt
leaves optional is optional, a closed list is not turned into an enum, and
what a reply says is verified afterwards exactly as before.

Author: Felix Vossel
"""
from __future__ import annotations

from . import fields

TEXT = {"type": "string"}
TEXT_OR_NULL = {"type": ["string", "null"]}
NUMBER_OR_TEXT = {"type": ["number", "string"]}
LABELS = {"type": "array", "items": TEXT}
# The sandbox round of a harvest: an action in place of an answer.
ACTION = {"action": {"enum": ["python"]}, "code": TEXT}


def anchors() -> dict:
    return {"type": "object", "properties": {"anchors": LABELS},
            "required": ["anchors"], "additionalProperties": False}


def phrase() -> dict:
    return {"type": "object", "properties": {"phrase": TEXT},
            "required": ["phrase"], "additionalProperties": False}


def _answer(slot) -> dict:
    """What stands under a coordinate's own name."""
    if slot.kind == fields.NUMBER:
        return {"type": ["integer", "string", "null"]}
    return TEXT_OR_NULL


def frame(slots) -> dict:
    """One pair per row of the frame: each coordinate with its wording, its
    quote and the passage the quote is from."""
    pair: dict = {}
    for slot in slots:
        pair[slot.name] = _answer(slot)
        pair[f"{slot.name}_raw"] = TEXT_OR_NULL
        pair[f"{slot.name}_quote"] = TEXT_OR_NULL
        pair[f"{slot.name}_source"] = TEXT_OR_NULL
    return {"type": "object",
            "properties": {
                "pairs": {"type": "array",
                          "items": {"type": "object", "properties": pair,
                                    "additionalProperties": False}},
                "status": TEXT,
                "need_more": LABELS},
            "required": ["pairs"], "additionalProperties": False}


def review(slots) -> dict:
    """The fields of one stored value, read again: each under its own name
    with its wording and its quote; the value also with its unit."""
    said: dict = {}
    for slot in slots:
        if slot.name == fields.VALUE:
            said.update({"value": {"type": ["number", "string", "null"]},
                         "value_raw": TEXT_OR_NULL,
                         "value_quote": TEXT_OR_NULL,
                         "unit": TEXT_OR_NULL, "unit_raw": TEXT_OR_NULL})
            continue
        said[slot.name] = {"type": ["string", "integer", "number", "null"]}
        said[f"{slot.name}_raw"] = TEXT_OR_NULL
        said[f"{slot.name}_quote"] = TEXT_OR_NULL
    return {"type": "object", "properties": said,
            "additionalProperties": False}


def _coordinates(spec) -> dict:
    """The keys a whole tuple carries beside its value: the parameter, the
    unit and every axis any parameter of the spec has, each with its wording."""
    keys: dict = {"parameter": TEXT_OR_NULL, "unit": TEXT_OR_NULL}
    for parameter in spec.parameters:
        for name in parameter.axes:
            keys.setdefault(name, {"type": ["string", "integer", "null"]})
            keys.setdefault(f"{name}_raw", TEXT_OR_NULL)
    return keys


def rows(spec=None, *, whole: bool = False, sandbox: bool = True) -> dict:
    """The harvest reply: the values of the passages, or a sandbox action.

    *whole* is the contract in which a row carries its coordinates itself;
    otherwise a row is a value with its wording, its unit's wording and its
    quote, and the coordinates are asked per field afterwards.
    """
    shared: dict = {"source": TEXT, "unit_raw": TEXT_OR_NULL}
    if whole and spec is not None:
        shared.update(_coordinates(spec))
    row = {**shared,
           "value": NUMBER_OR_TEXT, "value_raw": TEXT_OR_NULL,
           "quote": TEXT, "computed": {"type": "boolean"}}
    reply = {
        "tuples": {"type": "array",
                   "items": {"type": "object", "properties": row,
                             "additionalProperties": False}},
        "defaults": {"type": "object", "properties": shared,
                     "additionalProperties": False},
        "status": TEXT,
        "need_more": LABELS,
    }
    if sandbox:
        reply.update(ACTION)
    return {"type": "object", "properties": reply,
            "additionalProperties": False}
