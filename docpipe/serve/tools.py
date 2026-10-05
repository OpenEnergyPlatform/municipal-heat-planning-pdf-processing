"""
tools.py: The questions the store answers for a program.

The HTTP API and the MCP server offer the same eight, described once here,
so a program that asks over one gets what a program that asks over the
other gets:

    list_documents, list_parameters   what the harvest has values of
    find_values, get_value            the values, each with what backs it
    get_states, get_coverage          what the harvest says about a parameter
                                      that has no value: unstated, exhausted,
                                      unbacked, never asked
    find_refusals                     the claims that were refused, and why
    search                            passages of the documents by word

A question the store cannot answer is one of three errors, so that a caller
can tell them apart: `BadRequest` (the question is malformed), `NotFound`
(a document or a parameter the harvest does not have) and `Unavailable`
(the search has no database or no word index behind it).

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from .passages import DEFAULT_LIMIT, NO_DATABASE, Unavailable
from .values import LEVELS, MAX_LIMIT, STATES, NotFound, Values  # noqa: F401

FIND_DEFAULT = 50
SEARCH_DEFAULT = DEFAULT_LIMIT


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


def _only(arguments: dict, known: set) -> None:
    unknown = sorted(set(arguments) - known)
    if unknown:
        raise BadRequest(f"unknown argument(s): {', '.join(unknown)} "
                         f"(known: {', '.join(sorted(known))})")


def _name(arguments: dict, name: str) -> Optional[str]:
    given = arguments.get(name)
    if given is not None and (not isinstance(given, str) or not given):
        raise BadRequest(f"{name} must be a name")
    return given


def find_values(store: Values, arguments: dict) -> dict:
    _only(arguments, {"document", "parameter", "level", "coordinates",
                      "text", "limit", "offset"})
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


def get_states(store: Values, arguments: dict) -> dict:
    _only(arguments, {"document", "parameter", "state", "limit", "offset"})
    state = arguments.get("state")
    if state is not None and state not in STATES:
        raise BadRequest(f"state must be one of {', '.join(STATES)}")
    return store.states(
        document=_name(arguments, "document"),
        parameter=_name(arguments, "parameter"), state=state,
        limit=_number(arguments, "limit", FIND_DEFAULT),
        offset=_number(arguments, "offset", 0))


def get_coverage(store: Values, arguments: dict) -> dict:
    _only(arguments, {"document", "parameter", "limit", "offset"})
    return store.coverage(
        document=_name(arguments, "document"),
        parameter=_name(arguments, "parameter"),
        limit=_number(arguments, "limit", FIND_DEFAULT),
        offset=_number(arguments, "offset", 0))


def find_refusals(store: Values, arguments: dict) -> dict:
    _only(arguments, {"document", "parameter", "limit", "offset"})
    return store.refusals(
        document=_name(arguments, "document"),
        parameter=_name(arguments, "parameter"),
        limit=_number(arguments, "limit", FIND_DEFAULT),
        offset=_number(arguments, "offset", 0))


def search(store: Values, arguments: dict) -> dict:
    # Whether there is a search at all comes first: a caller of a server
    # that has none should learn that, not that its question was wrong.
    passages = store.passages
    if passages is None:
        raise Unavailable(NO_DATABASE)
    if not passages.available:
        raise Unavailable(passages.why)
    _only(arguments, {"text", "document", "limit"})
    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        raise BadRequest("text is missing")
    try:
        return passages.search(text, document=_name(arguments, "document"),
                               limit=_number(arguments, "limit",
                                             SEARCH_DEFAULT))
    except ValueError as exc:
        raise BadRequest(str(exc)) from None


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
                       "open, see `reasons`). Every coordinate has its own "
                       "quote and state. Every argument narrows the "
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
    "get_states": {
        "description": "What the harvest says about a parameter in a "
                       "document, which is the answer when there is no "
                       "value. read: values were read. unstated: the "
                       "document was read and does not carry it. exhausted: "
                       "the run ended before the document was read "
                       "through, so nothing is known. unbacked: values were "
                       "offered and refused (find_refusals says why). "
                       "never_asked: the harvest has no question about it "
                       "for this document. not_recorded: the harvest "
                       "predates states. These are different answers; none "
                       "means 'not found'. Ask with a document, a "
                       "parameter, both, or neither.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document": {"type": "string",
                             "description": "exact document name"},
                "parameter": {"type": "string",
                              "description": "parameter name or label"},
                "state": {"type": "string", "enum": list(STATES),
                          "description": "only the pairs in this state"},
                "limit": {"type": "integer", "minimum": 0,
                          "maximum": MAX_LIMIT, "default": FIND_DEFAULT},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        },
    },
    "get_coverage": {
        "description": "Documents by parameters, each cell the state of "
                       "that pair (the words of get_states), and per "
                       "parameter how many documents are in each state. "
                       "Shows which plans say nothing about which "
                       "parameter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document": {"type": "string",
                             "description": "exact document name"},
                "parameter": {"type": "string",
                              "description": "parameter name or label"},
                "limit": {"type": "integer", "minimum": 0,
                          "maximum": MAX_LIMIT, "default": FIND_DEFAULT,
                          "description": "documents on the page"},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        },
    },
    "find_refusals": {
        "description": "The claims the harvest refused: the reason, the "
                       "passage it came from and the claim as the model "
                       "returned it. Explains an `unbacked` state. `failed` "
                       "is set where a request was not served and there was "
                       "no claim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document": {"type": "string",
                             "description": "exact document name"},
                "parameter": {"type": "string",
                              "description": "parameter name or label"},
                "limit": {"type": "integer", "minimum": 0,
                          "maximum": MAX_LIMIT, "default": FIND_DEFAULT},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        },
    },
    "search": {
        "description": "Passages of the documents that carry words of the "
                       "text, best first, each with its document, section "
                       "title, page and text. By word, not by meaning, and "
                       "not verified: a passage is not a value. Needs the "
                       "corpus database and its word index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "the words to look for"},
                "document": {"type": "string",
                             "description": "exact document name"},
                "limit": {"type": "integer", "minimum": 0,
                          "maximum": MAX_LIMIT, "default": SEARCH_DEFAULT},
            },
            "required": ["text"], "additionalProperties": False,
        },
    },
}


def described(store: Values) -> dict:
    """DESCRIPTIONS as this store can keep them. A search with no database
    or no word index behind it says so first in its description: it is
    listed, so that a caller sees that it exists, and not offered as
    working."""
    passages = store.passages
    if passages is not None and passages.available:
        return DESCRIPTIONS
    why = NO_DATABASE if passages is None else passages.why
    entry = dict(DESCRIPTIONS["search"])
    entry["description"] = f"NOT AVAILABLE: {why}. " + entry["description"]
    return {**DESCRIPTIONS, "search": entry}


def call(store: Values, name: str, arguments: Optional[dict]) -> dict:
    """Answer one of the eight by name."""
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
    if name == "get_states":
        return get_states(store, arguments)
    if name == "get_coverage":
        return get_coverage(store, arguments)
    if name == "find_refusals":
        return find_refusals(store, arguments)
    if name == "search":
        return search(store, arguments)
    raise BadRequest(f"unknown tool {name!r} (known: "
                     f"{', '.join(DESCRIPTIONS)})")
