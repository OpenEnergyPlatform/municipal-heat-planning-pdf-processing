"""
replies.py: The reply each extraction request asks for, as a JSON schema.

The prompts state these shapes in words. Here they are once more as schemas,
for an API that generates inside one: a hosted model is asked for JSON in no
other way, and a server of one's own can be (LLM_SCHEMA=all).

Nothing here is a check. A schema says which keys a reply can have and what
kind of thing stands under each, as the prompt does. Every key the prompt
leaves optional is optional, a closed list is not turned into an enum, and
what a reply says is verified afterwards exactly as before. Every object
lists its keys in the order its prompt names them (owner decision
2026-11-04): a server that holds a reply to its schema has the model write
them in that order, so a key listed before one already written could no
longer come.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from . import fields

TEXT = {"type": "string"}
TEXT_OR_NULL = {"type": ["string", "null"]}
# The sandbox round of a harvest: an action in place of an answer.
ACTION = {"action": {"enum": ["python"]}, "code": TEXT}


def phrase() -> dict:
    return {"type": "object", "properties": {"phrase": TEXT},
            "required": ["phrase"], "additionalProperties": False}


def review(slots) -> dict:
    """The fields of one stored value, read again: each under its own name
    with its wording and its quote; the value also with its unit."""
    said: dict = {}
    for slot in slots:
        if slot.name == fields.VALUE:
            said.update({"value": {"type": ["number", "string", "null"]},
                         "value_raw": TEXT_OR_NULL,
                         "unit": TEXT_OR_NULL, "unit_raw": TEXT_OR_NULL,
                         "value_quote": TEXT_OR_NULL})
            continue
        said[slot.name] = {"type": ["string", "integer", "number", "null"]}
        said[f"{slot.name}_raw"] = TEXT_OR_NULL
        said[f"{slot.name}_quote"] = TEXT_OR_NULL
    return {"type": "object", "properties": said,
            "additionalProperties": False}


def compute(labels: list, *, more: Optional[dict] = None,
            take: Optional[dict] = None, quote: bool = False) -> dict:
    """The reply of a compute request: a sandbox action, or the number with
    the numbers it came from. *more* is what it may ask of the plan, *take*
    a number it may take from a passage, *quote* whether the answer quotes
    what the number it chose is."""
    properties = {**ACTION, "value": {"type": ["number", "null"]},
                  "used": {"type": "array", "items": {"enum": list(labels)}}}
    if more is not None:
        properties["more"] = more
    if take is not None:
        properties["take"] = take
    if quote:
        properties["quote"] = TEXT
    return {"type": "object", "properties": properties,
            "additionalProperties": False}


