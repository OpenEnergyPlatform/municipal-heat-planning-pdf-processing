"""
schema.py: One reply schema, in the dialect a hosted API generates in.

A stage writes the reply it asks for as plain JSON Schema: keys that may be
left out, objects keyed by a row label. An API that generates inside a schema
takes less than that, and each takes something else. `strict` rewrites a
schema into what one of them takes and hands back the way home, so the stage
reads the reply in the shape it asked for:

    an object keyed per request  a list of {"key", "value"}; read as the object
    bounds, patterns, formats    dropped: generation never checked them
    a key that may be left out   ALL_REQUIRED: required and nullable, and a
                                 null reads as left out
                                 OPTIONAL: left as it is, and a null it could
                                 also say is taken away, since leaving the key
                                 out says the same

ALL_REQUIRED is the dialect of the API that wants every property required.
OPTIONAL is for the ones that take optional properties but count them:
`budget` is (optional properties, properties with alternatives) the API
compiles, and what is over the first is moved into the second by making it
required and nullable. A schema that fits neither is refused with its counts.

The way home repairs nothing. It is applied to a reply the API generated
inside the rewritten schema and undoes the rewriting, key for key. A reply
that is not JSON is handed on as it came, and the stage that asked says what
is wrong with it.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Callable, Optional

# What generation inside a schema does not take, on at least one of the APIs.
DROPPED = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
           "multipleOf", "minLength", "maxLength", "pattern", "format",
           "minItems", "maxItems", "uniqueItems", "minProperties",
           "maxProperties", "default", "examples", "title", "$schema", "$id")
ENTRY_KEY = "key"
ENTRY_VALUE = "value"
ALL_REQUIRED = "all-required"
OPTIONAL = "optional"
# The keywords that belong to one type and not to the null beside it.
OF_ONE_TYPE = ("properties", "required", "additionalProperties", "items",
               "enum")


class SchemaError(ValueError):
    """A reply schema this API cannot generate in."""


def strict(schema: dict, dialect: str = ALL_REQUIRED,
           budget: Optional[tuple] = None) -> tuple:
    """(the schema in the dialect, decode(reply) back to its shape)."""
    state = {"dialect": dialect, "optional": 0, "unions": 0, "spare": None}
    if dialect == OPTIONAL and budget is not None:
        optional, unions = _count(schema)
        state["spare"] = max(0, optional - budget[0])
    rewritten = _strict(schema, "reply", state)
    if budget is not None:
        optional, unions = complexity(rewritten)
        if optional > budget[0] or unions > budget[1]:
            raise SchemaError(
                f"{optional} optional properties and {unions} properties "
                f"with alternatives; this API compiles {budget[0]} and "
                f"{budget[1]}")

    def decode(value):
        return _decode(value, schema)

    return rewritten, decode


def _json_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _branches(node: dict):
    """The alternatives of a node, however it spells them, or None."""
    for word in ("anyOf", "oneOf"):
        if isinstance(node.get(word), list):
            return node[word]
    if isinstance(node.get("type"), list):
        rest = {k: v for k, v in node.items() if k != "type"}
        bare = {k: v for k, v in rest.items() if k not in OF_ONE_TYPE}
        return [{**(bare if kind == "null" else rest), "type": kind}
                for kind in node["type"]]
    return None


def _keyed(node: dict) -> bool:
    """An object whose keys are the request's own: row labels, section ids."""
    return (isinstance(node.get("additionalProperties"), dict)
            and not node.get("properties"))


def _is_object(node: dict) -> bool:
    return node.get("type") == "object" or "properties" in node


def _is_null(node) -> bool:
    return isinstance(node, dict) and node.get("type") == "null"


def _nullable(node: dict) -> dict:
    options = node.get("anyOf")
    if _is_null(node):
        return node
    if isinstance(options, list):
        if any(_is_null(option) for option in options):
            return node
        return {**node, "anyOf": [*options, {"type": "null"}]}
    return {"anyOf": [node, {"type": "null"}]}


def _without_null(node: dict) -> dict:
    """The schema without the null it could also say; itself if that is all
    it says."""
    options = node.get("anyOf")
    if not isinstance(options, list):
        return node
    rest = [option for option in options if not _is_null(option)]
    if not rest or len(rest) == len(options):
        return node
    if len(rest) == 1:
        kept = {k: v for k, v in node.items() if k != "anyOf"}
        return {**rest[0], **kept}
    return {**node, "anyOf": rest}


def _strict(node, where: str, state: dict):
    if not isinstance(node, dict):
        raise SchemaError(f"{where}: a schema is an object, not {node!r}")
    out = {k: v for k, v in node.items() if k not in DROPPED}
    options = _branches(out)
    if options is not None:
        # A list of types carried its other keywords into each alternative.
        typed = "anyOf" not in out and "oneOf" not in out
        beside = set(out) - {"anyOf", "oneOf", "type", "description"}
        if beside and not typed:
            raise SchemaError(f"{where}: alternatives beside other keywords "
                              f"({', '.join(sorted(beside))})")
        if typed:
            options = [{k: v for k, v in option.items() if k != "description"}
                       for option in options]
        if any(_keyed(option) for option in options) and any(
                option.get("type") == "array" for option in options):
            raise SchemaError(f"{where}: an object keyed per request and a "
                              f"list among the alternatives cannot be told "
                              f"apart in a reply")
        kept = ({"description": out["description"]}
                if "description" in out else {})
        kept["anyOf"] = [_strict(option, f"{where}|{i}", state)
                         for i, option in enumerate(options)]
        return kept
    if "enum" in out and "type" not in out:
        kinds = {_json_type(v) for v in out["enum"]}
        if len(kinds) == 1:
            out["type"] = kinds.pop()
    if _keyed(out):
        entry = {"type": "object",
                 "properties": {
                     ENTRY_KEY: {"type": "string"},
                     ENTRY_VALUE: _strict(out["additionalProperties"],
                                          f"{where}.*", state)},
                 "required": [ENTRY_KEY, ENTRY_VALUE],
                 "additionalProperties": False}
        listed = {"type": "array", "items": entry}
        if "description" in out:
            listed["description"] = out["description"]
        return listed
    if _is_object(out):
        properties = out.get("properties")
        if isinstance(out.get("additionalProperties"), dict):
            raise SchemaError(f"{where}: an object with named keys and "
                              f"keys of its own cannot be generated in")
        if not properties:
            raise SchemaError(f"{where}: an object of any shape cannot be "
                              f"generated in")
        required = [name for name in (out.get("required") or ())
                    if name in properties]
        rewritten = {}
        for name, inner in properties.items():
            inner = _strict(inner, f"{where}.{name}", state)
            if name in required:
                rewritten[name] = inner
            elif state["dialect"] == ALL_REQUIRED:
                rewritten[name] = _nullable(inner)
                required.append(name)
            elif state["spare"]:
                # over the API's count of optional keys: this one is asked
                # for always and may say null
                state["spare"] -= 1
                rewritten[name] = _nullable(inner)
                required.append(name)
            else:
                rewritten[name] = _without_null(inner)
        out.update(type="object", properties=rewritten, required=required,
                   additionalProperties=False)
        return out
    if out.get("type") == "array":
        if "items" not in out:
            raise SchemaError(f"{where}: a list of anything cannot be "
                              f"generated in")
        out["items"] = _strict(out["items"], f"{where}[]", state)
    return out


def _walk(node):
    """Every schema of a schema: itself, its properties, items, alternatives."""
    yield node
    for inner in (node.get("properties") or {}).values():
        yield from _walk(inner)
    for word in ("items", "additionalProperties"):
        if isinstance(node.get(word), dict):
            yield from _walk(node[word])
    for word in ("anyOf", "oneOf", "allOf"):
        for inner in node.get(word) or ():
            yield from _walk(inner)


def _count(schema: dict) -> tuple:
    return complexity(schema)


def complexity(schema: dict) -> tuple:
    """(optional properties, properties with alternatives) of a schema: the
    two numbers an API that compiles a schema counts."""
    optional = unions = 0
    for node in _walk(schema):
        properties = node.get("properties") or {}
        required = set(node.get("required") or ())
        optional += sum(1 for name in properties if name not in required)
        unions += sum(1 for inner in properties.values()
                      if _branches(inner) is not None)
        items = node.get("items")
        if isinstance(items, dict) and _branches(items) is not None:
            unions += 1
    return optional, unions


def _fits(value, node) -> bool:
    """Whether a reply value can have come from this alternative."""
    if not isinstance(node, dict):
        return True
    if "const" in node:
        return value == node["const"]
    if "enum" in node:
        return value in node["enum"]
    kind = node.get("type")
    if _keyed(node):
        return isinstance(value, list)
    if kind == "object" or "properties" in node:
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return kind is None or _json_type(value) == kind


def _allows_null(node) -> bool:
    if not isinstance(node, dict):
        return True
    options = _branches(node)
    if options is not None:
        return any(_allows_null(option) for option in options)
    if "enum" in node:
        return None in node["enum"]
    return node.get("type") in (None, "null") and "properties" not in node


def _decode(value, node):
    if not isinstance(node, dict):
        return value
    options = _branches(node)
    if options is not None:
        for option in options:
            if _fits(value, option):
                return _decode(value, option)
        return value
    if _keyed(node):
        if not isinstance(value, list):
            return value
        inner = node["additionalProperties"]
        keys = [str(entry[ENTRY_KEY])
                if isinstance(entry, dict) and ENTRY_KEY in entry else None
                for entry in value]
        if None in keys or len(set(keys)) != len(keys):
            # An entry without its key, or one key twice: this is not the
            # object the stage asked for, and choosing among the entries
            # would be a repair. It stays the list it came as, which the
            # stage does not read as an answer.
            return value
        return {key: _decode(entry.get(ENTRY_VALUE), inner)
                for key, entry in zip(keys, value)}
    if _is_object(node) and isinstance(value, dict):
        properties = node.get("properties") or {}
        required = set(node.get("required") or ())
        out = {}
        for name, item in value.items():
            inner = properties.get(name)
            if (item is None and name not in required
                    and not _allows_null(inner)):
                continue                    # null: the key was left out
            out[name] = _decode(item, inner)
        return out
    if node.get("type") == "array" and isinstance(value, list):
        return [_decode(item, node.get("items")) for item in value]
    return value


def decoder_text(decode: Callable, text: str) -> str:
    """The reply text in the shape the stage asked for.

    Text that is not one JSON value is handed on untouched: a reply the API
    cut off stays cut off, and the stage that reads it names the fault.
    """
    import json
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return text
    return json.dumps(decode(value), ensure_ascii=False)
