"""
replies.py: The reply each chat request asks for, as a JSON schema.

Every chat request names its reply as the grammar of the request (see
`docpipe.providers.grammar`). The prompts state the same shapes in words;
nothing here is a check, and what a reply says is verified afterwards.

The answer is a list of statements. Each one carries its own evidence, so
that each can be checked against the passage it cites on its own: a text
statement a `quote` and the `index` of its excerpt, a statement read off a
picture the `reading` and the `index` of the crop that was attached (or the
`block` of a crop the model asked for), a statement about a calculated value
the `run` that printed it and a `quote` of its inputs. There is no prose
answer beside them: what the reader is shown is made of the statements that
stood the check.

One request has no schema: the answer reformatted into a JSON shape the user
wrote into the task. That shape is the user's and only exists as prose.

Author: Felix Vossel
"""
TEXT = {"type": "string"}

BASES = ("text", "image", "computed")
# What the answer request is called: in the fault list of a turn, and in the
# log, a reader tells it from the small requests around it by this name.
ANSWER = "answer_reply"


def _only(name: str, **properties) -> tuple:
    required = [key for key, value in properties.items()
                if value.pop("_required", False)]
    return name, {"type": "object", "properties": properties,
                  "required": required, "additionalProperties": False}


CHOOSE = _only("choice_reply",
               answer={"type": ["string", "integer"], "_required": True})
PHRASE = _only("search_phrase_reply",
               phrase={"type": "string", "_required": True},
               repetition={"type": "boolean"})
CHUNK = _only("chunk_reply",
              found={"type": "boolean", "_required": True},
              answer=dict(TEXT), quote=dict(TEXT))
READOFF = _only("readoff_reply",
                reading={"type": "string", "_required": True},
                value={"type": ["number", "null"]},
                unit={"type": ["string", "null"]},
                confidence=dict(TEXT))
COMPARE = _only("comparison_reply",
                comparison={"type": "string", "_required": True})

_STATEMENT = {"type": "object",
              "properties": {"statement": TEXT,
                             "basis": {"enum": list(BASES)},
                             "index": {"type": "integer"},
                             "quote": TEXT, "reading": TEXT, "block": TEXT,
                             "run": {"type": "integer"}},
              "required": ["statement", "basis"],
              "additionalProperties": False}


def answer(actions: bool = True) -> tuple:
    """The answer, and with *actions* the two things the model may ask for
    instead of statements: a calculation, or a crop it was only pointed at.

    Without actions the statements are required: the last call of a turn has
    to answer. With them a reply is either statements or an action, and
    `needs` says which keys that is.
    """
    properties = {"statements": {"type": "array", "items": _STATEMENT},
                  "complete": {"type": "boolean"}}
    if actions:
        properties.update(action={"enum": ["python", "image"]},
                          code=dict(TEXT), id=dict(TEXT))
    return ANSWER, {"type": "object", "properties": properties,
                    "required": [] if actions else ["statements"],
                    "additionalProperties": False}


_KINDS = {"array": list, "string": str}


def needs(shape) -> tuple:
    """(key, kind, instead) the reader needs of a reply of this shape.

    *key* has to be in the object, as an instance of *kind*; *instead* is a
    key that stands in for it (the action of an answer that may ask for one),
    or "". Read from the schema, so the schema is the one place that says it.
    A reply with no shape has to be one object and nothing else: ("", object,
    "").
    """
    if shape is None:
        return "", object, ""
    schema = shape[1]
    properties = schema["properties"]
    required = schema.get("required") or []
    if required:
        key = required[0]
    elif "statements" in properties:
        key = "statements"                      # an action may come instead
    else:
        return "", object, ""
    wanted = properties[key].get("type")
    kind = _KINDS.get(wanted, object) if isinstance(wanted, str) else object
    return key, kind, "action" if "action" in properties else ""
