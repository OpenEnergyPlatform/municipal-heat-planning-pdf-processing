"""
tools.py: The four questions the value store answers for a program.

The HTTP API and the MCP server offer the same four, described once here,
so a program that asks over one gets what a program that asks over the
other gets: which documents, which parameters, the values that match, and
one value with everything that backs it.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from .values import LEVELS, MAX_LIMIT, Values

FIND_DEFAULT = 50


class BadRequest(ValueError):
    """A question that cannot be asked that way."""


def list_documents(store: Values) -> dict:
    return {"documents": store.documents()}


def list_parameters(store: Values) -> dict:
    return {"parameters": store.parameters()}


def _number(arguments: dict, name: str, default: int) -> int:
    raw = arguments.get(name, default)
    if isinstance(raw, bool):
        raise BadRequest(f"{name} must be a whole number")
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} must be a whole number") from None
    if number < 0:
        raise BadRequest(f"{name} must not be negative")
    return number


def find_values(store: Values, arguments: dict) -> dict:
    known = {"document", "parameter", "level", "coordinates", "text",
             "limit", "offset"}
    unknown = sorted(set(arguments) - known)
    if unknown:
        raise BadRequest(f"unknown argument(s): {', '.join(unknown)} "
                         f"(known: {', '.join(sorted(known))})")
    coordinates = arguments.get("coordinates") or {}
    if not isinstance(coordinates, dict):
        raise BadRequest("coordinates must be an object of name -> value")
    level = arguments.get("level")
    if level is not None and level not in LEVELS:
        raise BadRequest(f"level must be one of {', '.join(LEVELS)}")
    return store.find(
        document=arguments.get("document"),
        parameter=arguments.get("parameter"), level=level,
        coordinates=coordinates, text=arguments.get("text"),
        limit=_number(arguments, "limit", FIND_DEFAULT),
        offset=_number(arguments, "offset", 0))


def get_value(store: Values, name: Optional[str]) -> dict:
    if not isinstance(name, str) or not name:
        raise BadRequest("id is missing")
    value = store.get(name)
    if value is None:
        raise KeyError(name)
    return value


# What each question is, for a program that reads descriptions (MCP) and
# for the API's own index page.
DESCRIPTIONS = {
    "list_documents": {
        "description": "The documents the harvest has values of, each with "
                       "its number of values and parameters.",
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
    "list_parameters": {
        "description": "The parameters the harvest has values of: label, "
                       "number of values and documents, units, and for each "
                       "coordinate what was read there and how often. Call "
                       "this first to see what can be asked for.",
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
    "find_values": {
        "description": "Values read from the documents, each with its "
                       "quote, its page and its trust level (A: stated in "
                       "the document's own text; B: read from a table or "
                       "figure image or a transcribed page; C: something is "
                       "open, see `reasons`). Every argument narrows the "
                       "result; none returns everything.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document": {"type": "string",
                             "description": "exact document name"},
                "parameter": {"type": "string",
                              "description": "parameter name or label"},
                "level": {"type": "string", "enum": list(LEVELS),
                          "description": "worst trust level still wanted"},
                "coordinates": {
                    "type": "object",
                    "description": "coordinate name -> the value or label "
                                   "read there, e.g. {\"year\": 2030}"},
                "text": {"type": "string",
                         "description": "words to look for in the quote and "
                                        "the wordings"},
                "limit": {"type": "integer", "minimum": 0,
                          "maximum": MAX_LIMIT, "default": FIND_DEFAULT},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        },
    },
    "get_value": {
        "description": "One value by its id, with everything that backs it.",
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"], "additionalProperties": False},
    },
}


def call(store: Values, name: str, arguments: Optional[dict]) -> dict:
    """Answer one of the four by name."""
    arguments = arguments or {}
    if not isinstance(arguments, dict):
        raise BadRequest("arguments must be an object")
    if name == "list_documents":
        return list_documents(store)
    if name == "list_parameters":
        return list_parameters(store)
    if name == "find_values":
        return find_values(store, arguments)
    if name == "get_value":
        return get_value(store, arguments.get("id"))
    raise BadRequest(f"unknown tool {name!r} (known: "
                     f"{', '.join(DESCRIPTIONS)})")
